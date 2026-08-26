"""Descriptive research observation reports. Not signals, orders, or PnL."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    ALLOWED_OBSERVATION_KINDS,
    OBSERVATION_KIND_CORPORATE_ACTION_SEEN,
    OBSERVATION_KIND_CORRECTION_SEEN,
    OBSERVATION_KIND_SESSION_SEEN,
    OBSERVATION_KIND_UNKNOWN_EVENT,
    PolicyRunOutput,
)
from quant_platform.backtest.types import POLICY_OUTPUT_ARTIFACT_NAME
from quant_platform.research.snapshots import manifest_contains_secrets

OBSERVATION_REPORT_KIND = "research_observation_report"
OBSERVATION_REPORT_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ObservationReportIssue:
    severity: str
    code: str
    message: str
    path: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class ObservationKindSummary:
    kind: str
    count: int

    def as_mapping(self) -> dict[str, object]:
        return {"kind": self.kind, "count": self.count}


@dataclass(frozen=True, slots=True)
class ObservationSeveritySummary:
    severity: str
    count: int

    def as_mapping(self) -> dict[str, object]:
        return {"severity": self.severity, "count": self.count}


@dataclass(frozen=True, slots=True)
class ObservationInstrumentSummary:
    instrument_id: str | None
    symbol: str | None
    count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    event_time: str | None
    kind: str | None
    severity: str | None
    instrument_id: str | None
    symbol: str | None
    message: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "event_time": self.event_time,
            "kind": self.kind,
            "severity": self.severity,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ObservationReport:
    policy_name: str | None
    policy_output_hash: str | None
    observation_count: int
    warning_count: int
    error_count: int
    unknown_event_count: int
    correction_count: int
    corporate_action_count: int
    session_count: int
    kinds: tuple[ObservationKindSummary, ...]
    severities: tuple[ObservationSeveritySummary, ...]
    instruments: tuple[ObservationInstrumentSummary, ...]
    first_observation: ObservationSnapshot | None
    last_observation: ObservationSnapshot | None
    issues: tuple[ObservationReportIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": OBSERVATION_REPORT_KIND,
            "format_version": OBSERVATION_REPORT_FORMAT_VERSION,
            "policy_name": self.policy_name,
            "policy_output_hash": self.policy_output_hash,
            "observation_count": self.observation_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "unknown_event_count": self.unknown_event_count,
            "correction_count": self.correction_count,
            "corporate_action_count": self.corporate_action_count,
            "session_count": self.session_count,
            "kinds": [item.as_mapping() for item in self.kinds],
            "severities": [item.as_mapping() for item in self.severities],
            "instruments": [item.as_mapping() for item in self.instruments],
            "first_observation": (
                None
                if self.first_observation is None
                else self.first_observation.as_mapping()
            ),
            "last_observation": (
                None
                if self.last_observation is None
                else self.last_observation.as_mapping()
            ),
            "issues": [item.as_mapping() for item in self.issues],
        }


def observation_report_json(report: ObservationReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def build_observation_report(
    source: PolicyRunOutput | Mapping[str, object] | Path | str,
) -> ObservationReport:
    """Summarize policy observations. Does not emit signals or compute PnL."""
    payload = _as_mapping(source)
    policy_name = _optional_str(payload.get("policy_name"))
    policy_output_hash = _optional_str(payload.get("policy_output_hash"))
    raw_observations = payload.get("observations", [])
    if raw_observations is None:
        raw_observations = []
    if not isinstance(raw_observations, list):
        raise BacktestError(
            "policy output observations must be a list",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    ranked = _rank_observations(raw_observations)
    kind_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    instrument_counts: Counter[tuple[str, str]] = Counter()
    for item in ranked:
        kind = _optional_str(item.get("kind")) or "unknown_event"
        kind_counts[kind] += 1
        severity = _optional_str(item.get("severity")) or "info"
        severity_counts[severity] += 1
        instrument_id = _optional_str(item.get("instrument_id"))
        symbol = _optional_str(item.get("symbol"))
        if instrument_id is not None or symbol is not None:
            instrument_counts[(instrument_id or "", symbol or "")] += 1

    summary = payload.get("summary")
    summary_map = summary if isinstance(summary, dict) else {}
    observation_count = _optional_int(summary_map.get("observation_count"))
    if observation_count is None:
        observation_count = len(ranked)
    warning_count = _optional_int(summary_map.get("warning_count"))
    if warning_count is None:
        warning_count = severity_counts.get("warning", 0)
    error_count = _optional_int(summary_map.get("error_count"))
    if error_count is None:
        error_count = severity_counts.get("error", 0)

    kinds = tuple(
        ObservationKindSummary(kind=kind, count=count)
        for kind, count in sorted(kind_counts.items())
    )
    severities = tuple(
        ObservationSeveritySummary(severity=name, count=severity_counts[name])
        for name in ("error", "warning", "info")
        if severity_counts.get(name, 0) > 0
    )
    instruments = tuple(
        ObservationInstrumentSummary(
            instrument_id=key[0] or None,
            symbol=key[1] or None,
            count=count,
        )
        for key, count in sorted(instrument_counts.items())
    )
    first = _snapshot(ranked[0]) if ranked else None
    last = _snapshot(ranked[-1]) if ranked else None
    issues: list[ObservationReportIssue] = []
    if observation_count == 0:
        issues.append(
            ObservationReportIssue(
                severity="info",
                code="empty_observations",
                message="policy output contains no observations",
            )
        )
    unknown_kinds = sorted(
        kind for kind in kind_counts if kind not in ALLOWED_OBSERVATION_KINDS
    )
    for kind in unknown_kinds:
        issues.append(
            ObservationReportIssue(
                severity="warning",
                code="unregistered_observation_kind",
                message="observation kind is outside the research allowlist",
                path=kind,
            )
        )
    return ObservationReport(
        policy_name=policy_name,
        policy_output_hash=policy_output_hash,
        observation_count=observation_count,
        warning_count=warning_count,
        error_count=error_count,
        unknown_event_count=kind_counts.get(OBSERVATION_KIND_UNKNOWN_EVENT, 0),
        correction_count=kind_counts.get(OBSERVATION_KIND_CORRECTION_SEEN, 0),
        corporate_action_count=kind_counts.get(
            OBSERVATION_KIND_CORPORATE_ACTION_SEEN, 0
        ),
        session_count=kind_counts.get(OBSERVATION_KIND_SESSION_SEEN, 0),
        kinds=kinds,
        severities=severities,
        instruments=instruments,
        first_observation=first,
        last_observation=last,
        issues=tuple(issues),
    )


def _as_mapping(
    source: PolicyRunOutput | Mapping[str, object] | Path | str,
) -> dict[str, object]:
    if isinstance(source, PolicyRunOutput):
        return source.as_mapping()
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    if path.is_dir():
        path = path / POLICY_OUTPUT_ARTIFACT_NAME
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BacktestError(
            "policy_output.json is missing",
            code=BacktestErrorCode.BROKEN_RUN,
        ) from exc
    except json.JSONDecodeError as exc:
        raise BacktestError(
            "policy_output.json is not valid JSON",
            code=BacktestErrorCode.BROKEN_RUN,
        ) from exc
    if not isinstance(loaded, dict):
        raise BacktestError(
            "policy_output.json must be an object",
            code=BacktestErrorCode.BROKEN_RUN,
        )
    return dict(loaded)


def _rank_observations(
    observations: Sequence[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in observations:
        if isinstance(item, dict):
            rows.append(dict(item))
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("event_time") or ""),
            str(item.get("kind") or ""),
            str(item.get("instrument_id") or ""),
            str(item.get("symbol") or ""),
            str(item.get("message") or ""),
        ),
    )


def _snapshot(item: Mapping[str, object]) -> ObservationSnapshot:
    message = _optional_str(item.get("message"))
    if message is not None and manifest_contains_secrets(message):
        message = None
    return ObservationSnapshot(
        event_time=_optional_str(item.get("event_time")),
        kind=_optional_str(item.get("kind")),
        severity=_optional_str(item.get("severity")),
        instrument_id=_optional_str(item.get("instrument_id")),
        symbol=_optional_str(item.get("symbol")),
        message=message,
    )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
