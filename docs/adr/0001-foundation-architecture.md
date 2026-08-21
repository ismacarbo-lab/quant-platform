# ADR 0001 — Foundation architecture

- Status: accepted
- Date: 2026-08-21

## Context

We need a professional, reproducible base for quantitative research and
later assisted trading. The workspace already contains an unrelated
product (`AI_VENTURE_OS_PROMPTS`, CBAM/venture OS). There is no existing
quant package, FastAPI app, PostgreSQL schema, or CI at the `invest`
root. The temptation on a green field is to introduce a distributed
runtime, message buses, and agent frameworks before any domain logic
exists.

Phase 0 must maximize robustness, traceability, and safety without
implementing strategies, brokers, or market-data clients.

## Decision

1. **Keep the existing venture-OS tree untouched.** Initialize
   `quant_platform` at the `invest` root as a separate modular monolith.
2. **Python 3.13 + uv + src layout + pyproject.toml** as the packaging
   and lock mechanism.
3. **Typed settings** via Pydantic Settings. Default and only valid mode:
   `research`. Reject live/paper configuration.
4. **PostgreSQL + SQLAlchemy 2.x + Alembic**, with no financial tables
   yet and no SQLite fallback.
5. **FastAPI** limited to `GET /health`.
6. **UTC-aware clocks, run ids, JSON logs** as shared core/monitoring
   utilities.
7. **Document** bronze/silver/gold data layers, point-in-time fields,
   look-ahead prohibition, and strategy → risk → execution → broker
   direction. Do not implement that flow yet.

## Alternatives rejected

| Alternative | Why not now |
|-------------|-------------|
| Microservices | No scale, team, or isolation need. Multiplies ops and consistency cost. |
| Kafka | No event volume or multiple consumers. Adds operational surface. |
| Redis | No cache/session/queue requirement in Phase 0. |
| Kubernetes | Single local process. Orchestration would hide missing product. |
| Multi-agent runtime | Unrelated to research-grade data/risk foundations; hard to test. |
| Adapt `cbam-ops` as the package | Different domain (customs/CBAM). Mixing would destroy both designs. |
| SQLite for tests | Silent divergence from PostgreSQL; forbidden as a substitute. |
| Broker mock | Would imply execution exists. Phase 0 has no orders. |

## Consequences

- One package, one process, one database engine family.
- Later paper trading can be added as a new mode **after** risk and
  execution exist; live remains off by design until a future ADR.
- Empty placeholder packages for strategies/ml/backtesting are omitted
  so the tree only contains running code plus documentation of
  boundaries.
- Alembic has no initial empty revision; the first migration will ship
  with the first real model.
- Docker Compose provides only PostgreSQL for local development.
