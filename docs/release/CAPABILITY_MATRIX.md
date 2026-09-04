# Capability matrix — research freeze

This matrix is the freeze inventory for `quant_platform`. Implemented
does **not** mean profitable. Disabled and prohibited stay off until a
later ADR.

Operational Alembic head is `0010_normalized_dataset_catalog`
(`normalized_datasets` is metadata-only). The freeze tag
`v0.1.0-research` was cut at `0009_backtest_experiments`.

Related: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[RISK_REGISTER.md](RISK_REGISTER.md),
[ADR 0003](../adr/0003-research-mode-freeze.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md).

## Implemented

| Capability | What it does | What it is not |
|------------|--------------|----------------|
| Research mode | `APP_MODE=research` only | Not paper or live |
| Local CSV ingestion | PIT daily bars into PostgreSQL | Not a vendor download |
| PIT daily bars | `available_time`, corrections as new rows | Not rewritten history |
| Bronze / silver | Raw records + canonical bars | Not gold features |
| Instrument master | Symbol, asset class, exchange, currency | Not a broker account |
| Calendars / sessions | Manual open, holiday, exceptional_close | Not an exchange feed |
| Corporate action store | Facts stored; silver OHLCV unchanged | Not a vendor CA feed |
| CA normalization | Derived split / reverse-split view | Not a strategy; not dividend-adjusted; not performance |
| Normalization research layer | In-memory golden matrix + opt-in evidence artifacts | Not returns, PnL, or a walk-forward |
| Normalized dataset catalog | PostgreSQL metadata table `normalized_datasets` (metadata-only) | Not normalized bars in the DB; not returns |
| Dataset API | `as_of` required | Not a trading book |
| Dataset quality | Coverage, calendar, PIT, ingest notes | Not a score of edge |
| Snapshots | Local hashed CSV + quality + manifest | Not cloud object storage |
| Snapshot catalog | PostgreSQL metadata | Not event rows in the DB |
| Snapshot integrity | Read-only hash / path checks | Not a repair tool |
| Replay | Ordered market events | Not a strategy engine |
| Replay audit / registry | Stream hash, catalog row | Not PnL |
| Replay readiness | Gate for dry-run | Not a go-live |
| Dry-run backtest | Registered `ResearchPolicy` observer | Not orders or fills |
| Data-quality policies | `data_quality`, `coverage`, CA/correction audit | Not signals |
| Policy output integrity | Hashes and observation reports | Not returns |
| Experiments | Group dry-runs | Not a portfolio |
| Experiment usability | Intact evidence gate | Not profitability |
| Policy regression matrix | Golden hashes | Not a walk-forward |
| Release checks / status | Guardrails, Alembic pin | Not a trading launch |
| Evidence bundle | Fixture → release local pack | Not a performance report |
| Health endpoint | `GET /health` | Not a data or trade API |
| Vendor-agnostic data contracts | Offline payload types, validation, hash, fake provider | Not a vendor download; not credentials; not internet |
| Data-contract conformance | Offline reports, relative artifacts, golden regression | Not a vendor client; not returns/PnL; not trading |
| Data-contract schema baseline | Offline JSON schema export and compatibility compare | Not a vendor adapter; not internet; not returns/PnL |
| Contract-payload intake (offline) | Dry-run plan from a synthetic/fixture batch; optional `--write-db` through existing PIT ingest | Not a vendor download; not silent DB writes; not returns/PnL; not trading |

## Intentionally disabled

These names exist as **disabled** capabilities in release status. They
are not implemented.

- paper trading
- live trading
- brokers
- order execution
- portfolio
- positions
- PnL
- returns
- signals
- strategies
- fills
- trades
- AI runtime (OpenAI, Anthropic, LangChain, RAG)
- external market-data vendors
- SQLite fallback
- cloud object storage

`APP_MODE=paper` and `APP_MODE=live` fail settings validation.

## Explicitly prohibited (this freeze)

Do not add without a new ADR and a later phase spec:

- strategy / signal / alpha models
- buy / sell / hold or target weights
- orders, fills, trades, execution, brokers
- paper trading or live trading
- portfolio, positions, cash, PnL, returns
- drawdown, Sharpe, hit ratio, exposure as product metrics
- risk engine or optimizer
- ML training/inference runtime
- OpenAI, Anthropic, LangChain, RAG, Cursor SDK as app runtime
- external finance vendors or automatic data downloads
- HTTP routes beyond `GET /health`
- S3 / GCS / Azure object storage
- dynamic external policy plugins
- mixing this repo with `AI_VENTURE_OS_PROMPTS/`

## Future candidates

Only after an explicit ADR. Still research-first unless that ADR says
otherwise:

1. A real vendor **adapter behind this contract** (PIT, raw capture,
   hashed idempotence, secrets out of repo). Not a silent internet
   call from tests.
2. Richer **local** datasets (still no vendor client until that adapter
   ADR).
3. Dividend or FX restatement as another **derived** view (still not a
   strategy).
4. A strategy **interface** with no brokers, no orders, and no PnL
   until those layers exist.
5. Optional, default-off research assistant (see
   [ADR 0002](../adr/0002-ai-usage-boundary.md)) — never a trading brain.

Do not skip from this freeze to paper or live.
