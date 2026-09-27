"""Tests for Batch 5 NSE F&O Universe Normalizer."""

import pytest
from yogi.data.normalization.fno import parse_fno_list_csv, parse_fno_lots_csv


class TestParseFnoLotsCsv:
    def test_parse_valid_fno_lots(self):
        # Generate mock CSV with at least 50 symbols to satisfy min_symbols default
        symbols = [f"SYM{i}" for i in range(1, 60)]
        lines = ["UNDERLYING,SYMBOL,LOT SIZE"]
        for s in symbols:
            lines.append(f"Name {s},{s},1250")
        csv_text = "\n".join(lines)

        fno_set = parse_fno_lots_csv(csv_text)
        assert len(fno_set) == 59
        assert "SYM1" in fno_set
        assert "SYM59" in fno_set

    def test_min_symbols_threshold_rejection(self):
        # Only 5 symbols -> under min_symbols=50 -> returns frozenset()
        csv_text = """SYMBOL,LOT SIZE
RELIANCE,250
TCS,175
INFY,400
HDFCBANK,550
ICICIBANK,700
"""
        assert parse_fno_lots_csv(csv_text, min_symbols=50) == frozenset()

        # With min_symbols overridden to 3, it should succeed
        parsed = parse_fno_lots_csv(csv_text, min_symbols=3)
        assert len(parsed) == 5
        assert "RELIANCE" in parsed

    def test_sanitization_and_filtering(self):
        csv_text = """SYMBOL,LOT
reliance,250
TCS   ,175
SYMBOL,100
INVALID_SYMBOL_THAT_EXCEEDS_TWENTY_CHARACTERS,50
NAN,100
NULL,100
NONE,100
INFY,400
"""
        parsed = parse_fno_lots_csv(csv_text, min_symbols=0)
        assert "RELIANCE" in parsed
        assert "TCS" in parsed
        assert "INFY" in parsed
        assert "SYMBOL" not in parsed
        assert "INVALID_SYMBOL_THAT_EXCEEDS_TWENTY_CHARACTERS" not in parsed
        assert "NAN" not in parsed
        assert "NULL" not in parsed
        assert "NONE" not in parsed

    def test_empty_or_malformed(self):
        assert parse_fno_lots_csv("") == frozenset()
        assert parse_fno_lots_csv("   ") == frozenset()
        assert parse_fno_lots_csv("ColA,ColB\n1,2", min_symbols=0) == frozenset()


class TestParseFnoListCsv:
    def test_parse_valid_fno_list(self):
        csv_text = """symbol
RELIANCE
TCS
INFY
HDFCBANK
"""
        parsed = parse_fno_list_csv(csv_text)
        assert parsed == frozenset({"RELIANCE", "TCS", "INFY", "HDFCBANK"})

    def test_empty_or_malformed(self):
        assert parse_fno_list_csv("") == frozenset()
        assert parse_fno_list_csv("invalid_col\nval1") == frozenset()
