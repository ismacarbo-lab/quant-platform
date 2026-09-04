# Data-contract schema baseline remote verification — Phase 7.6

Research-only operational check of the vendor-agnostic data source
contracts, offline conformance reports, and the **schema compatibility
baseline**. This is **not** a trading launch, **not** a strategy, and
it does **not** compute PnL or returns. There is **no trading**,
**no internet**, **no vendors reales**, and **no** AI runtime.

Related: [DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[COMMANDS.md](COMMANDS.md),
[DATA_CONTRACT_REMOTE_RELEASE_VERIFICATION.md](DATA_CONTRACT_REMOTE_RELEASE_VERIFICATION.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Current operational head is
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only. Historical tags stay in place:

- `v0.1.0-research` at `0009_backtest_experiments`
- `v0.2.0-research-normalization` on the normalization add-on
- `v0.3.0-research-data-contracts` on the contracts/conformance add-on

This report is a **tag proposal only**. The annotated tag
`v0.4.0-research-data-contract-schemas` was **not** created and was
**not** pushed.

## Verification timestamp

- Local: `2026-09-04T12:28:28+02:00`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `681ab7cbcba8af2a5f7a0045a4cdc383b07cc393` |
| Subject | Add data contract schema compatibility baseline |
| `HEAD` vs `origin/main` | identical (0 ahead, 0 behind after `git fetch`) |
| Working tree at verification start | clean |
| `AI_VENTURE_OS_PROMPTS/` | not modified (mtime 2026-08-18) |
| `AI_VENTURE_OS_PROMPTS.zip` | not modified (mtime 2026-08-12) |

`git status --short` was empty before this report was written.
`AI_VENTURE_OS_PROMPTS` is intact.

## Local checks

Run from `/home/isma/invest` with `APP_MODE=research`.

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `data_contract_conformance_supported=true`, `data_contract_schema_baseline_supported=true`, `data_contract_schema_compatibility_status=compatible`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets`, `dividend_policy=informational only` |
| `make research-release-check` | `ok=true`, errors=0, `trading_constructs=none`, `ai_runtime=none` |
| `make policy-regression` | 18/18 passed |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make normalization-regression` | 6/6 passed |
| Normalization regression hash | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make data-contract-conformance-regression` | 5/5 passed |
| Conformance regression hash | `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| `make data-contract-schema-export` | 7 schemas, bundle hash below |
| `make data-contract-schema-compatibility` | `compatible`, 0 issues |
| Schema compatibility report hash | `sha256:e45bbe232923f5388364fdaa2cc7052c4a6abc6025d67e627894ab8a51045d48` |
| `make quality` | ruff / format-check / mypy / 417 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 303 files already formatted |
| `uv run mypy src` | 123 files, no issues |
| `uv run pytest` | 567 passed (Postgres reachable in this invocation) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This verification note adds one consistency test. After that test,
`make quality` reports 418 fast tests. The proposed tag still points at
`681ab7c`, which does not include this note.

## PostgreSQL / Alembic

Local Compose Postgres was already running. `docker compose up -d` left
the existing healthy container in place. Alembic was already at head.

| Check | Result |
|-------|--------|
| Expected head | `0010_normalized_dataset_catalog` |
| `uv run alembic current` | `0010_normalized_dataset_catalog (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| Public table `normalized_datasets` | present, metadata-only |
| `uv run pytest -m postgres` | 150 passed |

Connection strings were not printed. Isolated postgres tests assert
silver `daily_bars` are not rewritten. This add-on does not write
financial rows.

## Schema export / compatibility add-on

Vendor-agnostic contracts, offline conformance, and the schema
compatibility baseline are present. There is **no internet** client
and **no vendors reales**. There is **no PnL/returns**.

| Check | Result |
|-------|--------|
| Capability `vendor_agnostic_data_contracts` | enabled |
| Capability `data_contract_conformance` | enabled |
| Capability `data_contract_schema_baseline` | enabled |
| Capability `external_market_data_vendors` | disabled |
| `vendor_runtime` | none |
| Contracts package HTTP imports (`requests` / `httpx` / `aiohttp` / `urllib.request`) | none |
| Real vendor modules under `data/contracts` | none |
| Current vs baseline | compatible, 0 issues |
| Artifact paths | relative only |
| Secrets in export JSON | none |

Exported schemas (7):

- `DataContractConformanceManifest`
- `DataContractConformanceReport`
- `DataSourceContract`
- `VendorCorporateActionPayload`
- `VendorDailyBarPayload`
- `VendorMarketSessionPayload`
- `VendorPayloadBatch`

Schema bundle hash:

`sha256:f52d704bb3c422bd318033f1ef7606a12098c0127c17bd434950009f3097648a`

This does **not** mean profitability. There is **no PnL/returns**.

## CI remote

GitHub CLI (`gh`) is installed and authenticated for `github.com`
(`ismacarbo-lab`, protocol ssh). Tokens were not printed.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33863077055` |
| Title | Add data contract schema compatibility baseline |
| Event | push |
| Head SHA | `681ab7cbcba8af2a5f7a0045a4cdc383b07cc393` |
| Conclusion | success |
| Duration | 57s |
| Started | 2026-09-04T10:24:28Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33863077055 |

Jobs:

- `lint-typecheck-fast-tests` — success
- `postgres-integration` — success

`gh run view 33863077055 --log-failed` produced no failed-step logs.

Annotations (non-blocking): GitHub Actions Node.js 20 deprecation
warning on `actions/checkout@v4` and `astral-sh/setup-uv@v6`.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.4.0-research-data-contract-schemas`

Meaning: research-only vendor-agnostic data contracts, offline
conformance, and schema compatibility baseline at commit
`681ab7cbcba8af2a5f7a0045a4cdc383b07cc393`.

It represents:

- `APP_MODE=research` only
- Alembic head `0010_normalized_dataset_catalog`
- vendor-agnostic data contracts
- offline payload validation
- offline conformance reports
- conformance regression matrix
- schema export offline
- schema compatibility baseline
- vendor/network guardrails
- no vendors reales
- no internet
- no trading
- no PnL/returns
- no IA runtime

It does **not** mark paper trading, live trading, a real vendor client,
or an AI runtime.

### Create (do not run until approved)

```bash
cd /home/isma/invest
git tag -a v0.4.0-research-data-contract-schemas -m "Research data contract schemas release"
git push origin v0.4.0-research-data-contract-schemas
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.4.0-research-data-contract-schemas
git push origin :refs/tags/v0.4.0-research-data-contract-schemas
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only, no
portfolio/PnL, no trading, local artifact directories, manual goldens
(policy, normalization, data-contract conformance, and schema baseline),
no automatic downloads, evidence ≠ profitability, accidental git at
`/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate, rate
limits/licensing still unimplemented for any future adapter.

Added operational notes from this check:

- Tag candidate is `681ab7c`; this verification note is uncommitted
  documentation and is not part of the proposed tag commit.
- Node.js 20 deprecation annotations on CI are warnings, not failures.
- Schema compatibility rules stay simple (not SemVer, no ADR parser).
- Catalog usability still needs the local artifact folder (R5b / R8).

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime. No real vendor HTTP clients. No automatic
downloads. Silver `daily_bars` are not mutated by this add-on.
