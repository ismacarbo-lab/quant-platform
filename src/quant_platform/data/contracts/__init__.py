"""Vendor-agnostic data source contracts. Offline only; no real vendors."""

from quant_platform.data.contracts.conformance import (
    assert_offline_contract_package,
    build_data_contract_conformance_report,
    build_data_contract_conformance_request,
    detect_contract_forbidden_terms,
    hash_data_contract_conformance_report,
    summarize_vendor_payload_batch,
)
from quant_platform.data.contracts.conformance_artifacts import (
    write_data_contract_conformance_artifacts,
)
from quant_platform.data.contracts.conformance_integrity import (
    verify_data_contract_conformance_artifacts,
)
from quant_platform.data.contracts.conformance_regression import (
    default_data_contract_conformance_dir,
    run_data_contract_conformance_regression,
)
from quant_platform.data.contracts.conformance_types import (
    DataContractConformanceArtifact,
    DataContractConformanceIntegrityReport,
    DataContractConformanceIssue,
    DataContractConformanceManifest,
    DataContractConformanceReport,
    DataContractConformanceRequest,
    DataContractConformanceSummary,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.fake_provider import (
    FakeVendorPayloadProvider,
    default_synthetic_batch,
    load_offline_vendor_payload_batch,
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
    "DataContractConformanceArtifact",
    "DataContractConformanceIntegrityReport",
    "DataContractConformanceIssue",
    "DataContractConformanceManifest",
    "DataContractConformanceReport",
    "DataContractConformanceRequest",
    "DataContractConformanceSummary",
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
    "assert_offline_contract_package",
    "build_data_contract_conformance_report",
    "build_data_contract_conformance_request",
    "default_data_contract_conformance_dir",
    "default_offline_contract",
    "default_synthetic_batch",
    "detect_contract_forbidden_terms",
    "hash_data_contract_conformance_report",
    "hash_vendor_payload_batch",
    "load_offline_vendor_payload_batch",
    "run_data_contract_conformance_regression",
    "summarize_vendor_payload_batch",
    "validate_corporate_action_payload",
    "validate_daily_bar_payload",
    "validate_market_session_payload",
    "validate_vendor_payload_batch",
    "verify_data_contract_conformance_artifacts",
    "write_data_contract_conformance_artifacts",
]
