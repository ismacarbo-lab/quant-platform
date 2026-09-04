"""Research release checks. Repo-local, no vendors, no trading."""

from __future__ import annotations

import importlib
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.policy_regression import (
    default_policy_regression_matrix_path,
    run_policy_regression_matrix,
)
from quant_platform.core.config import Settings, get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.constants import (
    EXPECTED_ALEMBIC_HEAD,
    EXPECTED_PUBLIC_TABLES,
    SMOKE_IMPORT_MODULES,
)
from quant_platform.release.guards import (
    detect_ai_runtime,
    detect_contracts_networking,
    detect_real_vendor_clients,
    forbidden_dependencies_declared,
    forbidden_runtime_packages_present,
)
from quant_platform.release.status import (
    alembic_script_heads,
    build_release_status,
    repository_root,
)
from quant_platform.release.types import ReleaseCheckItem, ReleaseStatusReport
from quant_platform.research.normalization.errors import NormalizationError
from quant_platform.research.normalization.regression import (
    default_normalization_regression_dir,
    run_normalization_regression_matrix,
)
from quant_platform.simulation.constructs import (
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.storage.database import (
    create_db_engine,
    list_public_tables,
    ping_database,
)


def run_research_release_checks(
    *,
    settings: Settings | None = None,
    repo_root: Path | str | None = None,
    package_root: Path | str | None = None,
    matrix_path: Path | str | None = None,
    skip_db: bool = False,
    require_db: bool = False,
    skip_compose: bool = False,
    skip_regression: bool = False,
    skip_normalization_regression: bool = False,
    skip_data_contract_conformance: bool = False,
    skip_data_contract_schema_compatibility: bool = False,
    skip_contract_payload_intake: bool = False,
    skip_imports: bool = False,
    research_mode: bool | None = None,
    normalization_fixtures_dir: Path | str | None = None,
    conformance_fixtures_dir: Path | str | None = None,
    schema_baseline_file: Path | str | None = None,
    intake_fixtures_dir: Path | str | None = None,
) -> ReleaseStatusReport:
    """Run research release-candidate checks. Never prints secrets."""
    root = Path(repo_root) if repo_root is not None else repository_root()
    pkg = (
        Path(package_root)
        if package_root is not None
        else root / "src" / "quant_platform"
    )
    matrix = (
        Path(matrix_path)
        if matrix_path is not None
        else default_policy_regression_matrix_path()
    )
    cfg = settings if settings is not None else get_settings()
    checks: list[ReleaseCheckItem] = []
    checks.append(_check_app_mode(cfg, research_mode=research_mode))
    checks.append(_check_postgresql_url(cfg))
    checks.append(_check_alembic_scripts(root))
    construct_item, constructs_detected = _check_trading_constructs(pkg)
    checks.append(construct_item)
    ai_item, ai_detected = _check_ai_runtime(root, pkg, cfg)
    checks.append(ai_item)
    checks.append(_check_forbidden_packages(pkg))
    checks.append(_check_forbidden_dependencies(root / "pyproject.toml"))
    checks.append(_check_vendor_runtime(pkg))
    if not skip_imports:
        checks.append(_check_smoke_imports())
    if not skip_regression:
        checks.append(_check_policy_regression(matrix))
    if not skip_normalization_regression:
        fixtures = (
            Path(normalization_fixtures_dir)
            if normalization_fixtures_dir is not None
            else default_normalization_regression_dir()
        )
        checks.append(_check_normalization_regression(fixtures))
    if not skip_data_contract_conformance:
        from quant_platform.data.contracts.conformance_regression import (
            default_data_contract_conformance_dir,
        )

        conformance_root = (
            Path(conformance_fixtures_dir)
            if conformance_fixtures_dir is not None
            else default_data_contract_conformance_dir()
        )
        checks.append(_check_data_contract_conformance(conformance_root))
    if not skip_data_contract_schema_compatibility:
        from quant_platform.data.contracts.schema_export import (
            default_schema_baseline_path,
        )

        baseline = (
            Path(schema_baseline_file)
            if schema_baseline_file is not None
            else default_schema_baseline_path()
        )
        checks.append(_check_data_contract_schema_compatibility(baseline))
    if not skip_contract_payload_intake:
        from quant_platform.data.contracts.intake_regression import (
            default_contract_payload_intake_dir,
        )

        intake_root = (
            Path(intake_fixtures_dir)
            if intake_fixtures_dir is not None
            else default_contract_payload_intake_dir()
        )
        checks.append(_check_contract_payload_intake(intake_root))
    if not skip_compose:
        checks.append(_check_compose_config(root))
    database_checked = False
    if require_db or not skip_db:
        db_item, database_checked = _check_database(cfg, require=require_db)
        checks.append(db_item)
    return build_release_status(
        settings=cfg,
        repo_root=root,
        matrix_path=matrix,
        checks=tuple(checks),
        trading_constructs_detected=constructs_detected,
        ai_runtime_detected=ai_detected,
        database_checked=database_checked,
    )


def _ok(name: str, message: str, *, code: str | None = None) -> ReleaseCheckItem:
    return ReleaseCheckItem(name=name, status="ok", message=message, code=code)


def _error(name: str, message: str, *, code: str) -> ReleaseCheckItem:
    return ReleaseCheckItem(
        name=name,
        status="error",
        message=redact_secret_text(message),
        code=code,
    )


def _warning(name: str, message: str, *, code: str) -> ReleaseCheckItem:
    return ReleaseCheckItem(
        name=name,
        status="warning",
        message=redact_secret_text(message),
        code=code,
    )


def _skipped(name: str, message: str, *, code: str) -> ReleaseCheckItem:
    return ReleaseCheckItem(
        name=name,
        status="skipped",
        message=redact_secret_text(message),
        code=code,
    )


def _check_app_mode(
    settings: Settings,
    *,
    research_mode: bool | None,
) -> ReleaseCheckItem:
    is_research = settings.is_research_mode if research_mode is None else research_mode
    if is_research:
        return _ok("app_mode", "APP_MODE is research")
    return _error(
        "app_mode",
        "APP_MODE must be research",
        code="app_mode_not_research",
    )


def _check_postgresql_url(settings: Settings) -> ReleaseCheckItem:
    if settings.database_url.startswith("postgresql"):
        return _ok("postgres_url_scheme", "configured store is PostgreSQL")
    return _error(
        "postgres_url_scheme",
        "configured store must be PostgreSQL; SQLite is not allowed",
        code="sqlite_fallback",
    )


def _check_alembic_scripts(repo_root: Path) -> ReleaseCheckItem:
    try:
        heads = alembic_script_heads(repo_root)
    except Exception as exc:
        return _error(
            "alembic_scripts",
            f"could not read Alembic script heads: {type(exc).__name__}",
            code="alembic_scripts_unreadable",
        )
    if heads == (EXPECTED_ALEMBIC_HEAD,):
        return _ok(
            "alembic_scripts",
            f"Alembic script head is {EXPECTED_ALEMBIC_HEAD}",
        )
    return _error(
        "alembic_scripts",
        "Alembic script head does not match expected "
        f"{EXPECTED_ALEMBIC_HEAD}: {','.join(heads) or 'none'}",
        code="alembic_head_mismatch",
    )


def _check_trading_constructs(
    package_root: Path,
) -> tuple[ReleaseCheckItem, bool]:
    findings = detect_trading_constructs(
        package_root=package_root,
        scan_tables=True,
        scan_packages=True,
    )
    if findings:
        names = ", ".join(item.name for item in findings)
        return (
            _error(
                "trading_constructs",
                f"forbidden trading constructs present: {names}",
                code="trading_construct_detected",
            ),
            True,
        )
    return (
        _ok("trading_constructs", "no trading constructs in package or tables"),
        False,
    )


def _check_ai_runtime(
    repo_root: Path,
    package_root: Path,
    settings: Settings,
) -> tuple[ReleaseCheckItem, bool]:
    findings = detect_ai_runtime(
        package_root=package_root,
        pyproject_path=repo_root / "pyproject.toml",
        settings_fields={name: True for name in type(settings).model_fields},
    )
    if findings:
        return (
            _error(
                "ai_runtime",
                f"AI runtime markers present: {', '.join(findings)}",
                code="ai_runtime_detected",
            ),
            True,
        )
    return (_ok("ai_runtime", "no AI runtime client or dependency"), False)


def _check_forbidden_packages(package_root: Path) -> ReleaseCheckItem:
    present = forbidden_runtime_packages_present(package_root)
    if present:
        return _error(
            "architecture_packages",
            f"forbidden packages present: {', '.join(present)}",
            code="forbidden_package",
        )
    return _ok("architecture_packages", "no strategy/signal/broker packages")


def _check_forbidden_dependencies(pyproject_path: Path) -> ReleaseCheckItem:
    leaked = forbidden_dependencies_declared(pyproject_path)
    if leaked:
        return _error(
            "architecture_dependencies",
            f"forbidden dependencies declared: {', '.join(leaked)}",
            code="forbidden_dependency",
        )
    return _ok(
        "architecture_dependencies",
        "no trading, vendor, or AI runtime dependencies",
    )


def _check_vendor_runtime(package_root: Path) -> ReleaseCheckItem:
    clients = detect_real_vendor_clients(package_root)
    networking = detect_contracts_networking(package_root)
    if clients:
        return _error(
            "vendor_runtime",
            f"real vendor clients present: {', '.join(clients)}",
            code="real_vendor_client",
        )
    if networking:
        return _error(
            "vendor_runtime",
            f"vendor contracts must stay offline: {', '.join(networking)}",
            code="contracts_networking",
        )
    return _ok(
        "vendor_runtime",
        "no real vendor clients or contract networking",
    )


def _check_smoke_imports() -> ReleaseCheckItem:
    failed: list[str] = []
    for name in SMOKE_IMPORT_MODULES:
        try:
            importlib.import_module(name)
        except Exception:
            failed.append(name)
    if failed:
        return _error(
            "smoke_imports",
            f"import failed: {', '.join(failed)}",
            code="import_failure",
        )
    return _ok("smoke_imports", "research modules import")


def _check_policy_regression(matrix_path: Path) -> ReleaseCheckItem:
    try:
        report = run_policy_regression_matrix(matrix_path)
    except (BacktestError, OSError) as exc:
        return _error(
            "policy_regression",
            f"policy regression matrix could not run: {type(exc).__name__}",
            code="policy_regression_error",
        )
    if report.ok:
        return _ok(
            "policy_regression",
            f"{report.passed_count}/{report.case_count} regression cases passed",
        )
    return _error(
        "policy_regression",
        f"policy regression failed: {report.failed_count} cases, "
        f"{report.error_count} errors",
        code="policy_regression_failed",
    )


def _check_normalization_regression(fixtures_dir: Path) -> ReleaseCheckItem:
    try:
        report = run_normalization_regression_matrix(fixtures_dir)
    except (NormalizationError, OSError) as exc:
        return _error(
            "normalization_regression",
            f"normalization regression matrix could not run: {type(exc).__name__}",
            code="normalization_regression_error",
        )
    if report.ok:
        return _ok(
            "normalization_regression",
            f"{report.passed_count}/{report.case_count} regression cases passed",
        )
    return _error(
        "normalization_regression",
        f"normalization regression failed: {report.failed_count} cases, "
        f"{report.error_count} errors",
        code="normalization_regression_failed",
    )


def _check_data_contract_conformance(fixtures_dir: Path) -> ReleaseCheckItem:
    from quant_platform.data.contracts.conformance_regression import (
        run_data_contract_conformance_regression,
    )
    from quant_platform.data.contracts.errors import VendorContractError

    try:
        report = run_data_contract_conformance_regression(fixtures_dir)
    except (VendorContractError, OSError) as exc:
        return _error(
            "data_contract_conformance",
            f"data-contract conformance matrix could not run: {type(exc).__name__}",
            code="data_contract_conformance_error",
        )
    if report.ok:
        return _ok(
            "data_contract_conformance",
            f"{report.passed_count}/{report.case_count} regression cases passed",
        )
    return _error(
        "data_contract_conformance",
        f"data-contract conformance failed: {report.failed_count} cases, "
        f"{report.error_count} errors",
        code="data_contract_conformance_failed",
    )


def _check_data_contract_schema_compatibility(baseline_file: Path) -> ReleaseCheckItem:
    from quant_platform.data.contracts.errors import VendorContractError
    from quant_platform.data.contracts.schema_compatibility import (
        check_schema_compatibility_against_baseline,
    )

    try:
        report = check_schema_compatibility_against_baseline(
            baseline_file=baseline_file
        )
    except (VendorContractError, OSError) as exc:
        return _error(
            "data_contract_schema_compatibility",
            f"data-contract schema compatibility could not run: {type(exc).__name__}",
            code="data_contract_schema_compatibility_error",
        )
    if report.ok:
        return _ok(
            "data_contract_schema_compatibility",
            "schema baseline compatible",
        )
    return _error(
        "data_contract_schema_compatibility",
        "data-contract schema compatibility is potentially_breaking: "
        f"{report.issue_count} issues",
        code="data_contract_schema_incompatible",
    )


def _check_contract_payload_intake(fixtures_dir: Path) -> ReleaseCheckItem:
    from quant_platform.data.contracts.errors import VendorContractError
    from quant_platform.data.contracts.intake_regression import (
        run_contract_payload_intake_regression,
    )

    try:
        report = run_contract_payload_intake_regression(fixtures_dir)
    except (VendorContractError, OSError) as exc:
        return _error(
            "contract_payload_intake",
            f"contract-payload intake matrix could not run: {type(exc).__name__}",
            code="contract_payload_intake_error",
        )
    if report.ok:
        return _ok(
            "contract_payload_intake",
            f"{report.passed_count}/{report.case_count} regression cases passed",
        )
    return _error(
        "contract_payload_intake",
        f"contract-payload intake failed: {report.failed_count} cases, "
        f"{report.error_count} errors",
        code="contract_payload_intake_failed",
    )


def _check_compose_config(repo_root: Path) -> ReleaseCheckItem:
    docker = shutil.which("docker")
    if docker is None:
        return _skipped(
            "compose_config",
            "docker executable is not available",
            code="docker_missing",
        )
    try:
        completed = subprocess.run(  # noqa: S603
            [docker, "compose", "config"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _warning(
            "compose_config",
            f"docker compose config could not run: {type(exc).__name__}",
            code="compose_unavailable",
        )
    if completed.returncode == 0:
        return _ok("compose_config", "docker compose config succeeded")
    return _error(
        "compose_config",
        "docker compose config failed",
        code="compose_invalid",
    )


def _check_database(
    settings: Settings,
    *,
    require: bool,
) -> tuple[ReleaseCheckItem, bool]:
    engine = create_db_engine(settings, connect_timeout_seconds=2)
    try:
        try:
            ping_database(engine)
            tables = list_public_tables(engine)
            db_head = _database_alembic_head(engine)
        except OperationalError:
            item = (
                _error(
                    "database",
                    "PostgreSQL is required but is not reachable",
                    code="database_unreachable",
                )
                if require
                else _skipped(
                    "database",
                    "PostgreSQL is not reachable; skipped",
                    code="database_skipped",
                )
            )
            return item, False
        except Exception as exc:
            return (
                _error(
                    "database",
                    f"database check failed: {type(exc).__name__}",
                    code="database_error",
                ),
                False,
            )
    finally:
        engine.dispose()
    present = set(tables)
    trading = sorted(present & FORBIDDEN_TABLE_NAMES)
    if trading:
        return (
            _error(
                "database",
                f"trading tables present: {', '.join(trading)}",
                code="trading_tables",
            ),
            True,
        )
    unexpected = sorted(present - EXPECTED_PUBLIC_TABLES)
    if unexpected:
        return (
            _error(
                "database",
                f"unexpected tables present: {', '.join(unexpected)}",
                code="unexpected_tables",
            ),
            True,
        )
    if db_head != EXPECTED_ALEMBIC_HEAD:
        return (
            _error(
                "database",
                "database Alembic head does not match expected "
                f"{EXPECTED_ALEMBIC_HEAD}",
                code="alembic_database_mismatch",
            ),
            True,
        )
    return (
        _ok(
            "database",
            f"PostgreSQL ping ok, trading_tables=none, head={db_head}",
        ),
        True,
    )


def _database_alembic_head(engine: Engine) -> str | None:
    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    if value is None:
        return None
    return str(value)


def check_items_have_errors(items: Sequence[ReleaseCheckItem]) -> bool:
    return any(item.status == "error" for item in items)
