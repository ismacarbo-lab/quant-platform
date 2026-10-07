# Risk register — research freeze

Known limits of the frozen research stage. None of these are trading
incidents; they are product and operations risks if someone treats this
repo as a live system.

Operational Alembic head is `0010_normalized_dataset_catalog`. The
freeze tag `v0.1.0-research` was cut at `0009_backtest_experiments`.

Related: [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[ADR 0003](../adr/0003-research-mode-freeze.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md).

| ID | Risk | Impact | Current mitigation | Possible later phase |
|----|------|--------|--------------------|----------------------|
| R1 | PostgreSQL is mandatory | Catalogued runs cannot use SQLite; local work needs Compose or CI Postgres | Settings reject SQLite; `check-db.py`; Alembic on Postgres 16 | Managed Postgres for a later ops phase; still no SQLite |
| R2 | No market-data vendors | Coverage is only as good as local CSV | Offline vendor-agnostic contract; local fixtures; no download client; release risk `no_data_vendors` | Optional vendor **adapter** behind a later ADR; never silent internet from tests |
| R3 | Fixtures are small | Evidence bundle is a smoke path, not a universe | Documented fictional `e2e_research_bundle` CSVs | Larger local fixtures; still not live market dumps by default |
| R4 | Silver corporate actions are stored, not applied | Reading `daily_bars` as split-adjusted still misleads | CA store + audit policy; derived view is explicit and hashed | Keep silver immutable; do not fold factors into ingestion |
| R5 | Normalization is split-only and local | Dividends, FX, and vendor CA feeds are absent; fixtures stay small | Phase 6.0 derived view; dividends stay informational only (`dividend_not_adjusted`); Phase 6.1 golden matrix; no vendor client | Later dividend methodology only behind an ADR |
| R5a | Normalization goldens are manual | Hash drift can fail CI until a human copies `expected.json` | `--update-expected` writes actuals; goldens are hand-copied | Same discipline; do not auto-rewrite goldens |
| R5b | Normalized catalog is metadata-only | Operators may expect bars in PostgreSQL or treat a catalog row as a trading book | Table stores hashes/counts only; usability needs local artifacts; no returns/PnL | Keep silver immutable; do not add normalized-bar tables |
| R6 | No portfolio or PnL | Nobody can compute returns from this stack | Disabled capabilities; usability gates are integrity-only | Portfolio/PnL only after strategy + risk ADRs |
| R7 | No trading | Accidental “go live” would have no execution path — and must not gain one silently | `APP_MODE` research-only; architecture tests; no order tables | Paper/live only after brokers, risk, and human gates |
| R8 | Artifacts need local `--base-dir` / `--output-dir` | Lost folders break catalog verification | Relative paths in manifests; integrity checks reject traversal | Still local unless a later ADR allows object storage |
| R9 | Golden policy updates are manual | Hash drift can fail CI until a human copies expecteds | `--update-expected` writes actuals beside the matrix; `matrix.json` is hand-edited | Same discipline; do not auto-rewrite goldens |
| R10 | No automatic data downloads | Operators must supply CSV | Scripts refuse vendors; tests stay offline | Download clients remain prohibited until an ADR |
| R11 | Release evidence does not measure profitability | A green bundle can be mistaken for an edge | Evidence docs; risk `evidence_not_profitability`; no returns fields | Never treat integrity hashes as Sharpe or PnL |
| R12 | Accidental git at `/home/isma` | Commits can land outside this repo | Handoff and checklist: work only in `/home/isma/invest` | Keep the boundary; do not “fix” that foreign git from here |
| R13 | Venture OS tree beside the repo | Mixing products would leak unrelated prompts into quant | Do not touch `AI_VENTURE_OS_PROMPTS/` | Keep separate forever unless a dedicated ADR says otherwise |
| R14 | Shared local PostgreSQL already holds e2e fixtures | A second evidence-bundle ingest inserts 0 silver bars and looks like a failure | Strict default still fails; `--allow-existing-fixture-data` verifies equivalence then reuses; PIT constraints stay; no deletes or `daily_bars` rewrites | Keep verification-before-reuse; never silent conflict ignore |
| R15 | Rate limits and licensing unimplemented | A future adapter could hit vendor quotas or violate redistribution terms | Documented only (`vendor_rate_limits_unimplemented`); no HTTP client | Implement limits and license checks with the adapter ADR, not before |
| R16 | Conformance goldens are manual | Hash drift can fail CI until a human copies `expected.json` | `--update-expected` writes actuals; goldens are hand-copied; no vendor HTTP | Same discipline; do not auto-rewrite goldens |
| R17 | Schema baseline goldens are manual | Contract field or type drift can fail CI until a human copies `current_baseline.json` | Compatibility checker; goldens are hand-copied; no vendor HTTP | Same discipline; do not auto-rewrite goldens |
| R18 | Intake goldens are manual | Hash drift can fail CI until a human copies `expected.json` | `--update-expected` writes actuals; goldens are hand-copied; dry-run default; `--write-db` explicit | Same discipline; do not auto-rewrite goldens |
| R19 | Evidence-bundle intake is opt-in | Operators may expect every bundle to prove vendor intake, or may enable `--contract-intake-write-db` on a shared database | Default omit keeps existing hashes; dry-run unless the write flag is set; no vendor HTTP; `daily_bars` are not rewritten | Keep default off; never silent writes |
| R20 | Single free data vendor (Yahoo via yfinance) | Unofficial feed without SLA; outages, throttling or silent data revisions | Adapter is the only module importing `yfinance`; PIT availability; restatements stored as corrections; tests use recorded fixtures | Second vendor behind the same contract if needed |
| R21 | Vendor prices are split-adjusted | Emitting splits as corporate actions would double-adjust history | Splits are kept in bronze raw payload only; `total_return` applies dividends on top of vendor prices | Revisit if a raw-price vendor is added |
| R22 | Backtest overfitting | Parameter grids can look great in-sample | Anchored walk-forward with yearly OOS blocks; promotion rule uses OOS only; parameter stability reported | Keep grids small; never promote on in-sample metrics |
| R23 | Paper results are simulated | Fills at open plus fixed slippage ignore liquidity, partial fills and real broker behaviour | Costs are explicit and configurable; fictional cash; `BrokerAdapter` seam without a real implementation | A real broker only after a dedicated ADR with human gates |
| R24 | Benchmark dominance | In 2010–2026 buy-and-hold SPY beat every tactical strategy out of sample, so none is "apto para paper" | Dashboard shows benchmark next to every strategy; promotion verdict stored with reasons | Keep measuring forward; do not loosen the rule to force a winner |
| R25 | Replayed track records look like live results | A replay from 2024 is still a simulation on known history | Replayed sessions are flagged in `paper_runs` and snapshots and shown in the dashboard | Judge strategies on forward (non-replayed) sessions |

Severity for all rows above is **accepted for this freeze**. The
mitigation is documentation plus tests, not a trading control.
