"""RegistryHub — Unified container of capability registries across YOGI's contracts."""

from typing import Optional

from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.calculation import ICalcModule
from yogi.core.contracts.provider import IDataProvider
from yogi.core.registry.base import CapabilityRegistry


class RegistryHub:
    """The explicit container of capability registries across YOGI's contracts.

    Coordinates exactly the three approved capability registries:
    - providers:    CapabilityRegistry[IDataProvider]
    - calculations: CapabilityRegistry[ICalcModule]
    - bands:        CapabilityRegistry[IBandsRepository]

    Security/instrument reference metadata and trader annotations are absorbed
    into the Provider → Normalization pipeline (src/yogi/data/), and do not
    require an independent RegistryHub capability.

    Does NOT expose registries for securities, filters, strategies, rankings,
    selections, assemblers, or formatters.
    """

    def __init__(
        self,
        providers: Optional[CapabilityRegistry[IDataProvider]] = None,
        calculations: Optional[CapabilityRegistry[ICalcModule]] = None,
        bands: Optional[CapabilityRegistry[IBandsRepository]] = None,
    ) -> None:
        self.providers: CapabilityRegistry[IDataProvider] = (
            providers if providers is not None else CapabilityRegistry("providers", IDataProvider)
        )
        self.calculations: CapabilityRegistry[ICalcModule] = (
            calculations if calculations is not None else CapabilityRegistry("calculations", ICalcModule)
        )
        self.bands: CapabilityRegistry[IBandsRepository] = (
            bands if bands is not None else CapabilityRegistry("bands", IBandsRepository)
        )

    def __repr__(self) -> str:
        return (
            f"<RegistryHub("
            f"providers={self.providers.list_keys()}, "
            f"calculations={self.calculations.list_keys()}, "
            f"bands={self.bands.list_keys()})>"
        )
