"""Column definitions, metadata rules, categorization, and default projection schemas.

Derived and adapted from prototype yogi.screening.strategy.available_fields and api/routes.py.
"""

from typing import Optional

from yogi.core.contracts.results import ColumnDefinition

DEFAULT_SUMMARY_COLUMNS: tuple[str, ...] = (
    "symbol",
    "name",
    "exchange",
    "price",
    "M_CUR",
    "RANK_M",
    "RANK_M_CUR",
    "EMA_W",
    "EMA_M",
    "BANDST_M",
    "BD_M",
    "S4",
    "ACCEL_L",
    "ATH_DIFF",
    "sector",
    "grade",
)

RANK_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    # Month aliases
    "RANK_M": ("RANK_M", "RANK_M_CUR", "RANK_MROC"),
    "RANK_M_CUR": ("RANK_M_CUR", "RANK_M", "RANK_MROC"),
    "RANK_MROC": ("RANK_MROC", "RANK_M_CUR", "RANK_M"),
    # Year aliases
    "RANK_Y": ("RANK_Y", "RANK_YROC"),
    "RANK_YROC": ("RANK_YROC", "RANK_Y"),
    # Week aliases
    "RANK_W": ("RANK_W", "RANK_WROC"),
    "RANK_WROC": ("RANK_WROC", "RANK_W"),
    # Day aliases
    "RANK_D": ("RANK_D", "RANK_DROC"),
    "RANK_DROC": ("RANK_DROC", "RANK_D"),
    # Quarter aliases
    "RANK_Q": ("RANK_Q", "RANK_Q_CUR", "RANK_QROC"),
    "RANK_Q_CUR": ("RANK_Q_CUR", "RANK_Q", "RANK_QROC"),
    "RANK_QROC": ("RANK_QROC", "RANK_Q_CUR", "RANK_Q"),
    # Half-Year aliases
    "RANK_H": ("RANK_H", "RANK_H_CUR", "RANK_HROC"),
    "RANK_H_CUR": ("RANK_H_CUR", "RANK_H", "RANK_HROC"),
    "RANK_HROC": ("RANK_HROC", "RANK_H_CUR", "RANK_H"),
    # Multi-year / YTD aliases
    "RANK_YTD": ("RANK_YTD", "YTD"),
    "RANK_3M": ("RANK_3M", "3M"),
    "RANK_3Y": ("RANK_3Y", "3Y"),
    "RANK_4Y": ("RANK_4Y", "4Y"),
    "RANK_5Y": ("RANK_5Y", "5Y"),
    "RANK_AVG5Y": ("RANK_AVG5Y", "AVG5Y"),
}

KNOWN_LABELS: dict[str, str] = {
    "symbol": "Symbol",
    "name": "Name",
    "exchange": "Exchange",
    "price": "Price",
    "sector": "Sector",
    "grade": "Grade",
    "fno": "F&O",
    "mcap": "Market Cap",
    "instr": "Instrument",
    "grp": "Group/Series",
    "in_gsheet": "In Sheet",
    "SUSPECT": "Suspect",
    # ROC
    "DROC": "Daily ROC",
    "WROC": "Weekly ROC",
    "MROC": "Monthly ROC",
    "QROC": "Quarterly ROC",
    "HROC": "Half-Yearly ROC",
    "YROC": "Yearly ROC",
    # Months
    "M_CUR": "Month (Cur)",
    "M_P1": "Month (P1)",
    "M_P2": "Month (P2)",
    "M_P3": "Month (P3)",
    "UPCUT": "Upcut",
    # Quarters / Halves
    "Q_CUR": "Quarter (Cur)",
    "Q_P1": "Quarter (P1)",
    "H_CUR": "Half (Cur)",
    "H_P1": "Half (P1)",
    # Sprints
    "S4": "Sprint S4",
    "S13": "Sprint S13",
    "S26": "Sprint S26",
    "S52": "Sprint S52",
    "ACCEL_S": "Short Accel",
    "ACCEL_L": "Long Accel",
    "SPR_CONSIST": "Sprint Consist",
    # Impulse
    "IC": "Impulse Conf",
    "IC_PCT": "Impulse Pct",
    "IC_BARS": "Impulse Bars",
    "IC_RATIO": "Impulse Ratio",
    "IC_START": "Impulse Start",
    "IC_END": "Impulse End",
    "IC_AGE": "Impulse Age",
    # Years / ATH
    "ATH_DIFF": "ATH Diff",
    "YTD": "YTD",
    "Y_OLDER": "Older Years",
    # Multi-timeframe counts
    "OUT_ABOVE": "Out Above",
    "OUT_BELOW": "Out Below",
    "N_ABOVE": "Count Above",
    "N_BELOW": "Count Below",
    "EMA_UP_COUNT": "EMA UP Count",
}

