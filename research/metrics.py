from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


def _drawdown(equity: Iterable[float]) -> tuple[float, int]:
    values = np.asarray(list(equity), dtype=float)
    if values.size == 0:
        return 0.0, 0
    peaks = np.maximum.accumulate(values)
    drawdowns = np.divide(
        peaks - values,
        peaks,
        out=np.zeros_like(values),
        where=peaks != 0,
    )
    max_index = int(np.argmax(drawdowns))
    peak_index = int(np.argmax(values[: max_index + 1])) if max_index else 0
    return float(drawdowns[max_index]), max_index - peak_index


def bootstrap_expectancy_ci(
    r_multiples: Iterable[float],
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[Optional[float], Optional[float]]:
    values = np.asarray(list(r_multiples), dtype=float)
    if values.size == 0:
        return None, None
    if iterations < 1 or not 0 < confidence < 1:
        raise ValueError("Bootstrap iterations and confidence level are invalid.")
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(iterations, values.size), replace=True).mean(axis=1)
    tail = (1 - confidence) / 2
    lower, upper = np.quantile(samples, [tail, 1 - tail])
    return float(lower), float(upper)


def calculate_metrics(
    trades: Iterable[Dict[str, Any]],
    equity_curve: Iterable[Dict[str, Any]],
    starting_equity: float,
    bootstrap_iterations: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    rows = list(trades)
    curve = list(equity_curve)
    pnl = np.asarray([float(trade["pnl_usd"]) for trade in rows], dtype=float)
    r_multiples = np.asarray(
        [
            float(trade["pnl_usd"]) / float(trade["initial_risk_usd"])
            for trade in rows
            if float(trade.get("initial_risk_usd", 0)) > 0
        ],
        dtype=float,
    )
    end_equity = float(curve[-1]["equity"]) if curve else starting_equity
    elapsed_seconds = 0.0
    if len(curve) > 1:
        elapsed_seconds = max(
            0.0,
            float(curve[-1]["timestamp_ms"] - curve[0]["timestamp_ms"]) / 1000,
        )
    years = elapsed_seconds / (365.25 * 24 * 60 * 60)
    total_return = end_equity / starting_equity - 1 if starting_equity else 0.0
    annualized_return = (
        (end_equity / starting_equity) ** (1 / years) - 1
        if years > 0 and end_equity > 0 and starting_equity > 0
        else None
    )
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    sharpe = None
    sortino = None
    if len(curve) > 1:
        returns = pd.Series([point["equity"] for point in curve]).pct_change().dropna()
        downside = returns[returns < 0]
        periods_per_year = len(returns) / years if years > 0 else len(returns)
        if returns.std(ddof=1) > 0:
            sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year))
        if len(downside) and downside.std(ddof=1) > 0:
            sortino = float(
                returns.mean() / downside.std(ddof=1) * np.sqrt(periods_per_year)
            )
    max_drawdown, drawdown_duration = _drawdown(
        point["equity"] for point in curve
    )
    if elapsed_seconds > 0:
        trades_per_month = len(rows) / (elapsed_seconds / (30.4375 * 24 * 60 * 60))
    else:
        trades_per_month = 0.0
    exposure_seconds = sum(
        max(0, float(trade.get("duration_seconds", 0))) for trade in rows
    )
    exposure_time = exposure_seconds / elapsed_seconds if elapsed_seconds else 0.0
    ci_lower, ci_upper = bootstrap_expectancy_ci(
        r_multiples, iterations=bootstrap_iterations, seed=seed
    )
    return {
        "trade_count": len(rows),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "net_expectancy_r": float(r_multiples.mean()) if r_multiples.size else None,
        "expectancy_r_ci_95": [ci_lower, ci_upper],
        "win_rate": float(np.mean(pnl > 0)) if pnl.size else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_win_usd": float(wins.mean()) if wins.size else None,
        "average_loss_usd": float(losses.mean()) if losses.size else None,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "max_drawdown_duration_points": drawdown_duration,
        "trades_per_month": trades_per_month,
        "exposure_time_fraction": exposure_time,
        "starting_equity": starting_equity,
        "ending_equity": end_equity,
        "elapsed_days": elapsed_seconds / 86400,
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
