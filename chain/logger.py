import os
import json
import hashlib
import time
import uuid
from typing import Dict, Any, Optional

def canonicalize_json(data: Dict[str, Any]) -> str:
    """Canonicalize JSON string with sorted keys, no extra whitespace, UTF-8 encoding"""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def compute_decision_hash(data_without_hash: Dict[str, Any]) -> str:
    """Compute SHA-256 digest of canonicalized decision JSON"""
    canonical_str = canonicalize_json(data_without_hash)
    return hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()

def get_decisions_dir() -> str:
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "decisions")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def get_last_decision_hash() -> Optional[str]:
    dec_dir = get_decisions_dir()
    hash_files = sorted([f for f in os.listdir(dec_dir) if f.endswith(".hash")])
    if not hash_files:
        return None
    latest_file = hash_files[-1]
    with open(os.path.join(dec_dir, latest_file), "r") as f:
        return f.read().strip()

def log_decision_record(
    price: float,
    candles_digest: str,
    raw_direction: str,
    rationale: str,
    trade_plan: Dict[str, Any],
    risk_checks: Dict[str, bool],
    model_id: str = "gemini-2.5-flash",
    leverage: int = 1,
) -> Dict[str, Any]:
    """Write decision record to disk with SHA-256 hash and hash chaining"""
    decision_id = f"dec_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    timestamp_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prev_hash = get_last_decision_hash()

    record_no_hash = {
        "schema_version": "1.0",
        "decision_id": decision_id,
        "timestamp_utc": timestamp_utc,
        "symbol": "BTCUSDT",
        "model": model_id,
        "prompt_version": "v1",
        "config_snapshot": {
            "symbol": "BTCUSDT",
            "confidence_threshold": 0.60,
            "confidence_cap": 0.95,
            "base_risk_pct": 0.0075,
            "max_size_multiplier": 1.5,
            "max_notional_pct": 0.50,
            "max_open_positions": 1,
            "max_daily_loss_pct": 0.03,
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.5,
            "fee_pct_round_trip": 0.03,
            "slippage_pct": 0.0005,
            "leverage": leverage
        },
        "inputs": {
            "price": price,
            "candles_digest": candles_digest
        },
        "agent_outputs": [
            {
                "agent": "ta",
                "direction": 1 if raw_direction == "long" else (-1 if raw_direction == "short" else 0),
                "confidence": trade_plan["raw_confidence"],
                "clamped_confidence": trade_plan["clamped_confidence"],
                "rationale": rationale,
                "inputs_digest": candles_digest
            }
        ],
        "score": trade_plan["clamped_confidence"] if raw_direction != "neutral" else 0.0,
        "action": trade_plan["action"],
        "reason_if_no_trade": trade_plan.get("reason_if_no_trade"),
        "trade": {
            "entry": trade_plan["entry"],
            "stop_loss": trade_plan["stop_loss"],
            "take_profit": trade_plan["take_profit"],
            "size_btc": trade_plan["size_btc"],
            "risk_amount_usd": trade_plan["risk_amount_usd"],
            "leverage": leverage,
            "notional_usd": trade_plan["notional_usd"],
            "flags": trade_plan.get("flags", [])
        } if trade_plan["action"] != "no_trade" else None,
        "risk_checks": risk_checks,
        "previous_decision_hash": prev_hash
    }

    decision_hash = compute_decision_hash(record_no_hash)
    full_record = dict(record_no_hash)
    full_record["decision_hash"] = decision_hash

    dec_dir = get_decisions_dir()
    json_path = os.path.join(dec_dir, f"{decision_id}.json")
    hash_path = os.path.join(dec_dir, f"{decision_id}.hash")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_record, f, indent=2)

    with open(hash_path, "w", encoding="utf-8") as f:
        f.write(decision_hash)

    return full_record

def verify_decision_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Verify decision record SHA-256 hash integrity"""
    stored_hash = record.get("decision_hash")
    rec_copy = dict(record)
    rec_copy.pop("decision_hash", None)
    computed_hash = compute_decision_hash(rec_copy)
    return {
        "valid": stored_hash == computed_hash,
        "stored_hash": stored_hash,
        "computed_hash": computed_hash
    }
