# Backtest experiment usability — Phase 4.5 / 5.0

A registered dry-run **experiment** can be intact as a catalog row and
still be unfit as research evidence (missing member artifacts, a member
that fails the backtest usability gate, operative wording, and so on).

This phase answers: is the **whole experiment** usable as research
evidence, and what did its members observe in aggregate?

It is **not** a strategy check. It does **not** decide to buy or sell,
emit signals, size positions, or compute PnL.

Packages:

- `quant_platform.backtest.experiment_readiness`
- `quant_platform.backtest.experiment_readiness_types`
- `quant_platform.backtest.experiment_reports`
- `quant_platform.backtest.experiment_report_artifacts`

Experiments: [BACKTEST_EXPERIMENTS.md](BACKTEST_EXPERIMENTS.md).
Member usability: [BACKTEST_INTEGRITY.md](BACKTEST_INTEGRITY.md).
Observation reports: [POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md).
Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).

Data-quality policies: [DATA_QUALITY_POLICIES.md](DATA_QUALITY_POLICIES.md).

End-to-end research evidence: [RESEARCH_EVIDENCE_BUNDLE.md](../release/RESEARCH_EVIDENCE_BUNDLE.md).

**No Alembic revision for this phase.** Catalog table
`backtest_experiments` already exists from `0009_backtest_experiments`.

## What `experiment_usable` means

`evaluate_backtest_experiment_usability(session, experiment_id, base_dir)`
returns `experiment_usable=True` only when **all** of the following hold:

- `APP_MODE=research`
- the `experiment_id` is registered
- the local experiment folder can be resolved under `--base-dir`
- `verify_backtest_experiment_artifacts` has **no errors**
- `experiment_hash` and `manifest_hash` are valid `sha256:<64 hex>` and
  match recomputation
- `member_count > 0`
- every declared member exists on disk and in the backtest catalog
- every member has `usable_result=True` (the Phase 4.1/4.3 backtest
  result gate)
- no member `policy_output.json` fails policy-output integrity
- no investment-decision wording in experiment or member metadata
- `detect_trading_constructs()` is empty
- the usability report itself has `error_count == 0`

`--base-dir` may be the experiment folder, or a parent of several
experiment folders. Matching uses `experiment_manifest.json` →
`experiment_id`.

Member folders are evaluated at `runs/0001`, `runs/0002`, … (not at the
experiment root). The experiment root has `experiment_manifest.json`,
not a backtest `manifest.json`.

## What `experiment_usable` does not mean

Usable means the experiment is **intact, reproducible, and audited**.
It does **not** mean:

- edge, alpha, or a profitable idea
- a recommendation to invest
- PnL, returns, drawdown, Sharpe, hit ratio, or exposure
- that a strategy, signal, or portfolio exists

`--usable-only` on `list-backtest-experiments.py` is a **catalog
summary** (`usable_count == member_count` and `error_count == 0`). That
is not the same as this gate, which re-reads local artifacts and each
member's backtest usability report.

Compare-experiment verdict `same_result` (same `experiment_hash`,
different `manifest_hash`) is also not this gate.

## Issue codes

Severity: `info`, `warning`, `error`. Error codes include:

| Code | Typical cause |
|------|----------------|
| `experiment_missing` | `experiment_id` is not in the catalog |
| `experiment_artifact_missing` | folder, listed file, or summary/manifest missing |
| `experiment_hash_mismatch` | stored hash ≠ recomputation |
| `member_backtest_missing` | member folder or nested `backtest_id` missing |
| `member_not_usable` | member failed `evaluate_backtest_result_usability` |
| `member_artifact_invalid` | member artifact verification failed |
| `policy_output_invalid` | member `policy_output.json` is not valid evidence |
| `forbidden_operational_language` | investment-decision wording |
| `inconsistent_policy_name` | member policy ≠ experiment policy |
| `inconsistent_member_count` | catalog count ≠ declared members |
| `construct_detected` | forbidden trading construct in the package |
| `no_usable_members` | empty experiment or every member unusable |
| `app_mode_not_research` | `APP_MODE` is not `research` |
| `invalid_hash` | hash is not `sha256:<64 hex>` |

