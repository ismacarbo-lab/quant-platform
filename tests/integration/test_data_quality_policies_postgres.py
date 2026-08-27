"""PostgreSQL data-quality research policies. No trading tables."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import register_backtest_run
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.experiment_catalog import get_backtest_experiment_by_id
from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
)
from quant_platform.backtest.experiment_reports import (
    build_research_report_from_catalog,
    load_member_observation_reports,
)
from quant_platform.backtest.experiment_types import BacktestExperimentRequest
from quant_platform.backtest.experiments import (
    members_from_experiment_summary,
    run_backtest_experiment,
)
from quant_platform.backtest.policy_output_integrity import verify_policy_output
from quant_platform.backtest.readiness import evaluate_backtest_result_usability
from quant_platform.backtest.types import BacktestRequest
from quant_platform.core.config import get_settings
from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_corporate_action,
    create_ingestion_run,
    get_daily_bars,
    insert_daily_bar_correction,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.types import build_daily_bars_dataset_request
from quant_platform.simulation.artifacts import write_replay_run_artifacts
from quant_platform.simulation.audit import audit_replay
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.run_catalog import register_replay_run
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_TRADING_TABLES = frozenset(
    {
        "trades",
        "orders",
        "fills",
        "signals",
        "strategies",
        "positions",
        "portfolio",
    }
)
_QUALITY_POLICIES = (
    "data_quality",
    "coverage",
    "corporate_action_audit",
    "correction_audit",
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _insert_bar(
    session: Session, *, instrument: Instrument, source_id: UUID, run_id: UUID
) -> None:
    price = Decimal("10")
    insert_daily_bars(
        session,
        drafts=[
            DailyBarDraft(
                symbol=instrument.symbol,
                observation_time=datetime(2024, 1, 2, tzinfo=UTC),
                available_time=datetime(2024, 1, 3, tzinfo=UTC),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100"),
            )
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source_id,
        ingestion_run_id=run_id,
    )


def _seed_quality_replay(db_session: Session, tmp_path: Path, *, prefix: str = "DQ"):
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique(prefix), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(db_session, instrument=instrument, source_id=source.id, run_id=run.id)
    original = get_daily_bars(
        db_session, instrument_id=instrument.id, source_id=source.id
    )
    assert original
    insert_daily_bar_correction(
        db_session,
        superseded=original[0],
        available_time=datetime(2024, 1, 6, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("100"),
        ingestion_run_id=run.id,
        reason="late_print",
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 4, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
        note="fictional split",
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 8, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    replay = create_daily_bar_replay(
        db_session,
        request,
        deterministic_id=True,
        include_corporate_actions=True,
    )
    report = audit_replay(replay.events, as_of=replay.summary.as_of)
    output = tmp_path / prefix.lower()
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest, base_path=output)
    return result, output


def _run_policy(
    db_session: Session,
    replay_dir: Path,
    replay_id: str,
    output_dir: Path,
    *,
    policy_name: str,
):
    result = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(
            replay_id=replay_id,
            deterministic_id=True,
            policy_name=policy_name,
        ),
        replay_dir,
        output_dir=output_dir,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    register_backtest_run(db_session, result.manifest)
    return result


def test_quality_policies_run_and_are_usable(
    db_session: Session, tmp_path: Path
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay, replay_dir = _seed_quality_replay(db_session, tmp_path)
    replay_id = str(replay.manifest.replay_id)
    for name in _QUALITY_POLICIES:
        result = _run_policy(
            db_session, replay_dir, replay_id, tmp_path / name, policy_name=name
        )
        assert result.summary.policy_name == name
        payload = json.loads((tmp_path / name / "policy_output.json").read_text())
        assert payload["policy_name"] == name
        assert verify_policy_output(tmp_path / name).ok is True
        usability = evaluate_backtest_result_usability(
            db_session, str(result.summary.backtest_id), tmp_path / name
        )
        assert usability.usable_result is True
        assert result.orders == ()
        assert result.fills == ()
        assert result.signals == ()


def test_quality_experiment_usability_and_aggregation(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_quality_replay(db_session, tmp_path, prefix="EX")
    output = tmp_path / "exp-quality"
    result = run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name="quality-grid",
            replay_ids=(str(replay.manifest.replay_id),),
            policy_name="data_quality",
            deterministic_ids=True,
        ),
        replay_dir,
        output,
        register=True,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    report = evaluate_backtest_experiment_usability(
        db_session, result.summary.experiment_id, output
    )
    assert report.experiment_usable is True
    entry = get_backtest_experiment_by_id(db_session, result.summary.experiment_id)
    assert entry is not None
    members = members_from_experiment_summary(entry.summary)
    observations = load_member_observation_reports(output, members)
    research = build_research_report_from_catalog(
        entry, observation_reports=observations, members=members
    )
    kinds = {item.kind for item in research.observations.kinds}
    assert "data_quality_summary" in kinds


def test_no_trading_tables_and_research_mode(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "DATABASE_URL" not in str(tables)
