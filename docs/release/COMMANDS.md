# Canonical commands — research freeze

Working directory: `/home/isma/invest`.

Do not print secrets. Do not print a live `DATABASE_URL`. Copy
`.env.example` to `.env` for local overrides (gitignored, fictional
placeholders only).

Full narrative: [DEVELOPER_WORKFLOW.md](../development/DEVELOPER_WORKFLOW.md).
Handoff: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md).
Minimal path: [MINIMAL_REPRODUCIBLE_EXAMPLE.md](MINIMAL_REPRODUCIBLE_EXAMPLE.md).

## Setup

```bash
uv python install 3.13
uv sync
cp .env.example .env
```

`APP_MODE` must remain `research`.

## Quality (no PostgreSQL required)

```bash
make quality
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not postgres"
docker compose config
```

## PostgreSQL

```bash
docker compose up -d postgres
uv run python scripts/check-db.py
uv run pytest -m postgres
```

Local Compose uses host port **5434**. Do not fall back to SQLite.

## Alembic

```bash
uv run alembic current
uv run alembic upgrade head
```

Expected head: `0009_backtest_experiments`.

## Load sample data

```bash
uv run python scripts/load-daily-bars.py tests/fixtures/daily_bars_sample.csv
```

No vendors. Local CSV only.

## Normalized daily bars (derived)

```bash
uv run python scripts/build-normalized-dataset.py \
  --source-name local_csv \
  --symbol FIXT \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --as-of 2024-01-20T00:00:00Z \
  --adjustment-mode split_only \
  --output-dir /tmp/normalized-fixt
uv run python scripts/verify-normalized-dataset.py \
  --run-dir /tmp/normalized-fixt
```

Does not rewrite silver `daily_bars`. See
[CORPORATE_ACTION_NORMALIZATION.md](../research/CORPORATE_ACTION_NORMALIZATION.md).

## Snapshot

```bash
uv run python scripts/create-dataset-snapshot.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --output-dir /tmp/fixt-snapshot \
  --register
```

## Replay

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --include-sessions \
  --include-corporate-actions \
  --output-dir /tmp/fixt-replay \
  --register \
  --deterministic-id \
  --audit \
  --json
```

## Backtest dry-run

```bash
uv run python scripts/run-backtest.py \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-backtest \
  --policy-name data_quality \
  --register \
  --deterministic-id
```

Not a strategy. No orders.

## Experiment

```bash
uv run python scripts/run-backtest-experiment.py \
  --experiment-name e2e-research-evidence \
  --replay-id ID_A \
  --replay-base-dir /tmp/fixt-replay \
  --output-dir /tmp/fixt-experiment \
  --policy-name data_quality \
  --register \
  --deterministic-id \
  --json
```

## Policy regression

```bash
make policy-regression
uv run python scripts/run-policy-regression-matrix.py --json
```

Do not auto-rewrite `matrix.json`. Copy expected hashes by hand after
review.

## Release check and status

```bash
make research-status
uv run python scripts/research-status.py --json
make research-release-check
uv run python scripts/research-release-check.py --json
```

Status prints `final_freeze_ready`, `evidence_bundle_available`,
`alembic_head_expected`, and disabled capabilities. It does not ping
PostgreSQL.

## Evidence bundle

```bash
make research-evidence-bundle
make verify-research-evidence-bundle
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --json
uv run python scripts/verify-research-evidence-bundle.py \
  --bundle-dir /tmp/research-evidence-bundle \
  --json
```

Not in `make quality`. Needs PostgreSQL.

## CI troubleshooting

- Confirm you are in `/home/isma/invest`, not the accidental git at
  `/home/isma`.
- Actions jobs: `quality` (no DB) and `postgres` (service on 5432 inside
  the runner). No GitHub secrets required.
- If **postgres** fails: do not add SQLite. Check the service healthcheck
  and `QUANT_PLATFORM_REQUIRE_POSTGRES=1`.
- If **policy regression** fails: run the matrix locally; review
  observations; update `matrix.json` by hand if the change is intended.
- If **setup-uv** fails: retry / pin the action; do not weaken gates.
- Never paste passwords or connection URLs into issues or logs.

## Remote verification and tag

See [REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md) and
[POST_TAG_RELEASE_NOTES.md](POST_TAG_RELEASE_NOTES.md).

Annotated tag `v0.1.0-research` exists on `origin`. Do not create another
tag for this freeze.
