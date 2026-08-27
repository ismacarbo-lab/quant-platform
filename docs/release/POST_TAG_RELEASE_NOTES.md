# Post-tag release notes — Phase 5.6

Archive notes for the research-only tag. This is **not** a trading
system and **not** an AI runtime.

Related: [REMOTE_RELEASE_VERIFICATION.md](REMOTE_RELEASE_VERIFICATION.md),
[RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md),
[RISK_REGISTER.md](RISK_REGISTER.md),
[COMMANDS.md](COMMANDS.md),
[ADR 0003](../adr/0003-research-mode-freeze.md).

**No Alembic revision for this phase.** Expected head remains
`0009_backtest_experiments`.

Do **not** create another tag from this document.

## Closure timestamp

- Local: `2026-08-27T13:17:31+02:00`
- Workspace: `/home/isma/invest`
- Git directory: `/home/isma/invest/.git`
- Accidental git at `/home/isma` was **not** used

## Tag

| Item | Value |
|------|--------|
| Tag | `v0.1.0-research` |
| Kind | annotated |
| Tag object | `ac597ddc800b61f8a31cef8b8a0098d7683dcb63` |
| Message | Research mode release candidate |
| TaggerDate | 2026-08-27 13:16:24 +0200 |
| Local | present (`git tag --list "v0.1.0-research"`) |
| Remote `origin` | present (`git ls-remote --tags origin v0.1.0-research`) |

`git ls-remote` shows the **tag object** SHA, not the peeled commit.
Peel with `git rev-parse v0.1.0-research^{commit}`.

## Commit pointed by the tag

| Item | Value |
|------|--------|
| Peeled commit | `5969890be489519993ee97e8f4f4768789a33a1d` |
| Subject | Document remote research release verification |
| Branch | `main` |
| Remote | `git@github.com:ismacarbo-lab/quant-platform.git` |
| `HEAD` / `origin/main` | same commit (working tree clean at verification start) |
| Parent (freeze) | `9b7fe7c312734fc5d3a5029a45d2128701a9aa07` Freeze research mode release candidate |

Phase 5.5 proposed tagging the freeze commit. The operator committed the
verification report first, then tagged **that** commit. The freeze is
still the parent. This tag is research-only either way.

## Checks executed (this phase)

From `/home/isma/invest`, `APP_MODE=research`:

- `git status --short` — empty before these notes
- `git branch --show-current` — `main`
- `git log -1 --oneline` — `5969890 Document remote research release verification`
- `git tag --list "v0.1.0-research"` — present
- `git show --no-patch --format=fuller v0.1.0-research` — annotated tag → `5969890`
- `git ls-remote --tags origin v0.1.0-research` — tag object `ac597ddc…`
- `make research-status`
- `make research-release-check`
- `make policy-regression`
- `uv run pytest tests/unit/test_research_freeze.py`
- `docker compose config`

## CI status

`gh` authenticated for this check. Latest `main` and tag-push runs:

| Run | Event | Conclusion | URL |
|-----|-------|------------|-----|
| `33066626059` | push `main` (`5969890`) | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33066626059 |
| `33066649071` | push `v0.1.0-research` | success | https://github.com/ismacarbo-lab/quant-platform/actions/runs/33066649071 |

Jobs on both: `lint-typecheck-fast-tests` and `postgres-integration` green.
`--log-failed` empty. Remaining annotation: Node.js 20 deprecation on
`actions/checkout@v4` and `astral-sh/setup-uv@v6` (warning, not a failure).

## Remaining risks

Unchanged freeze register: PostgreSQL required, no vendors, small
fixtures, corporate actions stored not applied, no advanced
normalization, no portfolio/PnL, no trading, local artifact dirs,
manual goldens, no automatic downloads, evidence ≠ profitability,
accidental git at `/home/isma`, keep `AI_VENTURE_OS_PROMPTS/` separate.

Operational notes still true: a reused local database can make a second
evidence-bundle ingest insert zero bars; Node.js 20 Action warnings.

The tag does **not** remove those risks.

## Allowed next steps

Only after a **new ADR** and an explicit phase spec, still research-first
unless that ADR says otherwise:

1. Richer **local** fixtures (still no vendor client).
2. Stronger PIT / corporate-action **research notes** (still not a
   strategy).
3. A strategy **interface** with no brokers, orders, or PnL until those
   layers exist.
4. Optional, default-off research assistant per ADR 0002 — never a
   trading brain.

Maintenance on this tag: keep `APP_MODE=research`, run
[COMMANDS.md](COMMANDS.md) quality/release checks, do not retag.

## Prohibited next steps

Do not add without a new ADR:

- strategy, signal, alpha, buy/sell/hold, target weights
- orders, fills, trades, positions, portfolio, cash
- PnL, returns, drawdown, Sharpe, hit ratio, exposure
- brokers, execution, paper trading, live trading
- risk engine, optimizer, ML / LLM runtime
- OpenAI, Anthropic, LangChain, RAG as application runtime
- external market-data vendors or automatic downloads
- HTTP routes beyond `GET /health`
- another release tag for this freeze

## Tag rollback (do not run unless the tag must be withdrawn)

```bash
cd /home/isma/invest
git tag -d v0.1.0-research
git push origin :refs/tags/v0.1.0-research
```

Deleting a published tag is disruptive. Prefer a later tag over rewriting
this one.

## Maintenance commands

```bash
cd /home/isma/invest
make research-status
make research-release-check
make policy-regression
make quality
```

PostgreSQL (optional): `docker compose up -d`, `uv run alembic current`,
`uv run python scripts/check-db.py`, `uv run pytest -m postgres`.

Do not print connection URLs. Do not mix this repo with
`AI_VENTURE_OS_PROMPTS/`.
