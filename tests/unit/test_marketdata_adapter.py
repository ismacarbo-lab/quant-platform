"""Offline tests for the market data adapter. No network; recorded fixtures."""

from __future__ import annotations

import ast
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_request,
)
from quant_platform.data.contracts.validation import validate_vendor_payload_batch
from quant_platform.marketdata.payloads import (
    StoredBarSnapshot,
    build_market_data_batch,
    market_data_contract,
    session_times,
)
from quant_platform.marketdata.providers import (
    MarketDataProviderError,
    RecordedMarketDataProvider,
    normalize_history_frame,
)
from quant_platform.marketdata.universe import (
    DEFAULT_UNIVERSE,
    OPTIONAL_UNIVERSE,
    resolve_universe,
    universe_symbols,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests" / "fixtures" / "marketdata"
_NOW = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)


def _spy_frame() -> pd.DataFrame:
    provider = RecordedMarketDataProvider(_FIXTURES)
    return provider.fetch_history("SPY", start=date(2024, 1, 1), end=date(2024, 3, 31))


def test_default_universe_is_diversified_and_unique() -> None:
    symbols = universe_symbols()
    assert len(symbols) == len(set(symbols))
    assert {"SPY", "TLT", "GLD", "BIL"} <= set(symbols)
    roles = {item.role for item in DEFAULT_UNIVERSE}
    assert roles == {"risk", "defensive", "cash"}
    assert OPTIONAL_UNIVERSE[0].symbol == "BTC-USD"
    custom = resolve_universe(["spy", "eth-usd", "SPY"])
    assert [item.symbol for item in custom] == ["SPY", "ETH-USD"]
    assert custom[1].asset_class == "crypto"


def test_recorded_provider_filters_window_and_normalizes_columns() -> None:
    frame = _spy_frame()
    assert list(frame.columns) == [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Dividends",
        "Stock Splits",
    ]
    assert frame.index.tz is not None
    assert len(frame) == 60
    provider = RecordedMarketDataProvider(_FIXTURES)
    with pytest.raises(MarketDataProviderError):
        provider.fetch_history("NOPE", start=date(2024, 1, 1), end=date(2024, 1, 31))


def test_normalize_history_frame_handles_missing_action_columns() -> None:
    raw = pd.DataFrame(
        {"Open": [1.0], "High": [1.1], "Low": [0.9], "Close": [1.05], "Volume": [10]},
        index=pd.to_datetime(["2024-01-02"]),
    )
    frame = normalize_history_frame(raw)
    assert float(frame["Dividends"].iloc[0]) == 0.0
    assert str(frame.index.tz) == "UTC"


def test_session_times_are_pit_consistent() -> None:
    observation, available = session_times(date(2024, 1, 2), asset_class="etf")
    assert observation == datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
    assert available > observation
    crypto_obs, crypto_avail = session_times(date(2024, 1, 2), asset_class="crypto")
    assert crypto_obs.date() == date(2024, 1, 2)
    assert crypto_avail > crypto_obs


def test_market_data_contract_is_vendor_api_without_credentials() -> None:
    contract = market_data_contract("yfinance")
    assert contract.source_kind == "vendor_api"
    assert contract.requires_network is True
    assert contract.requires_credentials is False
    assert contract.pit_required is True


def test_batch_from_recorded_history_validates_and_plans() -> None:
    batch, report = build_market_data_batch(
        _spy_frame(), symbol="SPY", source_name="yfinance", asset_class="etf", now=_NOW
    )
    assert report.rows_received == 60
    assert report.bars_emitted == 60
    assert report.dividends_emitted == 1
    assert report.sanitized_bars == 1
    assert report.splits_seen == 0
    assert report.first_session == date(2024, 1, 2)
    assert report.last_session == date(2024, 3, 25)
    validation = validate_vendor_payload_batch(batch)
    assert validation.ok is True, [issue.code for issue in validation.issues]
    plan = build_contract_payload_intake_plan(
        batch,
        build_contract_payload_intake_request(
            source_name="yfinance", created_by="market_data_fetch", asset_class="etf"
        ),
    )
    assert plan.ok is True, [issue.code for issue in plan.issues]
    assert plan.accepted_counts.daily_bars == 60
    assert plan.accepted_counts.corporate_actions == 1
    dividend = batch.corporate_actions[0]
    assert dividend.action_type == "dividend"
    assert dividend.cash_amount == Decimal("1.6")
    assert dividend.effective_time.date() == date(2024, 3, 15)
    for bar in batch.daily_bars:
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
        assert bar.available_time > bar.observation_time
        assert bar.available_time <= _NOW


