# Research policy regression matrix — Phase 5.1

A **policy regression matrix** re-runs registered `ResearchPolicy`
implementations against small golden replay fixtures and compares
`policy_output_hash`, observation counts, and kind/severity histograms
with expected values.

It is **not** a financial backtest. It does **not** measure edge,
profitability, or skill.

Packages: `quant_platform.backtest.policy_regression`,
`policy_regression_types`, `policy_regression_artifacts`.

Fixtures: `tests/fixtures/policy_regression/`.

Related: [RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md),
[DATA_QUALITY_POLICIES.md](DATA_QUALITY_POLICIES.md),
[POLICY_OUTPUT_INTEGRITY.md](POLICY_OUTPUT_INTEGRITY.md),
[BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).

**No Alembic revision for this phase.** The matrix never touches
PostgreSQL.

## What it is for

- Catch accidental changes to descriptive policy outputs.
- Keep hashes comparable across commits.
- Document the smallest streams each policy is expected to observe.
- Give a local workflow (`scripts/run-policy-regression-matrix.py`) that
  tests can share.

Passing the matrix means **outputs are stable**, not that a strategy
exists.

## What it does not measure

The matrix must not compute or store:

- PnL, returns, drawdown, Sharpe, hit ratio
- exposure, portfolio value, cash, holdings
- signals, orders, fills, trades, positions

It only compares research observations.

## Golden fixtures

JSONL files under `tests/fixtures/policy_regression/`:

| File | Stream |
|------|--------|
| `simple_bars.jsonl` | started, one bar, finished |
| `sessions_and_bars.jsonl` | started, one session, one bar, finished |
| `corporate_actions.jsonl` | pre-known split plus one bar |
| `corrections.jsonl` | one restated bar |
| `gaps.jsonl` | two bars with a date gap |
| `unknown_event.jsonl` | one unrecognized kind among valid events |

Events use already-supported replay kinds. Unrecognized kinds stay as
strings so policies can emit `unknown_event` warnings. Fixtures contain
no secrets, no signals, and no orders.

## Declarative matrix

`tests/fixtures/policy_regression/matrix.json` lists cases for:

- `noop`
- `event_counting`
- `data_quality`
- `coverage`
- `corporate_action_audit`
- `correction_audit`

Each policy has at least a basic case, an explicit-config case, and a
warning case when the policy can emit `warning` observations.

Expected fields may be null during authoring. The committed golden file
stores hashes and counts so CI fails on drift.

## How to run

The runner does **not** open PostgreSQL and does **not** write files
unless `--output-dir` is set.

```bash
uv run python scripts/run-policy-regression-matrix.py --json

uv run python scripts/run-policy-regression-matrix.py \
  --matrix-path tests/fixtures/policy_regression/matrix.json \
  --output-dir /tmp/policy-regression
```

`APP_MODE` must be `research`. The script never prints `DATABASE_URL`.

The research release check also runs this matrix unless `--skip-regression`
is set. See [RESEARCH_RELEASE_CANDIDATE.md](../release/RESEARCH_RELEASE_CANDIDATE.md).

Without `--update-expected`, any error issue (missing fixture, unknown
policy, invalid config, hash/count drift, forbidden language, unexpected
failure) exits non-zero.

## Reviewing expected-hash changes

`--update-expected` writes `policy_regression_actuals.json` for humans.
It does **not** rewrite `matrix.json`.

```bash
uv run python scripts/run-policy-regression-matrix.py \
  --output-dir /tmp/policy-regression \
  --update-expected
```

Then:

1. Read `policy_regression_actuals.json`.
2. Confirm the observation kinds and messages still describe the stream
   (no buy/sell/hold wording, no PnL).
3. Copy hashes and counts into `matrix.json` by hand.
4. Re-run without `--update-expected` and commit the reviewed goldens.

Automatic golden updates would hide accidental policy changes. A human
must decide that a new hash is the intended research output.

`--update-expected` still fails on structural errors (missing fixture,
unknown policy, invalid config, forbidden language). Hash and count
drift is ignored only for the exit code so actuals can be written.

## Adding a safe ResearchPolicy

1. Implement the `ResearchPolicy` protocol. Do not name it Strategy or
   Signal. Do not emit orders, fills, or investment decisions.
2. Register the name in `policy_registry` / `ALLOWED_POLICY_NAMES`.
3. Add a small JSONL fixture if the policy needs a new stream shape.
4. Add matrix cases (basic, explicit config, warning if applicable).
5. Run with `--update-expected`, review actuals, copy expected hashes.
6. Add unit tests that the new cases pass and still contain no
   operational language.

No dynamic plugins. No vendor downloads.

## Artifacts

When `--output-dir` is set:

| File | Contents |
|------|----------|
| `policy_regression_report.json` | Pass/fail, issues, hashes |
| `policy_regression_actuals.json` | Current hashes/counts for review |

Paths in those files are relative fixture names. Report hashes exclude
wall-clock, absolute paths, and secrets.

## Why this is still not a strategy

A strategy would decide to buy, sell, hold, or size. The matrix only
asks: did this observer emit the same descriptive notes as last time?
There are still no signals, orders, fills, portfolio, or PnL.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold, target weights
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- dynamic external policy plugins
