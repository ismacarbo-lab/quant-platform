# Risk register — research freeze

Known limits of the frozen research stage. None of these are trading
incidents; they are product and operations risks if someone treats this
repo as a live system.

Related: [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

| ID | Risk | Impact | Current mitigation | Possible later phase |
|----|------|--------|--------------------|----------------------|
| R1 | PostgreSQL is mandatory | Catalogued runs cannot use SQLite; local work needs Compose or CI Postgres | Settings reject SQLite; `check-db.py`; Alembic on Postgres 16 | Managed Postgres for a later ops phase; still no SQLite |
| R2 | No market-data vendors | Coverage is only as good as local CSV | Local fixtures; no download client; release risk `no_data_vendors` | Optional vendor **behind** an ADR; never silent internet from tests |
| R3 | Fixtures are small | Evidence bundle is a smoke path, not a universe | Documented fictional `e2e_research_bundle` CSVs | Larger local fixtures; still not live market dumps by default |
| R4 | Silver corporate actions are stored, not applied | Reading `daily_bars` as split-adjusted still misleads | CA store + audit policy; derived view is explicit and hashed | Keep silver immutable; do not fold factors into ingestion |
| R5 | Normalization is split-only and local | Dividends, FX, and vendor CA feeds are absent; fixtures stay small | Phase 6.0 derived view; `dividend_not_adjusted`; no vendor client | Later dividend methodology only behind an ADR |
| R6 | No portfolio or PnL | Nobody can compute returns from this stack | Disabled capabilities; usability gates are integrity-only | Portfolio/PnL only after strategy + risk ADRs |
| R7 | No trading | Accidental “go live” would have no execution path — and must not gain one silently | `APP_MODE` research-only; architecture tests; no order tables | Paper/live only after brokers, risk, and human gates |
| R8 | Artifacts need local `--base-dir` / `--output-dir` | Lost folders break catalog verification | Relative paths in manifests; integrity checks reject traversal | Still local unless a later ADR allows object storage |
| R9 | Golden policy updates are manual | Hash drift can fail CI until a human copies expecteds | `--update-expected` writes actuals beside the matrix; `matrix.json` is hand-edited | Same discipline; do not auto-rewrite goldens |
| R10 | No automatic data downloads | Operators must supply CSV | Scripts refuse vendors; tests stay offline | Download clients remain prohibited until an ADR |
| R11 | Release evidence does not measure profitability | A green bundle can be mistaken for an edge | Evidence docs; risk `evidence_not_profitability`; no returns fields | Never treat integrity hashes as Sharpe or PnL |
| R12 | Accidental git at `/home/isma` | Commits can land outside this repo | Handoff and checklist: work only in `/home/isma/invest` | Keep the boundary; do not “fix” that foreign git from here |
| R13 | Venture OS tree beside the repo | Mixing products would leak unrelated prompts into quant | Do not touch `AI_VENTURE_OS_PROMPTS/` | Keep separate forever unless a dedicated ADR says otherwise |

Severity for all rows above is **accepted for this freeze**. The
mitigation is documentation plus tests, not a trading control.
