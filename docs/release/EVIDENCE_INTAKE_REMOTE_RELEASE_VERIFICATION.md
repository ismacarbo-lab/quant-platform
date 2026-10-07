# Evidence intake integration remote verification — Phase 8.5

Research-only operational check of the **opt-in contract payload
intake** step on the research **evidence bundle**. This is **not** a
trading launch, **not** a strategy, and it does **not** compute PnL or
returns. There is **no trading**, **no internet**, **no vendors reales**,
and **no** AI runtime.

Related: [RESEARCH_EVIDENCE_BUNDLE.md](RESEARCH_EVIDENCE_BUNDLE.md),
[CONTRACT_PAYLOAD_INTAKE.md](../data/CONTRACT_PAYLOAD_INTAKE.md),
[CONTRACT_PAYLOAD_INTAKE_REMOTE_RELEASE_VERIFICATION.md](CONTRACT_PAYLOAD_INTAKE_REMOTE_RELEASE_VERIFICATION.md),
[COMMANDS.md](COMMANDS.md),
[ADR 0004](../adr/0004-vendor-agnostic-data-source-contract.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Current operational head is
`0010_normalized_dataset_catalog`. Table `normalized_datasets` is
metadata-only. Historical tags stay in place:

- `v0.1.0-research` at `0009_backtest_experiments`
- `v0.2.0-research-normalization` on the normalization add-on
- `v0.3.0-research-data-contracts` on the contracts/conformance add-on
- `v0.4.0-research-data-contract-schemas` on the schema baseline add-on
- `v0.5.0-research-intake-bridge` on the offline intake bridge

This report is a **tag proposal only**. The annotated tag
`v0.6.0-research-evidence-intake` was **not** created and was **not**
pushed.

## Verification timestamp

- Local: `2026-10-07T08:00:21+02:00`
- Earlier draft of this note: `2026-09-05T11:42:17+02:00` (same commit, same hashes)
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `346b92b054a56a5244a1735919e61e90498f231e` |
| Subject | Integrate contract payload intake into evidence bundle |
| `HEAD` vs `origin/main` | identical (0 ahead, 0 behind after `git fetch`) |
| Working tree at verification start | this uncommitted Phase 8.5 note plus its unit test |
| `AI_VENTURE_OS_PROMPTS/` | not modified (mtime 2026-08-18) |
| `AI_VENTURE_OS_PROMPTS.zip` | not modified (mtime 2026-08-12) |

`HEAD` matched `origin/main` on `346b92b`. The only local delta is
this verification note and `tests/unit/test_evidence_bundle.py`.
`AI_VENTURE_OS_PROMPTS` is intact. Tag `v0.5.0-research-intake-bridge`
still peels to `807bd6b4f19afd57141981ef664a25b205d6cfb1` and was **not**
moved. No `v0.6*` tag exists locally or on `origin`.

## Local checks

Run from `/home/isma/invest` with `APP_MODE=research`.

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `contract_payload_intake_supported=true`, `contract_payload_intake_default=dry_run`, `data_contract_schema_compatibility_status=compatible`, `vendor_runtime=none`, `external_market_data_vendors=disabled`, `alembic_head_expected=0010_normalized_dataset_catalog` |
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
| `make quality` equivalent | ruff / format-check / mypy / 448 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 321 files already formatted |
| `uv run mypy src` | 131 files, no issues |
| `uv run pytest -m "not postgres"` | 448 passed, 157 deselected |
| `uv run pytest -m postgres` | 157 passed (see PostgreSQL section) |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, fills,
portfolio, PnL, returns, signals, strategies, AI runtime, and
`external_market_data_vendors`.

This verification note adds one consistency test, included in the 448
fast tests above. The proposed tag still points at `346b92b`, which does
not include this note. `uv` on this machine is
`/home/isma/invest/.tools/uv-venv/bin/uv`.

## PostgreSQL / Alembic

Local Compose Postgres was already running. `docker compose up -d` left
the existing healthy container in place. Alembic was already at head.

| Check | Result |
|-------|--------|
| Expected head | `0010_normalized_dataset_catalog` |
| `uv run alembic current` | `0010_normalized_dataset_catalog (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| Public table `normalized_datasets` | present, metadata-only |
| `uv run pytest -m postgres` | 157 passed |

Connection strings were not printed. Isolated postgres tests assert:

- default evidence bundle omits the contract payload intake step and
  artifacts
- opt-in intake **dry-run** does not insert bars or raw records
- opt-in `--contract-intake-write-db` inserts once; a second run skips
  bars, does not duplicate them, and does not rewrite OHLCV or PIT on
  either the evidence source or the intake source

`--contract-intake-write-db` was **not** run from the operator CLI
during this check. Database writes were exercised only inside the
marked postgres tests. No truncate, delete, or constraint change.

## Evidence bundle intake opt-in

Default remains **without** intake. The evidence bundle hash does not
pick up intake fields unless `contract_intake_included` is true.

| Check | Result |
|-------|--------|
| Default `include_contract_payload_intake` | false |
| Default `contract_intake_write_db` | false |
| Default bundle step `contract_payload_intake` | absent |
| Default `contract_payload_intake/` artifacts | absent |
| Opt-in flag | `--include-contract-payload-intake` |
| Write flag | `--contract-intake-write-db` (requires the opt-in) |
| Dry-run when included | `write_db=false`, `inserted_counts.total=0` |
| `vendor_runtime` | none |
| `external_market_data_vendors` | disabled |
| Real vendor HTTP | none |
| Artifact paths | relative only |
| Secrets | none |

Operator CLI on the **shared** local database with
`--allow-existing-fixture-data` and the stock
`tests/fixtures/e2e_research_bundle` source did **not** complete (repeat
of 2026-10-07, same as 2026-09-05): reuse failed (`extra_bar`,
`missing_correction`, `corporate_action_mismatch`, `missing_calendar`).
That is risk **R14**. The same reuse failure happened with and without
`--include-contract-payload-intake`. In both cases:

- `ok=false`, `fixture_data_mode=failed`
- no `contract_payload_intake` step
- no `contract_payload_intake/` directory
- no intake-related manifest keys
- identical `bundle_hash`
  (`sha256:637c3b2c9a2683ee7fdf0844a9d9aa85e674c6ea9802e45e57a74f68f44f3a2a`)

Intake was not executed. Existing rows were **not** truncated, deleted,
or rewritten. `verify-research-evidence-bundle.py` was not used as a
success check on those failed shared-database runs.

Isolated proofs of the opt-in path:

- helper dry-run (`run_evidence_contract_payload_intake`, no write):
  `included=true`, `write_db=false`, `status=dry_run`,
  `inserted_counts.total=0`, relative artifact paths only
- postgres `test_evidence_bundle_default_omits_contract_intake`
- postgres `test_evidence_bundle_intake_dry_run_does_not_write`
  (`contract_intake_included=true`, `contract_intake_write_db=false`,
  `inserted_counts.total=0`, `verify_research_evidence_bundle` ok)
- postgres `test_evidence_bundle_intake_write_db_is_idempotent`
  (explicit `--contract-intake-write-db` path; second run skips bars
  and does not rewrite OHLCV/PIT)

This does **not** mean profitability. There is **no PnL/returns**.

## CI remote

GitHub CLI (`gh`) is installed and authenticated for `github.com`
(`ismacarbo-lab`, protocol ssh). Tokens were not printed.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33958305455` |
| Title | Integrate contract payload intake into evidence bundle |
| Event | push |
| Head SHA | `346b92b054a56a5244a1735919e61e90498f231e` |
| Conclusion | success |
| Duration | 55s |
| Started | 2026-09-05T09:33:21Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33958305455 |

Jobs:

- `lint-typecheck-fast-tests` — success
- `postgres-integration` — success

`gh run view 33958305455 --log-failed` produced no failed-step logs.

Annotations (non-blocking): GitHub Actions Node.js 20 deprecation
warning on `actions/checkout@v4` and `astral-sh/setup-uv@v6`.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.6.0-research-evidence-intake`

Meaning: research-only evidence bundle with opt-in contract payload
intake at commit `346b92b054a56a5244a1735919e61e90498f231e`.

It represents:

- `APP_MODE=research` only
- Alembic head `0010_normalized_dataset_catalog`
- evidence bundle with contract payload intake opt-in
- dry-run by default
- PostgreSQL write explicit with `--contract-intake-write-db`
- raw capture / PIT preserved
- vendor-agnostic contracts
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
git tag -a v0.6.0-research-evidence-intake -m "Research evidence intake integration release"
git push origin v0.6.0-research-evidence-intake
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.6.0-research-evidence-intake
git push origin :refs/tags/v0.6.0-research-evidence-intake
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, dividends informational only, no
portfolio/PnL, no trading, local artifact directories, manual goldens,
no automatic downloads, evidence ≠ profitability, accidental git at
`/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate, rate
limits/licensing still unimplemented for any future adapter.

Added operational notes from this check:

- Tag candidate is `346b92b`; this verification note is uncommitted
  documentation and is not part of the proposed tag commit.
- Node.js 20 deprecation annotations on CI are warnings, not failures.
- Shared local PostgreSQL already holds e2e fixture rows that do not
  match the stock fixture (R14). `--allow-existing-fixture-data`
  verifies equivalence and fails on mismatch. Do not truncate to force
  a green operator CLI.
- Evidence-bundle intake stays opt-in (R19). `--contract-intake-write-db`
  is explicit and still does not rewrite existing silver `daily_bars`.

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime. No real vendor HTTP clients. No automatic
downloads. Silver `daily_bars` are not mutated by this add-on. No
silent database writes.
