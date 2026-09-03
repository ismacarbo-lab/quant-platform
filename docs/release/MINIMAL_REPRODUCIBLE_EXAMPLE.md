# Minimal reproducible example — research evidence bundle

This is the shortest local path that shows research mode works. It uses
**fictional fixtures** in `tests/fixtures/e2e_research_bundle/`.

No internet. No vendors. No real market data. No trading.

Related: [COMMANDS.md](COMMANDS.md),
[RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md),
[FINAL_RESEARCH_CHECKLIST.md](FINAL_RESEARCH_CHECKLIST.md).

## 1. PostgreSQL

From `/home/isma/invest`:

```bash
cp .env.example .env   # if needed; gitignored placeholders only
docker compose up -d postgres
uv run python scripts/check-db.py
```

Expect `ping=ok` and `trading_tables=none`. Local Compose listens on
`127.0.0.1:5434`.

## 2. Alembic

```bash
uv run alembic upgrade head
uv run alembic current
```

Expect `0010_normalized_dataset_catalog`.
(`v0.1.0-research` was tagged at `0009_backtest_experiments`.)

## 3. Build the evidence bundle

```bash
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle \
  --deterministic-id \
  --json
```

Or `make research-evidence-bundle`.

The command fails if `APP_MODE` is not research, Alembic is not at the
expected head, the policy is not registered, or a pipeline step errors.
It does not print connection URLs.

## 4. Verify

```bash
uv run python scripts/verify-research-evidence-bundle.py \
  --bundle-dir /tmp/research-evidence-bundle \
  --json
```

Or `make verify-research-evidence-bundle`.

Expect `ok=true`. That means hashes, relative paths, and research
guardrails passed. It does **not** mean PnL or returns exist.

## 5. Inspect the summary

```bash
uv run python -c "from pathlib import Path; print(Path('/tmp/research-evidence-bundle/evidence_summary.json').read_text())"
```

Useful fields: `ok`, `dataset_snapshot_id`, `replay_id`, `backtest_id`,
`experiment_id`, `replay_ready`, `backtest_usable`, `experiment_usable`,
`release_ok`, `bundle_hash`.

Also present: `evidence_manifest.json`, `release_status.json`, and
subdirectories `dataset_snapshot/`, `replay_run/`, `backtest_run/`,
`experiment/`, `reports/`.

`bundle_hash` ignores wall-clock and random `bundle_id`. A change to
`stream_hash` changes the bundle hash.

## What you should not see

- strategies, signals, orders, fills, portfolio
- PnL or returns
- broker calls
- downloads
- `DATABASE_URL` in the printed JSON
