"""Performance metrics from a daily return series. Descriptive, not predictive."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    sessions: int
    years: float
    total_return: float
    cagr: float
    annual_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    best_day: float
    worst_day: float
    positive_months: float
    best_month: float
    worst_month: float
    annual_turnover: float
    total_costs: float
    average_exposure: float
    final_equity: float
    start: str | None
    end: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "sessions": self.sessions,
            "years": _clean(self.years),
            "total_return": _clean(self.total_return),
            "cagr": _clean(self.cagr),
            "annual_volatility": _clean(self.annual_volatility),
            "sharpe": _clean(self.sharpe),
            "sortino": _clean(self.sortino),
            "max_drawdown": _clean(self.max_drawdown),
            "calmar": _clean(self.calmar),
            "best_day": _clean(self.best_day),
            "worst_day": _clean(self.worst_day),
            "positive_months": _clean(self.positive_months),
            "best_month": _clean(self.best_month),
            "worst_month": _clean(self.worst_month),
            "annual_turnover": _clean(self.annual_turnover),
            "total_costs": _clean(self.total_costs),
            "average_exposure": _clean(self.average_exposure),
            "final_equity": _clean(self.final_equity),
            "start": self.start,
            "end": self.end,
        }


def _clean(value: float) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return round(float(value), 10)


def compute_metrics(
    returns: pd.Series,
    *,
    turnover: pd.Series | None = None,
    costs: pd.Series | None = None,
    exposure: pd.Series | None = None,
    initial_equity: float = 1.0,
) -> PerformanceMetrics:
    """Metrics for a daily simple-return series indexed by session."""
    clean = returns.dropna().astype("float64")
    sessions = int(clean.shape[0])
    if sessions == 0:
        return _empty_metrics()
    years = sessions / TRADING_DAYS
    growth = (1.0 + clean).cumprod()
    equity = growth * initial_equity
    total_return = float(growth.iloc[-1] - 1.0)
    cagr = float(growth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    std = float(clean.std(ddof=1)) if sessions > 1 else float("nan")
    mean = float(clean.mean())
    annual_vol = std * math.sqrt(TRADING_DAYS) if not math.isnan(std) else float("nan")
    sharpe = (
        mean / std * math.sqrt(TRADING_DAYS)
        if std and not math.isnan(std) and std > 0
        else float("nan")
    )
    downside = clean[clean < 0]
    downside_std = (
        float(np.sqrt(np.mean(np.square(downside.to_numpy()))))
        if downside.shape[0] > 0
        else 0.0
    )
    sortino = (
        mean / downside_std * math.sqrt(TRADING_DAYS)
        if downside_std > 0
        else float("nan")
    )
    drawdown = growth / growth.cummax() - 1.0
    max_dd = float(drawdown.min()) if sessions else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 and not math.isnan(cagr) else float("nan")
    monthly = monthly_returns(clean)
    positive_months = (
        float((monthly > 0).mean()) if monthly.shape[0] > 0 else float("nan")
    )
    annual_turnover = (
        float(turnover.fillna(0.0).sum()) / years
        if turnover is not None and years > 0
        else 0.0
    )
    total_costs = float(costs.fillna(0.0).sum()) if costs is not None else 0.0
    average_exposure = (
        float(exposure.dropna().mean()) if exposure is not None else float("nan")
    )
    return PerformanceMetrics(
        sessions=sessions,
        years=years,
        total_return=total_return,
        cagr=cagr,
        annual_volatility=annual_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        calmar=calmar,
        best_day=float(clean.max()),
        worst_day=float(clean.min()),
        positive_months=positive_months,
        best_month=float(monthly.max()) if monthly.shape[0] else float("nan"),
        worst_month=float(monthly.min()) if monthly.shape[0] else float("nan"),
        annual_turnover=annual_turnover,
        total_costs=total_costs,
        average_exposure=average_exposure,
        final_equity=float(equity.iloc[-1]),
        start=str(pd.Timestamp(clean.index[0]).date()),
        end=str(pd.Timestamp(clean.index[-1]).date()),
    )


def monthly_returns(returns: pd.Series) -> pd.Series:
    """Compound daily returns into calendar-month returns."""
    clean = returns.dropna().astype("float64")
    if clean.empty:
        return pd.Series(dtype="float64")
    stamps = pd.DatetimeIndex(clean.index)
    labels = [
        f"{int(y):04d}-{int(m):02d}"
        for y, m in zip(stamps.year, stamps.month, strict=True)
    ]
    grouped: pd.Series = (1.0 + clean).groupby(pd.Index(labels)).prod() - 1.0
    return grouped


def drawdown_series(returns: pd.Series) -> pd.Series:
    clean = returns.dropna().astype("float64")
    growth = (1.0 + clean).cumprod()
    result: pd.Series = growth / growth.cummax() - 1.0
    return result


def monthly_table(returns: pd.Series) -> list[dict[str, object]]:
    """Rows for a year x month heatmap."""
    monthly = monthly_returns(returns)
    rows: list[dict[str, object]] = []
    for label, value in monthly.items():
        year, month = str(label).split("-")
        rows.append(
            {"year": int(year), "month": int(month), "return": _clean(float(value))}
        )
    return rows


def relative_metrics(
    strategy: pd.Series, benchmark: pd.Series
) -> dict[str, float | None]:
    """Beta, correlation and excess CAGR of a strategy against a benchmark."""
    joined = pd.concat([strategy, benchmark], axis=1, join="inner").dropna()
    if joined.shape[0] < 3:
        return {"beta": None, "correlation": None, "excess_cagr": None}
    left = joined.iloc[:, 0].astype("float64")
    right = joined.iloc[:, 1].astype("float64")
    variance = float(right.var(ddof=1))
    beta = float(left.cov(right) / variance) if variance > 0 else float("nan")
    left_std = float(left.std(ddof=1))
    correlation = (
        float(left.corr(right)) if variance > 0 and left_std > 0 else float("nan")
    )
    excess = compute_metrics(left).cagr - compute_metrics(right).cagr
    return {
        "beta": _clean(beta),
        "correlation": _clean(correlation),
        "excess_cagr": _clean(excess),
    }


def _empty_metrics() -> PerformanceMetrics:
    nan = float("nan")
    return PerformanceMetrics(
        sessions=0,
        years=0.0,
        total_return=nan,
        cagr=nan,
        annual_volatility=nan,
        sharpe=nan,
        sortino=nan,
        max_drawdown=nan,
        calmar=nan,
        best_day=nan,
        worst_day=nan,
        positive_months=nan,
        best_month=nan,
        worst_month=nan,
        annual_turnover=0.0,
        total_costs=0.0,
        average_exposure=nan,
        final_equity=nan,
        start=None,
        end=None,
    )
