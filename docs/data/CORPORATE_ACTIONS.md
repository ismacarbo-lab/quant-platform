# Corporate actions — Phase 1.4

Storage only. The platform records that an event exists. It does **not**
adjust OHLCV, rewrite history, or change `instruments.symbol`.

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

- Price or volume adjustments
- Point-in-time symbol rewriting on `instruments`
- Cash-flow accounting
- Merger / spin-off / rights types
- Vendor corporate-action feeds

A `symbol_change` row is a fact you stored. The instrument natural key is
unchanged until a later phase defines a listing timeline.

## Fixtures

`tests/fixtures/corporate_actions.csv` is fictional. Load with
`load_corporate_actions_csv`.

## Later phases

Applying actions to silver bars, adjusted return series, and listing
successor chains belong later. Do not treat stored events as an adjusted
price engine.
