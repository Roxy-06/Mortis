import yaml
import os
import math
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

LEVERAGE_OPTIONS = tuple(range(1, 6))

def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError("config.yaml must contain a mapping.")
        return config
    return {
        "symbol": "BTCUSDT",
        "timeframes": ["4h", "1h", "15m"],
        "candles_per_timeframe": 300,
        "atr_timeframe": "1h",
        "starting_equity_usd": 10000.0,
        "risk": {
            "confidence_threshold": 0.55,
            "confidence_cap": 0.95,
            "default_leverage": 2,
            "max_leverage": 5,
            "base_risk_pct": 0.0025,
            "max_size_multiplier": 1.0,
            "max_notional_pct": 0.5,
            "max_open_positions": 1,
            "max_daily_loss_pct": 0.03,
            "max_consecutive_losses": 3,
            "loss_cooldown_hours": 24,
            "max_drawdown_pct": 0.10,
            "max_holding_bars": 48,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.5,
            "fee_pct_round_trip": 0.001,
        },
        "backtest": {
            "fee_per_side_pct": 0.0005,
            "slippage_pct": 0.0005,
            "include_funding": True,
            "intrabar_conflict": "stop_first",
        },
        "model": {
            "active_version": None,
            "margin_over_breakeven": 0.03,
            "kelly_fraction_cap": 0.25,
            "retrain_interval_days": 30,
        },
        "monitoring": {
            "rolling_trades_window": 30,
            "min_rolling_expectancy_r": 0.0,
        },
    }


