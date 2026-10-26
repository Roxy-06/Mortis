import numpy as np
import pandas as pd

from research.backtest import run_backtest
from research.features import build_features
from research.labels import (
    build_labels,
    label_uniqueness_weights,
    purged_walk_forward_splits,
)


def make_candles(periods, interval_minutes):
    times = pd.date_range(
        "2024-01-01", periods=periods, freq=f"{interval_minutes}min", tz="UTC"
    )
    open_ms = np.asarray([int(value.timestamp() * 1000) for value in times])
    close = 100 + np.arange(periods) * 0.03 + np.sin(np.arange(periods) / 7)
    return pd.DataFrame(
        {
            "open_time": open_ms,
            "close_time": open_ms + interval_minutes * 60_000 - 1,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(periods, 100.0),
        }
    )


def market_data():
    return {
        "15m": make_candles(300, 15),
        "1h": make_candles(100, 60),
        "4h": make_candles(40, 240),
    }


def test_triple_barrier_label_matches_backtest_outcome():
    data = market_data()
    features = build_features(data)
    features["4h_close_ema50_atr"] = -1
    features["4h_ema20_50_atr"] = 1
    features.loc[200, "4h_close_ema50_atr"] = 1
    features.loc[200, "1h_rsi14"] = 50
    features.loc[200, "15m_macd_hist_rising"] = 1

    labels = build_labels(data, features=features)
    matching = labels.loc[
        (labels["candidate_index"] == 200) & (labels["direction"] == 1)
    ].iloc[0]
    replay = run_backtest(
        data,
        signals_override={200: 1},
        feature_frame=features,
    )["trades"][0]

    assert matching["exit_reason"] == replay["exit_reason"]
    assert matching["pnl_usd"] == replay["pnl_usd"]
    assert matching["realized_net_r"] == (
        replay["pnl_usd"] / replay["initial_risk_usd"]
    )


def test_label_uniqueness_weights_decrease_for_overlapping_labels():
    labels = pd.DataFrame(
        {
            "entry_index": [1, 2],
            "label_end_index": [4, 5],
        }
    )

    weights = label_uniqueness_weights(labels)

    assert 0 < weights.iloc[0] < 1
    assert 0 < weights.iloc[1] < 1


def test_walk_forward_splits_purge_overlap_and_embargo():
    labels = pd.DataFrame(
        {
            "candidate_index": np.arange(0, 120, 10),
            "label_end_index": np.arange(0, 120, 10) + 3,
        }
    )

    splits = purged_walk_forward_splits(labels, n_splits=3, embargo_bars=3)

    assert len(splits) == 3
    for training, validation in splits:
        first_validation = labels.iloc[validation[0]]["candidate_index"]
        assert all(
            labels.iloc[index]["label_end_index"] < first_validation - 3
            for index in training
        )
