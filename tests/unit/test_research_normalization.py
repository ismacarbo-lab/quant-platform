"""Corporate-action normalization without PostgreSQL. No trading."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_platform.research.normalization import (
    AdjustmentMode,
    assemble_normalized_dataset,
    build_normalization_request,
    compute_bar_adjustment,
    hash_normalized_daily_bars_dataset,
    split_quantity_factors,
    verify_normalization_artifacts,
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.integrity import NormalizationIntegrityCode
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    build_daily_bars_dataset_request,
)

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _stamp(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def _bar(**overrides: object) -> DailyBarDatasetRow:
    values: dict[str, object] = {
        "instrument_id": UUID("11111111-1111-1111-1111-111111111111"),
        "symbol": "FICT",
        "exchange_code": "XNYS",
        "asset_class": "equity",
        "currency": "USD",
        "observation_time": _stamp(2),
        "available_time": _stamp(3),
        "open": Decimal("40"),
        "high": Decimal("41"),
        "low": Decimal("39"),
        "close": Decimal("40"),
        "volume": Decimal("100"),
        "source_name": "local_csv",
        "ingestion_run_id": UUID("22222222-2222-2222-2222-222222222222"),
        "is_correction": False,
        "correction_reason": None,
    }
    values.update(overrides)
    return DailyBarDatasetRow(**values)  # type: ignore[arg-type]


def _action(**overrides: object) -> CorporateActionDatasetRow:
    values: dict[str, object] = {
        "id": UUID("33333333-3333-3333-3333-333333333333"),
        "instrument_id": UUID("11111111-1111-1111-1111-111111111111"),
        "symbol": "FICT",
        "exchange_code": "XNYS",
        "asset_class": "equity",
        "action_type": "split",
        "effective_time": _stamp(10),
        "available_time": _stamp(1, 20),
        "quantity_before": Decimal("1"),
        "quantity_after": Decimal("4"),
        "cash_amount": None,
        "currency": None,
        "old_value": None,
        "new_value": None,
        "note": "fixture",
    }
    values.update(overrides)
    return CorporateActionDatasetRow(**values)  # type: ignore[arg-type]


def _request(**overrides: object):
    values: dict[str, object] = {
        "as_of": _stamp(20),
        "start_time": _stamp(1),
        "end_time": _stamp(5),
        "source_name": "local_csv",
        "adjustment_mode": AdjustmentMode.SPLIT_ONLY,
        "symbols": ("FICT",),
    }
    values.update(overrides)
    return build_normalization_request(**values)  # type: ignore[arg-type]


def _dataset(
    *,
    bars: tuple[DailyBarDatasetRow, ...] | None = None,
    actions: tuple[CorporateActionDatasetRow, ...] | None = None,
    request=None,
):
    req = request or _request()
    raw = DailyBarsDataset(request=req.dataset_request(), rows=bars or (_bar(),))
    return assemble_normalized_dataset(
        request=req,
        raw_dataset=raw,
        visible_actions=actions if actions is not None else (_action(),),
    )


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_quantity_factors_match_stored_before_after() -> None:
    price, volume = split_quantity_factors(Decimal("1"), Decimal("4"))
    assert price == Decimal("0.25")
    assert volume == Decimal("4")
    reverse_price, reverse_volume = split_quantity_factors(Decimal("4"), Decimal("1"))
    assert reverse_price == Decimal("4")
    assert reverse_volume == Decimal("0.25")


def test_split_factor_adjusts_historical_prices_and_volume() -> None:
    price, volume, _factors, issues, _trace = compute_bar_adjustment(
        _bar(),
        (_action(),),
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    assert price == Decimal("0.25")
    assert volume == Decimal("4")
    assert issues == ()
    dataset = _dataset()
    row = dataset.rows[0]
    assert row.raw_close == Decimal("40")
    assert row.normalized_close == Decimal("10")
    assert row.normalized_volume == Decimal("400")
    assert row.applied_action_ids == ("33333333-3333-3333-3333-333333333333",)


def test_reverse_split_factor_multiplies_historical_prices() -> None:
    action = _action(
        action_type="reverse_split",
        quantity_before=Decimal("4"),
        quantity_after=Decimal("1"),
    )
    price, volume, _factors, issues, _trace = compute_bar_adjustment(
        _bar(),
        (action,),
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_AND_REVERSE_SPLIT,
    )
    assert price == Decimal("4")
    assert volume == Decimal("0.25")
    assert issues == ()


def test_dividend_is_informational_only() -> None:
    action = _action(
        action_type="dividend",
        quantity_before=None,
        quantity_after=None,
        cash_amount=Decimal("0.25"),
    )
    price, volume, factors, issues, _trace = compute_bar_adjustment(
        _bar(),
        (action,),
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    assert price == Decimal("1")
    assert volume == Decimal("1")
    assert factors == ()
    assert [item.code for item in issues] == ["dividend_not_adjusted"]


def test_future_action_is_not_applied() -> None:
    action = _action(available_time=_stamp(25))
    price, _volume, factors, issues, _trace = compute_bar_adjustment(
        _bar(),
        (action,),
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    assert price == Decimal("1")
    assert factors == ()
    assert issues == ()


def test_other_instrument_action_is_not_applied() -> None:
    action = _action(instrument_id=uuid4())
    price, _volume, factors, _issues, _trace = compute_bar_adjustment(
        _bar(),
        (action,),
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    assert price == Decimal("1")
    assert factors == ()


def test_compound_factors_use_stable_order() -> None:
    first = _action(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        effective_time=_stamp(8),
        quantity_after=Decimal("2"),
    )
    second = _action(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        effective_time=_stamp(12),
        quantity_after=Decimal("3"),
    )
    reversed_order = (second, first)
    price, volume, _factors, _issues, trace = compute_bar_adjustment(
        _bar(),
        reversed_order,
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    expected = (Decimal("1") / Decimal("2")) * (Decimal("1") / Decimal("3"))
    assert price == expected
    assert volume == Decimal("6")
    assert trace.applied_action_ids == (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )


def test_normalized_hash_is_stable_and_changes_with_factor() -> None:
    left = _dataset()
    right = _dataset()
    assert left.dataset_hash == right.dataset_hash
    assert left.dataset_hash == hash_normalized_daily_bars_dataset(left)
    assert left.dataset_hash.startswith("sha256:")
    drifted = _dataset(actions=(_action(quantity_after=Decimal("2")),))
    assert drifted.dataset_hash != left.dataset_hash
    blob = json.dumps(left.report.as_mapping(), default=str)
    assert "DATABASE_URL" not in blob
    assert "pnl" not in blob.lower()
    assert "returns" not in blob.lower()
    assert "portfolio" not in blob.lower()
    assert "order" not in blob.lower()
    assert "trade" not in blob.lower()


def test_csv_and_integrity(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    write_normalized_dataset_artifacts(dataset, tmp_path)
    csv_text = (tmp_path / "normalized_daily_bars.csv").read_text(encoding="utf-8")
    manifest_text = (tmp_path / "normalization_manifest.json").read_text(
        encoding="utf-8"
    )
    assert "DATABASE_URL" not in csv_text
    assert "postgresql+psycopg://" not in csv_text
    assert "DATABASE_URL" not in manifest_text
    report = verify_normalization_artifacts(tmp_path)
    assert report.ok is True
    assert report.dataset_hash == dataset.dataset_hash


def test_integrity_detects_path_traversal(tmp_path: Path) -> None:
    dataset = _dataset()
    write_normalized_dataset_artifacts(dataset, tmp_path)
    manifest = json.loads((tmp_path / "normalization_manifest.json").read_text())
    manifest["artifacts"] = [
        {"name": "escaped", "path": "../secret.csv", "kind": "csv"}
    ]
    (tmp_path / "normalization_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    report = verify_normalization_artifacts(tmp_path)
    assert report.ok is False
    assert any(
        item.code == NormalizationIntegrityCode.PATH_ESCAPE for item in report.issues
    )


def test_integrity_detects_forbidden_language(tmp_path: Path) -> None:
    dataset = _dataset()
    write_normalized_dataset_artifacts(dataset, tmp_path)
    report_path = tmp_path / "normalization_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["note"] = "this mentions pnl on purpose"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = verify_normalization_artifacts(tmp_path)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert NormalizationIntegrityCode.FORBIDDEN_METRIC in codes or (
        NormalizationIntegrityCode.OPERATIVE_LANGUAGE in codes
    )


def test_request_requires_research_source_and_mode() -> None:
    with pytest.raises(Exception, match="source_name"):
        build_normalization_request(
            as_of=_stamp(20),
            start_time=_stamp(1),
            end_time=_stamp(5),
            source_name="  ",
            symbols=["FICT"],
        )
    with pytest.raises(Exception, match="adjustment_mode"):
        build_normalization_request(
            as_of=_stamp(20),
            start_time=_stamp(1),
            end_time=_stamp(5),
            source_name="local_csv",
            symbols=["FICT"],
            adjustment_mode="paper",
        )


def test_scripts_parse_help() -> None:
    builder = _load_script("build-normalized-dataset.py")
    with pytest.raises(SystemExit) as help_exc:
        builder.main(["--help"])
    assert help_exc.value.code == 0
    verifier = _load_script("verify-normalized-dataset.py")
    with pytest.raises(SystemExit) as verify_help:
        verifier.main(["--help"])
    assert verify_help.value.code == 0


def test_dataset_request_builder_still_works() -> None:
    request = build_daily_bars_dataset_request(
        as_of=_stamp(20),
        start_time=_stamp(1),
        end_time=_stamp(5),
        symbols=["FICT"],
    )
    assert request.symbols == ("FICT",)
