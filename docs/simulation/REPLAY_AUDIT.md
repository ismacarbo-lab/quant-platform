# Replay audit — Phase 3.2

A **replay audit** inspects an already-built event stream. It does not
trade, does not run a strategy, and does not store event rows. Phase 3.3
can write the full report to local `audit.json` and a compact
`audit_summary` into the replay-run catalog. See
[REPLAY_RUNS.md](REPLAY_RUNS.md).

Package: `quant_platform.simulation.audit` plus
`quant_platform.simulation.hashing`.

Boundary semantics: [REPLAY_BOUNDARIES.md](REPLAY_BOUNDARIES.md).

## Stream hash

`hash_replay_events(events)` returns `sha256:<64 hex>`.

The payload is canonical JSON (sorted keys, UTC `Z` timestamps, 8-decimal
prices), **format version 2**. It includes event kinds, PIT timestamps,
and `known_before_start`. It does **not** include:

- `replay_id` (UUID4 or derived)
- wall-clock `utc_now`
- absolute filesystem paths
- `DATABASE_URL` or other secrets

Same ordered stream ⇒ same hash. Changing a close, a session kind, a
pre-known flag, or event order changes the hash.

Replay hashes events **in the order given**. The producer
(`replay_daily_bars_dataset`) always emits canonical order. `audit_replay`
flags a stream that is not in that order.

## Deterministic replay id

Default `replay_id` is still UUID4.

`derive_replay_id(stream_hash, request_hash=None)` builds a stable UUID
from the stream hash and, optionally, `hash_replay_request(request)`.

`replay_daily_bars_dataset(..., deterministic_id=True)` and the script flag
`--deterministic-id` use both hashes. An explicit `replay_id=` still wins.

## Audit report

`audit_replay(events, as_of=..., sessions_requested=..., calendar_code=...,
start_time=...)` returns `ReplayAuditReport`.

`start_time` is taken from `ReplayStartedEvent` when present, otherwise
from the optional argument. It is used for pre-known and
`event_time < start_time` checks.

| Field | Meaning |
|-------|---------|
| `ok` | no `error` issues |
| `stream_hash` | hash of the given sequence |
| `counts_by_kind` | how many events of each kind |
| `first_event_time` / `last_event_time` | ends of the given sequence |
| `starts_with_replay_started` | first event is `ReplayStartedEvent` |
| `ends_with_replay_finished` | last event is `ReplayFinishedEvent` |
| `boundary_ok` | bookends present and no boundary errors |
| `pre_known_event_count` | events with `known_before_start` |
| `issues` | `info` / `warning` / `error` |

`as_mapping()` also includes a `boundary` object with the bookend flags.

Checks:

- stream does not start with `ReplayStartedEvent` (`missing_started`)
- stream does not end with `ReplayFinishedEvent` (`missing_finished`)
- payload `event_time < start_time` (`event_before_start`)
- `available_time < start_time` without `known_before_start`
  (`preknown_unmarked`)
- pre-known fact after an in-window payload event (`preknown_misplaced`)
- naive timestamps
- `event_time > as_of` or `available_time > as_of` (lookahead)
- in-window bar or corporate-action `event_time != available_time`
  (pre-known events may differ; `event_time` is `start_time`)
- canonical sort order (boundary group, time, type priority, instrument, …)
- `include_sessions` without `calendar_code` (info)
- calendar expected but zero session events (warning)
- holes between emitted session dates (warning)
- bar observation date with no session event when sessions were requested (warning)

Audit never invents missing calendar rows.

## Script

```bash
uv run python scripts/replay-daily-dataset.py \
  --as-of 2024-01-10T00:00:00Z \
  --start 2024-01-01T00:00:00Z \
  --end 2024-01-05T00:00:00Z \
  --symbol FIXT \
  --calendar XNYS \
  --include-sessions \
  --include-corporate-actions \
  --audit \
  --deterministic-id \
  --json
```

`--audit --json` prints `stream_hash`, counts by kind (including
`pre_known_event_count` on the summary), boundary status, first/last
market event times, warning/error counts, and issue lines. It does not
print `DATABASE_URL`.

With `--output-dir`, the same audit is written to `audit.json` even if
`--audit` is omitted. `--register` stores only the compact summary
(`ok`, `boundary_ok`, counts, `stream_hash`, bookend flags), not the
issue list.

Snapshot replay can still be audited (bars only). `--include-sessions` /
`--include-corporate-actions` on a snapshot add summary warnings: those
facts are not stored in the snapshot folder.

## What this is not

Not a backtester, quality report, or catalog integrity check. Those stay
in `quant_platform.research`. Replay audit only looks at the simulation
event stream. Persisting the run is [REPLAY_RUNS.md](REPLAY_RUNS.md).
Whether a registered run may feed a future backtester is
[BACKTEST_READINESS.md](BACKTEST_READINESS.md).
