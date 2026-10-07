"""Backtest strategies on the stored PIT panel and rank them vs the benchmark.

Stores each result in ``strategy_backtests`` unless ``--no-store``.
Walk-forward validation (in-sample selection, out-of-sample judgement)
runs by default for non-benchmark strategies.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime

from quant_platform.backtesting.data import PricePanelError, load_price_panel
from quant_platform.backtesting.engine import BacktestConfig, BacktestError
from quant_platform.backtesting.runner import (
    StrategyBacktestOutcome,
    run_strategy_backtest_on_panel,
)
from quant_platform.backtesting.walk_forward import WalkForwardConfig
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.marketdata.universe import (
    DEFAULT_HISTORY_START,
    resolve_universe,
    universe_symbols,
)
from quant_platform.research.snapshots import get_git_commit
from quant_platform.storage.database import create_db_engine, create_session_factory
from quant_platform.strategies import STRATEGY_SPECS, StrategyError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run strategy backtests with costs and walk-forward validation on "
            "the stored market data. Results are descriptive, not predictive."
        )
    )
    parser.add_argument(
        "--strategy",
        action="append",
        default=None,
        help="Strategy name (repeatable). Default: all registered strategies.",
    )
    parser.add_argument(
        "--params",
        default=None,
        help="JSON object with parameter overrides (single --strategy only).",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=DEFAULT_HISTORY_START
    )
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--rebalance",
        default="monthly",
        choices=("daily", "weekly", "monthly", "quarterly"),
    )
    parser.add_argument("--commission-bps", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--include-crypto", action="store_true")
    parser.add_argument("--no-walk-forward", action="store_true")
    parser.add_argument("--min-is-years", type=int, default=5)
    parser.add_argument("--no-store", action="store_true", help="Do not persist.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_research_mode:
        print("APP_MODE must be research or paper", file=sys.stderr)
        return 1
    names = args.strategy or [spec.name for spec in STRATEGY_SPECS]
    params: dict[str, object] | None = None
    if args.params:
        if len(names) != 1:
            print("--params requires exactly one --strategy", file=sys.stderr)
            return 1
        loaded = json.loads(args.params)
        if not isinstance(loaded, dict):
            print("--params must be a JSON object", file=sys.stderr)
            return 1
        params = {str(key): value for key, value in loaded.items()}
    universe = resolve_universe(None, include_optional=args.include_crypto)
    try:
        config = BacktestConfig(
            rebalance=args.rebalance,
            commission_bps=args.commission_bps,
            slippage_bps=args.slippage_bps,
            initial_cash=args.initial_cash,
            universe=tuple(universe),
        )
    except BacktestError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    end = args.end or datetime.now(tz=UTC).date()
    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    outcomes: list[StrategyBacktestOutcome] = []
    try:
        panel = load_price_panel(
            session,
            source_name=settings.market_data_source_name,
            symbols=universe_symbols(universe),
            start=args.start,
            end=end,
        )
        git_commit = get_git_commit()
        for name in names:
            outcome = run_strategy_backtest_on_panel(
                None if args.no_store else session,
                panel,
                strategy_name=name,
                params=params,
                config=config,
                walk_forward=not args.no_walk_forward,
                wf_config=WalkForwardConfig(min_is_years=args.min_is_years),
                git_commit=git_commit,
            )
            outcomes.append(outcome)
        if not args.no_store:
            session.commit()
    except (PricePanelError, StrategyError, BacktestError) as exc:
        session.rollback()
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    except Exception as exc:
        session.rollback()
        print(redact_secret_text(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()
    if args.json:
        print(
            json.dumps(
                {
                    "kind": "strategy_backtest_run",
                    "panel": {
                        "source_name": panel.source_name,
                        "start": str(panel.start.date()),
                        "end": str(panel.end.date()),
                        "sessions": panel.session_count,
                        "symbols": list(panel.symbols),
                        "data_hash": panel.data_hash,
                    },
                    "config": config.as_mapping(),
                    "results": [item.summary() for item in outcomes],
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    _print_ranking(
        outcomes, panel_start=str(panel.start.date()), panel_end=str(panel.end.date())
    )
    return 0


def _fmt_pct(value: object) -> str:
    return "   n/a" if not isinstance(value, int | float) else f"{value * 100:6.1f}%"


def _fmt_num(value: object) -> str:
    return "  n/a" if not isinstance(value, int | float) else f"{value:5.2f}"


def _print_ranking(
    outcomes: list[StrategyBacktestOutcome], *, panel_start: str, panel_end: str
) -> None:
    print(f"strategy backtests {panel_start} -> {panel_end} (costs included)")
    header = (
        f"{'strategy':26s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>6s} {'MaxDD':>7s} "
        f"{'OOS Sharpe':>10s} {'OOS MaxDD':>9s} {'paper?':>7s}"
    )
    print(header)
    ranked = sorted(
        outcomes,
        key=lambda item: -(item.result.metrics.sharpe or float("-inf")),
    )
    for item in ranked:
        m = item.result.metrics.as_mapping()
        oos = item.walk_forward.oos_metrics.as_mapping() if item.walk_forward else {}
        verdict = (
            "bench"
            if item.promotion is None and item.walk_forward is None
            else "yes"
            if item.promotion is not None and item.promotion.eligible
            else "no"
        )
        print(
            f"{item.strategy_name:26s} {_fmt_pct(m['cagr'])} "
            f"{_fmt_pct(m['annual_volatility'])} {_fmt_num(m['sharpe']):>6s} "
            f"{_fmt_pct(m['max_drawdown'])} {_fmt_num(oos.get('sharpe')):>10s} "
            f"{_fmt_pct(oos.get('max_drawdown')):>9s} {verdict:>7s}"
        )
    bench = outcomes[0].benchmark.metrics.as_mapping() if outcomes else {}
    if bench:
        print(
            f"{'benchmark (' + outcomes[0].benchmark.strategy_name + ')':26s} "
            f"{_fmt_pct(bench['cagr'])} {_fmt_pct(bench['annual_volatility'])} "
            f"{_fmt_num(bench['sharpe']):>6s} {_fmt_pct(bench['max_drawdown'])}"
        )
    print("Past performance, even out-of-sample, does not guarantee future results.")


if __name__ == "__main__":
    sys.exit(main())
