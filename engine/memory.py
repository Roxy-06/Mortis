from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import numpy as np


def retrieve_similar(
    feature_vector: Dict[str, float],
    side: str,
    episodes: Iterable[Dict[str, Any]],
    *,
    k: int = 20,
    min_n: int = 30,
    min_gap_bars: int = 24,
    half_life_days: float = 90,
    prior_strength: float = 20,
    feature_schema_version: int = 1,
    now_ms: Optional[int] = None,
    feature_stats: Optional[Dict[str, tuple[float, float]]] = None,
    exclude_episode_id: Optional[str] = None,
) -> Dict[str, Any]:
    if side not in ("long", "short"):
        raise ValueError("Memory retrieval requires a long or short side.")
    if k < 1 or min_n < 1 or min_gap_bars < 0 or half_life_days <= 0:
        raise ValueError("Memory retrieval limits must be positive.")
    current_time = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    gap_ms = min_gap_bars * 15 * 60 * 1000
    valid_query = {
        key: float(value)
        for key, value in feature_vector.items()
        if math.isfinite(float(value))
    }
    candidates = []
    for episode in episodes:
        if (
            episode.get("side") != side
            or int(episode.get("feature_schema_version", -1))
            != feature_schema_version
            or int(episode.get("counterfactual", 0))
            or episode.get("id") == exclude_episode_id
        ):
            continue
        created_at = int(episode["created_at_ms"])
        if abs(current_time - created_at) <= gap_ms:
            continue
        try:
            values = json.loads(episode["feature_vector_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        common = sorted(set(valid_query).intersection(values))
        if not common:
            continue
        pairs = []
        for name in common:
            left = valid_query[name]
            right = float(values[name])
            if not math.isfinite(right):
                continue
            mean, stddev = (feature_stats or {}).get(name, (0.0, 1.0))
            scale = stddev if math.isfinite(stddev) and stddev > 1e-12 else 1.0
            pairs.append(((left - mean) / scale, (right - mean) / scale))
        if not pairs:
            continue
        distance = math.sqrt(
            sum((left - right) ** 2 for left, right in pairs) / len(pairs)
        )
        age_days = max(0, current_time - created_at) / 86_400_000
        weight = math.exp(-math.log(2) * age_days / half_life_days)
        candidates.append(
            {
                **episode,
                "distance": distance,
                "weight": weight,
            }
        )
    candidates.sort(key=lambda item: (item["distance"], -item["created_at_ms"]))
    neighbors = candidates[:k]
    resolved = [
        item for item in neighbors if item.get("outcome") in ("win", "loss", "timeout")
    ]
    all_resolved = [
        item
        for item in candidates
        if item.get("outcome") in ("win", "loss", "timeout")
    ]
    global_rate = (
        sum(item["outcome"] == "win" for item in all_resolved) / len(all_resolved)
        if all_resolved
        else 0.5
    )
    weights = np.asarray([item["weight"] for item in resolved], dtype=float)
    wins = np.asarray([item["outcome"] == "win" for item in resolved], dtype=float)
    returns = np.asarray(
        [float(item["r_multiple"] or 0.0) for item in resolved], dtype=float
    )
    weight_sum = float(weights.sum())
    effective_n = weight_sum**2 / float(np.square(weights).sum()) if weight_sum else 0.0
    shrunk_win_rate = (
        (float(np.dot(weights, wins)) + prior_strength * global_rate)
        / (weight_sum + prior_strength)
        if weight_sum + prior_strength > 0
        else global_rate
    )
    weighted_average_r = (
        float(np.dot(weights, returns) / weight_sum) if weight_sum else None
    )
    weighted_stddev_r = (
        float(np.sqrt(np.dot(weights, np.square(returns - weighted_average_r)) / weight_sum))
        if weight_sum and weighted_average_r is not None
        else None
    )
    interval = None
    if len(resolved) >= 2:
        random = np.random.default_rng(42)
        probabilities = weights / weight_sum
        bootstrap = [
            float(np.mean(wins[random.choice(len(wins), len(wins), p=probabilities)]))
            for _ in range(500)
        ]
        interval = [
            float(np.quantile(bootstrap, 0.025)),
            float(np.quantile(bootstrap, 0.975)),
        ]
    return {
        "side": side,
        "feature_schema_version": feature_schema_version,
        "neighbors": [
            {
                "id": item["id"],
                "decision_id": item["decision_id"],
                "created_at_ms": item["created_at_ms"],
                "outcome": item["outcome"],
                "r_multiple": item["r_multiple"],
                "exit_reason": item["exit_reason"],
                "lesson_text": item["lesson_text"],
                "distance": item["distance"],
                "weight": item["weight"],
            }
            for item in neighbors
        ],
        "n": len(resolved),
        "effective_n": effective_n,
        "global_win_rate": global_rate,
        "shrunk_win_rate": shrunk_win_rate,
        "average_r": weighted_average_r,
        "stddev_r": weighted_stddev_r,
        "win_rate_confidence_interval": interval,
        "sufficient": effective_n >= min_n,
        "min_n": min_n,
    }


def memory_gate(
    summary: Dict[str, Any],
    breakeven_probability: Optional[float],
    *,
    veto_gap: float = 0.10,
    min_size_multiplier: float = 0.5,
) -> Dict[str, Any]:
    if not 0.5 <= min_size_multiplier <= 1:
        raise ValueError("Memory size multiplier must be between 0.5 and 1.")
    result = {"veto": False, "size_multiplier": 1.0, "reason": None}
    if not summary.get("sufficient") or breakeven_probability is None:
        return result
    win_rate = float(summary["shrunk_win_rate"])
    gap = float(breakeven_probability) - win_rate
    if gap >= veto_gap:
        result.update(veto=True, reason="memory_veto")
    elif gap > 0:
        result.update(
            size_multiplier=max(min_size_multiplier, 1.0 - gap / max(veto_gap, 1e-9)),
            reason="memory_size_reduced",
        )
    return result
