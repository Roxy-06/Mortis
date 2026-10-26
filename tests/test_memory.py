import pytest

from engine.memory import memory_gate, retrieve_similar


def episode(identifier, outcome, created_at, value=0.0, schema=1, counterfactual=0):
    import json

    return {
        "id": identifier,
        "decision_id": identifier,
        "created_at_ms": created_at,
        "side": "long",
        "feature_schema_version": schema,
        "feature_vector_json": json.dumps({"signal": value}),
        "outcome": outcome,
        "r_multiple": 1.0 if outcome == "win" else -1.0,
        "exit_reason": "test",
        "lesson_text": None,
        "counterfactual": counterfactual,
    }


def test_retrieval_excludes_self_near_time_other_side_and_schema():
    now = 2_000_000_000
    episodes = [
        episode("self", "win", now - 8 * 60 * 60 * 1000),
        episode("near", "win", now - 60 * 60 * 1000),
        episode("wrong-side", "win", now - 8 * 60 * 60 * 1000),
        episode("old-schema", "win", now - 8 * 60 * 60 * 1000, schema=2),
        episode("counterfactual", "win", now - 8 * 60 * 60 * 1000, counterfactual=1),
    ]
    episodes[2]["side"] = "short"

    result = retrieve_similar(
        {"signal": 0.0},
        "long",
        episodes,
        now_ms=now,
        min_n=2,
        exclude_episode_id="self",
    )

    assert result["neighbors"] == []
    assert result["n"] == 0
    assert result["sufficient"] is False


def test_retrieval_shrinks_small_local_sample_toward_global_rate():
    now = 2_000_000_000
    episodes = [
        episode("near-win", "win", now - 8 * 60 * 60 * 1000, value=0.0),
        episode("far-loss", "loss", now - 2 * 24 * 60 * 60 * 1000, value=10.0),
        episode("other-loss", "loss", now - 3 * 24 * 60 * 60 * 1000, value=11.0),
    ]

    result = retrieve_similar(
        {"signal": 0.0},
        "long",
        episodes,
        k=1,
        min_n=2,
        now_ms=now,
        prior_strength=10,
        feature_stats={"signal": (0.0, 1.0)},
    )

    assert result["n"] == 1
    assert result["global_win_rate"] == pytest.approx(1 / 3)
    assert result["global_win_rate"] < result["shrunk_win_rate"] < 1
    assert result["sufficient"] is False


@pytest.mark.parametrize("probability", [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0])
def test_memory_gate_never_increases_position_size(probability):
    action = memory_gate(
        {"sufficient": True, "shrunk_win_rate": probability},
        breakeven_probability=0.5,
    )

    assert 0.5 <= action["size_multiplier"] <= 1.0
