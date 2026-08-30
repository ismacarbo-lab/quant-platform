"""Corporate-action factor math. Research-only; not returns or PnL."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from quant_platform.research.normalization.types import (
    AdjustmentMode,
    CorporateActionFactor,
    NormalizationAdjustmentTrace,
    NormalizationIssue,
)
from quant_platform.research.types import CorporateActionDatasetRow, DailyBarDatasetRow

_ONE = Decimal("1")
_TRACE_NAMESPACE = UUID("6c0a0001-ca06-4f00-9f00-000000000600")

ACTION_SPLIT = "split"
ACTION_REVERSE_SPLIT = "reverse_split"
ACTION_DIVIDEND = "dividend"

ADJUSTABLE_BY_MODE: dict[AdjustmentMode, frozenset[str]] = {
    AdjustmentMode.NONE: frozenset(),
    AdjustmentMode.SPLIT_ONLY: frozenset({ACTION_SPLIT}),
    AdjustmentMode.SPLIT_AND_REVERSE_SPLIT: frozenset(
        {ACTION_SPLIT, ACTION_REVERSE_SPLIT}
    ),
    AdjustmentMode.INFORMATIONAL: frozenset(),
}


def action_sort_key(action: CorporateActionDatasetRow) -> tuple[object, ...]:
    """Stable apply order: effective time, available time, type, id."""
    return (
        action.effective_time,
        action.available_time,
        action.action_type,
        str(action.id) if action.id is not None else "",
        str(action.instrument_id),
    )


def split_quantity_factors(
    quantity_before: Decimal, quantity_after: Decimal
) -> tuple[Decimal, Decimal]:
    """Map stored before/after share counts to price and volume factors.

    Convention matches silver storage (1→4 split is ``1:4``):
    historical prices multiply by ``before/after``; volume by ``after/before``.
    The same formula covers ``reverse_split`` when stored as 4→1.
    """
    if quantity_before <= 0 or quantity_after <= 0:
        raise ValueError("split quantities must be positive")
    return quantity_before / quantity_after, quantity_after / quantity_before


def is_visible_at(action: CorporateActionDatasetRow, *, as_of: datetime) -> bool:
    return action.available_time <= as_of


def applies_to_bar(action: CorporateActionDatasetRow, bar: DailyBarDatasetRow) -> bool:
    return (
        action.instrument_id == bar.instrument_id
        and action.effective_time > bar.observation_time
    )


def trace_id_for(
    bar: DailyBarDatasetRow, *, as_of: datetime, adjustment_mode: AdjustmentMode
) -> str:
    token = (
        f"{bar.instrument_id}|{bar.observation_time.isoformat()}|{bar.source_name}|"
        f"{as_of.isoformat()}|{adjustment_mode.value}"
    )
    return str(uuid5(_TRACE_NAMESPACE, token))


def compute_bar_adjustment(
    bar: DailyBarDatasetRow,
    actions: Sequence[CorporateActionDatasetRow],
    *,
    as_of: datetime,
    adjustment_mode: AdjustmentMode,
) -> tuple[
    Decimal,
    Decimal,
    tuple[CorporateActionFactor, ...],
    tuple[NormalizationIssue, ...],
    NormalizationAdjustmentTrace,
]:
    """Compose PIT-visible factors for one bar. Does not compute performance."""
    price = _ONE
    volume = _ONE
    factors: list[CorporateActionFactor] = []
    issues: list[NormalizationIssue] = []
    applied_ids: list[str] = []
    adjustable = ADJUSTABLE_BY_MODE[adjustment_mode]
    ordered = sorted(actions, key=action_sort_key)
    seen_issue_keys: set[tuple[str, str | None]] = set()

    for action in ordered:
        if not is_visible_at(action, as_of=as_of):
            continue
        if action.instrument_id != bar.instrument_id:
            continue
        retroactive = applies_to_bar(action, bar)
        factor, extra = _factor_for_action(
            action,
            adjustment_mode=adjustment_mode,
            adjustable=adjustable,
            retroactive=retroactive,
        )
        for issue in extra:
            key = (
                issue.code,
                None if issue.action_id is None else str(issue.action_id),
            )
            if key in seen_issue_keys:
                continue
            seen_issue_keys.add(key)
            issues.append(issue)
        if factor is None:
            continue
        factors.append(factor)
        if factor.applied and retroactive:
            price *= factor.price_factor
            volume *= factor.volume_factor
            if factor.action_id is not None:
                applied_ids.append(str(factor.action_id))

    trace = NormalizationAdjustmentTrace(
        trace_id=trace_id_for(bar, as_of=as_of, adjustment_mode=adjustment_mode),
        instrument_id=bar.instrument_id,
        symbol=bar.symbol,
        source_name=bar.source_name,
        observation_time=bar.observation_time,
        available_time=bar.available_time,
        as_of=as_of,
        adjustment_mode=adjustment_mode.value,
        price_factor=price,
        volume_factor=volume,
        applied_action_ids=tuple(applied_ids),
        factors=tuple(factors),
        issue_codes=tuple(issue.code for issue in issues),
    )
    return price, volume, tuple(factors), tuple(issues), trace


def _factor_for_action(
    action: CorporateActionDatasetRow,
    *,
    adjustment_mode: AdjustmentMode,
    adjustable: frozenset[str],
    retroactive: bool,
) -> tuple[CorporateActionFactor | None, tuple[NormalizationIssue, ...]]:
    if action.action_type == ACTION_DIVIDEND:
        return None, (
            NormalizationIssue(
                code="dividend_not_adjusted",
                message="dividend is informational only; prices were not adjusted",
                instrument_id=action.instrument_id,
                action_id=action.id,
            ),
        )
    if action.action_type not in {ACTION_SPLIT, ACTION_REVERSE_SPLIT}:
        return None, (
            NormalizationIssue(
                code="action_not_adjusted",
                message=(
                    f"{action.action_type} is informational only; "
                    "prices were not adjusted"
                ),
                instrument_id=action.instrument_id,
                action_id=action.id,
            ),
        )
    if action.action_type not in adjustable:
        return None, (
            NormalizationIssue(
                code="action_not_adjusted",
                message=(
                    f"{action.action_type} is outside adjustment_mode "
                    f"{adjustment_mode.value}"
                ),
                severity="info",
                instrument_id=action.instrument_id,
                action_id=action.id,
            ),
        )
    if action.quantity_before is None or action.quantity_after is None:
        return None, (
            NormalizationIssue(
                code="invalid_split_ratio",
                message="split quantities are missing; factor was skipped",
                instrument_id=action.instrument_id,
                action_id=action.id,
            ),
        )
    try:
        price_factor, volume_factor = split_quantity_factors(
            action.quantity_before, action.quantity_after
        )
    except ValueError:
        return None, (
            NormalizationIssue(
                code="invalid_split_ratio",
                message="split quantities must be positive; factor was skipped",
                instrument_id=action.instrument_id,
                action_id=action.id,
            ),
        )
    applied = retroactive and adjustment_mode not in {
        AdjustmentMode.NONE,
        AdjustmentMode.INFORMATIONAL,
    }
    return (
        CorporateActionFactor(
            action_id=action.id,
            action_type=action.action_type,
            instrument_id=action.instrument_id,
            effective_time=action.effective_time,
            available_time=action.available_time,
            price_factor=price_factor,
            volume_factor=volume_factor,
            applied=applied,
        ),
        (),
    )
