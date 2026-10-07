"""Offline data-contract conformance runner. No network, vendors, or trading."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from quant_platform.data.contracts.conformance_types import (
    CONFORMANCE_HASH_FORMAT_VERSION,
    CONFORMANCE_HASH_KIND,
    DEFAULT_CONTRACT_NAME,
    DEFAULT_CONTRACT_VERSION,
    DEFAULT_CREATED_BY,
    DataContractConformanceIssue,
    DataContractConformanceReport,
    DataContractConformanceRequest,
    DataContractConformanceSummary,
    DataContractIssueCounts,
    DataContractPayloadCounts,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import (
    hash_vendor_payload_batch,
    sha256_canonical_mapping,
)
from quant_platform.data.contracts.types import (
    NETWORK_SOURCE_KINDS,
    VendorPayloadBatch,
)
from quant_platform.data.contracts.validation import validate_vendor_payload_batch
from quant_platform.data.payload import redact_payload_secrets

_FORBIDDEN_TERMS = (
    "pnl",
    "returns",
    "sharpe",
    "drawdown",
    "strategy",
    "strategies",
    "signal",
    "signals",
    "order",
    "orders",
    "fill",
    "fills",
    "trade",
    "trades",
    "position",
    "positions",
    "portfolio",
    "broker",
    "brokers",
    "trading",
    "execution",
)
_FORBIDDEN_TERM = re.compile(
    r"(?i)\b(?:" + "|".join(re.escape(term) for term in _FORBIDDEN_TERMS) + r")\b"
)
_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)


def _contract_network_violation(batch: VendorPayloadBatch) -> bool:
    contract = batch.contract
    if contract.requires_credentials:
        return True
    return contract.requires_network and (
        contract.source_kind not in NETWORK_SOURCE_KINDS
    )


def summarize_vendor_payload_batch(
    batch: VendorPayloadBatch,
) -> DataContractPayloadCounts:
    """Count records in a captured batch. Does not validate."""
    return DataContractPayloadCounts(
        daily_bars=len(batch.daily_bars),
        corporate_actions=len(batch.corporate_actions),
        market_sessions=len(batch.market_sessions),
    )


def detect_contract_forbidden_terms(
    batch: VendorPayloadBatch,
) -> tuple[DataContractConformanceIssue, ...]:
    """Scan payload metadata for trading/performance terms. No network."""
    issues: list[DataContractConformanceIssue] = []
    for index, bar in enumerate(batch.daily_bars):
        issues.extend(
            _scan_mapping(
                bar.metadata,
                record_kind="daily_bar",
                record_index=index,
                field="metadata",
            )
        )
        issues.extend(
            _scan_mapping(
                bar.raw_payload,
                record_kind="daily_bar",
                record_index=index,
                field="raw_payload",
            )
        )
    for index, action in enumerate(batch.corporate_actions):
        issues.extend(
            _scan_mapping(
                action.metadata,
                record_kind="corporate_action",
                record_index=index,
                field="metadata",
            )
        )
        if action.note:
            issues.extend(
                _scan_text(
                    action.note,
                    record_kind="corporate_action",
                    record_index=index,
                    field="note",
                )
            )
    for index, session in enumerate(batch.market_sessions):
        issues.extend(
            _scan_mapping(
                session.metadata,
                record_kind="market_session",
                record_index=index,
                field="metadata",
            )
        )
        if session.note:
            issues.extend(
                _scan_text(
                    session.note,
                    record_kind="market_session",
                    record_index=index,
                    field="note",
                )
            )
    return tuple(issues)


def detect_offline_contract_violations(
    package_root: Path | str | None = None,
) -> tuple[str, ...]:
    """Return networking/vendor findings under quant_platform. Repo-local."""
    from quant_platform.release.guards import (
        detect_contracts_networking,
        detect_real_vendor_clients,
    )

    root = (
        Path(package_root)
        if package_root is not None
        else Path(__file__).resolve().parents[2]
    )
    findings = list(detect_contracts_networking(root))
    findings.extend(detect_real_vendor_clients(root))
    return tuple(dict.fromkeys(findings))


def assert_offline_contract_package(package_root: Path | str | None = None) -> None:
    """Raise if the contracts package imported networking or a real vendor."""
    findings = detect_offline_contract_violations(package_root)
    if findings:
        raise VendorContractError(
            "data contracts must stay offline: " + ", ".join(findings),
            code=VendorContractErrorCode.NETWORKING_IMPORT,
        )


def build_data_contract_conformance_request(
    *,
    contract_name: str = DEFAULT_CONTRACT_NAME,
    contract_version: str = DEFAULT_CONTRACT_VERSION,
    source_name: str | None = None,
    created_by: str = DEFAULT_CREATED_BY,
    notes: str | None = None,
    include_source_payload: bool = False,
) -> DataContractConformanceRequest:
    name = contract_name.strip() or DEFAULT_CONTRACT_NAME
    version = contract_version.strip() or DEFAULT_CONTRACT_VERSION
    creator = created_by.strip() or DEFAULT_CREATED_BY
    note = None if notes is None else notes.strip() or None
    source = None if source_name is None else source_name.strip() or None
    _reject_secret_text(name, field="contract_name")
    _reject_secret_text(version, field="contract_version")
    _reject_secret_text(creator, field="created_by")
    if source is not None:
        _reject_secret_text(source, field="source_name")
    if note is not None:
        _reject_secret_text(note, field="notes")
        if _FORBIDDEN_TERM.search(note):
            raise VendorContractError(
                "conformance notes must not contain trading or performance terms",
                code=VendorContractErrorCode.FORBIDDEN_TERM,
            )
    return DataContractConformanceRequest(
        contract_name=name,
        contract_version=version,
        source_name=source,
        created_by=creator,
        notes=note,
        include_source_payload=include_source_payload,
    )


def build_data_contract_conformance_report(
    batch: VendorPayloadBatch,
    request: DataContractConformanceRequest | None = None,
    *,
    package_root: Path | str | None = None,
) -> DataContractConformanceReport:
    """Validate a batch against the offline contract. Never opens sockets."""
    req = request if request is not None else build_data_contract_conformance_request()
    validation = validate_vendor_payload_batch(batch)
    issues = [
        DataContractConformanceIssue(
            code=item.code,
            message=item.message,
            field=item.field,
            record_kind=item.record_kind,
            record_index=item.record_index,
        )
        for item in validation.issues
    ]
    seen = {
        (item.code, item.field, item.record_kind, item.record_index) for item in issues
    }
    for extra in detect_contract_forbidden_terms(batch):
        key = (extra.code, extra.field, extra.record_kind, extra.record_index)
        if key not in seen:
            issues.append(extra)
            seen.add(key)
    offline_findings = detect_offline_contract_violations(package_root)
    network_violation = _contract_network_violation(batch)
    if network_violation:
        issues.append(
            DataContractConformanceIssue(
                code="offline_contract_violation",
                message=(
                    "only vendor_api contracts may require network; "
                    "credentials are never allowed"
                ),
                field="contract",
                record_kind="contract",
            )
        )
    for finding in offline_findings:
        issues.append(
            DataContractConformanceIssue(
                code="offline_contract_violation",
                message=f"offline package violation: {finding}",
                field="package",
                record_kind="package",
            )
        )
    ranked = tuple(sorted(issues, key=_issue_sort_key))
    codes = Counter(item.code for item in ranked)
    issue_counts = DataContractIssueCounts(
        total=len(ranked),
        by_code=tuple(sorted(codes.items())),
    )
    payload_counts = summarize_vendor_payload_batch(batch)
    source_name = req.source_name or batch.source_name
    batch_hash = hash_vendor_payload_batch(batch)
    capabilities = tuple(item.value for item in batch.contract.capabilities)
    validation_ok = validation.ok
    forbidden_terms_ok = all(item.code != "forbidden_term" for item in ranked)
    offline_only_ok = all(item.code != "offline_contract_violation" for item in ranked)
    if network_violation:
        offline_only_ok = False
    if offline_findings:
        offline_only_ok = False
    summary = DataContractConformanceSummary(
        contract_name=req.contract_name,
        contract_version=req.contract_version,
        source_name=source_name,
        batch_hash=batch_hash,
        payload_counts=payload_counts,
        issue_counts=issue_counts,
        capability_summary=capabilities,
        validation_ok=validation_ok,
        forbidden_terms_ok=forbidden_terms_ok,
        offline_only_ok=offline_only_ok,
    )
    draft = DataContractConformanceReport(
        ok=validation_ok and forbidden_terms_ok and offline_only_ok,
        summary=summary,
        issues=ranked,
        created_by=req.created_by,
        notes=req.notes,
        conformance_hash="",
    )
    return DataContractConformanceReport(
        ok=draft.ok,
        summary=draft.summary,
        issues=draft.issues,
        created_by=draft.created_by,
        notes=draft.notes,
        conformance_hash=hash_data_contract_conformance_report(draft),
    )


def hash_data_contract_conformance_report(
    report: DataContractConformanceReport | Mapping[str, object],
) -> str:
    """SHA-256 of the conformance report. No wall-clock or absolute paths."""
    if isinstance(report, DataContractConformanceReport):
        payload = report.as_mapping(include_conformance_hash=False)
    else:
        payload = dict(report)
        payload.pop("conformance_hash", None)
        payload.pop("report_hash", None)
    summary = payload.get("summary")
    summary_map = dict(summary) if isinstance(summary, dict) else {}
    issues = payload.get("issues")
    issue_codes: list[str] = []
    if isinstance(issues, list):
        for item in issues:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                issue_codes.append(str(item["code"]))
    issue_codes.sort()
    digest = {
        "kind": CONFORMANCE_HASH_KIND,
        "version": CONFORMANCE_HASH_FORMAT_VERSION,
        "ok": payload.get("ok"),
        "contract_name": summary_map.get("contract_name"),
        "contract_version": summary_map.get("contract_version"),
        "source_name": summary_map.get("source_name"),
        "batch_hash": summary_map.get("batch_hash"),
        "payload_counts": summary_map.get("payload_counts"),
        "issue_counts": summary_map.get("issue_counts"),
        "capability_summary": summary_map.get("capability_summary"),
        "validation_ok": summary_map.get("validation_ok"),
        "forbidden_terms_ok": summary_map.get("forbidden_terms_ok"),
        "offline_only_ok": summary_map.get("offline_only_ok"),
        "issue_codes": issue_codes,
        "created_by": payload.get("created_by"),
        "notes": payload.get("notes") or "",
    }
    blob = str(digest)
    lowered = blob.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "conformance report must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    return sha256_canonical_mapping(digest)


def _scan_mapping(
    mapping: Mapping[str, object],
    *,
    record_kind: str,
    record_index: int,
    field: str,
) -> list[DataContractConformanceIssue]:
    redacted = redact_payload_secrets(mapping)
    return _scan_text(
        str(redacted),
        record_kind=record_kind,
        record_index=record_index,
        field=field,
    )


def _scan_text(
    text: str,
    *,
    record_kind: str,
    record_index: int | None,
    field: str,
) -> list[DataContractConformanceIssue]:
    if not _FORBIDDEN_TERM.search(text):
        return []
    return [
        DataContractConformanceIssue(
            code="forbidden_term",
            message="payload must not contain trading or performance terms",
            field=field,
            record_kind=record_kind,
            record_index=record_index,
        )
    ]


def _issue_sort_key(
    item: DataContractConformanceIssue,
) -> tuple[str, str, str, int]:
    return (
        item.code,
        item.record_kind or "",
        item.field or "",
        item.record_index if item.record_index is not None else -1,
    )


def _reject_secret_text(value: str, *, field: str) -> None:
    lowered = value.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                f"{field} must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
