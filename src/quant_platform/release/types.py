"""Typed research release-candidate reports. Not a strategy or trading API."""

from __future__ import annotations

from dataclasses import dataclass

from quant_platform.release.constants import (
    RELEASE_STATUS_FORMAT_VERSION,
    RELEASE_STATUS_KIND,
)


@dataclass(frozen=True, slots=True)
class ReleaseCheckItem:
    name: str
    status: str
    message: str
    code: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class ReleaseRiskItem:
    code: str
    message: str
    severity: str = "info"

    def as_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class ReleaseCapabilitySummary:
    enabled: tuple[str, ...]
    disabled: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "enabled": list(self.enabled),
            "disabled": list(self.disabled),
        }


@dataclass(frozen=True, slots=True)
class ReleaseStatusReport:
    ok: bool
    app_mode: str
    package_version: str
    alembic_head_expected: str
    alembic_head_scripts: tuple[str, ...]
    database_required: bool
    database_checked: bool
    capabilities: ReleaseCapabilitySummary
    registered_policy_names: tuple[str, ...]
    registered_policy_count: int
    regression_case_count: int
    trading_constructs_detected: bool
    ai_runtime_detected: bool
    final_freeze_ready: bool
    evidence_bundle_available: bool
    checks: tuple[ReleaseCheckItem, ...]
    risks: tuple[ReleaseRiskItem, ...]
    error_count: int
    warning_count: int
    report_hash: str

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": RELEASE_STATUS_KIND,
            "format_version": RELEASE_STATUS_FORMAT_VERSION,
            "ok": self.ok,
            "app_mode": self.app_mode,
            "package_version": self.package_version,
            "alembic_head_expected": self.alembic_head_expected,
            "alembic_head_scripts": list(self.alembic_head_scripts),
            "database_required": self.database_required,
            "database_checked": self.database_checked,
            "final_freeze_ready": self.final_freeze_ready,
            "evidence_bundle_available": self.evidence_bundle_available,
            "capabilities": self.capabilities.as_mapping(),
            "registered_policy_names": list(self.registered_policy_names),
            "registered_policy_count": self.registered_policy_count,
            "regression_case_count": self.regression_case_count,
            "trading_constructs_detected": self.trading_constructs_detected,
            "ai_runtime_detected": self.ai_runtime_detected,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks": [item.as_mapping() for item in self.checks],
            "risks": [item.as_mapping() for item in self.risks],
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload
