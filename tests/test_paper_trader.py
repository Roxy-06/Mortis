import sqlite3

import pytest

from engine.paper_trader import PaperTrader


def test_account_starts_with_ten_thousand_and_empty_verified_ledger(tmp_path):
    trader = PaperTrader(str(tmp_path))

    state = trader.get_state()

    assert state["equity"] == 10000
    assert state["available_balance"] == 10000
    assert state["open_position"] is None
    assert trader.get_ledger()["valid"] is True


def test_legacy_database_schema_is_migrated_without_losing_learning_data(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "mortis.db"
    with sqlite3.connect(db_path) as conn:
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
            INSERT INTO training_samples (
                decision_id, created_at_ms, features_json, decision_json,
                best_bid, best_ask
            ) VALUES ('legacy-decision', 1, '{}', '{}', 99.9, 100.1);
            """
        )

    monkeypatch.setattr(
        "engine.paper_trader.fetch_intrabar_candles",
        lambda *args, **kwargs: [],
    )
    trader = PaperTrader(str(tmp_path))

    assert trader.get_state()["balance"] == 8000
    assert trader.get_training_samples()[0]["decision_id"] == "legacy-decision"
    assert trader.get_training_samples()[0]["quote_status"] == "captured"
    backups = list((tmp_path / "backups").glob("mortis_*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0

    trader.record_training_sample(
        "new-decision",
        {"trend": 0.2},
        {"direction": "long"},
        best_bid=99.9,
        best_ask=100.1,
    )
    trader.open_position("new-decision", "long", 100, 1, 95, 110, 5)
    trader.settle_open_position(100)
    closed = trader.close_position(101)

    assert closed["pnl_usd"] > 0
    assert trader.get_trade_count() == 1
    assert len(trader.get_trades()) == 1
    assert trader.get_learning_summary()["sample_count"] == 2
    with sqlite3.connect(db_path) as conn:
        controls = conn.execute(
            "SELECT last_settlement_at_ms FROM trading_controls WHERE id = 1"
        ).fetchone()
        assert controls[0] > 0

    reopened = PaperTrader(str(tmp_path))
    assert reopened.get_trade_count() == 1
    assert reopened.get_learning_summary()["sample_count"] == 2
    with sqlite3.connect(db_path) as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 2
        assert migrated.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0] == 1


def test_open_position_persists_across_paper_trader_instances(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "short", 100, 1, 105, 90, 50, leverage=5)

    reopened_trader = PaperTrader(str(tmp_path))

    assert reopened_trader.get_state()["open_position"]["side"] == "short"
    assert reopened_trader.get_state()["open_position"]["leverage"] == 5
    assert reopened_trader.get_state()["available_balance"] == 9980
    assert reopened_trader.get_ledger()["valid"] is True


@pytest.mark.parametrize(
    ("side", "stop_loss", "take_profit"),
    [
        ("long", None, 110),
        ("long", 95, None),
        ("long", 100, 110),
        ("long", 95, 100),
        ("short", 90, 110),
        ("short", 105, 100),
    ],
)
def test_open_position_rejects_missing_or_wrong_side_levels(
    tmp_path, side, stop_loss, take_profit
):
    trader = PaperTrader(str(tmp_path))

    with pytest.raises(ValueError):
        trader.open_position(
            None, side, 100, 1, stop_loss, take_profit, 5, leverage=2
        )

    assert trader.get_trade_count() == 0


def test_database_trigger_rejects_open_position_without_levels(tmp_path):
    trader = PaperTrader(str(tmp_path))

    with sqlite3.connect(trader.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO trades (
                id, side, entry, size, notional, leverage, margin, opened_at,
                initial_risk_usd, source, status
            ) VALUES ('unsafe', 'long', 100, 1, 100, 2, 50, 1, 5, 'manual', 'open')
            """
        )


