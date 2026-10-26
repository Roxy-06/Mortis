import json
import sqlite3

from research.forward_validation import evaluate_forward_trial


def test_forward_validation_uses_only_resolved_candidate_ai_trades(tmp_path):
    database = tmp_path / "mortis.db"
    metadata_path = tmp_path / "metadata.json"
    report_path = tmp_path / "forward.json"
    trial_start = 1_700_000_000_000
    metadata_path.write_text(
        json.dumps(
            {
                "version": "candidate-a",
                "lifecycle": "paper_trial",
                "paper_trial_started_at_utc": "2023-11-14T22:13:20+00:00",
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE training_samples (
                decision_id TEXT, created_at_ms INTEGER, outcome_resolved INTEGER,
                outcome_label INTEGER, realized_net_r REAL, pnl_usd REAL,
                decision_json TEXT
            );
            CREATE TABLE trades (
                decision_id TEXT, status TEXT, source TEXT, closed_at INTEGER,
                rowid INTEGER PRIMARY KEY, opened_at INTEGER, exit_reason TEXT,
                side TEXT, initial_risk_usd REAL
            );
            """
        )
        for index, days in enumerate((0, 58)):
            decision_id = f"decision-{index}"
            created_at = trial_start + days * 86_400_000
            connection.execute(
                "INSERT INTO training_samples VALUES (?, ?, 1, 1, 0.5, 5, ?)",
                (
                    decision_id,
                    created_at,
                    json.dumps({"model_version": "candidate-a"}),
                ),
            )
            connection.execute(
                "INSERT INTO trades VALUES (?, 'closed', 'ai', ?, ?, ?, 'TP', 'long', 10)",
                (
                    decision_id,
                    created_at + 60_000,
                    index,
                    created_at,
                ),
            )
        connection.execute(
            "INSERT INTO training_samples VALUES (?, ?, 1, 1, 0.5, 5, ?)",
            (
                "other-model",
                trial_start + 59 * 86_400_000,
                json.dumps({"model_version": "different"}),
            ),
        )
        connection.execute(
            "INSERT INTO trades VALUES (?, 'closed', 'ai', ?, 3, ?, 'TP', 'long', 10)",
            (
                "other-model",
                trial_start + 59 * 86_400_000,
                trial_start + 59 * 86_400_000 - 60_000,
            ),
        )

    report = evaluate_forward_trial(database, metadata_path, report_path)

    assert report["resolved_ai_paper_trades"] == 2
    assert report["observed_duration_days"] > 58
    assert report["gates"]["minimum_duration_met"] is True
    assert report["gates"]["minimum_closed_trades_met"] is False
    assert report["forward_validation_passed"] is False
    assert report["real_money_authorization"] is False
