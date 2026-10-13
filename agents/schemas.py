from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field

class AgentOutput(BaseModel):
    agent: Literal["ta", "news", "lead"] = "ta"
    direction: Literal[-1, 0, 1]  # -1 short/bearish, 0 neutral, 1 long/bullish
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., max_length=500)
    inputs_digest: Optional[str] = None

class RiskChecks(BaseModel):
    threshold_ok: bool = True
    open_positions_ok: bool = True
    daily_loss_ok: bool = True
    notional_cap_ok: bool = True

class TradeDetails(BaseModel):
    entry: float
    stop_loss: float
    take_profit: float
    size_btc: float
    risk_amount_usd: float
    notional_usd: float
    flags: List[str] = []

class DecisionRecord(BaseModel):
    schema_version: str = "1.0"
    decision_id: str
    timestamp_utc: str
    symbol: str = "BTCUSDT"
    model: str
    prompt_version: str = "v1"
    config_snapshot: Dict[str, Any]
    inputs: Dict[str, Any]
    agent_outputs: List[AgentOutput]
    score: float
    action: Literal["long", "short", "no_trade"]
    reason_if_no_trade: Optional[str] = None
    trade: Optional[TradeDetails] = None
    risk_checks: RiskChecks
    previous_decision_hash: Optional[str] = None
    decision_hash: Optional[str] = None
