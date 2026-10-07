# quant_platform

Quantitative platform with a point-in-time market data store, research
tooling, strategy backtests and **paper trading** with fictional money.
Real market data comes from Yahoo Finance (`yfinance`, free, no account).
There is **no real money** and **no live trading**: `APP_MODE=live` is
rejected, no broker SDK is installed, and no credentials live in the repo.
Pivot decision: [docs/adr/0005-paper-trading-pivot.md](docs/adr/0005-paper-trading-pivot.md).

The research layer frozen at `v0.1.0-research` … `v0.6.0-research-evidence-intake`
(PIT daily bars, bronze/silver, corporate actions, normalization, evidence
bundles, vendor-agnostic contracts) is still here and its regression
matrices still run.

Handoff: [docs/release/RESEARCH_HANDOFF.md](docs/release/RESEARCH_HANDOFF.md).
Evidence bundle: [docs/release/RESEARCH_EVIDENCE_BUNDLE.md](docs/release/RESEARCH_EVIDENCE_BUNDLE.md).
Capabilities: [docs/release/CAPABILITY_MATRIX.md](docs/release/CAPABILITY_MATRIX.md).
Paper trading: [docs/trading/PAPER_TRADING.md](docs/trading/PAPER_TRADING.md).
Strategies and backtests: [docs/trading/STRATEGIES_AND_BACKTESTS.md](docs/trading/STRATEGIES_AND_BACKTESTS.md).
Market data: [docs/trading/MARKET_DATA.md](docs/trading/MARKET_DATA.md).

## Honest expectation

Nothing here is "always profitable" or "safe money". The strategies were
chosen because they have decades of academic evidence (trend, momentum,
volatility targeting), not because they guarantee anything. Backtests
charge commission and slippage, separate in-sample from out-of-sample
(walk-forward), and always show the benchmark next to the strategy. If
paper trading does not beat buy-and-hold, the dashboard says so.

## Quickstart (paper trading + dashboard)

```bash
uv python install 3.13
uv sync
cp .env.example .env            # fictional local values, gitignored
docker compose up -d postgres   # local PostgreSQL on 127.0.0.1:5434
uv run alembic upgrade head     # head: 0012_paper_trading

make fetch-data                 # Yahoo Finance -> PIT store (~4 min first time)
make backtest-all               # all strategies, costs + walk-forward (~4 min)
make paper-replay FROM=2024-01-02   # simulated track record from that date
make dashboard-install && make dashboard-build
make app                        # http://127.0.0.1:8000  (APP_MODE=paper)
```

Then, once per trading day after the US close (cron example in
`scripts/paper-run.py`):

```bash
make paper-run                  # fetch latest data + run the paper engine
```

Development: `make dashboard-dev` (Vite on `127.0.0.1:5173`, proxies to
the API on 8000).

## What it does

- **Market data** (`quant_platform.marketdata`): downloads daily bars and
  dividends for a diversified ETF universe (SPY, QQQ, IWM, EFA, EEM, VNQ,
  TLT, IEF, GLD, DBC, BIL, optional BTC-USD) and writes them through the
  existing contract-payload intake: bronze raw capture, PIT
  `available_time`, idempotent silver inserts, vendor restatements stored
  as corrections. Incremental by default.
- **Strategies** (`quant_platform.strategies`): long-only target weights
  from prices visible at `as_of` only: trend following (SMA), dual
  momentum, relative momentum top-N, inverse volatility with a vol
  target, plus buy-and-hold SPY and 60/40 benchmarks.
- **Backtests** (`quant_platform.backtesting`): daily simulation with a
  one-session execution lag, commission + slippage in bps, drift between
  rebalances, metrics (CAGR, vol, Sharpe, Sortino, max drawdown, Calmar,
  turnover), anchored walk-forward validation and a promotion rule.
  Results persist in `strategy_backtests`.
- **Paper trading** (`quant_platform.paper`): one simulated account per
  strategy (100,000 fictional USD). Each daily run fills yesterday's
  orders at today's open with slippage, credits dividends, marks to
  market, and queues the next rebalance. Idempotent per session; replays
  are flagged. A `BrokerAdapter` seam exists; only `SimulatedBroker` is
  implemented.
- **Dashboard** (`dashboard/`, React + Vite): overview, strategies,
  backtest detail (equity, drawdown, monthly heatmap, walk-forward),
  paper accounts (positions, orders, fills), market candlesticks and
  data coverage. Served by FastAPI at `/`, JSON API under `/api`.
- **Research layer** (unchanged): PIT datasets, quality, snapshots,
  replay, dry-run research policies, evidence bundles, normalization
  (now with a `total_return` mode), vendor-agnostic contracts.

## Boundaries

Enabled: research tooling, yfinance market data, strategies, strategy
backtests with PnL/returns metrics, simulated paper trading, dashboard.

Disabled and rejected: live trading, real brokers, real money, leverage,
short selling, intraday, AI runtime, SQLite, cloud object storage.
`APP_MODE=live` fails settings validation.

Full matrix: [docs/release/CAPABILITY_MATRIX.md](docs/release/CAPABILITY_MATRIX.md).
Risks: [docs/release/RISK_REGISTER.md](docs/release/RISK_REGISTER.md).