def test_rejected_level_attempt_is_recorded_with_specific_reason(tmp_path):
    trader = PaperTrader(str(tmp_path))

    with pytest.raises(ValueError):
        trader.open_position(
            None, "long", 100, 1, None, 110, 5, source="manual"
        )

    with sqlite3.connect(trader.db_path) as conn:
        assert conn.execute(
            "SELECT rejection_reason FROM decisions"
        ).fetchone()[0] == "rejected_missing_levels"
        assert conn.execute(
            "SELECT event_type FROM trade_events"
        ).fetchone()[0] == "rejected_missing_levels"


def test_catchup_closes_gap_through_stop_once_and_is_idempotent(tmp_path):
    trader = PaperTrader(str(tmp_path))
    opened = trader.open_position(
        None, "long", 100, 1, 95, 110, 5, leverage=2, source="manual"
    )
    candle_open_ms = opened["opened_at"] // 60_000 * 60_000 + 60_000
    candle = {
        "open_time": candle_open_ms,
        "close_time": candle_open_ms + 59_999,
        "open": 94,
        "high": 96,
        "low": 93,
        "close": 94,
    }

    first = trader.catch_up([candle])
    closed = trader.get_trade(opened["id"])
    balance_after_first = trader.get_state()["balance"]
    second = trader.catch_up([])

    assert first["closed_positions"] == 1
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "catchup_stop_loss"
    assert closed["exit_price"] == 94
    assert closed["resolution_source"] == "catchup_replay"
    assert second["closed_positions"] == 0
    assert trader.get_state()["balance"] == balance_after_first
    assert trader.get_ledger()["valid"] is True


def test_catchup_resolves_counterfactual_episode_once(tmp_path, monkeypatch):
    trader = PaperTrader(str(tmp_path))
    decision_id = "counterfactual-decision"
    trader.record_training_sample(
        decision_id,
        {"signal": 0.2},
        {
            "direction": "long",
            "source": "deterministic_rule_fallback",
            "trade_plan": {
                "action": "no_trade",
                "entry": 100,
                "stop_loss": 95,
                "take_profit": 110,
                "size_btc": 1,
            },
        },
    )
    trader.record_decision(
        record={
            "decision_id": decision_id,
            "symbol": "BTCUSDT",
            "config_snapshot": {},
            "learning": {},
        },
        direction="long",
        source="deterministic_rule_fallback",
        confidence=0.5,
        calibrated_probability=None,
        feature_vector={"signal": 0.2},
        indicator_snapshot={},
        trade_plan={
            "action": "no_trade",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "size_btc": 1,
        },
        counterfactual=True,
    )
    episode = trader.get_memory_episodes()["episodes"][0]
    candle_open_ms = episode["created_at_ms"] // 60_000 * 60_000 + 60_000
    monkeypatch.setattr(
        "engine.paper_trader.fetch_intrabar_candles",
        lambda *args, **kwargs: [{
            "open_time": candle_open_ms,
            "close_time": candle_open_ms + 59_999,
            "open": 100,
            "high": 111,
            "low": 99,
            "close": 110,
        }],
    )

    resolved = trader._resolve_counterfactual_episodes(episode["created_at_ms"] + 120_000)
    after_first = trader.get_memory_episodes()["episodes"][0]
    sample = trader.get_training_samples()[0]
    second = trader._resolve_counterfactual_episodes(episode["created_at_ms"] + 120_000)

    assert resolved == 1
    assert after_first["outcome"] == "win"
    assert after_first["resolution_source"] == "counterfactual"
    assert after_first["exit_reason"] == "catchup_take_profit"
    assert sample["outcome_resolved"] == 1
    assert second == 0


