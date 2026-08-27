"""Deterministic ResearchPolicy regression matrix. No database, no trading."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    PolicyRunOutput,
    contains_operative_language,
)
from quant_platform.backtest.policy_interface import apply_research_event
from quant_platform.backtest.policy_output_integrity import verify_policy_output_mapping
from quant_platform.backtest.policy_output_types import PolicyOutputIntegrityCode
from quant_platform.backtest.policy_registry import (
    get_research_policy,
    is_registered_policy,
)
from quant_platform.backtest.policy_regression_types import (
    EXPECTED_DRIFT_CODES,
    POLICY_REGRESSION_HASH_FORMAT_VERSION,
    POLICY_REGRESSION_HASH_KIND,
    POLICY_REGRESSION_MATRIX_FORMAT_VERSION,
    POLICY_REGRESSION_MATRIX_KIND,
    POLICY_REGRESSION_SEVERITY_RANK,
    PolicyRegressionActual,
    PolicyRegressionCase,
    PolicyRegressionCode,
    PolicyRegressionExpected,
    PolicyRegressionIssue,
    PolicyRegressionMatrixReport,
    PolicyRegressionResult,
    PolicyRegressionSeverity,
)
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.snapshots import (
    canonical_json,
    manifest_contains_secrets,
    sha256_canonical,
)
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.event_fixtures import replay_event_from_mapping
from quant_platform.simulation.events import EVENT_PRIORITY, ReplayEvent
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_FORBIDDEN_KIND_FRAGMENTS = (
    "order",
    "trade",
    "fill",
    "signal",
    "position",
    "portfolio",
)
_KNOWN_EVENT_KINDS = frozenset(EVENT_PRIORITY)


def policy_regression_fixtures_dir() -> Path:
    """Resolve ``tests/fixtures/policy_regression`` from the repository."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "policy_regression"
        if candidate.is_dir():
            return candidate
    raise BacktestError(
        "policy regression fixtures directory is missing",
        code=BacktestErrorCode.CATALOG_INVALID,
    )


def default_policy_regression_matrix_path() -> Path:
    return policy_regression_fixtures_dir() / "matrix.json"


