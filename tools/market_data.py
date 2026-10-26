import time
import requests
import pandas as pd
from typing import Dict, List, Any, Optional

BINANCE_BASE_URLS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
]


def _candle_frame(raw: list) -> pd.DataFrame:
    frame = pd.DataFrame(raw, columns=KLINE_COLUMNS)
    for column in ("open_time", "close_time", "number_of_trades"):
        frame[column] = frame[column].astype("int64")
    for column in (
        "open", "high", "low", "close", "volume", "quote_asset_volume",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"
    ):
        frame[column] = frame[column].astype(float)
    return frame

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


def fetch_best_bid_ask(symbol: str = "BTCUSDT") -> Dict[str, float]:
    """Fetch public top-of-book prices for paper execution-quality records."""
    last_err = None
    for base_url in BINANCE_BASE_URLS:
        try:
            response = requests.get(
                f"{base_url}/api/v3/ticker/bookTicker?symbol={symbol}", timeout=5
            )
            response.raise_for_status()
            quote = response.json()
            bid = float(quote["bidPrice"])
            ask = float(quote["askPrice"])
            if bid <= 0 or ask < bid:
                raise ValueError("Market quote returned an invalid bid/ask.")
            return {"best_bid": bid, "best_ask": ask}
        except (requests.RequestException, ValueError, KeyError) as error:
            last_err = error
    raise RuntimeError(f"Failed to fetch best bid/ask: {last_err}")


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
                df = _candle_frame(raw)
                
                now_ms = int(time.time() * 1000)
                # Drop unclosed candles
                closed_df = df[df["close_time"] <= now_ms].copy()
                if closed_df.empty:
                    continue
                return closed_df
        except Exception as e:
            last_err = e
            
    raise RuntimeError(f"Failed to fetch candles for {interval}: {last_err}")


def fetch_intrabar_candles(
    symbol: str = "BTCUSDT",
    start_time_ms: Optional[int] = None,
    end_time_ms: Optional[int] = None,
    closed_only: bool = False,
) -> pd.DataFrame:
    """Fetch 1-minute bars, paginating when a persisted check time is old."""
    cursor = int(start_time_ms) if start_time_ms is not None else None
    end = int(end_time_ms) if end_time_ms is not None else None
    collected = []
    last_err = None
    for _ in range(100):
        params: Dict[str, Any] = {"symbol": symbol, "interval": "1m", "limit": 1000}
        if cursor is not None:
            params["startTime"] = cursor
        if end is not None:
            params["endTime"] = end
        page = None
        for base_url in BINANCE_BASE_URLS:
            try:
                response = requests.get(
                    f"{base_url}/api/v3/klines", params=params, timeout=10
                )
                response.raise_for_status()
                page = _candle_frame(response.json())
                break
            except (requests.RequestException, ValueError, KeyError) as error:
                last_err = error
        if page is None:
            raise RuntimeError(f"Failed to fetch 1m settlement candles: {last_err}")
        if cursor is not None:
            page = page[page["open_time"] >= cursor]
        if end is not None:
            page = page[page["open_time"] <= end]
        if closed_only:
            page = page[page["close_time"] <= int(time.time() * 1000)]
        if not page.empty:
            collected.append(page)
        if len(page) < 1000:
            break
        next_cursor = int(page.iloc[-1]["open_time"]) + 60_000
        if cursor is not None and next_cursor <= cursor:
            raise RuntimeError("1m candle pagination did not advance.")
        cursor = next_cursor
        if end is not None and cursor > end:
            break
    else:
        raise RuntimeError("1m candle catch-up exceeded the 100-page safety limit.")
    if collected:
        candles = pd.concat(collected, ignore_index=True)
        return (
            candles.drop_duplicates("open_time")
            .sort_values("open_time")
            .reset_index(drop=True)
        )
    if last_err is not None:
        raise RuntimeError(f"Failed to fetch 1m settlement candles: {last_err}")
    return _candle_frame([])


def fetch_multi_timeframe_candles(
    symbol: str = "BTCUSDT",
    timeframes: List[str] | None = None,
    limit: int = 300,
) -> Dict[str, pd.DataFrame]:
    """Fetch multi-timeframe candle datasets"""
    if timeframes is None:
        timeframes = ["4h", "1h", "15m"]
    data = {}
    for tf in timeframes:
        data[tf] = fetch_closed_candles(symbol=symbol, interval=tf, limit=limit)
    return data
