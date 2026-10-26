import json

import pytest

import agents.model_registry as model_registry


def test_model_registry_uses_fallback_when_no_version_is_active():
    assert model_registry.load_active_model({"model": {"active_version": None}}) is None


def test_model_registry_refuses_candidate_artifacts(tmp_path, monkeypatch):
    version = "candidate-logistic"
    artifact = tmp_path / version
    artifact.mkdir()
    (artifact / "metadata.json").write_text(
        json.dumps(
            {
                "version": version,
                "promoted": False,
                "promotion_gate_passed": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(model_registry, "MODEL_ROOT", tmp_path)

    with pytest.raises(ValueError, match="paper trial"):
        model_registry.load_active_model({"model": {"active_version": version}})


def test_model_registry_rejects_path_traversal():
    with pytest.raises(ValueError, match="version is invalid"):
        model_registry.load_active_model({"model": {"active_version": "..\\secret"}})
