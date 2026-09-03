# Data-contract add-on remote verification — Phase 7.2

Research-only operational check of the vendor-agnostic data source
contracts and offline conformance reports. This is **not** a trading
launch, **not** a strategy, and it does **not** compute PnL or returns.
There is **no trading**, **no internet**, **no vendors reales**, and
**no** AI runtime.

Related: [DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[COMMANDS.md](COMMANDS.md),
[REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md),
[NORMALIZATION_REMOTE_RELEASE_VERIFICATION.md](NORMALIZATION_REMOTE_RELEASE_VERIFICATION.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Current operational head is
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only. The freeze tag `v0.1.0-research` remains historical at
`0009_backtest_experiments`. Tag `v0.2.0-research-normalization` remains
historical on the normalization add-on.

This report is a **tag proposal only**. The annotated tag
`v0.3.0-research-data-contracts` was **not** created and was **not**
pushed.

## Verification timestamp

- Local: `2026-09-03T12:33:32+02:00`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `4dd805f9acb72ea03e812db2b39bf072b5ddd3a1` |
| Subject | Add offline data contract conformance reports |
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
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `data_contract_conformance_supported=true`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets`, `dividend_policy=informational only` |
| `make research-release-check` | `ok=true`, errors=0, `trading_constructs=none`, `ai_runtime=none` |
| `make policy-regression` | 18/18 passed |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make normalization-regression` | 6/6 passed |
| Normalization regression hash | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make data-contract-conformance-regression` | 5/5 passed |
| Conformance regression hash | `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| `make data-contract-conformance` | `ok=true`, fake-provider batch, 0 issues |
| `make quality` | ruff / format-check / mypy / 400 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 294 files already formatted |
| `uv run mypy src` | 120 files, no issues |
| `uv run pytest` | 401 passed (postgres tests skipped in this invocation) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This verification note adds one consistency test. After that test,
`make quality` reports 401 fast tests. The proposed tag still points at
`4dd805f`, which does not include this note.

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

## Data-contract add-on

Vendor-agnostic contracts and offline conformance reports are present.
There is **no internet** client and **no vendors reales**.

| Check | Result |
|-------|--------|
| Capability `vendor_agnostic_data_contracts` | enabled |
| Capability `data_contract_conformance` | enabled |
| Capability `external_market_data_vendors` | disabled |
| `vendor_runtime` | none |
| Contracts package HTTP imports (`requests` / `httpx` / `aiohttp` / `urllib.request`) | none |
| Real vendor modules under `data/contracts` | none |

Default fake-provider conformance report:

- `ok=true`
- `conformance_hash=sha256:ab474d11a92177aa624575e378118b04e0974f566345c4f01a447ab52b848725`
- `batch_hash=sha256:44ab3eeeda7ca7197e94b6582fdea0b92ec413515f094c7ad5860875fae2b70a`

This does **not** mean profitability. There is **no PnL/returns**.

## CI remote

GitHub CLI (`gh`) is installed and authenticated for `github.com`
(`ismacarbo-lab`, protocol ssh). Tokens were not printed.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33744756813` |
| Title | Add offline data contract conformance reports |
| Event | push |
| Head SHA | `4dd805f9acb72ea03e812db2b39bf072b5ddd3a1` |
| Conclusion | success |
| Duration | 1m10s |
| Started | 2026-09-03T10:31:27Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33744756813 |

Jobs:

- `lint-typecheck-fast-tests` — success
- `postgres-integration` — success

`gh run view 33744756813 --log-failed` produced no failed-step logs.

Annotations (non-blocking): GitHub Actions Node.js 20 deprecation
warning on `actions/checkout@v4` and `astral-sh/setup-uv@v6`.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.3.0-research-data-contracts`

Meaning: research-only vendor-agnostic data contracts and offline
conformance add-on at commit
`4dd805f9acb72ea03e812db2b39bf072b5ddd3a1`.

It represents:

- `APP_MODE=research` only
- Alembic head `0010_normalized_dataset_catalog`
- vendor-agnostic data contracts
- offline payload validation
- offline conformance reports
- conformance regression matrix
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
git tag -a v0.3.0-research-data-contracts -m "Research data contracts release"
git push origin v0.3.0-research-data-contracts
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.3.0-research-data-contracts
git push origin :refs/tags/v0.3.0-research-data-contracts
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only, no
portfolio/PnL, no trading, local artifact directories, manual goldens
(policy, normalization, and data-contract conformance), no automatic
downloads, evidence ≠ profitability, accidental git at `/home/isma`,
keep `AI_VENTURE_OS_PROMPTS/` separate, rate limits/licensing still
unimplemented for any future adapter.

Added operational notes from this check:

- Tag candidate is `4dd805f`; this verification note is uncommitted
  documentation and is not part of the proposed tag commit.
- Node.js 20 deprecation annotations on CI are warnings, not failures.
- Catalog usability still needs the local artifact folder (R5b / R8).

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime. No real vendor HTTP clients. No automatic
downloads. Silver `daily_bars` are not mutated by this add-on.
