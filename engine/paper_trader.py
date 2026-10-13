import os
import json
import time
from typing import Dict, Any, List, Optional
from tools.market_data import fetch_closed_candles

class PaperTrader:
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        self.file_path = os.path.join(data_dir, "paper-account.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "equity": 10000.0,
            "starting_equity": 10000.0,
            "open_position": None,
            "closed_trades": [],
            "realized_pnl_by_day": {}
        }

    def _save_state(self):
        with open(self.file_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def _get_today_utc(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def settle_open_position(self) -> Dict[str, Any]:
        """Settle open paper position against recent 15m closed candles"""
        pos = self.state.get("open_position")
        if not pos:
            return self.get_state()

        try:
            df15m = fetch_closed_candles(symbol="BTCUSDT", interval="15m", limit=300)
            opened_at = pos["opened_at"]
            relevant = df15m[df15m["open_time"] >= (opened_at - 15 * 60 * 1000)]

            for _, row in relevant.iterrows():
                low = row["low"]
                high = row["high"]
                close_time = int(row["close_time"])

                hit_sl = False
                hit_tp = False

                if pos["side"] == "long":
                    if low <= pos["stop_loss"]: hit_sl = True
                    if high >= pos["take_profit"]: hit_tp = True
                else:
                    if high >= pos["stop_loss"]: hit_sl = True
                    if low <= pos["take_profit"]: hit_tp = True

                if hit_sl or hit_tp:
                    # SL takes precedence if both touched in same bar
                    exit_reason = "SL" if hit_sl else "TP"
                    raw_exit = pos["stop_loss"] if hit_sl else pos["take_profit"]
                    
                    # Apply slippage on SL exit
                    slippage = 0.0005
                    if exit_reason == "SL":
                        final_exit = raw_exit * (1 - slippage) if pos["side"] == "long" else raw_exit * (1 + slippage)
                    else:
                        final_exit = raw_exit

                    fee_pct = 0.001
                    fee_exit = final_exit * pos["size"] * fee_pct
                    fees_total = pos["fees_paid_open"] + fee_exit

                    gross_pnl = (final_exit - pos["entry"]) * pos["size"] if pos["side"] == "long" else (pos["entry"] - final_exit) * pos["size"]
                    net_pnl = gross_pnl - fees_total
                    pnl_r = net_pnl / pos["initial_risk_usd"] if pos.get("initial_risk_usd", 0) > 0 else 0.0

                    closed_trade = {
                        "id": f"trade_{int(time.time() * 1000)}",
                        "decision_id": pos["decision_id"],
                        "side": pos["side"],
                        "entry": round(pos["entry"], 2),
                        "exit": round(final_exit, 2),
                        "size": round(pos["size"], 6),
                        "opened_at": pos["opened_at"],
                        "closed_at": close_time,
                        "exit_reason": exit_reason,
                        "pnl_usd": round(net_pnl, 2),
                        "pnl_r_multiples": round(pnl_r, 2),
                        "fees_paid_total": round(fees_total, 2)
                    }

                    self.state["equity"] += net_pnl
                    self.state["closed_trades"].insert(0, closed_trade)
                    self.state["open_position"] = None

                    today = self._get_today_utc()
                    self.state["realized_pnl_by_day"][today] = self.state["realized_pnl_by_day"].get(today, 0.0) + net_pnl
                    self._save_state()
                    break

        except Exception as e:
            print(f"Settlement error: {e}")

        return self.get_state()

    def is_trading_blocked(self) -> Dict[str, Any]:
        if self.state.get("open_position"):
            return {"blocked": True, "reason": "Open position already exists (Max positions = 1)."}

        today = self._get_today_utc()
        today_pnl = self.state.get("realized_pnl_by_day", {}).get(today, 0.0)
        max_daily_loss = self.state["starting_equity"] * 0.03

        if today_pnl <= -max_daily_loss:
            return {"blocked": True, "reason": f"Daily loss limit reached ({today_pnl:.2f} <= -{max_daily_loss:.2f})."}

        return {"blocked": False}

    def open_position(self, decision_id: str, side: str, entry: float, size_btc: float, stop_loss: float, take_profit: float, initial_risk_usd: float) -> Dict[str, Any]:
        self.settle_open_position()
        guard = self.is_trading_blocked()
        if guard["blocked"]:
            raise RuntimeError(guard["reason"])

        fee_pct = 0.001
        notional = entry * size_btc
        fee_open = notional * fee_pct

        pos = {
            "id": f"pos_{int(time.time() * 1000)}",
            "decision_id": decision_id,
            "side": side,
            "entry": round(entry, 2),
            "size": round(size_btc, 6),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "opened_at": int(time.time() * 1000),
            "initial_risk_usd": round(initial_risk_usd, 2),
            "fees_paid_open": round(fee_open, 2)
        }

        self.state["equity"] -= fee_open
        self.state["open_position"] = pos
        self._save_state()
        return pos

    def get_state(self) -> Dict[str, Any]:
        return dict(self.state)

    def reset_account(self) -> Dict[str, Any]:
        self.state = {
            "equity": 10000.0,
            "starting_equity": 10000.0,
            "open_position": None,
            "closed_trades": [],
            "realized_pnl_by_day": {}
        }
        self._save_state()
        return self.get_state()
