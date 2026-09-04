# Contract payload intake remote verification — Phase 8.1

Research-only operational check of the vendor-agnostic data source
contracts, schema compatibility baseline, and the **offline contract
payload intake bridge**. This is **not** a trading launch, **not** a
strategy, and it does **not** compute PnL or returns. There is
**no trading**, **no internet**, **no vendors reales**, and **no** AI
runtime.

Related: [CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[COMMANDS.md](COMMANDS.md),
[DATA_CONTRACT_SCHEMA_REMOTE_RELEASE_VERIFICATION.md](DATA_CONTRACT_SCHEMA_REMOTE_RELEASE_VERIFICATION.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Current operational head is
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only. Historical tags stay in place:

- `v0.1.0-research` at `0009_backtest_experiments`
- `v0.2.0-research-normalization` on the normalization add-on
- `v0.3.0-research-data-contracts` on the contracts/conformance add-on
- `v0.4.0-research-data-contract-schemas` on the schema baseline add-on

This report is a **tag proposal only**. The annotated tag
`v0.5.0-research-intake-bridge` was **not** created and was **not**
pushed.

## Verification timestamp

- Local: `2026-09-04T13:47:51+02:00`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `807bd6b4f19afd57141981ef664a25b205d6cfb1` |
| Subject | Add offline contract payload intake bridge |
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
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `data_contract_conformance_supported=true`, `data_contract_schema_baseline_supported=true`, `data_contract_schema_compatibility_status=compatible`, `contract_payload_intake_supported=true`, `contract_payload_intake_default=dry_run`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets`, `dividend_policy=informational only` |
| `make research-release-check` | `ok=true`, errors=0, `trading_constructs=none`, `ai_runtime=none` |
| `make policy-regression` | 18/18 passed |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make normalization-regression` | 6/6 passed |
| Normalization regression hash | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make data-contract-conformance-regression` | 5/5 passed |
| Conformance regression hash | `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| `make data-contract-schema-compatibility` | `compatible`, 0 issues |
| Schema compatibility report hash | `sha256:e45bbe232923f5388364fdaa2cc7052c4a6abc6025d67e627894ab8a51045d48` |
| `make contract-payload-intake-regression` | 5/5 passed |
| Intake regression hash | `sha256:109d98a0434206ff9f73a67eab369c47b6dc6c7faddb932007d22c07bb8dc5ad` |
| `make quality` | ruff / format-check / mypy / 436 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 317 files already formatted |
| `uv run mypy src` | 130 files, no issues |
| `uv run pytest` | 437 passed, 153 skipped (postgres marker skipped in that invocation) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This verification note adds one consistency test. After that test,
`make quality` reports 437 fast tests. The proposed tag still points at
`807bd6b`, which does not include this note.

## PostgreSQL / Alembic

Local Compose Postgres was already running. `docker compose up -d` left
the existing healthy container in place. Alembic was already at head.

| Check | Result |
|-------|--------|
| Expected head | `0010_normalized_dataset_catalog` |
| `uv run alembic current` | `0010_normalized_dataset_catalog (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| Public table `normalized_datasets` | present, metadata-only |
| `uv run pytest -m postgres` | 154 passed |

Connection strings were not printed. Isolated postgres tests assert
silver `daily_bars` are not rewritten on a second `--write-db`
execution: inserted counts drop to zero, skipped counts rise, and
OHLCV plus PIT timestamps stay identical. Raw `payload_hash` values
remain 64 hex characters.

`--write-db` was **not** run from the operator CLI during this check.
Database writes were exercised only inside the marked postgres tests.

## Intake bridge add-on

Vendor-agnostic contracts, the schema compatibility baseline, and the
offline intake bridge are present. Default is **dry-run**. PostgreSQL
writes require explicit `--write-db`. There is **no internet** client
and **no vendors reales**. There is **no PnL/returns**.

| Check | Result |
|-------|--------|
| Capability `vendor_agnostic_data_contracts` | enabled |
| Capability `data_contract_conformance` | enabled |
| Capability `data_contract_schema_baseline` | enabled |
| Capability `contract_payload_intake_offline` | enabled |
| Capability `external_market_data_vendors` | disabled |
| `vendor_runtime` | none |
| Default intake mode | dry-run (`write_db=false`, `db_executed=false`) |
| `--write-db` | explicit; required before any INSERT |
| Contracts package HTTP imports (`requests` / `httpx` / `aiohttp` / `urllib.request`) | none |
| Real vendor modules under `data/contracts` | none |
| Artifact paths | relative only |
| Secrets in intake JSON | none |
| Raw payload hash | preserved (`batch_hash` / `payload_hash`) |
| PIT | preserved (`available_time` / `observation_time` not rewritten) |

Dry-run fixture (`tests/fixtures/contract_payload_intake/valid_dry_run`):

- `ok=true`
- `write_db=false`
- `db_executed=false`
- `inserted_counts.total=0`
- `batch_hash=sha256:bc88c13ec1a1fdecab8ca008f8e6b293126a5af5909aad6fb6e1a1e64201d2a9`
- `intake_hash=sha256:d959e879f0e13c2cc00074151c6a9f44e8a373647e64b57b10aeb31c9022e816`
- plan / report / manifest written with relative artifact names only

This does **not** mean profitability. There is **no PnL/returns**.

## CI remote

GitHub CLI (`gh`) is installed and authenticated for `github.com`
(`ismacarbo-lab`, protocol ssh). Tokens were not printed.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33869303443` |
| Title | Add offline contract payload intake bridge |
| Event | push |
| Head SHA | `807bd6b4f19afd57141981ef664a25b205d6cfb1` |
| Conclusion | success |
| Duration | 57s |
| Started | 2026-09-04T11:43:39Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33869303443 |

Jobs:

- `lint-typecheck-fast-tests` — success
- `postgres-integration` — success

`gh run view 33869303443 --log-failed` produced no failed-step logs.

Annotations (non-blocking): GitHub Actions Node.js 20 deprecation
warning on `actions/checkout@v4` and `astral-sh/setup-uv@v6`.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.5.0-research-intake-bridge`

Meaning: research-only vendor-agnostic data contracts, schema
compatibility baseline, and offline contract payload intake bridge at
commit `807bd6b4f19afd57141981ef664a25b205d6cfb1`.

It represents:

- `APP_MODE=research` only
- Alembic head `0010_normalized_dataset_catalog`
- vendor-agnostic data contracts
- schema compatibility baseline
- offline contract payload intake bridge
- dry-run by default
- PostgreSQL write explicit with `--write-db`
- raw capture before silver
- PIT preserved
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
git tag -a v0.5.0-research-intake-bridge -m "Research contract payload intake bridge release"
git push origin v0.5.0-research-intake-bridge
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.5.0-research-intake-bridge
git push origin :refs/tags/v0.5.0-research-intake-bridge
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only, no
portfolio/PnL, no trading, local artifact directories, manual goldens
(policy, normalization, data-contract conformance, schema baseline, and
intake), no automatic downloads, evidence ≠ profitability, accidental
git at `/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate, rate
limits/licensing still unimplemented for any future adapter.

Added operational notes from this check:

- Tag candidate is `807bd6b`; this verification note is uncommitted
  documentation and is not part of the proposed tag commit.
- Node.js 20 deprecation annotations on CI are warnings, not failures.
- Intake goldens stay manual (R18); dry-run remains the default.
- `--write-db` is explicit and still does not rewrite existing silver
  `daily_bars`.
- Catalog usability still needs the local artifact folder (R5b / R8).

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime. No real vendor HTTP clients. No automatic
downloads. Silver `daily_bars` are not mutated by this add-on. No
silent database writes.
