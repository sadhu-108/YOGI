"""Default composition and bootstrap functions for RegistryHub."""

import logging

from yogi.core.registry.hub import RegistryHub

logger = logging.getLogger(__name__)


def create_default_registry_hub() -> RegistryHub:
    """Construct and return an authoritative RegistryHub configured with default capabilities.

    Capabilities registered:
    - calculations:
      - bands:    BandsCalculator (eager)
      - velocity: VelocityCalculator (eager)
      - impulse:  ImpulseCalculator (eager)
      - trend:    TrendCalculator (eager)
      - candles:  CandleCalculator (eager)
    - providers:
      - demo:     DemoDataProvider (lazy factory)
      - yfinance: YFinanceDataProvider (lazy factory, keeps startup fast and demo isolated)
    - bands:
      - demo:     DemoBandsRepository (lazy factory)
      - csv:      CsvBandsRepository (lazy factory)
      - excel:    CsvBandsRepository (lazy factory mapping to the shared csv repository)
    """
    hub = RegistryHub()

    # 1. Analytical Calculation Modules (Eager registration - lightweight with no heavy I/O)
    from yogi.calculation.bands import BandsCalculator
    from yogi.calculation.candles import CandleCalculator
    from yogi.calculation.impulse import ImpulseCalculator
    from yogi.calculation.trend import TrendCalculator
    from yogi.calculation.velocity import VelocityCalculator

    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())

    # 2. Market Data Providers (Lazy factories to prevent unneeded imports and network init)
    def _demo_provider_factory():
        from yogi.data.providers.demo import DemoDataProvider
        return DemoDataProvider()

    def _yfinance_provider_factory():
        from yogi.data.providers.yfinance import YFinanceDataProvider
        return YFinanceDataProvider()

    hub.providers.register_factory("demo", _demo_provider_factory)
    hub.providers.register_factory("yfinance", _yfinance_provider_factory)

    # 3. Bands Repositories (Lazy factories)
    def _demo_bands_factory():
        from yogi.cockpit.demo import DemoBandsRepository
        return DemoBandsRepository()

    def _csv_bands_factory():
        from yogi.storage.bands import CsvBandsRepository
        return CsvBandsRepository()

    hub.bands.register_factory("demo", _demo_bands_factory)
    hub.bands.register_factory("csv", _csv_bands_factory)
    hub.bands.register_factory("excel", lambda: hub.bands.get("csv"))

    return hub
