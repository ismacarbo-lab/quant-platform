"""Local backtest artifacts. Summary and manifest only; no event copies."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from quant_platform import __version__
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.types import (
    MANIFEST_ARTIFACT_NAME,
    SUMMARY_ARTIFACT_NAME,
    BacktestManifest,
    BacktestResult,
    default_backtest_artifacts,
    optional_backtest_notes,
)
from quant_platform.core.time import utc_now
from quant_platform.research.snapshots import (
    get_git_commit,
    hash_manifest_mapping,
    manifest_contains_secrets,
)


def write_backtest_artifacts(
    result: BacktestResult,
    output_dir: Path | str,
    *,
    created_at: datetime | None = None,
    git_commit: str | None = None,
    resolve_git: bool = True,
) -> BacktestResult:
    """Write summary.json and manifest.json. Does not copy replay events."""
    stamp = created_at if created_at is not None else utc_now()
    if stamp.tzinfo is None:
        raise BacktestError(
            "created_at must be timezone-aware UTC",
            code=BacktestErrorCode.NAIVE_TIMESTAMP,
        )
    stamp = stamp.astimezone(UTC)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    summary_path = target / SUMMARY_ARTIFACT_NAME
    manifest_path = target / MANIFEST_ARTIFACT_NAME

    resolved_commit = git_commit
    if resolve_git and resolved_commit is None:
        resolved_commit = get_git_commit()
    artifacts = default_backtest_artifacts()
    draft = BacktestManifest(
        backtest_id=result.summary.backtest_id,
        created_at=stamp,
        package_version=__version__,
        git_commit=resolved_commit,
        replay_id=result.summary.replay_id,
        stream_hash=result.summary.stream_hash,
        backtest_hash=result.summary.backtest_hash,
        policy_name=result.summary.policy_name,
        request=result.request.as_mapping(),
        summary=result.summary.as_mapping(),
        artifacts=artifacts,
        notes=optional_backtest_notes(result.request.notes),
        manifest_hash="",
    )
    blob = draft.as_mapping(include_manifest_hash=False)
    _reject_secrets(blob)
    manifest_hash = hash_manifest_mapping(blob)
    manifest = replace(draft, manifest_hash=manifest_hash)
    _write_json(result.summary.as_mapping(), summary_path)
    _write_json(manifest.as_mapping(), manifest_path)
    return replace(result, manifest=manifest, output_dir=target)


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise BacktestError(
            "backtest output must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _reject_secrets(payload: Mapping[str, object]) -> None:
    if manifest_contains_secrets(payload):
        raise BacktestError(
            "backtest metadata must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
