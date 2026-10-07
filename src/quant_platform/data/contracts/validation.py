"""Offline vendor-payload validation. No database, sockets, or downloads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from quant_platform.data.contracts.errors import VendorContractErrorCode
from quant_platform.data.contracts.hashing import hash_vendor_payload_batch
from quant_platform.data.contracts.types import (
    ALLOWED_ACTION_TYPES,
    ALLOWED_SESSION_KINDS,
    ALLOWED_SOURCE_KINDS,
    FORBIDDEN_VENDOR_IDENTITY_NAMES,
    NETWORK_SOURCE_KINDS,
    OPEN_SESSION_KINDS,
    DataSourceContract,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
    VendorPayloadValidationIssue,
    VendorPayloadValidationReport,
    normalize_source_identity,
)
from quant_platform.data.validation import (
    DataValidationError,
    IngestionErrorCode,
    ensure_utc,
    parse_decimal,
    require_available_after_observation,
    validate_ohlc,
)

_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "database_url",
        "access_token",
        "refresh_token",
        "authorization",
        "bearer",
    }
)
_TOKEN_URL = re.compile(
    r"(?i)https?://[^\s]*[?&](?:api_key|apikey|token|access_token|password|secret)="
)
_FORBIDDEN_TERMS = (
    "pnl",
    "returns",
    "sharpe",
    "drawdown",
    "strategy",
    "strategies",
    "signal",
    "signals",
    "order",
    "orders",
    "fill",
    "fills",
    "trade",
    "trades",
    "position",
    "positions",
    "portfolio",
    "broker",
    "brokers",
    "trading",
    "execution",
)
_FORBIDDEN_TERM = re.compile(
    r"(?i)\b(?:" + "|".join(re.escape(term) for term in _FORBIDDEN_TERMS) + r")\b"
)
_SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def validate_daily_bar_payload(
    payload: VendorDailyBarPayload,
    *,
    record_index: int | None = None,
) -> VendorPayloadValidationReport:
    issues: list[VendorPayloadValidationIssue] = []
    _check_symbol(
        payload.symbol, issues, record_kind="daily_bar", record_index=record_index
    )
    _check_source_name(
        payload.source_name,
        issues,
        record_kind="daily_bar",
        record_index=record_index,
    )
    observation = _check_utc(
        payload.observation_time,
        field="observation_time",
        issues=issues,
        record_kind="daily_bar",
        record_index=record_index,
    )
    available = _check_utc(
        payload.available_time,
        field="available_time",
        issues=issues,
        record_kind="daily_bar",
        record_index=record_index,
    )
    _check_utc(
        payload.ingestion_time,
        field="ingestion_time",
        issues=issues,
        record_kind="daily_bar",
        record_index=record_index,
    )
    if observation is not None and available is not None:
        try:
            require_available_after_observation(observation, available)
        except DataValidationError as exc:
            issues.append(
                _issue(
                    VendorContractErrorCode.LOOKAHEAD,
                    str(exc),
                    field="available_time",
                    record_kind="daily_bar",
                    record_index=record_index,
                )
            )
    _check_ohlc(payload, issues, record_index=record_index)
    _scan_mappings(
        payload.raw_payload,
        payload.metadata,
        issues,
        record_kind="daily_bar",
        record_index=record_index,
    )
    return _report(issues)


def validate_corporate_action_payload(
    payload: VendorCorporateActionPayload,
    *,
    record_index: int | None = None,
) -> VendorPayloadValidationReport:
    issues: list[VendorPayloadValidationIssue] = []
    _check_symbol(
        payload.symbol,
        issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    _check_source_name(
        payload.source_name,
        issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    _check_utc(
        payload.effective_time,
        field="effective_time",
        issues=issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    _check_utc(
        payload.available_time,
        field="available_time",
        issues=issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    _check_utc(
        payload.observation_time,
        field="observation_time",
        issues=issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    _check_utc(
        payload.ingestion_time,
        field="ingestion_time",
        issues=issues,
        record_kind="corporate_action",
        record_index=record_index,
    )
    if payload.action_type.strip() not in ALLOWED_ACTION_TYPES:
        issues.append(
            _issue(
                VendorContractErrorCode.INVALID_ACTION_TYPE,
                f"unsupported action_type {payload.action_type!r}",
                field="action_type",
                record_kind="corporate_action",
                record_index=record_index,
            )
        )
    for field_name, number in (
        ("quantity_before", payload.quantity_before),
        ("quantity_after", payload.quantity_after),
        ("cash_amount", payload.cash_amount),
    ):
        if number is None:
            continue
        try:
            parsed = parse_decimal(number, field=field_name)
        except DataValidationError as exc:
            issues.append(
                _issue(
                    VendorContractErrorCode.INVALID_NUMBER,
                    str(exc),
                    field=field_name,
                    record_kind="corporate_action",
                    record_index=record_index,
                )
            )
            continue
        if parsed < 0:
            issues.append(
                _issue(
                    VendorContractErrorCode.INVALID_NUMBER,
                    f"{field_name} must be non-negative",
                    field=field_name,
                    record_kind="corporate_action",
                    record_index=record_index,
                )
            )
    _scan_mappings(
        payload.raw_payload,
        payload.metadata,
        issues,
        record_kind="corporate_action",
        record_index=record_index,
        extra_text=payload.note,
    )
    return _report(issues)


def validate_market_session_payload(
    payload: VendorMarketSessionPayload,
    *,
    record_index: int | None = None,
) -> VendorPayloadValidationReport:
    issues: list[VendorPayloadValidationIssue] = []
    if payload.symbol is not None and not payload.symbol.strip():
        issues.append(
            _issue(
                VendorContractErrorCode.EMPTY_SYMBOL,
                "symbol must not be empty when provided",
                field="symbol",
                record_kind="market_session",
                record_index=record_index,
            )
        )
    _check_source_name(
        payload.source_name,
        issues,
        record_kind="market_session",
        record_index=record_index,
    )
    if not payload.calendar_code.strip():
        issues.append(
            _issue(
                VendorContractErrorCode.VALIDATION_ERROR,
                "calendar_code is required",
                field="calendar_code",
                record_kind="market_session",
                record_index=record_index,
            )
        )
    _check_utc(
        payload.observation_time,
        field="observation_time",
        issues=issues,
        record_kind="market_session",
        record_index=record_index,
    )
    _check_utc(
        payload.available_time,
        field="available_time",
        issues=issues,
        record_kind="market_session",
        record_index=record_index,
    )
    _check_utc(
        payload.ingestion_time,
        field="ingestion_time",
        issues=issues,
        record_kind="market_session",
        record_index=record_index,
    )
    kind = payload.session_kind.strip()
    if kind not in ALLOWED_SESSION_KINDS:
        issues.append(
            _issue(
                VendorContractErrorCode.INVALID_SESSION_KIND,
                f"unsupported session_kind {payload.session_kind!r}",
                field="session_kind",
                record_kind="market_session",
                record_index=record_index,
            )
        )
    elif payload.is_open != (kind in OPEN_SESSION_KINDS):
        issues.append(
            _issue(
                VendorContractErrorCode.INVALID_SESSION_KIND,
                "is_open must match session_kind",
                field="is_open",
                record_kind="market_session",
                record_index=record_index,
            )
        )
    _scan_mappings(
        payload.raw_payload,
        payload.metadata,
        issues,
        record_kind="market_session",
        record_index=record_index,
        extra_text=payload.note,
    )
    return _report(issues)


def validate_vendor_payload_batch(
    batch: VendorPayloadBatch,
) -> VendorPayloadValidationReport:
    issues: list[VendorPayloadValidationIssue] = []
    issues.extend(_validate_contract(batch.contract, expected_source=batch.source_name))
    _check_source_name(
        batch.source_name, issues, record_kind="batch", record_index=None
    )
    for index, bar in enumerate(batch.daily_bars):
        if bar.source_name != batch.source_name:
            issues.append(
                _issue(
                    VendorContractErrorCode.EMPTY_SOURCE_NAME,
                    "daily bar source_name must match the batch",
                    field="source_name",
                    record_kind="daily_bar",
                    record_index=index,
                )
            )
        issues.extend(validate_daily_bar_payload(bar, record_index=index).issues)
    for index, action in enumerate(batch.corporate_actions):
        if action.source_name != batch.source_name:
            issues.append(
                _issue(
                    VendorContractErrorCode.EMPTY_SOURCE_NAME,
                    "corporate action source_name must match the batch",
                    field="source_name",
                    record_kind="corporate_action",
                    record_index=index,
                )
            )
        issues.extend(
            validate_corporate_action_payload(action, record_index=index).issues
        )
    for index, session in enumerate(batch.market_sessions):
        if session.source_name != batch.source_name:
            issues.append(
                _issue(
                    VendorContractErrorCode.EMPTY_SOURCE_NAME,
                    "market session source_name must match the batch",
                    field="source_name",
                    record_kind="market_session",
                    record_index=index,
                )
            )
        issues.extend(
            validate_market_session_payload(session, record_index=index).issues
        )
    payload_hash = hash_vendor_payload_batch(batch)
    return VendorPayloadValidationReport(
        ok=not issues,
        issues=tuple(issues),
        payload_hash=payload_hash,
    )


def _validate_contract(
    contract: DataSourceContract,
    *,
    expected_source: str,
) -> list[VendorPayloadValidationIssue]:
    issues: list[VendorPayloadValidationIssue] = []
    _check_source_name(
        contract.source_name, issues, record_kind="contract", record_index=None
    )
    if contract.source_name != expected_source:
        issues.append(
            _issue(
                VendorContractErrorCode.EMPTY_SOURCE_NAME,
                "contract source_name must match the batch",
                field="source_name",
                record_kind="contract",
            )
        )
    if contract.source_kind not in ALLOWED_SOURCE_KINDS:
        issues.append(
            _issue(
                VendorContractErrorCode.INVALID_SOURCE_KIND,
                f"unsupported source_kind {contract.source_kind!r}",
                field="source_kind",
                record_kind="contract",
            )
        )
    if contract.requires_network and contract.source_kind not in NETWORK_SOURCE_KINDS:
        issues.append(
            _issue(
                VendorContractErrorCode.NETWORK_REQUIRED,
                "only vendor_api data source contracts may require network",
                field="requires_network",
                record_kind="contract",
            )
        )
    if contract.requires_credentials:
        issues.append(
            _issue(
                VendorContractErrorCode.CREDENTIALS_REQUIRED,
                "data source contracts must not require credentials in this phase",
                field="requires_credentials",
                record_kind="contract",
            )
        )
    if not contract.pit_required:
        issues.append(
            _issue(
                VendorContractErrorCode.PIT_NOT_REQUIRED,
                "data source contracts must require point-in-time fields",
                field="pit_required",
                record_kind="contract",
            )
        )
    if not contract.capture_raw_payload:
        issues.append(
            _issue(
                VendorContractErrorCode.VALIDATION_ERROR,
                "raw payload capture is required",
                field="capture_raw_payload",
                record_kind="contract",
            )
        )
    return issues


def _check_symbol(
    symbol: str,
    issues: list[VendorPayloadValidationIssue],
    *,
    record_kind: str,
    record_index: int | None,
) -> None:
    if not symbol.strip():
        issues.append(
            _issue(
                VendorContractErrorCode.EMPTY_SYMBOL,
                "symbol is required",
                field="symbol",
                record_kind=record_kind,
                record_index=record_index,
            )
        )


def _check_source_name(
    source_name: str,
    issues: list[VendorPayloadValidationIssue],
    *,
    record_kind: str,
    record_index: int | None,
) -> None:
    token = source_name.strip()
    identity = normalize_source_identity(token)
    if not token:
        issues.append(
            _issue(
                VendorContractErrorCode.EMPTY_SOURCE_NAME,
                "source_name is required",
                field="source_name",
                record_kind=record_kind,
                record_index=record_index,
            )
        )
        return
    if identity in FORBIDDEN_VENDOR_IDENTITY_NAMES:
        issues.append(
            _issue(
                VendorContractErrorCode.REAL_VENDOR_NAME,
                "source_name must not be a real vendor identity",
                field="source_name",
                record_kind=record_kind,
                record_index=record_index,
            )
        )
    if not _SOURCE_NAME.fullmatch(identity):
        issues.append(
            _issue(
                VendorContractErrorCode.EMPTY_SOURCE_NAME,
                "source_name must be a stable lowercase identifier",
                field="source_name",
                record_kind=record_kind,
                record_index=record_index,
            )
        )


def _check_utc(
    value: datetime,
    *,
    field: str,
    issues: list[VendorPayloadValidationIssue],
    record_kind: str,
    record_index: int | None,
) -> datetime | None:
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        code = (
            VendorContractErrorCode.NAIVE_TIMESTAMP
            if exc.code == IngestionErrorCode.NAIVE_TIMESTAMP
            else VendorContractErrorCode.VALIDATION_ERROR
        )
        issues.append(
            _issue(
                code,
                str(exc),
                field=field,
                record_kind=record_kind,
                record_index=record_index,
            )
        )
        return None


def _check_ohlc(
    payload: VendorDailyBarPayload,
    issues: list[VendorPayloadValidationIssue],
    *,
    record_index: int | None,
) -> None:
    try:
        validate_ohlc(
            payload.open,
            payload.high,
            payload.low,
            payload.close,
            payload.volume,
        )
    except DataValidationError as exc:
        issues.append(
            _issue(
                VendorContractErrorCode.INVALID_OHLC,
                str(exc),
                field="ohlc",
                record_kind="daily_bar",
                record_index=record_index,
            )
        )


def _scan_mappings(
    raw_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    issues: list[VendorPayloadValidationIssue],
    *,
    record_kind: str,
    record_index: int | None,
    extra_text: str | None = None,
) -> None:
    _scan_mapping(
        raw_payload,
        issues,
        field="raw_payload",
        record_kind=record_kind,
        record_index=record_index,
    )
    _scan_mapping(
        metadata,
        issues,
        field="metadata",
        record_kind=record_kind,
        record_index=record_index,
    )
    if extra_text:
        _scan_text(
            extra_text,
            issues,
            field="note",
            record_kind=record_kind,
            record_index=record_index,
        )


def _scan_mapping(
    mapping: Mapping[str, Any],
    issues: list[VendorPayloadValidationIssue],
    *,
    field: str,
    record_kind: str,
    record_index: int | None,
) -> None:
    for key, value in mapping.items():
        lowered = str(key).strip().lower()
        if lowered in _SECRET_KEYS or lowered.endswith("_password"):
            issues.append(
                _issue(
                    VendorContractErrorCode.SECRET_IN_METADATA,
                    "payload metadata must not contain secrets",
                    field=field,
                    record_kind=record_kind,
                    record_index=record_index,
                )
            )
        _scan_value(
            key,
            value,
            issues,
            field=field,
            record_kind=record_kind,
            record_index=record_index,
        )


def _scan_value(
    key: object,
    value: object,
    issues: list[VendorPayloadValidationIssue],
    *,
    field: str,
    record_kind: str,
    record_index: int | None,
) -> None:
    _scan_text(
        str(key),
        issues,
        field=field,
        record_kind=record_kind,
        record_index=record_index,
    )
    if isinstance(value, dict):
        _scan_mapping(
            value,
            issues,
            field=field,
            record_kind=record_kind,
            record_index=record_index,
        )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _scan_value(
                key,
                item,
                issues,
                field=field,
                record_kind=record_kind,
                record_index=record_index,
            )
        return
    if isinstance(value, str):
        _scan_text(
            value,
            issues,
            field=field,
            record_kind=record_kind,
            record_index=record_index,
        )


def _scan_text(
    text: str,
    issues: list[VendorPayloadValidationIssue],
    *,
    field: str,
    record_kind: str,
    record_index: int | None,
) -> None:
    if _TOKEN_URL.search(text):
        issues.append(
            _issue(
                VendorContractErrorCode.TOKEN_URL,
                "payload must not contain URLs with credential query parameters",
                field=field,
                record_kind=record_kind,
                record_index=record_index,
            )
        )
    if _FORBIDDEN_TERM.search(text):
        issues.append(
            _issue(
                VendorContractErrorCode.FORBIDDEN_TERM,
                "payload must not contain trading or performance terms",
                field=field,
                record_kind=record_kind,
                record_index=record_index,
            )
        )


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
    record_kind: str | None = None,
    record_index: int | None = None,
) -> VendorPayloadValidationIssue:
    return VendorPayloadValidationIssue(
        code=code,
        message=message,
        field=field,
        record_kind=record_kind,
        record_index=record_index,
    )


def _report(
    issues: Sequence[VendorPayloadValidationIssue],
    *,
    payload_hash: str = "",
) -> VendorPayloadValidationReport:
    return VendorPayloadValidationReport(
        ok=not issues,
        issues=tuple(issues),
        payload_hash=payload_hash,
    )
