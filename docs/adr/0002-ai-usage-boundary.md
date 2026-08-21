# ADR 0002 — AI usage boundary

- Status: accepted
- Date: 2026-08-21

## Context

The platform is a research-only ingestion stack (PostgreSQL, Alembic, PIT
daily bars, bronze audit). Developers use Cursor as a copilot. That can
be mistaken for “the app is an AI trading agent.”

Vendors (OpenAI, Anthropic, Cursor APIs, local LLMs) would add secrets,
non-determinism, and a path to generate signals or orders before risk and
execution exist. Phase 1.3 must freeze a safety boundary **before** any
client is added.

## Decision

1. **AI is allowed only as a research/development assistant**, never as a
   financial decision engine.
2. **Cursor is not runtime.** It is not a package dependency, not required
   for tests or CI, and not part of the deployed process.
3. **No AI provider is integrated in this phase** (no OpenAI, Anthropic,
   Cursor API, local models, agents, RAG, or embeddings).
4. **AI must not connect to brokers or execution.** It must not create
   orders, paper/live trades, or signals the platform treats as
   authoritative.
5. **AI must not modify data** except through the existing validated
   ingestion pipeline, after human review. No direct SQL/Alembic from a
   model.
6. A future integration requires a **new ADR**, default-off settings,
   redaction, an audit trail, and tests. It remains optional.

## Alternatives rejected

| Alternative | Why not |
|-------------|---------|
| Ship an LLM client now | No product need; adds vendor and secret surface. |
| Cursor as a production dependency | Tests/CI would require a vendor; the app would not run standalone. |
| AI-generated orders “for research” | Still execution semantics; forbidden until risk/execution ADRs exist. |
| AI writes bronze/silver | Breaks PIT and audit; humans + constraints own data. |
| Empty `quant_platform.ai` package | Placeholder packages imply a runtime that does not exist. |

## Consequences

- `pyproject.toml` has no Cursor, OpenAI, Anthropic, LangChain,
  LlamaIndex, or Transformers dependency in this phase.
- Architecture tests fail if trading/broker packages or those AI
  dependencies appear without a later ADR.
- Deterministic guarantees (Postgres, constraints, PIT, CI) stay the
  source of reliability.
- Docs in `docs/ai/AI_USAGE_BOUNDARY.md` are the human-facing policy.
