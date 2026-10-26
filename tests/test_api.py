import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

_test_data = tempfile.TemporaryDirectory(prefix="mortis-api-tests-")
os.environ["MORTIS_DATA_DIR"] = _test_data.name
os.environ["MORTIS_AUTOTRADE_ENABLED"] = "false"

import server
import engine.paper_trader as paper_trader_module
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
    monkeypatch.setattr(
        paper_trader_module,
        "fetch_intrabar_candles",
        lambda *args, **kwargs: [],
    )
    with TestClient(server.app) as client:
        yield client, price


def test_manual_trade_open_close_updates_account_and_verified_ledger(api_client):
    client, price = api_client

    opened = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 100, "leverage": 5, "stop_loss": 95, "take_profit": 110},
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


def test_health_reports_local_paper_mode_and_active_model(api_client, monkeypatch):
    client, _ = api_client
    monkeypatch.setattr(
        server,
        "load_config",
        lambda: {
            "model": {"active_version": None},
            "risk": {"max_leverage": 5},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["trading_mode"] == "paper"
    assert response.json()["model"] == "deterministic_rule_fallback"
    assert response.json()["model_version"] is None


def test_autonomous_paper_trading_is_opt_in_by_default(monkeypatch):
    monkeypatch.delenv("MORTIS_AUTOTRADE_ENABLED", raising=False)

    assert server.autonomous_trading_enabled() is False


def test_api_rejects_excessive_leverage_and_margin_over_balance(api_client):
    client, _ = api_client

    excessive_leverage = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 100, "leverage": 6, "stop_loss": 95, "take_profit": 110},
    )
    assert excessive_leverage.status_code == 409

    excessive_margin = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 10001, "leverage": 1, "stop_loss": 95, "take_profit": 110},
    )
    assert excessive_margin.status_code == 409
    assert client.get("/api/trades").json()["trades"] == []


def test_manual_entry_requires_and_validates_protective_levels(api_client):
    client, _ = api_client

    missing = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 100, "leverage": 1},
    )
    invalid = client.post(
        "/api/trades",
        json={
            "side": "long",
            "margin_usd": 100,
            "leverage": 1,
            "stop_loss": 105,
            "take_profit": 110,
        },
    )

    assert missing.status_code == 409
    assert invalid.status_code == 409
    assert client.get("/api/trades").json()["trades"] == []
    reasons = {
        decision["rejection_reason"]
        for decision in client.get("/api/decisions?limit=10").json()["decisions"]
    }
    assert reasons == {"rejected_missing_levels", "rejected_invalid_levels"}


def test_chat_execution_rejecting_missing_levels_is_logged(api_client, monkeypatch):
    client, _ = api_client

    class InvalidAgent:
        def __init__(self, paper_trader):
            self.paper_trader = paper_trader

        def execute(self, message):
            self.paper_trader.open_position(
                None, "long", 100, 1, None, 110, 5, source="ai"
            )

    monkeypatch.setattr(server, "TAAgent", InvalidAgent)

    response = client.post(
        "/api/chat",
        json={"message": "Execute this invalid plan", "execute": True},
    )

    assert response.status_code == 409
    decision = server.paper_trader.get_decisions(limit=1)["decisions"][0]
    assert decision["rejection_reason"] == "rejected_missing_levels"


def test_api_accepts_configured_leverage_range(api_client):
    client, _ = api_client

    for leverage in (1, 2, 5):
        opened = client.post(
            "/api/trades",
            json={"side": "long", "margin_usd": 10, "leverage": leverage, "stop_loss": 95, "take_profit": 110},
        )
        assert opened.status_code == 200
        assert opened.json()["trade"]["leverage"] == leverage
        assert client.post("/api/trades/close").status_code == 200

    excessive = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 10, "leverage": 6, "stop_loss": 95, "take_profit": 110},
    )
    assert excessive.status_code == 409


def test_trade_history_api_returns_paginated_closed_trades(api_client):
    client, price = api_client
    opened_ids = []

    for exit_price in (101, 102, 103):
        opened = client.post(
            "/api/trades",
            json={"side": "long", "margin_usd": 10, "leverage": 1, "stop_loss": 95, "take_profit": 110},
        )
        assert opened.status_code == 200
        opened_ids.append(opened.json()["trade"]["id"])
        price["value"] = exit_price
        assert client.post("/api/trades/close").status_code == 200

    first_page = client.get("/api/trades?limit=2&offset=0").json()
    second_page = client.get("/api/trades?limit=2&offset=2").json()

    assert first_page["total"] == 3
    assert [trade["id"] for trade in first_page["trades"]] == opened_ids[-1:-3:-1]
    assert [trade["id"] for trade in second_page["trades"]] == opened_ids[:1]


