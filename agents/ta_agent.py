import hashlib
import json
import logging
import math
from typing import Any, Dict, Optional

import pandas as pd

from chain.logger import log_decision_record
from agents.model_registry import load_active_model
from engine.paper_trader import PaperTrader
from engine.risk import calculate_risk, load_config
from research.features import build_features
from tools.indicators import compute_timeframe_indicators
from tools.market_data import (
    fetch_best_bid_ask,
    fetch_current_price,
    fetch_multi_timeframe_candles,
)


class TAAgent:
    def __init__(self, paper_trader: Optional[PaperTrader] = None):
        self.paper_trader = paper_trader

    def _fallback_deterministic_analysis(
        self, snapshot: Dict[str, Any], reason: str
    ) -> Dict[str, Any]:
        indicators = snapshot["timeframes"]
        ind_4h = indicators["4h"]
        ind_1h = indicators["1h"]
        ind_15m = indicators["15m"]

        bullish_4h = (
            ind_4h["trend_flags"]["price_above_ema50"]
            and ind_4h["trend_flags"]["ema20_above_ema50"]
        )
        bearish_4h = (
            not ind_4h["trend_flags"]["price_above_ema50"]
            and not ind_4h["trend_flags"]["ema20_above_ema50"]
        )
        rsi_1h = ind_1h["rsi14"]
        macd_rising_15m = ind_15m["macd"]["histogram_rising"]

        if bullish_4h and rsi_1h < 65 and macd_rising_15m:
            direction = "long"
            rationale = (
                f"4h EMA trend bullish, 1h RSI ({rsi_1h:.1f}) in buy zone, "
                f"15m MACD momentum rising. ({reason})"
            )
        elif bearish_4h and rsi_1h > 35 and not macd_rising_15m:
            direction = "short"
            rationale = (
                f"4h EMA trend bearish, 1h RSI ({rsi_1h:.1f}) in sell zone, "
                f"15m MACD momentum declining. ({reason})"
            )
        else:
            direction = "neutral"
            rationale = f"Timeframe confluence weak; maintaining neutral stance. ({reason})"
        return {
            "direction": direction,
            "confidence": 0.65 if direction != "neutral" else 0.50,
            "rationale": rationale,
            "source": "deterministic_rule_fallback",
            "calibrated": False,
        }

    def analyze(self, user_message: str = "") -> Dict[str, Any]:
        """Return an analysis and paper plan without writing a decision or opening a trade."""
        del user_message
        config = load_config()
        active_model = load_active_model(config)
        timeframes = config.get("timeframes", ["4h", "1h", "15m"])
        candles_per_timeframe = int(config.get("candles_per_timeframe", 300))
        symbol = str(config.get("symbol", "BTCUSDT"))
        price = fetch_current_price(symbol)
        tf_candles = fetch_multi_timeframe_candles(
            symbol, timeframes, limit=candles_per_timeframe
        )
        indicators = {
            timeframe: compute_timeframe_indicators(tf_candles[timeframe])
            for timeframe in timeframes
        }
        required_timeframes = {"4h", "1h", "15m"}
        if not required_timeframes.issubset(indicators):
            raise ValueError("The deterministic strategy requires 4h, 1h, and 15m timeframes.")

        snapshot = {
            "symbol": symbol,
            "price": price,
            "timeframes": indicators,
        }
        candle_digest = hashlib.sha256(
            json.dumps(
                {
                    timeframe: tf_candles[timeframe][["open_time", "close"]]
                    .tail(5)
                    .to_dict(orient="records")
                    for timeframe in timeframes
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        decision_timeframe = (
            active_model.decision_timeframe if active_model is not None else "15m"
        )
        if decision_timeframe not in tf_candles:
            raise ValueError(
                f"Active model timeframe {decision_timeframe!r} is unavailable."
            )
        feature_frame = build_features(
            tf_candles, decision_timeframe=decision_timeframe
        )
        features_row = feature_frame.iloc[-1].drop(labels=["closed_at"])
        feature_vector = {
            name: float(value)
            for name, value in features_row.items()
            if pd.notna(value) and math.isfinite(float(value))
        }

        decision = self._fallback_deterministic_analysis(
            snapshot,
            (
                "no promoted calibrated model is configured"
                if active_model is None
                else f"promoted model {active_model.version} is active"
            ),
        )
        decision_margin = float(
            config.get("model", {}).get("margin_over_breakeven", 0.03)
        )
        if active_model is not None:
            decision_margin = active_model.margin_over_breakeven
            direction = {"long": 1, "short": -1}.get(decision["direction"])
            if direction is not None:
                probability = active_model.probability(feature_vector, direction)
                decision.update(
                    {
                        "confidence": probability,
                        "calibrated_probability": probability,
                        "source": f"promoted_model:{active_model.version}",
                        "calibrated": True,
                        "rationale": (
                            f"{decision['rationale']} Promoted model estimates "
                            f"{probability:.1%} probability of a net-positive outcome."
                        ),
                    }
                )
        decision["decision_margin"] = decision_margin
        account_state = (
            self.paper_trader.get_state()
            if self.paper_trader is not None
            else {
                "equity": float(config.get("starting_equity_usd", 10000.0)),
                "open_position": None,
            }
        )
        risk_settings = config.get("risk", {})
        atr_timeframe = config.get("atr_timeframe", "1h")
        if atr_timeframe not in indicators:
            raise ValueError(f"Configured ATR timeframe {atr_timeframe!r} is unavailable.")
        memory_summary = (
            self.paper_trader.retrieve_memory(feature_vector, decision["direction"])
            if self.paper_trader is not None
            and decision["direction"] in ("long", "short")
            else {
                "neighbors": [],
                "n": 0,
                "effective_n": 0.0,
                "shrunk_win_rate": None,
                "average_r": None,
                "sufficient": False,
                "mode": config.get("memory", {}).get("mode", "advisory"),
            }
        )
        calibrated = bool(decision.get("calibrated"))
        confidence_for_sizing = decision["confidence"]
        if not calibrated:
            confidence_for_sizing = float(
                risk_settings.get("confidence_threshold", 0.55)
            )
        trade_plan = calculate_risk(
            direction=decision["direction"],
            confidence=confidence_for_sizing,
            price=price,
            atr=indicators[atr_timeframe]["atr14"],
            equity=account_state["equity"],
            config=config,
            leverage=None,
        )
        plan = {
            "action": trade_plan.action,
            "reason_if_no_trade": trade_plan.reason_if_no_trade,
            "raw_confidence": trade_plan.raw_confidence,
            "clamped_confidence": trade_plan.clamped_confidence,
            "entry": trade_plan.entry,
            "stop_loss": trade_plan.stop_loss,
            "take_profit": trade_plan.take_profit,
            "size_btc": trade_plan.size_btc,
            "notional_usd": trade_plan.notional_usd,
            "risk_amount_usd": trade_plan.risk_amount_usd,
            "size_multiplier": trade_plan.size_multiplier,
            "leverage": trade_plan.leverage,
            "expected_cost_r": trade_plan.expected_cost_r,
            "breakeven_probability": trade_plan.breakeven_probability,
            "required_probability": (
                trade_plan.breakeven_probability
                + decision_margin
                if trade_plan.breakeven_probability is not None
                else None
            ),
            "flags": trade_plan.flags,
            "atr_at_entry": indicators[atr_timeframe]["atr14"],
            "sl_atr_mult": risk_settings.get("sl_atr_mult", 1.5),
            "tp_atr_mult": risk_settings.get("tp_atr_mult", 2.5),
        }
        memory_action = {"veto": False, "size_multiplier": 1.0, "reason": None}
        memory_settings = config.get("memory", {})
        if (
            memory_settings.get("mode", "advisory") == "gate"
            and plan["action"] != "no_trade"
        ):
            memory_action = memory_gate(
                memory_summary,
                plan["breakeven_probability"],
                veto_gap=float(memory_settings.get("veto_gap", 0.1)),
                min_size_multiplier=float(
                    memory_settings.get("min_size_multiplier", 0.5)
                ),
            )
            if memory_action["veto"]:
                plan["action"] = "no_trade"
                plan["reason_if_no_trade"] = "memory_veto"
            elif memory_action["size_multiplier"] < 1:
                multiplier = min(1.0, float(memory_action["size_multiplier"]))
                plan["size_btc"] = round(plan["size_btc"] * multiplier, 8)
                plan["notional_usd"] = round(plan["notional_usd"] * multiplier, 2)
                plan["risk_amount_usd"] = round(
                    plan["risk_amount_usd"] * multiplier, 2
                )
                plan["size_multiplier"] = round(
                    plan["size_multiplier"] * multiplier, 4
                )
                plan["flags"].append("memory_size_reduced")
        plan["memory_action"] = memory_action
        if (
            active_model is not None
            and plan["action"] != "no_trade"
            and plan["required_probability"] is not None
            and decision.get("calibrated_probability", 0.0)
            <= plan["required_probability"]
        ):
            plan["action"] = "no_trade"
            plan["reason_if_no_trade"] = (
                "Promoted model probability does not exceed estimated breakeven "
                "by the configured margin."
            )
        guard = (
            self.paper_trader.is_trading_blocked()
            if self.paper_trader is not None
            else {"blocked": False}
        )
        if plan["action"] != "no_trade" and guard["blocked"]:
            plan["action"] = "no_trade"
            plan["reason_if_no_trade"] = guard["reason"]

        return {
            "snapshot": snapshot,
            "agent_decision": decision,
            "trade_plan": plan,
            "decision_record": None,
            "account": account_state,
            "config": config,
            "feature_vector": feature_vector,
            "memory_summary": memory_summary,
            "candles_digest": candle_digest,
            "risk_checks": {
                "threshold_ok": plan["action"] != "no_trade",
                "open_positions_ok": not bool(account_state.get("open_position")),
                "account_guard_ok": not guard["blocked"],
            },
        }

    def execute(self, user_message: str = "") -> Dict[str, Any]:
        """Persist an analysis and execute its plan in the local paper account."""
        if self.paper_trader is None:
            self.paper_trader = PaperTrader()
        result = self.analyze(user_message)
        decision = result["agent_decision"]
        plan = result["trade_plan"]
        config = result["config"]
        quote = None
        quote_status = "unavailable"
        try:
            quote = fetch_best_bid_ask(str(config.get("symbol", "BTCUSDT")))
            quote_status = "captured"
        except RuntimeError as error:
            logging.warning("Training sample has no best bid/ask quote: %s", error)
        record = log_decision_record(
            price=result["snapshot"]["price"],
            candles_digest=result["candles_digest"],
            raw_direction=decision["direction"],
            rationale=decision["rationale"],
            trade_plan=plan,
            risk_checks=result["risk_checks"],
            model_id=decision["source"],
            leverage=plan["leverage"],
            config_snapshot=config,
            feature_vector=result["feature_vector"],
            model_version=config.get("model", {}).get("active_version"),
            calibrated_probability=decision.get("calibrated_probability"),
            breakeven_probability=plan.get("breakeven_probability"),
            decision_margin=decision.get(
                "decision_margin",
                config.get("model", {}).get("margin_over_breakeven", 0.03),
            ),
            memory_summary=result["memory_summary"],
        )
        self.paper_trader.record_training_sample(
            decision_id=record["decision_id"],
            features=result["feature_vector"],
            decision={
                **decision,
                "trade_plan": plan,
                "model_version": config.get("model", {}).get("active_version"),
                "quote_status": quote_status,
                "memory_summary": result["memory_summary"],
                "indicator_snapshot": result["snapshot"]["timeframes"],
            },
            best_bid=quote["best_bid"] if quote else None,
            best_ask=quote["best_ask"] if quote else None,
            quote_status=quote_status,
        )
        self.paper_trader.record_decision(
            record=record,
            direction=decision["direction"],
            source=decision["source"],
            confidence=decision["confidence"],
            calibrated_probability=decision.get("calibrated_probability"),
            feature_vector=result["feature_vector"],
            indicator_snapshot=result["snapshot"]["timeframes"],
            trade_plan=plan,
            memory=result["memory_summary"],
            counterfactual=(
                plan["action"] == "no_trade"
                and decision["direction"] in ("long", "short")
            ),
        )
        if plan["action"] != "no_trade":
            self.paper_trader.open_position(
                decision_id=record["decision_id"],
                side=plan["action"],
                entry=plan["entry"],
                size_btc=plan["size_btc"],
                stop_loss=plan["stop_loss"],
                take_profit=plan["take_profit"],
                initial_risk_usd=plan["risk_amount_usd"],
                leverage=plan["leverage"],
                source="ai",
                rationale=decision["rationale"],
                atr_at_entry=plan["atr_at_entry"],
                sl_atr_mult=float(plan["sl_atr_mult"]),
                tp_atr_mult=float(plan["tp_atr_mult"]),
                confidence=decision["confidence"],
                feature_vector=result["feature_vector"],
                decision_source=decision["source"],
            )
        result["decision_record"] = record
        result["account"] = self.paper_trader.get_state()
        return result

    def analyze_and_trade(self, user_message: str = "") -> Dict[str, Any]:
        """Compatibility entry point for autonomous paper trading."""
        return self.execute(user_message)