def risk_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return risk settings while accepting legacy flat settings from callers."""
    nested = config.get("risk", {})
    backtest = config.get("backtest", {})
    flattened = {**config, **(nested if isinstance(nested, dict) else {})}
    if isinstance(backtest, dict):
        flattened.setdefault("slippage_pct", backtest.get("slippage_pct", 0.0005))
        flattened.setdefault(
            "fee_pct_round_trip",
            2 * float(backtest.get("fee_per_side_pct", 0.0005)),
        )
    return flattened

@dataclass
class TradePlan:
    action: str  # "long", "short", "no_trade"
    reason_if_no_trade: Optional[str]
    raw_confidence: float
    clamped_confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    size_btc: float
    notional_usd: float
    risk_amount_usd: float
    size_multiplier: float
    leverage: int
    expected_cost_r: Optional[float] = None
    breakeven_probability: Optional[float] = None
    flags: List[str] = field(default_factory=list)

def calculate_risk(
    direction: str,  # "long", "short", "neutral"
    confidence: float,
    price: float,
    atr: float,
    equity: float,
    config: Optional[Dict[str, Any]] = None,
    leverage: Optional[int] = None,
) -> TradePlan:
    """Pure Python risk calculation engine"""
    if config is None:
        config = load_config()
    config = risk_config(config)

    max_leverage = int(config.get("max_leverage", 5))
    if leverage is not None and (
        int(leverage) < 1 or int(leverage) > max_leverage
    ):
        raise ValueError(
            f"Leverage must be between 1x and {max_leverage}x."
        )
    reported_leverage = int(leverage or config.get("default_leverage", 2))

    flags = []
    raw_conf = confidence
    conf = raw_conf

    conf_cap = config.get("confidence_cap", 0.95)
    conf_thresh = config.get("confidence_threshold", 0.55)
    slippage = config.get("slippage_pct", 0.0005)
    sl_mult = config.get("sl_atr_mult", 1.5)
    tp_mult = config.get("tp_atr_mult", 2.5)
    base_risk = config.get("base_risk_pct", 0.0075)
    max_size_mult = config.get("max_size_multiplier", 1.5)
    max_notional_pct = config.get("max_notional_pct", 0.50)
    fee_pct = config.get("fee_pct_round_trip", 0.001)

    # Clamp confidence
    if conf > conf_cap:
        conf = conf_cap
        flags.append("confidence_clamped")

    # Reject if neutral or below threshold
    if direction == "neutral":
        return TradePlan(
            action="no_trade",
            reason_if_no_trade="Agent proposed neutral direction.",
            raw_confidence=raw_conf,
            clamped_confidence=conf,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            size_btc=0.0,
            notional_usd=0.0,
            risk_amount_usd=0.0,
            size_multiplier=1.0,
            leverage=reported_leverage,
            flags=flags
        )

    if conf < conf_thresh:
        return TradePlan(
            action="no_trade",
            reason_if_no_trade=f"Confidence ({conf:.2f}) below threshold ({conf_thresh}).",
            raw_confidence=raw_conf,
            clamped_confidence=conf,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            size_btc=0.0,
            notional_usd=0.0,
            risk_amount_usd=0.0,
            size_multiplier=1.0,
            leverage=reported_leverage,
            flags=flags
        )

    # Calculate Entry with Slippage
    entry = price * (1 + slippage) if direction == "long" else price * (1 - slippage)

    # Calculate ATR distances
    sl_dist = sl_mult * atr
    tp_dist = tp_mult * atr

    if sl_dist <= 0:
        return TradePlan(
            action="no_trade",
            reason_if_no_trade="Invalid ATR distance (<=0).",
            raw_confidence=raw_conf,
            clamped_confidence=conf,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            size_btc=0.0,
            notional_usd=0.0,
            risk_amount_usd=0.0,
            size_multiplier=1.0,
            leverage=reported_leverage,
            flags=["invalid_atr"]
        )

    stop_loss = entry - sl_dist if direction == "long" else entry + sl_dist
    take_profit = entry + tp_dist if direction == "long" else entry - tp_dist
    total_cost_pct = fee_pct + 2 * slippage
    if tp_dist <= entry * total_cost_pct:
        return TradePlan(
            action="no_trade",
            reason_if_no_trade=(
                "Expected take-profit move does not cover estimated fees and slippage."
            ),
            raw_confidence=raw_conf,
            clamped_confidence=conf,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            size_btc=0.0,
            notional_usd=0.0,
            risk_amount_usd=0.0,
            size_multiplier=1.0,
            leverage=reported_leverage,
            flags=["fee_exceeds_take_profit"]
        )

    selected_leverage = int(leverage) if leverage is not None else select_leverage(
        sl_dist, entry, config
    )
    if selected_leverage < reported_leverage:
        flags.append("leverage_reduced_for_stop")

    # Size multiplier
    size_mult = min(max_size_mult, max(1.0, 1.0 + 0.5 * (conf - conf_thresh) / (1.0 - conf_thresh)))
    risk_budget = equity * base_risk * size_mult
    risk_per_btc = sl_dist + entry * total_cost_pct
    size_btc = risk_budget / risk_per_btc
    notional = size_btc * entry

    # Leverage only expands the exposure ceiling; stop risk remains budgeted.
    max_notional = equity * max_notional_pct * selected_leverage
    if notional > max_notional:
        size_btc = max_notional / entry
        notional = max_notional
        flags.append("capped_by_notional")
    size_btc = math.floor(size_btc * 100_000_000) / 100_000_000
    notional = size_btc * entry
    risk_amount = size_btc * risk_per_btc
    cost_r = entry * total_cost_pct / sl_dist
    reward_r = tp_mult / sl_mult
    breakeven_probability = (1 + cost_r) / (1 + reward_r)

    return TradePlan(
        action=direction,
        reason_if_no_trade=None,
        raw_confidence=raw_conf,
        clamped_confidence=conf,
        entry=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        take_profit=round(take_profit, 2),
        size_btc=round(size_btc, 8),
        notional_usd=round(notional, 2),
        risk_amount_usd=round(risk_amount, 2),
        size_multiplier=round(size_mult, 2),
        leverage=selected_leverage,
        expected_cost_r=round(cost_r, 6),
        breakeven_probability=round(breakeven_probability, 6),
        flags=flags
    )


def select_leverage(
    stop_distance: float,
    entry: float,
    config: Optional[Dict[str, Any]] = None,
) -> int:
    """Apply the configured fixed leverage with a buffer before simulated liquidation."""
    if config is None:
        config = load_config()
    config = risk_config(config)
    desired = int(config.get("default_leverage", 2))
    max_leverage = int(config.get("max_leverage", 5))
    if desired < 1 or desired > max_leverage:
        raise ValueError("Configured default_leverage must be between 1 and max_leverage.")
    safe_maximum = (
        math.floor(entry / (stop_distance * 1.25))
        if entry > 0 and stop_distance > 0
        else 1
    )
    ceiling = min(desired, max_leverage, safe_maximum)
    return max(1, ceiling)
