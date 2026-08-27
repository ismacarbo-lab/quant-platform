# Research evidence bundle — Phase 5.3

This phase builds a **local, auditable evidence pack** that walks the
research stack from small fixtures through ingest, quality, snapshot,
catalog, replay, readiness, a dry-run `ResearchPolicy`, backtest
usability, a minimal experiment, experiment usability, an aggregated
research report, and the release status report.

It demonstrates that research mode **works end-to-end and is
reproducible**. It does **not** demonstrate a strategy, edge, or
profitability.

Package: `quant_platform.release.evidence_bundle`.

Scripts: `scripts/build-research-evidence-bundle.py`,
`scripts/verify-research-evidence-bundle.py`.

Related: [RESEARCH_RELEASE_CANDIDATE.md](RESEARCH_RELEASE_CANDIDATE.md),
[DATA_QUALITY_POLICIES.md](../backtest/DATA_QUALITY_POLICIES.md),
[BACKTEST_EXPERIMENT_USABILITY.md](../backtest/BACKTEST_EXPERIMENT_USABILITY.md),
[DEVELOPER_WORKFLOW.md](../development/DEVELOPER_WORKFLOW.md),
[RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

## What the bundle demonstrates

A successful bundle shows that, on local PostgreSQL and local fixtures:

1. `APP_MODE=research` and Alembic are at the pinned head
2. small CSV fixtures ingest as PIT daily bars
3. a dataset quality report can be built
4. a hashed dataset snapshot can be written and catalogued
5. a replay run can be written, registered, and pass readiness
6. a registered research policy (`data_quality` by default) can dry-run
7. that dry-run passes backtest usability
8. a one-member experiment can be registered and pass experiment usability
9. an aggregated research report can be hashed
10. the research release status report is `ok`

`ok=true` means the pipeline produced intact research evidence. It does
not mean anyone should invest.

## What it does not demonstrate

The bundle is **not**:

- a strategy, signal, or alpha model
- buy/sell/hold advice or target weights
- orders, fills, trades, positions, or a portfolio
- PnL, returns, drawdown, Sharpe, hit ratio, or exposure
- paper trading or live trading
- a broker, execution engine, or risk engine
- an AI/LLM runtime
- a vendor download or cloud object store

Corporate actions in the fixtures are **stored**, not applied to OHLCV.

## How to build it

PostgreSQL must be reachable. `APP_MODE` must be `research`. Alembic must
be at `0009_backtest_experiments`.

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run python scripts/check-db.py

uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --json

make research-evidence-bundle
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--fixture-dir` | Local CSV fixtures (required). |
| `--output-dir` | Bundle directory (required). |
| `--policy-name` | Registered research policy. Default: `data_quality`. |
| `--policy-config-json` | Optional JSON object for that policy. |
| `--deterministic-id` | Derive replay/backtest/experiment/bundle ids from hashes. |
| `--json` | Print the evidence summary. |

The builder fails if `APP_MODE` is not research, Alembic is not at the
expected head, the policy is not registered, the release check has
errors, or any coordinated step errors. It does not print `DATABASE_URL`.

The builder reuses existing APIs. It does not add a second ingest, replay,
or backtest engine.

Release status inside the bundle skips Compose and the policy regression
matrix so the run stays local and reasonably fast. Run
`make research-release-check` separately when you want the full candidate
check.

## How to verify it

```bash
uv run python scripts/verify-research-evidence-bundle.py \
  --bundle-dir /tmp/research-evidence-bundle \
  --json

make verify-research-evidence-bundle
```

Verification is read-only. It checks that the three top-level JSON files
exist, declared paths are relative and stay inside the bundle, hashes are
`sha256:<64 hex>`, step counts match, secret-like values are absent, and
the text does not use investment-decision wording or forbidden
performance metrics.

## Artifacts

The bundle directory contains:

| Path | Role |
|------|------|
| `evidence_manifest.json` | Bundle ids, hashes, steps, relative artifacts |
| `evidence_summary.json` | Short form of the same evidence |
| `release_status.json` | Research release status report |
| `dataset_snapshot/` | Snapshot CSV, quality JSON, snapshot manifest |
| `replay_run/` | `events.jsonl`, audit, summary, replay manifest |
| `backtest_run/` | Dry-run summary, manifest, policy output |
| `experiment/` | Experiment summary/manifest plus member runs |
| `reports/` | Quality, readiness, usability, and research report JSON |

Event rows live in `replay_run/events.jsonl`. The bundle manifest does
not copy them.

Paths in the manifest are **relative**. Absolute directories are not
versioned.

## How to interpret hashes

`bundle_hash` is `sha256:` plus 64 hex characters. It covers:

- snapshot hash (`content_hash`)
- stream hash
- backtest hash
- experiment hash
- research report hash
- release report hash
- step names and statuses
- `ok` / `error_count`
- package version, `app_mode`, Alembic head

It does **not** cover:

- `created_at`
- a random `bundle_id`
- `git_commit`
- absolute paths
- wall-clock
- secrets

Two successful runs with the same fixtures and `--deterministic-id` can
share the same `bundle_hash` even when `bundle_id` and `created_at`
differ. A change to `stream_hash` changes `bundle_hash`.

## Why there is no trading, PnL, or returns

This phase answers: did the research stack run, and can we prove it from
local files and PostgreSQL metadata?

A strategy would decide what to do. PnL would score an economic outcome.
Neither belongs in a research-evidence pack. The default policy
(`data_quality`) only emits observations and counters.

## What remains for later phases

- richer local datasets (still not vendor downloads)
- more PIT / corporate-action research notes (still not applied as a
  strategy)
- only later, an explicit strategy interface — still without brokers

Do not skip ahead to paper trading, live trading, or an LLM runtime.

This Makefile target is a **manual** release check. It is not part of
`make quality`.
