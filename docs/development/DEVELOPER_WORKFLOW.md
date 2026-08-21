# Developer workflow

This project is **research-only**. There is no paper trading, live trading,
broker adapter, or execution engine.

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

Load a local CSV (no vendors):

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv
```

Details: [docs/data/DATA_INGESTION.md](../data/DATA_INGESTION.md).

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
