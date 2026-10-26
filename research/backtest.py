from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from engine.risk import calculate_risk, load_config, risk_config
from research.features import build_features
from research.metrics import calculate_metrics
from tools.indicators import calculate_atr


def _as_utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _signal(strategy: str, row: pd.Series, previous: Optional[pd.Series]) -> int:
    bullish = (
        row.get("4h_close_ema50_atr", 0) > 0
        and row.get("4h_ema20_50_atr", 0) > 0
    )
    bearish = (
        row.get("4h_close_ema50_atr", 0) < 0
        and row.get("4h_ema20_50_atr", 0) < 0
    )
    if strategy == "fallback":
        if (
            bullish
            and row.get("1h_rsi14", 50) < 65
            and row.get("15m_macd_hist_rising", 0) > 0
        ):
            return 1
        if (
            bearish
            and row.get("1h_rsi14", 50) > 35
            and row.get("15m_macd_hist_rising", 0) == 0
        ):
            return -1
        return 0
    if strategy == "trend":
        volatility_ok = row.get("4h_atr_pct_rank", 1) < 0.9
        if bullish and row.get("4h_ema50_200_atr", 0) > 0 and volatility_ok:
            return 1
        if bearish and row.get("4h_ema50_200_atr", 0) < 0 and volatility_ok:
            return -1
        return 0
    if strategy == "breakout" and previous is not None:
        if (
            row.get("15m_resistance_distance_atr", 1) < 0
            and row.get("15m_volume_ratio", 0) > 1
        ):
            return 1
        if (
            row.get("15m_support_distance_atr", 1) < 0
            and row.get("15m_volume_ratio", 0) > 1
        ):
            return -1
    return 0


def _prepare_atr(
    candle_map: Dict[str, pd.DataFrame],
    atr_timeframe: str,
    decision_times: pd.Series,
) -> pd.DataFrame:
    if atr_timeframe not in candle_map:
        raise ValueError(f"ATR timeframe {atr_timeframe!r} is unavailable.")
    candles = candle_map[atr_timeframe].copy()
    candles = candles.sort_values("open_time").reset_index(drop=True)
    candles["_atr"] = calculate_atr(candles, 14)
    if "close_time" in candles:
        times = candles["close_time"]
        if pd.api.types.is_numeric_dtype(times):
            candles["_closed_at"] = pd.to_datetime(times, unit="ms", utc=True)
        else:
            candles["_closed_at"] = pd.to_datetime(times, utc=True)
    else:
        duration = {"15m": 15, "1h": 60, "4h": 240}[atr_timeframe]
        times = pd.to_numeric(candles["open_time"], errors="raise") + duration * 60_000
        candles["_closed_at"] = pd.to_datetime(times, unit="ms", utc=True)
    atr_frame = candles[["_closed_at", "_atr"]].dropna().sort_values("_closed_at")
    return pd.merge_asof(
        pd.DataFrame({"_closed_at": decision_times}),
        atr_frame,
        on="_closed_at",
        direction="backward",
    )


def _adverse_exit_price(price: float, direction: int, slippage: float) -> float:
    return price * (1 - direction * slippage)