def test_splits_are_not_emitted_because_vendor_prices_are_split_adjusted() -> None:
    provider = RecordedMarketDataProvider(_FIXTURES)
    frame = provider.fetch_history("TLT", start=date(2024, 1, 1), end=date(2024, 3, 31))
    batch, report = build_market_data_batch(
        frame, symbol="TLT", source_name="yfinance", asset_class="etf", now=_NOW
    )
    assert report.splits_seen == 1
    assert all(item.action_type == "dividend" for item in batch.corporate_actions)
    assert report.dividends_emitted == 2


def test_incomplete_sessions_are_dropped() -> None:
    frame = _spy_frame()
    early_now = datetime(2024, 3, 25, 21, 30, tzinfo=UTC)  # before availability
    batch, report = build_market_data_batch(
        frame, symbol="SPY", source_name="yfinance", asset_class="etf", now=early_now
    )
    assert report.bars_dropped_incomplete == 1
    assert report.last_session == date(2024, 3, 22)
    assert all(bar.available_time <= early_now for bar in batch.daily_bars)


def test_unchanged_stored_bars_are_skipped_and_restatements_become_corrections() -> (
    None
):
    frame = _spy_frame()
    first_day = frame.index[0]
    second_day = frame.index[1]
    stored = {
        first_day.date(): StoredBarSnapshot(
            open=Decimal(repr(float(frame.loc[first_day, "Open"]))),
            high=Decimal(repr(float(frame.loc[first_day, "High"]))),
            low=Decimal(repr(float(frame.loc[first_day, "Low"]))),
            close=Decimal(repr(float(frame.loc[first_day, "Close"]))),
            volume=Decimal(int(frame.loc[first_day, "Volume"])),
        ),
        second_day.date(): StoredBarSnapshot(
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=None,
        ),
    }
    batch, report = build_market_data_batch(
        frame,
        symbol="SPY",
        source_name="yfinance",
        asset_class="etf",
        now=_NOW,
        stored_bars=stored,
        stored_dividend_dates={date(2024, 3, 15)},
    )
    assert report.bars_unchanged == 1
    assert report.corrections_emitted == 1
    assert report.dividends_emitted == 0
    correction = next(bar for bar in batch.daily_bars if bar.is_correction)
    assert correction.observation_time.date() == second_day.date()
    assert correction.available_time == _NOW
    assert correction.correction_reason == "vendor_restatement"
    assert validate_vendor_payload_batch(batch).ok is True


def test_invalid_rows_are_dropped_not_fatal() -> None:
    frame = _spy_frame().copy()
    frame.iloc[3, frame.columns.get_loc("Close")] = float("nan")
    frame.iloc[4, frame.columns.get_loc("Open")] = -5.0
    _, report = build_market_data_batch(
        frame, symbol="SPY", source_name="yfinance", asset_class="etf", now=_NOW
    )
    assert report.bars_dropped_invalid == 2
    assert report.bars_emitted == 58


def test_only_providers_module_imports_yfinance_and_lazily() -> None:
    package = _ROOT / "src" / "quant_platform"
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            if "yfinance" in names:
                assert path.name == "providers.py", path
                assert node.col_offset > 0, "yfinance import must be inside a function"
    import quant_platform.marketdata  # noqa: F401

    assert "yfinance" not in sys.modules
