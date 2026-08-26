# Developer workflow

This project is **research-only**. There is no paper trading, live trading,
broker adapter, or execution engine.

## AI usage boundary

Use Cursor or another assistant to edit the repo if you want. Do **not**
add it to `pyproject.toml`. Tests and CI must pass without Cursor.

There is no LLM client in the application. Do not add OpenAI, Anthropic,
LangChain, LlamaIndex, or Transformers until a later ADR. A future helper
must stay optional, off by default, and must not trade or mutate data.

Details: [docs/ai/AI_USAGE_BOUNDARY.md](../ai/AI_USAGE_BOUNDARY.md).

Commands below assume the working directory is the repository root
(`/home/isma/invest` on this machine). Use the `uv run …` forms if `make`
is unavailable. `make` is a convenience wrapper, not a required dependency.

## Install

```bash
uv python install 3.13
uv sync
cp .env.example .env   # gitignored; fictional local values only
```

`.env` is never committed. `.env.example` is the tracked template.

## Quality gates (no Docker)

Equivalent to the default GitHub Actions `quality` job:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not postgres"
docker compose config
```

Or:

```bash
make quality
```

| Intent | Command |
|--------|---------|
| Lint | `uv run ruff check .` / `make lint` |
| Format check | `uv run ruff format --check .` / `make format-check` |
| Apply format | `uv run ruff format .` / `make format` |
| Types | `uv run mypy src` / `make typecheck` |
| All tests (Postgres tests skip if DB is down) | `uv run pytest` / `make test` |
| Fast tests only | `uv run pytest -m "not postgres"` / `make test-fast` |
| Postgres tests only | `uv run pytest -m postgres` / `make test-postgres` |
| Compose file | `docker compose config` / `make compose-config` |

Unit tests and `tests/integration/test_local_infra.py` do **not** need Docker.
Tests marked `postgres` need a reachable PostgreSQL; they skip unless
`QUANT_PLATFORM_REQUIRE_POSTGRES=1` (used in CI so a missing DB fails the job).

## PostgreSQL (local)

This machine already binds **5432** (`ia_postgres`) and **5433** (`postgres_db`).
Compose therefore publishes **`127.0.0.1:5434`**.

```bash
docker compose up -d postgres
docker compose ps
uv run python scripts/check-db.py
```

`scripts/check-db.py` runs `SELECT 1`, lists public tables, and refuses
trading tables. It does not print `DATABASE_URL` or passwords.

Apply the ingestion schema:

```bash
uv run alembic upgrade head
```

Load a local CSV (no vendors). Default is collect-errors:

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv
```

Fail-fast: add `--fail-fast`. Optional `--calendar CODE` (must already exist)
and `--validate-calendar` (rejects closed sessions). Row errors live in
`ingestion_errors`; raw payloads in `raw_ingestion_records`. See
[docs/data/DATA_INGESTION.md](../data/DATA_INGESTION.md),
[INSTRUMENT_MASTER.md](../data/INSTRUMENT_MASTER.md),
[MARKET_CALENDARS.md](../data/MARKET_CALENDARS.md), and
[CORPORATE_ACTIONS.md](../data/CORPORATE_ACTIONS.md).

Export a point-in-time daily dataset (`--as-of` required):

```bash
uv run python scripts/export-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output /tmp/daily-dataset.csv
```

See [docs/research/RESEARCH_DATASETS.md](../research/RESEARCH_DATASETS.md).

Diagnose coverage, calendar gaps, PIT corrections, and related ingestion
errors (`--as-of` required):

```bash
uv run python scripts/report-dataset-quality.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --calendar XNAS
```

Optional `--output PATH` writes JSON. See
[docs/research/DATASET_QUALITY.md](../research/DATASET_QUALITY.md).

Save a hashed local snapshot (CSV + quality JSON + manifest; `--as-of` and
`--output-dir` required):

```bash
uv run python scripts/create-dataset-snapshot.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-snapshot
```

See [docs/research/DATASET_SNAPSHOTS.md](../research/DATASET_SNAPSHOTS.md).

Register snapshot metadata in PostgreSQL (`--register`) and list it:

```bash
uv run python scripts/create-dataset-snapshot.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-snapshot \
  --register

uv run python scripts/list-dataset-snapshots.py --usable-only --json
```

See [docs/research/DATASET_CATALOG.md](../research/DATASET_CATALOG.md).

Verify local artifacts (no writes) and catalog rows against a folder:

```bash
uv run python scripts/verify-dataset-snapshot.py --snapshot-dir /tmp/fixt-snapshot
uv run python scripts/verify-dataset-catalog.py \
  --base-dir /tmp/fixt-snapshot \
  --json
```

See [docs/research/SNAPSHOT_INTEGRITY.md](../research/SNAPSHOT_INTEGRITY.md).

Replay a PIT dataset (or a local snapshot) as ordered market events. This
is not a backtester:

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT

uv run python scripts/replay-daily-dataset.py \
  --snapshot-dir /tmp/fixt-snapshot \
  --json

uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --include-corporate-actions \
  --include-sessions \
  --calendar XNYS \
  --audit \
  --deterministic-id \
  --json
```

Export artifacts and register catalog metadata (`--register` requires
`--output-dir`):

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-replay \
  --register \
  --deterministic-id \
  --json

uv run python scripts/list-replay-runs.py --usable-only --json
uv run python scripts/verify-replay-run.py --run-dir /tmp/fixt-replay
uv run python scripts/compare-replay-runs.py --left ID_A --right ID_B
uv run python scripts/check-replay-readiness.py \
  --replay-id ID_A \
  --base-dir /tmp/fixt-replay
```

