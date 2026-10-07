"""Normalization add-on status. No trading and no PnL."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.constants import (
    ENABLED_CAPABILITIES,
    EXPECTED_ALEMBIC_HEAD,
    EXPECTED_PUBLIC_TABLES,
)
from quant_platform.research.normalization.regression import (
    default_normalization_regression_dir,
)
from quant_platform.research.normalization.types import AdjustmentMode
from quant_platform.storage.database import (
    create_db_engine,
    list_public_tables,
    ping_database,
)

NORMALIZATION_STATUS_KIND = "normalization_addon_status"
EXPECTED_CATALOG_TABLE = "normalized_datasets"
DIVIDEND_POLICY = "informational only (reinvested only in total_return mode)"
NORMALIZATION_CAPABILITY = "normalized_dataset_catalog"


@dataclass(frozen=True, slots=True)
class NormalizationStatusReport:
    kind: str
    app_mode: str
    capability_enabled: bool
    expected_alembic_head: str
    expected_table: str
    regression_case_count: int
    adjustment_modes: tuple[str, ...]
    dividend_policy: str
    database_checked: bool
    database_table_present: bool | None
    database_alembic_head: str | None
    ok: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "app_mode": self.app_mode,
            "capability_enabled": self.capability_enabled,
            "expected_alembic_head": self.expected_alembic_head,
            "expected_table": self.expected_table,
            "regression_case_count": self.regression_case_count,
            "adjustment_modes": list(self.adjustment_modes),
            "dividend_policy": self.dividend_policy,
            "database_checked": self.database_checked,
            "database_table_present": self.database_table_present,
            "database_alembic_head": self.database_alembic_head,
            "ok": self.ok,
        }


def _regression_case_count() -> int:
    root = default_normalization_regression_dir()
    if not root.is_dir():
        return 0
    return sum(1 for item in root.iterdir() if item.is_dir())


def _database_alembic_head(engine: Engine) -> str | None:
    from sqlalchemy import text

    with engine.connect() as connection:
        value = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    if value is None:
        return None
    return str(value)


def build_normalization_status(*, check_db: bool = False) -> NormalizationStatusReport:
    """Summarize the normalization add-on. Does not ping PostgreSQL by default."""
    settings = get_settings()
    capability_enabled = NORMALIZATION_CAPABILITY in ENABLED_CAPABILITIES
    table_expected = EXPECTED_CATALOG_TABLE in EXPECTED_PUBLIC_TABLES
    modes = tuple(item.value for item in AdjustmentMode)
    table_present: bool | None = None
    db_head: str | None = None
    database_checked = False
    if check_db:
        engine = create_db_engine(settings, connect_timeout_seconds=5)
        try:
            ping_database(engine)
            tables = set(list_public_tables(engine))
            table_present = EXPECTED_CATALOG_TABLE in tables
            db_head = _database_alembic_head(engine)
            database_checked = True
        except Exception as exc:
            raise RuntimeError(redact_secret_text(str(exc))) from exc
        finally:
            engine.dispose()
    db_ok = True
    if database_checked:
        db_ok = table_present is True and db_head == EXPECTED_ALEMBIC_HEAD
    ok = (
        settings.is_research_mode
        and capability_enabled
        and table_expected
        and EXPECTED_ALEMBIC_HEAD >= "0010_normalized_dataset_catalog"
        and db_ok
    )
    return NormalizationStatusReport(
        kind=NORMALIZATION_STATUS_KIND,
        app_mode=str(settings.app_mode),
        capability_enabled=capability_enabled,
        expected_alembic_head=EXPECTED_ALEMBIC_HEAD,
        expected_table=EXPECTED_CATALOG_TABLE,
        regression_case_count=_regression_case_count(),
        adjustment_modes=modes,
        dividend_policy=DIVIDEND_POLICY,
        database_checked=database_checked,
        database_table_present=table_present,
        database_alembic_head=db_head,
        ok=ok,
    )
