# Normalization post-tag release notes — Phase 6.6

Archive notes for the research-only normalization tag. This is **not** a
trading system, there is **no trading**, and it does **not** compute PnL
or returns. There is **no** AI runtime.

Related: [NORMALIZATION_REMOTE_RELEASE_VERIFICATION.md](NORMALIZATION_REMOTE_RELEASE_VERIFICATION.md),
[NORMALIZATION_ADDON_VERIFICATION.md](NORMALIZATION_ADDON_VERIFICATION.md),
[COMMANDS.md](COMMANDS.md),
[POST_TAG_RELEASE_NOTES.md](POST_TAG_RELEASE_NOTES.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Operational head remains
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only. The freeze tag `v0.1.0-research` stays historical at
`0009_backtest_experiments`.

Do **not** create another tag from this document.

## Closure timestamp

- Local: `2026-09-03T11:37:42+02:00`
- Workspace: `/home/isma/invest`
- Git directory: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used
- `AI_VENTURE_OS_PROMPTS/` was **not** modified

## Tag

| Item | Value |
|------|--------|
| Tag | `v0.2.0-research-normalization` |
| Kind | annotated |
| Tag object | `7697649b49cd77248a18e95ca12589d8e295f893` |
| Message | Research normalization add-on release |
| TaggerDate | 2026-09-03 11:35:59 +0200 |
| Local | present (`git tag --list "v0.2.0-research-normalization"`) |
| Remote `origin` | present (`git ls-remote --tags origin v0.2.0-research-normalization`) |

`git ls-remote` shows the **tag object** SHA, not the peeled commit.
Peel with `git rev-parse v0.2.0-research-normalization^{commit}`.

No other tag was created in this phase.

## Commit pointed by the tag

| Item | Value |
|------|--------|
| Peeled commit | `83610f2131b7bd69ce5a15e455f7b92ab21144f4` |
| Subject | Add idempotent evidence fixture reuse |
| Branch | `main` |
| Remote | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Alembic head | `0010_normalized_dataset_catalog` |

## Current `main` (docs after the tag)

| Item | Value |
|------|--------|
| `HEAD` / `origin/main` | `22bc6df4473fc9d0592ae75e7648eb7e42b825e1` |
| Subject | Document normalization release verification |
| Working tree at verification start | clean |

`main` is one commit **ahead** of the tagged commit: the Phase 6.5
verification note. The tag still peels to
`83610f2131b7bd69ce5a15e455f7b92ab21144f4`. That is expected and
research-only either way.

## Checks executed (this phase)

From `/home/isma/invest`, `APP_MODE=research`:

- `git status --short` — empty before these notes
- `git branch --show-current` — `main`
- `git log -1 --oneline` — `22bc6df Document normalization release verification`
- `git tag --list "v0.2.0-research-normalization"` — present
- `git show --no-patch --format=fuller v0.2.0-research-normalization` — annotated tag → `83610f2`
- `git ls-remote --tags origin v0.2.0-research-normalization` — tag object `7697649b…`
- `make research-status`
- `make normalization-status`
- `make normalization-regression`
- `make research-release-check`
- `docker compose config`

## Local check results

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_fixture_reuse_supported=true`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets`, `dividend_policy=informational only` |
| `make normalization-regression` | 6/6, `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make research-release-check` | `ok=true`, `trading_constructs=none`, `ai_runtime=none` |
| Policy regression hash (Phase 6.5 / tag CI) | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, and AI runtime.

## CI status

`gh` authenticated for this check. Tag push and later `main` docs push:

| Run | Event | Conclusion | URL |
|-----|-------|------------|-----|
| `33739751100` | push tag `v0.2.0-research-normalization` (`83610f2`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33739751100 |
| `33739727641` | push `main` (`22bc6df`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33739727641 |

Jobs on both: `lint-typecheck-fast-tests` and `postgres-integration` green.
`--log-failed` on the tag run was empty.

## Evidence reuse status

Known from Phase 6.5 and unchanged by this tag:

- Isolated `pytest -m postgres` covers explicit fixture reuse and keeps
  silver `daily_bars` unmutated.
- Operator reuse on the **shared** local database can fail closed when
  leftover `e2e_local_csv` rows are not equivalent to the canonical
  fixtures. That is correct. Do not relax PIT constraints or truncate
  the database to hide it.

## Remaining risks

Unchanged register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only,
normalized catalog metadata-only, no portfolio/PnL, no trading, local
artifact dirs, manual goldens, no automatic downloads, evidence ≠
profitability, accidental git at `/home/isma`, keep
`AI_VENTURE_OS_PROMPTS/` separate.

The tag does **not** remove those risks.

## Tag rollback (do not run unless the tag must be withdrawn)

```bash
cd /home/isma/invest
git tag -d v0.2.0-research-normalization
git push origin :refs/tags/v0.2.0-research-normalization
```

Deleting a published tag is disruptive. Prefer a later tag over rewriting
this one.

## Maintenance commands

```bash
cd /home/isma/invest
make research-status
make normalization-status
make normalization-regression
make research-release-check
make quality
```

PostgreSQL (optional): `docker compose up -d`, `uv run alembic current`,
`uv run python scripts/check-db.py`, `uv run pytest -m postgres`.

Do not print connection URLs. Do not mix this repo with
`AI_VENTURE_OS_PROMPTS/`.
