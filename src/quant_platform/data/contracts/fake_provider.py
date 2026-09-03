"""In-memory / local-fixture payload provider. No sockets, secrets, or APIs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.types import (
    DataSourceContract,
    DataVendorCapability,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
    default_offline_contract,
)
from quant_platform.data.contracts.validation import validate_vendor_payload_batch

_SOURCE_NAME = "offline_fixture"
_INGESTION = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)


class FakeVendorPayloadProvider:
    """Synthetic research payloads. Does not download or open sockets."""

    def __init__(
        self,
        *,
        batch: VendorPayloadBatch | None = None,
        fixtures_path: Path | str | None = None,
        validate: bool = True,
    ) -> None:
        self._validate = validate
        if fixtures_path is not None:
            self._batch = _load_fixture_batch(Path(fixtures_path))
        elif batch is not None:
            self._batch = batch
        else:
            self._batch = default_synthetic_batch()
        if validate:
            self._require_valid(self._batch)

    def load_batch(self) -> VendorPayloadBatch:
        """Return the captured synthetic batch. Never touches the network."""
        if self._validate:
            self._require_valid(self._batch)
        return self._batch

    @staticmethod
    def _require_valid(batch: VendorPayloadBatch) -> None:
        report = validate_vendor_payload_batch(batch)
        if report.ok:
            return
        first = report.issues[0]
        raise VendorContractError(first.message, code=first.code)


def default_synthetic_batch() -> VendorPayloadBatch:
    """Fixed fictional ACME sample. Not market data."""
    contract = default_offline_contract(_SOURCE_NAME)
    observation = datetime(2024, 1, 2, tzinfo=UTC)
    available = datetime(2024, 1, 3, tzinfo=UTC)
    bar = VendorDailyBarPayload(
        symbol="ACME",
        source_name=_SOURCE_NAME,
        observation_time=observation,
        available_time=available,
        ingestion_time=_INGESTION,
        open=Decimal("10.00"),
        high=Decimal("11.00"),
        low=Decimal("9.50"),
        close=Decimal("10.50"),
        volume=Decimal("1000"),
        raw_payload={
            "symbol": "ACME",
            "open": "10.00",
            "high": "11.00",
            "low": "9.50",
            "close": "10.50",
            "volume": "1000",
        },
        metadata={"fixture_id": "acme-2024-01-02"},
    )
    action = VendorCorporateActionPayload(
        symbol="ACME",
        source_name=_SOURCE_NAME,
        action_type="split",
        effective_time=datetime(2024, 1, 3, tzinfo=UTC),
        available_time=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        observation_time=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        ingestion_time=_INGESTION,
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
        raw_payload={"action_type": "split", "ratio": "2-for-1"},
        metadata={"fixture_id": "acme-split"},
        note="two-for-one split",
    )
    session = VendorMarketSessionPayload(
        source_name=_SOURCE_NAME,
        calendar_code="TEST",
        session_date=date(2024, 1, 2),
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        ingestion_time=_INGESTION,
        session_kind="open",
        is_open=True,
        raw_payload={"session_kind": "open", "calendar_code": "TEST"},
        metadata={"fixture_id": "test-2024-01-02"},
        symbol="ACME",
    )
    return VendorPayloadBatch(
        source_name=_SOURCE_NAME,
        contract=contract,
        daily_bars=(bar,),
        corporate_actions=(action,),
        market_sessions=(session,),
    )


def _load_fixture_batch(path: Path) -> VendorPayloadBatch:
    if _looks_like_url(path):
        raise VendorContractError(
            "fake provider must not load remote URLs",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    target = path / "batch.json" if path.is_dir() else path
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VendorContractError(
            "fake provider could not read a local fixture batch",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    if not isinstance(raw, dict):
        raise VendorContractError(
            "fixture batch must be a JSON object",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    return _batch_from_mapping(raw)


def _looks_like_url(path: Path) -> bool:
    token = path.as_posix().strip().lower()
    return token.startswith("http://") or token.startswith("https://")


def _batch_from_mapping(raw: Mapping[str, Any]) -> VendorPayloadBatch:
    source_name = str(raw.get("source_name", _SOURCE_NAME))
    contract_raw = raw.get("contract")
    if isinstance(contract_raw, dict):
        contract = _contract_from_mapping(contract_raw, source_name)
    else:
        contract = default_offline_contract(source_name)
    bars = tuple(
        _bar_from_mapping(item, source_name) for item in _as_list(raw.get("daily_bars"))
    )
    actions = tuple(
        _action_from_mapping(item, source_name)
        for item in _as_list(raw.get("corporate_actions"))
    )
    sessions = tuple(
        _session_from_mapping(item, source_name)
        for item in _as_list(raw.get("market_sessions"))
    )
    return VendorPayloadBatch(
        source_name=source_name,
        contract=contract,
        daily_bars=bars,
        corporate_actions=actions,
        market_sessions=sessions,
    )


def _contract_from_mapping(
    raw: Mapping[str, Any],
    source_name: str,
) -> DataSourceContract:
    capabilities_raw = raw.get("capabilities")
    capabilities: Sequence[str]
    if isinstance(capabilities_raw, list):
        capabilities = [str(item) for item in capabilities_raw]
    else:
        capabilities = []
    try:
        caps = tuple(DataVendorCapability(item) for item in capabilities) or (
            DataVendorCapability.DAILY_BARS,
            DataVendorCapability.CORPORATE_ACTIONS,
            DataVendorCapability.MARKET_SESSIONS,
        )
    except ValueError as exc:
        raise VendorContractError(
            "fixture contract capabilities are invalid",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        ) from exc
    return DataSourceContract(
        source_name=str(raw.get("source_name", source_name)),
        source_kind=str(raw.get("source_kind", "offline_fixture")),
        capabilities=caps,
        requires_network=bool(raw.get("requires_network", False)),
        requires_credentials=bool(raw.get("requires_credentials", False)),
        pit_required=bool(raw.get("pit_required", True)),
        capture_raw_payload=bool(raw.get("capture_raw_payload", True)),
    )


def _bar_from_mapping(
    raw: Mapping[str, Any], source_name: str
) -> VendorDailyBarPayload:
    return VendorDailyBarPayload(
        symbol=str(raw["symbol"]),
        source_name=str(raw.get("source_name", source_name)),
        observation_time=_parse_datetime(raw["observation_time"]),
        available_time=_parse_datetime(raw["available_time"]),
        ingestion_time=_parse_datetime(
            raw.get("ingestion_time", _INGESTION.isoformat())
        ),
        open=_parse_decimal(raw["open"]),
        high=_parse_decimal(raw["high"]),
        low=_parse_decimal(raw["low"]),
        close=_parse_decimal(raw["close"]),
        volume=_parse_optional_decimal(raw.get("volume")),
        raw_payload=_as_mapping(raw.get("raw_payload")),
        metadata=_as_mapping(raw.get("metadata")),
        is_correction=bool(raw.get("is_correction", False)),
        correction_reason=(
            None
            if raw.get("correction_reason") is None
            else str(raw.get("correction_reason"))
        ),
    )


def _action_from_mapping(
    raw: Mapping[str, Any],
    source_name: str,
) -> VendorCorporateActionPayload:
    return VendorCorporateActionPayload(
        symbol=str(raw["symbol"]),
        source_name=str(raw.get("source_name", source_name)),
        action_type=str(raw["action_type"]),
        effective_time=_parse_datetime(raw["effective_time"]),
        available_time=_parse_datetime(raw["available_time"]),
        observation_time=_parse_datetime(raw["observation_time"]),
        ingestion_time=_parse_datetime(
            raw.get("ingestion_time", _INGESTION.isoformat())
        ),
        raw_payload=_as_mapping(raw.get("raw_payload")),
        metadata=_as_mapping(raw.get("metadata")),
        quantity_before=_parse_optional_decimal(raw.get("quantity_before")),
        quantity_after=_parse_optional_decimal(raw.get("quantity_after")),
        cash_amount=_parse_optional_decimal(raw.get("cash_amount")),
        currency=None if raw.get("currency") is None else str(raw.get("currency")),
        note=None if raw.get("note") is None else str(raw.get("note")),
    )


def _session_from_mapping(
    raw: Mapping[str, Any],
    source_name: str,
) -> VendorMarketSessionPayload:
    return VendorMarketSessionPayload(
        source_name=str(raw.get("source_name", source_name)),
        calendar_code=str(raw["calendar_code"]),
        session_date=_parse_date(raw["session_date"]),
        observation_time=_parse_datetime(raw["observation_time"]),
        available_time=_parse_datetime(raw["available_time"]),
        ingestion_time=_parse_datetime(
            raw.get("ingestion_time", _INGESTION.isoformat())
        ),
        session_kind=str(raw["session_kind"]),
        is_open=bool(raw["is_open"]),
        raw_payload=_as_mapping(raw.get("raw_payload")),
        metadata=_as_mapping(raw.get("metadata")),
        symbol=None if raw.get("symbol") is None else str(raw.get("symbol")),
        note=None if raw.get("note") is None else str(raw.get("note")),
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    token = str(value).strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    parsed = datetime.fromisoformat(token)
    if parsed.tzinfo is None:
        raise VendorContractError(
            "fixture timestamps must be timezone-aware UTC",
            code=VendorContractErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed.astimezone(UTC)


def _parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _parse_optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return _parse_decimal(value)


def _as_mapping(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    raise VendorContractError(
        "fixture mapping fields must be JSON objects",
        code=VendorContractErrorCode.FIXTURE_UNREADABLE,
    )


def _as_list(value: object) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise VendorContractError(
            "fixture collections must be JSON arrays",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    rows: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise VendorContractError(
                "fixture records must be JSON objects",
                code=VendorContractErrorCode.FIXTURE_UNREADABLE,
            )
        rows.append(item)
    return rows
