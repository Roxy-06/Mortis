import pytest
from chain.logger import (
    canonicalize_json,
    compute_decision_hash,
    log_decision_record,
    verify_decision_record,
)

def test_canonical_json_key_sorting():
    obj1 = {"b": 2, "a": 1, "c": {"z": 10, "y": 20}}
    obj2 = {"a": 1, "c": {"y": 20, "z": 10}, "b": 2}
    assert canonicalize_json(obj1) == canonicalize_json(obj2)

def test_decision_hash_verification():
    record_no_hash = {
        "schema_version": "1.0",
        "decision_id": "test_123",
        "timestamp_utc": "2026-10-08T18:00:00Z",
        "symbol": "BTCUSDT",
        "model": "gemini-2.5-flash",
        "prompt_version": "v1",
        "config_snapshot": {"threshold": 0.6},
        "inputs": {"price": 60000},
        "agent_outputs": [],
        "score": 0.7,
        "action": "long",
        "reason_if_no_trade": None,
        "trade": None,
        "risk_checks": {"threshold_ok": True},
        "previous_decision_hash": None
    }

    hash_val = compute_decision_hash(record_no_hash)
    record = dict(record_no_hash)
    record["decision_hash"] = hash_val

    res = verify_decision_record(record)
    assert res["valid"] is True

    # Tamper test
    record["score"] = 0.8
    res_tampered = verify_decision_record(record)
    assert res_tampered["valid"] is False


def test_decision_record_preserves_exact_loaded_config(tmp_path, monkeypatch):
    import chain.logger as logger

    monkeypatch.setattr(logger, "get_decisions_dir", lambda: str(tmp_path))
    config = {
        "symbol": "BTCUSDT",
        "risk": {"max_leverage": 5, "default_leverage": 2},
        "model": {"active_version": None},
    }
    plan = {
        "action": "no_trade",
        "raw_confidence": 0.5,
        "clamped_confidence": 0.5,
        "reason_if_no_trade": "neutral",
    }

    record = log_decision_record(
        price=100,
        candles_digest="digest",
        raw_direction="neutral",
        rationale="No setup",
        trade_plan=plan,
        risk_checks={},
        config_snapshot=config,
    )

    assert record["config_snapshot"] == config
    assert record["symbol"] == config["symbol"]
    assert verify_decision_record(record)["valid"] is True
