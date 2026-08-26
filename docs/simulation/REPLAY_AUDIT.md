# Replay audit — Phase 3.1

A **replay audit** inspects an already-built event stream. It does not
trade, does not run a strategy, and does not persist a simulation run.

Package: `quant_platform.simulation.audit` plus
`quant_platform.simulation.hashing`.

## Stream hash

`hash_replay_events(events)` returns `sha256:<64 hex>`.

The payload is canonical JSON (sorted keys, UTC `Z` timestamps, 8-decimal
prices). It includes event kinds and the fields that define the stream.
It does **not** include:

- `replay_id` (UUID4 or derived)
- wall-clock `utc_now`
- `DATABASE_URL` or other secrets

Same ordered stream ⇒ same hash. Changing a close, a session kind, or
event order changes the hash.

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

`audit_replay(events, as_of=..., sessions_requested=..., calendar_code=...)`
returns `ReplayAuditReport`:

| Field | Meaning |
|-------|---------|
| `ok` | no `error` issues |
| `stream_hash` | hash of the given sequence |
| `counts_by_kind` | how many events of each kind |
| `first_event_time` / `last_event_time` | ends of the given sequence |
| `issues` | `info` / `warning` / `error` |

Checks:

- naive timestamps
- `event_time > as_of` (lookahead)
- bar or corporate-action `event_time != available_time`
- canonical sort order (time, then type priority, then instrument, …)
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

`--audit` prints `stream_hash`, counts by kind, warning/error counts, and
issue lines. It does not print `DATABASE_URL`.

Snapshot replay can still be audited (bars only). `--include-sessions` /
`--include-corporate-actions` on a snapshot add summary warnings: those
facts are not stored in the snapshot folder.

## What this is not

Not a backtester, quality report, or catalog integrity check. Those stay
in `quant_platform.research`. Replay audit only looks at the simulation
event stream.
