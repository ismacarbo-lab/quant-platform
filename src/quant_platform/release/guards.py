"""Repo-local architecture guards. Scans this tree only; no network."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping
from pathlib import Path

from quant_platform.data.contracts.types import FORBIDDEN_VENDOR_IDENTITY_NAMES
from quant_platform.release.constants import (
    FORBIDDEN_DEPENDENCY_NAMES,
    FORBIDDEN_RUNTIME_PACKAGES,
)

FORBIDDEN_HTTP_IMPORT_ROOTS = frozenset(
    {
        "aiohttp",
        "httpx",
        "requests",
        "urllib3",
    }
)
FORBIDDEN_HTTP_IMPORT_FULL = frozenset(
    {
        "http.client",
        "socket",
        "urllib.request",
    }
)


def forbidden_runtime_packages_present(package_root: Path | str) -> tuple[str, ...]:
    """Return forbidden package names found as direct children of the root."""
    root = Path(package_root)
    present: list[str] = []
    if not root.is_dir():
        return ()
    for name in FORBIDDEN_RUNTIME_PACKAGES:
        if (root / name).is_dir() or (root / f"{name}.py").is_file():
            present.append(name)
    return tuple(present)


def declared_requirement_names(pyproject_path: Path | str) -> frozenset[str]:
    data = tomllib.loads(Path(pyproject_path).read_text(encoding="utf-8"))
    names: set[str] = set()
    project = data.get("project", {})
    if isinstance(project, dict):
        _collect_requirement_names(project.get("dependencies"), names)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group in optional.values():
                _collect_requirement_names(group, names)
    groups = data.get("dependency-groups", {})
    if isinstance(groups, dict):
        for group in groups.values():
            _collect_requirement_names(group, names)
    return frozenset(names)


def forbidden_dependencies_declared(pyproject_path: Path | str) -> tuple[str, ...]:
    declared = declared_requirement_names(pyproject_path)
    return tuple(sorted(declared & FORBIDDEN_DEPENDENCY_NAMES))


def settings_ai_vendor_fields(
    field_names: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if field_names is None:
        return ()
    names = {str(name).lower() for name in field_names}
    hits: list[str] = []
    for needle in ("openai", "anthropic", "langchain", "cursor", "rag"):
        hits.extend(sorted(name for name in names if needle in name))
    return tuple(hits)


def detect_real_vendor_clients(package_root: Path | str) -> tuple[str, ...]:
    """Return real-vendor module paths found under the package root."""
    root = Path(package_root)
    if not root.is_dir():
        return ()
    findings: list[str] = []
    for name in sorted(FORBIDDEN_VENDOR_IDENTITY_NAMES):
        candidates = (
            root / name,
            root / f"{name}.py",
            root / "data" / name,
            root / "data" / f"{name}.py",
            root / "data" / "vendors" / name,
            root / "data" / "vendors" / f"{name}.py",
            root / "data" / "contracts" / f"{name}.py",
        )
        if any(path.is_dir() or path.is_file() for path in candidates):
            findings.append(f"package:{name}")
    return tuple(findings)


def detect_contracts_networking(package_root: Path | str) -> tuple[str, ...]:
    """Return forbidden HTTP/socket imports in data/contracts. Offline only."""
    contracts = Path(package_root) / "data" / "contracts"
    if not contracts.is_dir():
        return ()
    findings: list[str] = []
    for path in sorted(contracts.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "urllib":
                    modules.extend(
                        f"urllib.{alias.name}" if alias.name != "*" else "urllib"
                        for alias in node.names
                    )
                else:
                    modules.append(node.module)
            for module in modules:
                imported_root = module.split(".", 1)[0]
                if (
                    imported_root in FORBIDDEN_HTTP_IMPORT_ROOTS
                    or module in FORBIDDEN_HTTP_IMPORT_FULL
                    or imported_root in FORBIDDEN_VENDOR_IDENTITY_NAMES
                    or module in FORBIDDEN_VENDOR_IDENTITY_NAMES
                ):
                    findings.append(f"{path.name}:{module}")
    return tuple(dict.fromkeys(findings))


def detect_ai_runtime(
    *,
    package_root: Path | str,
    pyproject_path: Path | str,
    settings_fields: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Return AI-runtime findings for this repository only."""
    findings: list[str] = []
    findings.extend(
        f"package:{name}"
        for name in forbidden_runtime_packages_present(package_root)
        if name in {"llm", "rag"}
    )
    findings.extend(
        f"dependency:{name}"
        for name in forbidden_dependencies_declared(pyproject_path)
        if name
        in {
            "anthropic",
            "chromadb",
            "cursor",
            "cursor-sdk",
            "cursor_sdk",
            "langchain",
            "langgraph",
            "llama-index",
            "llama_index",
            "openai",
            "transformers",
        }
    )
    findings.extend(
        f"settings:{name}" for name in settings_ai_vendor_fields(settings_fields)
    )
    return tuple(findings)


def _collect_requirement_names(group: object, names: set[str]) -> None:
    if not isinstance(group, list):
        return
    for spec in group:
        if isinstance(spec, str):
            names.add(_requirement_name(spec))


def _requirement_name(spec: str) -> str:
    token = spec.strip()
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        token = token.split(separator, 1)[0]
    return token.strip().lower()
