import pytest
from engine.risk import calculate_risk

NO_FEE_CONFIG = {
    "risk": {
        "confidence_threshold": 0.60,
        "confidence_cap": 0.95,
        "default_leverage": 2,
        "max_leverage": 5,
        "base_risk_pct": 0.0025,
        "max_size_multiplier": 1.0,
        "max_notional_pct": 0.5,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "fee_pct_round_trip": 0.0,
    },
    "backtest": {"slippage_pct": 0.0},
}

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
    assert plan.risk_amount_usd == pytest.approx(25.0)
    assert plan.notional_usd == pytest.approx(2500.0)
    assert plan.leverage == 2

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

def test_leverage_only_changes_position_ceiling_not_stop_risk_budget():
    constrained_config = {
        **NO_FEE_CONFIG,
        "risk": {**NO_FEE_CONFIG["risk"], "max_notional_pct": 0.1},
    }
    one_x = calculate_risk(
        direction="long",
        confidence=0.60,
        price=60000,
        atr=400,
        equity=10000,
        config=constrained_config,
        leverage=1
    )
    five_x = calculate_risk(
        direction="long",
        confidence=0.60,
        price=60000,
        atr=400,
        equity=10000,
        config=constrained_config,
        leverage=5
    )

    assert one_x.notional_usd == 1000
    assert five_x.notional_usd == 2500
    assert five_x.risk_amount_usd > one_x.risk_amount_usd
    assert five_x.leverage == 5

def test_leverage_above_configured_maximum_is_rejected():
    with pytest.raises(ValueError, match="between 1x and 5x"):
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


def test_leverage_is_fixed_and_independent_of_confidence():
    moderate = calculate_risk(
        direction="long",
        confidence=0.70,
        price=10000,
        atr=40,
        equity=10000,
        leverage=None,
    )
    high = calculate_risk(
        direction="long",
        confidence=0.95,
        price=10000,
        atr=40,
        equity=10000,
        leverage=None,
    )

    assert moderate.leverage == high.leverage == 2


def test_stop_distance_reduces_configured_leverage():
    config = {
        **NO_FEE_CONFIG,
        "risk": {**NO_FEE_CONFIG["risk"], "default_leverage": 5},
    }
    plan = calculate_risk(
        direction="long",
        confidence=0.70,
        price=10000,
        atr=10000,
        equity=10000,
        config=config,
        leverage=None,
    )

    assert plan.leverage == 1
    assert "leverage_reduced_for_stop" in plan.flags


def test_cost_and_breakeven_probability_include_fees_and_slippage():
    config = {
        **NO_FEE_CONFIG,
        "risk": {
            **NO_FEE_CONFIG["risk"],
            "fee_pct_round_trip": 0.001,
        },
        "backtest": {"slippage_pct": 0.0005},
    }
    plan = calculate_risk(
        direction="long",
        confidence=0.70,
        price=10000,
        atr=100,
        equity=10000,
        config=config,
        leverage=None,
    )

    assert plan.expected_cost_r == pytest.approx(0.1334)
    assert plan.breakeven_probability == pytest.approx(0.425025)