def test_account_and_trade_routes_work_with_legacy_account_schema(api_client, tmp_path):
    client, _ = api_client
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    with sqlite3.connect(legacy_dir / "mortis.db") as conn:
        conn.executescript(
            """
            CREATE TABLE account (
                id INTEGER PRIMARY KEY,
                balance REAL NOT NULL,
                starting_equity REAL NOT NULL,
                reset_at INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO account VALUES (1, 8000, 10000, 0);
            CREATE TABLE trading_controls (
                id INTEGER PRIMARY KEY,
                peak_equity REAL NOT NULL,
                drawdown_paused INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO trading_controls VALUES (1, 10000, 0);
            CREATE TABLE training_samples (
                decision_id TEXT PRIMARY KEY,
                created_at_ms INTEGER NOT NULL,
                features_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                best_bid REAL,
                best_ask REAL,
                outcome_resolved INTEGER NOT NULL DEFAULT 0,
                outcome_label INTEGER,
                realized_net_r REAL,
                pnl_usd REAL,
                mistake TEXT
            );
            """
        )

    legacy_trader = PaperTrader(str(legacy_dir))
    legacy_trader.open_position(None, "long", 100, 0.1, 95, 110, 5)
    server.paper_trader = legacy_trader

    account = client.get("/api/account")
    trades = client.get("/api/trades?limit=25&offset=0")

    assert account.status_code == 200
    assert account.json()["balance"] == 7990
    assert trades.status_code == 200
    assert trades.json()["total"] == 1
    assert len(trades.json()["trades"]) == 1


def test_chat_is_read_only_unless_execute_is_explicit(api_client, monkeypatch):
    client, _ = api_client
    calls = []
    analysis = {
        "snapshot": {"price": 100},
        "trade_plan": {
            "action": "no_trade",
            "raw_confidence": 0.5,
            "reason_if_no_trade": "No setup",
        },
        "agent_decision": {"rationale": "No setup"},
        "decision_record": None,
    }

    class StubAgent:
        def __init__(self, paper_trader):
            self.paper_trader = paper_trader

        def analyze(self, message):
            calls.append(("analyze", message))
            return analysis

        def execute(self, message):
            calls.append(("execute", message))
            return {
                **analysis,
                "decision_record": {"decision_hash": "paper-hash"},
            }

    monkeypatch.setattr(server, "TAAgent", StubAgent)

    read_only = client.post("/api/chat", json={"message": "Explain the trend"})
    assert read_only.status_code == 200
    assert calls == [("analyze", "Explain the trend")]
    assert "Read-only analysis" in read_only.json()["reply"]

    executed = client.post(
        "/api/chat",
        json={"message": "Execute the signal", "execute": True},
    )
    assert executed.status_code == 200
    assert calls[-1] == ("execute", "Execute the signal")
    assert "paper-hash" in executed.json()["reply"]


def test_chat_labels_promoted_model_probability_as_calibrated(api_client, monkeypatch):
    client, _ = api_client

    class StubAgent:
        def __init__(self, paper_trader):
            pass

        def analyze(self, message):
            return {
                "snapshot": {"price": 100},
                "trade_plan": {
                    "action": "no_trade",
                    "raw_confidence": 0.72,
                    "reason_if_no_trade": "Risk guard",
                },
                "agent_decision": {
                    "rationale": "Promoted model applied.",
                    "calibrated": True,
                },
                "decision_record": None,
            }

    monkeypatch.setattr(server, "TAAgent", StubAgent)

    response = client.post("/api/chat", json={"message": "Explain this setup"})

    assert response.status_code == 200
    assert "72% calibrated model estimate" in response.json()["reply"]
    assert "not a profit guarantee" in response.json()["reply"]


def test_learning_api_includes_all_time_outcome_summary(api_client):
    client, _ = api_client
    trader = server.paper_trader
    trader.record_training_sample(
        "decision-learning-api",
        {"trend": 0.2},
        {"model_version": None},
    )

    response = client.get("/api/learning")
    payload = response.json()

    assert response.status_code == 200
    assert payload["summary"]["sample_count"] == 1
    assert payload["summary"]["resolved_count"] == 0
    assert payload["summary"]["unresolved_count"] == 1
    assert payload["summary"]["mean_realized_net_r"] is None


def test_daily_loss_guard_blocks_next_manual_trade(api_client):
    client, price = api_client
    opened = client.post(
        "/api/trades",
        json={"side": "long", "margin_usd": 5000, "leverage": 1, "stop_loss": 95, "take_profit": 110},
    )
    assert opened.status_code == 200

    price["value"] = 90
    closed = client.post("/api/trades/close")
    assert closed.status_code == 200
    assert closed.json()["trade"]["pnl_usd"] == -505

    blocked = client.post(
        "/api/trades",
        json={"side": "short", "margin_usd": 100, "leverage": 1, "stop_loss": 95, "take_profit": 80},
    )
    assert blocked.status_code == 409
    assert "Daily loss limit" in blocked.json()["detail"]


def test_reset_refuses_open_position_and_does_not_erase_ledger(api_client):
    client, _ = api_client
    opened = client.post(
        "/api/trades",
        json={"side": "short", "margin_usd": 100, "leverage": 1, "stop_loss": 105, "take_profit": 90},
    )
    assert opened.status_code == 200

    reset = client.post("/api/account/reset")

    assert reset.status_code == 409
    ledger = client.get("/api/ledger").json()
    assert ledger["valid"] is True
    assert ledger["records"][-1]["event_type"] == "trade_opened"
