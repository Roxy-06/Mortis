import os
import json
import hashlib
from typing import Dict, Any
from tools.market_data import fetch_multi_timeframe_candles, fetch_current_price
from tools.indicators import compute_timeframe_indicators
from engine.risk import calculate_risk
from engine.paper_trader import PaperTrader
from chain.logger import log_decision_record

SYSTEM_PROMPT = """You are Mortis, an autonomous Bitcoin paper-trading analyst agent. You analyze live BTC/USDT market data and make simulated paper-trading decisions. You never trade real money.

Rules:
1. Read the market snapshot top-down: 4h = trend direction, 1h = setup quality, 15m = entry timing. Prefer trades aligned with the 4h trend. If timeframes conflict or setup is weak, output direction = "neutral".
2. You output ONLY JSON matching this format:
{
  "direction": "long" | "short" | "neutral",
  "confidence": 0.0 - 1.0,
  "rationale": "Max 3 concise sentences summarizing key indicator alignment."
}
3. Confidence guide: 0.50 = weak lean, 0.60-0.70 = decent setup, 0.80+ = rare and strong, never above 0.95.
4. Never calculate stop-loss, take-profit or position size yourself; the system computes them.
5. Be honest and objective."""

class TAAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.paper_trader = PaperTrader()

    def _fallback_deterministic_analysis(self, snapshot: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """Deterministic TA evaluation fallback when Gemini API key is missing or unauthenticated"""
        ind_4h = snapshot["timeframes"]["4h"]
        ind_1h = snapshot["timeframes"]["1h"]
        ind_15m = snapshot["timeframes"]["15m"]

        # 4h Trend
        bullish_4h = ind_4h["trend_flags"]["price_above_ema50"] and ind_4h["trend_flags"]["ema20_above_ema50"]
        bearish_4h = not ind_4h["trend_flags"]["price_above_ema50"] and not ind_4h["trend_flags"]["ema20_above_ema50"]

        # 1h Setup
        rsi_1h = ind_1h["rsi14"]
        macd_rising_15m = ind_15m["macd"]["histogram_rising"]

        direction = "neutral"
        confidence = 0.50

        if bullish_4h and rsi_1h < 65 and macd_rising_15m:
            direction = "long"
            confidence = 0.65
            rationale = f"4h EMA trend bullish, 1h RSI ({rsi_1h:.1f}) in buy zone, 15m MACD momentum rising. ({reason})"
        elif bearish_4h and rsi_1h > 35 and not macd_rising_15m:
            direction = "short"
            confidence = 0.65
            rationale = f"4h EMA trend bearish, 1h RSI ({rsi_1h:.1f}) in sell zone, 15m MACD momentum declining. ({reason})"
        else:
            rationale = f"Timeframe confluence weak or 4h trend neutral; maintaining neutral stance. ({reason})"

        return {
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale
        }

    def analyze_and_trade(self) -> Dict[str, Any]:
        """Fetch market snapshot, query Gemini TA agent (or fallback rules), run risk engine, log & execute paper trade"""
        price = fetch_current_price("BTCUSDT")
        tf_candles = fetch_multi_timeframe_candles("BTCUSDT", ["4h", "1h", "15m"])

        ind_4h = compute_timeframe_indicators(tf_candles["4h"])
        ind_1h = compute_timeframe_indicators(tf_candles["1h"])
        ind_15m = compute_timeframe_indicators(tf_candles["15m"])

        snapshot = {
            "symbol": "BTCUSDT",
            "price": price,
            "timeframes": {
                "4h": ind_4h,
                "1h": ind_1h,
                "15m": ind_15m
            }
        }

        # SHA-256 digest of candles
        candles_summary = json.dumps({
            "4h": tf_candles["4h"][["open_time", "close"]].tail(5).to_dict(orient="records"),
            "1h": tf_candles["1h"][["open_time", "close"]].tail(5).to_dict(orient="records"),
            "15m": tf_candles["15m"][["open_time", "close"]].tail(5).to_dict(orient="records"),
        }, sort_keys=True)
        candles_digest = hashlib.sha256(candles_summary.encode("utf-8")).hexdigest()

        agent_decision = None

        # Attempt Gemini API Call if key exists and starts with valid format
        if self.api_key and len(self.api_key) > 10:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                prompt = f"Analyze this live market snapshot and give your JSON decision:\n{json.dumps(snapshot, indent=2)}"
                
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                )

                raw_text = response.text.strip() if response.text else "{}"
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()

                agent_decision = json.loads(raw_text)
            except Exception as e:
                print(f"[Gemini API Notice]: {e}. Using deterministic TA fallback rule engine.")
                agent_decision = self._fallback_deterministic_analysis(
                    snapshot, reason="Gemini key unauthenticated or rate-limited"
                )
        else:
            agent_decision = self._fallback_deterministic_analysis(
                snapshot, reason="No valid GEMINI_API_KEY configured"
            )

        direction = agent_decision.get("direction", "neutral")
        confidence = float(agent_decision.get("confidence", 0.5))
        rationale = agent_decision.get("rationale", "")

        # Settle paper account & check guards
        self.paper_trader.settle_open_position()
        account_state = self.paper_trader.get_state()
        guard = self.paper_trader.is_trading_blocked()

        atr_1h = ind_1h["atr14"]
        trade_plan = calculate_risk(
            direction=direction,
            confidence=confidence,
            price=price,
            atr=atr_1h,
            equity=account_state["equity"]
        )

        final_action = trade_plan.action
        reason_if_no_trade = trade_plan.reason_if_no_trade

        opened_trade = None
        if final_action != "no_trade":
            if guard["blocked"]:
                final_action = "no_trade"
                reason_if_no_trade = guard["reason"]
            else:
                opened_trade = self.paper_trader.open_position(
                    decision_id="pending",
                    side=final_action,
                    entry=trade_plan.entry,
                    size_btc=trade_plan.size_btc,
                    stop_loss=trade_plan.stop_loss,
                    take_profit=trade_plan.take_profit,
                    initial_risk_usd=trade_plan.risk_amount_usd
                )

        trade_plan_dict = {
            "action": final_action,
            "reason_if_no_trade": reason_if_no_trade,
            "raw_confidence": trade_plan.raw_confidence,
            "clamped_confidence": trade_plan.clamped_confidence,
            "entry": trade_plan.entry,
            "stop_loss": trade_plan.stop_loss,
            "take_profit": trade_plan.take_profit,
            "size_btc": trade_plan.size_btc,
            "notional_usd": trade_plan.notional_usd,
            "risk_amount_usd": trade_plan.risk_amount_usd,
            "size_multiplier": trade_plan.size_multiplier,
            "flags": trade_plan.flags
        }

        # Log decision with canonical SHA-256 hash
        record = log_decision_record(
            price=price,
            candles_digest=candles_digest,
            raw_direction=direction,
            rationale=rationale,
            trade_plan=trade_plan_dict,
            risk_checks={
                "threshold_ok": final_action != "no_trade" or "threshold" not in (reason_if_no_trade or ""),
                "open_positions_ok": not account_state.get("open_position"),
                "daily_loss_ok": not guard["blocked"],
                "notional_cap_ok": "capped_by_notional" not in trade_plan.flags
            },
            model_id=self.model_name
        )

        if opened_trade and self.paper_trader.get_state().get("open_position"):
            self.paper_trader.state["open_position"]["decision_id"] = record["decision_id"]
            self.paper_trader._save_state()

        return {
            "snapshot": snapshot,
            "agent_decision": agent_decision,
            "trade_plan": trade_plan_dict,
            "decision_record": record,
            "account": self.paper_trader.get_state()
        }
