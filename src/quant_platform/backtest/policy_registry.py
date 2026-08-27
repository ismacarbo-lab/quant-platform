"""Static registry of allowed research policies. No plugins or entry points."""

from __future__ import annotations

from collections.abc import Mapping

from quant_platform.backtest.data_quality_policies import (
    CorporateActionAuditPolicy,
    CorrectionAuditPolicy,
    CoverageResearchPolicy,
    DataQualityResearchPolicy,
)
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import normalize_policy_config
from quant_platform.backtest.policy import EventCountingResearchPolicy
from quant_platform.backtest.policy_interface import ResearchPolicy
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    CORPORATE_ACTION_AUDIT_POLICY_NAME,
    CORRECTION_AUDIT_POLICY_NAME,
    COVERAGE_POLICY_NAME,
    DATA_QUALITY_POLICY_NAME,
    EVENT_COUNTING_POLICY_NAME,
    NOOP_POLICY_NAME,
)


def registered_policy_names() -> frozenset[str]:
    return ALLOWED_POLICY_NAMES


def is_registered_policy(name: str) -> bool:
    return name.strip() in ALLOWED_POLICY_NAMES


def get_research_policy(
    name: str,
    config: Mapping[str, object] | None = None,
) -> ResearchPolicy:
    """Return a built-in research policy. Rejects unknown names."""
    cleaned = name.strip()
    if cleaned not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name is not a registered research policy",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    normalized = normalize_policy_config(config)
    if cleaned == EVENT_COUNTING_POLICY_NAME:
        return EventCountingResearchPolicy(name=cleaned, config=normalized)
    if cleaned == DATA_QUALITY_POLICY_NAME:
        return DataQualityResearchPolicy(config=normalized)
    if cleaned == COVERAGE_POLICY_NAME:
        return CoverageResearchPolicy(config=normalized)
    if cleaned == CORPORATE_ACTION_AUDIT_POLICY_NAME:
        return CorporateActionAuditPolicy(config=normalized)
    if cleaned == CORRECTION_AUDIT_POLICY_NAME:
        return CorrectionAuditPolicy(config=normalized)
    return EventCountingResearchPolicy(name=NOOP_POLICY_NAME, config=normalized)
