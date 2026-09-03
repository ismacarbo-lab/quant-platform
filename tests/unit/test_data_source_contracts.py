"""Offline vendor-agnostic data source contracts. No HTTP, no vendors."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from quant_platform.data.contracts import (
    FakeVendorPayloadProvider,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
    VendorPayloadValidationReport,
    default_offline_contract,
    hash_vendor_payload_batch,
    validate_corporate_action_payload,
    validate_daily_bar_payload,
    validate_market_session_payload,
    validate_vendor_payload_batch,
)
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    ENABLED_CAPABILITIES,
)
from quant_platform.release.guards import (
    detect_contracts_networking,
    detect_real_vendor_clients,
)

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "src" / "quant_platform"
_FIXTURE = _ROOT / "tests" / "fixtures" / "data_source_contracts" / "batch.json"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_INGESTION = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)


def _bar(**overrides: object) -> VendorDailyBarPayload:
    base: dict[str, object] = {
        "symbol": "ACME",
        "source_name": "offline_fixture",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9.5"),
        "close": Decimal("10.5"),
        "volume": Decimal("1000"),
        "raw_payload": {"symbol": "ACME"},
        "metadata": {"fixture_id": "acme-bar"},
    }
    base.update(overrides)
    return VendorDailyBarPayload(**base)  # type: ignore[arg-type]


def _action(**overrides: object) -> VendorCorporateActionPayload:
    base: dict[str, object] = {
        "symbol": "ACME",
        "source_name": "offline_fixture",
        "action_type": "split",
        "effective_time": datetime(2024, 1, 3, tzinfo=UTC),
        "available_time": datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        "observation_time": datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "quantity_before": Decimal("1"),
        "quantity_after": Decimal("2"),
        "raw_payload": {"action_type": "split"},
        "metadata": {"fixture_id": "acme-split"},
    }
    base.update(overrides)
    return VendorCorporateActionPayload(**base)  # type: ignore[arg-type]


def _session(**overrides: object) -> VendorMarketSessionPayload:
    base: dict[str, object] = {
        "source_name": "offline_fixture",
        "calendar_code": "TEST",
        "session_date": date(2024, 1, 2),
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "session_kind": "open",
        "is_open": True,
        "raw_payload": {"session_kind": "open"},
        "metadata": {"fixture_id": "test-session"},
        "symbol": "ACME",
    }
    base.update(overrides)
    return VendorMarketSessionPayload(**base)  # type: ignore[arg-type]


def _codes(report: VendorPayloadValidationReport) -> set[str]:
    return {item.code for item in report.issues}


def test_valid_daily_bar_payload_passes() -> None:
    report = validate_daily_bar_payload(_bar())
    assert report.ok is True
    assert report.issues == ()


def test_available_time_not_after_observation_fails() -> None:
    observation = datetime(2024, 1, 2, tzinfo=UTC)
    report = validate_daily_bar_payload(
        _bar(observation_time=observation, available_time=observation)
    )
    assert report.ok is False
    assert "lookahead" in _codes(report)


def test_naive_datetime_fails() -> None:
    report = validate_daily_bar_payload(_bar(observation_time=datetime(2024, 1, 2)))
    assert report.ok is False
    assert "naive_timestamp" in _codes(report)


def test_invalid_ohlc_fails() -> None:
    report = validate_daily_bar_payload(_bar(high=Decimal("8"), low=Decimal("9")))
    assert report.ok is False
    assert "invalid_ohlc" in _codes(report)


def test_valid_corporate_action_passes() -> None:
    report = validate_corporate_action_payload(_action())
    assert report.ok is True


def test_valid_market_session_passes() -> None:
    report = validate_market_session_payload(_session())
    assert report.ok is True


def test_batch_hash_is_stable_and_order_independent() -> None:
    first = _bar()
    second = _bar(
        observation_time=datetime(2024, 1, 3, tzinfo=UTC),
        available_time=datetime(2024, 1, 4, tzinfo=UTC),
        close=Decimal("10.75"),
        metadata={"fixture_id": "acme-bar-2"},
    )
    contract = default_offline_contract()
    left = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=contract,
        daily_bars=(first, second),
    )
    right = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=contract,
        daily_bars=(second, first),
    )
    digest = hash_vendor_payload_batch(left)
    assert _SHA256.fullmatch(digest)
    assert digest == hash_vendor_payload_batch(right)
    assert digest == hash_vendor_payload_batch(left)


def test_batch_hash_changes_when_payload_changes() -> None:
    original = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract(),
        daily_bars=(_bar(),),
    )
    changed = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract(),
        daily_bars=(_bar(close=Decimal("12")),),
    )
    assert hash_vendor_payload_batch(original) != hash_vendor_payload_batch(changed)


def test_batch_hash_excludes_ingestion_time() -> None:
    left = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract(),
        daily_bars=(_bar(),),
    )
    right = VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract(),
        daily_bars=(_bar(ingestion_time=_INGESTION + timedelta(hours=3)),),
    )
    assert hash_vendor_payload_batch(left) == hash_vendor_payload_batch(right)


def test_fake_provider_offline_load_batch() -> None:
    provider = FakeVendorPayloadProvider()
    batch = provider.load_batch()
    report = validate_vendor_payload_batch(batch)
    assert report.ok is True
    assert _SHA256.fullmatch(report.payload_hash)
    assert batch.contract.requires_network is False
    assert batch.contract.requires_credentials is False
    assert batch.daily_bars[0].symbol == "ACME"


def test_fake_provider_loads_local_fixture_file() -> None:
    provider = FakeVendorPayloadProvider(fixtures_path=_FIXTURE)
    batch = provider.load_batch()
    assert batch.source_name == "offline_fixture"
    assert validate_vendor_payload_batch(batch).ok is True


def test_metadata_with_token_secret_fails() -> None:
    report = validate_daily_bar_payload(_bar(metadata={"token": "test-token-not-real"}))
    assert report.ok is False
    assert "secret_in_metadata" in _codes(report)


def test_url_with_api_key_fails() -> None:
    report = validate_daily_bar_payload(
        _bar(
            metadata={"feed": "https://example.invalid/v1/bars?api_key=not-a-real-key"}
        )
    )
    assert report.ok is False
    assert "token_url" in _codes(report)


def test_forbidden_trading_and_performance_terms_fail() -> None:
    report = validate_daily_bar_payload(
        _bar(metadata={"note": "this is not trading PnL or returns"})
    )
    assert report.ok is False
    assert "forbidden_term" in _codes(report)


def test_contracts_package_has_no_http_or_vendor_imports() -> None:
    assert detect_contracts_networking(_PACKAGE) == ()
    assert detect_real_vendor_clients(_PACKAGE) == ()


def test_no_real_vendor_client_is_implemented() -> None:
    enabled = set(ENABLED_CAPABILITIES)
    disabled = set(DISABLED_CAPABILITIES)
    assert "vendor_agnostic_data_contracts" in enabled
    assert "external_market_data_vendors" in disabled
    contracts = _PACKAGE / "data" / "contracts"
    forbidden = {
        "polygon.py",
        "yfinance.py",
        "alpaca.py",
        "binance.py",
        "yahoo.py",
        "tiingo.py",
    }
    present = {path.name for path in contracts.glob("*.py")}
    assert present.isdisjoint(forbidden)


def test_contract_docs_exist_without_database_url() -> None:
    adr = _ROOT / "docs" / "adr" / "0004-vendor-agnostic-data-source-contract.md"
    spec = _ROOT / "docs" / "data" / "DATA_SOURCE_CONTRACTS.md"
    assert adr.is_file()
    assert spec.is_file()
    for path in (adr, spec):
        text = path.read_text(encoding="utf-8")
        assert "DATABASE_URL" not in text
        assert "postgresql+psycopg://" not in text.lower()
        lowered = text.lower()
        assert "no trading" in lowered or "not a trading" in lowered
        assert "pnl" in lowered
        assert "returns" in lowered
        assert "offline" in lowered
