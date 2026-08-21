"""Fail if trading/broker packages or premature AI/runtime deps appear."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "quant_platform"
PYPROJECT = ROOT / "pyproject.toml"

FORBIDDEN_RUNTIME_PACKAGES = (
    "execution",
    "broker",
    "brokers",
    "trading",
    "orders",
    "portfolio",
    "positions",
    "strategies",
    "signals",
)

FORBIDDEN_DEPENDENCY_NAMES = frozenset(
    {
        "alpaca",
        "alpaca-py",
        "ib-insync",
        "ib_insync",
        "ibapi",
        "ccxt",
        "yfinance",
        "openai",
        "anthropic",
        "langchain",
        "llama-index",
        "llama_index",
        "transformers",
        "cursor",
        "cursor-sdk",
        "cursor_sdk",
    }
)


def _requirement_name(spec: str) -> str:
    token = spec.strip()
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        token = token.split(separator, 1)[0]
    return token.strip().lower()


def _declared_requirement_names() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names: set[str] = set()
    project = data.get("project", {})
    for spec in project.get("dependencies", []):
        if isinstance(spec, str):
            names.add(_requirement_name(spec))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for group in optional.values():
            for spec in group:
                if isinstance(spec, str):
                    names.add(_requirement_name(spec))
    for group in data.get("dependency-groups", {}).values():
        if not isinstance(group, list):
            continue
        for spec in group:
            if isinstance(spec, str):
                names.add(_requirement_name(spec))
    return names


def test_forbidden_runtime_packages_are_absent() -> None:
    present = []
    for name in FORBIDDEN_RUNTIME_PACKAGES:
        if (PACKAGE_ROOT / name).exists() or (PACKAGE_ROOT / f"{name}.py").exists():
            present.append(name)
    assert present == []


def test_pyproject_has_no_trading_or_ai_runtime_dependencies() -> None:
    declared = _declared_requirement_names()
    leaked = sorted(declared & FORBIDDEN_DEPENDENCY_NAMES)
    assert leaked == []


def test_cursor_is_not_a_package_dependency() -> None:
    declared = _declared_requirement_names()
    assert "cursor" not in declared
    assert "cursor-sdk" not in declared
    assert "cursor_sdk" not in declared


def test_settings_have_no_ai_vendor_fields() -> None:
    from quant_platform.core.config import Settings

    names = {field.lower() for field in Settings.model_fields}
    for needle in ("openai", "anthropic", "langchain", "cursor"):
        assert all(needle not in name for name in names)
