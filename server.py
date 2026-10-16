import os
import json
import time
import threading
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

from agents.ta_agent import TAAgent
from engine.paper_trader import PaperTrader, ROUND_TRIP_FEE_PCT
from chain.logger import verify_decision_record, get_decisions_dir
from tools.market_data import fetch_multi_timeframe_candles, fetch_current_price
from tools.indicators import compute_timeframe_indicators
from engine.loop import run_loop


def autonomous_trading_enabled() -> bool:
    return os.getenv("MORTIS_AUTOTRADE_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()
    worker = None
    if autonomous_trading_enabled():
        worker = threading.Thread(
            target=run_loop,
            kwargs={"stop_event": stop_event},
            name="mortis-autonomous-trader",
            daemon=True,
        )
        worker.start()
    app.state.autotrade_enabled = autonomous_trading_enabled()
    app.state.autotrade_worker = worker
    yield
    stop_event.set()
    if worker is not None:
        worker.join(timeout=10)


app = FastAPI(
    title="Mortis Python Engine API",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for React / Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

paper_trader = PaperTrader()

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = []

class VerifyRequest(BaseModel):
    decision_id: Optional[str] = None
    record_json: Optional[Dict[str, Any]] = None

class ManualTradeRequest(BaseModel):
    side: Literal["long", "short"]
    margin_usd: float = Field(gt=0, allow_inf_nan=False)
    leverage: Literal[1, 5, 10, 20, 100, 200] = 1


@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "agent": "Mortis AI",
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "autotrade_enabled": autonomous_trading_enabled(),
        "trading_mode": "paper",
        "max_leverage": 200,
    }

@app.get("/api/snapshot")
def get_snapshot():
    try:
        price = fetch_current_price("BTCUSDT")
        tf_candles = fetch_multi_timeframe_candles("BTCUSDT", ["4h", "1h", "15m"])
        return {
            "symbol": "BTCUSDT",
            "price": price,
            "candles": [
                {
                    "time": int(row["open_time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                for _, row in tf_candles["15m"].tail(48).iterrows()
            ],
            "timeframes": {
                "4h": compute_timeframe_indicators(tf_candles["4h"]),
                "1h": compute_timeframe_indicators(tf_candles["1h"]),
                "15m": compute_timeframe_indicators(tf_candles["15m"])
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/account")
def get_account():
    try:
        current_price = fetch_current_price("BTCUSDT")
        paper_trader.settle_open_position(current_price)
        state = paper_trader.get_state()
        open_pos = state.get("open_position")
        unrealized_pnl_usd = 0.0
        if open_pos:
            entry = open_pos["entry"]
            size = open_pos["size"]
            gross = (current_price - entry) * size if open_pos["side"] == "long" else (entry - current_price) * size
            estimated_fee = max(
                0.0,
                open_pos["notional"] * ROUND_TRIP_FEE_PCT - open_pos["fees_paid_before"],
            )
            unrealized_pnl_usd = max(gross - estimated_fee, -open_pos["margin"])
            open_pos["unrealized_pnl_usd"] = round(unrealized_pnl_usd, 2)
            open_pos["estimated_round_trip_fee_usd"] = round(estimated_fee, 2)

        equity = state["balance"] + (open_pos["margin"] if open_pos else 0.0) + unrealized_pnl_usd
        total_return_pct = ((equity - state["starting_equity"]) / state["starting_equity"]) * 100

        wins = len([t for t in state["closed_trades"] if t["pnl_usd"] > 0])
        total_closed = len(state["closed_trades"])
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        today_str = time.strftime("%Y-%m-%d", time.gmtime())
        today_pnl = state.get("realized_pnl_by_day", {}).get(today_str, 0.0)

        guard = paper_trader.is_trading_blocked()

        history = [{"label": "Starting balance", "equity": state["starting_equity"], "time": ""}]
        balance_point = state["starting_equity"]
        current_trades = [
            trade for trade in reversed(state["closed_trades"])
            if trade["closed_at"] >= state["reset_at"]
        ]
        for trade in current_trades:
            balance_point += trade["pnl_usd"]
            history.append(
                {
                    "label": f"Trade {trade['id'][-8:]}",
                    "equity": round(balance_point, 2),
                    "time": time.strftime(
                        "%H:%M", time.gmtime(trade["closed_at"] / 1000)
                    ),
                }
            )
        history.append({"label": "Current equity", "equity": round(equity, 2), "time": "Now"})
        peak_equity = state["starting_equity"]
        max_drawdown_pct = 0.0
        for point in history[1:]:
            peak_equity = max(peak_equity, point["equity"])
            if peak_equity > 0:
                max_drawdown_pct = max(
                    max_drawdown_pct,
                    (peak_equity - point["equity"]) / peak_equity * 100,
                )

        return {
            "equity": round(equity, 2),
            "balance": state["balance"],
            "available_balance": state["available_balance"],
            "starting_equity": state["starting_equity"],
            "total_return_pct": round(total_return_pct, 2),
            "unrealized_pnl_usd": round(unrealized_pnl_usd, 2),
            "open_position": open_pos,
            "last_5_closed_trades": state["closed_trades"][:5],
            "equity_history": history,
            "total_trades": total_closed + (1 if open_pos else 0),
            "win_rate": round(win_rate, 1),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "today_realized_pnl_usd": round(today_pnl, 2),
            "is_blocked": guard["blocked"],
            "block_reason": guard.get("reason"),
            "current_btc_price": current_price,
            "trading_mode": "paper",
            "max_leverage": 200,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/account/reset")
def reset_account():
    try:
        new_state = paper_trader.reset_account()
        return {
            "message": "Paper account reset. Existing trade and audit history was retained.",
            "equity": new_state["equity"],
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades")
def list_trades():
    try:
        price = fetch_current_price("BTCUSDT")
        paper_trader.settle_open_position(price)
        return {
            "trades": paper_trader.get_trades(),
            "current_price": price,
            "trading_mode": "paper",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unable to load paper trades: {e}")


@app.post("/api/trades")
def create_manual_trade(req: ManualTradeRequest):
    try:
        price = fetch_current_price("BTCUSDT")
        paper_trader.settle_open_position(price)
        size = (req.margin_usd * req.leverage) / price
        trade = paper_trader.open_position(
            decision_id=None,
            side=req.side,
            entry=price,
            size_btc=size,
            stop_loss=None,
            take_profit=None,
            initial_risk_usd=req.margin_usd,
            leverage=req.leverage,
            source="manual",
        )
        return {"trade": trade, "current_price": price, "trading_mode": "paper"}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unable to execute simulated trade: {e}")


@app.post("/api/trades/close")
def close_manual_trade():
    try:
        price = fetch_current_price("BTCUSDT")
        paper_trader.settle_open_position(price)
        state = paper_trader.get_state()
        if state["open_position"] is None:
            latest = paper_trader.get_trades(limit=1)
            if latest and latest[0]["closed_at"]:
                return {"trade": latest[0], "current_price": price, "trading_mode": "paper"}
            raise HTTPException(status_code=409, detail="There is no open position to close.")
        trade = paper_trader.close_position(price, "manual")
        return {"trade": trade, "current_price": price, "trading_mode": "paper"}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unable to close simulated trade: {e}")


@app.get("/api/ledger")
def get_ledger():
    try:
        return paper_trader.get_ledger()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to verify audit ledger: {e}")


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    try:
        agent = TAAgent()
        res = agent.analyze_and_trade(req.message)
        
        plan = res["trade_plan"]
        rec = res["decision_record"]
        agent_dec = res["agent_decision"]

        reply = "### ⚡ Mortis market read\n"
        reply += f"BTC is at **${res['snapshot']['price']:,.2f}**. "
        reply += f"Setup: **{plan['action'].upper()}** with {plan['raw_confidence']:.0%} model confidence.\n"
        reply += f"**Why:** {agent_dec.get('rationale')}\n"

        if plan['action'] != "no_trade":
            reply += (
                f"**Paper plan:** {plan['leverage']}x leverage · "
                f"{plan['size_btc']} BTC (${plan['notional_usd']:,.2f} exposure) · "
                f"entry ${plan['entry']:,.2f} · stop ${plan['stop_loss']:,.2f} · "
                f"target ${plan['take_profit']:,.2f}. "
                f"Planned loss at the stop, including estimated fees: "
                f"about ${plan['risk_amount_usd']:,.2f}.\n"
            )
        else:
            reply += f"**No entry this time:** {plan.get('reason_if_no_trade')}\n"

        reply += "\nPaper trading only; confidence is not a probability or profit guarantee."
        reply += f"\n🔒 Decision hash: `{rec['decision_hash']}`"

        return {
            "reply": reply,
            "analysis": res
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/verify")
def verify_endpoint(req: VerifyRequest):
    try:
        target_record = req.record_json
        if not target_record and req.decision_id:
            dec_dir = get_decisions_dir()
            json_path = os.path.join(dec_dir, f"{req.decision_id}.json")
            if not os.path.exists(json_path):
                raise HTTPException(status_code=404, detail=f"Decision ID {req.decision_id} not found")
            with open(json_path, "r", encoding="utf-8") as f:
                target_record = json.load(f)

        if not target_record:
            raise HTTPException(status_code=400, detail="Missing decision_id or record_json")

        verification = verify_decision_record(target_record)
        return {
            "decision_id": target_record.get("decision_id"),
            "stored_hash": target_record.get("decision_hash"),
            "computed_hash": verification["computed_hash"],
            "valid": verification["valid"],
            "previous_decision_hash": target_record.get("previous_decision_hash"),
            "timestamp_utc": target_record.get("timestamp_utc"),
            "action": target_record.get("action")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
