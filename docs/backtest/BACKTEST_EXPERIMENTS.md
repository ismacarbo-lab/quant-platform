# Backtest experiments — Phase 4.4 / 4.5

A **backtest experiment** groups already-allowed dry-run backtest runs
under one reproducible research record.

It is **not** a strategy. It does **not** decide to buy or sell, emit
signals, size positions, or compute PnL.

Package: `quant_platform.backtest.experiments`, `experiment_types`,
`experiment_artifacts`, `experiment_catalog`, `experiment_integrity`.
Phase 4.5 adds `experiment_readiness`, `experiment_reports`, and
`experiment_report_artifacts`.

Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
Policy: [RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md).
Integrity: [BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md).
Experiment usability and research reports:
[BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md).

## What an experiment is

An experiment is a named cartesian product of:

- one or more ready `replay_id` values (duplicates dropped, order kept)
- one registered research policy (`noop` or `event_counting`)
- one or more JSON-safe `policy_configs` (empty list becomes `{}`)

Each pair `(replay_id, policy_config)` becomes a member dry-run written
under `runs/0001`, `runs/0002`, … The experiment then writes:

- `experiment_summary.json`
- `experiment_manifest.json`

Typical uses:

- same replay, several allowed configs
- several replay runs, same safe policy
- NoOp vs `event_counting` as **two** experiments, then compare them
- a hash and usability summary across members

## Why it is not a strategy

A strategy would choose holdings. This registry only **groups** dry-runs
that the existing engine already permits. Member results stay counts,
hashes, and observations. There is still no signal, order, fill,
portfolio, or return series.

Unknown policy names are rejected. External plugins are not loaded.

## Hashes

| Hash | Meaning |
|------|---------|
| `experiment_hash` | Experiment name + sorted replay ids + policy name + canonical policy configs + member stream/backtest hashes + usable/error/warning counts. No wall-clock, no UUID, no absolute paths, no secrets. |
| `manifest_hash` | Canonical export of this experiment folder, **including** `created_at` and `experiment_id`. |

Compare **logic** with `experiment_hash`. Compare **this export** with
`manifest_hash`. Two runs of the same definition can share
`experiment_hash` and still differ in `manifest_hash` if `created_at` or
`experiment_id` differs (`same_result`).

`--deterministic-id` derives `experiment_id` (and member `backtest_id`
values) from hashes. The default experiment id is UUID4 (not part of
`experiment_hash`).

Format: `sha256:<64 hex>`.

## Local artifacts

Written under `--output-dir`:

- `experiment_summary.json`
- `experiment_manifest.json`
- `runs/NNNN/` — one existing dry-run backtest folder per member
  (`summary.json`, `manifest.json`, `policy_output.json`)

Not written: copies of `events.jsonl`, replay artifacts, datasets, or
absolute paths. Manifest artifact paths are relative
(`experiment_summary.json`, `runs/0001/manifest.json`).

Phase 4.5 may also write `experiment_research_report.json` and
`experiment_usability.json`. Those files are **not** in the default
manifest list, so older experiment folders stay valid. If they **are**
listed, a missing file is an integrity error. Writing them does not
rewrite `experiment_manifest.json`.

PostgreSQL does **not** store those files. It stores metadata only.

## PostgreSQL catalog

Table: `backtest_experiments`. Alembic revision `0009_backtest_experiments`.

Columns include `experiment_id`, `experiment_name`, `experiment_hash`,
`manifest_hash`, `policy_name`, package/git stamps, member/usable/error/
warning counts, and JSONB `request` / `summary` / `artifacts`.

- upsert by `experiment_id`
- unique `manifest_hash`
- conflict if the same `manifest_hash` is owned by another
  `experiment_id`
- no event rows, datasets, orders, fills, positions, or PnL

`--usable-only` keeps rows where `usable_count == member_count` and
`error_count == 0`. That is a catalog summary, not an edge, and not the
Phase 4.5 local usability gate (see
[BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md)).

## Run, register, compare

Requires ready replay runs on disk:

```bash
uv run python scripts/run-backtest-experiment.py \
  --experiment-name noop-grid \
  --replay-id <replay_id_a> \
  --replay-id <replay_id_b> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name noop \
  --deterministic-id \
  --json
```

Register metadata (`--output-dir` is required; `--register` writes the
catalog after local artifacts):

```bash
uv run python scripts/run-backtest-experiment.py \
  --experiment-name noop-grid \
  --replay-id <replay_id_a> \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name event_counting \
  --policy-config-json '{"emit_observations": true}' \
  --register \
  --deterministic-id \
  --notes "event counting grid" \
  --json

uv run python scripts/list-backtest-experiments.py --usable-only --json
uv run python scripts/list-backtest-experiments.py \
  --experiment-name noop-grid --policy-name noop

uv run python scripts/check-backtest-experiment-usability.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment \
  --json
uv run python scripts/report-backtest-experiment.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment \
  --output-dir /tmp/fixt-experiment \
  --json

uv run python scripts/verify-backtest-experiment.py \
  --experiment-dir /tmp/fixt-experiment

uv run python scripts/compare-backtest-experiments.py \
  --left <experiment_id_a> \
  --right <experiment_id_b> \
  --json
```

Python:

```python
from quant_platform.backtest import (
    BacktestExperimentRequest,
    compare_backtest_experiments,
    run_backtest_experiment,
)

request = BacktestExperimentRequest(
    experiment_name="noop-grid",
    replay_ids=(replay_id,),
    policy_name="noop",
    deterministic_ids=True,
)
result = run_backtest_experiment(
    session, request, replay_base_dir, output_dir, register=True
)
```

Compare verdicts:

| Verdict | Meaning |
|---------|---------|
| `identical` | Same `manifest_hash`. |
| `same_result` | Same `experiment_hash`, different `manifest_hash`. |
| `different` | Different `experiment_hash`. |

Scripts do not print `DATABASE_URL`. They do not trade.

## Integrity

`verify_backtest_experiment_artifacts` checks that the experiment
manifest and summary exist, paths are relative, hashes recompute,
counts match members, member folders cite the listed `backtest_id`
values, and metadata has no secret markers or investment-decision
wording. Listed report files, when present, are scanned the same way.
Unlisted report files are ignored so Phase 4.4 folders still pass.
The check does not copy events or invent PnL.

`evaluate_backtest_experiment_usability` is a separate gate: every
member must be a usable backtest result, artifacts must verify, and
there must be no trading constructs. See
[BACKTEST_EXPERIMENT_USABILITY.md](BACKTEST_EXPERIMENT_USABILITY.md).

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
- dynamic external policy plugins