def load_policy_regression_events(
    path: Path | str,
) -> tuple[ReplayEvent | str, ...]:
    """Load a small JSONL replay fixture. Unknown kinds stay as strings."""
    root = Path(path)
    try:
        text = root.read_text(encoding="utf-8")
    except OSError as exc:
        raise BacktestError(
            "policy regression fixture cannot be read",
            code=BacktestErrorCode.CATALOG_INVALID,
        ) from exc
    events: list[ReplayEvent | str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BacktestError(
                "policy regression fixture is not valid JSONL",
                code=BacktestErrorCode.CATALOG_INVALID,
            ) from exc
        if not isinstance(payload, dict):
            raise BacktestError(
                "policy regression fixture rows must be objects",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        events.append(_event_from_payload(payload))
    if not events:
        raise BacktestError(
            "policy regression fixture has no events",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return tuple(events)


def load_policy_regression_matrix(
    path: Path | str,
) -> tuple[PolicyRegressionCase, ...]:
    """Parse a declarative regression matrix. Does not run policies."""
    root = Path(path)
    try:
        text = root.read_text(encoding="utf-8")
    except OSError as exc:
        raise BacktestError(
            "policy regression matrix cannot be read",
            code=BacktestErrorCode.CATALOG_INVALID,
        ) from exc
    if manifest_contains_secrets(text):
        raise BacktestError(
            "policy regression matrix must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BacktestError(
            "policy regression matrix is not valid JSON",
            code=BacktestErrorCode.CATALOG_INVALID,
        ) from exc
    if not isinstance(payload, dict):
        raise BacktestError(
            "policy regression matrix must be an object",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    kind = payload.get("kind")
    if kind != POLICY_REGRESSION_MATRIX_KIND:
        raise BacktestError(
            "policy regression matrix kind is invalid",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    version = payload.get("format_version")
    if version != POLICY_REGRESSION_MATRIX_FORMAT_VERSION:
        raise BacktestError(
            "policy regression matrix format_version is invalid",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BacktestError(
            "policy regression matrix cases must be a non-empty list",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    cases: list[PolicyRegressionCase] = []
    seen: set[str] = set()
    for item in raw_cases:
        if not isinstance(item, dict):
            raise BacktestError(
                "policy regression case must be an object",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        case = _case_from_mapping(item)
        if case.case_id in seen:
            raise BacktestError(
                "policy regression case_id must be unique",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        seen.add(case.case_id)
        cases.append(case)
    return tuple(cases)


def run_policy_regression_case(
    case: PolicyRegressionCase,
    *,
    fixture_root: Path | str,
) -> PolicyRegressionResult:
    """Run one matrix case against a local JSONL fixture. No PostgreSQL."""
    issues: list[PolicyRegressionIssue] = []
    fixture_path = case.fixture_path
    if artifact_path_is_unsafe(fixture_path):
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.MISSING_FIXTURE,
                "fixture_path must be a relative file inside the matrix folder",
                path=fixture_path,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    target = Path(fixture_root) / fixture_path
    if not target.is_file():
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.MISSING_FIXTURE,
                "replay fixture is missing",
                path=fixture_path,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    try:
        events = load_policy_regression_events(target)
    except BacktestError as exc:
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.UNEXPECTED_ERROR,
                "replay fixture could not be loaded",
                path=fixture_path,
                actual=exc.code,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    if not is_registered_policy(case.policy_name):
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.UNKNOWN_POLICY,
                "policy_name is not a registered research policy",
                path=fixture_path,
                actual=case.policy_name,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    try:
        policy = get_research_policy(case.policy_name, case.policy_config)
    except BacktestError:
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.INVALID_POLICY_CONFIG,
                "policy_config is not valid for this research policy",
                path=fixture_path,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    try:
        for event in events:
            apply_research_event(policy, event)
        output = policy.finalize()
    except Exception as exc:
        issues.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.UNEXPECTED_ERROR,
                "research policy failed while observing the fixture",
                path=fixture_path,
                actual=type(exc).__name__,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    payload = output.as_mapping()
    issues.extend(scan_policy_regression_payload(payload, path=fixture_path))
    integrity = verify_policy_output_mapping(payload)
    issues.extend(_issues_from_integrity(integrity.issues, path=fixture_path))
    actual = _actual_from_output(case, output, integrity_ok=integrity.ok)
    issues.extend(compare_policy_regression_result(actual, case.expected))
    return _finish_case(case, actual=actual, issues=issues)


def run_policy_regression_matrix(
    matrix_path: Path | str,
) -> PolicyRegressionMatrixReport:
    """Run every matrix case. Does not write artifacts or touch PostgreSQL."""
    root = Path(matrix_path)
    cases = load_policy_regression_matrix(root)
    results = [
        run_policy_regression_case(case, fixture_root=root.parent) for case in cases
    ]
    ranked = tuple(sorted(results, key=lambda item: item.case_id))
    error_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == PolicyRegressionSeverity.ERROR.value
    )
    warning_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == PolicyRegressionSeverity.WARNING.value
    )
    passed_count = sum(1 for item in ranked if item.passed)
    draft = PolicyRegressionMatrixReport(
        case_count=len(ranked),
        passed_count=passed_count,
        failed_count=len(ranked) - passed_count,
        error_count=error_count,
        warning_count=warning_count,
        results=ranked,
        report_hash="",
        ok=all(item.passed for item in ranked),
        matrix_name=root.name,
    )
    return replace(draft, report_hash=hash_policy_regression_report(draft))


def compare_policy_regression_result(
    actual: PolicyRegressionActual,
    expected: PolicyRegressionExpected,
) -> tuple[PolicyRegressionIssue, ...]:
    """Compare actual policy output against optional golden expected values."""
    issues: list[PolicyRegressionIssue] = []
    if expected.policy_output_hash is not None:
        if actual.policy_output_hash != expected.policy_output_hash:
            issues.append(
                _issue(
                    PolicyRegressionSeverity.ERROR,
                    PolicyRegressionCode.POLICY_OUTPUT_HASH_CHANGED,
                    "policy_output_hash differs from the golden expected hash",
                    expected=expected.policy_output_hash,
                    actual=actual.policy_output_hash,
                )
            )
    if expected.observation_count is not None:
        if actual.observation_count != expected.observation_count:
            issues.append(
                _issue(
                    PolicyRegressionSeverity.ERROR,
                    PolicyRegressionCode.OBSERVATION_COUNT_CHANGED,
                    "observation_count differs from the golden expected count",
                    expected=str(expected.observation_count),
                    actual=(
                        None
                        if actual.observation_count is None
                        else str(actual.observation_count)
                    ),
                )
            )
    if expected.counts_by_kind is not None:
        if _count_map(actual.counts_by_kind) != _count_map(expected.counts_by_kind):
            issues.append(
                _issue(
                    PolicyRegressionSeverity.ERROR,
                    PolicyRegressionCode.OBSERVATION_KIND_COUNTS_CHANGED,
                    "counts_by_kind differ from the golden expected counts",
                    expected=canonical_json(_count_map(expected.counts_by_kind)),
                    actual=canonical_json(_count_map(actual.counts_by_kind)),
                )
            )
    if expected.counts_by_severity is not None:
        left = _count_map(actual.counts_by_severity)
        right = _count_map(expected.counts_by_severity)
        if left != right:
            issues.append(
                _issue(
                    PolicyRegressionSeverity.ERROR,
                    PolicyRegressionCode.OBSERVATION_SEVERITY_COUNTS_CHANGED,
                    "counts_by_severity differ from the golden expected counts",
                    expected=canonical_json(right),
                    actual=canonical_json(left),
                )
            )
    return tuple(issues)


def scan_policy_regression_payload(
    payload: Mapping[str, object],
    *,
    path: str | None = None,
) -> tuple[PolicyRegressionIssue, ...]:
    """Flag forbidden operational language in a policy-output mapping."""
    try:
        blob = canonical_json(dict(payload))
    except (TypeError, ValueError):
        return (
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.UNEXPECTED_ERROR,
                "policy output is not JSON-serializable",
                path=path,
            ),
        )
    if contains_operative_language(blob):
        return (
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
                "policy output contains forbidden operational language",
                path=path,
            ),
        )
    return ()


def hash_policy_regression_report(
    report: PolicyRegressionMatrixReport | Mapping[str, object],
) -> str:
    """SHA-256 of the regression report. No wall-clock or absolute paths."""
    if isinstance(report, PolicyRegressionMatrixReport):
        payload = report.as_mapping(include_report_hash=False)
    else:
        payload = dict(report)
        payload.pop("report_hash", None)
    payload.pop("matrix_path", None)
    results = payload.get("results", [])
    ranked: list[dict[str, object]] = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                ranked.append(_result_digest(item))
        ranked.sort(key=canonical_json)
    digest_payload = {
        "kind": POLICY_REGRESSION_HASH_KIND,
        "version": POLICY_REGRESSION_HASH_FORMAT_VERSION,
        "matrix_name": payload.get("matrix_name"),
        "ok": payload.get("ok"),
        "case_count": payload.get("case_count"),
        "passed_count": payload.get("passed_count"),
        "failed_count": payload.get("failed_count"),
        "error_count": payload.get("error_count"),
        "warning_count": payload.get("warning_count"),
        "results": ranked,
    }
    blob = canonical_json(digest_payload)
    if manifest_contains_secrets(blob):
        raise BacktestError(
            "policy regression report must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return sha256_canonical(digest_payload)


def regression_report_has_blocking_errors(
    report: PolicyRegressionMatrixReport,
    *,
    ignore_expected_drift: bool = False,
) -> bool:
    """True when the report has errors that should fail an operator run."""
    for result in report.results:
        for issue in result.issues:
            if issue.severity != PolicyRegressionSeverity.ERROR.value:
                continue
            if ignore_expected_drift and issue.code in EXPECTED_DRIFT_CODES:
                continue
            return True
    return False


def _event_from_payload(payload: Mapping[str, object]) -> ReplayEvent | str:
    kind = payload.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise BacktestError(
            "policy regression fixture event kind is required",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    cleaned = kind.strip()
    lowered = cleaned.lower()
    if any(fragment in lowered for fragment in _FORBIDDEN_KIND_FRAGMENTS):
        raise BacktestError(
            "policy regression fixture contains a trading kind",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if cleaned in _KNOWN_EVENT_KINDS:
        try:
            return replay_event_from_mapping(payload)
        except SimulationError as exc:
            raise BacktestError(
                "policy regression fixture event is invalid",
                code=BacktestErrorCode.CATALOG_INVALID,
            ) from exc
    return cleaned


def _case_from_mapping(payload: Mapping[str, object]) -> PolicyRegressionCase:
    case_id = _require_str(payload, "case_id")
    description = _require_str(payload, "description")
    fixture_path = payload.get("fixture_path", payload.get("fixture"))
    if not isinstance(fixture_path, str) or not fixture_path.strip():
        raise BacktestError(
            "policy regression case fixture_path is required",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    policy_name = _require_str(payload, "policy_name")
    raw_config = payload.get("policy_config", {})
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise BacktestError(
            "policy_config must be an object",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    expected = PolicyRegressionExpected(
        policy_output_hash=_optional_str(payload.get("expected_policy_output_hash")),
        observation_count=_optional_int(payload.get("expected_observation_count")),
        counts_by_kind=_optional_count_map(payload.get("expected_counts_by_kind")),
        counts_by_severity=_optional_count_map(
            payload.get("expected_counts_by_severity")
        ),
    )
    return PolicyRegressionCase(
        case_id=case_id,
        description=description,
        fixture_path=fixture_path.strip(),
        policy_name=policy_name,
        policy_config=dict(raw_config),
        expected=expected,
    )


def _actual_from_output(
    case: PolicyRegressionCase,
    output: PolicyRunOutput,
    *,
    integrity_ok: bool,
) -> PolicyRegressionActual:
    kind_counts = dict(sorted(output.summary.counts_by_kind.items()))
    severity_counts = dict(
        sorted(Counter(item.severity for item in output.observations).items())
    )
    return PolicyRegressionActual(
        case_id=case.case_id,
        policy_name=output.policy_name,
        policy_config=dict(output.policy_config),
        policy_output_hash=output.policy_output_hash,
        observation_count=output.summary.observation_count,
        counts_by_kind=kind_counts,
        counts_by_severity=severity_counts,
        integrity_ok=integrity_ok,
    )


def _finish_case(
    case: PolicyRegressionCase,
    *,
    actual: PolicyRegressionActual | None,
    issues: Sequence[PolicyRegressionIssue],
) -> PolicyRegressionResult:
    unique: list[PolicyRegressionIssue] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in issues:
        key = (
            item.severity,
            item.code,
            item.message,
            item.path or "",
            f"{item.expected}|{item.actual}",
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    ranked = tuple(
        sorted(
            unique,
            key=lambda item: (
                POLICY_REGRESSION_SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
                item.path or "",
            ),
        )
    )
    passed = not any(
        item.severity == PolicyRegressionSeverity.ERROR.value for item in ranked
    )
    return PolicyRegressionResult(
        case_id=case.case_id,
        description=case.description,
        fixture_path=case.fixture_path,
        policy_name=case.policy_name,
        passed=passed,
        actual=actual,
        expected=case.expected,
        issues=ranked,
    )


def _issues_from_integrity(
    integrity_issues: Sequence[object],
    *,
    path: str | None,
) -> tuple[PolicyRegressionIssue, ...]:
    mapped: list[PolicyRegressionIssue] = []
    for item in integrity_issues:
        code = getattr(item, "code", None)
        severity = getattr(item, "severity", None)
        if severity != "error":
            continue
        if code == PolicyOutputIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value:
            mapped.append(
                _issue(
                    PolicyRegressionSeverity.ERROR,
                    PolicyRegressionCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
                    "policy output failed integrity for operational language",
                    path=path,
                )
            )
            continue
        mapped.append(
            _issue(
                PolicyRegressionSeverity.ERROR,
                PolicyRegressionCode.UNEXPECTED_ERROR,
                "policy output failed integrity verification",
                path=path,
                actual=str(code) if code is not None else None,
            )
        )
    return tuple(mapped)


def _result_digest(item: Mapping[str, object]) -> dict[str, object]:
    actual = item.get("actual")
    actual_map = actual if isinstance(actual, dict) else {}
    issues = item.get("issues", [])
    codes: list[str] = []
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and isinstance(issue.get("code"), str):
                codes.append(issue["code"])
    return {
        "case_id": item.get("case_id"),
        "fixture_path": item.get("fixture_path"),
        "policy_name": item.get("policy_name"),
        "passed": item.get("passed"),
        "policy_output_hash": actual_map.get("policy_output_hash"),
        "observation_count": actual_map.get("observation_count"),
        "counts_by_kind": actual_map.get("counts_by_kind"),
        "counts_by_severity": actual_map.get("counts_by_severity"),
        "issue_codes": sorted(codes),
    }


def _issue(
    severity: PolicyRegressionSeverity,
    code: PolicyRegressionCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> PolicyRegressionIssue:
    return PolicyRegressionIssue(
        severity=severity.value,
        code=code.value,
        message=redact_secret_text(message),
        path=path,
        expected=expected,
        actual=None if actual is None else redact_secret_text(actual),
    )


def _count_map(value: Mapping[str, int]) -> dict[str, int]:
    return {str(key): int(count) for key, count in sorted(value.items())}


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BacktestError(
            f"{key} is required",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BacktestError(
            "expected hash must be a non-empty string when set",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value.strip()


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(
            "expected observation_count must be an integer",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if value < 0:
        raise BacktestError(
            "expected observation_count must be >= 0",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value


def _optional_count_map(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BacktestError(
            "expected count maps must be objects",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    counts: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key.strip():
            raise BacktestError(
                "expected count map keys must be strings",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise BacktestError(
                "expected count map values must be integers >= 0",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        counts[key.strip()] = raw
    return dict(sorted(counts.items()))
