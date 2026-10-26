import json
import sqlite3

import pandas as pd

from research.feedback import load_resolved_paper_feedback


def test_resolved_paper_trade_is_added_as_training_feedback(tmp_path):
    database = tmp_path / "mortis.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE training_samples (
                decision_id TEXT, created_at_ms INTEGER, features_json TEXT,
                decision_json TEXT, outcome_resolved INTEGER, outcome_label INTEGER,
                realized_net_r REAL, pnl_usd REAL
            );
            CREATE TABLE trades (
                decision_id TEXT, side TEXT, initial_risk_usd REAL,
                exit_reason TEXT, closed_at INTEGER, status TEXT, source TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO training_samples VALUES (?, ?, ?, ?, 1, 0, -0.5, -5)",
            (
                "decision-1",
                1_700_000_000_000,
                json.dumps({"trend": 0.4, "momentum": -0.2}),
                json.dumps(
                    {"trade_plan": {"breakeven_probability": 0.52}}
                ),
            ),
        )
        connection.execute(
            "INSERT INTO trades VALUES (?, 'long', 10, 'SL', ?, 'closed', 'ai')",
            ("decision-1", 1_700_003_600_000),
        )

    original_features = pd.DataFrame(
        {
            "closed_at": pd.to_datetime(["2023-11-14T00:00:00Z"]),
            "trend": [0.1],
            "momentum": [0.2],
        }
    )
    combined_features, feedback = load_resolved_paper_feedback(
        original_features, database
    )

    assert len(combined_features) == 2
    assert combined_features.iloc[-1]["trend"] == 0.4
    assert feedback.iloc[0]["direction"] == 1
    assert feedback.iloc[0]["label"] == 0
    assert feedback.iloc[0]["exit_reason"] == "SL"
    assert feedback.iloc[0]["breakeven_probability"] == 0.52


def test_feedback_loader_returns_empty_when_account_database_is_missing(tmp_path):
    features = pd.DataFrame({"trend": [1.0]})

    combined, feedback = load_resolved_paper_feedback(
        features, tmp_path / "missing.db"
    )

    assert combined.equals(features)
    assert feedback.empty
