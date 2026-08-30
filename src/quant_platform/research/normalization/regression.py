"""Deterministic corporate-action normalization regression. No database, no trading."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from quant_platform.core.redact import redact_secret_text
from quant_platform.data.csv_loader import CsvLoadError, parse_utc_datetime
from quant_platform.data.validation import DataValidationError, parse_decimal
from quant_platform.research.normalization.datasets import assemble_normalized_dataset
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.regression_types import (
    ACTIONS_FIXTURE_NAME,
    BARS_FIXTURE_NAME,
    EXPECTED_DRIFT_CODES,
    EXPECTED_FIXTURE_NAME,
    NORMALIZATION_REGRESSION_HASH_FORMAT_VERSION,
    NORMALIZATION_REGRESSION_HASH_KIND,
    NORMALIZATION_REGRESSION_SEVERITY_RANK,
    REQUEST_FIXTURE_NAME,
    NormalizationRegressionActual,
    NormalizationRegressionCase,
    NormalizationRegressionCode,
    NormalizationRegressionExpected,
    NormalizationRegressionIssue,
    NormalizationRegressionMatrixReport,
    NormalizationRegressionResult,
    NormalizationRegressionSeverity,
)
from quant_platform.research.normalization.types import (
    AdjustmentMode,
    NormalizedDailyBar,
    NormalizedDailyBarsDataset,
    build_normalization_request,
)
from quant_platform.research.snapshots import (
    canonical_json,
    manifest_contains_secrets,
    sha256_canonical,
)
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_ONE = Decimal("1")
_FORBIDDEN_METRIC_PATTERN = re.compile(
    r"\b(sharpe|drawdown|hit_ratio|hit ratio|pnl|returns|return|"
    r"portfolio|exposure)\b",
    re.IGNORECASE,
)
_REQUIRED_CASE_FILES = (
    BARS_FIXTURE_NAME,
    ACTIONS_FIXTURE_NAME,
    REQUEST_FIXTURE_NAME,
    EXPECTED_FIXTURE_NAME,
)


def default_normalization_regression_dir() -> Path:
    """Resolve ``tests/fixtures/normalization_regression`` from the repository."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "normalization_regression"
        if candidate.is_dir():
            return candidate
    raise NormalizationError(
        "normalization regression fixtures directory is missing",
        code=NormalizationErrorCode.ARTIFACT_INVALID,
    )


