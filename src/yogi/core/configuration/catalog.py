"""Declarative catalog for managing reusable StrategySpec recipes and mentor presets."""

from typing import Dict, Iterable, Optional, Sequence

from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.selection import RankCutoffSpec
from yogi.core.contracts.strategy import StrategySpec


class StrategyCatalog:
    """A declarative catalog of named StrategySpec recipes.

    Stores composition recipes (e.g. mentor presets, saved screener strategies).
    This is NOT an implementation registry; it contains no Python class discovery,
    instantiation, or execution mechanisms.
    """

    def __init__(self, initial_specs: Optional[Iterable[StrategySpec]] = None) -> None:
        self._strategies: Dict[str, StrategySpec] = {}
        if initial_specs:
            for spec in initial_specs:
                self.register(spec)

    def register(self, spec: StrategySpec) -> None:
        """Register a strategy recipe under its spec.name.

        Raises:
            ValueError: If a strategy with the same name is already in the catalog.
            TypeError: If spec is not a StrategySpec.
        """
        if not isinstance(spec, StrategySpec):
            raise TypeError(f"Expected StrategySpec, got {type(spec).__name__}.")
        if spec.name in self._strategies:
            raise ValueError(f"Strategy '{spec.name}' is already registered in catalog.")
        self._strategies[spec.name] = spec

    def get(self, name: str) -> StrategySpec:
        """Retrieve a strategy recipe by name.

        Raises:
            KeyError: If the strategy name is not found in the catalog.
        """
        if name not in self._strategies:
            raise KeyError(f"Strategy '{name}' not found in catalog.")
        return self._strategies[name]

    def has(self, name: str) -> bool:
        """Return True if the named strategy exists in the catalog."""
        return name in self._strategies

    def list_names(self) -> Sequence[str]:
        """Return a sorted sequence of all registered strategy names."""
        return sorted(self._strategies.keys())

    def to_query(self, name: str) -> ScreeningQuery:
        """Translate a registered StrategySpec recipe into an executable ScreeningQuery.

        Maps the strategy recipe's components to the QUALIFY -> ORDER -> SHOW model:
        - filter_group          -> QUALIFY (boolean qualification criteria)
        - target_ranking_metric -> ORDER (relative standing metric)
        - target_cutoff_limit   -> SHOW (rank cutoff on target_ranking_metric)

        Note on Semantics:
            target_cutoff_limit represents an analytical rank cutoff (RankCutoffSpec),
            NOT a presentation result limit. StrategySpec is explicitly decoupled
            from presentation sorting and display truncation; therefore,
            ScreeningQuery.limit remains None.
            Ranking order relies on ScreeningQuery's contractual default
            (RankingOrder.DESCENDING) as StrategySpec defines no custom ordering direction.
        """
        spec = self.get(name)
        cutoffs = []
        if spec.target_ranking_metric and spec.target_cutoff_limit:
            cutoffs.append(
                RankCutoffSpec(
                    rank_metric=spec.target_ranking_metric,
                    max_rank=spec.target_cutoff_limit,
                )
            )

        return ScreeningQuery(
            filter_group=spec.filter_group,
            ranking_metric=spec.target_ranking_metric,
            selection_cutoffs=tuple(cutoffs),
        )

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __getitem__(self, name: str) -> StrategySpec:
        return self.get(name)

    def __len__(self) -> int:
        return len(self._strategies)

    def __repr__(self) -> str:
        return f"<StrategyCatalog: {self.list_names()}>"
