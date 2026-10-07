# Paper trading (fictional money)

Module: `quant_platform.paper`. Script: `scripts/paper-run.py`
(`make paper-run`, `make paper-replay FROM=YYYY-MM-DD`). API:
`GET /api/paper/accounts`, `GET /api/paper/accounts/{name}`,
`GET /api/paper/accounts/{name}/equity`, `POST /api/paper/run`,
`POST /api/paper/accounts`, `POST /api/paper/accounts/{name}/status`.

Requires `APP_MODE=paper`. In `research` mode the paper endpoints are
read-only (mutations return 409) and the engine refuses to start.

## Accounts

On the first run one account per strategy in `PAPER_DEFAULT_STRATEGIES`
is created with `PAPER_INITIAL_CASH` (100,000 USD by default): the
"paper horse race". Each account has its own rebalance frequency, costs
and benchmark symbol (SPY).

## Daily run for session `D`

1. **Fill** the orders decided at the previous run at `D`'s raw open
   through the `BrokerAdapter`. `SimulatedBroker` applies slippage
   (buys pay more, sells receive less), charges commission, executes
   sells before buys and caps buys at the available cash. Nothing goes
   short or levered.
2. **Dividends** whose ex-date is `D` are credited in cash for held
   positions.
3. **Mark to market** at `D`'s close; store an equity snapshot with cash,
   positions value, daily return, benchmark equity and weights.
4. **Decide**: if `D` is a rebalance session (or the account has never
   been invested) the strategy computes target weights from prices
   `<= D` and market orders are queued for the next session. Trades
   below 25 USD or 0.1% of equity are skipped.

Each `(account, session_date)` pair runs once (`paper_runs` unique
constraint); re-running is a no-op.

## Replay

`--replay-from 2024-01-02` runs every session from that date to the
latest available one, flagging all but the last as `replayed`, so a new
account gets a simulated track record immediately. Forward runs are the
real paper test. The dashboard shows the replay boundary.

## Scheduling

Run once per trading day after the US close, for example with cron:

```
30 23 * * 1-5  cd /home/isma/invest && make paper-run >> /tmp/paper-run.log 2>&1
```

`make paper-run` downloads the latest data first (`--fetch`).

## Tables (Alembic `0012`)

`paper_accounts`, `paper_runs`, `paper_orders`, `paper_fills`,
`paper_positions`, `paper_equity_snapshots`. No real broker, no
credentials, no live mode.
