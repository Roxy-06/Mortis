import yaml
import os
import math
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

LEVERAGE_OPTIONS = (1, 5, 10, 20, 100, 200)
LEVERAGE_CONFIDENCE_TIERS = (
    (0.95, 200),
    (0.90, 100),
    (0.85, 20),
    (0.80, 10),
    (0.70, 5),
    (0.55, 1),
)

def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {
        "confidence_threshold": 0.55,
        "confidence_cap": 0.95,
        "base_risk_pct": 0.0075,
        "max_size_multiplier": 1.5,
        "max_notional_pct": 0.50,
        "max_leverage": 200,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "slippage_pct": 0.0005,
        "fee_pct_round_trip": 0.001,
    }

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
    flags: List[str] = field(default_factory=list)

def calculate_risk(
    direction: str,  # "long", "short", "neutral"
    confidence: float,
    price: float,
    atr: float,
    equity: float,
    config: Optional[Dict[str, Any]] = None,
    leverage: Optional[int] = 1,
) -> TradePlan:
    """Pure Python risk calculation engine"""
    if config is None:
        config = load_config()

    max_leverage = int(config.get("max_leverage", 200))
    if leverage is not None and (
        int(leverage) not in LEVERAGE_OPTIONS or int(leverage) > max_leverage
    ):
        raise ValueError(
            "Leverage must be one of 1x, 5x, 10x, 20x, 100x, or 200x."
        )
    reported_leverage = int(leverage or 1)

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
    if tp_dist <= entry * fee_pct:
        return TradePlan(
            action="no_trade",
            reason_if_no_trade=(
                f"Expected take-profit move does not cover the {fee_pct:.0%} round-trip fee."
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

    selected_leverage = (
        int(leverage)
        if leverage is not None
        else select_leverage(conf, sl_dist, entry, config)
    )
    confidence_tier = next(
        (tier for minimum, tier in LEVERAGE_CONFIDENCE_TIERS if conf >= minimum),
        1,
    )
    if leverage is None and selected_leverage < confidence_tier:
        flags.append("leverage_reduced_for_stop")

    # Size multiplier
    size_mult = min(max_size_mult, max(1.0, 1.0 + 0.5 * (conf - conf_thresh) / (1.0 - conf_thresh)))
    risk_budget = equity * base_risk * size_mult
    risk_per_btc = sl_dist + entry * fee_pct
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
        flags=flags
    )


def select_leverage(
    confidence: float,
    stop_distance: float,
    entry: float,
    config: Optional[Dict[str, Any]] = None,
) -> int:
    """Choose confidence-tier leverage with a buffer before simulated liquidation."""
    if config is None:
        config = load_config()
    confidence = min(float(confidence), float(config.get("confidence_cap", 0.95)))
    desired = next(
        (tier for minimum, tier in LEVERAGE_CONFIDENCE_TIERS if confidence >= minimum),
        1,
    )
    max_leverage = int(config.get("max_leverage", 200))
    safe_maximum = (
        math.floor(entry / (stop_distance * 1.25))
        if entry > 0 and stop_distance > 0
        else 1
    )
    ceiling = min(desired, max_leverage, safe_maximum)
    return max((value for value in LEVERAGE_OPTIONS if value <= ceiling), default=1)
