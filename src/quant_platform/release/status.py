"""Lightweight research release status. No trading, no network, no secrets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from quant_platform import __version__
from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.policy_registry import registered_policy_names
from quant_platform.backtest.policy_regression import (
    default_policy_regression_matrix_path,
    load_policy_regression_matrix,
)
from quant_platform.core.config import Settings, get_settings
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    ENABLED_CAPABILITIES,
    EVIDENCE_BUNDLE_DOC_PATH,
    EVIDENCE_BUNDLE_MODULE_PATH,
    EXPECTED_ALEMBIC_HEAD,
    FREEZE_DOC_PATHS,
    RELEASE_STATUS_HASH_FORMAT_VERSION,
    RELEASE_STATUS_HASH_KIND,
)
from quant_platform.release.types import (
    ReleaseCapabilitySummary,
    ReleaseCheckItem,
    ReleaseRiskItem,
    ReleaseStatusReport,
)
from quant_platform.research.snapshots import (
    canonical_json,
    manifest_contains_secrets,
    sha256_canonical,
)

DOCUMENTED_RELEASE_RISKS: tuple[ReleaseRiskItem, ...] = (
    ReleaseRiskItem(
        code="no_data_vendors",
        message="Market data is local CSV only; there is no vendor download client.",
    ),
    ReleaseRiskItem(
        code="no_advanced_normalization",
        message=(
            "Silver OHLCV stays unadjusted; optional derived split "
            "normalization exists; dividends stay informational; "
            "CA methodology is limited to stored split factors."
        ),
    ),
    ReleaseRiskItem(
        code="no_portfolio_pnl",
        message="There is no portfolio, cash, holdings, PnL, or returns engine.",
    ),
    ReleaseRiskItem(
        code="no_strategy_framework",
        message="ResearchPolicy is an observer, not a strategy or signal model.",
    ),
    ReleaseRiskItem(
        code="no_execution",
        message="There is no broker adapter, order execution, or paper/live mode.",
    ),
    ReleaseRiskItem(
        code="policy_regression_manual_goldens",
        message="Policy regression goldens must be copied into matrix.json by hand.",
    ),
    ReleaseRiskItem(
        code="normalization_dividends_informational",
        message="Dividends are informational only; prices are not dividend-adjusted.",
    ),
    ReleaseRiskItem(
        code="normalization_regression_manual_goldens",
        message=(
            "Normalization regression goldens must be copied into "
            "expected.json by hand after review."
        ),
    ),
    ReleaseRiskItem(
        code="postgresql_required",
        message="SQLite is rejected; catalogued research runs need PostgreSQL.",
    ),
    ReleaseRiskItem(
        code="local_artifact_base_dir",
        message=(
            "Replay and backtest artifacts stay on a local base-dir, not cloud storage."
        ),
    ),
    ReleaseRiskItem(
        code="evidence_not_profitability",
        message=(
            "The evidence bundle proves the research pipeline ran; "
            "it does not measure returns or edge."
        ),
    ),
)


def repository_root() -> Path:
    """Resolve the repository root from this package location."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "alembic.ini").is_file() and (parent / "pyproject.toml").is_file():
            return parent
    raise FileNotFoundError("repository root with alembic.ini was not found")


