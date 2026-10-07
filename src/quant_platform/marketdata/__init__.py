"""Real market data adapter (Yahoo Finance via yfinance). See ADR 0005.

The vendor SDK is imported lazily inside :mod:`providers`; nothing else in
``quant_platform`` imports it. Captured frames are mapped to
``VendorPayloadBatch`` objects and written through the existing contract
payload intake, so raw capture, PIT timestamps and idempotent inserts are
reused unchanged.
"""

from quant_platform.marketdata.payloads import (
    MarketDataPayloadReport,
    build_market_data_batch,
)
from quant_platform.marketdata.providers import (
    MarketDataProvider,
    RecordedMarketDataProvider,
    YFinanceMarketDataProvider,
)
from quant_platform.marketdata.service import (
    MarketDataFetchReport,
    MarketDataSymbolReport,
    fetch_and_store_market_data,
)
from quant_platform.marketdata.universe import (
    DEFAULT_UNIVERSE,
    OPTIONAL_UNIVERSE,
    UniverseInstrument,
    universe_symbols,
)

__all__ = [
    "DEFAULT_UNIVERSE",
    "OPTIONAL_UNIVERSE",
    "MarketDataFetchReport",
    "MarketDataPayloadReport",
    "MarketDataProvider",
    "MarketDataSymbolReport",
    "RecordedMarketDataProvider",
    "UniverseInstrument",
    "YFinanceMarketDataProvider",
    "build_market_data_batch",
    "fetch_and_store_market_data",
    "universe_symbols",
]
