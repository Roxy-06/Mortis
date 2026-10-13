import time
import requests
import pandas as pd
from typing import Dict, List, Any

BINANCE_BASE_URLS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

def fetch_current_price(symbol: str = "BTCUSDT") -> float:
    """Fetch live ticker price for symbol"""
    last_err = None
    for base_url in BINANCE_BASE_URLS:
        try:
            resp = requests.get(f"{base_url}/api/v3/ticker/price?symbol={symbol}", timeout=5)
            if resp.status_code == 200:
                return float(resp.json()["price"])
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to fetch current price: {last_err}")

def fetch_closed_candles(symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 300) -> pd.DataFrame:
    """
    Fetch public Binance klines and filter out still-forming candles
    (prevents lookahead / repainting bias).
    """
    last_err = None
    for base_url in BINANCE_BASE_URLS:
        try:
            url = f"{base_url}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                raw = resp.json()
                df = pd.DataFrame(raw, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_asset_volume", "number_of_trades",
                    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
                ])
                
                # Convert numeric types
                df["open_time"] = df["open_time"].astype(int)
                df["close_time"] = df["close_time"].astype(int)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)
                
                now_ms = int(time.time() * 1000)
                # Drop unclosed candles
                closed_df = df[df["close_time"] <= now_ms].copy()
                if closed_df.empty:
                    continue
                return closed_df
        except Exception as e:
            last_err = e
            
    raise RuntimeError(f"Failed to fetch candles for {interval}: {last_err}")

def fetch_multi_timeframe_candles(symbol: str = "BTCUSDT", timeframes: List[str] = ["4h", "1h", "15m"]) -> Dict[str, pd.DataFrame]:
    """Fetch multi-timeframe candle datasets"""
    data = {}
    for tf in timeframes:
        data[tf] = fetch_closed_candles(symbol=symbol, interval=tf, limit=300)
    return data
