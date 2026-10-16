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


def test_open_position_persists_across_paper_trader_instances(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "short", 100, 1, None, None, 50, leverage=5)

    reopened_trader = PaperTrader(str(tmp_path))

    assert reopened_trader.get_state()["open_position"]["side"] == "short"
    assert reopened_trader.get_state()["open_position"]["leverage"] == 5
    assert reopened_trader.get_state()["available_balance"] == 9980
    assert reopened_trader.get_ledger()["valid"] is True


def test_manual_trade_reserves_margin_and_charges_round_trip_fee_once_on_close(tmp_path):
    trader = PaperTrader(str(tmp_path))
    opened = trader.open_position(
        decision_id=None,
        side="long",
        entry=100,
        size_btc=2,
        stop_loss=None,
        take_profit=None,
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
        stop_loss=None,
        take_profit=None,
        initial_risk_usd=100,
        leverage=5,
        source="manual",
    )

    closed = trader.close_position(105)

    assert closed["pnl_gross"] == -10
    assert closed["fee_usd"] == 0.2
    assert closed["pnl_usd"] == -10.2
    assert trader.get_state()["equity"] == 9989.8


def test_max_leverage_and_available_margin_are_enforced(tmp_path):
    trader = PaperTrader(str(tmp_path))

    with pytest.raises(ValueError, match="one of 1x, 5x, 10x, 20x, 100x, or 200x"):
        trader.open_position(None, "long", 100, 1, None, None, 100, leverage=11)

    with pytest.raises(RuntimeError, match="Insufficient available"):
        trader.open_position(None, "long", 100, 101, None, None, 10100)


def test_position_liquidation_caps_loss_to_isolated_margin(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(
        decision_id=None,
        side="long",
        entry=100,
        size_btc=10,
        stop_loss=None,
        take_profit=None,
        initial_risk_usd=100,
        leverage=10,
        source="manual",
    )

    trader.settle_open_position(89)
    state = trader.get_state()

    assert state["open_position"] is None
    assert state["closed_trades"][0]["exit_reason"] == "LIQUIDATION"
    assert state["closed_trades"][0]["pnl_usd"] == -100
    assert state["equity"] == 9900


def test_reset_requires_closed_position_and_preserves_audit_history(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 1, None, None, 100)

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


def test_account_balance_is_restored_after_restarting_with_existing_database(tmp_path):
    trader = PaperTrader(str(tmp_path))
    trader.open_position(None, "long", 100, 50, None, None, 500, leverage=1)
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
        trader.open_position(None, "long", 100, 1, None, None, 100)