def load_normalization_regression_case(
    path: Path | str,
) -> NormalizationRegressionCase:
    """Parse one golden case directory. Does not run normalization."""
    root = Path(path)
    case_id = root.name
    if artifact_path_is_unsafe(case_id):
        raise NormalizationError(
            "normalization regression case path must be a relative directory name",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    request_payload = _load_json_object(root / REQUEST_FIXTURE_NAME, required=False)
    expected_payload = _load_json_object(root / EXPECTED_FIXTURE_NAME, required=False)
    mode = ""
    as_of: datetime | None = None
    if request_payload is not None:
        raw_mode = request_payload.get("adjustment_mode", AdjustmentMode.SPLIT_ONLY)
        mode = str(raw_mode).strip()
        raw_as_of = request_payload.get("as_of")
        if isinstance(raw_as_of, str) and raw_as_of.strip():
            as_of = parse_utc_datetime(raw_as_of, field="as_of")
    expected = _expected_from_mapping(expected_payload)
    return NormalizationRegressionCase(
        case_id=case_id,
        fixture_dir=case_id,
        adjustment_mode=mode,
        as_of=as_of,
        expected=expected,
    )


def run_normalization_regression_case(
    case: NormalizationRegressionCase,
    *,
    fixtures_root: Path | str | None = None,
) -> NormalizationRegressionResult:
    """Run one case against local CSV fixtures. Does not open PostgreSQL."""
    issues: list[NormalizationRegressionIssue] = []
    root = (
        default_normalization_regression_dir()
        if fixtures_root is None
        else Path(fixtures_root)
    )
    if artifact_path_is_unsafe(case.fixture_dir):
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.MISSING_FIXTURE,
                "fixture_dir must be a relative case directory name",
                path=case.fixture_dir,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    target = root / case.fixture_dir
    if not target.is_dir():
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.MISSING_FIXTURE,
                "normalization regression case directory is missing",
                path=case.fixture_dir,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    missing = [name for name in _REQUIRED_CASE_FILES if not (target / name).is_file()]
    if missing:
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.MISSING_FIXTURE,
                f"missing fixture files: {', '.join(missing)}",
                path=case.fixture_dir,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    try:
        request_payload = _load_json_object(
            target / REQUEST_FIXTURE_NAME, required=True
        )
        if request_payload is None:
            raise NormalizationError(
                "request.json is required",
                code=NormalizationErrorCode.ARTIFACT_INVALID,
            )
        issues.extend(
            scan_normalization_regression_text(
                _fixture_blob(target),
                path=case.fixture_dir,
            )
        )
        dataset = _assemble_from_fixtures(target, request_payload)
    except NormalizationError as exc:
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.INVALID_REQUEST,
                "normalization request is invalid",
                path=case.fixture_dir,
                actual=exc.code,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    except (OSError, CsvLoadError, DataValidationError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.UNEXPECTED_ERROR,
                "normalization fixture could not be assembled",
                path=case.fixture_dir,
                actual=str(code),
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    except Exception as exc:
        issues.append(
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.UNEXPECTED_ERROR,
                "normalization regression case failed unexpectedly",
                path=case.fixture_dir,
                actual=type(exc).__name__,
            )
        )
        return _finish_case(case, actual=None, issues=issues)
    actual = _actual_from_dataset(case, dataset)
    issues.extend(
        scan_normalization_regression_text(
            canonical_json(actual.as_mapping()),
            path=case.fixture_dir,
        )
    )
    issues.extend(compare_normalization_regression_result(actual, case.expected))
    return _finish_case(case, actual=actual, issues=issues)


def run_normalization_regression_matrix(
    root_dir: Path | str | None = None,
) -> NormalizationRegressionMatrixReport:
    """Run every case directory. Does not write artifacts or touch PostgreSQL."""
    root = (
        default_normalization_regression_dir() if root_dir is None else Path(root_dir)
    )
    if not root.is_dir():
        raise NormalizationError(
            "normalization regression fixtures directory is missing",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    case_dirs = sorted(
        item
        for item in root.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    )
    if not case_dirs:
        raise NormalizationError(
            "normalization regression fixtures directory has no cases",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    results = [
        run_normalization_regression_case(
            load_normalization_regression_case(item),
            fixtures_root=root,
        )
        for item in case_dirs
    ]
    ranked = tuple(sorted(results, key=lambda item: item.case_id))
    error_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == NormalizationRegressionSeverity.ERROR.value
    )
    warning_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == NormalizationRegressionSeverity.WARNING.value
    )
    passed_count = sum(1 for item in ranked if item.passed)
    draft = NormalizationRegressionMatrixReport(
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
    return replace(draft, report_hash=hash_normalization_regression_report(draft))


def compare_normalization_regression_result(
    actual: NormalizationRegressionActual,
    expected: NormalizationRegressionExpected,
) -> tuple[NormalizationRegressionIssue, ...]:
    """Compare assembled actuals against optional golden expected values."""
    issues: list[NormalizationRegressionIssue] = []
    if expected.dataset_hash is not None:
        if actual.dataset_hash != expected.dataset_hash:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.DATASET_HASH_CHANGED,
                    "dataset_hash differs from the golden expected hash",
                    expected=expected.dataset_hash,
                    actual=actual.dataset_hash,
                )
            )
    if expected.bar_count is not None:
        if actual.bar_count != expected.bar_count:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.BAR_COUNT_CHANGED,
                    "bar_count differs from the golden expected count",
                    expected=str(expected.bar_count),
                    actual=_optional_int_text(actual.bar_count),
                )
            )
    if expected.issue_count is not None:
        if actual.issue_count != expected.issue_count:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.ISSUE_COUNT_CHANGED,
                    "issue_count differs from the golden expected count",
                    expected=str(expected.issue_count),
                    actual=_optional_int_text(actual.issue_count),
                )
            )
    if expected.adjusted_bar_count is not None:
        if actual.adjusted_bar_count != expected.adjusted_bar_count:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.ADJUSTED_BAR_COUNT_CHANGED,
                    "adjusted_bar_count differs from the golden expected count",
                    expected=str(expected.adjusted_bar_count),
                    actual=_optional_int_text(actual.adjusted_bar_count),
                )
            )
    if expected.actions_applied is not None:
        if actual.actions_applied != expected.actions_applied:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.ACTIONS_APPLIED_CHANGED,
                    "actions_applied differs from the golden expected count",
                    expected=str(expected.actions_applied),
                    actual=_optional_int_text(actual.actions_applied),
                )
            )
    if expected.warnings is not None:
        left = tuple(sorted(actual.warnings))
        right = tuple(sorted(expected.warnings))
        if left != right:
            issues.append(
                _issue(
                    NormalizationRegressionSeverity.ERROR,
                    NormalizationRegressionCode.WARNING_COUNT_CHANGED,
                    "warnings differ from the golden expected warning codes",
                    expected=canonical_json(list(right)),
                    actual=canonical_json(list(left)),
                )
            )
    return tuple(issues)