NON_NUMERIC_KEYS: frozenset[str] = frozenset({
    "symbol",
    "name",
    "exchange",
    "sector",
    "grade",
    "fno",
    "instr",
    "grp",
    "in_gsheet",
    "SUSPECT",
    "UPCUT",
    "IC",
    "IC_START",
    "IC_END",
})

INTEGER_KEYS: frozenset[str] = frozenset({
    "OUT_ABOVE",
    "OUT_BELOW",
    "N_ABOVE",
    "N_BELOW",
    "IC_BARS",
    "IC_AGE",
    "EMA_UP_COUNT",
})


def categorize_column(key: str) -> str:
    """Categorize a metric or identifier column by key pattern."""
    if key in ("symbol", "name", "exchange"):
        return "IDENTIFIER"
    if key in ("sector", "grade", "fno", "mcap", "in_gsheet"):
        return "METADATA"
    if key == "price":
        return "PRICE"
    if key.startswith("RANK_"):
        return "RANKS"
    if key.startswith(("ADX_", "DIP_", "DIM_", "DMI_")):
        return "DMI / ADX"
    if key.startswith("EMA_") or key == "UPCUT":
        return "EMA"
    if key.startswith(("BAND", "BD_", "OUT_", "N_AB", "N_BE")):
        return "BANDS"
    if key.startswith(("SPA_", "SPR_", "SPD_", "S4", "S13", "S26", "S52", "ACCEL")):
        return "SPRINT"
    if key.startswith("IC"):
        return "IMPULSE"
    if key.startswith(("CD_", "CW_", "CM_", "CQ_", "CH_", "CY_")):
        return "CANDLES"
    if key in ("DROC", "WROC", "MROC", "QROC", "HROC", "YROC"):
        return "ROC"
    if key.startswith("M") and (key[1:].isdigit() or key.startswith("M_")):
        return "MONTHS"
    if key.startswith(("Q", "H")) and len(key) <= 6:
        return "QUARTERS/HALVES"
    if key.startswith("Y2") or key == "Y_OLDER" or key.startswith("CAGR_") or key == "ATH_DIFF":
        return "YEARS"
    return "OTHER"


def derive_label(key: str) -> str:
    """Derive a clean, human-readable column label for a given column key."""
    if key in KNOWN_LABELS:
        return KNOWN_LABELS[key]
    if key.startswith("RANK_"):
        suffix = key[5:]
        return f"Rank {derive_label(suffix)}" if suffix in KNOWN_LABELS else f"Rank {suffix}"
    if key.startswith("BANDST_"):
        tf = key[7:]
        return f"Band State ({tf})"
    if key.startswith("BANDUP_"):
        tf = key[7:]
        return f"Band Upper ({tf})"
    if key.startswith("BANDLO_"):
        tf = key[7:]
        return f"Band Lower ({tf})"
    if key.startswith("BD_"):
        tf = key[3:]
        return f"Band Dist ({tf})"
    if key.startswith("EMA_"):
        tf = key[4:]
        return f"EMA ({tf})"
    if key.startswith("CAGR_"):
        years = key[5:]
        return f"CAGR {years}Y"
    # General fallback: replace underscores with spaces
    return key.replace("_", " ").strip()


def build_column_definition(key: str) -> ColumnDefinition:
    """Construct a ColumnDefinition DTO for a given column key."""
    category = categorize_column(key)
    label = derive_label(key)

    # Determine numeric nature
    if key.startswith("RANK_") or key in INTEGER_KEYS:
        is_numeric = True
        format_string = "0"
    elif key in NON_NUMERIC_KEYS or key.startswith(("BANDST_", "EMA_", "CD_", "CW_", "CM_", "CQ_", "CH_", "CY_")):
        is_numeric = False
        format_string = None
    else:
        is_numeric = True
        format_string = "0.00"

    return ColumnDefinition(
        key=key,
        label=label,
        category=category,
        is_numeric=is_numeric,
        format_string=format_string,
    )
