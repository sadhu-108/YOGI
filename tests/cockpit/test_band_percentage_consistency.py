"""Tests for strict band percentage consistency across UI, API, storage, and calculation boundaries.

Verifies:
1. User-entered percentage (e.g. 15%) is converted to fraction (0.15) at the boundary,
   and raw percentage numbers (> 1.0) are strictly rejected by the API schema.
2. Displayed value correctly converts stored fraction (0.15) to percentage (15.0%).
3. A 15% band is not accidentally interpreted as 0.15% or 1500% anywhere in calculations,
   envelopes, audit logs, or presentation DTOs.
4. Default band for every unassigned stock resolves to 0.0 (0.0%).
5. Existing manually assigned bands retain their intended fraction/percentage meaning across reloads.
6. Band calculations and envelope mathematics remain completely unchanged.
"""

from datetime import datetime
from pathlib import Path
import tempfile
import pytest
from pydantic import ValidationError

from yogi.calculation.bands import (
    BandEnvelopeResult,
    BandsCalculator,
    band_state,
    calculate_band_envelope,
)
from yogi.cockpit.router import get_band_log_all, get_band_log_symbol, update_band
from yogi.cockpit.schemas import (
    BandAuditItemOut,
    BandLogResponseOut,
    BandUpdateIn,
    BandsResponseOut,
    TimeframeRowOut,
)
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import BAND_TIMEFRAMES, BandAuditEntry
from yogi.storage.bands import CsvBandsRepository


@pytest.fixture
def temp_repo(tmp_path: Path) -> CsvBandsRepository:
    return CsvBandsRepository(data_dir=tmp_path)


@pytest.fixture
def app_state(temp_repo: CsvBandsRepository) -> AppState:
    config = EngineConfig(provider="yfinance", bands_repository="csv")
    return AppState(
        bands_repo=temp_repo,
        config=config,
        initial_dataset={"TEST_STOCK": {"symbol": "TEST_STOCK", "price": 100.0}},
    )


def test_user_entered_percentage_conversion_and_schema_guard():
    """Verify 15% is converted to 0.15 fraction, and raw percentages > 1.0 are rejected."""
    # When user enters 15% in UI, frontend divides by 100 to send 0.15
    user_input_pct = 15.0
    payload_fraction = user_input_pct / 100.0
    assert payload_fraction == 0.15

    # Valid fraction is accepted by BandUpdateIn schema
    valid_req = BandUpdateIn(timeframe="D", value=payload_fraction)
    assert valid_req.value == 0.15

    # If raw percentage number 15.0 is mistakenly passed without / 100, schema rejects it
    with pytest.raises(ValidationError):
        BandUpdateIn(timeframe="D", value=15.0)


def test_fifteen_percent_envelope_and_calculation_math():
    """Verify 15% band produces exact 15% bounds and is not confused with 0.15% or 1500%."""
    # 40 bars at price 100.0 -> basis is 100.0
    closes = [100.0] * 40

    # 15% band fraction is 0.15
    frac_15 = 0.15
    envelope = calculate_band_envelope(closes, band_frac=frac_15, basis_window=20)
    assert envelope.last_basis == 100.0
    # Upper must be 100 * (1 + 0.15) = 115.0, Lower must be 100 * (1 - 0.15) = 85.0
    assert round(envelope.last_upper, 2) == 115.0
    assert round(envelope.last_lower, 2) == 85.0

    # Guard against 1500% (if frac were 15.0: upper would be 1600.0)
    assert envelope.last_upper != 1600.0

    # Guard against 0.15% (if frac were 0.0015: upper would be 100.15)
    assert envelope.last_upper != 100.15

    # State checks: 110.0 is inside the 15% band (85.0 to 115.0)
    state_in = band_state([100.0] * 39 + [110.0], band_frac=frac_15, basis_window=20)
    assert state_in["state"] == "IN"
    assert state_in["bd"] == 0.0

    # 120.0 is above the 15% band: 20-bar basis becomes 101.0, upper becomes 101.0 * 1.15 = 116.15
    state_above = band_state([100.0] * 39 + [120.0], band_frac=frac_15, basis_window=20)
    assert state_above["state"] == "ABOVE"
    assert state_above["bd"] == round((120.0 / (101.0 * 1.15) - 1.0) * 100.0, 2)


