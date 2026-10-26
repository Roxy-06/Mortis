from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.risk import load_config
from research.metrics import calculate_metrics


def evaluate_forward_trial(
    database_path: Path,
    metadata_path: Path,
    report_path: Path,
    minimum_duration_days: int = 56,
    minimum_closed_trades: int = 100,
) -> Dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("lifecycle") != "paper_trial" or not metadata.get(
        "paper_trial_started_at_utc"
    ):
        raise ValueError("Forward validation requires an activated paper-trial model.")
    if minimum_duration_days < 1 or minimum_closed_trades < 1:
        raise ValueError("Forward validation thresholds must be positive.")
    if not database_path.is_file():
        raise FileNotFoundError(f"Paper-account database not found: {database_path}")

    started_at = pd.Timestamp(metadata["paper_trial_started_at_utc"])
    started_at = (
        started_at.tz_localize("UTC")
        if started_at.tzinfo is None
        else started_at.tz_convert("UTC")
    )
    with sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            """
            SELECT sample.decision_id, sample.created_at_ms, sample.outcome_label,
                   sample.realized_net_r, sample.pnl_usd, sample.decision_json,
                   trade.opened_at, trade.closed_at, trade.exit_reason, trade.side,
                   trade.initial_risk_usd
            FROM training_samples AS sample
            JOIN trades AS trade ON trade.decision_id = sample.decision_id
            WHERE sample.outcome_resolved = 1
              AND trade.status = 'closed'
              AND trade.source = 'ai'
            ORDER BY trade.closed_at, trade.rowid
            """
        ).fetchall()

    samples = []
    for row in rows:
        decision = json.loads(row[5])
        sample_time = pd.to_datetime(row[1], unit="ms", utc=True)
        if (
            decision.get("model_version") == metadata["version"]
            and sample_time >= started_at
        ):
            samples.append(row)
    if len({row[0] for row in samples}) != len(samples):
        raise ValueError("Forward paper-trial evidence contains duplicate decisions.")

    r_values = np.asarray(
        [float(row[3]) for row in samples if row[3] is not None],
        dtype=float,
    )
    pnl_values = np.asarray(
        [float(row[4] or 0.0) for row in samples],
        dtype=float,
    )
    end_at = (
        pd.to_datetime(max(row[7] for row in samples), unit="ms", utc=True)
        if samples else None
    )
    duration_days = (
        (end_at - started_at).total_seconds() / 86400
        if end_at is not None else 0.0
    )
    starting_equity = float(load_config().get("starting_equity_usd", 10000))
    equity = starting_equity
    curve = [{"timestamp_ms": int(started_at.timestamp() * 1000), "equity": equity}]
    trades = []
    for row, pnl in zip(samples, pnl_values):
        equity += float(pnl)
        curve.append({"timestamp_ms": int(row[7]), "equity": equity})
        trades.append(
            {
                "pnl_usd": float(pnl),
                "initial_risk_usd": float(row[10] or 0.0),
                "duration_seconds": max(0, (int(row[7]) - int(row[6])) // 1000),
            }
        )
    metrics = calculate_metrics(
        trades,
        curve,
        starting_equity,
        seed=42,
    )
    gates = {
        "minimum_duration_met": duration_days >= minimum_duration_days,
        "minimum_closed_trades_met": len(samples) >= minimum_closed_trades,
        "positive_net_expectancy": (
            metrics["net_expectancy_r"] is not None
            and metrics["net_expectancy_r"] > 0
        ),
        "positive_expectancy_confidence_interval": (
            metrics["expectancy_r_ci_95"][0] is not None
            and metrics["expectancy_r_ci_95"][0] > 0
        ),
    }
    report = {
        "model_version": metadata["version"],
        "lifecycle": "paper_trial",
        "trial_started_at_utc": started_at.isoformat(),
        "last_closed_trade_at_utc": end_at.isoformat() if end_at is not None else None,
        "observed_duration_days": duration_days,
        "resolved_ai_paper_trades": len(samples),
        "win_rate": (
            float(np.mean([int(row[2] or 0) for row in samples]))
            if samples else None
        ),
        "net_expectancy_r": metrics["net_expectancy_r"],
        "expectancy_r_ci_95": metrics["expectancy_r_ci_95"],
        "max_drawdown": metrics["max_drawdown"],
        "minimums": {
            "duration_days": minimum_duration_days,
            "closed_trades": minimum_closed_trades,
        },
        "gates": gates,
        "forward_validation_passed": bool(gates) and all(gates.values()),
        "real_money_authorization": False,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report prospective paper-trial evidence; never enables real trading."
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/mortis.db"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    metadata_path = args.candidate / "metadata.json"
    version = json.loads(metadata_path.read_text(encoding="utf-8"))["version"]
    report_path = args.report or Path(
        "research/reports"
    ) / f"forward-validation-{version}.json"
    report = evaluate_forward_trial(args.database, metadata_path, report_path)
    print(
        f"{report_path}: "
        f"{'PASS' if report['forward_validation_passed'] else 'NOT YET PASSED'}"
    )


if __name__ == "__main__":
    main()
