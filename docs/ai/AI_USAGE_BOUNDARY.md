# AI usage boundary

Phase 1.3 defines how this repository may use AI. It does **not** add a
model, an API client, or a Cursor runtime.

Reliability comes from PostgreSQL, Alembic, constraints, tests, CI,
point-in-time validation, log redaction, and human review. AI may assist
those processes. It must not replace them.

## What Cursor is

Cursor is a **development copilot**: an editor/agent used by people writing
code, docs, and tests in this workspace.

Typical allowed uses of Cursor (or any coding assistant) during development:

- explain existing code
- draft tests and documentation
- propose refactors that humans review
- help implement an already-specified phase
- review diffs for mistakes

`uv run pytest`, `make quality`, Compose, and Alembic must work on a
machine that has never installed Cursor.

## What Cursor is not

Cursor is **not**:

- part of the deployed `quant_platform` process
- a Python dependency
- a requirement for CI
- a broker, execution engine, or strategy runtime
- an authority over PostgreSQL data or Alembic revisions

Cursor must not appear in `pyproject.toml` (runtime or dev groups).
GitHub Actions must not call a Cursor API.

The tree `AI_VENTURE_OS_PROMPTS/` is a **separate product**. It is not an
AI subsystem of `quant_platform`. Do not import it, ship it, or treat its
prompts as trading or research runtime.

## Allowed AI uses (now and later)

Permitted, always with a human in the loop:

| Use | Notes |
|-----|--------|
| Development assistance | Draft code/docs/tests; humans merge. |
| Research explanation | Summarize stored research data or docs **after** deterministic queries. |
| Review | Point out PIT leaks, missing tests, or unclear errors. |
| Future optional assistant | A later ADR may add an **opt-in**, default-off helper that **reads** validated research outputs and explains them. |

Any future assistant must be:

- optional and **off by default**
- unused unless an explicit setting enables it
- free of secrets in logs (reuse `redact_secret_text`)
- unable to write market data, run migrations, or skip PIT/OHLC checks
- audited: persist prompt/response metadata without API keys
- covered by tests (disabled path, redaction, no writes)

## Prohibited AI uses

Forbidden in this phase and as standing policy until a future ADR
explicitly supersedes it:

- generating BUY/SELL **signals** that the platform then treats as truth
- creating or routing **orders**
- paper or live **trading**
- connecting to **brokers**
- overwriting **market data** or bronze/silver rows
- applying **Alembic** or ad-hoc SQL without human review
- calling OpenAI, Anthropic, Cursor APIs, or local models from this package
- making AI a **required** runtime for research or tests
- autonomous agents that mutate state
- RAG / embeddings / vector databases as a substitute for PostgreSQL

Deterministic validation always wins: if AI output disagrees with a
constraint, the constraint stands.

## Why there is no real AI integration yet

Phase 1.3 only draws the boundary. Integration would add vendor lock-in,
secrets, non-determinism, and a temptation to skip data quality. The
ingestion, PIT, and calendar layers must stay trustworthy first.

A later phase may add a client **after**:

1. a new ADR (provider, data the model may see, write prohibitions)
2. settings that default to disabled
3. secret handling that never logs `DATABASE_URL` passwords or API keys
4. tests for the disabled default and for “no writes”
5. no new FastAPI surface unless that ADR requires it

Do not pin the design to one vendor. Prefer a narrow interface (e.g. “complete
this text”) behind a port, with adapters added only when needed.

## Secrets and reproducibility

- API keys never belong in git, Compose, or structured logs.
- Research results must be reproducible from PostgreSQL + fixtures + tests
  **without** calling a model.
- Model output is not a source of truth for prices, calendars, or identity.
- CI stays green without network calls to LLM providers.

## Audit sketch (future)

If an assistant is added, record at least: timestamp (UTC), run id, which
setting enabled it, model identifier (not the key), hash or truncated
redacted input, redacted output, and that **no** database write was issued
by the assistant path. Store that trail in PostgreSQL, not in Cursor.

See [ADR 0002](../adr/0002-ai-usage-boundary.md).