See [docs/simulation/DATASET_REPLAY.md](../simulation/DATASET_REPLAY.md),
[docs/simulation/REPLAY_BOUNDARIES.md](../simulation/REPLAY_BOUNDARIES.md),
[docs/simulation/REPLAY_AUDIT.md](../simulation/REPLAY_AUDIT.md),
[docs/simulation/REPLAY_RUNS.md](../simulation/REPLAY_RUNS.md),
and [docs/simulation/BACKTEST_READINESS.md](../simulation/BACKTEST_READINESS.md).

Dry-run a ready replay run with `NoOpBacktestPolicy` (not a strategy,
not trading). `--register` requires `--output-dir`:

```bash
uv run python scripts/run-backtest.py \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name noop \
  --register \
  --deterministic-id \
  --json

uv run python scripts/list-backtest-runs.py --usable-only --json
uv run python scripts/verify-backtest-run.py --run-dir /tmp/fixt-backtest
uv run python scripts/verify-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest
uv run python scripts/report-policy-output.py \
  --backtest-run-dir /tmp/fixt-backtest
uv run python scripts/compare-backtest-runs.py --left ID_A --right ID_B
uv run python scripts/check-backtest-usability.py \
  --backtest-id ID_A \
  --base-dir /tmp/fixt-backtest

uv run python scripts/run-backtest-experiment.py \
  --experiment-name noop-grid \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name noop \
  --register \
  --deterministic-id \
  --json
uv run python scripts/list-backtest-experiments.py --usable-only --json
uv run python scripts/verify-backtest-experiment.py \
  --experiment-dir /tmp/fixt-experiment
uv run python scripts/compare-backtest-experiments.py --left ID_A --right ID_B
uv run python scripts/check-backtest-experiment-usability.py \
  --experiment-id ID_A \
  --base-dir /tmp/fixt-experiment
uv run python scripts/report-backtest-experiment.py \
  --experiment-id ID_A \
  --base-dir /tmp/fixt-experiment \
  --output-dir /tmp/fixt-experiment
```

See [docs/backtest/BACKTEST_ENGINE.md](../backtest/BACKTEST_ENGINE.md),
[docs/backtest/NOOP_POLICY.md](../backtest/NOOP_POLICY.md),
[docs/backtest/BACKTEST_INTEGRITY.md](../backtest/BACKTEST_INTEGRITY.md),
[docs/backtest/RESEARCH_POLICY_INTERFACE.md](../backtest/RESEARCH_POLICY_INTERFACE.md),
[docs/backtest/POLICY_OUTPUT_INTEGRITY.md](../backtest/POLICY_OUTPUT_INTEGRITY.md),
[docs/backtest/BACKTEST_EXPERIMENTS.md](../backtest/BACKTEST_EXPERIMENTS.md),
and [docs/backtest/BACKTEST_EXPERIMENT_USABILITY.md](../backtest/BACKTEST_EXPERIMENT_USABILITY.md).

Event JSON fixtures for tests live in `tests/fixtures/replay_events/`.

Stop (keeps the volume):

```bash
docker compose down
```

### If 5434 is occupied

Do **not** fall back to SQLite. Either:

1. Stop the process bound to `127.0.0.1:5434`, or
2. Change **both** the host port in `docker-compose.yml` and `DATABASE_URL`
   in `.env` to the same free port.

GitHub Actions uses `127.0.0.1:5432` inside the runner via `DATABASE_URL`.
That does not change the local Compose mapping.

## API

```bash
uv run uvicorn quant_platform.api.app:app --host 127.0.0.1 --port 8000
```

Only `GET /health`. It does not query PostgreSQL.

## Remote, first push, and GitHub Actions

Create an **empty** GitHub repository (recommended name: `quant-platform`).
Do not add a README, `.gitignore`, or license from the GitHub UI.

There is no `origin` remote until you add one. Do not invent a URL.

```bash
git remote add origin git@github.com:<github-user>/quant-platform.git
git push -u origin main
```

HTTPS alternative: `https://github.com/<github-user>/quant-platform.git`.

If push fails with authentication:

- GitHub CLI: `gh auth login -h github.com` then `gh auth setup-git`
- SSH: add the local public key (`~/.ssh/id_ed25519.pub`) at GitHub →
  Settings → SSH and GPG keys, then retry `git push -u origin main`
- Personal access token: GitHub → Settings → Developer settings.
  Do not commit or paste the token into the repo

After a successful push: GitHub → repository → **Actions** → latest
workflow run for `CI` (`.github/workflows/ci.yml`). Expect jobs
`quality` and `postgres` to pass.

If **setup-uv** fails: confirm the runner has network access, then retry or
pin `astral-sh/setup-uv` to a known-good tag in `ci.yml`. Re-run the
workflow; do not weaken quality gates.

If the **postgres** job fails: the runner uses `127.0.0.1:5432` via
`DATABASE_URL` (not local Compose `5434`). Check the service healthcheck,
that `QUANT_PLATFORM_REQUIRE_POSTGRES=1` is set, and that tests are not
skipping. Fix only the workflow or connection env; do not add SQLite.

## CI

`.github/workflows/ci.yml` runs on push and pull request. No GitHub secrets.
The `quality` job never starts Postgres. The `postgres` job uses a Postgres
16 service and `QUANT_PLATFORM_REQUIRE_POSTGRES=1`.
