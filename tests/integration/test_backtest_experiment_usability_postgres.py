"""PostgreSQL experiment usability gate and research reports."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.backtest.experiment_catalog import get_backtest_experiment_by_id
from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
)
from quant_platform.backtest.experiment_readiness_types import ExperimentUsabilityCode
from quant_platform.backtest.experiment_report_artifacts import (
    write_backtest_experiment_report_artifacts,
)
from quant_platform.backtest.experiment_reports import (
    build_research_report_from_catalog,
    hash_backtest_experiment_report,
    load_member_observation_reports,
)
from quant_platform.backtest.experiment_types import BacktestExperimentRequest
from quant_platform.backtest.experiments import (
    members_from_experiment_summary,
    run_backtest_experiment,
)
from quant_platform.core.config import get_settings
from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_ingestion_run,
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


def _seed_ready_replay(db_session: Session, tmp_path: Path, *, prefix: str = "PL"):
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique(prefix), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(db_session, instrument=instrument, source_id=source.id, run_id=run.id)
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    replay = create_daily_bar_replay(db_session, request, deterministic_id=True)
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


def _run_experiment(
    db_session: Session,
    tmp_path: Path,
    replay_ids: tuple[str, ...],
    output: Path,
    *,
    policy_name: str = "noop",
    name: str = "usable-grid",
):
    return run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name=name,
            replay_ids=replay_ids,
            policy_name=policy_name,
            deterministic_ids=True,
        ),
        tmp_path,
        output,
        register=True,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )


def test_experiment_usable_with_one_and_two_members(
    db_session: Session, tmp_path: Path
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    first, _first_dir = _seed_ready_replay(db_session, tmp_path, prefix="U1")
    second, _second_dir = _seed_ready_replay(db_session, tmp_path, prefix="U2")
    one = _run_experiment(
        db_session,
        tmp_path,
        (str(first.manifest.replay_id),),
        tmp_path / "exp-one",
        name="one-member",
    )
    two = _run_experiment(
        db_session,
        tmp_path,
        (str(first.manifest.replay_id), str(second.manifest.replay_id)),
        tmp_path / "exp-two",
        name="two-member",
    )
    one_report = evaluate_backtest_experiment_usability(
        db_session, one.summary.experiment_id, tmp_path / "exp-one"
    )
    two_report = evaluate_backtest_experiment_usability(
        db_session, two.summary.experiment_id, tmp_path / "exp-two"
    )
    assert one_report.experiment_usable is True
    assert one_report.member_count == 1
    assert one_report.usable_count == 1
    assert two_report.experiment_usable is True
    assert two_report.member_count == 2
    assert two_report.usable_count == 2


def test_missing_artifact_makes_experiment_unusable(
    db_session: Session, tmp_path: Path
) -> None:
    replay, _replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="MA")
    result = _run_experiment(
        db_session,
        tmp_path,
        (str(replay.manifest.replay_id),),
        tmp_path / "exp-missing",
        name="missing-summary",
    )
    (tmp_path / "exp-missing" / "experiment_summary.json").unlink()
    report = evaluate_backtest_experiment_usability(
        db_session, result.summary.experiment_id, tmp_path / "exp-missing"
    )
    assert report.experiment_usable is False
    assert ExperimentUsabilityCode.EXPERIMENT_ARTIFACT_MISSING.value in {
        item.code for item in report.issues
    }


def test_unusable_member_makes_experiment_unusable(
    db_session: Session, tmp_path: Path
) -> None:
    replay, _replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="MU")
    result = _run_experiment(
        db_session,
        tmp_path,
        (str(replay.manifest.replay_id),),
        tmp_path / "exp-member",
        name="broken-member",
    )
    member_output = tmp_path / "exp-member" / "runs" / "0001" / "policy_output.json"
    member_output.unlink()
    report = evaluate_backtest_experiment_usability(
        db_session, result.summary.experiment_id, tmp_path / "exp-member"
    )
    assert report.experiment_usable is False
    codes = {item.code for item in report.issues}
    assert ExperimentUsabilityCode.MEMBER_NOT_USABLE.value in codes or (
        ExperimentUsabilityCode.MEMBER_ARTIFACT_INVALID.value in codes
    )


def test_research_report_hash_and_observation_aggregate(
    db_session: Session, tmp_path: Path
) -> None:
    replay, _replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="RR")
    result = _run_experiment(
        db_session,
        tmp_path,
        (str(replay.manifest.replay_id),),
        tmp_path / "exp-report",
        policy_name="event_counting",
        name="count-grid",
    )
    assert result.manifest is not None
    entry = get_backtest_experiment_by_id(db_session, result.summary.experiment_id)
    assert entry is not None
    members = members_from_experiment_summary(entry.summary)
    observations = load_member_observation_reports(tmp_path / "exp-report", members)
    report = build_research_report_from_catalog(
        entry, observation_reports=observations, members=members
    )
    again = build_research_report_from_catalog(
        entry, observation_reports=observations, members=members
    )
    assert report.report_hash == again.report_hash
    assert hash_backtest_experiment_report(report) == report.report_hash
    assert report.observations.observation_count > 0
    write_backtest_experiment_report_artifacts(report, tmp_path / "exp-report")
    assert (tmp_path / "exp-report" / "experiment_research_report.json").is_file()
    usability = evaluate_backtest_experiment_usability(
        db_session, result.summary.experiment_id, tmp_path / "exp-report"
    )
    assert usability.experiment_usable is True


def test_no_trading_tables_and_research_mode(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert "backtest_experiments" in tables
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "DATABASE_URL" not in str(tables)
