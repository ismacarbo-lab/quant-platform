"""Write local research evidence-bundle artifacts. No cloud, no secrets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from quant_platform.release.evidence_types import (
    EVIDENCE_MANIFEST_NAME,
    EVIDENCE_SUMMARY_NAME,
    RELEASE_STATUS_NAME,
    EvidenceBundleError,
    ResearchEvidenceBundleResult,
)
from quant_platform.research.snapshots import manifest_contains_secrets
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_LOCAL_PATH_KEYS = frozenset({"run_root", "experiment_root", "output_dir"})


def write_research_evidence_artifacts(
    result: ResearchEvidenceBundleResult,
    *,
    release_status: Mapping[str, object] | None = None,
) -> Path:
    """Write evidence_manifest.json, evidence_summary.json, release_status.json.

    Manifest and summary include fixture_data_mode and fixture_reuse counts
    when the builder set them. Paths stay relative; no secrets.
    """
    target = Path(result.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    manifest_payload = result.manifest.as_mapping()
    summary_payload = result.summary_mapping()
    status_payload = without_local_paths(
        release_status if release_status is not None else result.release_status or {}
    )
    _write_json(manifest_payload, target / EVIDENCE_MANIFEST_NAME)
    _write_json(summary_payload, target / EVIDENCE_SUMMARY_NAME)
    _write_json(status_payload, target / RELEASE_STATUS_NAME)
    return target


def write_evidence_json(payload: Mapping[str, object], path: Path | str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _without_local_paths(dict(payload))
    if not isinstance(cleaned, dict):
        raise EvidenceBundleError(
            "evidence JSON payload must be an object",
            code="invalid_json",
        )
    _write_json(cleaned, destination)
    return destination


def without_local_paths(payload: Mapping[str, object]) -> dict[str, object]:
    cleaned = _without_local_paths(dict(payload))
    if not isinstance(cleaned, dict):
        raise EvidenceBundleError(
            "evidence JSON payload must be an object",
            code="invalid_json",
        )
    return cleaned


def _without_local_paths(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_local_paths(item)
            for key, item in value.items()
            if key not in _LOCAL_PATH_KEYS
        }
    if isinstance(value, list):
        return [_without_local_paths(item) for item in value]
    if (
        isinstance(value, str)
        and artifact_path_is_unsafe(value)
        and _looks_like_path(value)
    ):
        return None
    return value


def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    candidate = Path(stripped)
    return candidate.is_absolute() or ".." in candidate.parts


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise EvidenceBundleError(
            "evidence artifacts must not contain secrets",
            code="secret_like_value",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
