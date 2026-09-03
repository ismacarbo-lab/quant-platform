# Data-contract post-tag release notes — Phase 7.3

Archive notes for the research-only data-contracts tag. This is **not** a
trading system, there is **no trading**, **no internet**, and **no
vendors reales**. It does **not** compute PnL or returns. There is
**no** AI runtime.

Related: [DATA_CONTRACT_REMOTE_RELEASE_VERIFICATION.md](DATA_CONTRACT_REMOTE_RELEASE_VERIFICATION.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[COMMANDS.md](COMMANDS.md),
[POST_TAG_RELEASE_NOTES.md](POST_TAG_RELEASE_NOTES.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Operational head remains
`0010_normalized_dataset_catalog`. The freeze tag `v0.1.0-research`
stays historical at `0009_backtest_experiments`. Tag
`v0.2.0-research-normalization` stays historical on the normalization
add-on.

Do **not** create another tag from this document. Do **not** move
`v0.3.0-research-data-contracts`.

## Closure timestamp

- Local: `2026-09-03T12:39:46+02:00`
- Workspace: `/home/isma/invest`
- Git directory: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used
- `AI_VENTURE_OS_PROMPTS/` was **not** modified

## Tag

| Item | Value |
|------|--------|
| Tag | `v0.3.0-research-data-contracts` |
| Kind | annotated |
| Tag object | `5a4bae611982847fd5412684b4437bd741e99469` |
| Message | Research data contracts release |
| TaggerDate | 2026-09-03 12:38:36 +0200 |
| Local | present (`git tag --list "v0.3.0-research-data-contracts"`) |
| Remote `origin` | present (`git ls-remote --tags origin v0.3.0-research-data-contracts`) |

`git ls-remote` shows the **tag object** SHA, not the peeled commit.
Peel with `git rev-parse v0.3.0-research-data-contracts^{commit}`.

No other `v0.3*` tag exists.

## Commit pointed by the tag

| Item | Value |
|------|--------|
| Peeled commit | `4dd805f9acb72ea03e812db2b39bf072b5ddd3a1` |
| Subject | Add offline data contract conformance reports |
| Branch | `main` |
| Remote | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Alembic head | `0010_normalized_dataset_catalog` |

## Current `main` (docs after the tag)

| Item | Value |
|------|--------|
| `HEAD` / `origin/main` | `04787d7f40f83fe31ea53f52baee93bdd916c1f0` |
| Subject | Document data contract release verification |
| Working tree at verification start | clean |

`main` is one commit **ahead** of the tagged commit: the Phase 7.2
verification note. The tag still peels to
`4dd805f9acb72ea03e812db2b39bf072b5ddd3a1`. That is expected. Do not
move the tag onto this documentation commit.

## Checks executed (this phase)

From `/home/isma/invest`, `APP_MODE=research`:

- `git status --short` — empty before these notes
- `git branch --show-current` — `main`
- `git fetch origin` then `git status -sb` — `main...origin/main`
- `git log -1 --oneline` — `04787d7 Document data contract release verification`
- `git tag --list "v0.3.0-research-data-contracts"` — present
- `git show --no-patch --format=fuller v0.3.0-research-data-contracts` — annotated tag → `4dd805f`
- `git ls-remote --tags origin v0.3.0-research-data-contracts` — tag object `5a4bae61…`
- `make research-status`
- `make normalization-status`
- `make data-contract-conformance-regression`
- `make research-release-check`
- `uv run pytest tests/unit/test_data_contract_conformance.py`
- `docker compose config`

## Local check results

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `data_contract_conformance_supported=true`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets` |
| `make data-contract-conformance-regression` | 5/5, `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| `make research-release-check` | `ok=true`, `trading_constructs=none`, `ai_runtime=none` |
| Policy regression hash (Phase 7.2 / tag CI) | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| Normalization regression hash (Phase 7.2 / tag CI) | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `uv run pytest tests/unit/test_data_contract_conformance.py` | 20 passed (before this note's extra test) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

## CI status

`gh` authenticated for this check. Tag push and later `main` docs push:

| Run | Event | Conclusion | URL |
|-----|-------|------------|-----|
| `33745417550` | push tag `v0.3.0-research-data-contracts` (`4dd805f`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33745417550 |
| `33745397286` | push `main` (`04787d7`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33745397286 |

Jobs on both: `lint-typecheck-fast-tests` and `postgres-integration` green.
`--log-failed` on the tag run was empty.

If CLI auth breaks later, check the Actions tab for branch/tag
`v0.3.0-research-data-contracts` and branch `main`.

## Remaining risks

Unchanged register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only,
normalized catalog metadata-only, no portfolio/PnL, no trading, local
artifact dirs, manual goldens (policy, normalization, conformance), no
automatic downloads, evidence ≠ profitability, accidental git at
`/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate, rate
limits/licensing unimplemented for any future adapter.

The tag does **not** remove those risks. There is **no PnL/returns**.

## Tag rollback (do not run unless the tag must be withdrawn)

```bash
cd /home/isma/invest
git tag -d v0.3.0-research-data-contracts
git push origin :refs/tags/v0.3.0-research-data-contracts
```

Deleting a published tag is disruptive. Prefer a later tag over rewriting
this one.

## Maintenance commands

```bash
cd /home/isma/invest
make research-status
make normalization-status
make data-contract-conformance-regression
make research-release-check
make quality
```

PostgreSQL (optional): `docker compose up -d`, `uv run alembic current`,
`uv run python scripts/check-db.py`, `uv run pytest -m postgres`.

Do not print connection URLs. Do not mix this repo with
`AI_VENTURE_OS_PROMPTS/`.
