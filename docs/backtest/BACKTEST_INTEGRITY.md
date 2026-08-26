# Backtest artifact integrity — Phase 4.1 / 4.2

Read-only checks that a local dry-run backtest folder still matches its
manifest and, when asked, the PostgreSQL `backtest_runs` catalog.
Verification does **not** write files, mutate catalog rows, upload
objects, or download data.

Package: `quant_platform.backtest.integrity` (types in
`integrity_types`), plus `quant_platform.backtest.compare` and
`quant_platform.backtest.readiness` (result usability, not replay
readiness).

**No Alembic revision for integrity itself.** Phase 4.2 adds
`0008_backtest_policy_metadata` for catalog columns, not for the
verifier.

Registered research policies (`noop`, `event_counting`) may appear in
manifests. Passing integrity or `usable_result` does **not** mean a
strategy exists, that PnL was computed, or that the result is
economically interesting.

Engine: [BACKTEST_ENGINE.md](BACKTEST_ENGINE.md).
Policy: [NOOP_POLICY.md](NOOP_POLICY.md).
Research policy interface: [RESEARCH_POLICY_INTERFACE.md](RESEARCH_POLICY_INTERFACE.md).
Replay readiness (different gate): [BACKTEST_READINESS.md](../simulation/BACKTEST_READINESS.md).

## What is verified

For a backtest directory:

- `manifest.json`, `summary.json`, and `policy_output.json` exist
- listed artifact paths are relative, not absolute, and do not contain `..`
- hashes look like `sha256:<64 hex>` (`stream_hash`, `backtest_hash`,
  `manifest_hash`, `policy_output_hash`)
- `replay_id` is present
- `policy_name` is a registered research policy (`noop` or
  `event_counting`)
- `manifest_hash` matches a recomputation of the manifest (`manifest_hash`
  field excluded)
- `backtest_hash` matches a recomputation from `summary.json` (counts,
  policy name, policy config, policy output hash, replay id, stream hash,
  warning/error codes)
- `policy_output_hash` matches `policy_output.json`
- summary counts match the nested `manifest.summary` object and the
  warnings/errors lists
- observations do not contain investment-decision wording
- no `DATABASE_URL`, passwords, or connection-string markers

Against the catalog (optional):

- the `backtest_id` exists
- a local folder for that id can be found under `--base-dir`
- catalog hashes, `event_count`, and `policy_name` match the local files

## What is not verified

- replay `events.jsonl` (the backtest does not copy the stream)
- strategy logic, signals, orders, fills, portfolio, or PnL (none exist)
- that the NoOp counts are an “edge”
- byte-for-byte equality of pretty-printed JSON (hashes use canonical JSON)
- signatures, cloud object keys, or vendor payloads
- wall-clock `created_at` as part of `backtest_hash`

## `backtest_hash` vs `manifest_hash`

| Hash | Meaning |
|------|---------|
| `backtest_hash` | Replay id + stream hash + policy name + policy config + policy output hash + counts + warning/error codes. No wall-clock, no paths, no random UUID. |
| `policy_output_hash` | Canonical observations + policy config (no wall-clock). |
| `manifest_hash` | Canonical export of this folder, **including** `created_at` and `backtest_id`. |

Compare **logic** with `backtest_hash`. Compare **this export** with
`manifest_hash`. Two dry-runs of the same stream can share
`backtest_hash` and still differ in `manifest_hash` if `created_at` or
`backtest_id` differs.

## Compare runs (`same_result`)

`diff_backtest_runs` / `diff_catalog_backtest_runs` compare catalog or
manifest metadata. They do not load replay events.

Verdict:

| Verdict | Meaning |
|---------|---------|
| `identical` | Same `manifest_hash` (same export). |
| `same_result` | Same `backtest_hash`, different `manifest_hash` (same NoOp counts, different export identity). |
| `different` | Different `backtest_hash`. |

Shallow helper `compare_backtest_runs` from Phase 4.0 still exists.
Scripts and this document use the field-level diff.

## `usable_result`

`evaluate_backtest_result_usability` answers: is this registered NoOp
result intact enough to keep as research evidence?

`usable_result` is true only when:

- `APP_MODE=research`
- the `backtest_id` is registered
- catalog `is_reproducible` and `is_usable` are true
- catalog `error_count == 0`
- local artifact verification has no errors
- `policy_name` is `noop`
- `backtest_hash` and `manifest_hash` look like `sha256:<64 hex>`

If `replay_id` is missing from `simulation_replay_runs`, the report adds a
**warning** (`replay_catalog_missing`). That warning does **not** block
`usable_result`.

This is **not** replay `ready_for_backtest`. It does not mean the policy
made money.

## Verify a local backtest

No database connection. Exit status `1` if any **error** is present.

```bash
uv run python scripts/verify-backtest-run.py \
  --run-dir /tmp/fixt-backtest
uv run python scripts/verify-backtest-run.py \
  --run-dir /tmp/fixt-backtest \
  --json
```

`--base-dir` for catalog/usability may be the run folder itself, or a
parent of several folders. Matching uses `manifest.json` → `backtest_id`
(including a child named after the id).

## Compare two registered backtests

```bash
uv run python scripts/compare-backtest-runs.py \
  --left <backtest_id_a> \
  --right <backtest_id_b> \
  --json
```

## Usability gate

```bash
uv run python scripts/check-backtest-usability.py \
  --backtest-id <backtest_id> \
  --base-dir /tmp/fixt-backtest \
  --json
```

List catalog rows (short `backtest_hash`, `policy_name`, `is_usable`,
`error_count`):

```bash
uv run python scripts/list-backtest-runs.py --usable-only --json
```

Scripts do not print `DATABASE_URL`. There is no `--repair` flag.

## Why rows stay out of PostgreSQL

The catalog stores hashes and counts so you can tell two folders apart
without copying replay events into JSONB. Integrity re-reads the local
JSON when you point it at a directory.

## Limitations

- Finding a catalog row on disk requires `--base-dir`; the catalog does
  not store absolute paths.
- Verification is not stored (`last_verified_at` does not exist).
- Extra files in the folder are ignored.
- `same_result` is a metadata verdict, not a statistical test.

## Tests

```bash
uv run pytest -m "not postgres"
uv run pytest -m postgres
```

## What does not exist

- real strategies, signals, indicators-as-signals, alpha models
- orders, fills, trades, portfolio, positions, cash, PnL, returns
- execution, brokers, paper trading, live trading
- risk engine, optimizer, ML, LLM runtime
- HTTP routes beyond `GET /health`
- cloud object storage
