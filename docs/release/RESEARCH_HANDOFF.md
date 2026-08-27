# Research-mode technical handoff — Phase 5.4

This is the freeze handoff for `quant_platform` at `/home/isma/invest`.
Research mode is complete for this stage. The product is **not** a
trading system.

Related: [FINAL_RESEARCH_CHECKLIST.md](FINAL_RESEARCH_CHECKLIST.md),
[CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[RISK_REGISTER.md](RISK_REGISTER.md),
[COMMANDS.md](COMMANDS.md),
[MINIMAL_REPRODUCIBLE_EXAMPLE.md](MINIMAL_REPRODUCIBLE_EXAMPLE.md),
[RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md),
[REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

## Architecture now

`quant_platform` is a modular monolith (Python 3.13, `uv`, PostgreSQL,
SQLAlchemy 2, Alembic). `APP_MODE` accepts only `research`. FastAPI
exposes `GET /health` only.

```
src/quant_platform/
  core/         settings, UTC clock, ids
  data/         local CSV ingest, PIT bars, instruments, calendars, CA store
  research/     datasets, quality, snapshots, catalog, integrity
  simulation/   replay, audit, run catalog, readiness
  backtest/     dry-run engine, research policies, experiments, regression
  release/      status, checks, evidence bundle
  storage/      PostgreSQL engine/session
  monitoring/   structured logs
  api/          GET /health
```

There are no `strategies`, `signals`, `orders`, `portfolio`, `broker`,
or AI-client packages.

## End-to-end pipeline

Local fixtures only. No vendors. No internet.

1. Load CSV (exchanges, calendars, sessions, corporate actions, daily bars).
2. Ingest into bronze (`raw_ingestion_records`) and silver (`daily_bars`).
3. Query a PIT dataset (`as_of` required).
4. Build a dataset quality report.
5. Write a hashed snapshot and register it in the catalog.
6. Replay the dataset; audit; register the replay run.
7. Gate replay readiness.
8. Dry-run a registered `ResearchPolicy` (default `data_quality`).
9. Gate backtest usability.
10. Register a minimal experiment; gate experiment usability.
11. Write an aggregated research report (counts and hashes).
12. Run research release status / checks.
13. Pack the above into a local evidence bundle and verify it.

That path is coordinated by
`build_research_evidence_bundle` and
`scripts/build-research-evidence-bundle.py`.

## Main commands

Canonical list: [COMMANDS.md](COMMANDS.md).

Everyday:

```bash
make quality
make policy-regression
make research-release-check
make research-status
```

With PostgreSQL:

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run python scripts/check-db.py
uv run pytest -m postgres
make research-evidence-bundle
make verify-research-evidence-bundle
```

Do not print `DATABASE_URL`. Copy `.env.example` to `.env` for local
overrides. Values there are fictional placeholders.

## Database and Alembic

PostgreSQL is mandatory. SQLite is rejected.

Local Compose publishes `127.0.0.1:5434` because host 5432 and 5433 are
already taken on this machine. CI uses `127.0.0.1:5432` inside the
runner.

Expected head: `0009_backtest_experiments`.

Public tables are research metadata only (ingestion, instruments,
calendars, corporate actions, snapshots, replay runs, backtest runs,
experiments). There are no `orders`, `fills`, `trades`, `signals`,
`strategies`, `positions`, or `portfolio` tables.

## Fixtures and artifacts

| Location | Role |
|----------|------|
| `tests/fixtures/e2e_research_bundle/` | Small fictional CSV pack for the evidence bundle |
| `tests/fixtures/policy_regression/` | Golden JSONL streams and `matrix.json` |
| `tests/fixtures/` (other CSV) | Sample bars, calendars, sessions, CA |
| local `--output-dir` / `--base-dir` | Snapshot, replay, backtest, experiment, bundle files |

Artifact paths in manifests are **relative**. Hashes are `sha256:<64 hex>`.
Do not version absolute directories or wall-clock inside stable hashes.

## Policy registry

Built-in names only (no plugins):

| Name | Role |
|------|------|
| `noop` | Counts only |
| `event_counting` | Event-kind counts |
| `data_quality` | Stream quality observations (bundle default) |
| `coverage` | Coverage / gap notes |
| `corporate_action_audit` | Stored CA facts |
| `correction_audit` | PIT correction facts |

They emit `ResearchObservation` values. They do not emit signals, orders,
or PnL.

## Release checks

- `scripts/research-status.py` — lightweight status (no PostgreSQL ping).
- `scripts/research-release-check.py` — app mode, Alembic scripts,
  architecture, optional DB, Compose, policy regression.

`final_freeze_ready` is a docs + Alembic-script signal. It is **not** a
trading go-live.

## Evidence bundle

See [RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md).

A passing bundle proves the research pipeline ran on local fixtures. It
does **not** prove an edge, a strategy, or profitability.

## Explicitly out of scope

- real strategies, signals, alpha models, buy/sell/hold, target weights
- orders, fills, trades, positions, portfolio, cash
- PnL, returns, drawdown, Sharpe, hit ratio, exposure
- brokers, execution, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- market-data vendor clients, automatic downloads
- cloud object storage, HTTP routes beyond `GET /health`
- `AI_VENTURE_OS_PROMPTS/` (separate product; do not mix)

## How to resume later

1. Work only in `/home/isma/invest`. Do not use the accidental git at
   `/home/isma`.
2. Read [ADR 0003](../adr/0003-research-mode-freeze.md) before adding
   capabilities.
3. Keep `APP_MODE=research` until a later ADR changes it.
4. Re-run [FINAL_RESEARCH_CHECKLIST.md](FINAL_RESEARCH_CHECKLIST.md).
5. New work needs a new phase spec. Do not silently add brokers, paper,
   live, PnL, or an AI runtime.

Allowed future candidates (still not implemented): richer local datasets,
stronger PIT/CA research notes, and only then a strategy **interface**
without brokers. Each requires an explicit ADR.
