"""Vendor-agnostic data source contracts. Offline only; no real vendors."""

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.fake_provider import (
    FakeVendorPayloadProvider,
    default_synthetic_batch,
)
from quant_platform.data.contracts.hashing import hash_vendor_payload_batch
from quant_platform.data.contracts.types import (
    FORBIDDEN_VENDOR_IDENTITY_NAMES,
    DataSourceContract,
    DataSourceKind,
    DataVendorCapability,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
    VendorPayloadValidationIssue,
    VendorPayloadValidationReport,
    default_offline_contract,
)
from quant_platform.data.contracts.validation import (
    validate_corporate_action_payload,
    validate_daily_bar_payload,
    validate_market_session_payload,
    validate_vendor_payload_batch,
)

__all__ = [
    "FORBIDDEN_VENDOR_IDENTITY_NAMES",
    "DataSourceContract",
    "DataSourceKind",
    "DataVendorCapability",
    "FakeVendorPayloadProvider",
    "VendorContractError",
    "VendorContractErrorCode",
    "VendorCorporateActionPayload",
    "VendorDailyBarPayload",
    "VendorMarketSessionPayload",
    "VendorPayloadBatch",
    "VendorPayloadValidationIssue",
    "VendorPayloadValidationReport",
    "default_offline_contract",
    "default_synthetic_batch",
    "hash_vendor_payload_batch",
    "validate_corporate_action_payload",
    "validate_daily_bar_payload",
    "validate_market_session_payload",
    "validate_vendor_payload_batch",
]
