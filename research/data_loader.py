from __future__ import annotations

import argparse
import io
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "research_data"
REPORT_DIR = ROOT / "research" / "reports"
BINANCE_VISION = "https://data.binance.vision/data/futures/um/monthly/klines"
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def month_starts(start: datetime, end: datetime) -> Iterable[datetime]:
    month = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    while month < end:
        yield month
        month = (
            datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
            if month.month == 12
            else datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
        )


def parse_kline_archive(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        csv_files = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(csv_files) != 1:
            raise ValueError("Kline archive must contain exactly one CSV file.")
        with archive.open(csv_files[0]) as csv_file:
            frame = pd.read_csv(csv_file, header=None, names=KLINE_COLUMNS)
    frame = frame.loc[frame["open_time"].astype(str).str.lower() != "open_time"].copy()
    for column in ("open_time", "close_time", "number_of_trades"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    frame["open_time_utc"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time_utc"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    return frame


def validate_candles(
    frame: pd.DataFrame,
    interval: str,
    now: Optional[datetime] = None,
) -> tuple[pd.DataFrame, dict]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported kline interval: {interval}")
    data = frame.copy()
    for column in ("open_time", "close_time"):
        if column not in data:
            raise ValueError(f"Missing required timestamp column {column}.")
        data[column] = pd.to_numeric(data[column], errors="raise").astype("int64")
    initial_count = len(data)
    data = data.sort_values("open_time").drop_duplicates("open_time", keep="last")
    duplicate_count = initial_count - len(data)
    current_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    future = data.loc[data["close_time"] > current_ms, "open_time"].tolist()
    differences = data["open_time"].diff().dropna()
    gaps = data.loc[differences[differences != INTERVAL_MS[interval]].index, "open_time"]
    report = {
        "interval": interval,
        "rows": len(data),
        "duplicates_removed": duplicate_count,
        "future_candles": len(future),
        "gaps": len(gaps),
        "gap_open_times_utc": [
            datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat()
            for value in gaps.head(100)
        ],
        "valid": not future and not len(gaps),
    }
    data["open_time_utc"] = pd.to_datetime(data["open_time"], unit="ms", utc=True)
    data["close_time_utc"] = pd.to_datetime(data["close_time"], unit="ms", utc=True)
    return data.reset_index(drop=True), report


def _download(url: str, attempts: int = 4) -> bytes:
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except requests.RequestException as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to download {url}: {last_error}") from last_error


def _load_cached(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def update_klines(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    data_dir: Path = DATA_DIR,
) -> tuple[Path, dict]:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{symbol}_{interval}_futures.parquet"
    existing = _load_cached(path)
    covered_months = set()
    if not existing.empty:
        existing["open_time"] = pd.to_numeric(existing["open_time"], errors="raise").astype("int64")
        covered_months = {
            (stamp.year, stamp.month)
            for stamp in pd.to_datetime(existing["open_time"], unit="ms", utc=True)
        }

    downloaded = []
    for month in month_starts(start, end):
        if (month.year, month.month) in covered_months:
            continue
        name = f"{symbol}-{interval}-{month.year}-{month.month:02d}.zip"
        url = f"{BINANCE_VISION}/{symbol}/{interval}/{name}"
        downloaded.append(parse_kline_archive(_download(url)))
        time.sleep(0.2)

    if downloaded:
        combined = pd.concat([existing, *downloaded], ignore_index=True)
    else:
        combined = existing
    if combined.empty:
        raise RuntimeError(f"No {interval} futures candles found for {symbol}.")
    combined, validation = validate_candles(combined, interval)
    combined.to_parquet(path, index=False)
    return path, validation


def update_funding_rates(
    symbol: str,
    start: datetime,
    end: datetime,
    data_dir: Path = DATA_DIR,
) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{symbol}_funding_rates.parquet"
    existing = _load_cached(path)
    covered_months = set()
    if not existing.empty:
        times = pd.to_datetime(existing["fundingTime"], unit="ms", utc=True)
        covered_months = {(stamp.year, stamp.month) for stamp in times}
    rows = []
    for month in month_starts(start, end):
        if (month.year, month.month) in covered_months:
            continue
        month_end = (
            datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
            if month.month == 12
            else datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
        )
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={
                "symbol": symbol,
                "startTime": int(month.timestamp() * 1000),
                "endTime": int(month_end.timestamp() * 1000) - 1,
                "limit": 1000,
            },
            timeout=30,
        )
        response.raise_for_status()
        rows.extend(response.json())
        time.sleep(0.2)
    if rows:
        existing = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    if existing.empty:
        raise RuntimeError("No funding-rate history was returned.")
    existing = existing.drop_duplicates("fundingTime", keep="last").sort_values("fundingTime")
    existing.to_parquet(path, index=False)
    return path


def write_validation_report(reports: dict, path: Path = REPORT_DIR / "data_validation.md") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Historical data validation",
        "",
        "Source: Binance USD-M futures monthly klines. Reports show detected gaps; any gap",
        "must be explained before the dataset is used for model evaluation.",
        "",
        "| Interval | Rows | Duplicates removed | Future candles | Gaps | Valid |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for interval, report in reports.items():
        lines.append(
            f"| {interval} | {report['rows']} | {report['duplicates_removed']} | "
            f"{report['future_candles']} | {report['gaps']} | {report['valid']} |"
        )
    for interval, report in reports.items():
        lines.extend(["", f"## {interval} gap timestamps", ""])
        lines.extend(f"- {stamp}" for stamp in report["gap_open_times_utc"])
        if not report["gap_open_times_utc"]:
            lines.append("- None detected.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache and validate Binance futures history.")
    parser.add_argument("--update", action="store_true", help="Fetch missing monthly archives.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default=None, help="UTC date; defaults to four years ago.")
    parser.add_argument("--end", default=None, help="UTC date; defaults to the current month.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--skip-funding", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    start = (
        datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        if args.start
        else now.replace(year=now.year - 4, day=1, hour=0, minute=0, second=0, microsecond=0)
    )
    end = (
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        if args.end
        else datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    )
    if not args.update:
        parser.error("Use --update to download missing data.")
    reports = {}
    for interval in ("15m", "1h", "4h"):
        path, reports[interval] = update_klines(
            args.symbol, interval, start, end, args.data_dir
        )
        print(f"{interval}: {path} ({reports[interval]['rows']} rows)")
    if not args.skip_funding:
        funding_path = update_funding_rates(args.symbol, start, end, args.data_dir)
        print(f"funding: {funding_path}")
    write_validation_report(reports)
    if any(not report["valid"] for report in reports.values()):
        raise SystemExit("Validation found future candles or unexplained gaps.")


if __name__ == "__main__":
    main()
