import json

import numpy as np
import pandas as pd
import pytest

import research.holdout as holdout_module
import agents.model_registry as model_registry
from research.promotion import activate_paper_trial
from research.train import train_candidate


def _test_candidate(tmp_path):
    timestamps = pd.date_range("2024-01-01", periods=122, freq="h", tz="UTC")
    feature_frame = pd.DataFrame(
        {
            "closed_at": timestamps,
            "trend": np.linspace(-1, 1, len(timestamps)),
            "momentum": np.sin(np.arange(len(timestamps))),
        }
    )
    candidate_indices = np.arange(100)
    training = pd.DataFrame(
        {
            "candidate_index": candidate_indices,
            "entry_index": candidate_indices + 1,
            "label_end_index": candidate_indices + 2,
            "direction": np.where(candidate_indices % 2, 1, -1),
            "label": candidate_indices % 2,
            "timestamp": timestamps[candidate_indices],
            "label_end_timestamp": timestamps[candidate_indices + 1],
            "uniqueness_weight": np.ones(len(candidate_indices)),
        }
    )
    artifact = train_candidate(
        training,
        feature_frame,
        "logistic",
        timestamps[100].isoformat(),
        tmp_path,
        embargo_bars=1,
    )
    return artifact, feature_frame, timestamps


def _holdout_labels(timestamps):
    indices = np.arange(100, 120)
    directions = np.where(indices % 2, 1, -1)
    return pd.DataFrame(
        {
            "candidate_index": indices,
            "label_end_index": indices,
            "direction": directions,
            "primary_signal": directions,
            "label": indices % 2,
            "breakeven_probability": np.full(len(indices), 0.5),
            "timestamp": timestamps[indices],
            "label_end_timestamp": timestamps[indices] + pd.Timedelta(minutes=5),
        }
    )


def test_final_holdout_is_reported_once_without_automatic_promotion(tmp_path, monkeypatch):
    artifact, features, timestamps = _test_candidate(tmp_path / "models")
    candles = pd.DataFrame(
        {
            "open_time": (timestamps.astype("int64") // 1_000_000).to_numpy(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 10.0,
        }
    )
    candle_map = {"15m": candles}

    def stub_backtest(*args, cost_multiplier=1, strategy="fallback", **kwargs):
        expectancy = 0.05 if cost_multiplier == 2 else 0.1
        if kwargs.get("signals_override") is None:
            expectancy = -0.1
        return {
            "metrics": {
                "trade_count": 2,
                "net_expectancy_r": expectancy,
                "expectancy_r_ci_95": [-0.2, 0.3],
                "max_drawdown": 0.05,
            }
        }

    monkeypatch.setattr(holdout_module, "run_backtest", stub_backtest)
    report_path = tmp_path / "reports" / "final-holdout.json"
    marker_path = report_path.parent / "final-holdout-consumed.json"
    output = holdout_module.evaluate_final_holdout_once(
        [artifact],
        candle_map,
        features,
        _holdout_labels(timestamps),
        timestamps[100].isoformat(),
        timestamps[121].isoformat(),
        report_path,
        marker_path=marker_path,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["automatic_promotion"] is False
    assert report["evaluations"][0]["all_historical_gates_passed"] is True
    assert report["evaluations"][0]["holdout_candles_sha256"]["15m"]
    assert json.loads(
        marker_path.read_text(
            encoding="utf-8"
        )
    )["candidate_versions"] == [json.loads((artifact / "metadata.json").read_text())["version"]]

    with pytest.raises(ValueError, match="approval"):
        activate_paper_trial(artifact, report_path)
    report_contents = report_path.read_bytes()
    report_path.write_bytes(report_contents + b" ")
    with pytest.raises(ValueError, match="single-use"):
        activate_paper_trial(artifact, report_path, approved=True)
    report_path.write_bytes(report_contents)
    metadata = activate_paper_trial(artifact, report_path, approved=True)
    monkeypatch.setattr(model_registry, "MODEL_ROOT", artifact.parent)
    active_model = model_registry.load_active_model(
        {"model": {"active_version": metadata["version"]}}
    )
    assert active_model.version == metadata["version"]
    assert metadata["lifecycle"] == "paper_trial"
    assert metadata["forward_validation_required"] == {
        "minimum_duration_days": 56,
        "minimum_closed_trades": 100,
    }

    with pytest.raises(FileExistsError, match="already evaluated"):
        holdout_module.evaluate_final_holdout_once(
            [artifact],
            candle_map,
            features,
            _holdout_labels(timestamps),
            timestamps[100].isoformat(),
            timestamps[121].isoformat(),
            report_path,
            marker_path=marker_path,
        )


def test_candidate_holdout_rejects_dates_overlapping_training(tmp_path):
    artifact, features, timestamps = _test_candidate(tmp_path / "models")

    with pytest.raises(ValueError, match="after training"):
        holdout_module.evaluate_candidate(
            artifact,
            {"15m": pd.DataFrame()},
            features,
            _holdout_labels(timestamps),
            timestamps[99].isoformat(),
            timestamps[121].isoformat(),
        )
