"""The 21 Verified Mentor Presets — Authoritative screening strategies.

Derived directly from prototype LISTS_LOGIC.txt and verify_lists.py.
Preserves the exact qualification criteria, rank targets, and cutoff limits.
"""

from typing import Optional, Sequence

from yogi.core.configuration.catalog import StrategyCatalog
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.strategy import StrategySpec

# =============================================================================
# GROUP A: IMPULSE / RALLY
# =============================================================================

A1_IMPULSE_CONFIRMED = StrategySpec(
    name="A1_IMPULSE_CONFIRMED",
    description="Price above monthly band, monthly EMA positive, and rank improving",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE"),
            FilterRuleSpec(field="EMA_M", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="RANK_CHG", op=FilterOperator.GT, value=0.0),
        ],
    ),
    is_mentor_preset=True,
)

A2_ALL_6_TF_EMA_UP = StrategySpec(
    name="A2_ALL_6_TF_EMA_UP",
    description="EMA positive across all 6 timeframes (D, W, M, Q, H, Y)",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="EMA_D", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_W", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_M", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_Q", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_H", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_Y", op=FilterOperator.IN, value=("upcut", "yes")),
        ],
    ),
    is_mentor_preset=True,
)

A3_FRESH_MONTHLY_UPCUT = StrategySpec(
    name="A3_FRESH_MONTHLY_UPCUT",
    description="EMA3 crossed above EMA5 on monthly bar",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="EMA_M", op=FilterOperator.EQ, value="upcut"),
        ],
    ),
    is_mentor_preset=True,
)

A4_FRESH_WEEKLY_UPCUT = StrategySpec(
    name="A4_FRESH_WEEKLY_UPCUT",
    description="EMA3 crossed above EMA5 on weekly bar",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="upcut"),
        ],
    ),
    is_mentor_preset=True,
)

# =============================================================================
# GROUP B: SPRINT / MOMENTUM
# =============================================================================

B1_SPRINTERS_MONTH = StrategySpec(
    name="B1_SPRINTERS_MONTH",
    description="Fastest sprinters this month",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="SPD_M", op=FilterOperator.GT, value=0.0),
        ],
    ),
    target_ranking_metric="SPD_M",
    is_mentor_preset=True,
)

B2_SPRINTERS_QUARTER = StrategySpec(
    name="B2_SPRINTERS_QUARTER",
    description="Fastest sprinters this quarter",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="SPD_Q", op=FilterOperator.GT, value=0.0),
        ],
    ),
    target_ranking_metric="SPD_Q",
    is_mentor_preset=True,
)

B3_SPRINTERS_YEAR = StrategySpec(
    name="B3_SPRINTERS_YEAR",
    description="Fastest sprinters this year",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="SPD_Y", op=FilterOperator.GT, value=0.0),
        ],
    ),
    target_ranking_metric="SPD_Y",
    is_mentor_preset=True,
)

B4_ACCELERATING = StrategySpec(
    name="B4_ACCELERATING",
    description="Pace faster now vs 1-year pace",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="ACCEL_L", op=FilterOperator.GT, value=0.0),
        ],
    ),
    target_ranking_metric="ACCEL_L",
    is_mentor_preset=True,
)

B5_ACCEL_AND_EMA_UP = StrategySpec(
    name="B5_ACCEL_AND_EMA_UP",
    description="Accelerating pace with weekly and monthly EMA positive",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="ACCEL_L", op=FilterOperator.GT, value=0.0),
            FilterRuleSpec(field="EMA_W", op=FilterOperator.IN, value=("upcut", "yes")),
            FilterRuleSpec(field="EMA_M", op=FilterOperator.IN, value=("upcut", "yes")),
        ],
    ),
    is_mentor_preset=True,
)

B6_CONSISTENT_RUNNERS = StrategySpec(
    name="B6_CONSISTENT_RUNNERS",
    description="At least 75% of last 12 weekly closes were up",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="SPR_CONSIST", op=FilterOperator.GTE, value=75.0),
        ],
    ),
    is_mentor_preset=True,
)

B7_IN_IMPULSE = StrategySpec(
    name="B7_IN_IMPULSE",
    description="Impulse confirmed via 50% recovery rule",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="IC", op=FilterOperator.EQ, value="IP"),
        ],
    ),
    is_mentor_preset=True,
)

B8_IN_CORRECTION = StrategySpec(
    name="B8_IN_CORRECTION",
    description="Correction in progress",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="IC", op=FilterOperator.EQ, value="CR"),
        ],
    ),
    is_mentor_preset=True,
)

# =============================================================================
# GROUP C: BAND BREAKOUTS
# =============================================================================

C1_BROKE_ABOVE_BAND = StrategySpec(
    name="C1_BROKE_ABOVE_BAND",
    description="Price broke above upper band on at least one timeframe",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="OUT_ABOVE", op=FilterOperator.NOT_BLANK),
        ],
    ),
    is_mentor_preset=True,
)

