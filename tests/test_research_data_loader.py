import io
import zipfile
from datetime import datetime, timezone

import pandas as pd

from research.data_loader import (
    KLINE_COLUMNS,
    parse_kline_archive,
    update_klines,
    validate_candles,
)


def archive_bytes(rows):
    content = io.StringIO()
    pd.DataFrame(rows, columns=KLINE_COLUMNS).to_csv(content, index=False)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample.csv", content.getvalue())
    return buffer.getvalue()


def test_kline_archive_parser_keeps_full_order_flow_columns():
    raw = [
        1704067200000, "100", "102", "99", "101", "10",
        1704068099999, "1005", 25, "4.5", "451", "0",
    ]
    frame = parse_kline_archive(archive_bytes([KLINE_COLUMNS, raw]))

    assert frame.iloc[0]["open_time"] == raw[0]
    assert frame.iloc[0]["taker_buy_base_asset_volume"] == 4.5
    assert frame.iloc[0]["taker_buy_quote_asset_volume"] == 451
    assert frame.iloc[0]["number_of_trades"] == 25


def test_candle_validation_sorts_deduplicates_and_reports_gaps():
    frame = pd.DataFrame(
        {
            "open_time": [1_700_001_800_000, 1_700_000_000_000, 1_700_000_000_000],
            "close_time": [1_700_001_899_999, 1_700_000_899_999, 1_700_000_899_999],
        }
    )

    cleaned, report = validate_candles(
        frame,
        "15m",
        now=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert len(cleaned) == 2
    assert report["duplicates_removed"] == 1
    assert report["gaps"] == 1
    assert report["future_candles"] == 0
    assert report["valid"] is False


def test_cached_month_is_not_downloaded_again(tmp_path, monkeypatch):
    timestamps = [1_704_067_200_000, 1_704_068_100_000]
    frame = pd.DataFrame(
        {
            "open_time": timestamps,
            "close_time": [value + 899_999 for value in timestamps],
        }
    )
    frame["open_time_utc"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time_utc"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    target = tmp_path / "BTCUSDT_15m_futures.parquet"
    frame.to_parquet(target, index=False)

    def unexpected_download(url):
        raise AssertionError(f"Cached month triggered a download: {url}")

    monkeypatch.setattr("research.data_loader._download", unexpected_download)

    path, report = update_klines(
        "BTCUSDT",
        "15m",
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        data_dir=tmp_path,
    )

    assert path == target
    assert report["rows"] == 2
    assert report["valid"] is True
