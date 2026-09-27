"""Tests for Batch 5 Instrument Classification Normalizer."""

import pytest
from yogi.core.contracts.security import InstrumentType
from yogi.data.normalization.classification import (
    ClassificationMaps,
    classify_instrument,
    parse_bse_universe_csv,
    parse_nse_etf_csv,
    parse_nse_series_csv,
    parse_nse_sme_csv,
)


class TestParseNseEtfCsv:
    def test_parse_valid_etf_csv(self):
        csv_data = """Symbol,Security Name,Date of Listing
NIFTYBEES,NIPPON INDIA ETF NIFTY 50 BEES,28-DEC-2001
GOLDBEES,NIPPON INDIA ETF GOLD BEES,08-MAR-2007
MON100,MOTILAL OSWAL NASDAQ 100 ETF,29-MAR-2011
"""
        etfs = parse_nse_etf_csv(csv_data)
        assert etfs == frozenset({"NIFTYBEES", "GOLDBEES", "MON100"})

    def test_parse_empty_or_malformed(self):
        assert parse_nse_etf_csv("") == frozenset()
        assert parse_nse_etf_csv("   ") == frozenset()
        assert parse_nse_etf_csv("ColA,ColB\n1,2") == frozenset()


class TestParseNseSmeCsv:
    def test_parse_valid_sme_csv(self):
        csv_data = """Symbol,Name,Market Lot
ACCURACY,Accuracy Shipping Limited,3000
VERTEX,Vertexplus Technologies Limited,1000
"""
        smes = parse_nse_sme_csv(csv_data)
        assert smes == frozenset({"ACCURACY", "VERTEX"})

    def test_parse_empty_or_malformed(self):
        assert parse_nse_sme_csv("") == frozenset()
        assert parse_nse_sme_csv("NoMatchHeader,Value\n1,2") == frozenset()


class TestParseNseSeriesCsv:
    def test_parse_valid_series_csv(self):
        csv_data = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING
RELIANCE,Reliance Industries Limited, EQ, 29-NOV-1995
IDEA,Vodafone Idea Limited, BE, 09-MAR-2007
TEMPSME,Some SME Company, SM, 15-JUN-2022
"""
        series_map = parse_nse_series_csv(csv_data)
        assert series_map.get("RELIANCE") == "EQ"
        assert series_map.get("IDEA") == "BE"
        assert series_map.get("TEMPSME") == "SM"

    def test_parse_empty_or_malformed(self):
        assert len(parse_nse_series_csv("")) == 0
        assert len(parse_nse_series_csv("Col1,Col2\nA,B")) == 0


class TestParseBseUniverseCsv:
    def test_parse_valid_bse_universe(self):
        csv_data = """Scrip_Cd,Symbol,Group,Industry
500325,RELIANCE,A,Refineries
532187,INDUSINDBK,A,Banks
543210,NEWSME,M,Software
511111,ILLIQSTK,XT,Finance
"""
        bse_map = parse_bse_universe_csv(csv_data)
        assert bse_map.get("RELIANCE") == "A"
        assert bse_map.get("INDUSINDBK") == "A"
        assert bse_map.get("NEWSME") == "M"
        assert bse_map.get("ILLIQSTK") == "XT"

    def test_parse_empty(self):
        assert len(parse_bse_universe_csv("")) == 0


class TestClassifyInstrumentNse:
    def test_nse_etf_from_list(self):
        maps = ClassificationMaps(
            etf_symbols=frozenset({"NIFTYBEES"}),
            series_map={"NIFTYBEES": "EQ"},
        )
        itype, ser = classify_instrument("NIFTYBEES", exchange="NSE", maps=maps)
        assert itype == InstrumentType.ETF
        assert ser == "EQ"

    def test_nse_sme_from_list_and_series(self):
        maps = ClassificationMaps(
            sme_symbols=frozenset({"VERTEX"}),
            series_map={"VERTEX": "SM", "OTHER_SM": "SM"},
        )
        itype, ser = classify_instrument("VERTEX", exchange="NSE", maps=maps)
        assert itype == InstrumentType.SME
        assert ser == "SM"

        itype2, ser2 = classify_instrument("OTHER_SM", exchange="NSE", maps=maps)
        assert itype2 == InstrumentType.SME
        assert ser2 == "SM"

    def test_nse_reit_invit_hints(self):
        itype, ser = classify_instrument("EMBASSY", name="EMBASSY OFFICE PARKS REIT", exchange="NSE")
        assert itype == InstrumentType.REIT_INVIT

        itype2, ser2 = classify_instrument("POWERGRID-INVIT", name="POWERGRID INVIT", exchange="NSE")
        assert itype2 == InstrumentType.REIT_INVIT

    def test_nse_etf_hints(self):
        itype, ser = classify_instrument("JUNIORBEES", name="Nippon India Junior Bees", exchange="NSE")
        assert itype == InstrumentType.ETF

        itype2, ser2 = classify_instrument("ABSLGOLD", name="Aditya Birla Sun Life Gold ETF", exchange="NSE")
        assert itype2 == InstrumentType.ETF

    def test_nse_trade_to_trade_be_bz(self):
        maps = ClassificationMaps(series_map={"IDEA": "BE", "FAULTY": "BZ"})
        itype, ser = classify_instrument("IDEA", exchange="NSE", maps=maps)
        assert itype == InstrumentType.BE
        assert ser == "BE"

        itype2, ser2 = classify_instrument("FAULTY", exchange="NSE", maps=maps)
        assert itype2 == InstrumentType.BE
        assert ser2 == "BZ"

    def test_nse_standard_equity_default(self):
        maps = ClassificationMaps(series_map={"INFY": "EQ"})
        itype, ser = classify_instrument("INFY", name="Infosys Limited", exchange="NSE", maps=maps)
        assert itype == InstrumentType.EQ
        assert ser == "EQ"


class TestClassifyInstrumentBse:
    def test_bse_sme_groups(self):
        maps = ClassificationMaps(bse_group_map={"SMECO": "M", "SMECO2": "MT"})
        itype, grp = classify_instrument("SMECO", exchange="BSE", maps=maps)
        assert itype == InstrumentType.SME
        assert grp == "M"

        itype2, grp2 = classify_instrument("SMECO2", exchange="BSE", maps=maps)
        assert itype2 == InstrumentType.SME
        assert grp2 == "MT"

    def test_bse_illiquid_groups(self):
        maps = ClassificationMaps(bse_group_map={"PENNY": "XT", "SUSP": "Z"})
        itype, grp = classify_instrument("PENNY", exchange="BSE", maps=maps)
        assert itype == InstrumentType.ILLIQUID
        assert grp == "XT"

        itype2, grp2 = classify_instrument("SUSP", exchange="BSE", maps=maps)
        assert itype2 == InstrumentType.ILLIQUID
        assert grp2 == "Z"

    def test_bse_etf_and_reit_hints(self):
        itype, _ = classify_instrument("GOLDETF", name="Gold ETF Fund", exchange="BSE")
        assert itype == InstrumentType.ETF

        itype2, _ = classify_instrument("MINDSPACE", name="Mindspace REIT", exchange="BSE")
        assert itype2 == InstrumentType.REIT_INVIT

    def test_bse_standard_equity(self):
        maps = ClassificationMaps(bse_group_map={"TCS": "A"})
        itype, grp = classify_instrument("TCS", exchange="BSE", maps=maps)
        assert itype == InstrumentType.EQ
        assert grp == "A"

    def test_unknown_exchange(self):
        itype, grp = classify_instrument("AAPL", exchange="NASDAQ")
        assert itype == InstrumentType.UNKNOWN
        assert grp == ""
