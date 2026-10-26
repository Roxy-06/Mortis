import numpy as np
import pandas as pd

from research.features import build_features, drop_correlated_features


def make_candles(periods, interval_minutes, phase=0.0):
    open_times = pd.date_range(
        "2024-01-01", periods=periods, freq=f"{interval_minutes}min", tz="UTC"
    )
    open_time_ms = np.asarray([int(timestamp.timestamp() * 1000) for timestamp in open_times])
    trend = np.linspace(100, 130, periods)
    close = trend + np.sin(np.arange(periods) / 7 + phase)
    return pd.DataFrame(
        {
            "open_time": open_time_ms,
            "close_time": open_time_ms + interval_minutes * 60_000 - 1,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.linspace(100, 200, periods),
            "number_of_trades": np.arange(periods) + 1,
            "taker_buy_base_asset_volume": np.linspace(45, 110, periods),
        }
    )


def make_timeframes():
    return {
        "15m": make_candles(300, 15),
        "1h": make_candles(150, 60),
        "4h": make_candles(50, 240),
    }


def test_features_are_unchanged_when_future_rows_are_added():
    candles = make_timeframes()
    cut = 220
    past = {
        timeframe: frame.iloc[: min(len(frame), cut)].copy()
        for timeframe, frame in candles.items()
    }
    full_features = build_features(candles)
    past_features = build_features(past)

    full_row = full_features.loc[full_features["closed_at"] <= past_features["closed_at"].iloc[-1]].iloc[-1]
    past_row = past_features.iloc[-1]
    pd.testing.assert_series_equal(
        full_row.drop(labels="closed_at"),
        past_row.drop(labels="closed_at"),
        check_names=False,
    )


def test_future_higher_timeframe_candle_cannot_change_prior_features():
    original = make_timeframes()
    changed = make_timeframes()
    for column in ("open", "high", "low", "close"):
        changed["4h"].loc[14:, column] += 10

    original_features = build_features(original)
    changed_features = build_features(changed)
    row_index = 180

    pd.testing.assert_series_equal(
        original_features.iloc[row_index].drop(labels="closed_at"),
        changed_features.iloc[row_index].drop(labels="closed_at"),
        check_names=False,
    )


def test_features_are_normalized_and_correlation_pruning_is_stable():
    features = build_features(make_timeframes())
    numeric_columns = features.select_dtypes(include=[np.number]).columns
    assert not any(
        column in {"close", "open", "high", "low", "volume"}
        for column in numeric_columns
    )

    kept = drop_correlated_features(features)

    assert len(kept) > 0
    assert all(column in numeric_columns for column in kept)
