"""Read-only integrity checks for local replay-run artifacts."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.research.snapshots import (
    hash_manifest_mapping,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.artifacts import load_replay_events_jsonl
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.events import is_pre_known_event
from quant_platform.simulation.hashing import hash_replay_events
from quant_platform.simulation.run_catalog import get_replay_run_by_id
from quant_platform.simulation.run_types import (
    AUDIT_ARTIFACT_NAME,
    EVENTS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    SUMMARY_ARTIFACT_NAME,
    artifact_path_is_unsafe,
)

SEVERITY_RANK: dict[str, int] = {"error": 0, "warning": 1, "info": 2}


class ReplayRunIntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReplayRunIntegrityCode(StrEnum):
    MISSING_MANIFEST = "missing_manifest"
    MISSING_ARTIFACT = "missing_artifact"
    MISSING_RUN_DIR = "missing_run_dir"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    INVALID_HASH = "invalid_hash"
    MANIFEST_HASH_MISMATCH = "manifest_hash_mismatch"
    STREAM_HASH_MISMATCH = "stream_hash_mismatch"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    EVENT_COUNT_MISMATCH = "event_count_mismatch"
    COUNT_MISMATCH = "count_mismatch"
    CATALOG_MANIFEST_MISMATCH = "catalog_manifest_mismatch"
    CATALOG_ENTRY_MISSING = "catalog_entry_missing"
    INVALID_JSON = "invalid_json"
    EMPTY_ARTIFACT_PATH = "empty_artifact_path"


@dataclass(frozen=True, slots=True)
class ReplayRunIntegrityIssue:
    severity: str
    code: str
    message: str
    path: str | None = None
    expected: str | None = None
    actual: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class ReplayRunArtifactStatus:
    name: str
    path: str
    exists: bool
    relative: bool
    escaped: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "exists": self.exists,
            "relative": self.relative,
            "escaped": self.escaped,
        }


@dataclass(frozen=True, slots=True)
class ReplayRunIntegrityReport:
    run_root: str
    replay_id: str | None
    ok: bool
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[ReplayRunIntegrityIssue, ...]
    artifacts: tuple[ReplayRunArtifactStatus, ...]
    stream_hash: str | None
    recomputed_stream_hash: str | None
    manifest_hash: str | None
    recomputed_manifest_hash: str | None
    event_count: int | None
    jsonl_event_count: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "run_root": self.run_root,
            "replay_id": self.replay_id,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "stream_hash": self.stream_hash,
            "recomputed_stream_hash": self.recomputed_stream_hash,
            "manifest_hash": self.manifest_hash,
            "recomputed_manifest_hash": self.recomputed_manifest_hash,
            "event_count": self.event_count,
            "jsonl_event_count": self.jsonl_event_count,
        }


def replay_run_integrity_json(report: ReplayRunIntegrityReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def verify_replay_run_artifacts(
    run_root: Path | str,
    *,
    expected_replay_id: str | None = None,
) -> ReplayRunIntegrityReport:
    """Verify a local replay-run folder. Does not write files or touch PostgreSQL."""
    root = Path(run_root).expanduser()
    issues: list[ReplayRunIntegrityIssue] = []
    artifacts: list[ReplayRunArtifactStatus] = []
    if not root.exists() or not root.is_dir():
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.MISSING_RUN_DIR,
                "replay run directory is missing",
                path=str(root),
            )
        )
        return _finish(
            root=root,
            replay_id=expected_replay_id,
            issues=issues,
            artifacts=(),
        )

    resolved_root = root.resolve()
    manifest_path = resolved_root / MANIFEST_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.MISSING_MANIFEST,
                "manifest.json is missing",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish(
            root=root,
            replay_id=expected_replay_id,
            issues=issues,
            artifacts=(),
        )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    if manifest_contains_secrets(manifest_text):
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.SECRET_LIKE_VALUE,
                "manifest contains a secret-like marker",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
    try:
        loaded = json.loads(manifest_text)
    except json.JSONDecodeError:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.INVALID_JSON,
                "manifest.json is not valid JSON",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish(
            root=root,
            replay_id=expected_replay_id,
            issues=issues,
            artifacts=(),
        )
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.INVALID_JSON,
                "manifest.json must be an object",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish(
            root=root,
            replay_id=expected_replay_id,
            issues=issues,
            artifacts=(),
        )
    manifest = dict(loaded)
    replay_id = _optional_str(manifest.get("replay_id"))
    if expected_replay_id is not None and replay_id != expected_replay_id:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "manifest replay_id does not match the expected id",
                path=MANIFEST_ARTIFACT_NAME,
                expected=expected_replay_id,
                actual=replay_id,
            )
        )

    stored_manifest_hash = _optional_str(manifest.get("manifest_hash"))
    stored_stream_hash = _optional_str(manifest.get("stream_hash"))
    if stored_manifest_hash is None or not is_sha256_digest(stored_manifest_hash):
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.INVALID_HASH,
                "manifest_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_manifest_hash,
            )
        )
    if stored_stream_hash is None or not is_sha256_digest(stored_stream_hash):
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.INVALID_HASH,
                "stream_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_stream_hash,
            )
        )
    recomputed_manifest_hash: str | None = None
    try:
        recomputed_manifest_hash = hash_manifest_mapping(manifest)
        if (
            stored_manifest_hash is not None
            and is_sha256_digest(stored_manifest_hash)
            and recomputed_manifest_hash != stored_manifest_hash
        ):
            issues.append(
                _issue(
                    ReplayRunIntegritySeverity.ERROR,
                    ReplayRunIntegrityCode.MANIFEST_HASH_MISMATCH,
                    "manifest_hash does not match the canonical payload",
                    path=MANIFEST_ARTIFACT_NAME,
                    expected=stored_manifest_hash,
                    actual=recomputed_manifest_hash,
                )
            )
    except (TypeError, ValueError):
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.INVALID_JSON,
                "manifest payload cannot be hashed",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )

    required = (
        ("events", EVENTS_ARTIFACT_NAME),
        ("audit", AUDIT_ARTIFACT_NAME),
        ("summary", SUMMARY_ARTIFACT_NAME),
        ("manifest", MANIFEST_ARTIFACT_NAME),
    )
    listed = _listed_artifacts(manifest)
    seen_paths: set[str] = set()
    for name, default_path in required:
        path = listed.get(name, default_path)
        seen_paths.add(path)
        artifacts.append(
            _status_for(resolved_root, name=name, relative=path, issues=issues)
        )
    for name, path in listed.items():
        if path in seen_paths:
            continue
        artifacts.append(
            _status_for(resolved_root, name=name, relative=path, issues=issues)
        )

    events_path = resolved_root / EVENTS_ARTIFACT_NAME
    recomputed_stream_hash: str | None = None
    jsonl_event_count: int | None = None
    event_count = _optional_int(manifest.get("event_count"))
    if events_path.is_file():
        try:
            events = load_replay_events_jsonl(events_path)
            jsonl_event_count = len(events)
            recomputed_stream_hash = hash_replay_events(events)
        except (SimulationError, OSError, json.JSONDecodeError, ValueError):
            issues.append(
                _issue(
                    ReplayRunIntegritySeverity.ERROR,
                    ReplayRunIntegrityCode.INVALID_JSON,
                    "events.jsonl cannot be parsed as replay events",
                    path=EVENTS_ARTIFACT_NAME,
                )
            )
        else:
            if (
                stored_stream_hash is not None
                and is_sha256_digest(stored_stream_hash)
                and recomputed_stream_hash != stored_stream_hash
            ):
                issues.append(
                    _issue(
                        ReplayRunIntegritySeverity.ERROR,
                        ReplayRunIntegrityCode.STREAM_HASH_MISMATCH,
                        "stream_hash does not match events.jsonl",
                        path=EVENTS_ARTIFACT_NAME,
                        expected=stored_stream_hash,
                        actual=recomputed_stream_hash,
                    )
                )
            if event_count is not None and jsonl_event_count != event_count:
                issues.append(
                    _issue(
                        ReplayRunIntegritySeverity.ERROR,
                        ReplayRunIntegrityCode.EVENT_COUNT_MISMATCH,
                        "event_count does not match events.jsonl",
                        path=EVENTS_ARTIFACT_NAME,
                        expected=str(event_count),
                        actual=str(jsonl_event_count),
                    )
                )
            counted = dict(Counter(event.kind for event in events))
            declared = manifest.get("event_counts_by_type")
            if isinstance(declared, dict):
                normalized = {
                    str(key): int(value)
                    for key, value in declared.items()
                    if isinstance(value, int) and not isinstance(value, bool)
                }
                if normalized != counted:
                    issues.append(
                        _issue(
                            ReplayRunIntegritySeverity.ERROR,
                            ReplayRunIntegrityCode.COUNT_MISMATCH,
                            "event_counts_by_type does not match events.jsonl",
                            path=MANIFEST_ARTIFACT_NAME,
                        )
                    )
            pre_known = sum(1 for event in events if is_pre_known_event(event))
            declared_pre = _optional_int(manifest.get("pre_known_event_count"))
            if declared_pre is not None and declared_pre != pre_known:
                issues.append(
                    _issue(
                        ReplayRunIntegritySeverity.ERROR,
                        ReplayRunIntegrityCode.COUNT_MISMATCH,
                        "pre_known_event_count does not match events.jsonl",
                        path=MANIFEST_ARTIFACT_NAME,
                        expected=str(declared_pre),
                        actual=str(pre_known),
                    )
                )

    for extra_name, extra_path in (
        (AUDIT_ARTIFACT_NAME, resolved_root / AUDIT_ARTIFACT_NAME),
        (SUMMARY_ARTIFACT_NAME, resolved_root / SUMMARY_ARTIFACT_NAME),
    ):
        if extra_path.is_file() and manifest_contains_secrets(
            extra_path.read_text(encoding="utf-8")
        ):
            issues.append(
                _issue(
                    ReplayRunIntegritySeverity.ERROR,
                    ReplayRunIntegrityCode.SECRET_LIKE_VALUE,
                    f"{extra_name} contains a secret-like marker",
                    path=extra_name,
                )
            )

    return _finish(
        root=root,
        replay_id=replay_id or expected_replay_id,
        issues=issues,
        artifacts=tuple(artifacts),
        stream_hash=stored_stream_hash,
        recomputed_stream_hash=recomputed_stream_hash,
        manifest_hash=stored_manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        event_count=event_count,
        jsonl_event_count=jsonl_event_count,
    )


def verify_registered_replay_run(
    session: Session,
    replay_id: str,
    run_root: Path | str,
) -> ReplayRunIntegrityReport:
    """Verify local artifacts and compare them to the catalog row."""
    report = verify_replay_run_artifacts(run_root, expected_replay_id=replay_id)
    issues = list(report.issues)
    entry = get_replay_run_by_id(session, replay_id)
    if entry is None:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.CATALOG_ENTRY_MISSING,
                "replay_id is not registered",
            )
        )
        return replace_issues(report, issues)
    if report.stream_hash is not None and entry.stream_hash != report.stream_hash:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog stream_hash does not match local manifest",
                expected=entry.stream_hash,
                actual=report.stream_hash,
            )
        )
    if report.manifest_hash is not None and entry.manifest_hash != report.manifest_hash:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog manifest_hash does not match local manifest",
                expected=entry.manifest_hash,
                actual=report.manifest_hash,
            )
        )
    if report.event_count is not None and entry.event_count != report.event_count:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog event_count does not match local manifest",
                expected=str(entry.event_count),
                actual=str(report.event_count),
            )
        )
    return replace_issues(report, issues)


def replace_issues(
    report: ReplayRunIntegrityReport, issues: list[ReplayRunIntegrityIssue]
) -> ReplayRunIntegrityReport:
    ranked = tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
            ),
        )
    )
    error_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.INFO
    )
    return ReplayRunIntegrityReport(
        run_root=report.run_root,
        replay_id=report.replay_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=report.artifacts,
        stream_hash=report.stream_hash,
        recomputed_stream_hash=report.recomputed_stream_hash,
        manifest_hash=report.manifest_hash,
        recomputed_manifest_hash=report.recomputed_manifest_hash,
        event_count=report.event_count,
        jsonl_event_count=report.jsonl_event_count,
    )


def _listed_artifacts(manifest: dict[str, object]) -> dict[str, str]:
    raw = manifest.get("artifacts")
    listed: dict[str, str] = {}
    if not isinstance(raw, list):
        return listed
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        path = item.get("path")
        if isinstance(name, str) and isinstance(path, str) and name and path:
            listed[name] = path
    return listed


def _status_for(
    root: Path,
    *,
    name: str,
    relative: str,
    issues: list[ReplayRunIntegrityIssue],
) -> ReplayRunArtifactStatus:
    unsafe = artifact_path_is_unsafe(relative)
    escaped = ".." in Path(relative).parts
    absolute = Path(relative).is_absolute()
    if not relative.strip():
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.EMPTY_ARTIFACT_PATH,
                "artifact path is empty",
                path=name,
            )
        )
    elif absolute:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.ABSOLUTE_PATH,
                "artifact path must be relative",
                path=relative,
            )
        )
    elif escaped:
        issues.append(
            _issue(
                ReplayRunIntegritySeverity.ERROR,
                ReplayRunIntegrityCode.PATH_ESCAPE,
                "artifact path must not contain '..'",
                path=relative,
            )
        )
    exists = False
    if not unsafe:
        exists = (root / relative).is_file()
        if not exists:
            issues.append(
                _issue(
                    ReplayRunIntegritySeverity.ERROR,
                    ReplayRunIntegrityCode.MISSING_ARTIFACT,
                    f"{relative} is missing",
                    path=relative,
                )
            )
    return ReplayRunArtifactStatus(
        name=name,
        path=relative,
        exists=exists,
        relative=not absolute,
        escaped=escaped,
    )


def _issue(
    severity: ReplayRunIntegritySeverity,
    code: ReplayRunIntegrityCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> ReplayRunIntegrityIssue:
    return ReplayRunIntegrityIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _finish(
    *,
    root: Path,
    replay_id: str | None,
    issues: list[ReplayRunIntegrityIssue],
    artifacts: tuple[ReplayRunArtifactStatus, ...],
    stream_hash: str | None = None,
    recomputed_stream_hash: str | None = None,
    manifest_hash: str | None = None,
    recomputed_manifest_hash: str | None = None,
    event_count: int | None = None,
    jsonl_event_count: int | None = None,
) -> ReplayRunIntegrityReport:
    ranked = tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
            ),
        )
    )
    error_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == ReplayRunIntegritySeverity.INFO
    )
    return ReplayRunIntegrityReport(
        run_root=str(root),
        replay_id=replay_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=artifacts,
        stream_hash=stream_hash,
        recomputed_stream_hash=recomputed_stream_hash,
        manifest_hash=manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        event_count=event_count,
        jsonl_event_count=jsonl_event_count,
    )
