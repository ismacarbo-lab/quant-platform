# Research-mode release candidate — Phase 5.2

This phase hardens `quant_platform` as a **research-only release
candidate**. It does **not** add strategies, signals, orders, portfolio,
PnL, brokers, or an AI runtime.

Package: `quant_platform.release`.

Scripts: `scripts/research-status.py`,
`scripts/research-release-check.py`.

Related: [POLICY_REGRESSION_MATRIX.md](../backtest/POLICY_REGRESSION_MATRIX.md),
[DATA_QUALITY_POLICIES.md](../backtest/DATA_QUALITY_POLICIES.md),
[DEVELOPER_WORKFLOW.md](../development/DEVELOPER_WORKFLOW.md),
[RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md),
[RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[AI_USAGE_BOUNDARY.md](../ai/AI_USAGE_BOUNDARY.md).

Phase 5.2 added no schema. Expected Alembic head after Phase 6.2 is
`0010_normalized_dataset_catalog`.

## What is ready

The research stack can:

- ingest local PIT daily bars into PostgreSQL
- keep bronze/silver, instrument master, calendars, stored corporate actions
- build `as_of` datasets, quality reports, hashed snapshots, and a catalog
- replay a dataset, audit the stream, and register replay runs
- gate replay readiness for a dry-run backtest
- observe that stream with registered `ResearchPolicy` implementations
- hash and verify policy output, backtest artifacts, and experiments
- pin policy outputs with a golden regression matrix
- register derived normalized-dataset metadata (hashes and counts only)

`APP_MODE` still accepts only `research`. `GET /health` is still the only
HTTP route.

## What is not ready

This is **not** a production trading system. It does **not** include:

- real strategies, signals, or alpha models
- buy/sell/hold decisions or target weights
- orders, fills, trades, positions, portfolio, cash
- PnL, returns, drawdown, Sharpe, hit ratio, exposure
- brokers, execution, paper trading, live trading
- a risk engine, optimizer, or ML stack
- OpenAI, Anthropic, LangChain, RAG, or any LLM runtime
- market-data vendor clients or automatic downloads
- cloud object storage

Passing release checks means the research foundation is intact. It does
**not** mean a strategy exists or that results are profitable.

The [research evidence bundle](RESEARCH_EVIDENCE_BUNDLE.md) is a separate
**manual** check: it runs the local fixture → ingest → snapshot → replay
→ dry-run → experiment path and writes a hashed pack. It is not part of
`make quality`.

## How to run the release check

Lightweight status (no PostgreSQL, no policy matrix):

```bash
uv run python scripts/research-status.py
uv run python scripts/research-status.py --json
make research-status
```

Full local release check:

```bash
uv run python scripts/research-release-check.py
uv run python scripts/research-release-check.py --json
make research-release-check
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--skip-db` | Do not ping PostgreSQL (CI quality job). |
| `--require-db` | Fail if PostgreSQL is unreachable. |
| `--skip-compose` | Do not run `docker compose config`. |
| `--skip-regression` | Do not run the policy regression matrix. |
| `--skip-normalization-regression` | Do not run the normalization regression matrix. |
| `--json` | Print the status report. |

The checker never prints `DATABASE_URL` or passwords. It does not
download data, call vendors, or trade.

Makefile companions:

```bash
make policy-regression
make normalization-regression
make architecture-check
make quality
```

## Manual evidence bundle

Local PostgreSQL required. Not part of `make quality`:

```bash
make research-evidence-bundle
make verify-research-evidence-bundle
```

See [RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md).

## How to interpret the report

The JSON object is `kind=research_release_status`. Important fields:

| Field | Meaning |
|-------|---------|
| `ok` | No error-level checks. Warnings may still appear. |
| `app_mode` | Must be `research`. |
| `alembic_head_expected` | Script head this candidate pins (`0010_normalized_dataset_catalog`). |
| `registered_policy_count` | Built-in research policies only. |
| `regression_case_count` | Golden matrix cases. |
| `trading_constructs_detected` | Must be false. |
| `ai_runtime_detected` | Must be false. |
| `capabilities.enabled` / `.disabled` | What this candidate will and will not do. |
| `risks` | Known gaps; not runtime failures. |
| `report_hash` | SHA-256 of the report body. No wall-clock. |

`ok=true` is a research integrity signal. It is not a trading go-live.

## How to review policy-regression drift

If `policy_regression` fails:

1. Run `make policy-regression` or
   `uv run python scripts/run-policy-regression-matrix.py --json`.
2. If the change is intentional, write actuals with `--update-expected`
   (this **does not** rewrite `matrix.json`).
3. Review observation kinds and messages. Reject buy/sell/hold wording.
4. Copy hashes and counts into `matrix.json` by hand.
5. Re-run the matrix and the release check.

See [POLICY_REGRESSION_MATRIX.md](../backtest/POLICY_REGRESSION_MATRIX.md).

## How to review normalization-regression drift

If `normalization_regression` fails:

1. Run `make normalization-regression` or
   `uv run python scripts/run-normalization-regression.py --json`.
2. If the change is intentional, write actuals with `--update-expected`
   (this **does not** rewrite `expected.json`).
3. Review factors, warning codes, and bar counts. Reject returns/PnL.
4. Copy hashes and counts into that case's `expected.json` by hand.
5. Re-run the matrix and the release check.

See [NORMALIZATION_REGRESSION_MATRIX.md](../research/NORMALIZATION_REGRESSION_MATRIX.md).

## How to confirm there is no trading or AI runtime

Release check plus architecture tests assert:

- no `strategies` / `signals` / `orders` / `portfolio` / `broker` packages
- no paper/live `APP_MODE`
- no OpenAI, Anthropic, LangChain, RAG, or Cursor SDK dependencies
- no finance vendor clients in `pyproject.toml`
- no SQLite fallback
- no trading tables (`orders`, `fills`, `trades`, `signals`, `strategies`,
  `positions`)

```bash
make architecture-check
uv run python scripts/check-db.py   # trading_tables=none when DB is up
```

## Recommended next steps

Keep research-only until a later, explicit phase decides otherwise:

1. Better local data coverage and documentation of known dataset limits.
2. Stronger PIT/corporate-action research notes (still not applied as a
   strategy).
3. Only then consider a strategy interface — still without brokers.

Do not skip ahead to paper trading, live trading, or an LLM runtime.

## Pending risks

- No market-data vendors; local CSV only.
- No advanced price normalization; corporate actions are stored, not applied.
- No portfolio or PnL.
- No strategy framework.
- No execution.
- Policy regression goldens require human review; the runner will not
  rewrite them.
- PostgreSQL is mandatory for catalogued runs; SQLite is rejected.
- Replay/backtest artifacts need a local `--base-dir` / `--output-dir`.
- Compose publishes `127.0.0.1:5434` on this machine because 5432/5433
  are already taken.

## What still does not exist

- real strategies, signals, indicators-as-signals, alpha models
- buy/sell/hold, target weights
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
- dynamic external policy plugins
