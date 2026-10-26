from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd


def load_resolved_paper_feedback(
    features: pd.DataFrame,
    database_path: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Append resolved AI and labeled counterfactual feedback without altering the ledger."""
    if not database_path.is_file():
        return features.copy(), pd.DataFrame()

    connection_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(connection_uri, uri=True) as connection:
        trade_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(trades)")
        }
        risk_column = (
            "trade.risk_amount"
            if "risk_amount" in trade_columns
            else "trade.initial_risk_usd"
        )
        rows = connection.execute(
            f"""
            SELECT sample.created_at_ms, sample.features_json, sample.decision_json,
                   sample.outcome_label, sample.realized_net_r, sample.pnl_usd,
                   trade.side, {risk_column}, trade.exit_reason, trade.closed_at,
                   0 AS counterfactual
            FROM training_samples AS sample
            JOIN trades AS trade ON trade.decision_id = sample.decision_id
            WHERE sample.outcome_resolved = 1
              AND sample.outcome_label IS NOT NULL
              AND trade.status = 'closed'
              AND trade.source = 'ai'
            ORDER BY trade.closed_at, trade.rowid
            """
        ).fetchall()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counterfactual_rows = (
            connection.execute(
                """
            SELECT sample.created_at_ms, sample.features_json, sample.decision_json,
                   sample.outcome_label, sample.realized_net_r, sample.pnl_usd,
                   episode.side, 0.0, episode.exit_reason,
                   episode.created_at_ms + episode.bars_held * 900000,
                   1 AS counterfactual
            FROM training_samples AS sample
            JOIN memory_episodes AS episode
              ON episode.decision_id = sample.decision_id
            WHERE sample.outcome_resolved = 1
              AND sample.outcome_label IS NOT NULL
              AND episode.counterfactual = 1
              AND episode.outcome IN ('win', 'loss', 'timeout')
            ORDER BY episode.created_at_ms, episode.rowid
            """
            ).fetchall()
            if "memory_episodes" in table_names
            else []
        )
        rows.extend(counterfactual_rows)
        rows.sort(key=lambda row: (int(row[0]), int(row[9] or 0)))

    if not rows:
        return features.copy(), pd.DataFrame()

    numeric_columns = list(
        features.drop(columns=["closed_at"], errors="ignore")
        .select_dtypes(include=[np.number])
        .columns
    )
    feature_rows = []
    label_rows = []
    offset = len(features)
    for row_number, row in enumerate(rows):
        (
            created_at, feature_json, decision_json, label, net_r, pnl, side,
            risk, reason, closed_at, counterfactual,
        ) = row
        feature_values = json.loads(feature_json)
        decision = json.loads(decision_json)
        plan = decision.get("trade_plan", {})
        direction = 1 if side == "long" else -1
        feature_row = {
            column: feature_values.get(column, np.nan)
            for column in numeric_columns
        }
        feature_row["closed_at"] = pd.to_datetime(created_at, unit="ms", utc=True)
        feature_rows.append(feature_row)

        candidate_index = offset + row_number
        label_rows.append(
            {
                "candidate_index": candidate_index,
                "entry_index": candidate_index,
                "label_end_index": candidate_index,
                "direction": direction,
                "primary_signal": direction,
                "label": int(label),
                "realized_net_r": float(net_r) if net_r is not None else 0.0,
                "exit_reason": str(reason or "unknown"),
                "pnl_usd": float(pnl or 0.0),
                "initial_risk_usd": float(risk or 0.0),
                "breakeven_probability": float(
                    plan.get("breakeven_probability") or 0.0
                ),
                "timestamp": pd.to_datetime(created_at, unit="ms", utc=True),
                "label_end_timestamp": pd.to_datetime(
                    closed_at, unit="ms", utc=True
                ),
                "uniqueness_weight": 1.0,
                "counterfactual": bool(counterfactual),
            }
        )

    if any(
        not math.isfinite(float(value))
        for row in feature_rows
        for name, value in row.items()
        if name != "closed_at"
        if value is not None and not pd.isna(value)
    ):
        raise ValueError("Paper feedback contains non-finite feature values.")
    combined_features = pd.concat(
        [features, pd.DataFrame(feature_rows)], ignore_index=True
    )
    return combined_features, pd.DataFrame(label_rows)
