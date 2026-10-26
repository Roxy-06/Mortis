from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.preprocessing import StandardScaler

from engine.risk import load_config
from research.backtest import _load_candles, run_backtest
from research.features import (
    FEATURE_SCHEMA_VERSION,
    build_features,
    drop_correlated_features,
)
from research.feedback import load_resolved_paper_feedback
from research.labels import build_labels, purged_walk_forward_splits


@dataclass
class ModelBundle:
    family: str
    feature_names: list[str]
    imputer: SimpleImputer
    scaler: Optional[StandardScaler]
    estimator: Any

    def predict_probability(self, frame: pd.DataFrame) -> np.ndarray:
        values = self.imputer.transform(frame[self.feature_names])
        if self.scaler is not None:
            values = self.scaler.transform(values)
        return self.estimator.predict_proba(values)[:, 1]


@dataclass
class PlattCalibrator:
    estimator: LogisticRegression

    def predict(self, probabilities: Iterable[float]) -> np.ndarray:
        values = np.clip(np.asarray(list(probabilities), dtype=float), 1e-6, 1 - 1e-6)
        logits = np.log(values / (1 - values)).reshape(-1, 1)
        return self.estimator.predict_proba(logits)[:, 1]


def _matrix(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    feature_names: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    candidates = features.drop(columns=["closed_at"], errors="ignore")
    candidates = candidates.select_dtypes(include=[np.number])
    indices = labels["candidate_index"].astype(int).to_numpy()
    matrix = candidates.iloc[indices].reset_index(drop=True).copy()
    matrix["signal_direction"] = labels["direction"].to_numpy(dtype=float)
    if feature_names is None:
        feature_names = list(matrix.columns)
    missing = sorted(set(feature_names).difference(matrix.columns))
    if missing:
        raise ValueError(f"Model features are missing: {missing}")
    return matrix.loc[:, feature_names], feature_names


def _fit_model(
    family: str,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    weights: np.ndarray,
    feature_names: Optional[list[str]] = None,
    calibration_data: Optional[tuple[pd.DataFrame, pd.Series]] = None,
    seed: int = 42,
) -> ModelBundle:
    matrix, feature_names = _matrix(features, labels, feature_names)
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    values = imputer.fit_transform(matrix)
    scaler = None
    if family == "logistic":
        scaler = StandardScaler()
        values = scaler.fit_transform(values)
        estimator = LogisticRegression(
            C=0.1,
            max_iter=1000,
            random_state=seed,
            class_weight=None,
        )
        estimator.fit(values, labels["label"], sample_weight=weights)
    elif family == "lightgbm":
        try:
            from lightgbm import LGBMClassifier, early_stopping
        except ImportError as error:
            raise RuntimeError(
                "LightGBM is required for the requested model family; install requirements.txt."
            ) from error
        estimator = LGBMClassifier(
            objective="binary",
            max_depth=3,
            num_leaves=7,
            min_child_samples=30,
            reg_lambda=5.0,
            learning_rate=0.02,
            n_estimators=500,
            random_state=seed,
            verbosity=-1,
            deterministic=True,
            force_col_wise=True,
        )
        fit_options: Dict[str, Any] = {"sample_weight": weights}
        if calibration_data is not None:
            calibration_matrix, _ = _matrix(
                features, calibration_data[0], feature_names
            )
            calibration_values = imputer.transform(calibration_matrix)
            fit_options["eval_set"] = [(calibration_values, calibration_data[1])]
            fit_options["callbacks"] = [early_stopping(30, verbose=False)]
        estimator.fit(values, labels["label"], **fit_options)
    else:
        raise ValueError(f"Unsupported model family: {family}")
    return ModelBundle(family, feature_names, imputer, scaler, estimator)


def _fit_calibrator(
    probabilities: np.ndarray,
    labels: pd.Series,
    weights: np.ndarray,
) -> PlattCalibrator:
    if labels.nunique() < 2:
        raise ValueError("Calibration window must contain both outcome classes.")
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    estimator = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    estimator.fit(logits, labels, sample_weight=weights)
    return PlattCalibrator(estimator)


def _candidate_signals(
    validation: pd.DataFrame,
    probabilities: np.ndarray,
    margin: float,
) -> Dict[int, int]:
    selected = validation.copy()
    selected["probability"] = probabilities
    selected = selected.loc[
        (selected["direction"] == selected["primary_signal"])
        & (
            selected["probability"]
            > selected["breakeven_probability"] + margin
        )
    ]
    return {
        int(row.candidate_index): int(row.direction)
        for row in selected.itertuples()
    }


def _backtest_fold(
    candles: Dict[str, pd.DataFrame],
    timeframe: str,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    probabilities: np.ndarray,
    margin: float,
    config: Dict,
    funding: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    signals = _candidate_signals(labels, probabilities, margin)
    if not len(labels):
        return {"trade_count": 0, "net_expectancy_r": None, "max_drawdown": 0.0}
    first = int(labels["candidate_index"].min())
    last = int(labels["label_end_index"].max())
    closed = pd.to_datetime(features["closed_at"], utc=True)
    start = closed.iloc[first].isoformat()
    end = (closed.iloc[last] + pd.Timedelta(milliseconds=1)).isoformat()
    result = run_backtest(
        candles,
        decision_timeframe=timeframe,
        config=config,
        funding=funding,
        feature_frame=features,
        signals_override=signals,
        start=start,
        end=end,
    )
    return result["metrics"]


def walk_forward_evaluate(
    candles: Dict[str, pd.DataFrame],
    labels: pd.DataFrame,
    features: pd.DataFrame,
    decision_timeframe: str = "15m",
    config: Optional[Dict] = None,
    n_splits: int = 5,
    embargo_bars: int = 48,
    margins: Optional[list[float]] = None,
    seed: int = 42,
    funding: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    if config is None:
        config = load_config()
    if margins is None:
        margins = [round(value, 3) for value in np.arange(0.0, 0.101, 0.01)]
    ordered = labels.sort_values(["candidate_index", "direction"]).reset_index(drop=True)
    splits = purged_walk_forward_splits(ordered, n_splits, embargo_bars)
    if not splits:
        raise ValueError("No purged walk-forward folds have enough training data.")
    families = ("logistic", "lightgbm")
    evaluations: Dict[str, Any] = {}
    for family in families:
        fold_results = []
        margin_results = {margin: [] for margin in margins}
        for fold_number, (training_indices, validation_indices) in enumerate(splits, 1):
            training = ordered.iloc[training_indices].reset_index(drop=True)
            validation = ordered.iloc[validation_indices].reset_index(drop=True)
            candidate_values = np.sort(training["candidate_index"].unique())
            if len(candidate_values) < 5:
                continue
            calibration_start = int(candidate_values[max(1, int(len(candidate_values) * 0.8))])
            calibration = training.loc[
                training["candidate_index"] >= calibration_start
            ].reset_index(drop=True)
            core = training.loc[
                training["label_end_index"] < calibration_start - embargo_bars
            ].reset_index(drop=True)
            if core["label"].nunique() < 2 or calibration["label"].nunique() < 2:
                continue

            core_matrix, candidate_features = _matrix(features, core)
            kept = drop_correlated_features(core_matrix)
            if "signal_direction" not in kept:
                kept.append("signal_direction")
            core_weights = core["uniqueness_weight"].to_numpy(dtype=float)
            calibration_matrix, _ = _matrix(features, calibration, kept)
            bundle = _fit_model(
                family,
                features,
                core,
                core_weights,
                kept,
                (calibration, calibration["label"]),
                seed + fold_number,
            )
            raw_calibration = bundle.predict_probability(calibration_matrix)
            calibrator = _fit_calibrator(
                raw_calibration,
                calibration["label"],
                calibration["uniqueness_weight"].to_numpy(dtype=float),
            )
            validation_matrix, _ = _matrix(features, validation, kept)
            raw_probabilities = bundle.predict_probability(validation_matrix)
            probabilities = calibrator.predict(raw_probabilities)
            brier = float(brier_score_loss(validation["label"], probabilities))
            fold_results.append(
                {
                    "fold": fold_number,
                    "train_samples": len(core),
                    "calibration_samples": len(calibration),
                    "validation_samples": len(validation),
                    "validation_class_balance": {
                        str(key): int(value)
                        for key, value in validation["label"].value_counts().items()
                    },
                    "brier_score": brier,
                    "mean_predicted_probability": float(np.mean(probabilities)),
                    "observed_win_rate": float(validation["label"].mean()),
                }
            )
            for margin in margins:
                metrics = _backtest_fold(
                    candles,
                    decision_timeframe,
                    features,
                    validation,
                    probabilities,
                    margin,
                    config,
                    funding,
                )
                margin_results[margin].append(metrics)
        margin_summary = {}
        for margin, fold_metrics in margin_results.items():
            valid = [
                metric["net_expectancy_r"]
                for metric in fold_metrics
                if metric["net_expectancy_r"] is not None
            ]
            margin_summary[str(margin)] = {
                "mean_net_expectancy_r": float(np.mean(valid)) if valid else None,
                "profitable_folds": sum(value > 0 for value in valid),
                "folds_with_trades": len(valid),
            }
        ranked = [
            (margin, values["mean_net_expectancy_r"])
            for margin, values in margin_summary.items()
            if values["mean_net_expectancy_r"] is not None
        ]
        selected_margin = (
            max(ranked, key=lambda item: (item[1], -float(item[0])))[0]
            if ranked else None
        )
        evaluations[family] = {
            "folds": fold_results,
            "margin_validation": margin_summary,
            "selected_margin": float(selected_margin) if selected_margin is not None else None,
            "mean_brier_score": (
                float(np.mean([fold["brier_score"] for fold in fold_results]))
                if fold_results else None
            ),
        }
    return {
        "decision_timeframe": decision_timeframe,
        "fold_count": len(splits),
        "embargo_bars": embargo_bars,
        "candidate_labels": len(ordered),
        "class_balance": {
            str(key): int(value) for key, value in ordered["label"].value_counts().items()
        },
        "models": evaluations,
    }


def _git_hash() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def train_candidate(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    family: str,
    training_end: str,
    output_root: Path = Path("models"),
    config: Optional[Dict] = None,
    seed: int = 42,
    validation_metrics: Optional[Dict[str, Any]] = None,
    decision_timeframe: str = "15m",
    embargo_bars: int = 48,
    feedback_sample_count: int = 0,
    counterfactual_feedback_count: int = 0,
    strategy: str = "fallback",
) -> Path:
    if family not in ("logistic", "lightgbm"):
        raise ValueError("Candidate family must be logistic or lightgbm.")
    if config is None:
        config = load_config()
    end_time = pd.Timestamp(training_end, tz="UTC")
    training = labels.loc[
        (pd.to_datetime(labels["timestamp"], utc=True) < end_time)
        & (pd.to_datetime(labels["label_end_timestamp"], utc=True) < end_time)
    ].copy()
    if training.empty or training["label"].nunique() < 2:
        raise ValueError("Training range needs samples from both outcome classes.")
    unique_candidates = np.sort(training["candidate_index"].unique())
    calibration_start = int(unique_candidates[max(1, int(len(unique_candidates) * 0.8))])
    calibration = training.loc[
        training["candidate_index"] >= calibration_start
    ].reset_index(drop=True)
    core = training.loc[
        training["label_end_index"] < calibration_start - embargo_bars
    ].reset_index(drop=True)
    if core["label"].nunique() < 2 or calibration["label"].nunique() < 2:
        raise ValueError("Training and calibration windows must each contain both classes.")
    core_matrix, _ = _matrix(features, core)
    feature_names = drop_correlated_features(core_matrix)
    if "signal_direction" not in feature_names:
        feature_names.append("signal_direction")
    bundle = _fit_model(
        family,
        features,
        core,
        core["uniqueness_weight"].to_numpy(dtype=float),
        feature_names,
        (calibration, calibration["label"]),
        seed,
    )
    calibration_matrix, _ = _matrix(features, calibration, feature_names)
    calibrator = _fit_calibrator(
        bundle.predict_probability(calibration_matrix),
        calibration["label"],
        calibration["uniqueness_weight"].to_numpy(dtype=float),
    )
    version = f"candidate-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{family}"
    output = output_root / version
    output_root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    joblib.dump(bundle, output / "model.joblib")
    joblib.dump(calibrator, output / "calibrator.joblib")
    (output / "features.json").write_text(
        json.dumps(feature_names, indent=2) + "\n", encoding="utf-8"
    )
    metadata = {
        "version": version,
        "family": family,
        "promoted": False,
        "promotion_gate_passed": False,
        "training_range": {
            "start": pd.to_datetime(training["timestamp"], utc=True).min().isoformat(),
            "end": end_time.isoformat(),
        },
        "git_hash": _git_hash(),
        "feature_list": feature_names,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "class_balance": {
            str(key): int(value)
            for key, value in training["label"].value_counts().items()
        },
        "sample_count": len(training),
        "resolved_paper_feedback_count": feedback_sample_count,
        "counterfactual_feedback_count": counterfactual_feedback_count,
        "decision_timeframe": decision_timeframe,
        "strategy": strategy,
        "margin_over_breakeven": (
            validation_metrics["models"][family]["selected_margin"]
            if validation_metrics
            else config.get("model", {}).get("margin_over_breakeven", 0.03)
        ),
        "validation_metrics": validation_metrics or {},
        "seed": seed,
        "python_version": __import__("platform").python_version(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "scikit_learn_version": __import__("sklearn").__version__,
        "lightgbm_version": (
            __import__("lightgbm").__version__ if family == "lightgbm" else None
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate Mortis model candidates.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True, help="Training end; exclude protected holdout.")
    parser.add_argument("--data-dir", type=Path, default=Path("research_data"))
    parser.add_argument("--timeframe", choices=("15m", "1h", "4h"), default="15m")
    parser.add_argument("--strategy", choices=("fallback", "trend", "breakout"), default="fallback")
    parser.add_argument("--embargo-bars", type=int, default=48)
    parser.add_argument("--output-root", type=Path, default=Path("models"))
    args = parser.parse_args()
    config = load_config()
    candles = _load_candles(args.data_dir, args.start, args.end)
    funding_path = args.data_dir / "BTCUSDT_funding_rates.parquet"
    funding = pd.read_parquet(funding_path) if funding_path.exists() else None
    if funding is None and config.get("backtest", {}).get("include_funding", True):
        raise FileNotFoundError("Funding history is required; run research.data_loader first.")
    features = build_features(candles, decision_timeframe=args.timeframe)
    labels = build_labels(
        candles,
        decision_timeframe=args.timeframe,
        strategy=args.strategy,
        config=config,
        funding=funding,
        features=features,
    )
    training_start = pd.Timestamp(args.start, tz="UTC")
    labels = labels.loc[
        pd.to_datetime(labels["timestamp"], utc=True) >= training_start
    ].reset_index(drop=True)
    if labels.empty:
        raise SystemExit("No primary-signal labels found in the requested training range.")
    validation = walk_forward_evaluate(
        candles,
        labels,
        features,
        decision_timeframe=args.timeframe,
        config=config,
        embargo_bars=args.embargo_bars,
        funding=funding,
    )
    account_data_dir = Path(
        os.getenv(
            "MORTIS_DATA_DIR",
            str(Path(__file__).resolve().parents[1] / "data"),
        )
    )
    candidate_features, feedback_labels = load_resolved_paper_feedback(
        features, account_data_dir / "mortis.db"
    )
    candidate_labels = pd.concat(
        [labels, feedback_labels], ignore_index=True
    )
    outputs = {}
    for family in ("logistic", "lightgbm"):
        outputs[family] = str(
            train_candidate(
                candidate_labels,
                candidate_features,
                family,
                args.end,
                args.output_root,
                config,
                validation_metrics=validation,
                decision_timeframe=args.timeframe,
                embargo_bars=args.embargo_bars,
                feedback_sample_count=len(feedback_labels),
                counterfactual_feedback_count=(
                    int(feedback_labels["counterfactual"].sum())
                    if "counterfactual" in feedback_labels
                    else 0
                ),
                strategy=args.strategy,
            )
        )
    report_dir = Path("research/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "training_range": {"start": args.start, "end": args.end},
        "labels": {
            "count": len(labels),
            "class_balance": validation["class_balance"],
            "folds": validation["fold_count"],
            "resolved_paper_feedback_count": len(feedback_labels),
            "counterfactual_feedback_count": (
                int(feedback_labels["counterfactual"].sum())
                if "counterfactual" in feedback_labels
                else 0
            ),
        },
        "validation": validation,
        "candidates": outputs,
        "promotion": "NOT PROMOTED: final holdout and promotion gates have not been evaluated.",
    }
    report_path = report_dir / "model-validation.json"
    report_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(report_path)


if __name__ == "__main__":
    main()
