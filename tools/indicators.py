import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's Smoothing)"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's Smoothing)"""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr

def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """MACD (12, 26, 9)"""
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram
    }

def find_swing_levels(df: pd.DataFrame, lookback: int = 100, window: int = 3) -> Dict[str, Optional[float]]:
    """Compute swing support and resistance levels"""
    recent = df.tail(lookback).reset_index(drop=True)
    current_price = recent["close"].iloc[-1]
    
    supports = []
    resistances = []
    
    for i in range(window, len(recent) - window):
        low_window = recent["low"].iloc[i - window : i + window + 1]
        high_window = recent["high"].iloc[i - window : i + window + 1]
        
        if recent["low"].iloc[i] == low_window.min():
            supports.append(recent["low"].iloc[i])
        if recent["high"].iloc[i] == high_window.max():
            resistances.append(recent["high"].iloc[i])
            
    valid_supports = [s for s in supports if s < current_price]
    valid_resistances = [r for r in resistances if r > current_price]
    
    return {
        "support": float(max(valid_supports)) if valid_supports else None,
        "resistance": float(min(valid_resistances)) if valid_resistances else None
    }

def compute_timeframe_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute full indicator suite for a single timeframe's closed candles"""
    if len(df) < 200:
        raise ValueError(f"Need >= 200 candles for indicators, got {len(df)}")
        
    closes = df["close"]
    volumes = df["volume"]
    last_idx = df.index[-1]
    last_close = float(closes.iloc[-1])
    
    ema20 = float(calculate_ema(closes, 20).iloc[-1])
    ema50 = float(calculate_ema(closes, 50).iloc[-1])
    ema200 = float(calculate_ema(closes, 200).iloc[-1])
    
    rsi14 = float(calculate_rsi(closes, 14).iloc[-1])
    atr_series = calculate_atr(df, 14)
    atr14 = float(atr_series.iloc[-1])
    atr_pct = float(atr14 / last_close)
    
    macd_res = calculate_macd(closes, 12, 26, 9)
    last_macd = float(macd_res["macd"].iloc[-1])
    last_signal = float(macd_res["signal"].iloc[-1])
    last_hist = float(macd_res["histogram"].iloc[-1])
    prev_hist = float(macd_res["histogram"].iloc[-2])
    
    # Volume ratio: current volume vs avg of previous 20
    avg20_vol = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
    vol_ratio = float(volumes.iloc[-1] / avg20_vol) if avg20_vol > 0 else 1.0
    
    swings = find_swing_levels(df)
    
    return {
        "last_close": round(last_close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "rsi14": round(rsi14, 2),
        "macd": {
            "macd_line": round(last_macd, 2),
            "signal_line": round(last_signal, 2),
            "histogram": round(last_hist, 2),
            "histogram_rising": bool(last_hist > prev_hist)
        },
        "atr14": round(atr14, 2),
        "atr_pct": round(atr_pct, 4),
        "volume_ratio": round(vol_ratio, 2),
        "support_level": round(swings["support"], 2) if swings["support"] else None,
        "resistance_level": round(swings["resistance"], 2) if swings["resistance"] else None,
        "trend_flags": {
            "price_above_ema50": bool(last_close > ema50),
            "ema20_above_ema50": bool(ema20 > ema50),
            "ema50_above_ema200": bool(ema50 > ema200)
        }
    }