A pre-existing tree named `AI_VENTURE_OS_PROMPTS/` may sit next to this
project. It is a separate product and is **not** part of `quant_platform`.
Do not mix the two.

## Modes

- `APP_MODE=research` (default in `.env.example`): data and research
  tooling; paper endpoints are read-only.
- `APP_MODE=paper`: adds the simulated paper engine. `make app`,
  `make paper-run` and `make paper-replay` set it explicitly.
- `APP_MODE=live`: not implemented, rejected.

## Quality gates

```bash
make quality                 # ruff, format, mypy, fast tests, compose config
make policy-regression
make normalization-regression
make data-contract-conformance-regression
make data-contract-schema-compatibility
make contract-payload-intake-regression
make research-release-check
make research-status
make dashboard-typecheck
```

With PostgreSQL: `uv run pytest -m postgres`. CI runs the Python fast
path, the dashboard type-check/build and a Postgres job. Tests never hit
the network: the market data adapter is exercised with recorded fixtures.

## Tests

```bash
uv run pytest -m "not postgres"   # fast, offline
uv run pytest                     # all (Postgres tests skip if DB is down)
uv run pytest -m postgres
```

## PostgreSQL (local development)

Host **5432** is used on this machine by another container and **5433**
by `postgres_db`, so this project maps PostgreSQL to **`127.0.0.1:5434`**.

```bash
docker compose up -d postgres
docker compose ps
uv run python scripts/check-db.py
```

Default credentials in Compose and `.env.example` are fictional local
placeholders. Alembic revisions `0001_ingestion` … `0010_normalized_dataset_catalog`
create the research tables; `0011_strategy_backtests` and
`0012_paper_trading` add backtest results and the `paper_*` tables.
Silver `daily_bars` are never rewritten by any layer.

## API

```bash
make app     # or: APP_MODE=paper uv run uvicorn quant_platform.api.app:app --host 127.0.0.1 --port 8000
```

- `GET /health`
- `GET /api/status`, `GET /api/market/universe`, `GET /api/market/bars/{symbol}`
- `GET /api/strategies`, `GET /api/backtests`, `GET /api/backtests/ranking`, `GET /api/backtests/{id}`
- `GET /api/paper/accounts`, `GET /api/paper/accounts/{name}`, `GET /api/paper/accounts/{name}/equity`
- `POST /api/market/fetch`, `POST /api/backtests/run`, `POST /api/paper/run` (background jobs, `GET /api/jobs`)
- Static dashboard at `/` when `dashboard/dist` exists.

Everything binds to `127.0.0.1`. Paper mutations return 409 unless
`APP_MODE=paper`.

## AI usage boundary

Cursor (and similar editors) may be used to **write** this codebase. They
are **not** part of the running platform: not a dependency, not required
for tests or CI, and not a trading brain. There is **no** OpenAI,
Anthropic, Cursor API, or local-model integration.

Policy: [docs/ai/AI_USAGE_BOUNDARY.md](docs/ai/AI_USAGE_BOUNDARY.md) and
[docs/adr/0002-ai-usage-boundary.md](docs/adr/0002-ai-usage-boundary.md).

## More documentation

Research layer: [docs/data/DATA_INGESTION.md](docs/data/DATA_INGESTION.md),
[docs/data/CORPORATE_ACTIONS.md](docs/data/CORPORATE_ACTIONS.md),
[docs/research/RESEARCH_DATASETS.md](docs/research/RESEARCH_DATASETS.md),
[docs/research/CORPORATE_ACTION_NORMALIZATION.md](docs/research/CORPORATE_ACTION_NORMALIZATION.md),
[docs/research/NORMALIZED_DATASET_CATALOG.md](docs/research/NORMALIZED_DATASET_CATALOG.md),
[docs/simulation/DATASET_REPLAY.md](docs/simulation/DATASET_REPLAY.md),
[docs/backtest/BACKTEST_ENGINE.md](docs/backtest/BACKTEST_ENGINE.md),
[docs/data/DATA_SOURCE_CONTRACTS.md](docs/data/DATA_SOURCE_CONTRACTS.md),
[docs/data/CONTRACT_PAYLOAD_INTAKE.md](docs/data/CONTRACT_PAYLOAD_INTAKE.md),
[docs/release/RESEARCH_RELEASE_CANDIDATE.md](docs/release/RESEARCH_RELEASE_CANDIDATE.md).

Commands: [docs/release/COMMANDS.md](docs/release/COMMANDS.md).
Workflow: [docs/development/DEVELOPER_WORKFLOW.md](docs/development/DEVELOPER_WORKFLOW.md).
Architecture: [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md),
[docs/adr/0001-foundation-architecture.md](docs/adr/0001-foundation-architecture.md),
[docs/adr/0003-research-mode-freeze.md](docs/adr/0003-research-mode-freeze.md),
[docs/adr/0004-vendor-agnostic-data-source-contract.md](docs/adr/0004-vendor-agnostic-data-source-contract.md),
[docs/adr/0005-paper-trading-pivot.md](docs/adr/0005-paper-trading-pivot.md).
