"""total_return adjustment mode: dividends reinvested on the ex-date."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from quant_platform.research.normalization import (
    AdjustmentMode,
    assemble_normalized_dataset,
    build_normalization_request,
    compute_bar_adjustment,
)
from quant_platform.research.normalization.factors import (
    compute_dividend_price_factors,
    dividend_price_factor,
)
from quant_platform.research.normalization.status import (
    DIVIDEND_POLICY,
    build_normalization_status,
)
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
)

_INSTRUMENT = UUID("11111111-1111-1111-1111-111111111111")
_RUN = UUID("22222222-2222-2222-2222-222222222222")
_DIVIDEND_ID = UUID("44444444-4444-4444-4444-444444444444")


def _stamp(day: int, hour: int = 21) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def _bar(day: int, close: str) -> DailyBarDatasetRow:
    value = Decimal(close)
    return DailyBarDatasetRow(
        instrument_id=_INSTRUMENT,
        symbol="FICT",
        exchange_code=None,
        asset_class="etf",
        currency="USD",
        observation_time=_stamp(day),
        available_time=_stamp(day, 22),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("100"),
        source_name="yfinance",
        ingestion_run_id=_RUN,
        is_correction=False,
        correction_reason=None,
    )


def _dividend(
    day: int, cash: str, *, available_day: int | None = None
) -> CorporateActionDatasetRow:
    effective = datetime(2024, 1, day, 13, 30, tzinfo=UTC)
    return CorporateActionDatasetRow(
        id=_DIVIDEND_ID,
        instrument_id=_INSTRUMENT,
        symbol="FICT",
        exchange_code=None,
        asset_class="etf",
        action_type="dividend",
        effective_time=effective,
        available_time=(
            effective.replace(hour=14)
            if available_day is None
            else datetime(2024, 1, available_day, 14, 30, tzinfo=UTC)
        ),
        quantity_before=None,
        quantity_after=None,
        cash_amount=Decimal(cash),
        currency="USD",
        old_value=None,
        new_value=None,
        note="fixture",
    )


def _request(
    mode: AdjustmentMode = AdjustmentMode.TOTAL_RETURN, *, as_of_day: int = 20
):
    return build_normalization_request(
        as_of=_stamp(as_of_day),
        start_time=_stamp(1, 0),
        end_time=_stamp(10),
        source_name="yfinance",
        adjustment_mode=mode,
        symbols=("FICT",),
    )


def test_dividend_price_factor_math() -> None:
    assert dividend_price_factor(Decimal("1"), Decimal("100")) == Decimal("0.99")
    assert dividend_price_factor(Decimal("0"), Decimal("100")) is None
    assert dividend_price_factor(Decimal("1"), Decimal("0")) is None
    assert dividend_price_factor(Decimal("200"), Decimal("100")) is None


def test_total_return_uses_last_close_before_ex_date() -> None:
    bars = (_bar(2, "100"), _bar(3, "102"), _bar(4, "101"))
    actions = (_dividend(4, "2.04"),)
    factors = compute_dividend_price_factors(bars, actions)
    assert factors == {str(_DIVIDEND_ID): Decimal("0.98")}
    price, volume, applied, issues, trace = compute_bar_adjustment(
        bars[0],
        actions,
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        dividend_price_factors=factors,
    )
    assert price == Decimal("0.98")
    assert volume == Decimal("1")
    assert issues == ()
    assert applied[0].note == "cash dividend reinvested on ex-date"
    assert trace.applied_action_ids == (str(_DIVIDEND_ID),)
    # The ex-date bar itself is not adjusted.
    price_ex, _volume, _applied, _issues, _trace = compute_bar_adjustment(
        bars[2],
        actions,
        as_of=_stamp(20),
        adjustment_mode=AdjustmentMode.TOTAL_RETURN,
        dividend_price_factors=factors,
    )
    assert price_ex == Decimal("1")


def test_total_return_dataset_adjusts_prior_bars_only() -> None:
    bars = (_bar(2, "100"), _bar(3, "102"), _bar(4, "101"), _bar(5, "103"))
    request = _request()
    dataset = assemble_normalized_dataset(
        request=request,
        raw_dataset=DailyBarsDataset(request=request.dataset_request(), rows=bars),
        visible_actions=(_dividend(4, "2.04"),),
    )
    closes = [row.normalized_close for row in dataset.rows]
    assert closes[0] == Decimal("98.00")
    assert closes[1] == Decimal("99.96")
    assert closes[2] == Decimal("101")
    assert closes[3] == Decimal("103")
    assert dataset.report.applied_action_count == 1
    assert dataset.report.ok is True
    assert [item.code for item in dataset.report.issues] == []
    # Raw prices are untouched.
    assert [row.raw_close for row in dataset.rows] == [
        Decimal("100"),
        Decimal("102"),
        Decimal("101"),
        Decimal("103"),
    ]


def test_total_return_respects_pit_visibility() -> None:
    bars = (_bar(2, "100"), _bar(3, "102"), _bar(4, "101"))
    request = _request(as_of_day=3)
    dataset = assemble_normalized_dataset(
        request=request,
        raw_dataset=DailyBarsDataset(request=request.dataset_request(), rows=bars),
        visible_actions=(_dividend(4, "2.04", available_day=4),),
    )
    assert all(row.price_factor == Decimal("1") for row in dataset.rows)
    assert dataset.report.applied_action_count == 0


def test_dividend_without_prior_close_is_reported_not_applied() -> None:
    bars = (_bar(4, "101"), _bar(5, "103"))
    request = _request()
    dataset = assemble_normalized_dataset(
        request=request,
        raw_dataset=DailyBarsDataset(request=request.dataset_request(), rows=bars),
        visible_actions=(_dividend(4, "2.04"),),
    )
    assert [item.code for item in dataset.report.issues] == [
        "dividend_factor_unavailable"
    ]
    assert dataset.report.ok is True
    assert all(row.price_factor == Decimal("1") for row in dataset.rows)


def test_other_modes_still_treat_dividends_as_informational() -> None:
    bars = (_bar(2, "100"), _bar(4, "101"))
    request = _request(AdjustmentMode.SPLIT_ONLY)
    dataset = assemble_normalized_dataset(
        request=request,
        raw_dataset=DailyBarsDataset(request=request.dataset_request(), rows=bars),
        visible_actions=(_dividend(4, "2.04"),),
    )
    assert [item.code for item in dataset.report.issues] == ["dividend_not_adjusted"]
    assert all(row.price_factor == Decimal("1") for row in dataset.rows)


def test_status_lists_total_return_mode() -> None:
    report = build_normalization_status(check_db=False)
    assert "total_return" in report.adjustment_modes
    assert report.dividend_policy == DIVIDEND_POLICY
    assert "total_return" in DIVIDEND_POLICY
