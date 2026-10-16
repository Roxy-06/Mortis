import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from chain.logger import canonicalize_json, compute_decision_hash
from tools.market_data import fetch_current_price
from engine.risk import LEVERAGE_OPTIONS

STARTING_EQUITY = 10000.0
ROUND_TRIP_FEE_PCT = 0.001
DAILY_LOSS_LIMIT_PCT = 0.03


class PaperTrader:
    """SQLite-backed simulated account with an append-only SHA-256 event chain."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.getenv(
                "MORTIS_DATA_DIR",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
            )
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "mortis.db")
        self.legacy_file_path = os.path.join(data_dir, "paper-account.json")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL NOT NULL,
                    starting_equity REAL NOT NULL,
                    reset_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    decision_id TEXT,
                    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
                    entry REAL NOT NULL,
                    size REAL NOT NULL,
                    notional REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    margin REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    opened_at INTEGER NOT NULL,
                    closed_at INTEGER,
                    exit_price REAL,
                    exit_reason TEXT,
                    pnl_gross REAL,
                    fee_usd REAL,
                    pnl_usd REAL,
                    initial_risk_usd REAL NOT NULL DEFAULT 0,
                    fees_paid_before REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    rationale TEXT,
                    status TEXT NOT NULL CHECK (status IN ('open', 'closed'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_trade
                    ON trades(status) WHERE status = 'open';
                CREATE INDEX IF NOT EXISTS trades_opened_at
                    ON trades(opened_at DESC);
                CREATE TABLE IF NOT EXISTS daily_pnl (
                    utc_date TEXT PRIMARY KEY,
                    pnl_usd REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ledger (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    trade_id TEXT,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    record_hash TEXT NOT NULL UNIQUE
                );
                """
            )
            account = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
            if account is None:
                self._migrate_legacy_account(conn)

    def _migrate_legacy_account(self, conn: sqlite3.Connection) -> None:
        had_legacy_file = os.path.exists(self.legacy_file_path)
        state: Dict[str, Any] = {
            "equity": STARTING_EQUITY,
            "starting_equity": STARTING_EQUITY,
            "open_position": None,
            "closed_trades": [],
            "realized_pnl_by_day": {},
        }
        if os.path.exists(self.legacy_file_path):
            with open(self.legacy_file_path, "r", encoding="utf-8") as legacy_file:
                state = json.load(legacy_file)

        starting_equity = float(state.get("starting_equity", STARTING_EQUITY))
        balance = float(state.get("equity", starting_equity))
        conn.execute(
            "INSERT INTO account (id, balance, starting_equity) VALUES (1, ?, ?)",
            (balance, starting_equity),
        )
        for trade in state.get("closed_trades", []):
            entry = float(trade["entry"])
            size = float(trade["size"])
            opened_at = int(trade.get("opened_at", int(time.time() * 1000)))
            closed_at = int(trade.get("closed_at", opened_at))
            conn.execute(
                """
                INSERT OR IGNORE INTO trades (
                    id, decision_id, side, entry, size, notional, leverage, margin,
                    opened_at, closed_at, exit_price, exit_reason, pnl_gross, fee_usd,
                    pnl_usd, source, status
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'ai', 'closed')
                """,
                (
                    str(trade.get("id") or f"legacy_{uuid.uuid4().hex}"),
                    trade.get("decision_id"),
                    trade.get("side", "long"),
                    entry,
                    size,
                    entry * size,
                    entry * size,
                    opened_at,
                    closed_at,
                    float(trade.get("exit", entry)),
                    trade.get("exit_reason", "legacy"),
                    float(trade.get("pnl_usd", 0)),
                    float(trade.get("fees_paid_total", 0)),
                    float(trade.get("pnl_usd", 0)),
                ),
            )
        legacy_position = state.get("open_position")
        if legacy_position:
            entry = float(legacy_position["entry"])
            size = float(legacy_position["size"])
            notional = entry * size
            margin = notional
            balance -= margin
            conn.execute(
                """
                INSERT OR IGNORE INTO trades (
                    id, decision_id, side, entry, size, notional, leverage, margin,
                    stop_loss, take_profit, opened_at, initial_risk_usd,
                    fees_paid_before, source, status
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'ai', 'open')
                """,
                (
                    legacy_position.get("id", f"legacy_{uuid.uuid4().hex}"),
                    legacy_position.get("decision_id"),
                    legacy_position["side"],
                    entry,
                    size,
                    notional,
                    margin,
                    legacy_position.get("stop_loss"),
                    legacy_position.get("take_profit"),
                    int(legacy_position.get("opened_at", int(time.time() * 1000))),
                    float(legacy_position.get("initial_risk_usd", 0)),
                    float(legacy_position.get("fees_paid_open", 0)),
                ),
            )
            conn.execute("UPDATE account SET balance = ? WHERE id = 1", (balance,))

        for utc_date, pnl in state.get("realized_pnl_by_day", {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO daily_pnl (utc_date, pnl_usd) VALUES (?, ?)",
                (utc_date, float(pnl)),
            )
        self._append_ledger(
            conn,
            "legacy_import" if had_legacy_file else "account_initialized",
            None,
            {
                "starting_equity": starting_equity,
                "migrated_closed_trades": len(state.get("closed_trades", [])),
                "migrated_open_position": bool(legacy_position),
            },
        )

    def _verify_ledger(self, conn: sqlite3.Connection) -> bool:
        previous_hash = None
        rows = conn.execute("SELECT * FROM ledger ORDER BY sequence").fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            record = {
                "event_id": row["event_id"],
                "timestamp_utc": row["timestamp_utc"],
                "event_type": row["event_type"],
                "trade_id": row["trade_id"],
                "payload": payload,
                "previous_hash": row["previous_hash"],
            }
            if row["previous_hash"] != previous_hash:
                return False
            if compute_decision_hash(record) != row["record_hash"]:
                return False
            previous_hash = row["record_hash"]
        return True

    def _append_ledger(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        trade_id: Optional[str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._verify_ledger(conn):
            raise RuntimeError("Audit ledger verification failed; refusing to append an event.")
        last = conn.execute(
            "SELECT record_hash FROM ledger ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        event = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "trade_id": trade_id,
            "payload": payload,
            "previous_hash": last["record_hash"] if last else None,
        }
        record_hash = compute_decision_hash(event)
        conn.execute(
            """
            INSERT INTO ledger (
                event_id, timestamp_utc, event_type, trade_id, payload_json,
                previous_hash, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["timestamp_utc"],
                event["event_type"],
                event["trade_id"],
                canonicalize_json(payload),
                event["previous_hash"],
                record_hash,
            ),
        )
        return {**event, "record_hash": record_hash}

    def _current_utc_date(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _get_open_trade(self, conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM trades WHERE status = 'open' LIMIT 1"
        ).fetchone()

    def _close_trade(
        self,
        conn: sqlite3.Connection,
        trade: sqlite3.Row,
        exit_price: float,
        exit_reason: str,
    ) -> Dict[str, Any]:
        exit_price = float(exit_price)
        gross_pnl = (
            (exit_price - trade["entry"]) * trade["size"]
            if trade["side"] == "long"
            else (trade["entry"] - exit_price) * trade["size"]
        )
        target_fee = trade["notional"] * ROUND_TRIP_FEE_PCT
        fee_due = max(0.0, target_fee - trade["fees_paid_before"])
        fee_total = trade["fees_paid_before"] + fee_due
        account_pnl = max(gross_pnl - fee_due, -trade["margin"])
        net_pnl = max(gross_pnl - fee_total, -trade["margin"])
        closed_at = int(time.time() * 1000)
        duration_seconds = max(0, (closed_at - trade["opened_at"]) // 1000)
        conn.execute(
            """
            UPDATE account SET balance = balance + ? WHERE id = 1
            """,
            (trade["margin"] + account_pnl,),
        )
        conn.execute(
            """
            UPDATE trades SET status = 'closed', closed_at = ?, exit_price = ?,
                exit_reason = ?, pnl_gross = ?, fee_usd = ?, pnl_usd = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                closed_at,
                exit_price,
                exit_reason,
                gross_pnl,
                fee_total,
                net_pnl,
                trade["id"],
            ),
        )
        utc_date = self._current_utc_date()
        conn.execute(
            """
            INSERT INTO daily_pnl (utc_date, pnl_usd) VALUES (?, ?)
            ON CONFLICT(utc_date) DO UPDATE SET pnl_usd = pnl_usd + excluded.pnl_usd
            """,
            (utc_date, net_pnl),
        )
        updated = conn.execute("SELECT * FROM trades WHERE id = ?", (trade["id"],)).fetchone()
        trade_data = self._trade_to_dict(updated)
        self._append_ledger(
            conn,
            "trade_closed",
            trade["id"],
            {
                "side": trade["side"],
                "entry": trade["entry"],
                "exit": exit_price,
                "size_btc": trade["size"],
                "notional_usd": trade["notional"],
                "leverage": trade["leverage"],
                "gross_pnl_usd": round(gross_pnl, 2),
                "fee_usd": round(trade["fees_paid_before"] + fee_due, 2),
                "pnl_usd": round(net_pnl, 2),
                "duration_seconds": duration_seconds,
                "exit_reason": exit_reason,
                "source": trade["source"],
                "decision_id": trade["decision_id"],
            },
        )
        return trade_data

    @staticmethod
    def _trade_to_dict(trade: sqlite3.Row) -> Dict[str, Any]:
        result = dict(trade)
        result["duration_seconds"] = (
            max(0, (result["closed_at"] - result["opened_at"]) // 1000)
            if result["closed_at"] is not None
            else None
        )
        result["entry"] = round(result["entry"], 2)
        result["size"] = round(result["size"], 8)
        result["notional"] = round(result["notional"], 2)
        result["margin"] = round(result["margin"], 2)
        if result["pnl_usd"] is not None:
            result["pnl_usd"] = round(result["pnl_usd"], 2)
        if result["fee_usd"] is not None:
            result["fee_usd"] = round(result["fee_usd"], 2)
        return result

    def settle_open_position(self, current_price: Optional[float] = None) -> Dict[str, Any]:
        price = float(current_price if current_price is not None else fetch_current_price("BTCUSDT"))
        if price <= 0:
            raise ValueError("Settlement price must be greater than zero.")
        with self._connect() as conn:
            trade = self._get_open_trade(conn)
            if trade is None:
                return self.get_state()
            reason = None
            exit_price = price
            if trade["side"] == "long":
                if trade["stop_loss"] is not None and price <= trade["stop_loss"]:
                    reason = "SL"
                elif trade["take_profit"] is not None and price >= trade["take_profit"]:
                    reason = "TP"
                    exit_price = trade["take_profit"]
            else:
                if trade["stop_loss"] is not None and price >= trade["stop_loss"]:
                    reason = "SL"
                elif trade["take_profit"] is not None and price <= trade["take_profit"]:
                    reason = "TP"
                    exit_price = trade["take_profit"]
            unrealized_gross = (
                (price - trade["entry"]) * trade["size"]
                if trade["side"] == "long"
                else (trade["entry"] - price) * trade["size"]
            )
            if unrealized_gross <= -trade["margin"]:
                reason = "LIQUIDATION"
                exit_price = price
            if reason:
                conn.execute("BEGIN IMMEDIATE")
                trade = self._get_open_trade(conn)
                if trade is not None:
                    self._close_trade(conn, trade, exit_price, reason)
        return self.get_state()

    def is_trading_blocked(self) -> Dict[str, Any]:
        with self._connect() as conn:
            if self._get_open_trade(conn):
                return {"blocked": True, "reason": "An open position already exists."}
            today = self._current_utc_date()
            daily = conn.execute(
                "SELECT pnl_usd FROM daily_pnl WHERE utc_date = ?", (today,)
            ).fetchone()
            daily_pnl = float(daily["pnl_usd"]) if daily else 0.0
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            daily_limit = account["starting_equity"] * DAILY_LOSS_LIMIT_PCT
            if daily_pnl <= -daily_limit:
                return {
                    "blocked": True,
                    "reason": f"Daily loss limit reached ({daily_pnl:.2f} <= -{daily_limit:.2f}).",
                }
            return {"blocked": False}

    def open_position(
        self,
        decision_id: Optional[str],
        side: str,
        entry: float,
        size_btc: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        initial_risk_usd: float,
        leverage: int = 1,
        source: str = "ai",
        rationale: Optional[str] = None,
    ) -> Dict[str, Any]:
        if side not in ("long", "short"):
            raise ValueError("Side must be 'long' or 'short'.")
        if int(leverage) not in LEVERAGE_OPTIONS:
            raise ValueError(
                "Leverage must be one of 1x, 5x, 10x, 20x, 100x, or 200x."
            )
        if entry <= 0 or size_btc <= 0:
            raise ValueError("Entry price and BTC size must be greater than zero.")
        if side == "long" and (
            (stop_loss is not None and stop_loss >= entry)
            or (take_profit is not None and take_profit <= entry)
        ):
            raise ValueError("Long-position stop-loss and take-profit must bracket the entry.")
        if side == "short" and (
            (stop_loss is not None and stop_loss <= entry)
            or (take_profit is not None and take_profit >= entry)
        ):
            raise ValueError("Short-position stop-loss and take-profit must bracket the entry.")

        notional = float(entry) * float(size_btc)
        margin = notional / int(leverage)
        trade_id = f"trade_{uuid.uuid4().hex}"
        opened_at = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._get_open_trade(conn):
                raise RuntimeError("An open position already exists.")
            today = self._current_utc_date()
            daily = conn.execute(
                "SELECT pnl_usd FROM daily_pnl WHERE utc_date = ?", (today,)
            ).fetchone()
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            daily_pnl = float(daily["pnl_usd"]) if daily else 0.0
            daily_limit = account["starting_equity"] * DAILY_LOSS_LIMIT_PCT
            if daily_pnl <= -daily_limit:
                raise RuntimeError(
                    f"Daily loss limit reached ({daily_pnl:.2f} <= -{daily_limit:.2f})."
                )
            if not self._verify_ledger(conn):
                raise RuntimeError("Audit ledger verification failed; refusing to trade.")
            if margin > account["balance"]:
                raise RuntimeError(
                    f"Insufficient available paper balance for margin ({margin:.2f} required)."
                )
            conn.execute(
                "UPDATE account SET balance = balance - ? WHERE id = 1", (margin,)
            )
            conn.execute(
                """
                INSERT INTO trades (
                    id, decision_id, side, entry, size, notional, leverage, margin,
                    stop_loss, take_profit, opened_at, initial_risk_usd,
                    source, rationale, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    trade_id,
                    decision_id,
                    side,
                    float(entry),
                    float(size_btc),
                    notional,
                    int(leverage),
                    margin,
                    stop_loss,
                    take_profit,
                    opened_at,
                    float(initial_risk_usd),
                    source,
                    rationale,
                ),
            )
            self._append_ledger(
                conn,
                "trade_opened",
                trade_id,
                {
                    "side": side,
                    "entry": round(float(entry), 2),
                    "size_btc": round(float(size_btc), 8),
                    "notional_usd": round(notional, 2),
                    "margin_usd": round(margin, 2),
                    "leverage": int(leverage),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "source": source,
                    "decision_id": decision_id,
                    "rationale": rationale,
                },
            )
            trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            return self._trade_to_dict(trade)

    def close_position(
        self, exit_price: float, exit_reason: str = "manual"
    ) -> Dict[str, Any]:
        if exit_price <= 0:
            raise ValueError("Exit price must be greater than zero.")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            trade = self._get_open_trade(conn)
            if trade is None:
                raise RuntimeError("There is no open position to close.")
            if not self._verify_ledger(conn):
                raise RuntimeError("Audit ledger verification failed; refusing to close.")
            return self._close_trade(conn, trade, float(exit_price), exit_reason)

    def get_state(self) -> Dict[str, Any]:
        with self._connect() as conn:
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            open_trade = self._get_open_trade(conn)
            closed = conn.execute(
                "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_at DESC"
            ).fetchall()
            daily = conn.execute("SELECT * FROM daily_pnl").fetchall()
            margin = float(open_trade["margin"]) if open_trade else 0.0
            return {
                "equity": round(float(account["balance"]) + margin, 2),
                "balance": round(float(account["balance"]), 2),
                "starting_equity": float(account["starting_equity"]),
                "reset_at": int(account["reset_at"]),
                "available_balance": round(float(account["balance"]), 2),
                "open_position": self._trade_to_dict(open_trade) if open_trade else None,
                "closed_trades": [self._trade_to_dict(trade) for trade in closed],
                "realized_pnl_by_day": {row["utc_date"]: row["pnl_usd"] for row in daily},
            }

    def get_trades(self, limit: int = 100) -> list[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._trade_to_dict(row) for row in rows]

    def get_ledger(self, limit: int = 100) -> Dict[str, Any]:
        with self._connect() as conn:
            is_valid = self._verify_ledger(conn)
            rows = conn.execute(
                "SELECT * FROM ledger ORDER BY sequence DESC LIMIT ?", (limit,)
            ).fetchall()
            records = []
            for row in reversed(rows):
                records.append(
                    {
                        "sequence": row["sequence"],
                        "event_id": row["event_id"],
                        "timestamp_utc": row["timestamp_utc"],
                        "event_type": row["event_type"],
                        "trade_id": row["trade_id"],
                        "payload": json.loads(row["payload_json"]),
                        "previous_hash": row["previous_hash"],
                        "record_hash": row["record_hash"],
                    }
                )
            return {"valid": is_valid, "records": records}

    def reset_account(self) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._get_open_trade(conn):
                raise RuntimeError("Close the open position before resetting the account.")
            if not self._verify_ledger(conn):
                raise RuntimeError("Audit ledger verification failed; refusing to reset.")
            account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            conn.execute(
                "UPDATE account SET balance = starting_equity, reset_at = ? WHERE id = 1",
                (int(time.time() * 1000),),
            )
            conn.execute("DELETE FROM daily_pnl")
            self._append_ledger(
                conn,
                "account_reset",
                None,
                {"starting_equity": account["starting_equity"]},
            )
        return self.get_state()
