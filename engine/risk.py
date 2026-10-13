import yaml
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {
        "confidence_threshold": 0.60,
        "confidence_cap": 0.95,
        "base_risk_pct": 0.0075,
        "max_size_multiplier": 1.5,
        "max_notional_pct": 0.50,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "slippage_pct": 0.0005,
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
    flags: List[str] = field(default_factory=list)

def calculate_risk(
    direction: str,  # "long", "short", "neutral"
    confidence: float,
    price: float,
    atr: float,
    equity: float,
    config: Optional[Dict[str, Any]] = None
) -> TradePlan:
    """Pure Python risk calculation engine"""
    if config is None:
        config = load_config()

    flags = []
    raw_conf = confidence
    conf = raw_conf

    conf_cap = config.get("confidence_cap", 0.95)
    conf_thresh = config.get("confidence_threshold", 0.60)
    slippage = config.get("slippage_pct", 0.0005)
    sl_mult = config.get("sl_atr_mult", 1.5)
    tp_mult = config.get("tp_atr_mult", 2.5)
    base_risk = config.get("base_risk_pct", 0.0075)
    max_size_mult = config.get("max_size_multiplier", 1.5)
    max_notional_pct = config.get("max_notional_pct", 0.50)

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
            flags=["invalid_atr"]
        )

    stop_loss = entry - sl_dist if direction == "long" else entry + sl_dist
    take_profit = entry + tp_dist if direction == "long" else entry - tp_dist

    # Size multiplier
    size_mult = min(max_size_mult, max(1.0, 1.0 + 0.5 * (conf - conf_thresh) / (1.0 - conf_thresh)))
    risk_amount = equity * base_risk * size_mult
    size_btc = risk_amount / sl_dist
    notional = size_btc * entry

    # Max notional cap (50% equity)
    max_notional = equity * max_notional_pct
    if notional > max_notional:
        size_btc = max_notional / entry
        notional = max_notional
        flags.append("capped_by_notional")

    return TradePlan(
        action=direction,
        reason_if_no_trade=None,
        raw_confidence=raw_conf,
        clamped_confidence=conf,
        entry=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        take_profit=round(take_profit, 2),
        size_btc=round(size_btc, 6),
        notional_usd=round(notional, 2),
        risk_amount_usd=round(risk_amount, 2),
        size_multiplier=round(size_mult, 2),
        flags=flags
    )