def scan_normalization_regression_text(
    blob: str,
    *,
    path: str | None = None,
) -> tuple[NormalizationRegressionIssue, ...]:
    """Flag forbidden performance metrics in fixture or report text."""
    if manifest_contains_secrets(blob):
        return (
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.UNEXPECTED_ERROR,
                "normalization regression payload must not contain secrets",
                path=path,
            ),
        )
    if _FORBIDDEN_METRIC_PATTERN.search(blob):
        return (
            _issue(
                NormalizationRegressionSeverity.ERROR,
                NormalizationRegressionCode.FORBIDDEN_METRIC_DETECTED,
                "normalization regression payload contains a forbidden metric",
                path=path,
            ),
        )
    return ()


def hash_normalization_regression_report(
    report: NormalizationRegressionMatrixReport | Mapping[str, object],
) -> str:
    """SHA-256 of the regression report. No wall-clock or absolute paths."""
    if isinstance(report, NormalizationRegressionMatrixReport):
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
        "kind": NORMALIZATION_REGRESSION_HASH_KIND,
        "version": NORMALIZATION_REGRESSION_HASH_FORMAT_VERSION,
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
        raise NormalizationError(
            "normalization regression report must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    return sha256_canonical(digest_payload)


def normalization_regression_report_has_blocking_errors(
    report: NormalizationRegressionMatrixReport,
    *,
    ignore_expected_drift: bool = False,
) -> bool:
    """True when the report has errors that should fail an operator run."""
    for result in report.results:
        for issue in result.issues:
            if issue.severity != NormalizationRegressionSeverity.ERROR.value:
                continue
            if ignore_expected_drift and issue.code in EXPECTED_DRIFT_CODES:
                continue
            return True
    return False


def _assemble_from_fixtures(
    case_dir: Path,
    request_payload: Mapping[str, object],
) -> NormalizedDailyBarsDataset:
    request = build_normalization_request(
        as_of=_require_timestamp(request_payload, "as_of"),
        start_time=_require_timestamp(request_payload, "start_time"),
        end_time=_require_timestamp(request_payload, "end_time"),
        source_name=_require_str(request_payload, "source_name"),
        adjustment_mode=str(
            request_payload.get("adjustment_mode") or AdjustmentMode.SPLIT_ONLY
        ),
        symbols=_optional_string_tuple(request_payload.get("symbols")),
    )
    bars = load_normalization_daily_bars_csv(case_dir / BARS_FIXTURE_NAME)
    actions = load_normalization_corporate_actions_csv(case_dir / ACTIONS_FIXTURE_NAME)
    raw = DailyBarsDataset(request=request.dataset_request(), rows=bars)
    return assemble_normalized_dataset(
        request=request,
        raw_dataset=raw,
        visible_actions=actions,
    )


def load_normalization_daily_bars_csv(
    path: Path | str,
) -> tuple[DailyBarDatasetRow, ...]:
    """Load dataset-shaped daily bars from a local CSV. No PostgreSQL."""
    rows: list[DailyBarDatasetRow] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            volume_raw = (raw.get("volume") or "").strip()
            rows.append(
                DailyBarDatasetRow(
                    instrument_id=_require_uuid(raw, "instrument_id"),
                    symbol=_require_csv_str(raw, "symbol"),
                    exchange_code=_optional_csv_str(raw.get("exchange_code")),
                    asset_class=_require_csv_str(raw, "asset_class"),
                    currency=_optional_csv_str(raw.get("currency")),
                    observation_time=parse_utc_datetime(
                        raw["observation_time"], field="observation_time"
                    ),
                    available_time=parse_utc_datetime(
                        raw["available_time"], field="available_time"
                    ),
                    open=parse_decimal(raw["open"], field="open"),
                    high=parse_decimal(raw["high"], field="high"),
                    low=parse_decimal(raw["low"], field="low"),
                    close=parse_decimal(raw["close"], field="close"),
                    volume=None
                    if not volume_raw
                    else parse_decimal(volume_raw, field="volume"),
                    source_name=_require_csv_str(raw, "source_name"),
                    ingestion_run_id=_require_uuid(raw, "ingestion_run_id"),
                    is_correction=_parse_bool(raw.get("is_correction")),
                    correction_reason=_optional_csv_str(raw.get("correction_reason")),
                )
            )
    if not rows:
        raise NormalizationError(
            "daily_bars.csv has no rows",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return tuple(rows)


def load_normalization_corporate_actions_csv(
    path: Path | str,
) -> tuple[CorporateActionDatasetRow, ...]:
    """Load stored corporate actions from a local CSV. No PostgreSQL."""
    rows: list[CorporateActionDatasetRow] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                CorporateActionDatasetRow(
                    instrument_id=_require_uuid(raw, "instrument_id"),
                    symbol=_require_csv_str(raw, "symbol"),
                    exchange_code=_optional_csv_str(raw.get("exchange_code")),
                    asset_class=_require_csv_str(raw, "asset_class"),
                    action_type=_require_csv_str(raw, "action_type"),
                    effective_time=parse_utc_datetime(
                        raw["effective_time"], field="effective_time"
                    ),
                    available_time=parse_utc_datetime(
                        raw["available_time"], field="available_time"
                    ),
                    quantity_before=_optional_decimal(
                        raw.get("quantity_before"), "quantity_before"
                    ),
                    quantity_after=_optional_decimal(
                        raw.get("quantity_after"), "quantity_after"
                    ),
                    cash_amount=_optional_decimal(
                        raw.get("cash_amount"), "cash_amount"
                    ),
                    currency=_optional_csv_str(raw.get("currency")),
                    old_value=_optional_csv_str(raw.get("old_value")),
                    new_value=_optional_csv_str(raw.get("new_value")),
                    note=_optional_csv_str(raw.get("note")),
                    id=_optional_uuid(raw.get("id")),
                )
            )
    return tuple(rows)


def _actual_from_dataset(
    case: NormalizationRegressionCase,
    dataset: NormalizedDailyBarsDataset,
) -> NormalizationRegressionActual:
    warnings = tuple(
        sorted(
            {item.code for item in dataset.report.issues if item.severity == "warning"}
        )
    )
    return NormalizationRegressionActual(
        case_id=case.case_id,
        adjustment_mode=dataset.request.adjustment_mode.value,
        as_of=dataset.request.as_of,
        dataset_hash=dataset.dataset_hash,
        bar_count=len(dataset.rows),
        issue_count=dataset.report.issue_count,
        adjusted_bar_count=_adjusted_bar_count(dataset.rows),
        actions_applied=dataset.report.applied_action_count,
        warnings=warnings,
        raw_dataset_hash=dataset.raw_dataset_hash,
    )


def _adjusted_bar_count(rows: Sequence[NormalizedDailyBar]) -> int:
    return sum(1 for row in rows if _bar_was_adjusted(row))


def _bar_was_adjusted(row: NormalizedDailyBar) -> bool:
    return (
        row.price_factor != _ONE
        or row.volume_factor != _ONE
        or bool(row.applied_action_ids)
    )


def _finish_case(
    case: NormalizationRegressionCase,
    *,
    actual: NormalizationRegressionActual | None,
    issues: Sequence[NormalizationRegressionIssue],
) -> NormalizationRegressionResult:
    unique: list[NormalizationRegressionIssue] = []
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
                NORMALIZATION_REGRESSION_SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
                item.path or "",
            ),
        )
    )
    passed = not any(
        item.severity == NormalizationRegressionSeverity.ERROR.value for item in ranked
    )
    return NormalizationRegressionResult(
        case_id=case.case_id,
        fixture_dir=case.fixture_dir,
        adjustment_mode=case.adjustment_mode,
        as_of=case.as_of,
        passed=passed,
        actual=actual,
        expected=case.expected,
        issues=ranked,
    )


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
        "fixture_dir": item.get("fixture_dir"),
        "adjustment_mode": item.get("adjustment_mode"),
        "as_of": item.get("as_of"),
        "passed": item.get("passed"),
        "dataset_hash": actual_map.get("dataset_hash"),
        "bar_count": actual_map.get("bar_count"),
        "issue_count": actual_map.get("issue_count"),
        "adjusted_bar_count": actual_map.get("adjusted_bar_count"),
        "actions_applied": actual_map.get("actions_applied"),
        "warnings": actual_map.get("warnings"),
        "issue_codes": sorted(codes),
    }