## How observation reports are aggregated

`load_member_observation_reports` builds one observation report per
member folder that still has a readable `policy_output.json`.

`aggregate_experiment_observations` sums:

- observation counts by kind and by severity
- unknown events, corrections, corporate actions, sessions
- warning / error totals

It does not concatenate event streams, copy `events.jsonl`, or invent
PnL. Members whose policy output is missing contribute no observations.

## Research report

`build_backtest_experiment_research_report` / 
`build_research_report_from_catalog` produce a counts-and-hashes
summary:

- `experiment_id`, `experiment_name`, `policy_name`
- `member_count`, `usable_count`, `warning_count`, `error_count`
- policy configs, replay ids, stream hashes, backtest hashes
- observation aggregates (kinds, severities, unknown/correction/CA/session)
- a comparison summary (distinct replay / stream / backtest-hash /
  config counts; whether those hashes match across members)
- per-member hashes and usability flags
- `experiment_hash` and `report_hash`

An empty member list raises `BacktestError` (`catalog_invalid`). The
builder does **not** require `experiment_usable=True`; you can still
report an unusable experiment.

### Forbidden metrics

The report must not compute or store:

- PnL, returns, drawdown, Sharpe, hit ratio, exposure
- portfolio, positions, trades, orders, fills

Those words are also rejected as whole tokens in serialized JSON.

## `report_hash`

`hash_backtest_experiment_report` is SHA-256 of canonical JSON:

- experiment id, name, policy, `experiment_hash`
- member/usable/warning/error counts
- sorted policy configs, replay ids, stream hashes, backtest hashes
- observation aggregate and member comparison
- members sorted by replay id, backtest hash, backtest id

It excludes `report_hash` itself, wall-clock, absolute paths, and
secrets. Format: `sha256:<64 hex>`.

Same experiment definition + same members + same observation aggregates
= same `report_hash`. Changing a member `backtest_hash` changes it.

## Local report artifacts

`write_backtest_experiment_report_artifacts` writes relative paths only:

- `experiment_research_report.json` (always)
- `experiment_usability.json` (optional; `experiment_root` stripped)

It does **not** rewrite `experiment_manifest.json` (that would change
`manifest_hash`). It does not copy replay events or member backtest
folders.

These files are **not** in `default_experiment_artifacts()`. Phase 4.4
folders without a report still pass integrity. If a report **is listed**
in the manifest, a missing file is an integrity **error**. When a listed
report file exists, integrity scans it for secrets and operative wording.

## CLI

```bash
uv run python scripts/check-backtest-experiment-usability.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment \
  --json

uv run python scripts/report-backtest-experiment.py \
  --experiment-id <experiment_id> \
  --base-dir /tmp/fixt-experiment \
  --output-dir /tmp/fixt-experiment \
  --json

uv run python scripts/list-backtest-experiments.py --usable-only
uv run python scripts/verify-backtest-experiment.py \
  --experiment-dir /tmp/fixt-experiment
```

`check-backtest-experiment-usability.py` prints `experiment_usable`,
`member_count`, `usable_count`, `error_count`, `warning_count`, and
issues. Exit status `1` if the experiment is not usable.

`report-backtest-experiment.py` prints the aggregate summary and, with
`--output-dir`, writes the JSON artifacts. It does not trade.

Scripts do not print `DATABASE_URL`.

## Why there is still no PnL or portfolio

Experiment research reports sum observation counts, including Phase 5.0
kinds such as `data_quality_summary` and `coverage_gap`. They still do
not compute PnL.

An experiment is a **group of dry-runs**. Member policies still only
count events and emit observations. Aggregating those counts is not a
portfolio, not a return series, and not an investment recommendation.
PnL would be a later product, behind this gate.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold, target weights
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
- dynamic external policy plugins

A passing experiment usability gate is one input to the
[research evidence bundle](../release/RESEARCH_EVIDENCE_BUNDLE.md). That
bundle still does not compute PnL or returns.
