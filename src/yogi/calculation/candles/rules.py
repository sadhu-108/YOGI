"""Default threshold rules for Candlestick Theory / Pattern Engine.

Preserves exact numerical thresholds from prototype yogi/theories/candle_rules.py.
"""

from typing import Mapping

DEFAULT_CANDLE_RULES: Mapping[str, float] = {
    "DOJI_body_pct_max": 10.0,       # body smaller than this % of range = doji
    "MARUBOZU_body_pct_min": 90.0,   # body bigger than this % of range = marubozu
    "HAMMER_dnwick_pct_min": 60.0,   # lower wick at least this % of range
    "HAMMER_upwick_pct_max": 15.0,   # upper wick no more than this % of range
    "SHOOTSTAR_upwick_pct_min": 60.0,# upper wick at least this % of range
    "SHOOTSTAR_dnwick_pct_max": 15.0,# lower wick no more than this % of range
    "CLOSE_STRONG_pct": 80.0,        # closed above this % of range = strong close
    "CLOSE_WEAK_pct": 20.0,          # closed below this % of range = weak close
    "VOL_SPIKE_x": 2.0,              # volume this many times the 20-bar average
    "BIG_RANGE_pct": 5.0,            # range bigger than this % of low = big bar
    "ENGULF_require_full_body": 1.0, # 1 = body must fully cover previous body, 0 = range only
}
