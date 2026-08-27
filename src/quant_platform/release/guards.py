"""Repo-local architecture guards. Scans this tree only; no network."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from quant_platform.release.constants import (
    FORBIDDEN_DEPENDENCY_NAMES,
    FORBIDDEN_RUNTIME_PACKAGES,
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
