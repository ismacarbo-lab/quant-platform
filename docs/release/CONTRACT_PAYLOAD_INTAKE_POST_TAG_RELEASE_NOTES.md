# Contract payload intake post-tag release notes — Phase 8.2

Archive notes for the research-only **offline contract payload intake
bridge** tag. This is **not** a trading system, there is **no
trading**, **no internet**, and **no vendors reales**. It does **not**
compute PnL or returns. There is **no** AI runtime.

Related: [CONTRACT_PAYLOAD_INTAKE_REMOTE_RELEASE_VERIFICATION.md](CONTRACT_PAYLOAD_INTAKE_REMOTE_RELEASE_VERIFICATION.md),
[CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md),
[DATA_CONTRACT_SCHEMA_COMPATIBILITY.md](../data/DATA_CONTRACT_SCHEMA_COMPATIBILITY.md),
[DATA_CONTRACT_CONFORMANCE.md](../data/DATA_CONTRACT_CONFORMANCE.md),
[DATA_SOURCE_CONTRACTS.md](../data/DATA_SOURCE_CONTRACTS.md),
[COMMANDS.md](COMMANDS.md),
[DATA_CONTRACT_SCHEMA_POST_TAG_RELEASE_NOTES.md](DATA_CONTRACT_SCHEMA_POST_TAG_RELEASE_NOTES.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Operational head remains
`0010_normalized_dataset_catalog`. Historical tags stay in place:

- `v0.1.0-research` at `0009_backtest_experiments`
- `v0.2.0-research-normalization` on the normalization add-on
- `v0.3.0-research-data-contracts` on the contracts/conformance add-on
- `v0.4.0-research-data-contract-schemas` on the schema baseline add-on

Do **not** create another tag from this document. Do **not** move
`v0.5.0-research-intake-bridge`.

## Closure timestamp

- Local: `2026-09-04T13:53:10+02:00`
- Workspace: `/home/isma/invest`
- Git directory: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used
- `AI_VENTURE_OS_PROMPTS/` was **not** modified

## Tag

| Item | Value |
|------|--------|
| Tag | `v0.5.0-research-intake-bridge` |
| Kind | annotated |
| Tag object | `5e0e92badb179bbc383f9845eede3e93cbb12606` |
| Message | Research contract payload intake bridge release |
| TaggerDate | 2026-09-04 13:51:02 +0200 |
| Local | present (`git tag --list "v0.5.0-research-intake-bridge"`) |
| Remote `origin` | present (`git ls-remote --tags origin v0.5.0-research-intake-bridge`) |

`git ls-remote` shows the **tag object** SHA, not the peeled commit.
Peel with `git rev-parse v0.5.0-research-intake-bridge^{commit}`.

No other `v0.5*` tag exists.

## Commit pointed by the tag

| Item | Value |
|------|--------|
| Peeled commit | `807bd6b4f19afd57141981ef664a25b205d6cfb1` |
| Subject | Add offline contract payload intake bridge |
| Branch | `main` |
| Remote | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Alembic head | `0010_normalized_dataset_catalog` |

The tag represents:

- `APP_MODE=research` only
- vendor-agnostic data contracts
- schema compatibility baseline
- offline contract payload intake bridge
- dry-run by default
- PostgreSQL write explicit with `--write-db`
- raw capture before silver
- PIT preserved
- `vendor_runtime=none`
- `external_market_data_vendors=disabled`
- no vendors reales
- no internet
- no trading
- no PnL/returns
- no IA runtime

## Current `main` (docs after the tag)

| Item | Value |
|------|--------|
| `HEAD` / `origin/main` | `87ade756a6e683b27ad339db3dd68524e60adb29` |
| Subject | Document contract payload intake release verification |
| Working tree at verification start | clean |

`main` is one commit **ahead** of the tagged commit: the Phase 8.1
verification note. The tag still peels to
`807bd6b4f19afd57141981ef664a25b205d6cfb1`. That is expected. Do not
move the tag onto this documentation commit.

## Checks executed (this phase)

From `/home/isma/invest`, `APP_MODE=research`:

- `git status --short` — empty before these notes
- `git branch --show-current` — `main`
- `git fetch origin` then `git status -sb` — `main...origin/main`
- `git log -1 --oneline` — `87ade75 Document contract payload intake release verification`
- `git tag --list "v0.5.0-research-intake-bridge"` — present
- `git show --no-patch --format=fuller v0.5.0-research-intake-bridge` — annotated tag → `807bd6b`
- `git ls-remote --tags origin v0.5.0-research-intake-bridge` — tag object `5e0e92ba…`
- `make research-status`
- `make normalization-status`
- `make contract-payload-intake-regression`
- `make research-release-check`
- `uv run pytest tests/unit/test_contract_payload_intake.py`
- `docker compose config`

## Local check results

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `contract_payload_intake_supported=true`, `contract_payload_intake_default=dry_run`, `data_contract_schema_compatibility_status=compatible`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
| `make normalization-status` | `ok=true`, `expected_table=normalized_datasets` |
| `make contract-payload-intake-regression` | 5/5 passed |
| Intake regression hash | `sha256:109d98a0434206ff9f73a67eab369c47b6dc6c7faddb932007d22c07bb8dc5ad` |
| Schema compatibility report hash (Phase 8.1 / tag CI) | `sha256:e45bbe232923f5388364fdaa2cc7052c4a6abc6025d67e627894ab8a51045d48` |
| Conformance regression hash (Phase 8.1 / tag CI) | `sha256:a3aa433dc7339d69562913cee616ba7827583cf4282cf8ace357293769438113` |
| Policy regression hash (Phase 8.1 / tag CI) | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| Normalization regression hash (Phase 8.1 / tag CI) | `sha256:b2289d6d2640073f3e5c7b57b4c2a017c2059f0c7ca536d699650319ecc00685` |
| `make research-release-check` | `ok=true`, `trading_constructs=none`, `ai_runtime=none` |
| `uv run pytest tests/unit/test_contract_payload_intake.py` | 17 passed (before this note's extra test) |
| `docker compose config` | OK |

Default intake remains **dry-run**. PostgreSQL writes require explicit
`--write-db`. Isolated postgres tests already assert that a second
write does not duplicate silver `daily_bars` and does not rewrite
OHLCV or PIT timestamps. Raw `payload_hash` is preserved.

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This add-on is an **offline intake bridge**. There is **no
trading**, **no internet**, and **no vendors reales**. There is
**no PnL/returns**.

## CI status

`gh` authenticated for this check. Tag push and later `main` docs push:

| Run | Event | Conclusion | URL |
|-----|-------|------------|-----|
| `33869889575` | push tag `v0.5.0-research-intake-bridge` (`807bd6b`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33869889575 |
| `33869870045` | push `main` (`87ade75`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33869870045 |

Jobs on both: `lint-typecheck-fast-tests` and `postgres-integration` green.
`--log-failed` on the tag run was empty.

If CLI auth breaks later, check the Actions tab for branch/tag
`v0.5.0-research-intake-bridge` and branch `main`.

## Remaining risks

Unchanged register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only,
normalized catalog metadata-only, no portfolio/PnL, no trading, local
artifact dirs, manual goldens (policy, normalization, conformance,
schema baseline, and intake), no automatic downloads, evidence ≠
profitability, accidental git at `/home/isma`, keep
`AI_VENTURE_OS_PROMPTS/` separate, rate limits/licensing unimplemented
for any future adapter.

The tag does **not** remove those risks. There is **no PnL/returns**.
`--write-db` stays explicit. Silver `daily_bars` are not rewritten.
Node.js 20 deprecation annotations on CI remain warnings, not failures.

## Tag rollback (do not run unless the tag must be withdrawn)

```bash
cd /home/isma/invest
git tag -d v0.5.0-research-intake-bridge
git push origin :refs/tags/v0.5.0-research-intake-bridge
```

Deleting a published tag is disruptive. Prefer a later tag over rewriting
this one.

## Maintenance commands

```bash
cd /home/isma/invest
make research-status
make normalization-status
make contract-payload-intake-regression
make research-release-check
make quality
```

PostgreSQL (optional): `docker compose up -d`, `uv run alembic current`,
`uv run python scripts/check-db.py`, `uv run pytest -m postgres`.

Do not print connection URLs. Do not mix this repo with
`AI_VENTURE_OS_PROMPTS/`.
