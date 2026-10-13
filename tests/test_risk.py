import pytest
from engine.risk import calculate_risk

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
        equity=10000
    )

    assert plan.action == "long"
    assert plan.raw_confidence == 0.60
    assert plan.clamped_confidence == 0.60
    assert plan.size_multiplier == 1.0
    assert plan.risk_amount_usd == 75.0  # 0.75% of 10000
    assert "capped_by_notional" in plan.flags
    assert plan.notional_usd == 5000.0   # 50% cap of 10000

def test_confidence_clamping():
    plan = calculate_risk(
        direction="long",
        confidence=0.99,
        price=60000,
        atr=400,
        equity=10000
    )
    assert plan.clamped_confidence == 0.95
    assert "confidence_clamped" in plan.flags

def test_below_threshold_no_trade():
    plan = calculate_risk(
        direction="long",
        confidence=0.55,
        price=60000,
        atr=400,
        equity=10000
    )
    assert plan.action == "no_trade"
    assert "threshold" in plan.reason_if_no_trade

def test_neutral_no_trade():
    plan = calculate_risk(
        direction="neutral",
        confidence=0.80,
        price=60000,
        atr=400,
        equity=10000
    )
    assert plan.action == "no_trade"
