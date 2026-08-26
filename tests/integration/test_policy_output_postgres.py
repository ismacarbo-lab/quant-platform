"""PostgreSQL policy-output integrity and observation usability."""

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
from quant_platform.backtest.integrity import verify_registered_backtest_run
from quant_platform.backtest.integrity_types import BacktestIntegrityCode
from quant_platform.backtest.observation_reports import build_observation_report
from quant_platform.backtest.policy_output_integrity import compare_policy_outputs
from quant_platform.backtest.policy_output_types import PolicyOutputComparisonVerdict
from quant_platform.backtest.readiness import (
    BacktestUsabilityCode,
    evaluate_backtest_result_usability,
)
from quant_platform.backtest.types import BacktestRequest
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


def _seed_ready_replay(db_session: Session, tmp_path: Path, *, prefix: str = "PO"):
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


def _run(
    db_session: Session,
    replay_dir: Path,
    replay_id: str,
    output_dir: Path,
    *,
    policy_name: str = "noop",
):
    result = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(
            replay_id=replay_id,
            deterministic_id=False,
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


def _codes(report) -> set[str]:
    return {item.code for item in report.issues}


def test_valid_policy_output_is_usable(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="OK")
    result = _run(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        policy_name="event_counting",
    )
    assert (tmp_path / "bt" / "policy_output.json").is_file()
    integrity = verify_registered_backtest_run(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert integrity.ok is True
    assert integrity.policy_output_ok is True
    report = build_observation_report(tmp_path / "bt")
    assert report.observation_count >= 1
    usability = evaluate_backtest_result_usability(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert usability.usable_result is True
    assert usability.gate.policy_output_ok is True
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)


def test_usability_fails_when_policy_output_is_corrupt(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="CR")
    result = _run(
        db_session, replay_dir, str(replay.manifest.replay_id), tmp_path / "bt"
    )
    (tmp_path / "bt" / "policy_output.json").write_text("{", encoding="utf-8")
    usability = evaluate_backtest_result_usability(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert usability.usable_result is False
    assert usability.gate.policy_output_ok is False
    assert BacktestUsabilityCode.POLICY_OUTPUT_INVALID.value in _codes(usability)


def test_usability_fails_when_policy_output_has_forbidden_language(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="LG")
    result = _run(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        policy_name="event_counting",
    )
    path = tmp_path / "bt" / "policy_output.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    observations = payload["observations"]
    assert isinstance(observations, list) and observations
    observations[0]["message"] = "buy this instrument"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    integrity = verify_registered_backtest_run(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert integrity.ok is False
    assert BacktestIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value in _codes(
        integrity
    )
    usability = evaluate_backtest_result_usability(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert usability.usable_result is False
    assert BacktestUsabilityCode.POLICY_OUTPUT_INVALID.value in _codes(usability)


def test_compare_policy_outputs_detects_policy_change(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="CP")
    replay_id = str(replay.manifest.replay_id)
    noop = _run(db_session, replay_dir, replay_id, tmp_path / "noop")
    counting = _run(
        db_session,
        replay_dir,
        replay_id,
        tmp_path / "count",
        policy_name="event_counting",
    )
    diff = compare_policy_outputs(tmp_path / "noop", tmp_path / "count")
    assert diff.verdict == PolicyOutputComparisonVerdict.DIFFERENT.value
    assert diff.same_policy_output_hash is False
    assert noop.summary.policy_output_hash != counting.summary.policy_output_hash


def test_no_trading_tables_and_research_mode(
    postgres_engine: Engine,
) -> None:
    settings = get_settings()
    assert settings.app_mode.value == "research"
    inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "DATABASE_URL" not in str(tables)
