from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from engine.risk import load_config

ROOT = Path(__file__).resolve().parents[1]


def _database_path() -> Path:
    return Path(
        os.getenv("MORTIS_DATA_DIR", str(ROOT / "data"))
    ) / "mortis.db"


def eligibility(database: Path, config: dict) -> dict:
    if not database.is_file():
        raise FileNotFoundError(f"Mortis database not found: {database}")
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        values = {
            row[0]: json.loads(row[1])
            for row in conn.execute(
                "SELECT key, value_json FROM system_state "
                "WHERE key = 'last_training_at_ms'"
            )
        }
        last_training = int(values.get("last_training_at_ms") or 0)
        total = int(
            conn.execute(
                "SELECT COUNT(*) FROM training_samples WHERE outcome_resolved = 1"
            ).fetchone()[0]
        )
        new = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM training_samples
                WHERE outcome_resolved = 1 AND created_at_ms > ?
                """,
                (last_training,),
            ).fetchone()[0]
        )
    settings = config.get("learning", {})
    minimum_new = int(settings.get("retrain_min_new", 50))
    minimum_total = int(settings.get("min_total_for_training", 200))
    return {
        "eligible": new >= minimum_new and total >= minimum_total,
        "new_resolved": new,
        "minimum_new": minimum_new,
        "resolved_total": total,
        "minimum_total": minimum_total,
        "last_training_at_ms": last_training or None,
    }


def run_retrain(start: str, end: str, timeframe: str, database: Path) -> int:
    config = load_config()
    status = eligibility(database, config)
    print(json.dumps(status, indent=2))
    if not status["eligible"]:
        print("Retraining skipped: configured resolved-sample thresholds are not met.")
        return 0

    subprocess.run(
        [
            sys.executable,
            "-m",
            "research.train",
            "--start",
            start,
            "--end",
            end,
            "--timeframe",
            timeframe,
        ],
        cwd=ROOT,
        check=True,
    )
    now = int(time.time() * 1000)
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            INSERT INTO system_state (key, value_json, updated_at_ms)
            VALUES ('last_training_at_ms', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at_ms = excluded.updated_at_ms
            """,
            (json.dumps(now), now),
        )
        conn.execute(
            """
            INSERT INTO trade_events (
                trade_id, decision_id, event_type, created_at_ms, details_json
            ) VALUES (NULL, NULL, 'challenger_trained', ?, ?)
            """,
            (
                now,
                json.dumps(
                    {
                        "training_range": {"start": start, "end": end},
                        "resolved_feedback_count": status["new_resolved"],
                        "promotion": "not automatic; holdout and approval required",
                    },
                    sort_keys=True,
                ),
            ),
        )
    print(
        "Challenger training finished. It was not promoted; use the existing "
        "holdout and explicit paper-trial approval workflow."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check resolved-paper-data thresholds and train a challenger."
    )
    parser.add_argument("--check", action="store_true", help="Only report eligibility.")
    parser.add_argument("--start", help="Inclusive UTC research start date (YYYY-MM-DD).")
    parser.add_argument("--end", help="Exclusive UTC research end date (YYYY-MM-DD).")
    parser.add_argument("--timeframe", choices=("15m", "1h", "4h"), default="15m")
    args = parser.parse_args()
    database = _database_path()
    if args.check:
        print(json.dumps(eligibility(database, load_config()), indent=2))
        return
    if not args.start or not args.end:
        parser.error("--start and --end are required unless --check is used.")
    run_retrain(args.start, args.end, args.timeframe, database)


if __name__ == "__main__":
    main()
