"""Read-only integrity checks for policy_output.json. No writes or trading."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.observations import (
    ALLOWED_OBSERVATION_KINDS,
    OBSERVATION_SEVERITIES,
    PolicyRunOutput,
    contains_operative_language,
    hash_policy_output_mapping,
)
from quant_platform.backtest.policy_output_types import (
    POLICY_OUTPUT_SEVERITY_RANK,
    PolicyOutputComparison,
    PolicyOutputComparisonItem,
    PolicyOutputComparisonVerdict,
    PolicyOutputIntegrityCode,
    PolicyOutputIntegritySeverity,
    PolicyOutputStatus,
    PolicyOutputVerificationIssue,
    PolicyOutputVerificationReport,
)
from quant_platform.backtest.types import (
    MANIFEST_ARTIFACT_NAME,
    POLICY_OUTPUT_ARTIFACT_NAME,
)
from quant_platform.research.snapshots import (
    canonical_json,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe


def policy_output_verification_json(report: PolicyOutputVerificationReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def policy_output_comparison_json(comparison: PolicyOutputComparison) -> str:
    return json.dumps(
        comparison.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True
    )


def verify_policy_output(
    run_dir: Path | str,
    *,
    expected_hash: str | None = None,
    relative_path: str = POLICY_OUTPUT_ARTIFACT_NAME,
) -> PolicyOutputVerificationReport:
    """Verify local policy output. Does not write files or touch PostgreSQL."""
    root = Path(run_dir).expanduser()
    issues: list[PolicyOutputVerificationIssue] = []
    if root.is_file():
        path = root
        display_root = str(root.parent)
        relative = root.name
    else:
        display_root = str(root)
        relative = relative_path
        if artifact_path_is_unsafe(relative):
            if Path(relative).is_absolute():
                issues.append(
                    _issue(
                        PolicyOutputIntegritySeverity.ERROR,
                        PolicyOutputIntegrityCode.ABSOLUTE_PATH,
                        "policy output path must be relative",
                        path=relative,
                    )
                )
            else:
                issues.append(
                    _issue(
                        PolicyOutputIntegritySeverity.ERROR,
                        PolicyOutputIntegrityCode.PATH_ESCAPE,
                        "policy output path must not contain '..'",
                        path=relative,
                    )
                )
            return _finish(
                root=display_root,
                issues=issues,
                policy_name=None,
                stored_hash=expected_hash,
                recomputed_hash=None,
                observation_count=None,
            )
        path = root / relative

    if not path.is_file():
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.MISSING_POLICY_OUTPUT,
                "policy_output.json is missing",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
        return _finish(
            root=display_root,
            issues=issues,
            policy_name=None,
            stored_hash=expected_hash,
            recomputed_hash=None,
            observation_count=None,
        )

    text = path.read_text(encoding="utf-8")
    if manifest_contains_secrets(text):
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.SECRET_LIKE_VALUE,
                "policy_output contains a secret-like marker",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
    payload = _load_object(text, issues)
    if payload is None:
        return _finish(
            root=display_root,
            issues=issues,
            policy_name=None,
            stored_hash=expected_hash,
            recomputed_hash=None,
            observation_count=None,
        )
    manifest_hash = _manifest_policy_hash(root if root.is_dir() else root.parent)
    merged_expected = expected_hash if expected_hash is not None else manifest_hash
    return verify_policy_output_mapping(
        payload,
        expected_hash=merged_expected,
        run_root=display_root,
        prior_issues=issues,
    )


def verify_policy_output_mapping(
    payload: Mapping[str, object],
    *,
    expected_hash: str | None = None,
    run_root: str = "",
    prior_issues: list[PolicyOutputVerificationIssue] | None = None,
) -> PolicyOutputVerificationReport:
    """Verify an in-memory policy output object. Read-only."""
    issues = list(prior_issues or ())
    body = dict(payload)
    policy_name = _optional_str(body.get("policy_name"))
    stored_hash = _optional_str(body.get("policy_output_hash"))
    observations = body.get("observations", [])
    observation_count: int | None = None
    if isinstance(observations, list):
        observation_count = len(observations)
    else:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "observations must be a list",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )

    try:
        blob = canonical_json(body)
    except (TypeError, ValueError):
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "policy output is not JSON-serializable",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
        return _finish(
            root=run_root,
            issues=issues,
            policy_name=policy_name,
            stored_hash=stored_hash or expected_hash,
            recomputed_hash=None,
            observation_count=observation_count,
        )
    if contains_operative_language(blob):
        _scan_operative_language(body, issues)
    _scan_absolute_paths(body, issues)
    _check_observations(body, issues)
    _check_counts(body, issues)

    recomputed_hash: str | None = None
    try:
        recomputed_hash = hash_policy_output_mapping(body)
    except BacktestError:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "policy_output payload cannot be hashed",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
    else:
        if stored_hash is not None and not is_sha256_digest(stored_hash):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_HASH,
                    "policy_output_hash must be sha256:<64 hex>",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                    actual=stored_hash,
                )
            )
        if stored_hash is not None and stored_hash != recomputed_hash:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH,
                    "stored policy_output_hash does not match payload",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                    expected=stored_hash,
                    actual=recomputed_hash,
                )
            )
        if expected_hash is not None and expected_hash != recomputed_hash:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH,
                    "policy_output_hash does not match policy_output.json",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                    expected=expected_hash,
                    actual=recomputed_hash,
                )
            )

    return _finish(
        root=run_root,
        issues=issues,
        policy_name=policy_name,
        stored_hash=stored_hash or expected_hash,
        recomputed_hash=recomputed_hash,
        observation_count=observation_count,
    )


def compare_policy_outputs(
    left: PolicyRunOutput | Mapping[str, object] | Path | str,
    right: PolicyRunOutput | Mapping[str, object] | Path | str,
) -> PolicyOutputComparison:
    """Compare two policy outputs. Metadata and counts only; no PnL."""
    left_view = _comparison_view(left)
    right_view = _comparison_view(right)
    items: list[PolicyOutputComparisonItem] = []
    _add(items, "policy_output_hash", left_view.digest, right_view.digest)
    _add(
        items,
        "observation_count",
        str(left_view.observation_count),
        str(right_view.observation_count),
    )
    _add(items, "counts_by_kind", left_view.counts_by_kind, right_view.counts_by_kind)
    _add(
        items,
        "counts_by_severity",
        left_view.counts_by_severity,
        right_view.counts_by_severity,
    )
    _add(
        items,
        "warning_count",
        str(left_view.warning_count),
        str(right_view.warning_count),
    )
    _add(items, "error_count", str(left_view.error_count), str(right_view.error_count))
    _add(
        items,
        "first_observation_time",
        left_view.first_time,
        right_view.first_time,
    )
    _add(items, "last_observation_time", left_view.last_time, right_view.last_time)
    _add(items, "policy_name", left_view.policy_name, right_view.policy_name)
    _add(items, "policy_config", left_view.policy_config, right_view.policy_config)
    ranked = tuple(sorted(items, key=lambda item: item.field))
    same_hash = (
        left_view.digest is not None
        and right_view.digest is not None
        and left_view.digest == right_view.digest
    )
    same_observation_count = left_view.observation_count == right_view.observation_count
    same_kind = left_view.counts_by_kind == right_view.counts_by_kind
    same_severity = left_view.counts_by_severity == right_view.counts_by_severity
    same_warning = left_view.warning_count == right_view.warning_count
    same_error = left_view.error_count == right_view.error_count
    same_counts = (
        same_observation_count
        and same_kind
        and same_severity
        and same_warning
        and same_error
    )
    if same_hash:
        verdict = PolicyOutputComparisonVerdict.IDENTICAL.value
    elif same_counts:
        verdict = PolicyOutputComparisonVerdict.SAME_COUNTS.value
    else:
        verdict = PolicyOutputComparisonVerdict.DIFFERENT.value
    return PolicyOutputComparison(
        verdict=verdict,
        identical=same_hash,
        same_policy_output_hash=same_hash,
        same_observation_count=same_observation_count,
        same_counts_by_kind=same_kind,
        same_counts_by_severity=same_severity,
        same_warning_count=same_warning,
        same_error_count=same_error,
        same_policy_name=left_view.policy_name == right_view.policy_name,
        same_policy_config=left_view.policy_config == right_view.policy_config,
        same_first_observation_time=left_view.first_time == right_view.first_time,
        same_last_observation_time=left_view.last_time == right_view.last_time,
        left_hash=left_view.digest,
        right_hash=right_view.digest,
        items=ranked,
    )


def _load_object(
    text: str, issues: list[PolicyOutputVerificationIssue]
) -> dict[str, object] | None:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "policy_output.json is not valid JSON",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
        return None
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "policy_output.json must be an object",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
        return None
    return dict(loaded)


def _manifest_policy_hash(root: Path) -> str | None:
    manifest_path = root / MANIFEST_ARTIFACT_NAME
    if not manifest_path.is_file():
        return None
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return _optional_str(loaded.get("policy_output_hash"))


def _check_observations(
    payload: Mapping[str, object],
    issues: list[PolicyOutputVerificationIssue],
) -> None:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return
    for index, item in enumerate(observations):
        path = f"observations[{index}]"
        if not isinstance(item, dict):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                    "observation must be an object",
                    path=path,
                )
            )
            continue
        kind = _optional_str(item.get("kind"))
        if kind is None or kind not in ALLOWED_OBSERVATION_KINDS:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_OBSERVATION_KIND,
                    "observation kind is not allowed",
                    path=f"{path}.kind",
                    actual=kind,
                )
            )
        severity = _optional_str(item.get("severity"))
        if severity is None or severity not in OBSERVATION_SEVERITIES:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_OBSERVATION_SEVERITY,
                    "observation severity must be info, warning, or error",
                    path=f"{path}.severity",
                    actual=severity,
                )
            )
        for field in ("observation_time", "event_time"):
            raw = item.get(field)
            parsed = _parse_timestamp(raw)
            if parsed is None:
                issues.append(
                    _issue(
                        PolicyOutputIntegritySeverity.ERROR,
                        PolicyOutputIntegrityCode.TIMESTAMP_NOT_UTC,
                        f"{field} must be timezone-aware UTC",
                        path=f"{path}.{field}",
                        actual=None if raw is None else str(raw),
                    )
                )
            elif parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
                issues.append(
                    _issue(
                        PolicyOutputIntegritySeverity.ERROR,
                        PolicyOutputIntegrityCode.TIMESTAMP_NOT_UTC,
                        f"{field} must be timezone-aware UTC",
                        path=f"{path}.{field}",
                        actual=str(raw),
                    )
                )
        metadata = item.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                    "observation metadata must be a JSON object",
                    path=f"{path}.metadata",
                )
            )
            continue
        try:
            json.dumps(metadata, allow_nan=False)
        except (TypeError, ValueError):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                    "observation metadata must be JSON-safe",
                    path=f"{path}.metadata",
                )
            )


def _check_counts(
    payload: Mapping[str, object],
    issues: list[PolicyOutputVerificationIssue],
) -> None:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return
    rows = [item for item in observations if isinstance(item, dict)]
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.INVALID_POLICY_OUTPUT_JSON,
                "policy output summary must be an object",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
            )
        )
        return
    actual_count = len(rows)
    stored_count = _optional_int(summary.get("observation_count"))
    if stored_count is not None and stored_count != actual_count:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.COUNT_MISMATCH,
                "observation_count does not match observations list",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
                expected=str(stored_count),
                actual=str(actual_count),
            )
        )
    warning_actual = sum(
        1 for item in rows if _optional_str(item.get("severity")) == "warning"
    )
    error_actual = sum(
        1 for item in rows if _optional_str(item.get("severity")) == "error"
    )
    stored_warning = _optional_int(summary.get("warning_count"))
    stored_error = _optional_int(summary.get("error_count"))
    if stored_warning is not None and stored_warning != warning_actual:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.COUNT_MISMATCH,
                "warning_count does not match warning observations",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
                expected=str(stored_warning),
                actual=str(warning_actual),
            )
        )
    if stored_error is not None and stored_error != error_actual:
        issues.append(
            _issue(
                PolicyOutputIntegritySeverity.ERROR,
                PolicyOutputIntegrityCode.COUNT_MISMATCH,
                "error_count does not match error observations",
                path=POLICY_OUTPUT_ARTIFACT_NAME,
                expected=str(stored_error),
                actual=str(error_actual),
            )
        )
    stored_kinds = summary.get("counts_by_kind")
    if isinstance(stored_kinds, dict):
        actual_kinds = Counter(_optional_str(item.get("kind")) or "" for item in rows)
        actual_kinds.pop("", None)
        normalized = {
            str(key): value
            for key, value in stored_kinds.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if normalized != dict(actual_kinds):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.COUNT_MISMATCH,
                    "counts_by_kind does not match observations",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                )
            )
    for field in (
        "observation_count",
        "event_count",
        "warning_count",
        "error_count",
    ):
        value = _optional_int(summary.get(field))
        if value is not None and value < 0:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.COUNT_MISMATCH,
                    f"{field} must be >= 0",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                    actual=str(value),
                )
            )


def _scan_operative_language(
    payload: Mapping[str, object],
    issues: list[PolicyOutputVerificationIssue],
) -> None:
    found = False
    observations = payload.get("observations")
    if isinstance(observations, list):
        for index, item in enumerate(observations):
            if not isinstance(item, dict):
                continue
            path = f"observations[{index}]"
            for field in ("kind", "message", "symbol"):
                value = item.get(field)
                if isinstance(value, str) and contains_operative_language(value):
                    issues.append(
                        _issue(
                            PolicyOutputIntegritySeverity.ERROR,
                            PolicyOutputIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
                            "policy output contains investment-decision wording",
                            path=f"{path}.{field}",
                        )
                    )
                    found = True
            metadata = item.get("metadata")
            if isinstance(metadata, dict) and contains_operative_language(
                canonical_json(metadata)
            ):
                issues.append(
                    _issue(
                        PolicyOutputIntegritySeverity.ERROR,
                        PolicyOutputIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
                        "policy output contains investment-decision wording",
                        path=f"{path}.metadata",
                    )
                )
                found = True
    if found:
        return
    issues.append(
        _issue(
            PolicyOutputIntegritySeverity.ERROR,
            PolicyOutputIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
            "policy output contains investment-decision wording",
            path=POLICY_OUTPUT_ARTIFACT_NAME,
        )
    )


def _scan_absolute_paths(
    payload: Mapping[str, object],
    issues: list[PolicyOutputVerificationIssue],
) -> None:
    for path, value in _walk_strings(payload):
        if _looks_like_absolute_path(value):
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.ABSOLUTE_PATH,
                    "policy output must not contain absolute paths",
                    path=path,
                )
            )
        elif ("/" in value or "\\" in value) and ".." in Path(value).parts:
            issues.append(
                _issue(
                    PolicyOutputIntegritySeverity.ERROR,
                    PolicyOutputIntegrityCode.PATH_ESCAPE,
                    "policy output must not contain path traversal",
                    path=path,
                )
            )


def _walk_strings(value: object, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        found.append((prefix or POLICY_OUTPUT_ARTIFACT_NAME, value))
        return found
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_walk_strings(item, child))
        return found
    if isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            found.extend(_walk_strings(item, child))
    return found


def _looks_like_absolute_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    candidate = Path(stripped)
    return candidate.is_absolute()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


def _comparison_view(
    source: PolicyRunOutput | Mapping[str, object] | Path | str,
) -> _CountView:
    payload = _as_compare_mapping(source)
    observations_raw = payload.get("observations", [])
    rows = (
        [item for item in observations_raw if isinstance(item, dict)]
        if isinstance(observations_raw, list)
        else []
    )
    summary = payload.get("summary")
    summary_map = summary if isinstance(summary, dict) else {}
    kind_counts = Counter(_optional_str(item.get("kind")) or "" for item in rows)
    kind_counts.pop("", None)
    stored_kinds = summary_map.get("counts_by_kind")
    if isinstance(stored_kinds, dict) and stored_kinds:
        kind_payload = {
            str(key): int(value)
            for key, value in stored_kinds.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
    else:
        kind_payload = dict(sorted(kind_counts.items()))
    severity_counts = Counter(
        _optional_str(item.get("severity")) or "" for item in rows
    )
    severity_counts.pop("", None)
    observation_count = _optional_int(summary_map.get("observation_count"))
    if observation_count is None:
        observation_count = len(rows)
    warning_count = _optional_int(summary_map.get("warning_count"))
    if warning_count is None:
        warning_count = severity_counts.get("warning", 0)
    error_count = _optional_int(summary_map.get("error_count"))
    if error_count is None:
        error_count = severity_counts.get("error", 0)
    times: list[str] = []
    for item in rows:
        stamp = _optional_str(item.get("event_time"))
        if stamp is not None:
            times.append(stamp)
    first_time = min(times) if times else None
    last_time = max(times) if times else None
    digest = _optional_str(payload.get("policy_output_hash"))
    if digest is None:
        try:
            digest = hash_policy_output_mapping(payload)
        except BacktestError:
            digest = None
    config = payload.get("policy_config")
    config_text = canonical_json(config) if isinstance(config, dict) else "{}"
    return _CountView(
        digest=digest,
        observation_count=observation_count,
        counts_by_kind=canonical_json(kind_payload),
        counts_by_severity=canonical_json(dict(sorted(severity_counts.items()))),
        warning_count=warning_count,
        error_count=error_count,
        first_time=first_time,
        last_time=last_time,
        policy_name=_optional_str(payload.get("policy_name")),
        policy_config=config_text,
    )


def _as_compare_mapping(
    source: PolicyRunOutput | Mapping[str, object] | Path | str,
) -> dict[str, object]:
    if isinstance(source, PolicyRunOutput):
        return source.as_mapping()
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    if path.is_dir():
        path = path / POLICY_OUTPUT_ARTIFACT_NAME
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise BacktestError("policy_output.json must be an object")
    return dict(loaded)


def _add(
    items: list[PolicyOutputComparisonItem],
    field: str,
    left: str | None,
    right: str | None,
) -> None:
    if left != right:
        items.append(PolicyOutputComparisonItem(field=field, left=left, right=right))


def _issue(
    severity: PolicyOutputIntegritySeverity,
    code: PolicyOutputIntegrityCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> PolicyOutputVerificationIssue:
    return PolicyOutputVerificationIssue(
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


def _rank(
    issues: list[PolicyOutputVerificationIssue],
) -> tuple[PolicyOutputVerificationIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                POLICY_OUTPUT_SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
                item.path or "",
            ),
        )
    )


def _finish(
    *,
    root: str,
    issues: list[PolicyOutputVerificationIssue],
    policy_name: str | None,
    stored_hash: str | None,
    recomputed_hash: str | None,
    observation_count: int | None,
) -> PolicyOutputVerificationReport:
    ranked = _rank(issues)
    error_count = sum(
        1
        for item in ranked
        if item.severity == PolicyOutputIntegritySeverity.ERROR.value
    )
    warning_count = sum(
        1
        for item in ranked
        if item.severity == PolicyOutputIntegritySeverity.WARNING.value
    )
    info_count = sum(
        1
        for item in ranked
        if item.severity == PolicyOutputIntegritySeverity.INFO.value
    )
    ok = error_count == 0
    return PolicyOutputVerificationReport(
        run_root=root,
        ok=ok,
        status=PolicyOutputStatus.OK.value if ok else PolicyOutputStatus.INVALID.value,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        policy_name=policy_name,
        stored_hash=stored_hash,
        recomputed_hash=recomputed_hash,
        observation_count=observation_count,
    )


class _CountView:
    __slots__ = (
        "counts_by_kind",
        "counts_by_severity",
        "digest",
        "error_count",
        "first_time",
        "last_time",
        "observation_count",
        "policy_config",
        "policy_name",
        "warning_count",
    )

    def __init__(
        self,
        *,
        digest: str | None,
        observation_count: int,
        counts_by_kind: str,
        counts_by_severity: str,
        warning_count: int,
        error_count: int,
        first_time: str | None,
        last_time: str | None,
        policy_name: str | None,
        policy_config: str,
    ) -> None:
        self.digest = digest
        self.observation_count = observation_count
        self.counts_by_kind = counts_by_kind
        self.counts_by_severity = counts_by_severity
        self.warning_count = warning_count
        self.error_count = error_count
        self.first_time = first_time
        self.last_time = last_time
        self.policy_name = policy_name
        self.policy_config = policy_config
