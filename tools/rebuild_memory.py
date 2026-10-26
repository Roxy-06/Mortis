from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path

import numpy as np

from engine.paper_trader import FEATURE_SCHEMA_VERSION


def _database_path() -> Path:
    return Path(
        os.getenv(
            "MORTIS_DATA_DIR",
            str(Path(__file__).resolve().parents[1] / "data"),
        )
    ) / "mortis.db"


def rebuild_memory(database: Path | None = None) -> dict[str, int]:
    database = database or _database_path()
    if not database.is_file():
        raise FileNotFoundError(f"Mortis database not found: {database}")
    rebuilt = 0
    skipped_schema = 0
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        episodes = conn.execute(
            """
            SELECT episode.id, episode.feature_schema_version,
                   episode.feature_vector_json, decision.features_json
            FROM memory_episodes AS episode
            JOIN decisions AS decision
              ON decision.decision_id = episode.decision_id
            """
        ).fetchall()
        for episode in episodes:
            if int(episode["feature_schema_version"]) != FEATURE_SCHEMA_VERSION:
                skipped_schema += 1
                continue
            stored = json.loads(episode["feature_vector_json"] or "{}")
            raw_features = json.loads(episode["features_json"] or "{}")
            decision_features = {
                str(name): float(value)
                for name, value in raw_features.items()
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            }
            if decision_features and stored != decision_features:
                conn.execute(
                    "UPDATE memory_episodes SET feature_vector_json = ? WHERE id = ?",
                    (
                        json.dumps(decision_features, sort_keys=True, allow_nan=False),
                        episode["id"],
                    ),
                )
                rebuilt += 1

        conn.execute(
            "DELETE FROM memory_feature_stats WHERE feature_schema_version = ?",
            (FEATURE_SCHEMA_VERSION,),
        )
        vectors = conn.execute(
            """
            SELECT feature_vector_json FROM memory_episodes
            WHERE counterfactual = 0
              AND feature_schema_version = ?
            """,
            (FEATURE_SCHEMA_VERSION,),
        ).fetchall()
        values: dict[str, list[float]] = {}
        for row in vectors:
            for name, value in json.loads(row["feature_vector_json"]).items():
                number = float(value)
                if math.isfinite(number):
                    values.setdefault(name, []).append(number)
        now = int(time.time() * 1000)
        for name, numbers in values.items():
            conn.execute(
                """
                INSERT INTO memory_feature_stats (
                    feature_schema_version, feature_name, mean, stddev,
                    sample_count, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    FEATURE_SCHEMA_VERSION,
                    name,
                    float(np.mean(numbers)),
                    float(np.std(numbers)),
                    len(numbers),
                    now,
                ),
            )
    return {
        "episodes_seen": len(episodes),
        "vectors_rebuilt": rebuilt,
        "schema_mismatches_skipped": skipped_schema,
        "features_standardized": len(values),
    }


def main() -> None:
    result = rebuild_memory()
    print(json.dumps(result, indent=2))
    if result["schema_mismatches_skipped"]:
        print(
            "Some episodes use another feature schema and were preserved unchanged; "
            "their vectors cannot be safely transformed without stored raw candles."
        )


if __name__ == "__main__":
    main()
