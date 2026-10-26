from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from engine.risk import calculate_risk, load_config
from research.backtest import _prepare_atr, _signal, _simulate_one_trade
from research.features import build_features


def build_labels(
    candles_by_timeframe: Dict[str, pd.DataFrame],
    decision_timeframe: str = "15m",
    strategy: str = "fallback",
    config: Optional[Dict] = None,
    funding: Optional[pd.DataFrame] = None,
    features: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Create causal triple-barrier outcomes only for primary-signal candidates."""
    if config is None:
        config = load_config()
    decision_candles = (
        candles_by_timeframe[decision_timeframe]
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    if features is None:
        features = build_features(candles_by_timeframe, decision_timeframe)
    if len(features) != len(decision_candles):
        raise ValueError("Features must align one-to-one with decision candles.")
    atrs = _prepare_atr(
        candles_by_timeframe,
        str(config.get("atr_timeframe", "1h")),
        features["closed_at"],
    )["_atr"].to_numpy()
    starting_equity = float(config.get("starting_equity_usd", 10000))
    labels = []
    for index in range(len(decision_candles) - 1):
        row = features.iloc[index]
        signal = _signal(
            strategy,
            row,
            features.iloc[index - 1] if index else None,
        )
        if signal == 0 or not np.isfinite(atrs[index]) or atrs[index] <= 0:
            continue
        entry = float(decision_candles.iloc[index + 1]["open"])
        for direction in (1, -1):
            plan = calculate_risk(
                direction="long" if direction == 1 else "short",
                confidence=0.65,
                price=entry,
                atr=float(atrs[index]),
                equity=starting_equity,
                config=config,
                leverage=None,
            )
            if plan.action == "no_trade" or plan.size_btc <= 0:
                continue
            trade = _simulate_one_trade(
                decision_candles, index + 1, direction, plan, config, funding
            )
            if trade["exit_reason"] == "END_OF_DATA":
                continue
            labels.append(
                {
                    "candidate_index": index,
                    "entry_index": index + 1,
                    "label_end_index": trade["exit_index"],
                    "direction": direction,
                    "primary_signal": signal,
                    "label": int(trade["pnl_usd"] > 0),
                    "realized_net_r": (
                        trade["pnl_usd"] / trade["initial_risk_usd"]
                        if trade["initial_risk_usd"] > 0 else 0.0
                    ),
                    "exit_reason": trade["exit_reason"],
                    "pnl_usd": trade["pnl_usd"],
                    "initial_risk_usd": trade["initial_risk_usd"],
                    "breakeven_probability": plan.breakeven_probability,
                    "timestamp": row["closed_at"],
                    "label_end_timestamp": pd.to_datetime(
                        decision_candles.iloc[trade["exit_index"]]["close_time"],
                        unit="ms",
                        utc=True,
                    ),
                }
            )
    result = pd.DataFrame(labels)
    if result.empty:
        return result
    result["uniqueness_weight"] = label_uniqueness_weights(result)
    return result


def label_uniqueness_weights(labels: pd.DataFrame) -> pd.Series:
    required = {"entry_index", "label_end_index"}
    if not required.issubset(labels.columns):
        raise ValueError(f"Labels require {sorted(required)}.")
    concurrency: Dict[int, int] = {}
    for row in labels.itertuples():
        for bar in range(int(row.entry_index), int(row.label_end_index) + 1):
            concurrency[bar] = concurrency.get(bar, 0) + 1
    weights = []
    for row in labels.itertuples():
        active = [
            1 / concurrency[bar]
            for bar in range(int(row.entry_index), int(row.label_end_index) + 1)
        ]
        weights.append(float(np.mean(active)) if active else 0.0)
    return pd.Series(weights, index=labels.index, dtype=float)


def purged_walk_forward_splits(
    labels: pd.DataFrame,
    n_splits: int = 5,
    embargo_bars: int = 48,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return anchored time splits with overlapping labels purged before validation."""
    if n_splits < 2 or embargo_bars < 0:
        raise ValueError("At least two folds and a non-negative embargo are required.")
    sort_columns = ["candidate_index"]
    if "direction" in labels:
        sort_columns.append("direction")
    ordered = labels.sort_values(sort_columns).reset_index(drop=True)
    candidate_indices = np.sort(ordered["candidate_index"].unique())
    fold_size = len(candidate_indices) // (n_splits + 1)
    if fold_size < 1:
        raise ValueError("Not enough labeled samples for the requested folds.")
    splits = []
    for fold in range(n_splits):
        validation_start = (fold + 1) * fold_size
        validation_end = (
            len(candidate_indices)
            if fold == n_splits - 1
            else min(len(candidate_indices), validation_start + fold_size)
        )
        validation_candidates = candidate_indices[validation_start:validation_end]
        first_validation_bar = int(validation_candidates[0])
        validation = np.flatnonzero(
            ordered["candidate_index"].isin(validation_candidates).to_numpy()
        )
        train = np.flatnonzero(
            (ordered["candidate_index"] < first_validation_bar).to_numpy()
        )
        keep = ordered.iloc[train]["label_end_index"].to_numpy() < (
            first_validation_bar - embargo_bars
        )
        train = train[keep]
        if train.size and validation.size:
            splits.append((train, validation))
    return splits
