"""Research-policy observations. Descriptive only; never signals or orders."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_json,
    manifest_contains_secrets,
    sha256_canonical,
)

POLICY_OUTPUT_KIND = "research_policy_output"
POLICY_OUTPUT_FORMAT_VERSION = 1
POLICY_OUTPUT_HASH_KIND = "research_policy_output"
POLICY_OUTPUT_HASH_FORMAT_VERSION = 1

OBSERVATION_KIND_EVENT_SEEN = "event_seen"
OBSERVATION_KIND_CORPORATE_ACTION_SEEN = "corporate_action_seen"
OBSERVATION_KIND_SESSION_SEEN = "session_seen"
OBSERVATION_KIND_CORRECTION_SEEN = "correction_seen"
OBSERVATION_KIND_MISSING_EXPECTED_EVENT = "missing_expected_event"
OBSERVATION_KIND_UNKNOWN_EVENT = "unknown_event"
OBSERVATION_KIND_POLICY_NOTE = "policy_note"
OBSERVATION_KIND_DATA_QUALITY_SUMMARY = "data_quality_summary"
OBSERVATION_KIND_COVERAGE_SUMMARY = "coverage_summary"
OBSERVATION_KIND_COVERAGE_GAP = "coverage_gap"
OBSERVATION_KIND_INSTRUMENT_SEEN = "instrument_seen"
OBSERVATION_KIND_CORPORATE_ACTION_SUMMARY = "corporate_action_summary"
OBSERVATION_KIND_CORRECTION_SUMMARY = "correction_summary"
OBSERVATION_KIND_TEMPORAL_CONSISTENCY_WARNING = "temporal_consistency_warning"

ALLOWED_OBSERVATION_KINDS = frozenset(
    {
        OBSERVATION_KIND_EVENT_SEEN,
        OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
        OBSERVATION_KIND_SESSION_SEEN,
        OBSERVATION_KIND_CORRECTION_SEEN,
        OBSERVATION_KIND_MISSING_EXPECTED_EVENT,
        OBSERVATION_KIND_UNKNOWN_EVENT,
        OBSERVATION_KIND_POLICY_NOTE,
        OBSERVATION_KIND_DATA_QUALITY_SUMMARY,
        OBSERVATION_KIND_COVERAGE_SUMMARY,
        OBSERVATION_KIND_COVERAGE_GAP,
        OBSERVATION_KIND_INSTRUMENT_SEEN,
        OBSERVATION_KIND_CORPORATE_ACTION_SUMMARY,
        OBSERVATION_KIND_CORRECTION_SUMMARY,
        OBSERVATION_KIND_TEMPORAL_CONSISTENCY_WARNING,
    }
)
OBSERVATION_SEVERITIES = frozenset({"info", "warning", "error"})

FORBIDDEN_OPERATIVE_TOKENS = (
    "buy",
    "sell",
    "hold",
    "signal",
    "weight",
    "target",
    "order",
    "trade",
    "pnl",
    "return",
    "returns",
    "position",
    "portfolio",
    "fill",
    "alpha",
    "exposure",
    "recommendation",
)
_OPERATIVE_PATTERN = re.compile(
    r"\b("
    + "|".join(re.escape(token) for token in FORBIDDEN_OPERATIVE_TOKENS)
    + r")\b",
    re.IGNORECASE,
)


def contains_operative_language(text: str) -> bool:
    """True when text uses investment-decision wording as whole words."""
    return _OPERATIVE_PATTERN.search(text) is not None


def normalize_policy_config(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    """Return a JSON object. Reject non-JSON values, secrets, and operative text."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BacktestError(
            "policy_config must be a JSON object",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    payload = dict(value)
    if any(not isinstance(key, str) or not key.strip() for key in payload):
        raise BacktestError(
            "policy_config keys must be non-empty strings",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    try:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False)
        loaded = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise BacktestError(
            "policy_config must be JSON-serializable",
            code=BacktestErrorCode.INVALID_POLICY,
        ) from exc
    if not isinstance(loaded, dict):
        raise BacktestError(
            "policy_config must be a JSON object",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if manifest_contains_secrets(text):
        raise BacktestError(
            "policy_config must not contain secrets",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if contains_operative_language(text):
        raise BacktestError(
            "policy_config must not contain investment-decision wording",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return dict(loaded)


def canonical_policy_config(config: Mapping[str, object]) -> dict[str, object]:
    return normalize_policy_config(config)


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    observation_time: datetime
    event_time: datetime
    kind: str
    message: str
    severity: str
    instrument_id: str | None = None
    symbol: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = self.kind.strip()
        if kind not in ALLOWED_OBSERVATION_KINDS:
            raise BacktestError(
                "observation kind is not allowed",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "kind", kind)
        severity = self.severity.strip()
        if severity not in OBSERVATION_SEVERITIES:
            raise BacktestError(
                "observation severity must be info, warning, or error",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "severity", severity)
        message = self.message.strip()
        if not message:
            raise BacktestError(
                "observation message must not be empty",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "message", message)
        if self.observation_time.tzinfo is None or self.event_time.tzinfo is None:
            raise BacktestError(
                "observation timestamps must be timezone-aware UTC",
                code=BacktestErrorCode.NAIVE_TIMESTAMP,
            )
        instrument_id = _optional_token(self.instrument_id)
        symbol = _optional_token(self.symbol)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "symbol", symbol)
        metadata = dict(self.metadata)
        blob = self.as_mapping()
        if manifest_contains_secrets(canonical_json(blob)):
            raise BacktestError(
                "observation must not contain secrets",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        if contains_operative_language(canonical_json(blob)):
            raise BacktestError(
                "observation must not contain investment-decision wording",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "metadata", metadata)

    def as_mapping(self) -> dict[str, object]:
        return {
            "observation_time": canonical_datetime(self.observation_time),
            "event_time": canonical_datetime(self.event_time),
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ResearchObservationSummary:
    observation_count: int
    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    warning_count: int
    error_count: int
    counts_by_kind: dict[str, int]

    def as_mapping(self) -> dict[str, object]:
        return {
            "observation_count": self.observation_count,
            "event_count": self.event_count,
            "market_event_count": self.market_event_count,
            "session_event_count": self.session_event_count,
            "corporate_action_event_count": self.corporate_action_event_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "counts_by_kind": dict(sorted(self.counts_by_kind.items())),
        }


@dataclass(frozen=True, slots=True)
class PolicyRunOutput:
    policy_name: str
    policy_config: dict[str, object]
    observations: tuple[ResearchObservation, ...]
    summary: ResearchObservationSummary
    policy_output_hash: str

    def as_mapping(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": POLICY_OUTPUT_KIND,
            "format_version": POLICY_OUTPUT_FORMAT_VERSION,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "summary": self.summary.as_mapping(),
            "observations": [item.as_mapping() for item in self.observations],
        }
        if include_hash:
            payload["policy_output_hash"] = self.policy_output_hash
        return payload


def sort_observations(
    observations: Sequence[ResearchObservation],
) -> tuple[ResearchObservation, ...]:
    return tuple(
        sorted(
            observations,
            key=lambda item: (
                canonical_datetime(item.event_time),
                item.kind,
                item.instrument_id or "",
                item.symbol or "",
                item.message,
            ),
        )
    )


def hash_policy_output(output: PolicyRunOutput) -> str:
    """SHA-256 of policy name, config, summary, and sorted observations."""
    return hash_policy_output_mapping(output.as_mapping(include_hash=False))


def hash_policy_output_mapping(payload: Mapping[str, object]) -> str:
    body = dict(payload)
    body.pop("policy_output_hash", None)
    observations = body.get("observations", [])
    if not isinstance(observations, list):
        raise BacktestError(
            "policy output observations must be a list",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    ranked = sorted(
        observations,
        key=lambda item: canonical_json(item) if isinstance(item, dict) else str(item),
    )
    summary = body.get("summary", {})
    config = body.get("policy_config", {})
    if not isinstance(summary, dict) or not isinstance(config, dict):
        raise BacktestError(
            "policy output summary and policy_config must be objects",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    digest_payload = {
        "kind": POLICY_OUTPUT_HASH_KIND,
        "version": POLICY_OUTPUT_HASH_FORMAT_VERSION,
        "policy_name": body.get("policy_name"),
        "policy_config": dict(config),
        "summary": dict(summary),
        "observations": ranked,
    }
    if manifest_contains_secrets(canonical_json(digest_payload)):
        raise BacktestError(
            "policy output must not contain secrets",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return sha256_canonical(digest_payload)


def _optional_token(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
