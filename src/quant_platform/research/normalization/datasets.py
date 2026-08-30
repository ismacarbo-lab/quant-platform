"""Build a derived normalized daily-bar dataset. Silver rows stay untouched."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from quant_platform.research.datasets import get_daily_bars_dataset
from quant_platform.research.normalization.corporate_actions import (
    load_visible_corporate_actions,
)
from quant_platform.research.normalization.factors import compute_bar_adjustment
from quant_platform.research.normalization.types import (
    AdjustmentMode,
    CorporateActionFactor,
    NormalizationAdjustmentTrace,
    NormalizationIssue,
    NormalizationReport,
    NormalizationRequest,
    NormalizedDailyBar,
    NormalizedDailyBarsDataset,
    build_normalization_request,
)
from quant_platform.research.snapshots import hash_daily_bars_dataset
from quant_platform.research.types import DailyBarDatasetRow, DailyBarsDataset


def build_normalized_daily_bars_dataset(
    session: Session,
    request: NormalizationRequest,
) -> NormalizedDailyBarsDataset:
    """Return a derived view. Does not write PostgreSQL or mutate ``daily_bars``."""
    rebuilt = build_normalization_request(
        as_of=request.as_of,
        start_time=request.start_time,
        end_time=request.end_time,
        source_name=request.source_name,
        adjustment_mode=request.adjustment_mode,
        symbols=request.symbols,
        instrument_ids=request.instrument_ids,
        exchange_codes=request.exchange_codes,
        asset_classes=request.asset_classes,
        currency=request.currency,
        calendar_code=request.calendar_code,
        require_open_session=request.require_open_session,
        allow_unfiltered=request.allow_unfiltered,
    )
    raw = get_daily_bars_dataset(session, rebuilt.dataset_request())
    filtered_rows = tuple(
        row for row in raw.rows if row.source_name == rebuilt.source_name
    )
    filtered = DailyBarsDataset(request=raw.request, rows=filtered_rows)
    visible = load_visible_corporate_actions(session, rebuilt.dataset_request())
    return assemble_normalized_dataset(
        request=rebuilt,
        raw_dataset=filtered,
        visible_actions=visible,
    )


def assemble_normalized_dataset(
    *,
    request: NormalizationRequest,
    raw_dataset: DailyBarsDataset,
    visible_actions: tuple[object, ...] | None = None,
) -> NormalizedDailyBarsDataset:
    """Pure assembly used by tests. Does not open PostgreSQL."""
    from quant_platform.research.types import CorporateActionDatasetRow

    actions = tuple(
        item
        for item in (visible_actions or ())
        if isinstance(item, CorporateActionDatasetRow)
    )
    rows: list[NormalizedDailyBar] = []
    traces = []
    issues: list[NormalizationIssue] = []
    applied: dict[str, CorporateActionFactor] = {}
    seen_issue: set[tuple[str, str | None, str | None]] = set()

    for bar in raw_dataset.rows:
        price, volume, factors, bar_issues, trace = compute_bar_adjustment(
            bar,
            actions,
            as_of=request.as_of,
            adjustment_mode=request.adjustment_mode,
        )
        traces.append(trace)
        for issue in bar_issues:
            key = (
                issue.code,
                None if issue.action_id is None else str(issue.action_id),
                None if issue.instrument_id is None else str(issue.instrument_id),
            )
            if key in seen_issue:
                continue
            seen_issue.add(key)
            issues.append(issue)
        for factor in factors:
            if factor.applied and factor.action_id is not None:
                applied[str(factor.action_id)] = factor
        rows.append(
            _normalize_bar(
                bar, request=request, price=price, volume=volume, trace=trace
            )
        )

    raw_hash = hash_daily_bars_dataset(raw_dataset)
    applied_tuple = tuple(
        applied[key] for key in sorted(applied, key=lambda item: (item,))
    )
    issue_tuple = tuple(issues)
    draft_hash = hash_normalized_daily_bars_dataset(
        request=request,
        rows=tuple(rows),
        raw_dataset_hash=raw_hash,
        applied_actions=applied_tuple,
        issues=issue_tuple,
    )
    warning_count = sum(1 for item in issue_tuple if item.severity == "warning")
    error_count = sum(1 for item in issue_tuple if item.severity == "error")
    report = NormalizationReport(
        ok=error_count == 0,
        as_of=request.as_of,
        adjustment_mode=request.adjustment_mode.value,
        source_name=request.source_name,
        bar_count=len(rows),
        raw_bar_count=len(raw_dataset.rows),
        visible_action_count=len(actions),
        applied_action_count=len(applied_tuple),
        issue_count=len(issue_tuple),
        warning_count=warning_count,
        error_count=error_count,
        dataset_hash=draft_hash,
        raw_dataset_hash=raw_hash,
        issues=issue_tuple,
        applied_actions=applied_tuple,
    )
    return NormalizedDailyBarsDataset(
        request=request,
        raw_dataset=raw_dataset,
        rows=tuple(rows),
        traces=tuple(traces),
        visible_actions=actions,
        report=report,
        dataset_hash=draft_hash,
        raw_dataset_hash=raw_hash,
    )


def hash_normalized_daily_bars_dataset(
    dataset: NormalizedDailyBarsDataset | None = None,
    *,
    request: NormalizationRequest | None = None,
    rows: tuple[NormalizedDailyBar, ...] | None = None,
    raw_dataset_hash: str | None = None,
    applied_actions: tuple[CorporateActionFactor, ...] | None = None,
    issues: tuple[NormalizationIssue, ...] | None = None,
) -> str:
    """SHA-256 of the derived dataset. No wall-clock, paths, or secrets."""
    from quant_platform.research.snapshots import (
        canonical_datetime,
        canonical_decimal,
        manifest_contains_secrets,
        sha256_canonical,
    )

    if dataset is not None:
        request = dataset.request
        rows = dataset.rows
        raw_dataset_hash = dataset.raw_dataset_hash
        applied_actions = dataset.report.applied_actions
        issues = dataset.report.issues
    if request is None or rows is None or raw_dataset_hash is None:
        raise ValueError("normalized dataset hash is missing inputs")
    mode = (
        request.adjustment_mode.value
        if isinstance(request.adjustment_mode, AdjustmentMode)
        else str(request.adjustment_mode)
    )
    payload = {
        "kind": "normalized_daily_bars_dataset",
        "version": 1,
        "as_of": canonical_datetime(request.as_of),
        "adjustment_mode": mode,
        "source_name": request.source_name,
        "raw_dataset_hash": raw_dataset_hash,
        "applied_actions": [
            {
                "action_id": None if item.action_id is None else str(item.action_id),
                "action_type": item.action_type,
                "instrument_id": str(item.instrument_id),
                "effective_time": canonical_datetime(item.effective_time),
                "available_time": canonical_datetime(item.available_time),
                "price_factor": canonical_decimal(item.price_factor),
                "volume_factor": canonical_decimal(item.volume_factor),
            }
            for item in sorted(
                applied_actions or (),
                key=lambda item: (
                    item.effective_time,
                    item.available_time,
                    item.action_type,
                    str(item.action_id) if item.action_id is not None else "",
                ),
            )
        ],
        "issues": [
            {
                "code": item.code,
                "message": item.message,
                "severity": item.severity,
                "instrument_id": None
                if item.instrument_id is None
                else str(item.instrument_id),
                "action_id": None if item.action_id is None else str(item.action_id),
            }
            for item in sorted(
                issues or (),
                key=lambda item: (
                    item.code,
                    item.severity,
                    str(item.action_id) if item.action_id is not None else "",
                ),
            )
        ],
        "rows": [
            {
                "instrument_id": str(row.instrument_id),
                "symbol": row.symbol,
                "source_name": row.source_name,
                "observation_time": canonical_datetime(row.observation_time),
                "available_time": canonical_datetime(row.available_time),
                "raw_open": canonical_decimal(row.raw_open),
                "raw_high": canonical_decimal(row.raw_high),
                "raw_low": canonical_decimal(row.raw_low),
                "raw_close": canonical_decimal(row.raw_close),
                "raw_volume": canonical_decimal(row.raw_volume),
                "normalized_open": canonical_decimal(row.normalized_open),
                "normalized_high": canonical_decimal(row.normalized_high),
                "normalized_low": canonical_decimal(row.normalized_low),
                "normalized_close": canonical_decimal(row.normalized_close),
                "normalized_volume": canonical_decimal(row.normalized_volume),
                "price_factor": canonical_decimal(row.price_factor),
                "volume_factor": canonical_decimal(row.volume_factor),
                "applied_action_ids": list(row.applied_action_ids),
            }
            for row in rows
        ],
    }
    if manifest_contains_secrets(payload):
        raise ValueError("normalized dataset hash must not contain secrets")
    return sha256_canonical(payload)


def _normalize_bar(
    bar: DailyBarDatasetRow,
    *,
    request: NormalizationRequest,
    price: Decimal,
    volume: Decimal,
    trace: NormalizationAdjustmentTrace,
) -> NormalizedDailyBar:
    raw_volume = bar.volume
    return NormalizedDailyBar(
        instrument_id=bar.instrument_id,
        symbol=bar.symbol,
        source_name=bar.source_name,
        observation_time=bar.observation_time,
        available_time=bar.available_time,
        as_of=request.as_of,
        raw_open=bar.open,
        raw_high=bar.high,
        raw_low=bar.low,
        raw_close=bar.close,
        raw_volume=raw_volume,
        normalized_open=bar.open * price,
        normalized_high=bar.high * price,
        normalized_low=bar.low * price,
        normalized_close=bar.close * price,
        normalized_volume=None if raw_volume is None else raw_volume * volume,
        price_factor=price,
        volume_factor=volume,
        applied_action_ids=trace.applied_action_ids,
        trace_id=trace.trace_id,
    )