def test_default_band_zero_percent_everywhere(temp_repo: CsvBandsRepository):
    """Verify default band for every unassigned stock is 0.0 (0.0%)."""
    for tf in BAND_TIMEFRAMES:
        assert temp_repo.get_band("UNASSIGNED_CO", tf) == 0.0

    all_bands = temp_repo.get_all_bands("UNASSIGNED_CO")
    for tf in BAND_TIMEFRAMES:
        assert all_bands[tf] == 0.0

    # Calculation behavior with default 0.0: produces safe 'na' state and None levels
    res = band_state([100.0] * 40, band_frac=0.0)
    assert res["state"] == "na"
    assert res["up"] is None
    assert res["lo"] is None
    assert res["bd"] is None


def test_audit_log_percentage_representation_and_no_1500_percent_bug(
    app_state: AppState, temp_repo: CsvBandsRepository
):
    """Verify BandAuditEntry and API DTO represent percentages as plain percentage strings."""
    # 1. Update band to 15% (0.15 fraction)
    update_band("TEST_STOCK", BandUpdateIn(timeframe="M", value=0.15), app_state=app_state)

    # 2. Query per-symbol audit log
    symbol_log = get_band_log_symbol("TEST_STOCK", limit=10, app_state=app_state)
    assert len(symbol_log.changes) == 1
    change = symbol_log.changes[0]

    # new_pct must be string "15.0" (15%), NOT "0.15" and NOT "1500.0"
    assert change.new_pct == "15.0"
    assert change.old_pct == ""  # Unassigned before this edit

    # 3. Simulate UI formatting logic:
    # Previously, `${(c.new_pct * 100).toFixed(1)}%` multiplied "15.0" by 100 -> "1500.0%".
    # Fixed logic formats directly as `${Number(c.new_pct).toFixed(1)}%` -> "15.0%".
    formatted_new = f"{float(change.new_pct):.1f}%"
    assert formatted_new == "15.0%"
    assert formatted_new != "1500.0%"
    assert formatted_new != "0.15%"

    # 4. Subsequent change from 15% to 20%
    update_band("TEST_STOCK", BandUpdateIn(timeframe="M", value=0.20), app_state=app_state)
    symbol_log2 = get_band_log_symbol("TEST_STOCK", limit=10, app_state=app_state)
    assert len(symbol_log2.changes) == 2
    latest = symbol_log2.changes[0]
    assert latest.old_pct == "15.0"
    assert latest.new_pct == "20.0"

    formatted_old = f"{float(latest.old_pct):.1f}%"
    formatted_latest_new = f"{float(latest.new_pct):.1f}%"
    assert formatted_old == "15.0%"
    assert formatted_latest_new == "20.0%"


def test_persistence_reload_retains_exact_fraction_and_percentage(tmp_path: Path):
    """Verify persisting to bands.csv and reloading preserves exact meaning without corruption."""
    repo1 = CsvBandsRepository(data_dir=tmp_path)
    repo1.set_band("SYM_X", "W", 0.15)
    repo1.set_band("SYM_X", "D", 0.0)

    # Check raw file content in bands.csv
    bands_file = tmp_path / "bands.csv"
    assert bands_file.exists()
    content = bands_file.read_text(encoding="utf-8")
    # File must store fractions, not 15 or 1500
    assert "0.15" in content

    # Reload from disk into a fresh repository instance
    repo2 = CsvBandsRepository(data_dir=tmp_path)
    assert repo2.get_band("SYM_X", "W") == 0.15
    assert repo2.get_band("SYM_X", "D") == 0.0
    # Other timeframes remain default 0.0
    assert repo2.get_band("SYM_X", "M") == 0.0
