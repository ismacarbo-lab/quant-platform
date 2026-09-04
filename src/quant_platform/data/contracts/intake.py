"""Offline contract payload intake plan and optional PostgreSQL write.

This is not a vendor client, download path, or trading engine.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.data.contracts.conformance import (
    build_data_contract_conformance_report,
    build_data_contract_conformance_request,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import (
    jsonable_vendor_payload,
    sha256_canonical_mapping,
)
from quant_platform.data.contracts.intake_types import (
    DEFAULT_ASSET_CLASS,
    DEFAULT_CONTRACT_NAME,
    DEFAULT_CONTRACT_VERSION,
    DEFAULT_CREATED_BY,
    INTAKE_PLAN_HASH_FORMAT_VERSION,
    INTAKE_PLAN_HASH_KIND,
    INTAKE_REPORT_HASH_FORMAT_VERSION,
    INTAKE_REPORT_HASH_KIND,
    OFFLINE_SOURCE_VENDOR_LABEL,
    RECORD_KIND_CORPORATE_ACTION,
    RECORD_KIND_DAILY_BAR,
    RECORD_KIND_MARKET_SESSION,
    ContractPayloadIntakeCounts,
    ContractPayloadIntakeIssue,
    ContractPayloadIntakeItem,
    ContractPayloadIntakePlan,
    ContractPayloadIntakeReport,
    ContractPayloadIntakeRequest,
    empty_intake_counts,
)
from quant_platform.data.contracts.types import (
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
)
from quant_platform.data.models import (
    CorporateAction,
    DataSource,
    IngestionStatus,
    MarketSession,
)
from quant_platform.data.payload import payload_sha256, redact_payload_secrets
from quant_platform.data.repository import (
    create_corporate_action,
    create_ingestion_run,
    finish_ingestion_run,
    get_market_calendar_by_code,
    insert_daily_bars,
    insert_ingestion_error,
    insert_raw_record,
    upsert_instrument,
    upsert_market_calendar,
)
from quant_platform.data.validation import (
    DailyBarDraft,
    DataValidationError,
    ensure_utc,
)
from quant_platform.research.snapshots import manifest_contains_secrets

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)
_FORBIDDEN_TERM = re.compile(
    r"(?i)\b(?:pnl|returns|sharpe|drawdown|strategy|strategies|signal|signals|"
    r"order|orders|fill|fills|trade|trades|position|positions|portfolio|"
    r"broker|brokers|trading|execution)\b"
)


def build_contract_payload_intake_request(
    *,
    contract_name: str = DEFAULT_CONTRACT_NAME,
    contract_version: str = DEFAULT_CONTRACT_VERSION,
    source_name: str | None = None,
    created_by: str = DEFAULT_CREATED_BY,
    notes: str | None = None,
    write_db: bool = False,
    allow_invalid: bool = False,
    include_source_payload: bool = False,
    asset_class: str = DEFAULT_ASSET_CLASS,
) -> ContractPayloadIntakeRequest:
    name = contract_name.strip() or DEFAULT_CONTRACT_NAME
    version = contract_version.strip() or DEFAULT_CONTRACT_VERSION
    creator = created_by.strip() or DEFAULT_CREATED_BY
    note = None if notes is None else notes.strip() or None
    source = None if source_name is None else source_name.strip() or None
    klass = asset_class.strip() or DEFAULT_ASSET_CLASS
    _reject_secret_text(name, field="contract_name")
    _reject_secret_text(version, field="contract_version")
    _reject_secret_text(creator, field="created_by")
    _reject_secret_text(klass, field="asset_class")
    if source is not None:
        _reject_secret_text(source, field="source_name")
    if note is not None:
        _reject_secret_text(note, field="notes")
        if _FORBIDDEN_TERM.search(note):
            raise VendorContractError(
                "intake notes must not contain trading or performance terms",
                code=VendorContractErrorCode.FORBIDDEN_TERM,
            )
    return ContractPayloadIntakeRequest(
        contract_name=name,
        contract_version=version,
        source_name=source,
        created_by=creator,
        notes=note,
        write_db=write_db,
        allow_invalid=allow_invalid,
        include_source_payload=include_source_payload,
        asset_class=klass,
    )


def relabel_contract_payload_batch(
    batch: VendorPayloadBatch,
    source_name: str,
) -> VendorPayloadBatch:
    """Copy a batch under a new source_name. Does not download or mutate DB."""
    name = source_name.strip()
    if not name:
        raise VendorContractError(
            "source_name is required",
            code=VendorContractErrorCode.EMPTY_SOURCE_NAME,
        )
    _reject_secret_text(name, field="source_name")
    contract = replace(batch.contract, source_name=name)
    return VendorPayloadBatch(
        source_name=name,
        contract=contract,
        daily_bars=tuple(replace(item, source_name=name) for item in batch.daily_bars),
        corporate_actions=tuple(
            replace(item, source_name=name) for item in batch.corporate_actions
        ),
        market_sessions=tuple(
            replace(item, source_name=name) for item in batch.market_sessions
        ),
    )


def build_contract_payload_intake_plan(
    batch: VendorPayloadBatch,
    request: ContractPayloadIntakeRequest | None = None,
) -> ContractPayloadIntakePlan:
    """Validate a batch and map payloads to intake items. Never writes DB."""
    req = request if request is not None else build_contract_payload_intake_request()
    working = batch
    if req.source_name and req.source_name != batch.source_name:
        working = relabel_contract_payload_batch(batch, req.source_name)
    conformance_request = build_data_contract_conformance_request(
        contract_name=req.contract_name,
        contract_version=req.contract_version,
        source_name=req.source_name or working.source_name,
        created_by=req.created_by,
        notes=req.notes,
        include_source_payload=False,
    )
    conformance = build_data_contract_conformance_report(
        working,
        conformance_request,
    )
    issues = tuple(
        ContractPayloadIntakeIssue(
            code=item.code,
            message=item.message,
            field=item.field,
            record_kind=item.record_kind,
            record_index=item.record_index,
        )
        for item in conformance.issues
    )
    payload_counts = ContractPayloadIntakeCounts(
        daily_bars=len(working.daily_bars),
        corporate_actions=len(working.corporate_actions),
        market_sessions=len(working.market_sessions),
    )
    reject_all = (not conformance.ok) and (not req.allow_invalid)
    items: list[ContractPayloadIntakeItem] = []
    items.extend(
        _plan_items_for_kind(
            RECORD_KIND_DAILY_BAR,
            working.daily_bars,
            issues=issues,
            reject_all=reject_all,
        )
    )
    items.extend(
        _plan_items_for_kind(
            RECORD_KIND_CORPORATE_ACTION,
            working.corporate_actions,
            issues=issues,
            reject_all=reject_all,
        )
    )
    items.extend(
        _plan_items_for_kind(
            RECORD_KIND_MARKET_SESSION,
            working.market_sessions,
            issues=issues,
            reject_all=reject_all,
        )
    )
    ranked_items = tuple(
        sorted(items, key=lambda item: (item.record_kind, item.record_index))
    )
    accepted_counts = _counts_from_items(ranked_items, accepted=True)
    rejected_counts = _counts_from_items(ranked_items, accepted=False)
    warnings: list[ContractPayloadIntakeIssue] = []
    if req.allow_invalid and not conformance.ok:
        warnings.append(
            ContractPayloadIntakeIssue(
                code="allow_invalid_plan",
                message="allow_invalid produced a plan with conformance issues",
            )
        )
    if req.write_db and not conformance.ok:
        warnings.append(
            ContractPayloadIntakeIssue(
                code="db_write_skipped_invalid_plan",
                message="write_db was requested but invalid batches are not written",
            )
        )
    ok = conformance.ok
    draft = ContractPayloadIntakePlan(
        ok=ok,
        source_name=conformance.summary.source_name,
        contract_name=req.contract_name,
        contract_version=req.contract_version,
        batch_hash=conformance.summary.batch_hash,
        conformance_hash=conformance.conformance_hash,
        write_db=req.write_db,
        allow_invalid=req.allow_invalid,
        payload_counts=payload_counts,
        accepted_counts=accepted_counts,
        rejected_counts=rejected_counts,
        planned_daily_bar_count=accepted_counts.daily_bars,
        planned_corporate_action_count=accepted_counts.corporate_actions,
        planned_market_session_count=accepted_counts.market_sessions,
        items=ranked_items,
        issues=issues,
        warnings=tuple(warnings),
        created_by=req.created_by,
        notes=req.notes,
        intake_hash="",
    )
    return replace(draft, intake_hash=hash_contract_payload_intake_plan(draft))


def build_contract_payload_intake_report(
    plan: ContractPayloadIntakePlan,
    *,
    db_executed: bool = False,
    inserted_counts: ContractPayloadIntakeCounts | None = None,
    skipped_counts: ContractPayloadIntakeCounts | None = None,
    extra_issues: Sequence[ContractPayloadIntakeIssue] = (),
    extra_warnings: Sequence[ContractPayloadIntakeIssue] = (),
) -> ContractPayloadIntakeReport:
    """Build a report from a plan. Dry-run leaves inserted/skipped at zero."""
    inserted = inserted_counts if inserted_counts is not None else empty_intake_counts()
    skipped = skipped_counts if skipped_counts is not None else empty_intake_counts()
    issues = tuple(plan.issues) + tuple(extra_issues)
    warnings = tuple(plan.warnings) + tuple(extra_warnings)
    draft = ContractPayloadIntakeReport(
        ok=plan.ok,
        source_name=plan.source_name,
        contract_name=plan.contract_name,
        contract_version=plan.contract_version,
        batch_hash=plan.batch_hash,
        conformance_hash=plan.conformance_hash,
        write_db=plan.write_db,
        db_executed=db_executed,
        payload_counts=plan.payload_counts,
        accepted_counts=plan.accepted_counts,
        rejected_counts=plan.rejected_counts,
        planned_daily_bar_count=plan.planned_daily_bar_count,
        planned_corporate_action_count=plan.planned_corporate_action_count,
        planned_market_session_count=plan.planned_market_session_count,
        inserted_counts=inserted,
        skipped_counts=skipped,
        issues=issues,
        warnings=warnings,
        created_by=plan.created_by,
        notes=plan.notes,
        intake_hash="",
    )
    return replace(draft, intake_hash=hash_contract_payload_intake_report(draft))


def execute_contract_payload_intake(
    session: Session,
    batch: VendorPayloadBatch,
    request: ContractPayloadIntakeRequest,
) -> ContractPayloadIntakeReport:
    """Write accepted payloads through existing ingestion. Requires write_db."""
    if not request.write_db:
        raise VendorContractError(
            "execute_contract_payload_intake requires write_db=True",
            code=VendorContractErrorCode.WRITE_DB_REQUIRED,
        )
    plan = build_contract_payload_intake_plan(batch, request)
    if not plan.ok:
        return build_contract_payload_intake_report(
            plan,
            db_executed=False,
            extra_warnings=(
                ContractPayloadIntakeIssue(
                    code="db_write_skipped_invalid_plan",
                    message="invalid batch was not written",
                ),
            ),
        )
    working = batch
    if request.source_name and request.source_name != batch.source_name:
        working = relabel_contract_payload_batch(batch, request.source_name)
    source = _get_or_create_offline_source(session, plan.source_name)
    run = create_ingestion_run(
        session,
        source_id=source.id,
        run_metadata={
            "kind": "contract_payload_intake",
            "contract_name": plan.contract_name,
            "contract_version": plan.contract_version,
            "batch_hash": plan.batch_hash,
            "conformance_hash": plan.conformance_hash,
            "plan_hash": plan.intake_hash,
            "write_db": True,
        },
    )
    inserted = empty_intake_counts()
    skipped = empty_intake_counts()
    instruments: dict[str, Any] = {}
    bronze_index = 0
    try:
        for item in plan.items:
            record = _record_for_item(working, item)
            payload = _bronze_payload(record)
            digest = item.payload_hash.removeprefix("sha256:")
            insert_raw_record(
                session,
                ingestion_run_id=run.id,
                source_id=source.id,
                record_index=bronze_index,
                raw_payload=payload,
                payload_hash=digest,
            )
            if not item.accepted:
                bronze_index += 1
                continue
            if item.record_kind == RECORD_KIND_DAILY_BAR:
                bar_inserted, bar_skipped = _insert_daily_bar_item(
                    session,
                    record=working.daily_bars[item.record_index],
                    source_id=source.id,
                    run_id=run.id,
                    instruments=instruments,
                    asset_class=request.asset_class,
                    record_index=bronze_index,
                    payload=payload,
                )
                inserted = _add_counts(
                    inserted, daily_bars=bar_inserted, corporate_actions=0, sessions=0
                )
                skipped = _add_counts(
                    skipped, daily_bars=bar_skipped, corporate_actions=0, sessions=0
                )
            elif item.record_kind == RECORD_KIND_CORPORATE_ACTION:
                ca_inserted, ca_skipped = _insert_corporate_action_item(
                    session,
                    record=working.corporate_actions[item.record_index],
                    instruments=instruments,
                    asset_class=request.asset_class,
                    payload_hash=item.payload_hash,
                    source_name=plan.source_name,
                )
                inserted = _add_counts(
                    inserted, daily_bars=0, corporate_actions=ca_inserted, sessions=0
                )
                skipped = _add_counts(
                    skipped, daily_bars=0, corporate_actions=ca_skipped, sessions=0
                )
            elif item.record_kind == RECORD_KIND_MARKET_SESSION:
                sess_inserted, sess_skipped = _insert_market_session_item(
                    session,
                    record=working.market_sessions[item.record_index],
                )
                inserted = _add_counts(
                    inserted, daily_bars=0, corporate_actions=0, sessions=sess_inserted
                )
                skipped = _add_counts(
                    skipped, daily_bars=0, corporate_actions=0, sessions=sess_skipped
                )
            bronze_index += 1
        finish_ingestion_run(
            session,
            run,
            status=IngestionStatus.SUCCEEDED,
            row_count=plan.payload_counts.total,
            accepted_count=plan.accepted_counts.total,
            rejected_count=plan.rejected_counts.total,
        )
    except Exception:
        finish_ingestion_run(
            session,
            run,
            status=IngestionStatus.FAILED,
            row_count=plan.payload_counts.total,
            accepted_count=0,
            rejected_count=plan.payload_counts.total,
            error_message="contract payload intake failed",
        )
        raise
    return build_contract_payload_intake_report(
        plan,
        db_executed=True,
        inserted_counts=inserted,
        skipped_counts=skipped,
    )


def hash_contract_payload_intake_plan(
    plan: ContractPayloadIntakePlan | Mapping[str, object],
) -> str:
    """SHA-256 of the intake plan. No wall-clock, paths, or secrets."""
    if isinstance(plan, ContractPayloadIntakePlan):
        payload = plan.as_mapping(include_intake_hash=False)
    else:
        payload = dict(plan)
        payload.pop("intake_hash", None)
    digest = {
        "kind": INTAKE_PLAN_HASH_KIND,
        "version": INTAKE_PLAN_HASH_FORMAT_VERSION,
        "ok": payload.get("ok"),
        "source_name": payload.get("source_name"),
        "contract_name": payload.get("contract_name"),
        "contract_version": payload.get("contract_version"),
        "batch_hash": payload.get("batch_hash"),
        "conformance_hash": payload.get("conformance_hash"),
        "write_db": payload.get("write_db"),
        "allow_invalid": payload.get("allow_invalid"),
        "payload_counts": payload.get("payload_counts"),
        "accepted_counts": payload.get("accepted_counts"),
        "rejected_counts": payload.get("rejected_counts"),
        "planned_daily_bar_count": payload.get("planned_daily_bar_count"),
        "planned_corporate_action_count": payload.get("planned_corporate_action_count"),
        "planned_market_session_count": payload.get("planned_market_session_count"),
        "items": payload.get("items"),
        "issue_codes": _issue_codes(payload.get("issues")),
        "warning_codes": _issue_codes(payload.get("warnings")),
        "created_by": payload.get("created_by"),
        "notes": payload.get("notes") or "",
    }
    _reject_secret_mapping(digest, label="intake plan")
    return sha256_canonical_mapping(digest)


def hash_contract_payload_intake_report(
    report: ContractPayloadIntakeReport | Mapping[str, object],
) -> str:
    """SHA-256 of the intake report. No wall-clock, paths, or secrets."""
    if isinstance(report, ContractPayloadIntakeReport):
        payload = report.as_mapping(include_intake_hash=False)
    else:
        payload = dict(report)
        payload.pop("intake_hash", None)
    digest = {
        "kind": INTAKE_REPORT_HASH_KIND,
        "version": INTAKE_REPORT_HASH_FORMAT_VERSION,
        "ok": payload.get("ok"),
        "source_name": payload.get("source_name"),
        "contract_name": payload.get("contract_name"),
        "contract_version": payload.get("contract_version"),
        "batch_hash": payload.get("batch_hash"),
        "conformance_hash": payload.get("conformance_hash"),
        "write_db": payload.get("write_db"),
        "db_executed": payload.get("db_executed"),
        "payload_counts": payload.get("payload_counts"),
        "accepted_counts": payload.get("accepted_counts"),
        "rejected_counts": payload.get("rejected_counts"),
        "planned_daily_bar_count": payload.get("planned_daily_bar_count"),
        "planned_corporate_action_count": payload.get("planned_corporate_action_count"),
        "planned_market_session_count": payload.get("planned_market_session_count"),
        "inserted_counts": payload.get("inserted_counts"),
        "skipped_counts": payload.get("skipped_counts"),
        "issue_codes": _issue_codes(payload.get("issues")),
        "warning_codes": _issue_codes(payload.get("warnings")),
        "created_by": payload.get("created_by"),
        "notes": payload.get("notes") or "",
    }
    _reject_secret_mapping(digest, label="intake report")
    return sha256_canonical_mapping(digest)


def _plan_items_for_kind(
    kind: str,
    records: Sequence[object],
    *,
    issues: Sequence[ContractPayloadIntakeIssue],
    reject_all: bool,
) -> list[ContractPayloadIntakeItem]:
    items: list[ContractPayloadIntakeItem] = []
    for index, record in enumerate(records):
        record_issues = [
            item
            for item in issues
            if item.record_kind == kind and item.record_index == index
        ]
        accepted = not reject_all and not record_issues
        skip_reason = None
        if not accepted:
            skip_reason = (
                record_issues[0].code if record_issues else "conformance_not_ok"
            )
        items.append(
            ContractPayloadIntakeItem(
                record_kind=kind,
                record_index=index,
                accepted=accepted,
                payload_hash=_payload_digest(record),
                symbol=_record_symbol(record),
                skip_reason=skip_reason,
            )
        )
    return items


def _counts_from_items(
    items: Sequence[ContractPayloadIntakeItem],
    *,
    accepted: bool,
) -> ContractPayloadIntakeCounts:
    daily = 0
    actions = 0
    sessions = 0
    for item in items:
        if item.accepted is not accepted:
            continue
        if item.record_kind == RECORD_KIND_DAILY_BAR:
            daily += 1
        elif item.record_kind == RECORD_KIND_CORPORATE_ACTION:
            actions += 1
        elif item.record_kind == RECORD_KIND_MARKET_SESSION:
            sessions += 1
    return ContractPayloadIntakeCounts(
        daily_bars=daily,
        corporate_actions=actions,
        market_sessions=sessions,
    )


def _payload_digest(record: object) -> str:
    payload = _bronze_payload(record)
    return f"sha256:{payload_sha256(payload)}"


def _bronze_payload(record: object) -> dict[str, object]:
    raw: Mapping[str, object]
    raw_payload = getattr(record, "raw_payload", None)
    if isinstance(raw_payload, Mapping) and raw_payload:
        raw = dict(raw_payload)
    else:
        mapping = dict(record.as_mapping())  # type: ignore[attr-defined]
        mapping.pop("ingestion_time", None)
        raw = mapping
    redacted = redact_payload_secrets(raw)
    converted = jsonable_vendor_payload(redacted)
    if not isinstance(converted, dict):
        return {"value": converted}
    return {str(key): value for key, value in converted.items()}


def _record_symbol(record: object) -> str | None:
    symbol = getattr(record, "symbol", None)
    if symbol is None:
        return None
    token = str(symbol).strip()
    return token or None


def _record_for_item(
    batch: VendorPayloadBatch,
    item: ContractPayloadIntakeItem,
) -> object:
    if item.record_kind == RECORD_KIND_DAILY_BAR:
        return batch.daily_bars[item.record_index]
    if item.record_kind == RECORD_KIND_CORPORATE_ACTION:
        return batch.corporate_actions[item.record_index]
    return batch.market_sessions[item.record_index]


def _get_or_create_offline_source(session: Session, name: str) -> DataSource:
    existing = session.scalar(select(DataSource).where(DataSource.name == name))
    if existing is not None:
        return existing
    source = DataSource(
        name=name,
        vendor=OFFLINE_SOURCE_VENDOR_LABEL,
        description="offline contract payload intake",
    )
    session.add(source)
    session.flush()
    return source


def _insert_daily_bar_item(
    session: Session,
    *,
    record: VendorDailyBarPayload,
    source_id: UUID,
    run_id: UUID,
    instruments: dict[str, Any],
    asset_class: str,
    record_index: int,
    payload: dict[str, object],
) -> tuple[int, int]:
    try:
        instrument = instruments.get(record.symbol)
        if instrument is None:
            instrument = upsert_instrument(
                session,
                symbol=record.symbol,
                asset_class=asset_class,
            )
            instruments[record.symbol] = instrument
        draft = DailyBarDraft(
            symbol=record.symbol,
            observation_time=record.observation_time,
            available_time=record.available_time,
            open=record.open,
            high=record.high,
            low=record.low,
            close=record.close,
            volume=record.volume,
        )
        inserted = insert_daily_bars(
            session,
            drafts=[draft],
            instruments_by_symbol=instruments,
            source_id=source_id,
            ingestion_run_id=run_id,
        )
    except (DataValidationError, KeyError) as exc:
        code = getattr(exc, "code", "validation_error")
        insert_ingestion_error(
            session,
            ingestion_run_id=run_id,
            source_id=source_id,
            record_index=record_index,
            error_code=str(code),
            error_message=str(exc),
            raw_payload=payload,
        )
        return 0, 1
    if inserted:
        return 1, 0
    return 0, 1


def _insert_corporate_action_item(
    session: Session,
    *,
    record: VendorCorporateActionPayload,
    instruments: dict[str, Any],
    asset_class: str,
    payload_hash: str,
    source_name: str,
) -> tuple[int, int]:
    instrument = instruments.get(record.symbol)
    if instrument is None:
        instrument = upsert_instrument(
            session,
            symbol=record.symbol,
            asset_class=asset_class,
        )
        instruments[record.symbol] = instrument
    effective = ensure_utc(record.effective_time, field="effective_time")
    available = ensure_utc(record.available_time, field="available_time")
    existing = session.scalar(
        select(CorporateAction).where(
            CorporateAction.instrument_id == instrument.id,
            CorporateAction.action_type == record.action_type,
            CorporateAction.effective_time == effective,
            CorporateAction.available_time == available,
        )
    )
    if existing is not None:
        return 0, 1
    create_corporate_action(
        session,
        instrument_id=instrument.id,
        action_type=record.action_type,
        effective_time=effective,
        available_time=available,
        quantity_before=record.quantity_before,
        quantity_after=record.quantity_after,
        cash_amount=record.cash_amount,
        currency=record.currency,
        note=record.note,
        details={
            "kind": "contract_payload_intake",
            "source_name": source_name,
            "payload_hash": payload_hash,
        },
    )
    return 1, 0


def _insert_market_session_item(
    session: Session,
    *,
    record: VendorMarketSessionPayload,
) -> tuple[int, int]:
    calendar = get_market_calendar_by_code(session, code=record.calendar_code)
    if calendar is None:
        calendar = upsert_market_calendar(
            session,
            code=record.calendar_code,
            name=record.calendar_code,
            timezone="UTC",
        )
    existing = session.scalar(
        select(MarketSession).where(
            MarketSession.calendar_id == calendar.id,
            MarketSession.session_date == record.session_date,
        )
    )
    if existing is not None:
        return 0, 1
    row = MarketSession(
        calendar_id=calendar.id,
        session_date=record.session_date,
        session_kind=record.session_kind,
        is_open=record.is_open,
        note=record.note,
    )
    session.add(row)
    session.flush()
    return 1, 0


def _add_counts(
    current: ContractPayloadIntakeCounts,
    *,
    daily_bars: int,
    corporate_actions: int,
    sessions: int,
) -> ContractPayloadIntakeCounts:
    return ContractPayloadIntakeCounts(
        daily_bars=current.daily_bars + daily_bars,
        corporate_actions=current.corporate_actions + corporate_actions,
        market_sessions=current.market_sessions + sessions,
    )


def _issue_codes(value: object) -> list[str]:
    codes: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                codes.append(str(item["code"]))
    codes.sort()
    return codes


def _reject_secret_text(value: str, *, field: str) -> None:
    lowered = value.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                f"{field} must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )


def _reject_secret_mapping(payload: Mapping[str, object], *, label: str) -> None:
    blob = str(payload)
    if manifest_contains_secrets(blob):
        raise VendorContractError(
            f"{label} must not contain secrets",
            code=VendorContractErrorCode.SECRET_IN_METADATA,
        )
    lowered = blob.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                f"{label} must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
