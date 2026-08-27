# ADR 0003 — Research-mode freeze

- Status: accepted
- Date: 2026-08-27

## Context

Phases 0–5.3 built a research-only stack: PIT ingestion, datasets,
snapshots, replay, dry-run `ResearchPolicy` observers, experiments,
release checks, and a local evidence bundle.

The next tempting steps are strategies, signals, paper trading, brokers,
PnL, and an LLM runtime. Those would change the product from **research
evidence** into **trading** (or a fake trading agent) without risk,
execution, or a data-vendor design.

This ADR freezes the current stage so later work cannot “quietly” enable
paper/live.

## Decision

1. **Research mode is frozen as the delivery of this stage.**
   `APP_MODE` remains `research` only. `paper` and `live` stay invalid.
2. **The freeze is documentation and guardrails, not a trading launch.**
   Green CI and a green evidence bundle mean the research pipeline is
   intact. They do not mean a strategy exists or that results are
   profitable.
3. **No new functional subsystems in this phase.** Allowed work was
   handoff docs, checklists, capability/risk matrices, canonical
   commands, a minimal reproducible example, and a lightweight status
   flag (`final_freeze_ready`).
4. **`AI_VENTURE_OS_PROMPTS/` stays out of this product.**
5. **Passing to a later phase requires a new ADR** plus an explicit phase
   spec. Do not add brokers, orders, portfolio, PnL, or an AI runtime in
   a “small cleanup.”

## Frozen scope

In scope (already built; keep working):

- local CSV PIT ingestion, bronze/silver, instruments, calendars
- stored corporate actions (not applied)
- dataset API, quality, snapshots, catalog, integrity
- replay, audit, registry, readiness
- dry-run backtest and registered research policies
- experiments, usability gates, observation reports
- policy regression goldens
- research release checks and the local evidence bundle
- `GET /health`

Alembic head remains `0009_backtest_experiments` unless a later phase
needs a table that is still research-only.

## No-go zones

Do not implement until a later ADR:

- strategy, signal, alpha, buy/sell/hold, target weights
- orders, fills, trades, positions, portfolio, cash
- PnL, returns, drawdown, Sharpe, hit ratio, exposure
- brokers, execution, paper trading, live trading
- risk engine, optimizer, ML runtime
- OpenAI, Anthropic, LangChain, RAG as application runtime
- external market-data vendors and automatic downloads
- cloud object storage; HTTP routes beyond `/health`

## Why paper and live stay off

Paper and live are execution modes. This stack has no broker adapter, no
order lifecycle, no risk gate, and no portfolio. Enabling `APP_MODE=paper`
would imply those layers exist. They do not.

ResearchPolicy is an observer. It is not a strategy. Dry-run usability
means artifacts are intact, not that an idea should be traded.

## Consequences

- Release status may report `final_freeze_ready=true` when freeze docs
  exist, evidence-bundle docs/module exist, `APP_MODE` is research, and
  Alembic scripts pin `0009_backtest_experiments`. That flag is **not**
  a go-live.
- `evidence_bundle_available` is a docs/module presence check. It does
  not build or trade.
- Architecture tests, forbidden packages, and disabled capabilities stay
  as CI guardrails.
- Operators resume from [RESEARCH_HANDOFF.md](../release/RESEARCH_HANDOFF.md).

## Conditions for a later phase

A future phase may start only if:

1. A new ADR names the capability (for example strategy interface, still
   without brokers).
2. Tests keep `APP_MODE=research` unless that ADR explicitly changes
   modes.
3. No vendor download or LLM client is added “for convenience.”
4. Evidence of research integrity is not relabeled as PnL.

Alternatives rejected: treat the evidence bundle as a performance
report; enable paper “just for research”; add a broker stub.
