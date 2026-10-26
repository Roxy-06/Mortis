import json

import numpy as np
import pandas as pd
import joblib

from research.train import ModelBundle, PlattCalibrator, train_candidate


def test_candidate_artifact_is_loadable_and_never_promoted_without_gate(tmp_path):
    timestamps = pd.date_range("2023-01-01", periods=100, freq="h", tz="UTC")
    labels = pd.DataFrame(
        {
            "candidate_index": np.arange(100),
            "entry_index": np.arange(100) + 1,
            "label_end_index": np.arange(100) + 2,
            "direction": np.where(np.arange(100) % 2, 1, -1),
            "label": np.arange(100) % 2,
            "timestamp": timestamps,
            "label_end_timestamp": timestamps + pd.Timedelta(hours=2),
            "uniqueness_weight": np.ones(100),
        }
    )
    features = pd.DataFrame(
        {
            "closed_at": timestamps,
            "trend": np.linspace(-1, 1, len(timestamps)),
            "momentum": np.sin(np.arange(len(timestamps))),
        }
    )

    artifact = train_candidate(
        labels,
        features,
        "logistic",
        training_end=timestamps[-1].isoformat(),
        output_root=tmp_path,
        embargo_bars=1,
    )

    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    model = joblib.load(artifact / "model.joblib")
    calibrator = joblib.load(artifact / "calibrator.joblib")
    assert isinstance(model, ModelBundle)
    assert isinstance(calibrator, PlattCalibrator)
    assert metadata["promoted"] is False
    assert metadata["promotion_gate_passed"] is False
    prediction_features = features.iloc[:1].assign(signal_direction=1)
    assert len(model.predict_probability(prediction_features)) == 1
