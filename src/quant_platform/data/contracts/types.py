"""Vendor-agnostic payload types.

The contracts package itself never opens a network connection. Since ADR
0005 a ``vendor_api`` source kind exists so the separate
``quant_platform.marketdata`` adapter can hand real captured payloads to the
same intake path. Brokers and paid vendors stay forbidden identities.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

FORBIDDEN_VENDOR_IDENTITY_NAMES = frozenset(
    {
        "alpaca",
        "alphavantage",
        "alpha_vantage",
        "binance",
        "bloomberg",
        "coinbase",
        "finnhub",
        "iex",
        "interactivebrokers",
        "ibkr",
        "nasdaq",
        "polygon",
        "refinitiv",
        "tiingo",
    }
)

ALLOWED_SOURCE_KINDS = frozenset({"offline_fixture", "local_csv", "vendor_api"})
NETWORK_SOURCE_KINDS = frozenset({"vendor_api"})
ALLOWED_ACTION_TYPES = frozenset(
    {"split", "reverse_split", "dividend", "symbol_change", "delisting"}
)
ALLOWED_SESSION_KINDS = frozenset(
    {"open", "holiday", "half_session", "exceptional_close"}
)
OPEN_SESSION_KINDS = frozenset({"open", "half_session"})


class DataVendorCapability(StrEnum):
    DAILY_BARS = "daily_bars"
    CORPORATE_ACTIONS = "corporate_actions"
    MARKET_SESSIONS = "market_sessions"


class DataSourceKind(StrEnum):
    OFFLINE_FIXTURE = "offline_fixture"
    LOCAL_CSV = "local_csv"
    VENDOR_API = "vendor_api"


@dataclass(frozen=True, slots=True)
class DataSourceContract:
    """Identity and capability flags for a data source adapter.

    ``requires_network`` may only be true for ``vendor_api`` sources.
    ``requires_credentials`` stays false: no API keys live in this repo.
    This object is not a client.
    """

    source_name: str
    source_kind: str
    capabilities: tuple[DataVendorCapability, ...]
    requires_network: bool
    requires_credentials: bool
    pit_required: bool
    capture_raw_payload: bool = True

    def as_mapping(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "capabilities": [item.value for item in self.capabilities],
            "requires_network": self.requires_network,
            "requires_credentials": self.requires_credentials,
            "pit_required": self.pit_required,
            "capture_raw_payload": self.capture_raw_payload,
        }


@dataclass(frozen=True, slots=True)
class VendorDailyBarPayload:
    """Canonical daily-bar capture before silver mapping. Not a quote feed."""

    symbol: str
    source_name: str
    observation_time: datetime
    available_time: datetime
    ingestion_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    raw_payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    is_correction: bool = False
    correction_reason: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "daily_bar",
            "symbol": self.symbol,
            "source_name": self.source_name,
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "ingestion_time": self.ingestion_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "raw_payload": dict(self.raw_payload),
            "metadata": dict(self.metadata),
            "is_correction": self.is_correction,
            "correction_reason": self.correction_reason,
        }


@dataclass(frozen=True, slots=True)
class VendorCorporateActionPayload:
    """Canonical corporate-action capture. Not an adjusted-price feed."""

    symbol: str
    source_name: str
    action_type: str
    effective_time: datetime
    available_time: datetime
    observation_time: datetime
    ingestion_time: datetime
    raw_payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    quantity_before: Decimal | None = None
    quantity_after: Decimal | None = None
    cash_amount: Decimal | None = None
    currency: str | None = None
    note: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "corporate_action",
            "symbol": self.symbol,
            "source_name": self.source_name,
            "action_type": self.action_type,
            "effective_time": self.effective_time,
            "available_time": self.available_time,
            "observation_time": self.observation_time,
            "ingestion_time": self.ingestion_time,
            "quantity_before": self.quantity_before,
            "quantity_after": self.quantity_after,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
            "note": self.note,
            "raw_payload": dict(self.raw_payload),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class VendorMarketSessionPayload:
    """Canonical market-session capture. Not an exchange live calendar."""

    source_name: str
    calendar_code: str
    session_date: date
    observation_time: datetime
    available_time: datetime
    ingestion_time: datetime
    session_kind: str
    is_open: bool
    raw_payload: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    symbol: str | None = None
    note: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "market_session",
            "symbol": self.symbol,
            "source_name": self.source_name,
            "calendar_code": self.calendar_code,
            "session_date": self.session_date,
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "ingestion_time": self.ingestion_time,
            "session_kind": self.session_kind,
            "is_open": self.is_open,
            "note": self.note,
            "raw_payload": dict(self.raw_payload),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class VendorPayloadBatch:
    """Offline batch of captured payloads. Not a download response."""

    source_name: str
    contract: DataSourceContract
    daily_bars: tuple[VendorDailyBarPayload, ...] = ()
    corporate_actions: tuple[VendorCorporateActionPayload, ...] = ()
    market_sessions: tuple[VendorMarketSessionPayload, ...] = ()

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "vendor_payload_batch",
            "source_name": self.source_name,
            "contract": self.contract.as_mapping(),
            "daily_bars": [item.as_mapping() for item in self.daily_bars],
            "corporate_actions": [item.as_mapping() for item in self.corporate_actions],
            "market_sessions": [item.as_mapping() for item in self.market_sessions],
        }


@dataclass(frozen=True, slots=True)
class VendorPayloadValidationIssue:
    code: str
    message: str
    field: str | None = None
    record_kind: str | None = None
    record_index: int | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "record_kind": self.record_kind,
            "record_index": self.record_index,
        }


@dataclass(frozen=True, slots=True)
class VendorPayloadValidationReport:
    ok: bool
    issues: tuple[VendorPayloadValidationIssue, ...]
    payload_hash: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "issues": [item.as_mapping() for item in self.issues],
            "payload_hash": self.payload_hash,
        }


def default_offline_contract(
    source_name: str = "offline_fixture",
    *,
    source_kind: str = DataSourceKind.OFFLINE_FIXTURE.value,
    capabilities: Sequence[DataVendorCapability] | None = None,
) -> DataSourceContract:
    caps = (
        tuple(capabilities)
        if capabilities is not None
        else (
            DataVendorCapability.DAILY_BARS,
            DataVendorCapability.CORPORATE_ACTIONS,
            DataVendorCapability.MARKET_SESSIONS,
        )
    )
    return DataSourceContract(
        source_name=source_name.strip(),
        source_kind=source_kind.strip(),
        capabilities=caps,
        requires_network=False,
        requires_credentials=False,
        pit_required=True,
        capture_raw_payload=True,
    )


def normalize_source_identity(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")
