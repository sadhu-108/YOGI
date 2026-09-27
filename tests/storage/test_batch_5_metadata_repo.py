"""Tests for Batch 5 CsvMetadataRepository."""

import concurrent.futures
from pathlib import Path
import pytest
from yogi.core.contracts.security import InstrumentType, ListingStatus, SecurityMetadata
from yogi.storage.metadata import CsvMetadataRepository


class TestCsvMetadataRepository:
    def test_empty_initialization(self, tmp_path: Path):
        repo = CsvMetadataRepository(data_dir=tmp_path)
        assert repo.get_all_metadata() == {}
        assert repo.get_fno_symbols() == set()
        assert not repo.is_fno("RELIANCE")
        assert repo.get_metadata("RELIANCE") is None

    def test_seed_from_legacy_his_meta(self, tmp_path: Path):
        seed_meta = tmp_path / "his_meta.csv"
        seed_meta.write_text(
            "symbol,name,sector,grade,mcap,fno\n"
            "TCS,Tata Consultancy Services,IT,A,1400000.0,Y\n"
            "INFY,Infosys Limited,IT,A,600000.0,N\n",
            encoding="utf-8",
        )
        repo_dir = tmp_path / "repo_data"
        repo = CsvMetadataRepository(data_dir=repo_dir, seed_meta_csv=seed_meta)

        tcs = repo.get_metadata("TCS")
        assert tcs is not None
        assert tcs.symbol == "TCS"
        assert tcs.name == "Tata Consultancy Services"
        assert tcs.sector == "IT"
        assert tcs.grade == "A"
        assert tcs.mcap == 1400000.0
        assert tcs.is_fno is True
        assert tcs.instrument_type == InstrumentType.EQ

        infy = repo.get_metadata("INFY")
        assert infy is not None
        assert infy.is_fno is False

        # Verify metadata.csv was atomically created in repo_dir
        assert (repo_dir / "metadata.csv").exists()

    def test_seed_fno_list(self, tmp_path: Path):
        seed_fno = tmp_path / "fno_list.csv"
        seed_fno.write_text("symbol\nRELIANCE\nTCS\nSBIN\n", encoding="utf-8")

        repo_dir = tmp_path / "repo_data"
        repo = CsvMetadataRepository(data_dir=repo_dir, seed_fno_csv=seed_fno)

        assert repo.is_fno("RELIANCE")
        assert repo.is_fno("TCS")
        assert repo.is_fno("SBIN")
        assert not repo.is_fno("WIPRO")
        assert len(repo.get_fno_symbols()) == 3

    def test_update_metadata_fields(self, tmp_path: Path):
        repo = CsvMetadataRepository(data_dir=tmp_path)

        # Update sector on new symbol
        sec = repo.update_metadata("TITAN", "sector", "Consumer Discretionary")
        assert sec is not None
        assert sec.symbol == "TITAN"
        assert sec.sector == "Consumer Discretionary"

        # Update mcap
        sec = repo.update_metadata("TITAN", "mcap", "300000.5")
        assert sec.mcap == 300000.5

        # Update grade
        sec = repo.update_metadata("TITAN", "grade", "A")
        assert sec.grade == "A"

        # Update fno
        assert not repo.is_fno("TITAN")
        sec = repo.update_metadata("TITAN", "fno", "Y")
        assert sec.is_fno is True
        assert repo.is_fno("TITAN")
        assert "TITAN" in repo.get_fno_symbols()

        # Update instrument_type
        sec = repo.update_metadata("TITAN", "instrument_type", "ETF")
        assert sec.instrument_type == InstrumentType.ETF

        # Clear mcap
        sec = repo.update_metadata("TITAN", "mcap", "")
        assert sec.mcap is None

        # Verify disk persistence
        repo_reload = CsvMetadataRepository(data_dir=tmp_path)
        reloaded = repo_reload.get_metadata("TITAN")
        assert reloaded is not None
        assert reloaded.symbol == "TITAN"
        assert reloaded.sector == "Consumer Discretionary"
        assert reloaded.grade == "A"
        assert reloaded.is_fno is True
        assert reloaded.instrument_type == InstrumentType.ETF
        assert reloaded.mcap is None

    def test_update_metadata_invalid_field(self, tmp_path: Path):
        repo = CsvMetadataRepository(data_dir=tmp_path)
        with pytest.raises(ValueError, match="not a valid editable metadata field"):
            repo.update_metadata("RELIANCE", "non_existent_field", "value")

    def test_set_fno_symbols(self, tmp_path: Path):
        repo = CsvMetadataRepository(data_dir=tmp_path)
        repo.update_metadata("RELIANCE", "name", "Reliance Industries")
        repo.update_metadata("TCS", "name", "Tata Consultancy Services")

        assert not repo.is_fno("RELIANCE")
        assert not repo.is_fno("TCS")

        repo.set_fno_symbols(["RELIANCE", "TCS", "INFY"])
        assert repo.is_fno("RELIANCE")
        assert repo.is_fno("TCS")
        assert repo.is_fno("INFY")

        rel = repo.get_metadata("RELIANCE")
        assert rel is not None
        assert rel.is_fno is True

        # Overwrite with smaller set
        repo.set_fno_symbols(["INFY"])
        assert not repo.is_fno("RELIANCE")
        rel2 = repo.get_metadata("RELIANCE")
        assert rel2.is_fno is False
        assert repo.is_fno("INFY")

    def test_concurrent_updates(self, tmp_path: Path):
        repo = CsvMetadataRepository(data_dir=tmp_path)

        def worker(sym_idx: int):
            sym = f"SYM{sym_idx}"
            repo.update_metadata(sym, "name", f"Company {sym_idx}")
            repo.update_metadata(sym, "sector", f"Sector {sym_idx % 5}")
            repo.update_metadata(sym, "mcap", sym_idx * 1000.0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(50)]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()

        all_meta = repo.get_all_metadata()
        assert len(all_meta) == 50
        for i in range(50):
            sym = f"SYM{i}"
            assert sym in all_meta
            assert all_meta[sym].name == f"Company {i}"
            assert all_meta[sym].sector == f"Sector {i % 5}"
            assert all_meta[sym].mcap == i * 1000.0
