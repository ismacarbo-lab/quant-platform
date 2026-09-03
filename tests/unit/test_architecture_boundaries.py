"""Fail if trading/broker packages or premature AI/runtime deps appear."""

from __future__ import annotations

from pathlib import Path

from quant_platform.core.config import Settings
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    ENABLED_CAPABILITIES,
    FORBIDDEN_DEPENDENCY_NAMES,
    FORBIDDEN_RUNTIME_PACKAGES,
)
from quant_platform.release.guards import (
    declared_requirement_names,
    detect_ai_runtime,
    detect_contracts_networking,
    detect_real_vendor_clients,
    forbidden_dependencies_declared,
    forbidden_runtime_packages_present,
    settings_ai_vendor_fields,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "quant_platform"
PYPROJECT = ROOT / "pyproject.toml"


def test_forbidden_runtime_packages_are_absent() -> None:
    assert forbidden_runtime_packages_present(PACKAGE_ROOT) == ()
    for name in FORBIDDEN_RUNTIME_PACKAGES:
        assert not (PACKAGE_ROOT / name).exists()
        assert not (PACKAGE_ROOT / f"{name}.py").exists()


def test_pyproject_has_no_trading_or_ai_runtime_dependencies() -> None:
    leaked = forbidden_dependencies_declared(PYPROJECT)
    assert leaked == ()
    declared = declared_requirement_names(PYPROJECT)
    assert declared.isdisjoint(FORBIDDEN_DEPENDENCY_NAMES)


def test_cursor_is_not_a_package_dependency() -> None:
    declared = declared_requirement_names(PYPROJECT)
    assert "cursor" not in declared
    assert "cursor-sdk" not in declared
    assert "cursor_sdk" not in declared


def test_settings_have_no_ai_vendor_fields() -> None:
    hits = settings_ai_vendor_fields(Settings.model_fields)
    assert hits == ()
    names = {field.lower() for field in Settings.model_fields}
    for needle in ("openai", "anthropic", "langchain", "cursor", "rag"):
        assert all(needle not in name for name in names)


def test_ai_runtime_is_not_detected_in_this_repo() -> None:
    findings = detect_ai_runtime(
        package_root=PACKAGE_ROOT,
        pyproject_path=PYPROJECT,
        settings_fields=Settings.model_fields,
    )
    assert findings == ()


def test_disabled_capabilities_cover_trading_and_ai() -> None:
    disabled = set(DISABLED_CAPABILITIES)
    for name in (
        "paper_trading",
        "live_trading",
        "brokers",
        "ai_runtime",
        "signals",
        "strategies",
        "portfolio",
        "order_execution",
    ):
        assert name in disabled


def test_vendor_agnostic_contracts_enabled_real_vendors_disabled() -> None:
    assert "vendor_agnostic_data_contracts" in ENABLED_CAPABILITIES
    assert "external_market_data_vendors" in DISABLED_CAPABILITIES
    assert detect_real_vendor_clients(PACKAGE_ROOT) == ()
    assert detect_contracts_networking(PACKAGE_ROOT) == ()