def test_manual_trade_reserves_margin_and_charges_round_trip_fee_once_on_close(tmp_path):
    trader = PaperTrader(str(tmp_path))
    opened = trader.open_position(
        decision_id=None,
        side="long",
        entry=100,
        size_btc=2,
        stop_loss=95,
        take_profit=110,
        initial_risk_usd=100,
        leverage=5,
        source="manual",
    )

    assert opened["notional"] == 200
    assert opened["margin"] == 40
    assert trader.get_state()["available_balance"] == 9960
    closed = trader.close_position(110)

    assert closed["pnl_gross"] == 20
    assert closed["fee_usd"] == 0.2
    assert closed["pnl_usd"] == 19.8
    assert closed["duration_seconds"] is not None
    assert trader.get_state()["equity"] == 10019.8
    episode = trader.get_memory_episodes()["episodes"][0]
    assert episode["outcome"] == "win"
    assert episode["lesson_source"] == "rule"
    assert episode["position_id"] == opened["id"]
    ledger = trader.get_ledger()
    assert ledger["valid"] is True
    assert [record["event_type"] for record in ledger["records"]][-2:] == [
        "trade_opened",
        "trade_closed",
    ]


def test_short_loss_is_applied_to_balance_after_round_trip_fee(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(
        decision_id=None,
        side="short",
        entry=100,
        size_btc=2,
        stop_loss=105,
        take_profit=90,
        initial_risk_usd=100,
        leverage=5,
        source="manual",
    )

    closed = trader.close_position(105)

    assert closed["pnl_gross"] == -10
    assert closed["fee_usd"] == 0.2
    assert closed["pnl_usd"] == -10.2
    assert trader.get_state()["equity"] == 9989.8


def test_learning_summary_tracks_resolved_outcomes_model_and_loss_reason(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.record_training_sample(
        "decision-1",
        {"trend": 0.2},
        {"model_version": "candidate-a"},
        best_bid=99.9,
        best_ask=100.0,
        quote_status="captured",
    )
    trader.open_position(
        "decision-1",
        "long",
        100,
        1,
        95,
        110,
        10,
        source="ai",
    )
    trader.close_position(95, "SL")

    summary = trader.get_learning_summary()

    assert summary["sample_count"] == 1
    assert summary["resolved_count"] == 1
    assert summary["unresolved_count"] == 0
    assert summary["win_rate"] == 0
    assert summary["mean_realized_net_r"] == pytest.approx(-1.02)
    assert summary["mean_realized_slippage_bps"] == pytest.approx(0)
    assert summary["loss_reasons"] == {"SL": 1}
    assert summary["resolved_samples_by_model"] == {"candidate-a": 1}


def test_max_leverage_and_available_margin_are_enforced(tmp_path):
    trader = PaperTrader(str(tmp_path))

    with pytest.raises(ValueError, match="between 1x and 5x"):
        trader.open_position(None, "long", 100, 1, None, None, 100, leverage=6)

    with pytest.raises(RuntimeError, match="Insufficient available"):
        trader.open_position(None, "long", 100, 101, 95, 110, 10100)


def test_position_liquidation_caps_loss_to_isolated_margin(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(
        decision_id=None,
        side="long",
        entry=100,
        size_btc=50,
        stop_loss=95,
        take_profit=110,
        initial_risk_usd=1000,
        leverage=5,
        source="manual",
    )

    trader.settle_open_position(79, intrabar_candles=[])
    state = trader.get_state()

    assert state["open_position"] is None
    assert state["closed_trades"][0]["exit_reason"] == "liquidation"
    assert state["closed_trades"][0]["pnl_usd"] == -1000
    assert state["equity"] == 9000


def test_intrabar_conflict_assumes_stop_was_hit_first(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 1, 95, 105, 5)

    trader.settle_open_position(
        100,
        intrabar_candles=[{"open": 100, "high": 106, "low": 94}],
    )

    closed = trader.get_trades(limit=1)[0]
    assert closed["exit_reason"] == "stop_loss"
    assert closed["exit_price"] == 95


def test_intrabar_gap_through_stop_uses_worse_bar_open(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 1, 95, 110, 5)

    trader.settle_open_position(
        100,
        intrabar_candles=[{"open": 90, "high": 101, "low": 89}],
    )

    closed = trader.get_trades(limit=1)[0]
    assert closed["exit_reason"] == "stop_loss"
    assert closed["exit_price"] == 90


def test_consecutive_losses_trigger_persistent_cooldown(tmp_path):
    trader = PaperTrader(str(tmp_path))

    for _ in range(3):
        trader.open_position(None, "long", 100, 0.1, 95, 110, 1)
        trader.close_position(99)

    guard = trader.is_trading_blocked()

    assert guard["blocked"] is True
    assert "Loss cooldown active" in guard["reason"]


def test_drawdown_pause_requires_explicit_reenable(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.config["max_daily_loss_pct"] = 1.0
    trader.open_position(None, "long", 100, 100, 95, 110, 1000)
    trader.close_position(89)

    blocked = trader.is_trading_blocked()
    assert blocked["blocked"] is True
    assert "Drawdown kill-switch" in blocked["reason"]

    trader.reenable_trading()
    assert trader.is_trading_blocked()["blocked"] is False


def test_rolling_expectancy_breach_triggers_auto_pause(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.config["max_consecutive_losses"] = 100
    trader.monitoring_config["rolling_trades_window"] = 30
    trader.monitoring_config["min_rolling_expectancy_r"] = 0.0

    for _ in range(30):
        trader.open_position(None, "long", 100, 0.1, 95, 110, 1)
        trader.close_position(99.5)

    guard = trader.is_trading_blocked()

    assert guard["blocked"] is True
    assert "Rolling trade expectancy" in guard["reason"]


def test_closed_ai_trade_updates_persisted_learning_sample(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.record_training_sample(
        "decision-1",
        {"4h_ema_slope": 0.1},
        {"direction": "long", "trade_plan": {"action": "long"}},
        best_bid=99.9,
        best_ask=100.1,
    )
    trader.open_position(
        "decision-1", "long", 100, 1, 95, 110, 5, source="ai"
    )
    trader.close_position(110, "take_profit")

    sample = trader.get_training_samples()[0]
    assert sample["features"] == {"4h_ema_slope": 0.1}
    assert sample["decision"]["direction"] == "long"
    assert sample["best_bid"] == 99.9
    assert sample["best_ask"] == 100.1
    assert sample["outcome_resolved"] == 1
    assert sample["outcome_label"] == 1
    assert sample["realized_net_r"] > 0


def test_reset_requires_closed_position_and_preserves_audit_history(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 1, 95, 110, 100)

    with pytest.raises(RuntimeError, match="Close the open position"):
        trader.reset_account()

    trader.close_position(101)
    trade_count = len(trader.get_trades())
    state = trader.reset_account()
    ledger = trader.get_ledger()

    assert state["equity"] == 10000
    assert len(trader.get_trades()) == trade_count
    assert ledger["valid"] is True
    assert ledger["records"][-1]["event_type"] == "account_reset"


def test_trade_history_supports_stable_pagination(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trade_ids = []

    for _ in range(3):
        opened = trader.open_position(None, "long", 100, 1, 95, 110, 100)
        trade_ids.append(opened["id"])
        trader.close_position(101)

    first_page = trader.get_trades(limit=2, offset=0)
    second_page = trader.get_trades(limit=2, offset=2)

    assert trader.get_trade_count() == 3
    assert [trade["id"] for trade in first_page] == trade_ids[-1:-3:-1]
    assert [trade["id"] for trade in second_page] == trade_ids[:1]


def test_account_balance_is_restored_after_restarting_with_existing_database(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 50, 95, 110, 500, leverage=1)
    trader.close_position(90.1)

    restarted_trader = PaperTrader(str(tmp_path))

    assert restarted_trader.get_state()["equity"] == 9500
    assert restarted_trader.get_state()["available_balance"] == 9500


def test_tampered_ledger_prevents_new_position(tmp_path):
    trader = PaperTrader(str(tmp_path))
    with sqlite3.connect(trader.db_path) as conn:
        conn.execute("UPDATE ledger SET payload_json = '{}' WHERE sequence = 1")

    assert trader.get_ledger()["valid"] is False
    with pytest.raises(RuntimeError, match="Audit ledger verification failed"):
        trader.open_position(None, "long", 100, 1, 95, 110, 100)