def _issue(
    severity: NormalizationRegressionSeverity,
    code: NormalizationRegressionCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> NormalizationRegressionIssue:
    return NormalizationRegressionIssue(
        severity=severity.value,
        code=code.value,
        message=redact_secret_text(message),
        path=path,
        expected=expected,
        actual=None if actual is None else redact_secret_text(actual),
    )


def _expected_from_mapping(
    payload: Mapping[str, object] | None,
) -> NormalizationRegressionExpected:
    if payload is None:
        return NormalizationRegressionExpected()
    warnings = payload.get("expected_warnings")
    warning_codes: tuple[str, ...] | None = None
    if warnings is not None:
        if not isinstance(warnings, list):
            raise NormalizationError(
                "expected_warnings must be a list",
                code=NormalizationErrorCode.ARTIFACT_INVALID,
            )
        warning_codes = tuple(
            str(item).strip() for item in warnings if str(item).strip()
        )
    return NormalizationRegressionExpected(
        dataset_hash=_optional_str(payload.get("expected_dataset_hash")),
        bar_count=_optional_int(payload.get("expected_bar_count")),
        issue_count=_optional_int(payload.get("expected_issue_count")),
        adjusted_bar_count=_optional_int(payload.get("expected_adjusted_bar_count")),
        actions_applied=_optional_int(payload.get("expected_actions_applied")),
        warnings=warning_codes,
    )


def _load_json_object(path: Path, *, required: bool) -> dict[str, object] | None:
    if not path.is_file():
        if required:
            raise NormalizationError(
                f"{path.name} is required",
                code=NormalizationErrorCode.ARTIFACT_INVALID,
            )
        return None
    text = path.read_text(encoding="utf-8")
    if manifest_contains_secrets(text):
        raise NormalizationError(
            f"{path.name} must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NormalizationError(
            f"{path.name} is not valid JSON",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        ) from exc
    if not isinstance(payload, dict):
        raise NormalizationError(
            f"{path.name} must be an object",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return payload


def _fixture_blob(case_dir: Path) -> str:
    parts: list[str] = []
    for name in _REQUIRED_CASE_FILES:
        path = case_dir / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _require_timestamp(payload: Mapping[str, object], key: str) -> datetime:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(
            f"{key} is required",
            code=NormalizationErrorCode.MISSING_AS_OF
            if key == "as_of"
            else NormalizationErrorCode.INVALID_RANGE,
        )
    return parse_utc_datetime(value, field=key)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(
            f"{key} is required",
            code=NormalizationErrorCode.MISSING_SOURCE
            if key == "source_name"
            else NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return value.strip()


def _optional_string_tuple(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise NormalizationError(
            "symbols must be a list",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    rows = [str(item).strip() for item in value if str(item).strip()]
    return tuple(rows) or None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(
            "expected hash must be a non-empty string when set",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return value.strip()


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(
            "expected counts must be integers",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    if value < 0:
        raise NormalizationError(
            "expected counts must be >= 0",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return value


def _optional_int_text(value: int | None) -> str | None:
    return None if value is None else str(value)


def _require_csv_str(row: Mapping[str, str | None], key: str) -> str:
    value = (row.get(key) or "").strip()
    if not value:
        raise NormalizationError(
            f"{key} is required",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    return value


def _optional_csv_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _require_uuid(row: Mapping[str, str | None], key: str) -> UUID:
    raw = _require_csv_str(row, key)
    try:
        return UUID(raw)
    except ValueError as exc:
        raise NormalizationError(
            f"{key} is not a valid UUID",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        ) from exc


def _optional_uuid(value: str | None) -> UUID | None:
    raw = _optional_csv_str(value)
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise NormalizationError(
            "id is not a valid UUID",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        ) from exc


def _optional_decimal(value: str | None, field: str) -> Decimal | None:
    raw = _optional_csv_str(value)
    if raw is None:
        return None
    return parse_decimal(raw, field=field)


def _parse_bool(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    return raw in {"1", "true", "yes"}
