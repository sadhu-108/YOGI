"""Regression tests verifying default band value resolution of 0.0 for unassigned stocks.

Verifies:
1. Every stock without a manual band assignment resolves to band 0.0 across all timeframes.
2. An explicitly assigned band of 0.0 remains valid.
3. A manually assigned nonzero band is preserved and takes precedence over the default.
4. Reloading from disk, refreshing, or reinitializing does not reset manual assignments.
5. Band calculation states (band_state) for default 0.0 return 'na' and None metrics without breaking math.
6. DemoBandsRepository adheres to the exact same default 0.0 behavior.
"""

from pathlib import Path
import tempfile
import pytest

from yogi.calculation.bands import band_state
from yogi.cockpit.demo import DemoBandsRepository
from yogi.core.contracts.bands import BAND_TIMEFRAMES
from yogi.storage.bands import CsvBandsRepository


def test_unassigned_stock_resolves_to_zero():
    """Verify an unassigned stock resolves to band 0.0 across get_band and get_all_bands."""
    with tempfile.TemporaryDirectory() as td:
        repo = CsvBandsRepository(data_dir=Path(td))

        # Query completely unassigned symbol
        for tf in BAND_TIMEFRAMES:
            assert repo.get_band("UNASSIGNED_XYZ", tf) == 0.0

        all_bands = repo.get_all_bands("UNASSIGNED_XYZ")
        assert len(all_bands) == len(BAND_TIMEFRAMES)
        for tf in BAND_TIMEFRAMES:
            assert all_bands[tf] == 0.0


def test_explicit_assigned_zero_remains_valid():
    """Verify that explicitly assigning band 0.0 is persisted and returned as 0.0."""
    with tempfile.TemporaryDirectory() as td:
        repo = CsvBandsRepository(data_dir=Path(td))

        res = repo.set_band("EXPLICIT_ZERO", "D", 0.0, who="user", source="test")
        assert res == 0.0
        assert repo.get_band("EXPLICIT_ZERO", "D") == 0.0

        # Reload from disk to verify persistence
        repo2 = CsvBandsRepository(data_dir=Path(td))
        assert repo2.get_band("EXPLICIT_ZERO", "D") == 0.0


def test_manually_assigned_nonzero_band_takes_precedence():
    """Verify that manually assigned nonzero bands take precedence over default 0.0."""
    with tempfile.TemporaryDirectory() as td:
        repo = CsvBandsRepository(data_dir=Path(td))

        # Before assignment: resolves to default 0.0
        assert repo.get_band("ACTIVE_STOCK", "M") == 0.0

        # Manual assignment of 15% (0.15)
        repo.set_band("ACTIVE_STOCK", "M", 0.15, who="user", source="test")

        # After assignment: returns manual value
        assert repo.get_band("ACTIVE_STOCK", "M") == 0.15

        # Other unassigned timeframes for this stock continue to resolve to 0.0
        all_bands = repo.get_all_bands("ACTIVE_STOCK")
        assert all_bands["M"] == 0.15
        assert all_bands["D"] == 0.0
        assert all_bands["W"] == 0.0
        assert all_bands["Q"] == 0.0
        assert all_bands["H"] == 0.0
        assert all_bands["Y"] == 0.0


def test_reinitialization_preserves_manual_assignments():
    """Verify reinitializing repository from disk does not overwrite manual assignments."""
    with tempfile.TemporaryDirectory() as td:
        data_path = Path(td)
        repo1 = CsvBandsRepository(data_dir=data_path)
        repo1.set_band("SYM_A", "D", 0.08)
        repo1.set_band("SYM_B", "Y", 0.35)

        # Reinstantiate repository (simulating server restart / refresh)
        repo2 = CsvBandsRepository(data_dir=data_path)
        assert repo2.get_band("SYM_A", "D") == 0.08
        assert repo2.get_band("SYM_B", "Y") == 0.35
        # Unassigned stocks remain 0.0
        assert repo2.get_band("SYM_A", "W") == 0.0
        assert repo2.get_band("SYM_C", "D") == 0.0


def test_band_state_calculation_with_default_zero():
    """Verify band_state calculation semantics are preserved for default 0.0."""
    bars = [100.0] * 40

    # Default band value of 0.0 produces safe 'na' state and None boundary levels
    res = band_state(bars, band_frac=0.0)
    assert res["state"] == "na"
    assert res["bd"] is None
    assert res["pos"] is None
    assert res["up"] is None
    assert res["lo"] is None


def test_demo_bands_repository_default_zero():
    """Verify DemoBandsRepository also implements default 0.0 resolution."""
    demo_repo = DemoBandsRepository()

    # Unassigned stock resolves to 0.0
    assert demo_repo.get_band("UNASSIGNED_DEMO", "D") == 0.0
    all_demo = demo_repo.get_all_bands("UNASSIGNED_DEMO")
    for tf in BAND_TIMEFRAMES:
        assert all_demo[tf] == 0.0

    # Manual edit takes precedence
    demo_repo.set_band("UNASSIGNED_DEMO", "D", 0.20)
    assert demo_repo.get_band("UNASSIGNED_DEMO", "D") == 0.20
    assert demo_repo.get_band("UNASSIGNED_DEMO", "W") == 0.0
