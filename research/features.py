from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from tools.indicators import calculate_atr, calculate_ema, calculate_macd, calculate_rsi

_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
FEATURE_SCHEMA_VERSION = 1


def _closed_times(frame: pd.DataFrame, timeframe: str) -> pd.Series:
    if "close_time" in frame:
        raw = frame["close_time"]
    elif "open_time" in frame:
        raw = frame["open_time"] + _TIMEFRAME_MINUTES[timeframe] * 60_000
    else:
        raise ValueError(f"{timeframe} candles require open_time or close_time.")
    if pd.api.types.is_numeric_dtype(raw):
        return pd.to_datetime(raw, unit="ms", utc=True)
    return pd.to_datetime(raw, utc=True)


def _rank_last(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=min(30, window)).rank(pct=True)


def _timeframe_features(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{timeframe} candles are missing: {sorted(missing)}")

    data = frame.copy()
    data["_closed_at"] = _closed_times(data, timeframe)
    data = data.sort_values("_closed_at").drop_duplicates("_closed_at", keep="last")
    close = pd.to_numeric(data["close"], errors="raise").astype(float)
    high = pd.to_numeric(data["high"], errors="raise").astype(float)
    low = pd.to_numeric(data["low"], errors="raise").astype(float)
    volume = pd.to_numeric(data["volume"], errors="raise").astype(float)
    atr = calculate_atr(data.assign(high=high, low=low, close=close), 14)
    safe_atr = atr.replace(0, np.nan)
    ema20 = calculate_ema(close, 20)
    ema50 = calculate_ema(close, 50)
    ema200 = calculate_ema(close, 200)
    macd = calculate_macd(close)
    returns = np.log(close / close.shift(1))
    realized_vol = returns.rolling(96, min_periods=30).std()
    bollinger_mean = close.rolling(20, min_periods=20).mean()
    bollinger_std = close.rolling(20, min_periods=20).std()
    bb_width = 4 * bollinger_std / bollinger_mean

    plus_dm = high.diff()
    minus_dm = -low.diff()
    positive_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    negative_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    plus_di = 100 * positive_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / safe_atr
    minus_di = 100 * negative_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / safe_atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    features = pd.DataFrame(index=data.index)
    features[f"{timeframe}_close_ema20_atr"] = (close - ema20) / safe_atr
    features[f"{timeframe}_close_ema50_atr"] = (close - ema50) / safe_atr
    features[f"{timeframe}_close_ema200_atr"] = (close - ema200) / safe_atr
    features[f"{timeframe}_ema20_50_atr"] = (ema20 - ema50) / safe_atr
    features[f"{timeframe}_ema50_200_atr"] = (ema50 - ema200) / safe_atr
    features[f"{timeframe}_ema50_slope_atr"] = (ema50 - ema50.shift(3)) / safe_atr
    features[f"{timeframe}_rsi14"] = calculate_rsi(close, 14)
    features[f"{timeframe}_macd_hist_atr"] = macd["histogram"] / safe_atr
    features[f"{timeframe}_macd_hist_rising"] = (
        macd["histogram"] > macd["histogram"].shift(1)
    ).astype(float)
    features[f"{timeframe}_atr_pct"] = atr / close
    features[f"{timeframe}_atr_pct_rank"] = _rank_last(
        features[f"{timeframe}_atr_pct"], max(30, 90 * 1440 // _TIMEFRAME_MINUTES[timeframe])
    )
    features[f"{timeframe}_realized_vol_96"] = realized_vol
    features[f"{timeframe}_bb_width_rank"] = _rank_last(
        bb_width, max(30, 90 * 1440 // _TIMEFRAME_MINUTES[timeframe])
    )
    features[f"{timeframe}_adx14"] = adx

    volume_mean = volume.shift(1).rolling(20, min_periods=10).mean()
    volume_std = volume.shift(1).rolling(20, min_periods=10).std()
    features[f"{timeframe}_volume_ratio"] = volume / volume_mean.replace(0, np.nan)
    features[f"{timeframe}_volume_z20"] = (volume - volume_mean) / volume_std.replace(0, np.nan)
    if "taker_buy_base_asset_volume" in data:
        features[f"{timeframe}_taker_buy_ratio"] = (
            pd.to_numeric(data["taker_buy_base_asset_volume"], errors="coerce")
            / volume.replace(0, np.nan)
        )
    if "number_of_trades" in data:
        count = pd.to_numeric(data["number_of_trades"], errors="coerce")
        features[f"{timeframe}_trade_count_change"] = count.pct_change().replace(
            [np.inf, -np.inf], np.nan
        )
    volatility_scale = realized_vol.replace(0, np.nan)
    for lag in (1, 4, 16, 96):
        features[f"{timeframe}_return_{lag}_scaled"] = (
            np.log(close / close.shift(lag))
            / (volatility_scale * np.sqrt(lag))
        )

    timestamp = data["_closed_at"]
    minute_of_day = timestamp.dt.hour * 60 + timestamp.dt.minute
    day_of_week = timestamp.dt.dayofweek
    features[f"{timeframe}_hour_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
    features[f"{timeframe}_hour_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
    features[f"{timeframe}_weekday_sin"] = np.sin(2 * np.pi * day_of_week / 7)
    features[f"{timeframe}_weekday_cos"] = np.cos(2 * np.pi * day_of_week / 7)
    features["_closed_at"] = timestamp

    if timeframe == "15m":
        prior_low = low.shift(1).rolling(100, min_periods=20).min()
        prior_high = high.shift(1).rolling(100, min_periods=20).max()
        features["15m_support_distance_atr"] = (close - prior_low) / safe_atr
        features["15m_resistance_distance_atr"] = (prior_high - close) / safe_atr
    return features.reset_index(drop=True)


def build_features(
    candles: Dict[str, pd.DataFrame],
    decision_timeframe: str = "15m",
) -> pd.DataFrame:
    """Build causal, normalized features aligned to fully closed decision bars."""
    if decision_timeframe not in candles:
        raise ValueError(f"Decision timeframe {decision_timeframe!r} was not provided.")
    if any(timeframe not in _TIMEFRAME_MINUTES for timeframe in candles):
        raise ValueError("Unsupported candle timeframe.")

    target = _timeframe_features(candles[decision_timeframe], decision_timeframe)
    target = target.sort_values("_closed_at")
    for timeframe, frame in candles.items():
        if timeframe == decision_timeframe:
            continue
        source = _timeframe_features(frame, timeframe).sort_values("_closed_at")
        target = pd.merge_asof(
            target,
            source,
            on="_closed_at",
            direction="backward",
            suffixes=("", f"_{timeframe}"),
        )
    target = target.rename(columns={"_closed_at": "closed_at"})
    target = target.replace([np.inf, -np.inf], np.nan)
    return target.reset_index(drop=True)


def drop_correlated_features(
    features: pd.DataFrame,
    threshold: float = 0.9,
) -> list[str]:
    """Return a stable feature list after pruning highly correlated columns."""
    if not 0 < threshold < 1:
        raise ValueError("Correlation threshold must be between zero and one.")
    numeric = features.select_dtypes(include=[np.number])
    correlation = numeric.corr().abs()
    upper = correlation.where(np.triu(np.ones(correlation.shape), k=1).astype(bool))
    dropped = {column for column in upper.columns if (upper[column] > threshold).any()}
    return [column for column in numeric.columns if column not in dropped]
