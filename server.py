import os
import json
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

from agents.ta_agent import TAAgent
from engine.paper_trader import PaperTrader
from chain.logger import verify_decision_record, get_decisions_dir
from tools.market_data import fetch_multi_timeframe_candles, fetch_current_price
from tools.indicators import compute_timeframe_indicators

app = FastAPI(title="Mortis Python Engine API", version="1.0.0")

# Enable CORS for React / Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

@app.get("/api/health")
def health_check():
    return {"status": "online", "agent": "Mortis AI", "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash")}

@app.get("/api/snapshot")
def get_snapshot():
    try:
        price = fetch_current_price("BTCUSDT")
        tf_candles = fetch_multi_timeframe_candles("BTCUSDT", ["4h", "1h", "15m"])
        return {
            "symbol": "BTCUSDT",
            "price": price,
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
        paper_trader.settle_open_position()
        state = paper_trader.get_state()

        total_return_pct = ((state["equity"] - state["starting_equity"]) / state["starting_equity"]) * 100
        
        unrealized_pnl_usd = 0.0
        open_pos = state.get("open_position")
        if open_pos:
            entry = open_pos["entry"]
            size = open_pos["size"]
            gross = (current_price - entry) * size if open_pos["side"] == "long" else (entry - current_price) * size
            unrealized_pnl_usd = gross - open_pos["fees_paid_open"]

        wins = len([t for t in state["closed_trades"] if t["pnl_usd"] > 0])
        total_closed = len(state["closed_trades"])
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        today_str = time.strftime("%Y-%m-%d", time.gmtime())
        today_pnl = state.get("realized_pnl_by_day", {}).get(today_str, 0.0)

        guard = paper_trader.is_trading_blocked()

        return {
            "equity": round(state["equity"], 2),
            "starting_equity": state["starting_equity"],
            "total_return_pct": round(total_return_pct, 2),
            "unrealized_pnl_usd": round(unrealized_pnl_usd, 2),
            "open_position": open_pos,
            "last_5_closed_trades": state["closed_trades"][:5],
            "total_trades": total_closed,
            "win_rate": round(win_rate, 1),
            "today_realized_pnl_usd": round(today_pnl, 2),
            "is_blocked": guard["blocked"],
            "block_reason": guard.get("reason"),
            "current_btc_price": current_price
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/account/reset")
def reset_account():
    try:
        new_state = paper_trader.reset_account()
        return {"message": "Account successfully reset to $10,000 USD equity.", "equity": new_state["equity"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    try:
        agent = TAAgent()
        res = agent.analyze_and_trade()
        
        plan = res["trade_plan"]
        rec = res["decision_record"]
        agent_dec = res["agent_decision"]

        reply = f"### ⚡ Mortis Strategy Analysis Complete\n"
        reply += f"• **Symbol Price**: `${res['snapshot']['price']:,.2f}`\n"
        reply += f"• **Action**: `{plan['action'].upper()}` (Confidence: `{plan['raw_confidence']:.2f}`)\n"
        reply += f"• **Rationale**: {agent_dec.get('rationale')}\n"

        if plan['action'] != "no_trade":
            reply += f"• **Trade Plan**: Entry: `${plan['entry']}` | Stop Loss: `${plan['stop_loss']}` | Take Profit: `${plan['take_profit']}` | Size: `{plan['size_btc']} BTC`\n"
        else:
            reply += f"• **Note**: {plan.get('reason_if_no_trade')}\n"

        reply += f"\n🔒 **SHA-256 Decision Hash**: `{rec['decision_hash']}`"

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
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
