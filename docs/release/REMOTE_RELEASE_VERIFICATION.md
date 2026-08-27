# Remote release verification — Phase 5.5

Research-only operational check of the frozen release candidate. This is
**not** a trading launch and **not** a license to enable paper or live.

Related: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[FINAL_RESEARCH_CHECKLIST.md](FINAL_RESEARCH_CHECKLIST.md),
[COMMANDS.md](COMMANDS.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

This report was the pre-tag verification. The annotated tag
`v0.1.0-research` was created afterward; see
[POST_TAG_RELEASE_NOTES.md](POST_TAG_RELEASE_NOTES.md).

## Verification timestamp

- Local: `2026-08-27T13:05:43+02:00`
- Operator workspace: `/home/isma/invest`
- Git directory used: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Git

| Item | Value |
|------|--------|
| Branch | `main` |
| Remote `origin` | `git@github.com:ismacarbo-lab/quant-platform.git` |
| Verified commit | `9b7fe7c312734fc5d3a5029a45d2128701a9aa07` |
| Subject | Freeze research mode release candidate |
| `HEAD` vs `origin/main` | identical (0 ahead, 0 behind after `git fetch`) |
| Working tree at verification start | clean |
| `AI_VENTURE_OS_PROMPTS/` | not modified (mtime 2026-08-18) |

`git status --short` was empty before this report was written.

## Local checks

Run from `/home/isma/invest` with `APP_MODE=research`.

| Check | Result |
|-------|--------|
| `make research-status` | `final_freeze_ready=true`, `evidence_bundle_available=true`, `alembic_head_expected=0009_backtest_experiments` |
| `make research-release-check` | `ok=true`, errors=0, `trading_constructs=none`, `ai_runtime=none` |
| `make policy-regression` | 18/18 passed |
| Policy regression hash | `sha256:bac6bf591d011073547649c73b38eb7701b8f15bb3d118d3c68d5adae6d2c47f` |
| `make quality` | ruff / format-check / mypy / 294 fast tests / Compose config OK |
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 237 files already formatted |
| `uv run mypy src` | 92 files, no issues |
| `uv run pytest` | 420 passed |
| `docker compose config` | OK |

Disabled capabilities still include paper, live, brokers, orders, portfolio,
PnL, signals, strategies, and AI runtime.

## PostgreSQL / Alembic

Executed. Local Compose Postgres was already running.

| Check | Result |
|-------|--------|
| `docker compose up -d` | container `quant-platform-postgres` Running |
| `uv run alembic current` | `0009_backtest_experiments (head)` |
| `uv run python scripts/check-db.py` | `ping=ok`, `trading_tables=none` |
| `uv run pytest -m postgres` | 126 passed |

Connection strings were not printed.

## Evidence bundle

`pytest -m postgres` includes the isolated evidence-bundle integration
tests and passed.

Operator `make research-evidence-bundle` on this **shared** local database
failed with `ingest_failed` / `daily bar ingest did not insert research bars`.
That is consistent with fixture bars already present from earlier operator
runs (PIT insert of 0 new rows). It is **not** a CI failure.

Do not treat leftover files under `/tmp/research-evidence-bundle` from that
failed retry as the release pack.

Last known **successful** operator bundle hash from the freeze verification
(Phase 5.4, isolated rebuild then):

`sha256:8ee0f01bc591fe01995a70614a17191282f42ef77489c715de686a36a9f1325e`

A green bundle still does **not** mean profitability.

## CI remote

GitHub CLI (`gh`) is installed. `gh auth status` reported a github.com
login failure for the default account, but `gh run list` and `gh run view`
succeeded for this repository.

Latest `main` workflow (push of the verified commit):

| Field | Value |
|-------|--------|
| Workflow | CI |
| Run id | `33065645340` |
| Title | Freeze research mode release candidate |
| Event | push |
| Conclusion | success |
| Duration | 54s |
| Started | 2026-08-27T11:02:45Z |
| URL | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33065645340 |

Jobs:

- `lint-typecheck-fast-tests` — success (25s)
- `postgres-integration` — success (51s)

`gh run view 33065645340 --log-failed` produced no failed-step logs.

Annotations (warnings, not job failures): GitHub Node.js 20 deprecation
on `actions/checkout@v4` and `astral-sh/setup-uv@v6`. Not a research or
trading issue; do not weaken gates to silence it.

Previous four `main` CI runs were also `success`.

If CLI auth breaks later, check the Actions tab on GitHub for branch
`main`, workflow `CI`, jobs `lint-typecheck-fast-tests` and
`postgres-integration`.

## Proposed tag

**Not created. Not pushed.**

Name: `v0.1.0-research`

Meaning: research-only freeze of commit
`9b7fe7c312734fc5d3a5029a45d2128701a9aa07`.

It does **not** mark paper trading, live trading, or an AI runtime.

### Create (do not run until approved)

```bash
cd /home/isma/invest
git tag -a v0.1.0-research -m "Research mode release candidate"
git push origin v0.1.0-research
```

### Rollback (if the tag was created by mistake)

```bash
cd /home/isma/invest
git tag -d v0.1.0-research
git push origin :refs/tags/v0.1.0-research
```

## Remaining risks

Same freeze register: PostgreSQL required, no vendors, small fixtures,
corporate actions stored not applied, no advanced normalization, no
portfolio/PnL, no trading, local artifact directories, manual goldens, no
automatic downloads, evidence ≠ profitability, accidental git at
`/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate.

Added operational notes from this check:

- Shared local Postgres can make a second `make research-evidence-bundle`
  insert zero bars; use `pytest -m postgres` or a clean database for a
  fresh pack.
- `gh auth status` may disagree with `gh run list`; prefer the run view
  when both are available.
- Node.js 20 Action deprecation warnings on CI.

## Out of scope

No strategies, signals, orders, fills, portfolio, PnL, returns, brokers,
paper/live, or AI runtime.
