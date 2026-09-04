# Data-contract schema post-tag release notes — Phase 7.7

Archive notes for the research-only data-contract **schema compatibility
baseline** tag. This is **not** a trading system, there is **no
trading**, **no internet**, and **no vendors reales**. It does **not**
compute PnL or returns. There is **no** AI runtime.

Related: [DATA_CONTRACT_SCHEMA_REMOTE_RELEASE_VERIFICATION.md](DATA_CONTRACT_SCHEMA_REMOTE_RELEASE_VERIFICATION.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[COMMANDS.md](COMMANDS.md),
[DATA_CONTRACT_POST_TAG_RELEASE_NOTES.md](DATA_CONTRACT_POST_TAG_RELEASE_NOTES.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Operational head remains
`0010_normalized_dataset_catalog`. Historical tags stay in place:

- `v0.1.0-research` at `0009_backtest_experiments`
- `v0.2.0-research-normalization` on the normalization add-on
- `v0.3.0-research-data-contracts` on the contracts/conformance add-on

Do **not** create another tag from this document. Do **not** move
`v0.4.0-research-data-contract-schemas`.

## Closure timestamp

- Local: `2026-09-04T12:33:36+02:00`
- Workspace: `/home/isma/invest`
- Git directory: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used
- `AI_VENTURE_OS_PROMPTS/` was **not** modified

## Tag

| Item | Value |
|------|--------|
| Tag | `v0.4.0-research-data-contract-schemas` |
| Kind | annotated |
| Tag object | `e5425f5e32e781317977cbd12bebd9c2801e9aec` |
| Message | Research data contract schemas release |
| TaggerDate | 2026-09-04 12:31:49 +0200 |
| Local | present (`git tag --list "v0.4.0-research-data-contract-schemas"`) |
| Remote `origin` | present (`git ls-remote --tags origin v0.4.0-research-data-contract-schemas`) |

`git ls-remote` shows the **tag object** SHA, not the peeled commit.
Peel with `git rev-parse v0.4.0-research-data-contract-schemas^{commit}`.

No other `v0.4*` tag exists.

## Commit pointed by the tag

| Item | Value |
|------|--------|
| Peeled commit | `681ab7cbcba8af2a5f7a0045a4cdc383b07cc393` |
| Subject | Add data contract schema compatibility baseline |
| Branch | `main` |
| Remote | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Alembic head | `0010_normalized_dataset_catalog` |

## Current `main` (docs after the tag)

| Item | Value |
|------|--------|
| `HEAD` / `origin/main` | `486525006dca413a2c425b2876e45e7962a66b2e` |
| Subject | Document data contract schema release verification |
| Working tree at verification start | clean |

`main` is one commit **ahead** of the tagged commit: the Phase 7.6
verification note. The tag still peels to
`681ab7cbcba8af2a5f7a0045a4cdc383b07cc393`. That is expected. Do not
move the tag onto this documentation commit.

## Checks executed (this phase)

From `/home/isma/invest`, `APP_MODE=research`:

- `git status --short` — empty before these notes
- `git branch --show-current` — `main`
- `git fetch origin` then `git status -sb` — `main...origin/main`
- `git log -1 --oneline` — `4865250 Document data contract schema release verification`
- `git tag --list "v0.4.0-research-data-contract-schemas"` — present
- `git show --no-patch --format=fuller v0.4.0-research-data-contract-schemas` — annotated tag → `681ab7c`
- `git ls-remote --tags origin v0.4.0-research-data-contract-schemas` — tag object `e5425f5e…`
- `make research-status`
- `make normalization-status`
- `make data-contract-schema-compatibility`
- `make research-release-check`
- `uv run pytest tests/unit/test_data_contract_schema_compatibility.py`
- `docker compose config`

## Local check results

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `data_contract_schema_baseline_supported=true`, `data_contract_schema_compatibility_status=compatible`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets` |
| `make data-contract-schema-compatibility` | `compatible`, 0 issues, `sha256:e45bbe232923f5388364fdaa2cc7052c4a6abc6025d67e627894ab8a51045d48` |
| Schema bundle hash | `sha256:f52d704bb3c422bd318033f1ef7606a12098c0127c17bd434950009f3097648a` |
| Conformance regression hash (Phase 7.6 / tag CI) | `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| Policy regression hash (Phase 7.6 / tag CI) | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| Normalization regression hash (Phase 7.6 / tag CI) | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make research-release-check` | `ok=true`, `trading_constructs=none`, `ai_runtime=none` |
| `uv run pytest tests/unit/test_data_contract_schema_compatibility.py` | 15 passed (before this note's extra test) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This add-on is a **schema compatibility baseline**. There is **no
trading**, **no internet**, and **no vendors reales**. There is
**no PnL/returns**.

## CI status

`gh` authenticated for this check. Tag push and later `main` docs push:

| Run | Event | Conclusion | URL |
|-----|-------|------------|-----|
| `33863678333` | push tag `v0.4.0-research-data-contract-schemas` (`681ab7c`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33863678333 |
| `33863662266` | push `main` (`4865250`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33863662266 |

Jobs on both: `lint-typecheck-fast-tests` and `postgres-integration` green.
`--log-failed` on the tag run was empty.

If CLI auth breaks later, check the Actions tab for branch/tag
`v0.4.0-research-data-contract-schemas` and branch `main`.

## Remaining risks

Unchanged register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only,
normalized catalog metadata-only, no portfolio/PnL, no trading, local
artifact dirs, manual goldens (policy, normalization, conformance, and
schema baseline), no automatic downloads, evidence ≠ profitability,
accidental git at `/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate,
rate limits/licensing unimplemented for any future adapter.

The tag does **not** remove those risks. There is **no PnL/returns**.
Schema compatibility rules stay simple (not SemVer). Node.js 20
deprecation annotations on CI remain warnings, not failures.

## Tag rollback (do not run unless the tag must be withdrawn)

```bash
cd /home/isma/invest
git tag -d v0.4.0-research-data-contract-schemas
git push origin :refs/tags/v0.4.0-research-data-contract-schemas
```

Deleting a published tag is disruptive. Prefer a later tag over rewriting
this one.

## Maintenance commands

```bash
cd /home/isma/invest
make research-status
make normalization-status
make data-contract-schema-compatibility
make research-release-check
make quality
```

PostgreSQL (optional): `docker compose up -d`, `uv run alembic current`,
`uv run python scripts/check-db.py`, `uv run pytest -m postgres`.

Do not print connection URLs. Do not mix this repo with
`AI_VENTURE_OS_PROMPTS/`.
