# Normalization add-on remote verification — Phase 6.5

Research-only operational check of the normalization add-on. This is
**not** a trading launch, **not** a strategy, and it does **not** compute
PnL or returns. There is **no trading** and **no** AI runtime.

Related: [NORMALIZATION_ADDON_VERIFICATION.md](NORMALIZATION_ADDON_VERIFICATION.md),
[RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md),
[COMMANDS.md](COMMANDS.md),
[REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Current operational head is
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only (no OHLCV columns; no normalized-bar table). The freeze
tag `v0.1.0-research` remains historical at `0009_backtest_experiments`.

This report is a **tag proposal only**. The annotated tag
`v0.2.0-research-normalization` was **not** created and was **not**
pushed.

## Verification timestamp

- Local: `2026-09-03T11:04:00+02:00`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `83610f2131b7bd69ce5a15e455f7b92ab21144f4` |
| Subject | Add idempotent evidence fixture reuse |
| `HEAD` vs `origin/main` | identical (0 ahead, 0 behind after `git fetch`) |
| Working tree at verification start | clean |
| `AI_VENTURE_OS_PROMPTS/` | not modified (mtime 2026-08-18) |
| `AI_VENTURE_OS_PROMPTS.zip` | not modified (mtime 2026-08-12) |

`git status --short` was empty before this report was written.

## Local checks

Run from `/home/isma/invest` with `APP_MODE=research`.

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `evidence_bundle_fixture_reuse_supported=true`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets`, `dividend_policy=informational only` |
| `make research-release-check` | `ok=true`, errors=0, `trading_constructs=none`, `ai_runtime=none` |
| `make policy-regression` | 18/18 passed |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make normalization-regression` | 6/6 passed |
| Normalization regression hash | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make quality` | ruff / format-check / mypy / 360 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 273 files already formatted |
| `uv run mypy src` | 107 files, no issues |
| `uv run pytest` | 510 passed (includes this note's consistency test) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, and AI runtime.

## PostgreSQL / Alembic

Local Compose Postgres was already running (`Up`, healthy). `docker compose
up -d` was not required to start a new container. Alembic was already at
head, so `upgrade head` was a no-op relative to `alembic current`.

| Check | Result |
|-------|--------|
| Expected head | `0010_normalized_dataset_catalog` |
| `uv run alembic current` | `0010_normalized_dataset_catalog (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| Public table `normalized_datasets` | present, metadata-only |
| Normalized bar table | absent |
| `normalization-status.py --check-db` | `ok=true`, `database_table_present=true` |
| `uv run pytest -m postgres` | 150 passed |

Connection strings were not printed. Isolated postgres tests include
reuse of matching fixtures and assert silver `daily_bars` are not
rewritten.

## Evidence bundle with explicit reuse

Command (shared local PostgreSQL, output `/tmp/research-evidence-bundle-65`):

```bash
uv run python scripts/build-research-evidence-bundle.py \
  --fixture-dir tests/fixtures/e2e_research_bundle \
  --output-dir /tmp/research-evidence-bundle-65 \
  --policy-name data_quality \
  --deterministic-id \
  --include-normalized-dataset \
  --register-normalized-dataset \
  --allow-existing-fixture-data \
  --json

uv run python scripts/verify-research-evidence-bundle.py \
  --bundle-dir /tmp/research-evidence-bundle-65 \
  --json
```

Operator **build** on this shared database: `ok=false`,
`fixture_data_mode=failed`. Ingest inserted 0 new bars (expected on a
reused DB). `--allow-existing-fixture-data` then verified existing rows
against the canonical E2EA fixtures and **rejected** reuse. Issue codes:

- `extra_bar` — existing original daily bars are not equivalent to the fixture
- `missing_correction` — an existing correction bar does not match the fixture
- `corporate_action_mismatch`
- `missing_calendar`

Cause: leftover rows under source `e2e_local_csv` / calendar `E2E_EQUITY`
from earlier operator and mixed fixture runs. PIT constraints were **not**
changed. The database was **not** truncated or reset.

Operator **verify** of the written (failed) bundle artifacts:
`ok=true` (integrity of relative paths, hashes, and forbidden terms). That
does **not** mean the research pack succeeded.

Isolated `pytest -m postgres` remains the CI path. Those tests cover first
insert, strict second-run failure, matching reuse, OHLCV/CA/session
mismatch, normalized-dataset opt-in with reuse, and no trading tables.

A green isolated bundle still does **not** mean profitability. There is
no PnL and no returns engine.

## CI remote

GitHub CLI (`gh`) is installed and authenticated for `github.com`
(`ismacarbo-lab`, protocol ssh). Tokens were not printed.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33736558272` |
| Title | Add idempotent evidence fixture reuse |
| Event | push |
| Head SHA | `83610f2131b7bd69ce5a15e455f7b92ab21144f4` |
| Conclusion | success |
| Duration | 54s |
| Started | 2026-09-03T09:01:35Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33736558272 |

Jobs:

- `lint-typecheck-fast-tests` — success
- `postgres-integration` — success

`gh run view 33736558272 --log-failed` produced no failed-step logs.

Two **older** `main` runs (not this HEAD) failed and are superseded:

| Run | Commit | Conclusion |
|-----|--------|------------|
| `33735082308` | `f545e68` Sync normalization release documentation | failure (`postgres-integration` PostgreSQL tests; `lint-typecheck-fast-tests` Ruff lint) |
| `33735058672` | `4b0052d` Sync normalization release documentation | failure (`lint-typecheck-fast-tests` Ruff lint; postgres job succeeded) |

Those commits were incomplete intermediate snapshots of the fixture-reuse
work. HEAD `83610f2` is green.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.2.0-research-normalization`

Meaning: research-only normalization add-on at commit
`83610f2131b7bd69ce5a15e455f7b92ab21144f4`.

It represents:

- `APP_MODE=research` only
- Alembic head `0010_normalized_dataset_catalog`
- `normalized_datasets` metadata-only
- idempotent evidence-bundle reuse (explicit flag)
- no trading
- no PnL / no returns
- no IA runtime

It does **not** mark paper trading, live trading, or an AI runtime.

### Create (do not run until approved)

```bash
cd /home/isma/invest
git tag -a v0.2.0-research-normalization -m "Research normalization add-on release"
git push origin v0.2.0-research-normalization
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.2.0-research-normalization
git push origin :refs/tags/v0.2.0-research-normalization
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only, no
portfolio/PnL, no trading, local artifact directories, manual goldens, no
automatic downloads, evidence ≠ profitability, accidental git at
`/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate.

Added operational notes from this check:

- Shared local Postgres can hold leftover `e2e_local_csv` rows that do
  not match the canonical fixtures; `--allow-existing-fixture-data`
  then fails closed (correct). Isolated `pytest -m postgres` is the CI
  evidence path.
- Intermediate commits `4b0052d` / `f545e68` failed CI; do not tag them.
- Catalog usability still needs the local artifact folder (R5b / R8).

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime.
