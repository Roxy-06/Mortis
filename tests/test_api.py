import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_test_data = tempfile.TemporaryDirectory(prefix="mortis-api-tests-")
os.environ["MORTIS_DATA_DIR"] = _test_data.name
os.environ["MORTIS_AUTOTRADE_ENABLED"] = "false"

import server
from engine.paper_trader import PaperTrader


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    price = {"value": 100.0}
    monkeypatch.setattr(server, "paper_trader", PaperTrader(str(tmp_path)))
    monkeypatch.setattr(
        server,
        "fetch_current_price",
        lambda symbol="BTCUSDT": price["value"],
    )
    with TestClient(server.app) as client:
        yield client, price


def test_manual_trade_open_close_updates_account_and_verified_ledger(api_client):
    client, price = api_client

    opened = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 100, "leverage": 5},
    )
    assert opened.status_code == 200
    assert opened.json()["trade"]["leverage"] == 5

    price["value"] = 110
    closed = client.post("/api/trades/close")
    assert closed.status_code == 200
    assert closed.json()["trade"]["pnl_usd"] == 49.5

    account = client.get("/api/account").json()
    assert account["equity"] == 10049.5
    assert account["total_trades"] == 1
    ledger = client.get("/api/ledger").json()
    assert ledger["valid"] is True
    trade_events = [
        event["event_type"] for event in ledger["records"]
        if event["event_type"].startswith("trade_")
    ]
    assert trade_events == [
        "trade_opened",
        "trade_closed",
    ]


def test_api_rejects_excessive_leverage_and_margin_over_balance(api_client):
    client, _ = api_client

    excessive_leverage = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 100, "leverage": 2},
    )
    assert excessive_leverage.status_code == 422

    excessive_margin = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 10001, "leverage": 1},
    )
    assert excessive_margin.status_code == 409
    assert client.get("/api/trades").json()["trades"] == []


def test_api_accepts_each_supported_leverage_tier(api_client):
    client, _ = api_client

    for leverage in (1, 5, 10, 20, 100, 200):
        opened = client.post(
            "/api/trades",
            json={"side": "long", "margin_usd": 10, "leverage": leverage},
        )
        assert opened.status_code == 200
        assert opened.json()["trade"]["leverage"] == leverage
        assert client.post("/api/trades/close").status_code == 200


def test_daily_loss_guard_blocks_next_manual_trade(api_client):
    client, price = api_client
    opened = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 5000, "leverage": 1},
    )
    assert opened.status_code == 200

    price["value"] = 90
    closed = client.post("/api/trades/close")
    assert closed.status_code == 200
    assert closed.json()["trade"]["pnl_usd"] == -505

    blocked = client.post(
        "/api/trades",
        json={"side": "short", "margin_usd": 100, "leverage": 1},
    )
    assert blocked.status_code == 409
    assert "Daily loss limit" in blocked.json()["detail"]


def test_reset_refuses_open_position_and_does_not_erase_ledger(api_client):
    client, _ = api_client
    opened = client.post(
        "/api/trades",
        json={"side": "short", "margin_usd": 100, "leverage": 1},
    )
    assert opened.status_code == 200

    reset = client.post("/api/account/reset")

    assert reset.status_code == 409
    ledger = client.get("/api/ledger").json()
    assert ledger["valid"] is True
    assert ledger["records"][-1]["event_type"] == "trade_opened"
