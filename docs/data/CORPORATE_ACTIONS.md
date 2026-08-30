# Corporate actions — Phase 1.4

Storage only in silver. The platform records that an event exists. It
does **not** rewrite `daily_bars` or change `instruments.symbol`.

A derived research view can restate prices and volumes. See
[CORPORATE_ACTION_NORMALIZATION.md](../research/CORPORATE_ACTION_NORMALIZATION.md).

## What exists

Table `corporate_actions`:

| Field | Role |
|-------|------|
| `instrument_id` | Research instrument |
| `action_type` | See types below |
| `effective_time` | When the event takes economic effect (UTC) |
| `available_time` | When the event would have been knowable (UTC) |
| `quantity_before` / `quantity_after` | Split ratio (optional) |
| `cash_amount` / `currency` | Dividend cash (optional) |
| `old_value` / `new_value` | Symbol change strings (optional) |
| `note` / `details` | Free-text / JSON |

Types (check constraint):

- `split`
- `reverse_split`
- `dividend`
- `symbol_change`
- `delisting`

Announcement can precede effect: `available_time` may be **before**
`effective_time`. Daily-bar PIT still requires
`available_time > observation_time`. Those are different clocks.

`list_corporate_actions(..., as_of=)` keeps rows with
`available_time <= as_of`. It does not apply splits to bars.

`create_corporate_action()` validates the type and UTC timestamps.

## What does not exist

- Mutation of silver OHLCV
- Dividend price factors
- Point-in-time symbol rewriting on `instruments`
- Cash-flow accounting or performance series
- Merger / spin-off / rights types
- Vendor corporate-action feeds

A `symbol_change` row is a fact you stored. The instrument natural key is
unchanged until a later phase defines a listing timeline.

## Fixtures

`tests/fixtures/corporate_actions.csv` is fictional. Load with
`load_corporate_actions_csv`.

## Derived view (Phase 6.0)

`quant_platform.research.normalization` can build a hashed local view
(`split_only` by default). Silver rows stay as ingested. Dividends are
informational only. That view is not a strategy and does not compute
period results.
