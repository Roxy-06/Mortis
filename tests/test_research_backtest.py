import numpy as np
import pandas as pd

from research.backtest import run_backtest
from research.metrics import bootstrap_expectancy_ci, calculate_metrics


def make_candles(periods, interval_minutes):
    opens = pd.date_range(
        "2024-01-01", periods=periods, freq=f"{interval_minutes}min", tz="UTC"
    )
    open_time_ms = np.asarray([int(timestamp.timestamp() * 1000) for timestamp in opens])
    close = 100 + np.arange(periods) * 0.03 + np.sin(np.arange(periods) / 7)
    return pd.DataFrame(
        {
            "open_time": open_time_ms,
            "close_time": open_time_ms + interval_minutes * 60_000 - 1,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(periods, 100.0),
        }
    )


def test_backtest_enters_on_next_bar_and_uses_stop_first_intrabar_rule():
    data = {
        "15m": make_candles(300, 15),
        "1h": make_candles(100, 60),
        "4h": make_candles(40, 240),
    }
    entry_index = 201
    next_open = float(data["15m"].iloc[entry_index + 1]["open"])
    data["15m"].loc[entry_index + 1, "high"] = next_open + 100
    data["15m"].loc[entry_index + 1, "low"] = next_open - 100

    result = run_backtest(
        data,
        decision_timeframe="15m",
        signals_override={entry_index: 1},
    )

    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["opened_at"] == data["15m"].iloc[entry_index + 1]["open_time"]
    assert trade["exit_reason"] == "SL"
    assert trade["exit"] < trade["stop_loss"]
    assert trade["pnl_usd"] < 0


def test_metrics_include_seeded_bootstrap_interval_and_drawdown():
    trades = [
        {
            "pnl_usd": 10,
            "initial_risk_usd": 10,
            "duration_seconds": 3600,
        },
        {
            "pnl_usd": -5,
            "initial_risk_usd": 10,
            "duration_seconds": 3600,
        },
    ]
    curve = [
        {"timestamp_ms": 1_700_000_000_000, "equity": 100},
        {"timestamp_ms": 1_700_003_600_000, "equity": 110},
        {"timestamp_ms": 1_700_007_200_000, "equity": 105},
    ]

    metrics = calculate_metrics(trades, curve, 100, bootstrap_iterations=100, seed=7)
    interval = bootstrap_expectancy_ci([1, -0.5], iterations=100, seed=7)

    assert metrics["net_expectancy_r"] == 0.25
    assert metrics["max_drawdown"] == 5 / 110
    assert metrics["expectancy_r_ci_95"] == list(interval)