C2_BROKE_BELOW_BAND = StrategySpec(
    name="C2_BROKE_BELOW_BAND",
    description="Price broke below lower band on at least one timeframe",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="OUT_BELOW", op=FilterOperator.NOT_BLANK),
        ],
    ),
    is_mentor_preset=True,
)

C3_OUTSIDE_BAND_2PLUS_TF = StrategySpec(
    name="C3_OUTSIDE_BAND_2PLUS_TF",
    description="Outside band on 2 or more timeframes (N_ABOVE + N_BELOW >= 2)",
    filter_group=FilterGroupSpec(
        match="any",
        rules=[
            FilterRuleSpec(field="N_ABOVE", op=FilterOperator.GTE, value=2),
            FilterRuleSpec(field="N_BELOW", op=FilterOperator.GTE, value=2),
            FilterGroupSpec(
                match="all",
                rules=[
                    FilterRuleSpec(field="N_ABOVE", op=FilterOperator.GTE, value=1),
                    FilterRuleSpec(field="N_BELOW", op=FilterOperator.GTE, value=1),
                ],
            ),
        ],
    ),
    is_mentor_preset=True,
)

C4_REACTION_TRADE = StrategySpec(
    name="C4_REACTION_TRADE",
    description="Below yearly band, but weekly EMA turning positive",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="BANDST_Y", op=FilterOperator.EQ, value="BELOW"),
            FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="upcut"),
        ],
    ),
    is_mentor_preset=True,
)

# =============================================================================
# GROUP D: EXIT SIGNALS
# =============================================================================

D1_EXIT_FNO = StrategySpec(
    name="D1_EXIT_FNO",
    description="F&O stock with daily EMA turning negative",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="fno", op=FilterOperator.EQ, value="Y"),
            FilterRuleSpec(field="EMA_D", op=FilterOperator.EQ, value="downcut"),
        ],
    ),
    is_mentor_preset=True,
)

D2_EXIT_CASH = StrategySpec(
    name="D2_EXIT_CASH",
    description="Cash stock with weekly EMA turning negative",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="downcut"),
        ],
    ),
    is_mentor_preset=True,
)

# =============================================================================
# GROUP E: RANKING & CUTOFFS
# =============================================================================

E1_TOP_100_MONTH = StrategySpec(
    name="E1_TOP_100_MONTH",
    description="Top 100 ranking this month",
    filter_group=FilterGroupSpec(rules=[]),
    target_ranking_metric="M_CUR",
    target_cutoff_limit=100,
    is_mentor_preset=True,
)

E2_TOP_100_YEAR = StrategySpec(
    name="E2_TOP_100_YEAR",
    description="Top 100 ranking this year",
    filter_group=FilterGroupSpec(rules=[]),
    target_ranking_metric="YROC",
    target_cutoff_limit=100,
    is_mentor_preset=True,
)

E3_RANK_CLIMBERS = StrategySpec(
    name="E3_RANK_CLIMBERS",
    description="Positive rank change (rank improved this month vs last month)",
    filter_group=FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="RANK_CHG", op=FilterOperator.GT, value=0.0),
        ],
    ),
    target_ranking_metric="RANK_CHG",
    is_mentor_preset=True,
)

# Canonical sequence of all 21 Verified Mentor Presets
MENTOR_PRESETS: Sequence[StrategySpec] = (
    A1_IMPULSE_CONFIRMED,
    A2_ALL_6_TF_EMA_UP,
    A3_FRESH_MONTHLY_UPCUT,
    A4_FRESH_WEEKLY_UPCUT,
    B1_SPRINTERS_MONTH,
    B2_SPRINTERS_QUARTER,
    B3_SPRINTERS_YEAR,
    B4_ACCELERATING,
    B5_ACCEL_AND_EMA_UP,
    B6_CONSISTENT_RUNNERS,
    B7_IN_IMPULSE,
    B8_IN_CORRECTION,
    C1_BROKE_ABOVE_BAND,
    C2_BROKE_BELOW_BAND,
    C3_OUTSIDE_BAND_2PLUS_TF,
    C4_REACTION_TRADE,
    D1_EXIT_FNO,
    D2_EXIT_CASH,
    E1_TOP_100_MONTH,
    E2_TOP_100_YEAR,
    E3_RANK_CLIMBERS,
)


def load_mentor_presets(catalog: Optional[StrategyCatalog] = None) -> StrategyCatalog:
    """Populate a StrategyCatalog with all 21 Verified Mentor Presets.
    
    If no catalog is provided, a new StrategyCatalog is instantiated.
    """
    cat = catalog if catalog is not None else StrategyCatalog()
    for preset in MENTOR_PRESETS:
        if not cat.has(preset.name):
            cat.register(preset)
    return cat
