from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from engine.risk import load_config
from research.backtest import _load_candles, run_backtest
from research.features import build_features
from research.labels import build_labels
from research.train import ModelBundle, PlattCalibrator, _candidate_signals, _matrix

HOLDOUT_MARKER = (
    Path(__file__).resolve().parent / "reports" / "final-holdout-consumed.json"
)


def _frame_sha256(frame: pd.DataFrame) -> str:
    values = pd.util.hash_pandas_object(frame.reset_index(drop=True), index=False)
    return hashlib.sha256(values.to_numpy().tobytes()).hexdigest()


def evaluate_candidate(
    artifact_dir: Path,
    candles: Dict[str, pd.DataFrame],
    features: pd.DataFrame,
    labels: pd.DataFrame,
    holdout_start: str,
    holdout_end: str,
    config: Optional[Dict] = None,
    funding: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Evaluate one frozen candidate on a time range strictly after its training window."""
    if config is None:
        config = load_config()
    metadata_path = artifact_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("promoted") or metadata.get("promotion_gate_passed"):
        raise ValueError("Holdout evaluation only accepts an unpromoted candidate.")

    start = pd.Timestamp(holdout_start, tz="UTC")
    end = pd.Timestamp(holdout_end, tz="UTC")
    training_end = pd.Timestamp(metadata["training_range"]["end"], tz="UTC")
    if end <= start or start < training_end:
        raise ValueError("Final holdout must be a non-empty interval after training.")
    if metadata.get("strategy") != "fallback":
        raise ValueError("Only the production deterministic strategy can be evaluated.")
    timeframe = metadata["decision_timeframe"]
    if timeframe not in candles:
        raise ValueError(f"Holdout candle data is missing {timeframe}.")
    required = {
        "candidate_index",
        "label_end_index",
        "direction",
        "primary_signal",
        "label",
        "breakeven_probability",
        "timestamp",
        "label_end_timestamp",
    }
    if not required.issubset(labels.columns):
        raise ValueError(f"Holdout labels are missing {sorted(required - set(labels.columns))}.")
    label_times = pd.to_datetime(labels["timestamp"], utc=True)
    label_end_times = pd.to_datetime(labels["label_end_timestamp"], utc=True)
    holdout = labels.loc[
        (label_times >= start)
        & (label_times < end)
        & (label_end_times < end)
    ].sort_values(["candidate_index", "direction"]).reset_index(drop=True)
    if holdout.empty:
        raise ValueError("The requested holdout has no fully resolved labeled outcomes.")

    model = joblib.load(artifact_dir / "model.joblib")
    calibrator = joblib.load(artifact_dir / "calibrator.joblib")
    if not isinstance(model, ModelBundle) or not isinstance(calibrator, PlattCalibrator):
        raise ValueError("Candidate artifact has an unsupported model format.")
    if model.family != metadata.get("family"):
        raise ValueError("Candidate model family does not match its metadata.")
    if model.feature_names != metadata.get("feature_list"):
        raise ValueError("Candidate model features do not match its metadata.")
    probabilities = calibrator.predict(model.predict_probability(_matrix(features, holdout)[0]))
    brier = float(brier_score_loss(holdout["label"], probabilities))

    training_balance = metadata.get("class_balance", {})
    total_training = sum(int(value) for value in training_balance.values())
    positive_rate = (
        int(training_balance.get("1", 0)) / total_training
        if total_training else 0.5
    )
    constant_brier = float(
        brier_score_loss(
            holdout["label"],
            np.full(len(holdout), positive_rate, dtype=float),
        )
    )
    margin = metadata.get("margin_over_breakeven")
    if not isinstance(margin, (int, float)) or margin < 0:
        raise ValueError("Candidate has no valid walk-forward-selected margin.")
    signals = _candidate_signals(holdout, probabilities, float(margin))
    first = int(holdout["candidate_index"].min())
    last = int(holdout["label_end_index"].max())
    close_times = pd.to_datetime(features["closed_at"], utc=True)
    actual_start = max(start, close_times.iloc[first])
    actual_end = min(end, close_times.iloc[last] + pd.Timedelta(milliseconds=1))
    if actual_end <= actual_start:
        raise ValueError("Holdout timestamps do not overlap the requested interval.")

    candidate_run = run_backtest(
        candles,
        decision_timeframe=timeframe,
        config=config,
        funding=funding,
        feature_frame=features,
        signals_override=signals,
        start=actual_start.isoformat(),
        end=actual_end.isoformat(),
    )
    costly_run = run_backtest(
        candles,
        decision_timeframe=timeframe,
        config=config,
        funding=funding,
        feature_frame=features,
        signals_override=signals,
        cost_multiplier=2,
        start=actual_start.isoformat(),
        end=actual_end.isoformat(),
    )
    baseline = run_backtest(
        candles,
        decision_timeframe=timeframe,
        strategy="fallback",
        config=config,
        funding=funding,
        feature_frame=features,
        start=actual_start.isoformat(),
        end=actual_end.isoformat(),
    )
    candidate_expectancy = candidate_run["metrics"]["net_expectancy_r"]
    costly_expectancy = costly_run["metrics"]["net_expectancy_r"]
    baseline_expectancy = baseline["metrics"]["net_expectancy_r"]
    gates = {
        "beats_constant_brier": brier < constant_brier,
        "positive_net_expectancy": (
            candidate_expectancy is not None and candidate_expectancy > 0
        ),
        "positive_expectancy_at_2x_costs": (
            costly_expectancy is not None and costly_expectancy > 0
        ),
        "beats_deterministic_baseline": (
            candidate_expectancy is not None
            and baseline_expectancy is not None
            and candidate_expectancy > baseline_expectancy
        ),
        "has_trades": candidate_run["metrics"]["trade_count"] > 0,
    }
    data_digests = {}
    for candle_timeframe, candle_frame in candles.items():
        times = pd.to_datetime(candle_frame["open_time"], unit="ms", utc=True)
        selected = candle_frame.loc[(times >= start) & (times < end)]
        columns = [
            column
            for column in ("open_time", "open", "high", "low", "close", "volume")
            if column in selected
        ]
        data_digests[candle_timeframe] = _frame_sha256(selected[columns])
    return {
        "candidate_version": metadata["version"],
        "family": model.family,
        "holdout_range_utc": {
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "evaluated_start": actual_start.isoformat(),
            "evaluated_end": actual_end.isoformat(),
        },
        "training_end_utc": training_end.isoformat(),
        "label_count": len(holdout),
        "brier_score": brier,
        "constant_baseline_brier_score": constant_brier,
        "net_expectancy_r": candidate_expectancy,
        "expectancy_r_ci_95": candidate_run["metrics"]["expectancy_r_ci_95"],
        "trade_count": candidate_run["metrics"]["trade_count"],
        "max_drawdown": candidate_run["metrics"]["max_drawdown"],
        "expectancy_at_2x_costs_r": costly_expectancy,
        "deterministic_baseline_expectancy_r": baseline_expectancy,
        "gates": gates,
        "all_historical_gates_passed": bool(gates) and all(gates.values()),
        "holdout_candles_sha256": data_digests,
    }


def evaluate_final_holdout_once(
    artifact_dirs: list[Path],
    candles: Dict[str, pd.DataFrame],
    features: pd.DataFrame,
    labels: pd.DataFrame,
    holdout_start: str,
    holdout_end: str,
    report_path: Path,
    config: Optional[Dict] = None,
    funding: Optional[pd.DataFrame] = None,
    marker_path: Optional[Path] = None,
) -> Path:
    if not artifact_dirs:
        raise ValueError("At least one candidate artifact is required.")
    marker = marker_path or HOLDOUT_MARKER
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists() or report_path.exists():
        raise FileExistsError(
            f"Final holdout was already evaluated or reserved: {marker}"
        )
    evaluations = [
        evaluate_candidate(
            artifact,
            candles,
            features,
            labels,
            holdout_start,
            holdout_end,
            config,
            funding,
        )
        for artifact in artifact_dirs
    ]
    reservation = {
        "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start": holdout_start,
        "holdout_end": holdout_end,
        "candidate_versions": [result["candidate_version"] for result in evaluations],
        "consumption_marker": str(marker.resolve()),
        "promotion": "Historical evidence only; explicit review and prospective paper validation remain required.",
    }
    report = {
        **reservation,
        "evaluations": evaluations,
        "automatic_promotion": False,
    }
    report_contents = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    reservation["report_sha256"] = hashlib.sha256(
        report_contents
    ).hexdigest()
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as marker_file:
        marker_file.write(json.dumps(reservation, indent=2) + "\n")
    with report_path.open("xb") as report_file:
        report_file.write(report_contents)
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen candidates once on a protected final holdout."
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("research_data"))
    parser.add_argument(
        "--report", type=Path, default=Path("research/reports/final-holdout.json")
    )
    args = parser.parse_args()
    config = load_config()
    timeframes = {
        json.loads((candidate / "metadata.json").read_text(encoding="utf-8")).get(
            "decision_timeframe"
        )
        for candidate in args.candidate
    }
    if len(timeframes) != 1 or None in timeframes:
        raise ValueError("All candidates in one holdout run must share a decision timeframe.")
    timeframe = timeframes.pop()
    candles = _load_candles(args.data_dir, args.start, args.end)
    funding_path = args.data_dir / "BTCUSDT_funding_rates.parquet"
    funding = pd.read_parquet(funding_path) if funding_path.exists() else None
    if funding is None and config.get("backtest", {}).get("include_funding", True):
        raise FileNotFoundError("Funding history is required; run research.data_loader first.")
    features = build_features(candles, decision_timeframe=timeframe)
    labels = build_labels(
        candles,
        decision_timeframe=timeframe,
        config=config,
        funding=funding,
        features=features,
    )
    output = evaluate_final_holdout_once(
        args.candidate,
        candles,
        features,
        labels,
        args.start,
        args.end,
        args.report,
        config,
        funding,
    )
    print(output)


if __name__ == "__main__":
    main()
