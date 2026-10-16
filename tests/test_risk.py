import pytest
from engine.risk import calculate_risk

NO_FEE_CONFIG = {"fee_pct_round_trip": 0.0, "confidence_threshold": 0.60}

def test_hand_check_test_case():
    """
    Hand-check test case from Week 1 instructions:
    equity 10000, price 60000, ATR 400, long, confidence 0.60
    """
    plan = calculate_risk(
        direction="long",
        confidence=0.60,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG
    )

    assert plan.action == "long"
    assert plan.raw_confidence == 0.60
    assert plan.clamped_confidence == 0.60
    assert plan.size_multiplier == 1.0
    assert plan.risk_amount_usd == 49.98  # Actual stop risk after the notional cap
    assert "capped_by_notional" in plan.flags
    assert plan.notional_usd == 5000.0   # 50% cap of 10000

def test_confidence_clamping():
    plan = calculate_risk(
        direction="long",
        confidence=0.99,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG
    )
    assert plan.clamped_confidence == 0.95
    assert "confidence_clamped" in plan.flags

def test_below_threshold_no_trade():
    plan = calculate_risk(
        direction="long",
        confidence=0.55,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG
    )
    assert plan.action == "no_trade"
    assert "threshold" in plan.reason_if_no_trade

def test_neutral_no_trade():
    plan = calculate_risk(
        direction="neutral",
        confidence=0.80,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG
    )
    assert plan.action == "no_trade"

def test_leverage_scales_notional_cap_and_resulting_stop_risk():
    one_x = calculate_risk(
        direction="long",
        confidence=0.60,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG,
        leverage=1
    )
    five_x = calculate_risk(
        direction="long",
        confidence=0.60,
        price=60000,
        atr=400,
        equity=10000,
        config=NO_FEE_CONFIG,
        leverage=5
    )

    assert one_x.notional_usd == 5000
    assert five_x.notional_usd == 7503.75
    assert five_x.risk_amount_usd > one_x.risk_amount_usd
    assert five_x.leverage == 5

def test_leverage_above_configured_maximum_is_rejected():
    with pytest.raises(ValueError, match="one of 1x, 5x, 10x, 20x, 100x, or 200x"):
        calculate_risk(
            direction="long",
            confidence=0.80,
            price=60000,
            atr=400,
            equity=10000,
            leverage=11
        )

def test_ai_trade_is_rejected_when_target_does_not_cover_round_trip_fee():
    plan = calculate_risk(
        direction="long",
        confidence=0.80,
        price=10000,
        atr=1,
        equity=10000
    )

    assert plan.action == "no_trade"
    assert "fee" in plan.reason_if_no_trade
    assert "fee_exceeds_take_profit" in plan.flags


def test_confidence_selects_supported_leverage_only_when_stop_has_liquidation_buffer():
    plan = calculate_risk(
        direction="long",
        confidence=0.95,
        price=10000,
        atr=40,
        equity=10000,
        leverage=None,
    )

    assert plan.action == "long"
    assert plan.leverage == 100
    assert "leverage_reduced_for_stop" in plan.flags


def test_highest_confidence_can_select_200x_with_a_tight_enough_stop():
    plan = calculate_risk(
        direction="long",
        confidence=0.99,
        price=10000,
        atr=10,
        equity=10000,
        leverage=None,
    )

    assert plan.leverage == 200
    assert plan.clamped_confidence == 0.95
    assert plan.risk_amount_usd <= 112.5
