"""PostgreSQL backtest artifact integrity, comparison, and usability."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import register_backtest_run
from quant_platform.backtest.compare import (
    BacktestRunDiffVerdict,
    diff_catalog_backtest_runs,
)
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.integrity import (
    verify_backtest_catalog,
    verify_registered_backtest_run,
)
from quant_platform.backtest.integrity_types import BacktestIntegrityCode
from quant_platform.backtest.readiness import (
    BacktestUsabilityCode,
    evaluate_backtest_result_usability,
)
from quant_platform.backtest.types import BacktestRequest
from quant_platform.core.config import get_settings
from quant_platform.data.models import BacktestRunRecord, Instrument
from quant_platform.data.repository import (
    create_ingestion_run,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.snapshots import hash_manifest_mapping
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
_OTHER = "sha256:" + ("b" * 64)


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


def _seed_ready_replay(db_session: Session, tmp_path: Path, *, prefix: str = "BT"):
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


def _run_and_register(
    db_session: Session,
    replay_dir: Path,
    replay_id: str,
    output_dir: Path,
    *,
    created_at: datetime,
    deterministic_id: bool = True,
):
    result = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(replay_id=replay_id, deterministic_id=deterministic_id),
        replay_dir,
        output_dir=output_dir,
        created_at=created_at,
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    register_backtest_run(db_session, result.manifest)
    return result


def _codes(report) -> set[str]:
    return {item.code for item in report.issues}


def _load_json(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return dict(loaded)


def _dump_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def test_verify_registered_backtest_run(db_session: Session, tmp_path: Path) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="VR")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    report = verify_registered_backtest_run(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert report.ok is True
    assert report.error_count == 0
    assert report.policy_name == "noop"
    catalog = verify_backtest_catalog(
        db_session,
        tmp_path,
        replay_id=str(replay.manifest.replay_id),
    )
    assert catalog.ok is True
    assert catalog.verified_count == 1


def test_verify_detects_missing_summary(db_session: Session, tmp_path: Path) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="MS")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    (tmp_path / "bt" / "summary.json").unlink()
    report = verify_registered_backtest_run(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert report.ok is False
    assert BacktestIntegrityCode.MISSING_SUMMARY.value in _codes(report)


def test_verify_detects_hash_mismatch(db_session: Session, tmp_path: Path) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="HM")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    summary_path = tmp_path / "bt" / "summary.json"
    manifest_path = tmp_path / "bt" / "manifest.json"
    summary = _load_json(summary_path)
    manifest = _load_json(manifest_path)
    summary["backtest_hash"] = _OTHER
    nested = manifest.get("summary")
    assert isinstance(nested, dict)
    nested["backtest_hash"] = _OTHER
    manifest["summary"] = nested
    manifest["backtest_hash"] = _OTHER
    manifest["manifest_hash"] = hash_manifest_mapping(manifest)
    _dump_json(summary_path, summary)
    _dump_json(manifest_path, manifest)
    report = verify_registered_backtest_run(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert report.ok is False
    assert BacktestIntegrityCode.BACKTEST_HASH_MISMATCH.value in _codes(report)
    assert BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH.value in _codes(report)


def test_compare_identical_same_result_and_different(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="SM")
    first = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "same_a",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        deterministic_id=False,
    )
    second = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "same_b",
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        deterministic_id=False,
    )
    other_replay, other_dir = _seed_ready_replay(db_session, tmp_path, prefix="DF")
    other = _run_and_register(
        db_session,
        other_dir,
        str(other_replay.manifest.replay_id),
        tmp_path / "diff",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    left_id = str(first.summary.backtest_id)
    right_id = str(second.summary.backtest_id)
    other_id = str(other.summary.backtest_id)
    identical = diff_catalog_backtest_runs(db_session, left_id, left_id)
    assert identical.verdict == BacktestRunDiffVerdict.IDENTICAL.value
    same = diff_catalog_backtest_runs(db_session, left_id, right_id)
    assert same.verdict == BacktestRunDiffVerdict.SAME_RESULT.value
    assert same.same_backtest_hash is True
    assert same.same_manifest_hash is False
    different = diff_catalog_backtest_runs(db_session, left_id, other_id)
    assert different.verdict == BacktestRunDiffVerdict.DIFFERENT.value
    assert different.same_backtest_hash is False


def test_usability_ok(db_session: Session, tmp_path: Path) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="OK")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    report = evaluate_backtest_result_usability(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert report.usable_result is True
    assert report.gate.artifacts_ok is True
    assert report.gate.replay_registered is True
    assert report.policy_name == "noop"


def test_usability_fails_when_artifacts_break(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="BR")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    (tmp_path / "bt" / "summary.json").unlink()
    report = evaluate_backtest_result_usability(
        db_session, str(result.summary.backtest_id), tmp_path / "bt"
    )
    assert report.usable_result is False
    assert report.gate.artifacts_ok is False
    assert BacktestUsabilityCode.ARTIFACT_MISSING.value in _codes(report)


def test_usability_warns_if_replay_not_in_catalog(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="WR")
    result = _run_and_register(
        db_session,
        replay_dir,
        str(replay.manifest.replay_id),
        tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
    )
    backtest_id = str(result.summary.backtest_id)
    record = db_session.scalars(
        select(BacktestRunRecord).where(BacktestRunRecord.backtest_id == backtest_id)
    ).one()
    record.replay_id = str(uuid4())
    db_session.commit()
    report = evaluate_backtest_result_usability(
        db_session, backtest_id, tmp_path / "bt"
    )
    assert report.usable_result is True
    assert report.gate.replay_registered is False
    assert BacktestUsabilityCode.REPLAY_CATALOG_MISSING.value in _codes(report)


def test_no_trading_tables(postgres_engine: Engine) -> None:
    inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert "backtest_runs" in tables
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "DATABASE_URL" not in str(tables)
