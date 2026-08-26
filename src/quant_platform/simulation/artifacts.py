"""Local replay-run artifacts. Events in JSONL; metadata in JSON. No cloud."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from quant_platform import __version__
from quant_platform.core.time import utc_now
from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_json,
    dataset_request_mapping,
    get_git_commit,
    hash_manifest_mapping,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.research.types import DailyBarsDatasetRequest
from quant_platform.simulation.audit import ReplayAuditReport
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.event_fixtures import replay_event_from_mapping
from quant_platform.simulation.events import ReplayEvent
from quant_platform.simulation.hashing import hash_replay_events
from quant_platform.simulation.replay import DailyBarReplay
from quant_platform.simulation.run_types import (
    AUDIT_ARTIFACT_NAME,
    EVENTS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    SOURCE_TYPES,
    SUMMARY_ARTIFACT_NAME,
    ReplayRunManifest,
    ReplayRunResult,
    default_replay_run_artifacts,
    optional_replay_notes,
)
from quant_platform.simulation.summary import ReplaySummary

_TIME_FIELDS = frozenset(
    {
        "event_time",
        "start_time",
        "end_time",
        "as_of",
        "observation_time",
        "available_time",
        "effective_time",
        "started_at",
        "finished_at",
    }
)


def compact_audit_summary(report: ReplayAuditReport) -> dict[str, object]:
    """Small audit blob for PostgreSQL. Full issues stay in audit.json."""
    counts = {key: report.counts_by_kind[key] for key in sorted(report.counts_by_kind)}
    return {
        "ok": report.ok,
        "boundary_ok": report.boundary_ok,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "info_count": report.info_count,
        "stream_hash": report.stream_hash,
        "event_count": report.event_count,
        "counts_by_kind": counts,
        "pre_known_event_count": report.pre_known_event_count,
        "starts_with_replay_started": report.starts_with_replay_started,
        "ends_with_replay_finished": report.ends_with_replay_finished,
    }


def replay_request_mapping(
    request: DailyBarsDatasetRequest | Mapping[str, object] | None,
    *,
    summary: ReplaySummary,
    include_sessions: bool = False,
    include_corporate_actions: bool = False,
) -> dict[str, object]:
    """JSON request without filesystem paths or secrets."""
    if isinstance(request, DailyBarsDatasetRequest):
        payload = dataset_request_mapping(request)
    elif isinstance(request, Mapping):
        payload = dict(request)
    else:
        payload = {
            "as_of": canonical_datetime(summary.as_of),
            "start_time": canonical_datetime(summary.start_time),
            "end_time": canonical_datetime(summary.end_time),
        }
    payload["include_sessions"] = include_sessions
    payload["include_corporate_actions"] = include_corporate_actions
    payload["source_type"] = summary.source_type
    return payload


def event_artifact_mapping(event: ReplayEvent) -> dict[str, object]:
    """Stable event JSON: sorted later; timestamps as UTC Z; decimals as strings."""
    mapping = dict(event.as_mapping())
    for key, value in list(mapping.items()):
        if key not in _TIME_FIELDS or not isinstance(value, str) or not value:
            continue
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise SimulationError(
                f"{key} must be timezone-aware UTC",
                code=SimulationErrorCode.NAIVE_TIMESTAMP,
            )
        mapping[key] = canonical_datetime(parsed)
    return mapping


def write_replay_events_jsonl(events: Sequence[ReplayEvent], path: Path) -> None:
    lines = [canonical_json(event_artifact_mapping(event)) for event in events]
    text = ("\n".join(lines) + "\n") if lines else ""
    _reject_secrets(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_replay_events_jsonl(path: Path | str) -> tuple[ReplayEvent, ...]:
    root = Path(path)
    try:
        text = root.read_text(encoding="utf-8")
    except OSError as exc:
        raise SimulationError(
            "replay events.jsonl cannot be read",
            code=SimulationErrorCode.BROKEN_RUN,
        ) from exc
    events: list[ReplayEvent] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SimulationError(
                "replay events.jsonl is not valid JSONL",
                code=SimulationErrorCode.BROKEN_RUN,
            ) from exc
        if not isinstance(payload, dict):
            raise SimulationError(
                "replay events.jsonl rows must be objects",
                code=SimulationErrorCode.BROKEN_RUN,
            )
        events.append(replay_event_from_mapping(payload))
    return tuple(events)


def hash_replay_events_jsonl(path: Path | str) -> str:
    """Recompute ``stream_hash`` from a local events.jsonl file."""
    return hash_replay_events(load_replay_events_jsonl(path))


def write_replay_run_artifacts(
    replay: DailyBarReplay,
    audit: ReplayAuditReport,
    output_dir: Path | str,
    *,
    request: DailyBarsDatasetRequest | Mapping[str, object] | None = None,
    notes: str | None = None,
    dataset_snapshot_id: str | None = None,
    created_at: datetime | None = None,
    git_commit: str | None = None,
    resolve_git: bool = True,
    include_sessions: bool = False,
    include_corporate_actions: bool = False,
) -> ReplayRunResult:
    """Write events.jsonl, audit.json, summary.json, and manifest.json."""
    stamp = created_at if created_at is not None else utc_now()
    if stamp.tzinfo is None:
        raise SimulationError(
            "created_at must be timezone-aware UTC",
            code=SimulationErrorCode.NAIVE_TIMESTAMP,
        )
    stamp = stamp.astimezone(UTC)
    if replay.summary.source_type not in SOURCE_TYPES:
        raise SimulationError(
            "source_type must be 'database' or 'snapshot'",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    stream_hash = replay.summary.stream_hash
    if stream_hash is None or not is_sha256_digest(stream_hash):
        stream_hash = hash_replay_events(replay.events)
    if stream_hash != audit.stream_hash:
        raise SimulationError(
            "summary stream_hash must match audit stream_hash",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    events_path = target / EVENTS_ARTIFACT_NAME
    audit_path = target / AUDIT_ARTIFACT_NAME
    summary_path = target / SUMMARY_ARTIFACT_NAME
    manifest_path = target / MANIFEST_ARTIFACT_NAME
    write_replay_events_jsonl(replay.events, events_path)
    _write_json(audit.as_mapping(), audit_path)
    _write_json(replay.summary.as_mapping(), summary_path)

    resolved_commit = git_commit
    if resolve_git and resolved_commit is None:
        resolved_commit = get_git_commit()
    counts = dict(Counter(event.kind for event in replay.events))
    request_payload = replay_request_mapping(
        request,
        summary=replay.summary,
        include_sessions=include_sessions,
        include_corporate_actions=include_corporate_actions,
    )
    snapshot_id = _optional_token(dataset_snapshot_id)
    artifacts = default_replay_run_artifacts()
    draft = ReplayRunManifest(
        replay_id=replay.summary.replay_id,
        created_at=stamp,
        package_version=__version__,
        git_commit=resolved_commit,
        source_type=replay.summary.source_type,
        dataset_snapshot_id=snapshot_id,
        dataset_content_hash=replay.summary.content_hash,
        stream_hash=stream_hash,
        event_count=replay.summary.event_count,
        event_counts_by_type=counts,
        pre_known_event_count=replay.summary.pre_known_event_count,
        boundary_ok=audit.boundary_ok,
        warning_count=audit.warning_count,
        error_count=audit.error_count,
        first_event_time=replay.summary.first_event_time,
        last_event_time=replay.summary.last_event_time,
        first_market_event_time=replay.summary.first_market_event_time,
        last_market_event_time=replay.summary.last_market_event_time,
        request=request_payload,
        audit_summary=compact_audit_summary(audit),
        artifacts=artifacts,
        notes=optional_replay_notes(notes),
        manifest_hash="",
    )
    manifest_hash = hash_manifest_mapping(draft.as_mapping(include_manifest_hash=False))
    manifest = replace(draft, manifest_hash=manifest_hash)
    write_replay_run_manifest(manifest, manifest_path)
    return ReplayRunResult(
        manifest=manifest,
        output_dir=target,
        events_path=events_path,
        audit_path=audit_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
    )


def write_replay_run_manifest(manifest: ReplayRunManifest, path: Path) -> None:
    _write_json(manifest.as_mapping(), path)


def snapshot_id_from_snapshot_dir(snapshot_dir: Path | str) -> str | None:
    """Read snapshot_id from a local snapshot manifest. Not a filesystem path."""
    manifest_path = Path(snapshot_dir) / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("snapshot_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    _reject_secrets(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _reject_secrets(text: str) -> None:
    if manifest_contains_secrets(text):
        raise SimulationError(
            "replay run output must not contain secrets",
            code=SimulationErrorCode.CATALOG_INVALID,
        )


def _optional_token(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
