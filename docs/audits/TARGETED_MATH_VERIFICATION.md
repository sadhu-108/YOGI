# YOGI — Targeted Mathematical Verification

**Date:** 2026-10-15  
**Audit Target:** [`D:\Yogi Investing\My_version`](file:///D:/Yogi%20Investing/My_version/)  
**Prototype Reference:** [`D:\Yogi Investing\yogi_engine\yogi_engine`](file:///D:/Yogi%20Investing/yogi_engine/yogi_engine/)  
**Audit Mode:** READ-ONLY TARGETED VERIFICATION (Zero Code Modifications)  
**Governing Documents:** [`AGENTS.md`](file:///D:/Yogi%20Investing/My_version/AGENTS.md), [`docs/architecture.md`](file:///D:/Yogi%20Investing/My_version/docs/architecture.md), [`docs/decisions.md`](file:///D:/Yogi%20Investing/My_version/docs/decisions.md)

---

## Executive Summary & Dispositions

| # | Topic | Classification | Disposition | Severity | Affected Scope |
|---|---|---|---|---|---|
| **1** | **Half-Year (`H`) Timeframe Semantics** | Unresolved Requirement / Prototype Parity Drift from Spec | **MENTOR DECISION REQUIRED** | Medium | Timeframe resampling, H candle patterns, H bands, H EMAs, `H_CUR`, `H_P1`, and Golden Fixtures |
| **2** | **CAGR Edge-Case Safety** | Confirmed Defect | **FIX REQUIRED** | Medium | `cagr_trailing()` crashes with `TypeError` on Python float negative prices, emits `NaN` instead of `None` on numpy float, and crashes on $n \le 0$ |
| **3** | **ATR Band Orientation** | Verified Correct / Intentional Difference | **KEEP** | Low | Presentation overlay in Cockpit charting and `calculate_atr_bands()` |

---

## 1. Half-Year (`H`) Timeframe Semantics

### 1.1 Findings & Implementation Analysis
- **YOGI Implementation:**  
  - Resampling Rule: [`src/yogi/timeframe/engine.py:22`](file:///D:/Yogi%20Investing/My_version/src/yogi/timeframe/engine.py#L22): `"H": "2QE"`
  - Half-Block Calculation: [`src/yogi/calculation/trend/calculator.py:197`](file:///D:/Yogi%20Investing/My_version/src/yogi/calculation/trend/calculator.py#L197): `hb = c.resample("2QE").last().dropna()`
- **Prototype Implementation:**  
  - Resampling Rule: `config.py:19`: `TF_RULE = {"H":"2QE"}`
  - Half-Block Calculation: `yogi/core_math/formulas.py:183`: `bars = close.resample("2QE").last().dropna()`

### 1.2 Exact Period Boundaries & Labels Produced by `2QE`
In pandas, `"2QE"` is an alias for `"2QE-DEC"` (`QuarterEnd(n=2, startingMonth=12)`). When resampling a continuous daily time-series, pandas anchors to December and groups in increments of two calendar quarters:

| Bin Label (Timestamp) | Underlying Date Range Included | Calendar Quarters Included | Days in Bin |
|---|---|---|---|
| `YYYY-03-31` | October 1 ($Y-1$) to March 31 ($Y$) | Q4 ($Y-1$) + Q1 ($Y$) | ~182 days |
| `YYYY-09-30` | April 1 ($Y$) to September 30 ($Y$) | Q2 ($Y$) + Q3 ($Y$) | ~183 days |

**Crucial Finding:** `"2QE"` **never** produces boundaries on June 30 or December 31.
Instead, it splits the year into:
1. A **Winter/Spring block** spanning across the calendar year boundary (Oct 1 to Mar 31).
2. A **Summer/Monsoon block** (Apr 1 to Sep 30).

### 1.3 Divergence Between Prototype Code and Prototype Specification
In prototype `yogi/core_math/formulas.py:177-181`, the author explicitly documented the intended meaning:
```python
def half_block(close, bars=None):
    """Halves named by calendar half: Jan-Jun = H1, Jul-Dec = H2.
    In August 2026 the current half is H2, before it H1 (of 2026), then H2 (2025).
    Stable aliases: H_CUR, H_P1, H_P2.
    """
```
However, the code in `formulas.py:193-200` assigned keys dynamically by calendar month:
```python
keys = []
for i in range(3):
    d = last_dt - pd.DateOffset(months=6 * i)
    k = "H1" if d.month <= 6 else "H2"
    keys.append(k)
    if k not in out or out[k] is None:
        out[k] = vals[i]
```
Where `vals = [r(cur, bars.iloc[-2]), r(bars.iloc[-2], bars.iloc[-3]), r(bars.iloc[-3], bars.iloc[-4])]`.

**The Semantic Disconnect:**
For a stock evaluated in August 2026 (`last_dt = 2026-08-13`):
- `last_dt.month = 8` ($\ge 7$) $\implies$ label assigned is `"H2"`.
- But `bars.iloc[-2]` is the bar ending **`2026-03-31`**!
- Therefore, `H_CUR` calculates the return from `2026-03-31` to `2026-08-13` (approx 4.5 months, April to August), **not** the return from June 30 (which would be calendar H2-to-date, ~1.5 months).
- Similarly, `H_P1` calculates the return between `2025-09-30` and `2026-03-31` (winter half), but gets labeled as `"H1"` (implying Jan 1 – Jun 30).

### 1.4 Reproducible Example
```python
import pandas as pd

dates = pd.date_range("2025-01-01", "2026-08-13", freq="D")
s = pd.Series(range(len(dates)), index=dates)

# Resampling via 2QE
res = s.resample("2QE").last()
print(res.index.date)
# Output: [datetime.date(2025, 3, 31), datetime.date(2025, 9, 30), datetime.date(2026, 3, 31), datetime.date(2026, 9, 30)]
```

### 1.5 Consequences of Changing the Rule
If YOGI alters `"2QE"` to enforce strict calendar halves (Jan 1 – Jun 30 as H1, Jul 1 – Dec 31 as H2):
1. **Golden Fixtures Breakdown:**
   In [`tests/fixtures/expected.json`](file:///D:/Yogi%20Investing/My_version/tests/fixtures/expected.json), all 5 benchmark stocks (`MANYAVAR`, `SBCL`, `EMIL`, `MOREPENLAB`, `SHILPAMED`) have locked `H_CUR`, `H_P1`, and `EMA_H` metrics computed with `2QE`. Every stock would fail the golden regression test suite.
2. **Candlestick Theory Impact:**
   All 34 half-year candle patterns (`CH_O`, `CH_H`, `CH_L`, `CH_C`, `CH_ENGULFING`, `CH_HAMMER`, etc.) in `calculate_candle_fields()` would be synthesized from different date boundaries.
3. **Bands Pillar Impact:**
   `H_BASIS`, `H_UP`, `H_LO`, `H_POS`, `H_STATE`, and `H_BD` would change. Furthermore, `N_ABOVE` and `N_BELOW` (counts across D, W, M, Q, H, Y) would shift whenever the H band status changes.
4. **EMA 3/5 Status Impact:**
   `EMA_H` would evaluate moving averages on different bar closes.

### 1.6 Decision Required from Mentor
* **Option A (Prototype Parity - Recommended):**  
  Keep `"2QE"` (boundaries ending Mar 31 & Sep 30). Maintain 100% numerical parity with prototype outputs and existing golden regression fixtures. Update documentation to clearly state that the "H" timeframe represents 2-quarter cycles ending Mar/Sep.
* **Option B (Calendar Correctness):**  
  Implement custom calendar-half binning (Jan 1 – Jun 30, Jul 1 – Dec 31). Re-generate `tests/fixtures/expected.json` and approve new baseline numbers.

**Disposition:** **MENTOR DECISION REQUIRED**

---

## 2. CAGR Edge-Case Safety

### 2.1 Findings & Implementation Analysis
- **Implementation:** [`src/yogi/calculation/trend/calculator.py:258-272`](file:///D:/Yogi%20Investing/My_version/src/yogi/calculation/trend/calculator.py#L258-L272)
```python
def cagr_trailing(close: pd.Series, n: int) -> Optional[float]:
    """Calculate annualized Compound Annual Growth Rate over trailing n years."""
    c = close.dropna()
    if len(c) == 0:
        return None
    latest = c.index[-1]
    target = latest - pd.DateOffset(years=n)
    past = c[c.index <= target]
    if len(past) == 0:
        return None
    start = past.iloc[-1]
    if start <= 0:
        return None
    return float(((c.iloc[-1] / start) ** (1.0 / n) - 1.0) * 100.0)
```

### 2.2 Trace of Edge-Case Behaviors & Defects

1. **Negative Ending Price (`c.iloc[-1] < 0`) [CONFIRMED DEFECT]:**
   - If `c` has Python `float` or `object` dtype:
     `(negative_end / start) ** (1.0 / n)` produces a Python `complex` number (e.g. `(-0.5) ** (1/3) == (0.397 + 0.687j)`). Calling `float(complex)` raises an unhandled exception:  
     `TypeError: float() argument must be a string or a real number, not 'complex'`
   - If `c` has `numpy.float64` dtype:
     The scalar power emits `RuntimeWarning: invalid value encountered in scalar power` and returns `float('nan')` instead of the required `None`. Returning `NaN` causes JSON serialization failures in API schemas.
2. **Zero Ending Price (`c.iloc[-1] == 0`):**
   - Evaluates to `float((0.0 - 1.0) * 100.0) == -100.0`. Valid mathematically as a 100% wipeout, but requires clear policy on whether delisted/zero price ticks should be emitted as `-100.0` or `None`.
3. **Non-Finite Values (`np.inf`, `-np.inf`):**
   - `close.dropna()` filters `np.nan`, but does **not** drop `inf`. If `c.iloc[-1]` is `+inf`, `cagr_trailing` returns `inf`. In standard JSON (RFC 8259), `Infinity` is invalid.
4. **Invalid Duration ($n \le 0$):**
   - If $n \le 0$, `1.0 / n` raises `ZeroDivisionError: division by zero`.
5. **Valid Positive Equity Prices:**
   - Formula remains 100% mathematically correct and identical to prototype for all valid equity price series.

### 2.3 Minimal Reproducible Example
```python
import pandas as pd
from yogi.calculation.trend.calculator import cagr_trailing

# Scenario A: Negative ending price with Python floats
dates = pd.to_datetime(["2021-01-01", "2024-01-01"])
s_obj = pd.Series([float(100.0), float(-50.0)], index=dates, dtype=object)
try:
    cagr_trailing(s_obj, 3)
except TypeError as e:
    print("Defect 1 Confirmed:", e)
    # Output: TypeError: float() argument must be a string or a real number, not 'complex'

# Scenario B: n = 0
s_valid = pd.Series([100.0, 200.0], index=dates)
try:
    cagr_trailing(s_valid, 0)
except ZeroDivisionError as e:
    print("Defect 2 Confirmed:", e)
    # Output: ZeroDivisionError: division by zero
```

### 2.4 Required Guard Fix (No Formula Change for Valid Positive Prices)
```python
def cagr_trailing(close: pd.Series, n: int) -> Optional[float]:
    if close is None or n <= 0:
        return None
    c = close.dropna()
    if len(c) == 0:
        return None
    latest = c.index[-1]
    target = latest - pd.DateOffset(years=n)
    past = c[c.index <= target]
    if len(past) == 0:
        return None
    start = past.iloc[-1]
    end = c.iloc[-1]
    # Guard against non-positive and non-finite prices
    if not (np.isfinite(start) and np.isfinite(end)):
        return None
    if start <= 0 or end <= 0:
        return None
    val = ((end / start) ** (1.0 / n) - 1.0) * 100.0
    return float(val) if np.isfinite(val) else None
```

**Classification:** **CONFIRMED DEFECT**  
**Disposition:** **FIX REQUIRED** (during next code-edit turn)

---

## 3. ATR Band Orientation

### 3.1 Findings & Formula Comparison
- **Prototype Formula:** [`yogi/api/routes.py:137-138`](file:///D:/Yogi%20Investing/yogi_engine/yogi_engine/yogi/api/routes.py#L137-L138):
  ```python
  atr = tr.rolling(14).mean()
  stUp, stDn = close - 2 * atr, close + 2 * atr
  ```
- **Prototype UI:** [`web/index.html:1572-1573`](file:///D:/Yogi%20Investing/yogi_engine/yogi_engine/web/index.html#L1572-L1573):
  ```javascript
  if(chk('i_st')&&d.stUp){
      _chart.addLineSeries({..., color:'#49b6a8'}).setData(d.stUp); // #49b6a8 = teal/green
      _chart.addLineSeries({..., color:'#d08b5b'}).setData(d.stDn); // #d08b5b = orange/red
  }
  ```
- **YOGI Implementation:** [`src/yogi/calculation/bands/calculator.py:412-448`](file:///D:/Yogi%20Investing/My_version/src/yogi/calculation/bands/calculator.py#L412-L448):
  ```python
  def calculate_atr_bands(high, low, close, period=14, multiplier=2.0) -> ATRBandsResult:
      ...
      upper = c + multiplier * atr
      lower = c - multiplier * atr
  ```

### 3.2 Root Cause of the Prototype Discrepancy
The prototype author borrowed notation from **SuperTrend (`st`)**:
- In SuperTrend, a bullish trend has a support floor *below* price (`close - multiplier * ATR`), colored green (`#49b6a8`).
- A bearish trend has a resistance ceiling *above* price (`close + multiplier * ATR`), colored orange/red (`#d08b5b`).
- The prototype labeled the checkbox `i_st: "ATR bands"`, but named the variables `stUp` and `stDn`.
- As a consequence, `stUp` was mathematically the lower boundary ($Close - 2\text{ATR}$), and `stDn` was the upper boundary ($Close + 2\text{ATR}$).

### 3.3 YOGI Architecture & Consumer Verification
The audit traced all consumers and tests of `calculate_atr_bands` across YOGI:
1. **Contract/DTO:** [`src/yogi/calculation/bands/calculator.py:401`](file:///D:/Yogi%20Investing/My_version/src/yogi/calculation/bands/calculator.py#L401) defines `ATRBandsResult(upper, lower, atr, last_upper, last_lower, last_atr)`.
2. **Chart Data Service:** [`src/yogi/cockpit/charting.py:469-485`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/charting.py#L469-L485) directly routes `atr_res.upper` to `ATRBandsSeriesOut.upper` and `atr_res.lower` to `ATRBandsSeriesOut.lower`.
3. **Cockpit Frontend:** [`src/yogi/cockpit/static/js/chart.js:230-243, 595-600`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/static/js/chart.js#L230-L243) explicitly binds:
   - `this.atrUpper` (title: `'ATR Upper'`) to `d.atr_bands.upper` ($Close + 2\text{ATR}$).
   - `this.atrLower` (title: `'ATR Lower'`) to `d.atr_bands.lower` ($Close - 2\text{ATR}$).
4. **Independent Test Verification:**
   [`tests/calculation/test_price_volatility_indicators.py:170-183`](file:///D:/Yogi%20Investing/My_version/tests/calculation/test_price_volatility_indicators.py#L170-L183) independently verifies first-principles behavior:
   ```python
   highs, lows, closes = [105.0] * 20, [95.0] * 20, [100.0] * 20
   res = calculate_atr_bands(highs, lows, closes, period=14, multiplier=2.0)
   assert res.last_atr == pytest.approx(10.0)
   assert res.last_upper == pytest.approx(120.0)  # 100 + 2 * 10
   assert res.last_lower == pytest.approx(80.0)   # 100 - 2 * 10
   ```
   The test asserts independent numeric truth ($120.0$ and $80.0$) rather than tautologically mirroring the code.

**Conclusion:** YOGI's implementation is semantically consistent, mathematically sound, correctly labeled across all layers, and free of consumer swaps.

**Classification:** **VERIFIED CORRECT / INTENTIONAL CORRECTION**  
**Disposition:** **KEEP**

---

## 4. Focused Offline Test Results

The focused verification test suite was executed offline:
```powershell
pytest tests/calculation/test_trend.py tests/calculation/test_price_volatility_indicators.py tests/cockpit/test_batch_3b_indicators.py tests/regression/test_golden_calculations.py
```
**Output:**
```text
============================== 62 passed in 9.08s ==============================
- tests/calculation/test_trend.py: 16 passed
- tests/calculation/test_price_volatility_indicators.py: 15 passed
- tests/cockpit/test_batch_3b_indicators.py: 26 passed
- tests/regression/test_golden_calculations.py: 5 passed (0.000000 numerical drift)
```

---

## 5. Summary of Actions & Mentor Decisions

1. **Point 1 (Half-Year Semantics):** Await mentor decision on whether to **KEEP** `"2QE"` (prototype parity) or **UPDATE** to calendar halves (Jan-Jun, Jul-Dec).
2. **Point 2 (CAGR Edge Cases):** A **FIX** is prepared and ready to apply to `src/yogi/calculation/trend/calculator.py` to prevent crashes on negative prices and invalid inputs.
3. **Point 3 (ATR Bands):** **KEEP** current implementation as-is.
