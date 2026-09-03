"""Deterministic vendor-payload hashes. No wall-clock, secrets, or paths."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from quant_platform.data.contracts.types import (
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
)
from quant_platform.data.payload import redact_payload_secrets

VENDOR_PAYLOAD_HASH_KIND = "vendor_payload_batch"
VENDOR_PAYLOAD_HASH_FORMAT_VERSION = 1
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECIMAL_QUANT = Decimal("0.00000001")
_WALL_CLOCK_KEYS = frozenset(
    {
        "ingestion_time",
        "ingested_at",
        "created_at",
        "received_at",
        "wall_clock",
        "now",
    }
)
_PATH_KEYS = frozenset(
    {
        "path",
        "file_path",
        "absolute_path",
        "output_dir",
        "base_dir",
        "fixtures_dir",
        "artifact_path",
    }
)


def jsonable_vendor_payload(value: object) -> object:
    """JSON-safe mapping for artifacts. Datetimes become canonical UTC strings."""
    return _jsonable(value)


def sha256_canonical_mapping(value: object) -> str:
    """SHA-256 of canonical JSON. Format ``sha256:<64 hex>``."""
    return _sha256_canonical(value)


def is_sha256_digest(value: str) -> bool:
    return bool(_SHA256_PATTERN.fullmatch(value))


def hash_vendor_payload_batch(batch: VendorPayloadBatch) -> str:
    """SHA-256 of a canonical batch. Format ``sha256:<64 hex>``."""
    payload = {
        "kind": VENDOR_PAYLOAD_HASH_KIND,
        "version": VENDOR_PAYLOAD_HASH_FORMAT_VERSION,
        "source_name": batch.source_name,
        "contract": _jsonable(dict(batch.contract.as_mapping())),
        "daily_bars": sorted(
            (_canonical_daily_bar(item) for item in batch.daily_bars),
            key=_bar_sort_key,
        ),
        "corporate_actions": sorted(
            (_canonical_corporate_action(item) for item in batch.corporate_actions),
            key=_action_sort_key,
        ),
        "market_sessions": sorted(
            (_canonical_market_session(item) for item in batch.market_sessions),
            key=_session_sort_key,
        ),
    }
    return _sha256_canonical(payload)


def _canonical_daily_bar(item: VendorDailyBarPayload) -> dict[str, object]:
    return {
        "kind": "daily_bar",
        "symbol": item.symbol,
        "source_name": item.source_name,
        "observation_time": _canonical_datetime(item.observation_time),
        "available_time": _canonical_datetime(item.available_time),
        "open": _canonical_decimal(item.open),
        "high": _canonical_decimal(item.high),
        "low": _canonical_decimal(item.low),
        "close": _canonical_decimal(item.close),
        "volume": _canonical_decimal(item.volume),
        "is_correction": item.is_correction,
        "correction_reason": item.correction_reason or "",
        "raw_payload": _sanitize_mapping(item.raw_payload),
        "metadata": _sanitize_mapping(item.metadata),
    }


def _canonical_corporate_action(
    item: VendorCorporateActionPayload,
) -> dict[str, object]:
    return {
        "kind": "corporate_action",
        "symbol": item.symbol,
        "source_name": item.source_name,
        "action_type": item.action_type,
        "effective_time": _canonical_datetime(item.effective_time),
        "available_time": _canonical_datetime(item.available_time),
        "observation_time": _canonical_datetime(item.observation_time),
        "quantity_before": _canonical_decimal(item.quantity_before),
        "quantity_after": _canonical_decimal(item.quantity_after),
        "cash_amount": _canonical_decimal(item.cash_amount),
        "currency": item.currency or "",
        "note": item.note or "",
        "raw_payload": _sanitize_mapping(item.raw_payload),
        "metadata": _sanitize_mapping(item.metadata),
    }


def _canonical_market_session(item: VendorMarketSessionPayload) -> dict[str, object]:
    return {
        "kind": "market_session",
        "symbol": item.symbol or "",
        "source_name": item.source_name,
        "calendar_code": item.calendar_code,
        "session_date": item.session_date.isoformat(),
        "observation_time": _canonical_datetime(item.observation_time),
        "available_time": _canonical_datetime(item.available_time),
        "session_kind": item.session_kind,
        "is_open": item.is_open,
        "note": item.note or "",
        "raw_payload": _sanitize_mapping(item.raw_payload),
        "metadata": _sanitize_mapping(item.metadata),
    }


def _sanitize_mapping(payload: Mapping[str, Any]) -> dict[str, object]:
    redacted = redact_payload_secrets(payload)
    converted = _jsonable(_drop_excluded(redacted))
    if not isinstance(converted, dict):
        return {}
    return {str(key): item for key, item in converted.items()}


def _drop_excluded(value: object) -> object:
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if lowered in _WALL_CLOCK_KEYS or lowered in _PATH_KEYS:
                continue
            if isinstance(item, str) and _is_absolute_path(item):
                continue
            cleaned[str(key)] = _drop_excluded(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_drop_excluded(item) for item in value]
    return value


def _is_absolute_path(value: str) -> bool:
    token = value.strip()
    if not token or "://" in token:
        return False
    return Path(token).is_absolute()


def _canonical_datetime(value: datetime) -> str:
    utc = value.astimezone(UTC) if value.tzinfo is not None else value
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    quantized = value.quantize(_DECIMAL_QUANT, rounding=ROUND_HALF_EVEN)
    return format(quantized, "f")


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _sha256_canonical(value: object) -> str:
    blob = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _bar_sort_key(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item.get("symbol", "")),
        str(item.get("observation_time", "")),
        str(item.get("available_time", "")),
        str(item.get("open", "")),
    )


def _action_sort_key(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item.get("symbol", "")),
        str(item.get("effective_time", "")),
        str(item.get("available_time", "")),
        str(item.get("action_type", "")),
    )


def _session_sort_key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("calendar_code", "")),
        str(item.get("session_date", "")),
        str(item.get("session_kind", "")),
    )