def alembic_script_heads(repo_root: Path | str | None = None) -> tuple[str, ...]:
    """Read Alembic heads from script files. Does not open PostgreSQL."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(repo_root) if repo_root is not None else repository_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    return tuple(sorted(script.get_heads()))


def hash_release_status_report(
    report: ReleaseStatusReport | dict[str, object],
) -> str:
    """SHA-256 of the status report. No wall-clock or absolute paths."""
    if isinstance(report, ReleaseStatusReport):
        payload = report.as_mapping(include_report_hash=False)
    else:
        payload = dict(report)
        payload.pop("report_hash", None)
    digest = {
        "kind": RELEASE_STATUS_HASH_KIND,
        "version": RELEASE_STATUS_HASH_FORMAT_VERSION,
        "ok": payload.get("ok"),
        "app_mode": payload.get("app_mode"),
        "package_version": payload.get("package_version"),
        "alembic_head_expected": payload.get("alembic_head_expected"),
        "alembic_head_scripts": payload.get("alembic_head_scripts"),
        "database_required": payload.get("database_required"),
        "database_checked": payload.get("database_checked"),
        "final_freeze_ready": payload.get("final_freeze_ready"),
        "evidence_bundle_available": payload.get("evidence_bundle_available"),
        "capabilities": payload.get("capabilities"),
        "registered_policy_names": payload.get("registered_policy_names"),
        "regression_case_count": payload.get("regression_case_count"),
        "trading_constructs_detected": payload.get("trading_constructs_detected"),
        "ai_runtime_detected": payload.get("ai_runtime_detected"),
        "error_count": payload.get("error_count"),
        "warning_count": payload.get("warning_count"),
        "checks": payload.get("checks"),
        "risks": payload.get("risks"),
    }
    blob = canonical_json(digest)
    if manifest_contains_secrets(blob):
        raise ValueError("release status report must not contain secrets")
    return sha256_canonical(digest)


def build_release_status(
    *,
    settings: Settings | None = None,
    repo_root: Path | str | None = None,
    matrix_path: Path | str | None = None,
    checks: Sequence[ReleaseCheckItem] = (),
    trading_constructs_detected: bool = False,
    ai_runtime_detected: bool = False,
    database_checked: bool = False,
    alembic_heads: Sequence[str] | None = None,
) -> ReleaseStatusReport:
    """Summarize the research release candidate. Does not ping PostgreSQL."""
    cfg = settings if settings is not None else get_settings()
    root = Path(repo_root) if repo_root is not None else repository_root()
    if alembic_heads is None:
        heads = alembic_script_heads(root)
    else:
        heads = tuple(alembic_heads)
    policies = tuple(sorted(registered_policy_names()))
    case_count = _regression_case_count(matrix_path)
    ranked_checks = tuple(checks)
    error_count = sum(1 for item in ranked_checks if item.status == "error")
    warning_count = sum(1 for item in ranked_checks if item.status == "warning")
    ok = error_count == 0 and cfg.is_research_mode
    bundle_available = evidence_bundle_available(root)
    freeze_ready = final_freeze_ready(
        repo_root=root,
        research_mode=cfg.is_research_mode,
        alembic_heads=heads,
        evidence_bundle=bundle_available,
    )
    draft = ReleaseStatusReport(
        ok=ok,
        app_mode=str(cfg.app_mode),
        package_version=__version__,
        alembic_head_expected=EXPECTED_ALEMBIC_HEAD,
        alembic_head_scripts=heads,
        database_required=True,
        database_checked=database_checked,
        capabilities=ReleaseCapabilitySummary(
            enabled=ENABLED_CAPABILITIES,
            disabled=DISABLED_CAPABILITIES,
        ),
        registered_policy_names=policies,
        registered_policy_count=len(policies),
        regression_case_count=case_count,
        trading_constructs_detected=trading_constructs_detected,
        ai_runtime_detected=ai_runtime_detected,
        final_freeze_ready=freeze_ready,
        evidence_bundle_available=bundle_available,
        checks=ranked_checks,
        risks=DOCUMENTED_RELEASE_RISKS,
        error_count=error_count,
        warning_count=warning_count,
        report_hash="",
    )
    return replace(draft, report_hash=hash_release_status_report(draft))


def freeze_docs_available(repo_root: Path | str | None = None) -> bool:
    """True when Phase 5.4 freeze documents exist. No network, no PostgreSQL."""
    root = Path(repo_root) if repo_root is not None else repository_root()
    return all((root / relative).is_file() for relative in FREEZE_DOC_PATHS)


def evidence_bundle_available(repo_root: Path | str | None = None) -> bool:
    """True when evidence-bundle docs and module exist. Does not build a bundle."""
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / EVIDENCE_BUNDLE_DOC_PATH).is_file() and (
        root / EVIDENCE_BUNDLE_MODULE_PATH
    ).is_file()


def final_freeze_ready(
    *,
    repo_root: Path | str | None = None,
    research_mode: bool,
    alembic_heads: Sequence[str],
    evidence_bundle: bool | None = None,
) -> bool:
    """Lightweight freeze signal from docs and Alembic scripts. Not a trade go-live."""
    root = Path(repo_root) if repo_root is not None else repository_root()
    bundle_ok = (
        evidence_bundle
        if evidence_bundle is not None
        else evidence_bundle_available(root)
    )
    return (
        research_mode
        and freeze_docs_available(root)
        and bundle_ok
        and tuple(alembic_heads) == (EXPECTED_ALEMBIC_HEAD,)
    )


def _regression_case_count(matrix_path: Path | str | None) -> int:
    path = (
        Path(matrix_path)
        if matrix_path is not None
        else default_policy_regression_matrix_path()
    )
    try:
        return len(load_policy_regression_matrix(path))
    except (BacktestError, OSError):
        return 0
