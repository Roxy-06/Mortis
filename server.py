import os
import json
import logging
import time
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

from agents.ta_agent import TAAgent
from engine.paper_trader import PaperTrader
from chain.logger import verify_decision_record, get_decisions_dir
from tools.market_data import fetch_multi_timeframe_candles, fetch_current_price
from tools.indicators import compute_timeframe_indicators
from engine.loop import run_loop
from engine.risk import load_config


def autonomous_trading_enabled() -> bool:
    return os.getenv("MORTIS_AUTOTRADE_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()
    worker = None
    try:
        paper_trader.catch_up()
    except Exception:
        logging.exception("Paper-trading startup catch-up failed")
        paper_trader.set_catchup_error("Startup catch-up failed; see backend logs.")
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
    paper_trader.record_heartbeat()


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
    history: Optional[List[Dict[str, Any]]] = None
    execute: bool = False

class VerifyRequest(BaseModel):
    decision_id: Optional[str] = None
    record_json: Optional[Dict[str, Any]] = None

class ManualTradeRequest(BaseModel):
    side: Literal["long", "short"]
    margin_usd: float = Field(gt=0, allow_inf_nan=False)
    leverage: int = Field(default=1, ge=1)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@app.get("/api/health")
def health_check():
    config = load_config()
    active_version = config.get("model", {}).get("active_version")
    return {
        "status": "online",
        "agent": "Mortis paper-trading engine",
        "model": active_version or "deterministic_rule_fallback",
        "model_version": active_version,
        "autotrade_enabled": autonomous_trading_enabled(),
        "trading_mode": "paper",
        "max_leverage": config.get("risk", {}).get("max_leverage", 5),
        "memory_mode": config.get("memory", {}).get("mode", "advisory"),
    }

@app.get("/api/snapshot")
def get_snapshot():
    try:
        config = load_config()
        symbol = config.get("symbol", "BTCUSDT")
        timeframes = config.get("timeframes", ["4h", "1h", "15m"])
        price = fetch_current_price(symbol)
        tf_candles = fetch_multi_timeframe_candles(
            symbol,
            timeframes,
            limit=int(config.get("candles_per_timeframe", 300)),
        )
        return {
            "symbol": symbol,
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
                timeframe: compute_timeframe_indicators(candles)
                for timeframe, candles in tf_candles.items()
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/account")
def get_account():
    try:
        symbol = load_config().get("symbol", "BTCUSDT")
        current_price = fetch_current_price(symbol)
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
                open_pos["notional"] * paper_trader.round_trip_fee_pct
                - open_pos["fees_paid_before"],
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

        history = [{
            "label": "Starting balance",
            "equity": state["starting_equity"],
            "time": "",
        }]
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
                        "%Y-%m-%d %H:%M:%S",
                        time.gmtime(trade["closed_at"] / 1000),
                    ),
                }
            )
        history.append({
            "label": "Current equity",
            "equity": round(equity, 2),
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        })
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
            "max_leverage": load_config().get("risk", {}).get("max_leverage", 5),
            "catchup": paper_trader.get_memory_stats().get("last_catchup_summary", {}),
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


@app.post("/api/account/reenable")
def reenable_trading():
    try:
        state = paper_trader.reenable_trading()
        return {
            "message": "Trading re-enabled. Drawdown baseline reset to current paper equity.",
            "equity": state["equity"],
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades")
def list_trades(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[Literal["open", "closed"]] = None,
    side: Optional[Literal["long", "short"]] = None,
    source: Optional[Literal["ai", "manual"]] = None,
):
    try:
        price = fetch_current_price(load_config().get("symbol", "BTCUSDT"))
        paper_trader.settle_open_position(price)
        return {
            "trades": paper_trader.get_trades(
                limit=limit, offset=offset, status=status, side=side, source=source
            ),
            "total": paper_trader.get_trade_count(status=status, side=side, source=source),
            "offset": offset,
            "limit": limit,
            "current_price": price,
            "trading_mode": "paper",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unable to load paper trades: {e}")


@app.post("/api/trades")
def create_manual_trade(req: ManualTradeRequest):
    try:
        price = fetch_current_price(load_config().get("symbol", "BTCUSDT"))
        paper_trader.settle_open_position(price)
        size = (req.margin_usd * req.leverage) / price
        trade = paper_trader.open_position(
            decision_id=None,
            side=req.side,
            entry=price,
            size_btc=size,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            initial_risk_usd=req.margin_usd,
            leverage=req.leverage,
            source="manual",
        )
        return {"trade": trade, "current_price": price, "trading_mode": "paper"}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Unable to execute simulated trade: {e}")


@app.get("/api/trades/{trade_id}")
def get_trade(trade_id: str):
    trade = paper_trader.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return {"trade": trade, "trading_mode": "paper"}


@app.get("/api/decisions")
def list_decisions(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return paper_trader.get_decisions(limit=limit, offset=offset)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Unable to load decisions: {error}")


@app.get("/api/decisions/{decision_id}")
def get_decision(decision_id: str):
    decision = paper_trader.get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found.")
    return {"decision": decision}


@app.get("/api/memory/episodes")
def get_memory_episodes(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    outcome: Optional[Literal["win", "loss", "timeout", "unresolved"]] = None,
    side: Optional[Literal["long", "short"]] = None,
    include_counterfactual: bool = True,
):
    try:
        return paper_trader.get_memory_episodes(
            limit, offset, outcome, side, include_counterfactual
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Unable to load memory episodes: {error}")


@app.get("/api/memory/stats")
def get_memory_stats():
    return paper_trader.get_memory_stats()


@app.post("/api/trades/close")
def close_manual_trade():
    try:
        price = fetch_current_price(load_config().get("symbol", "BTCUSDT"))
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
        agent = TAAgent(paper_trader=paper_trader)
        res = agent.execute(req.message) if req.execute else agent.analyze(req.message)

        plan = res["trade_plan"]
        rec = res["decision_record"]
        agent_dec = res["agent_decision"]
        calibrated = bool(agent_dec.get("calibrated"))
        score_label = (
            "calibrated model estimate"
            if calibrated
            else "uncalibrated rule score"
        )

        reply = "### ⚡ Mortis market read\n"
        reply += f"BTC is at **${res['snapshot']['price']:,.2f}**. "
        reply += (
            f"Setup: **{plan['action'].upper()}** with "
            f"{plan['raw_confidence']:.0%} {score_label}.\n"
        )
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

        if calibrated:
            reply += (
                "\nPaper trading only; the calibrated estimate is not a profit "
                "guarantee."
            )
        else:
            reply += (
                "\nPaper trading only; the rule score is not a calibrated "
                "probability or profit guarantee."
            )
        if req.execute and rec:
            reply += f"\n🔒 Decision hash: `{rec['decision_hash']}`"
            reply += "\nThe requested simulated paper trade was executed."
        elif not req.execute:
            reply += "\nRead-only analysis; no decision was persisted and no trade was opened."

        return {
            "reply": reply,
            "analysis": res
        }
    except (ValueError, RuntimeError) as e:
        if req.execute:
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/learning")
def get_learning_samples(limit: int = Query(default=100, ge=1, le=1000)):
    try:
        samples = paper_trader.get_training_samples(limit)
        summary = paper_trader.get_learning_summary()
        resolved = sum(1 for sample in samples if sample["outcome_resolved"])
        return {
            "samples": samples,
            "count": len(samples),
            "resolved_count": resolved,
            "summary": summary,
            "model_version": load_config().get("model", {}).get("active_version"),
            "trading_mode": "paper",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to load learning records: {e}")

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