def _simulate_one_trade(
    candles: pd.DataFrame,
    entry_index: int,
    direction: int,
    plan,
    config: Dict,
    funding: Optional[pd.DataFrame],
) -> Dict:
    risk = risk_config(config)
    backtest = config.get("backtest", {})
    max_holding = int(risk.get("max_holding_bars", 48))
    slippage = float(backtest.get("slippage_pct", 0.0005))
    fee_per_side = float(backtest.get("fee_per_side_pct", 0.0005))
    entry_price = float(plan.entry)
    size = float(plan.size_btc)
    leverage = int(plan.leverage)
    margin = entry_price * size / leverage
    stop = float(plan.stop_loss)
    target = float(plan.take_profit)
    liquidation = entry_price - direction * margin / size
    exit_reason = "END_OF_DATA"
    exit_reference = float(candles.iloc[-1]["close"])
    exit_index = len(candles) - 1
    start_index = entry_index

    for index in range(start_index, len(candles)):
        bar = candles.iloc[index]
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        stop_hit = low <= stop if direction == 1 else high >= stop
        target_hit = high >= target if direction == 1 else low <= target
        liquidation_hit = low <= liquidation if direction == 1 else high >= liquidation
        if stop_hit:
            exit_reason = "SL"
            exit_reference = min(open_price, stop) if direction == 1 else max(open_price, stop)
        elif target_hit:
            exit_reason = "TP"
            exit_reference = target
        elif liquidation_hit:
            exit_reason = "LIQUIDATION"
            exit_reference = min(open_price, liquidation) if direction == 1 else max(open_price, liquidation)
        elif index - entry_index + 1 >= max_holding:
            exit_reason = "TIME"
            exit_reference = float(bar["close"])
        else:
            continue
        exit_index = index
        break

    exit_price = _adverse_exit_price(exit_reference, direction, slippage)
    gross_pnl = direction * (exit_price - entry_price) * size
    fees = (entry_price + exit_price) * size * fee_per_side
    funding_cost = 0.0
    opened_at = int(candles.iloc[entry_index]["open_time"])
    closed_at = int(candles.iloc[exit_index]["close_time"])
    if (
        funding is not None
        and not funding.empty
        and backtest.get("include_funding", True)
    ):
        funding_time = pd.to_numeric(funding["fundingTime"], errors="raise")
        funding_rate = pd.to_numeric(funding["fundingRate"], errors="raise")
        active = (funding_time > opened_at) & (funding_time <= closed_at)
        funding_cost = float(
            (funding_rate[active] * entry_price * size * direction).sum()
        )
    net_pnl = gross_pnl - fees - funding_cost
    return {
        "side": "long" if direction == 1 else "short",
        "entry": entry_price,
        "exit": exit_price,
        "size_btc": size,
        "leverage": leverage,
        "margin_usd": margin,
        "stop_loss": stop,
        "take_profit": target,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "duration_seconds": max(0, (closed_at - opened_at) // 1000),
        "exit_reason": exit_reason,
        "pnl_gross": gross_pnl,
        "fee_usd": fees,
        "funding_usd": funding_cost,
        "pnl_usd": net_pnl,
        "initial_risk_usd": float(plan.risk_amount_usd),
        "risk_flags": list(plan.flags),
        "entry_index": entry_index,
        "exit_index": exit_index,
    }


def run_backtest(
    candles_by_timeframe: Dict[str, pd.DataFrame],
    decision_timeframe: str = "15m",
    strategy: str = "fallback",
    config: Optional[Dict] = None,
    funding: Optional[pd.DataFrame] = None,
    feature_frame: Optional[pd.DataFrame] = None,
    signals_override: Optional[Dict[int, int]] = None,
    cost_multiplier: float = 1.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict:
    if config is None:
        config = load_config()
    if cost_multiplier <= 0:
        raise ValueError("Cost multiplier must be positive.")
    effective_config = deepcopy(config)
    effective_config.setdefault("backtest", {})
    effective_config["backtest"]["fee_per_side_pct"] = (
        float(effective_config["backtest"].get("fee_per_side_pct", 0.0005))
        * cost_multiplier
    )
    effective_config["backtest"]["slippage_pct"] = (
        float(effective_config["backtest"].get("slippage_pct", 0.0005))
        * cost_multiplier
    )
    effective_config.setdefault("risk", {})
    effective_config["risk"]["fee_pct_round_trip"] = (
        2 * effective_config["backtest"]["fee_per_side_pct"]
    )
    if effective_config.get("backtest", {}).get("intrabar_conflict", "stop_first") != "stop_first":
        raise ValueError("Only stop-first intrabar conflict handling is supported.")

    candles = candles_by_timeframe[decision_timeframe].copy()
    candles = candles.sort_values("open_time").reset_index(drop=True)
    features = (
        feature_frame
        if feature_frame is not None
        else build_features(candles_by_timeframe, decision_timeframe=decision_timeframe)
    )
    if len(features) != len(candles):
        raise ValueError("Features must align one-to-one with decision candles.")
    atrs = _prepare_atr(
        candles_by_timeframe,
        str(effective_config.get("atr_timeframe", "1h")),
        features["closed_at"],
    )["_atr"].to_numpy()
    risk = risk_config(effective_config)
    equity = float(effective_config.get("starting_equity_usd", 10000))
    starting_equity = equity
    peak_equity = equity
    trades = []
    start_index = 0
    stop_index = len(candles)
    if start is not None:
        start_bound = _as_utc(start)
        start_index = int(
            features["closed_at"].searchsorted(start_bound, side="left")
        )
    if end is not None:
        end_bound = _as_utc(end)
        stop_index = int(features["closed_at"].searchsorted(end_bound, side="left"))
    start_index = min(start_index, len(candles) - 1)
    stop_index = max(start_index + 1, min(stop_index, len(candles)))
    equity_curve = [
        {
            "timestamp_ms": int(candles.iloc[start_index]["open_time"]),
            "equity": equity,
        }
    ]
    daily_pnl: Dict[str, float] = {}
    recent_results = []
    cooldown_until_ms = 0
    drawdown_paused = False
    index = start_index

    while index < stop_index - 1:
        decision_row = features.iloc[index]
        direction = (
            signals_override.get(index, 0)
            if signals_override is not None
            else _signal(
                strategy,
                decision_row,
                features.iloc[index - 1] if index else None,
            )
        )
        next_open_ms = int(candles.iloc[index + 1]["open_time"])
        decision_date = datetime.fromtimestamp(
            next_open_ms / 1000, timezone.utc
        ).date().isoformat()
        if direction == 0:
            index += 1
            continue
        if drawdown_paused or next_open_ms < cooldown_until_ms:
            index += 1
            continue
        max_daily_loss = (
            float(effective_config.get("starting_equity_usd", 10000))
            * float(risk.get("max_daily_loss_pct", 0.03))
        )
        if daily_pnl.get(decision_date, 0.0) <= -max_daily_loss:
            index += 1
            continue
        atr = atrs[index]
        if not np.isfinite(atr) or atr <= 0:
            index += 1
            continue
        next_open = float(candles.iloc[index + 1]["open"])
        plan = calculate_risk(
            direction="long" if direction > 0 else "short",
            confidence=0.65,
            price=next_open,
            atr=float(atr),
            equity=equity,
            config=effective_config,
            leverage=None,
        )
        if plan.action == "no_trade" or plan.size_btc <= 0:
            index += 1
            continue
        trade = _simulate_one_trade(
            candles.iloc[:stop_index].reset_index(drop=True),
            index + 1,
            direction,
            plan,
            effective_config,
            funding,
        )
        if trade["exit_reason"] == "END_OF_DATA":
            index += 1
            continue
        trades.append(trade)
        recent_results.append(trade)
        equity += trade["pnl_usd"]
        closed_date = datetime.fromtimestamp(
            trade["closed_at"] / 1000, timezone.utc
        ).date().isoformat()
        daily_pnl[closed_date] = daily_pnl.get(closed_date, 0.0) + trade["pnl_usd"]
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0 and (
            peak_equity - equity
        ) / peak_equity > float(risk.get("max_drawdown_pct", 0.10)):
            drawdown_paused = True
        if trade["pnl_usd"] < 0:
            losses = 0
            for closed_trade in reversed(recent_results):
                if closed_trade["pnl_usd"] >= 0:
                    break
                losses += 1
            required_losses = int(risk.get("max_consecutive_losses", 3))
            if required_losses > 0 and losses >= required_losses:
                cooldown_until_ms = trade["closed_at"] + int(
                    float(risk.get("loss_cooldown_hours", 24)) * 3_600_000
                )
        equity_curve.append(
            {"timestamp_ms": trade["closed_at"], "equity": equity}
        )
        index = max(index + 1, trade["exit_index"] + 1)

    if stop_index > start_index:
        equity_curve.append(
            {
                "timestamp_ms": int(candles.iloc[stop_index - 1]["close_time"]),
                "equity": equity,
            }
        )
    metrics = calculate_metrics(trades, equity_curve, starting_equity)
    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "strategy": strategy,
        "decision_timeframe": decision_timeframe,
        "cost_multiplier": cost_multiplier,
    }


def random_entry_baseline(
    candles_by_timeframe: Dict[str, pd.DataFrame],
    decision_timeframe: str,
    trade_count: int,
    draws: int = 1000,
    config: Optional[Dict] = None,
    funding: Optional[pd.DataFrame] = None,
    seed: int = 42,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict:
    if trade_count < 0 or draws < 1:
        raise ValueError("Trade count and draw count are invalid.")
    feature_frame = build_features(
        candles_by_timeframe, decision_timeframe=decision_timeframe
    )
    max_holding = int(risk_config(config or load_config()).get("max_holding_bars", 48))
    candidate_start = (
        int(feature_frame["closed_at"].searchsorted(_as_utc(start), side="left"))
        if start is not None else 0
    )
    candidate_end = (
        int(feature_frame["closed_at"].searchsorted(_as_utc(end), side="left"))
        if end is not None else len(feature_frame)
    )
    candidate_end = min(candidate_end, len(feature_frame) - max_holding - 1)
    candidates = np.arange(candidate_start, max(candidate_start, candidate_end))
    rng = np.random.default_rng(seed)
    results = []
    for _ in range(draws):
        selected = np.sort(
            rng.choice(candidates, size=min(trade_count, len(candidates)), replace=False)
        ) if trade_count and len(candidates) else np.array([], dtype=int)
        signals = {}
        occupied_until = -1
        for candidate in selected:
            if candidate > occupied_until:
                signals[int(candidate)] = int(rng.choice([-1, 1]))
                occupied_until = int(candidate) + max_holding
        run = run_backtest(
            candles_by_timeframe,
            decision_timeframe=decision_timeframe,
            config=config,
            funding=funding,
            feature_frame=feature_frame,
            signals_override=signals,
            start=start,
            end=end,
        )
        results.append(run["metrics"])
    expectancy = [
        result["net_expectancy_r"]
        for result in results
        if result["net_expectancy_r"] is not None
    ]
    return {
        "draws": draws,
        "requested_trade_count": trade_count,
        "mean_net_expectancy_r": float(np.mean(expectancy)) if expectancy else None,
        "expectancy_r_95_interval": (
            [float(value) for value in np.quantile(expectancy, [0.025, 0.975])]
            if expectancy else [None, None]
        ),
        "mean_trade_count": float(np.mean([result["trade_count"] for result in results])),
        "seed": seed,
    }


def buy_and_hold_baseline(
    candles: pd.DataFrame,
    config: Optional[Dict] = None,
) -> Dict:
    if config is None:
        config = load_config()
    ordered = candles.sort_values("open_time").reset_index(drop=True)
    if len(ordered) < 2:
        raise ValueError("Buy-and-hold baseline requires at least two candles.")
    equity = float(config.get("starting_equity_usd", 10000))
    backtest = config.get("backtest", {})
    fee = float(backtest.get("fee_per_side_pct", 0.0005))
    slippage = float(backtest.get("slippage_pct", 0.0005))
    entry = float(ordered.iloc[0]["open"]) * (1 + slippage)
    exit_price = float(ordered.iloc[-1]["close"]) * (1 - slippage)
    size = equity / (entry * (1 + fee))
    fees = (entry + exit_price) * size * fee
    pnl = (exit_price - entry) * size - fees
    trade = {
        "side": "long",
        "entry": entry,
        "exit": exit_price,
        "size_btc": size,
        "opened_at": int(ordered.iloc[0]["open_time"]),
        "closed_at": int(ordered.iloc[-1]["close_time"]),
        "duration_seconds": max(
            0,
            (
                int(ordered.iloc[-1]["close_time"])
                - int(ordered.iloc[0]["open_time"])
            )
            // 1000,
        ),
        "pnl_usd": pnl,
        "initial_risk_usd": equity,
    }
    curve = [
        {"timestamp_ms": trade["opened_at"], "equity": equity},
        {"timestamp_ms": trade["closed_at"], "equity": equity + pnl},
    ]
    return {
        "trade": trade,
        "metrics": calculate_metrics([trade], curve, equity),
        "type": "spot_buy_and_hold",
    }


def _load_candles(data_dir: Path, start: str, end: str) -> Dict[str, pd.DataFrame]:
    result = {}
    start_time = pd.Timestamp(start, tz="UTC")
    end_time = pd.Timestamp(end, tz="UTC")
    warm_start = start_time - pd.Timedelta(days=90)
    for timeframe in ("15m", "1h", "4h"):
        path = data_dir / f"BTCUSDT_{timeframe}_futures.parquet"
        frame = pd.read_parquet(path)
        times = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        result[timeframe] = frame.loc[(times >= warm_start) & (times < end_time)].reset_index(drop=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a cost-inclusive historical paper backtest.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--report", type=Path, default=Path("research/reports/backtest.md"))
    parser.add_argument("--data-dir", type=Path, default=Path("research_data"))
    parser.add_argument("--random-draws", type=int, default=1000)
    args = parser.parse_args()
    config = load_config()
    data = _load_candles(args.data_dir, args.start, args.end)
    funding_path = args.data_dir / "BTCUSDT_funding_rates.parquet"
    funding = pd.read_parquet(funding_path) if funding_path.exists() else None
    if funding is None and config.get("backtest", {}).get("include_funding", True):
        raise FileNotFoundError("Funding history is required; run research.data_loader first.")

    results = []
    random_results = {}
    buy_hold_results = {}
    for timeframe in ("15m", "1h", "4h"):
        features = build_features(data, decision_timeframe=timeframe)
        for strategy in ("fallback", "trend", "breakout"):
            run = run_backtest(
                data,
                timeframe,
                strategy,
                config,
                funding,
                feature_frame=features,
                start=args.start,
                end=args.end,
            )
            expensive = run_backtest(
                data,
                timeframe,
                strategy,
                config,
                funding,
                feature_frame=features,
                cost_multiplier=2,
                start=args.start,
                end=args.end,
            )
            results.append((timeframe, strategy, run, expensive))
        random_results[timeframe] = random_entry_baseline(
            data,
            timeframe,
            next(
                result[2]["metrics"]["trade_count"]
                for result in results
                if result[0] == timeframe and result[1] == "fallback"
            ),
            draws=args.random_draws,
            config=config,
            funding=funding,
            start=args.start,
            end=args.end,
        )
        start_time = pd.Timestamp(args.start, tz="UTC")
        end_time = pd.Timestamp(args.end, tz="UTC")
        candle_times = pd.to_datetime(data[timeframe]["open_time"], unit="ms", utc=True)
        selected_candles = data[timeframe].loc[
            (candle_times >= start_time) & (candle_times < end_time)
        ]
        buy_hold_results[timeframe] = buy_and_hold_baseline(
            selected_candles, config
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cost-inclusive backtest",
        "",
        f"Range: {args.start} through {args.end} (UTC).",
        "Signal at bar close; entries at the next bar open. Same-bar stop/target conflicts assume stop first.",
        "",
        "| Timeframe | Strategy | Trades | Net expectancy (R) | 95% CI | Max DD | Expectancy at 2x costs |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for timeframe, strategy, run, expensive in results:
        metrics = run["metrics"]
        lines.append(
            f"| {timeframe} | {strategy} | {metrics['trade_count']} | "
            f"{metrics['net_expectancy_r']} | {metrics['expectancy_r_ci_95']} | "
            f"{metrics['max_drawdown']:.3%} | {expensive['metrics']['net_expectancy_r']} |"
        )
        stem = f"{args.report.stem}-{timeframe}-{strategy}"
        pd.DataFrame(run["trades"]).to_csv(args.report.with_name(f"{stem}-trades.csv"), index=False)
        pd.DataFrame(run["equity_curve"]).to_csv(args.report.with_name(f"{stem}-equity.csv"), index=False)
    for timeframe in ("15m", "1h", "4h"):
        hold = buy_hold_results[timeframe]["metrics"]
        lines.append(
            f"| {timeframe} | buy-and-hold (spot) | 1 | "
            f"{hold['net_expectancy_r']} | {hold['expectancy_r_ci_95']} | "
            f"{hold['max_drawdown']:.3%} | n/a |"
        )
        random = random_results[timeframe]
        lines.append(
            f"| {timeframe} | random ({args.random_draws} draws) | "
            f"{random['mean_trade_count']:.1f} | "
            f"{random['mean_net_expectancy_r']} | "
            f"{random['expectancy_r_95_interval']} | n/a | n/a |"
        )
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
