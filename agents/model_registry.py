from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
import pandas as pd

from research.train import ModelBundle, PlattCalibrator
from research.features import FEATURE_SCHEMA_VERSION

MODEL_ROOT = Path(__file__).resolve().parents[1] / "models"


@dataclass
class ActiveModel:
    version: str
    decision_timeframe: str
    margin_over_breakeven: float
    model: ModelBundle
    calibrator: PlattCalibrator

    def probability(self, features: Dict[str, Any], direction: int) -> float:
        row = {
            name: features.get(name, float("nan"))
            for name in self.model.feature_names
            if name != "signal_direction"
        }
        model_input = pd.DataFrame([row]).assign(signal_direction=direction)
        raw_probability = self.model.predict_probability(model_input)
        probability = float(self.calibrator.predict(raw_probability)[0])
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Promoted model returned an invalid calibrated probability.")
        return probability


def load_active_model(config: Dict[str, Any]) -> Optional[ActiveModel]:
    version = config.get("model", {}).get("active_version")
    if version is None:
        return None
    if not isinstance(version, str) or not version or Path(version).name != version:
        raise ValueError("Configured active model version is invalid.")

    artifact = MODEL_ROOT / version
    metadata_path = artifact / "metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Active model metadata is missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("version") != version
        or metadata.get("promoted") is not True
        or metadata.get("promotion_gate_passed") is not True
        or metadata.get("lifecycle") != "paper_trial"
        or metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
    ):
        raise ValueError(
            "Configured model has not passed review for this feature schema and paper trial."
        )
    decision_timeframe = metadata.get("decision_timeframe")
    if not isinstance(decision_timeframe, str):
        raise ValueError("Active model metadata has no decision timeframe.")

    model = joblib.load(artifact / "model.joblib")
    calibrator = joblib.load(artifact / "calibrator.joblib")
    if not isinstance(model, ModelBundle) or not isinstance(calibrator, PlattCalibrator):
        raise ValueError("Active model artifact contains an unsupported model format.")
    if model.family != metadata.get("family"):
        raise ValueError("Active model family does not match its metadata.")
    if model.feature_names != metadata.get("feature_list"):
        raise ValueError("Active model features do not match its metadata.")
    if "signal_direction" not in model.feature_names:
        raise ValueError("Active model is missing its direction input.")
    margin = metadata.get("margin_over_breakeven")
    if not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 0:
        raise ValueError("Active model has an invalid breakeven margin.")

    return ActiveModel(
        version=version,
        decision_timeframe=decision_timeframe,
        margin_over_breakeven=float(margin),
        model=model,
        calibrator=calibrator,
    )
