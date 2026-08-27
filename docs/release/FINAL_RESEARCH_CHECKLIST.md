# Final research checklist — Phase 5.4

Manual checks before treating this stage as frozen. None of these checks
mean the system can trade.

Related: [RESEARCH_HANDOFF.md](RESEARCH_HANDOFF.md),
[COMMANDS.md](COMMANDS.md),
[MINIMAL_REPRODUCIBLE_EXAMPLE.md](MINIMAL_REPRODUCIBLE_EXAMPLE.md).

## Workspace

- [ ] Working directory is `/home/isma/invest` (this repo).
- [ ] Do **not** run git commands in the accidental git at `/home/isma`.
- [ ] `AI_VENTURE_OS_PROMPTS/` and `AI_VENTURE_OS_PROMPTS.zip` are
      untouched (separate product).
- [ ] `.env` is gitignored. No real secrets in the tree.

## Tooling

- [ ] Python 3.13 via `uv python --version` (or `uv run python --version`).
- [ ] `uv` is available (`uv --version`).
- [ ] `APP_MODE=research` (paper and live must still fail settings
      validation).

## PostgreSQL and Alembic

- [ ] `docker compose up -d postgres` (or equivalent local PostgreSQL).
- [ ] `uv run python scripts/check-db.py` → `ping=ok`,
      `trading_tables=none`.
- [ ] `uv run alembic current` / `upgrade head` →
      `0009_backtest_experiments`.
- [ ] No SQLite database files used as the store.

## Fast quality

- [ ] `make quality` passes (ruff, format-check, mypy, fast pytest,
      `docker compose config`).
- [ ] `make policy-regression` → 18/18 passed.
- [ ] `make research-release-check` → `ok=true`,
      `trading_constructs=none`, `ai_runtime=none`.
- [ ] `make research-status` → `final_freeze_ready=true`,
      `evidence_bundle_available=true`,
      `alembic_head_expected=0009_backtest_experiments`.

## PostgreSQL tests and evidence

- [ ] `uv run pytest -m postgres` passes.
- [ ] `make research-evidence-bundle` writes a local bundle
      (default `/tmp/research-evidence-bundle`).
- [ ] `make verify-research-evidence-bundle` (or
      `scripts/verify-research-evidence-bundle.py --bundle-dir …`) is
      `ok=true`.

## CI and secrets

- [ ] GitHub Actions `quality` and `postgres` jobs are green on the
      branch you care about.
- [ ] Scripts and JSON reports do not print `DATABASE_URL` or
      `postgresql+psycopg://` connection strings.
- [ ] No vendor API keys, broker URLs, or LLM keys in settings.

## Boundaries

- [ ] No strategy / signal / order / fill / trade / portfolio / PnL
      packages or tables.
- [ ] No paper or live `APP_MODE`.
- [ ] No brokers, execution, or order routing.
- [ ] No OpenAI / Anthropic / LangChain / RAG / Cursor SDK runtime.
- [ ] HTTP surface is still `GET /health` only.

Passing this list freezes **research**. It does not authorize paper
trading, live trading, or an AI runtime.
