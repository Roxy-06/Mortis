import hashlib
import json
import logging
import math
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

from chain.logger import canonicalize_json, compute_decision_hash
from tools.market_data import (
    fetch_closed_candles,
    fetch_current_price,
    fetch_intrabar_candles,
)
from engine.risk import load_config, risk_config
from engine.memory import memory_gate, retrieve_similar
from research.features import FEATURE_SCHEMA_VERSION
from tools.indicators import calculate_atr

STARTING_EQUITY = 10000.0
ROUND_TRIP_FEE_PCT = 0.001
DAILY_LOSS_LIMIT_PCT = 0.03
SCHEMA_VERSION = 2


class PaperTrader:
    """SQLite-backed simulated account with an append-only SHA-256 event chain."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.getenv(
                "MORTIS_DATA_DIR",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
            )
        os.makedirs(data_dir, exist_ok=True)
        self.full_config = load_config()
        self.config = risk_config(self.full_config)
        self.monitoring_config = self.full_config.get("monitoring", {})
        self.starting_equity = float(self.full_config.get("starting_equity_usd", STARTING_EQUITY))
        self.max_leverage = int(self.config.get("max_leverage", 5))
        self.round_trip_fee_pct = float(
            self.config.get("fee_pct_round_trip", ROUND_TRIP_FEE_PCT)
        )
        self.db_path = os.path.join(data_dir, "mortis.db")
        self.data_dir = data_dir
        self.backup_dir = os.path.join(data_dir, "backups")
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
            database_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if database_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Paper account database schema {database_version} is newer "
                    f"than this application supports ({SCHEMA_VERSION})."
                )
            migration_table = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if not migration_table or database_version < SCHEMA_VERSION:
                self._backup_database(conn)
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
                CREATE TABLE IF NOT EXISTS trading_controls (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    peak_equity REAL NOT NULL,
                    drawdown_paused INTEGER NOT NULL DEFAULT 0,
                    last_settlement_at_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS training_samples (
                    decision_id TEXT PRIMARY KEY,
                    created_at_ms INTEGER NOT NULL,
                    features_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    best_bid REAL,
                    best_ask REAL,
                    quote_status TEXT NOT NULL DEFAULT 'not_collected',
                    outcome_resolved INTEGER NOT NULL DEFAULT 0,
                    outcome_label INTEGER,
                    realized_net_r REAL,
                    pnl_usd REAL,
                    realized_slippage_bps REAL,
                    mistake TEXT
                );
                """
            )
            self._migrate_schema(conn)
            account = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
            if account is None:
                self._migrate_legacy_account(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO trading_controls (id, peak_equity)
                SELECT 1, starting_equity FROM account WHERE id = 1
                """
            )
            restored = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(outcome != 'unresolved') AS resolved,
                       SUM(outcome = 'unresolved') AS unresolved
                FROM memory_episodes
                """
            ).fetchone()
            restored_at = int(time.time() * 1000)
            self._set_system_state(conn, "memory_restored_at_ms", restored_at)
            restore_summary = {
                "episodes_total": int(restored["total"] or 0),
                "resolved": int(restored["resolved"] or 0),
                "unresolved": int(restored["unresolved"] or 0),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "last_catchup_at_ms": self._get_system_state(
                    conn, "last_catchup_at_ms"
                ),
            }
            self._set_system_state(conn, "memory_restore_summary", restore_summary)
            stats_count = conn.execute(
                "SELECT COUNT(*) FROM memory_feature_stats"
            ).fetchone()[0]
            if restored["total"] and not stats_count:
                self._refresh_memory_feature_stats(conn, FEATURE_SCHEMA_VERSION)
            logging.info(
                "Memory restored: %s episodes (%s resolved, %s unresolved), "
                "schema v%s, last catch-up at %s",
                int(restored["total"] or 0),
                int(restored["resolved"] or 0),
                int(restored["unresolved"] or 0),
                FEATURE_SCHEMA_VERSION,
                self._get_system_state(conn, "last_catchup_at_ms"),
            )

    def _backup_database(self, source: sqlite3.Connection) -> Optional[str]:
        if not os.path.isfile(self.db_path) or os.path.getsize(self.db_path) == 0:
            return None
        os.makedirs(self.backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = os.path.join(
            self.backup_dir, f"mortis_{timestamp}.db"
        )
        suffix = 1
        while os.path.exists(destination):
            destination = os.path.join(
                self.backup_dir, f"mortis_{timestamp}_{suffix}.db"
            )
            suffix += 1
        with sqlite3.connect(destination) as backup:
            source.backup(backup)
        logging.info("Created paper-account migration backup: %s", destination)
        return destination

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at_ms INTEGER NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        if conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 1"
        ).fetchone() is None:
            conn.execute(
                """
                INSERT INTO schema_migrations (version, applied_at_ms, description)
                VALUES (1, ?, 'Existing SQLite paper-account schema')
                """,
                (int(time.time() * 1000),),
            )
        additions = {
            "trading_controls": {
                "last_settlement_at_ms": "INTEGER NOT NULL DEFAULT 0",
            },
            "training_samples": {
                "quote_status": "TEXT NOT NULL DEFAULT 'not_collected'",
                "realized_slippage_bps": "REAL",
                "feature_schema_version": "INTEGER NOT NULL DEFAULT 1",
                "indicator_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "unresolved_reason": "TEXT",
            },
            "trades": {
                "liquidation_price": "REAL",
                "atr_at_entry": "REAL",
                "sl_atr_mult": "REAL",
                "tp_atr_mult": "REAL",
                "risk_amount": "REAL",
                "reward_to_risk": "REAL",
                "decision_source": "TEXT",
                "confidence": "REAL",
                "feature_vector_json": "TEXT NOT NULL DEFAULT '{}'",
                "feature_schema_version": "INTEGER NOT NULL DEFAULT 1",
                "levels_backfilled": "INTEGER NOT NULL DEFAULT 0",
                "mae_r": "REAL NOT NULL DEFAULT 0",
                "mfe_r": "REAL NOT NULL DEFAULT 0",
                "bars_held": "INTEGER NOT NULL DEFAULT 0",
                "last_candle_open_ms": "INTEGER",
                "funding_usd": "REAL NOT NULL DEFAULT 0",
                "r_multiple": "REAL",
                "resolution_source": "TEXT",
            },
        }
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        for table, columns in additions.items():
            existing = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )

        conn.execute(
            """
            UPDATE trades
            SET liquidation_price = CASE side
                WHEN 'long' THEN entry - margin / size
                ELSE entry + margin / size
            END,
            risk_amount = ABS(entry - COALESCE(stop_loss, entry)) * size,
            reward_to_risk = CASE
                WHEN stop_loss IS NOT NULL AND take_profit IS NOT NULL
                     AND ABS(entry - stop_loss) > 0
                THEN ABS(take_profit - entry) / ABS(entry - stop_loss)
                ELSE NULL
            END
            WHERE status = 'open' AND liquidation_price IS NULL
            """
        )
        conn.execute(
            """
            UPDATE trades
            SET risk_amount = ABS(entry - stop_loss) * size
            WHERE risk_amount IS NULL AND stop_loss IS NOT NULL
            """
        )
        conn.execute(
            """
            UPDATE trades
            SET r_multiple = pnl_usd / risk_amount
            WHERE status = 'closed' AND r_multiple IS NULL
              AND pnl_usd IS NOT NULL AND risk_amount > 0
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                created_at_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                decision TEXT NOT NULL,
                direction TEXT NOT NULL,
                source TEXT NOT NULL,
                model_version TEXT,
                confidence REAL,
                calibrated_probability REAL,
                features_json TEXT NOT NULL,
                feature_schema_version INTEGER NOT NULL,
                indicator_snapshot_json TEXT NOT NULL,
                proposed_stop REAL,
                proposed_target REAL,
                rejection_reason TEXT,
                config_hash TEXT NOT NULL,
                trade_plan_json TEXT NOT NULL,
                memory_json TEXT NOT NULL DEFAULT '{}',
                decision_hash TEXT,
                previous_decision_hash TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS decisions_created_at "
            "ON decisions(created_at_ms DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                decision_id TEXT,
                event_type TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                details_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS trade_events_trade_id "
            "ON trade_events(trade_id, created_at_ms)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_episodes (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                position_id TEXT,
                created_at_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('long', 'short')),
                feature_vector_json TEXT NOT NULL,
                feature_schema_version INTEGER NOT NULL,
                trend_bucket TEXT,
                volatility_bucket TEXT,
                entry REAL,
                stop_loss REAL,
                take_profit REAL,
                outcome TEXT NOT NULL DEFAULT 'unresolved'
                    CHECK (outcome IN ('win', 'loss', 'timeout', 'unresolved')),
                r_multiple REAL,
                exit_reason TEXT,
                mae_r REAL,
                mfe_r REAL,
                bars_held INTEGER NOT NULL DEFAULT 0,
                resolution_source TEXT,
                model_version TEXT,
                lesson_text TEXT,
                lesson_source TEXT CHECK (lesson_source IN ('rule', 'llm')),
                counterfactual INTEGER NOT NULL DEFAULT 0,
                unresolved_reason TEXT,
                UNIQUE(decision_id, side)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS memory_episodes_lookup "
            "ON memory_episodes(side, feature_schema_version, created_at_ms)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_feature_stats (
                feature_schema_version INTEGER NOT NULL,
                feature_name TEXT NOT NULL,
                mean REAL NOT NULL,
                stddev REAL NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY(feature_schema_version, feature_name)
            )
            """
        )
        feature_stat_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memory_feature_stats)").fetchall()
        }
        if "sample_count" not in feature_stat_columns:
            conn.execute(
                "ALTER TABLE memory_feature_stats "
                "ADD COLUMN sample_count INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trades_require_open_levels_insert
            BEFORE INSERT ON trades
            WHEN NEW.status = 'open'
              AND (
                NEW.stop_loss IS NULL OR NEW.take_profit IS NULL
                OR NEW.liquidation_price IS NULL
                OR (NEW.side = 'long' AND NOT (
                    NEW.stop_loss < NEW.entry AND NEW.entry < NEW.take_profit
                    AND NEW.stop_loss > NEW.liquidation_price
                ))
                OR (NEW.side = 'short' AND NOT (
                    NEW.take_profit < NEW.entry AND NEW.entry < NEW.stop_loss
                    AND NEW.stop_loss < NEW.liquidation_price
                ))
              )
            BEGIN
                SELECT RAISE(ABORT, 'open positions require valid stop, target, and liquidation levels');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trades_require_open_levels_update
            BEFORE UPDATE OF status, side, entry, stop_loss, take_profit, liquidation_price ON trades
            WHEN NEW.status = 'open'
              AND (
                NEW.stop_loss IS NULL OR NEW.take_profit IS NULL
                OR NEW.liquidation_price IS NULL
                OR (NEW.side = 'long' AND NOT (
                    NEW.stop_loss < NEW.entry AND NEW.entry < NEW.take_profit
                    AND NEW.stop_loss > NEW.liquidation_price
                ))
                OR (NEW.side = 'short' AND NOT (
                    NEW.take_profit < NEW.entry AND NEW.entry < NEW.stop_loss
                    AND NEW.stop_loss < NEW.liquidation_price
                ))
              )
            BEGIN
                SELECT RAISE(ABORT, 'open positions require valid stop, target, and liquidation levels');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trade_events_append_only_update
            BEFORE UPDATE ON trade_events
            BEGIN
                SELECT RAISE(ABORT, 'trade_events is append-only');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trade_events_append_only_delete
            BEFORE DELETE ON trade_events
            BEGIN
                SELECT RAISE(ABORT, 'trade_events is append-only');
            END
            """
        )

        conn.execute(
            """
            UPDATE training_samples
            SET quote_status = CASE
                WHEN best_bid IS NOT NULL AND best_ask IS NOT NULL
                    THEN 'captured'
                ELSE 'not_collected'
            END
            WHERE quote_status = 'not_collected'
            """
        )
        conn.execute(
            """
            UPDATE training_samples
            SET realized_slippage_bps = (
                SELECT CASE trades.side
                    WHEN 'long' THEN
                        (trades.entry - training_samples.best_ask)
                        / training_samples.best_ask * 10000
                    ELSE
                        (training_samples.best_bid - trades.entry)
                        / training_samples.best_bid * 10000
                END
                FROM trades
                WHERE trades.decision_id = training_samples.decision_id
                  AND trades.status = 'closed'
            )
            WHERE realized_slippage_bps IS NULL
              AND outcome_resolved = 1
              AND best_bid > 0
              AND best_ask > 0
            """
        )
        conn.execute(
            """
            UPDATE training_samples
            SET outcome_resolved = 1,
                outcome_label = CASE WHEN trades.pnl_usd > 0 THEN 1 ELSE 0 END,
                realized_net_r = CASE
                    WHEN trades.risk_amount > 0
                    THEN trades.pnl_usd / trades.risk_amount
                    ELSE NULL
                END,
                pnl_usd = trades.pnl_usd,
                mistake = CASE WHEN trades.pnl_usd <= 0
                    THEN COALESCE(trades.exit_reason, 'loss') ELSE NULL END
            FROM trades
            WHERE training_samples.decision_id = trades.decision_id
              AND trades.status = 'closed'
              AND trades.source = 'ai'
              AND training_samples.outcome_resolved = 0
            """
        )
        self._backfill_legacy_decisions(conn)
        if conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 2"
        ).fetchone() is None:
            conn.execute(
                """
                INSERT INTO schema_migrations (version, applied_at_ms, description)
                VALUES (2, ?, 'Persistent memory, trade events, and position analytics')
                """,
                (int(time.time() * 1000),),
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        for key, value in (
            ("last_heartbeat_ms", int(time.time() * 1000)),
            ("last_catchup_at_ms", None),
            ("last_catchup_summary", {}),
            ("last_catchup_error", None),
            ("memory_restored_at_ms", None),
            ("app_version", "1.1.0"),
        ):
            conn.execute(
                """
                INSERT OR IGNORE INTO system_state (key, value_json, updated_at_ms)
                VALUES (?, ?, ?)
                """,
                (key, json.dumps(value), int(time.time() * 1000)),
            )

    def _backfill_legacy_decisions(self, conn: sqlite3.Connection) -> None:
        legacy_samples = conn.execute(
            """
            SELECT decision_id, created_at_ms, features_json, decision_json
            FROM training_samples ORDER BY created_at_ms, decision_id
            """
        ).fetchall()
        config_hash = hashlib.sha256(canonicalize_json({}).encode("utf-8")).hexdigest()
        for sample in legacy_samples:
            try:
                decision_data = json.loads(sample["decision_json"] or "{}")
                feature_data = json.loads(sample["features_json"] or "{}")
            except (TypeError, json.JSONDecodeError) as error:
                logging.warning(
                    "Skipping malformed legacy training sample %s: %s",
                    sample["decision_id"],
                    error,
                )
                continue
            plan = decision_data.get("trade_plan") or {}
            direction = str(decision_data.get("direction", "neutral"))
            confidence_value = decision_data.get("confidence")
            confidence = (
                float(confidence_value)
                if isinstance(confidence_value, (int, float))
                and math.isfinite(float(confidence_value))
                else None
            )
            source = str(decision_data.get("source", "legacy"))
            model_version = decision_data.get("model_version")
            conn.execute(
                """
                INSERT OR IGNORE INTO decisions (
                    decision_id, created_at_ms, symbol, decision, direction, source,
                    model_version, confidence, calibrated_probability, features_json,
                    feature_schema_version, indicator_snapshot_json, proposed_stop,
                    proposed_target, rejection_reason, config_hash, trade_plan_json,
                    memory_json, decision_hash, previous_decision_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    sample["decision_id"],
                    int(sample["created_at_ms"]),
                    str(self.full_config.get("symbol", "BTCUSDT")),
                    str(plan.get("action", "no_trade")),
                    direction,
                    source,
                    model_version,
                    confidence,
                    confidence if decision_data.get("calibrated") else None,
                    json.dumps(feature_data, sort_keys=True, allow_nan=False),
                    json.dumps(
                        decision_data.get("indicator_snapshot", {}),
                        sort_keys=True,
                        allow_nan=False,
                    ),
                    plan.get("stop_loss"),
                    plan.get("take_profit"),
                    plan.get("reason_if_no_trade"),
                    config_hash,
                    json.dumps(plan, sort_keys=True, allow_nan=False),
                    json.dumps(
                        decision_data.get(
                            "memory_summary",
                            {"mode": "legacy_unavailable", "neighbors": [], "n": 0},
                        ),
                        sort_keys=True,
                        allow_nan=False,
                    ),
                ),
            )
            if direction not in ("long", "short"):
                continue
            trade = conn.execute(
                "SELECT * FROM trades WHERE decision_id = ?",
                (sample["decision_id"],),
            ).fetchone()
            is_counterfactual = trade is None
            position_id = trade["id"] if trade is not None else None
            if trade is not None and trade["status"] == "closed":
                outcome = (
                    "win" if float(trade["pnl_usd"] or 0) > 0
                    else "timeout" if "timeout" in str(trade["exit_reason"] or "")
                    else "loss"
                )
                r_multiple = trade["r_multiple"]
                exit_reason = trade["exit_reason"]
                resolution_source = trade["resolution_source"] or "live"
            else:
                outcome = "unresolved"
                r_multiple = None
                exit_reason = None
                resolution_source = None
            vector = {
                str(name): float(value)
                for name, value in feature_data.items()
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            }
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_episodes (
                    id, decision_id, position_id, created_at_ms, symbol, side,
                    feature_vector_json, feature_schema_version, entry, stop_loss,
                    take_profit, outcome, r_multiple, exit_reason, resolution_source,
                    model_version, counterfactual, unresolved_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"episode_{sample['decision_id']}_{direction}",
                    sample["decision_id"],
                    position_id,
                    int(sample["created_at_ms"]),
                    str(self.full_config.get("symbol", "BTCUSDT")),
                    direction,
                    json.dumps(vector, sort_keys=True, allow_nan=False),
                    trade["entry"] if trade is not None else plan.get("entry"),
                    trade["stop_loss"] if trade is not None else plan.get("stop_loss"),
                    trade["take_profit"] if trade is not None else plan.get("take_profit"),
                    outcome,
                    r_multiple,
                    exit_reason,
                    resolution_source,
                    model_version,
                    int(is_counterfactual),
                    (
                        "Legacy candidate requires historical replay."
                        if is_counterfactual else None
                    ),
                ),
            )

    def _migrate_legacy_account(self, conn: sqlite3.Connection) -> None:
        had_legacy_file = os.path.exists(self.legacy_file_path)
        state: Dict[str, Any] = {
            "equity": self.starting_equity,
            "starting_equity": self.starting_equity,
            "open_position": None,
            "closed_trades": [],
            "realized_pnl_by_day": {},
        }
        if os.path.exists(self.legacy_file_path):
            with open(self.legacy_file_path, "r", encoding="utf-8") as legacy_file:
                state = json.load(legacy_file)

        starting_equity = float(state.get("starting_equity", self.starting_equity))
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
        closed_at_ms: Optional[int] = None,
        resolution_source: str = "live",
    ) -> Dict[str, Any]:
        exit_price = float(exit_price)
        gross_pnl = (
            (exit_price - trade["entry"]) * trade["size"]
            if trade["side"] == "long"
            else (trade["entry"] - exit_price) * trade["size"]
        )
        target_fee = trade["notional"] * self.round_trip_fee_pct
        fee_due = max(0.0, target_fee - trade["fees_paid_before"])
        fee_total = trade["fees_paid_before"] + fee_due
        account_pnl = max(gross_pnl - fee_due, -trade["margin"])
        net_pnl = max(gross_pnl - fee_total, -trade["margin"])
        closed_at = int(closed_at_ms or time.time() * 1000)
        duration_seconds = max(0, (closed_at - trade["opened_at"]) // 1000)
        r_multiple = (
            net_pnl / float(trade["risk_amount"])
            if trade["risk_amount"] and trade["risk_amount"] > 0
            else None
        )
        conn.execute(
            """
            UPDATE account SET balance = balance + ? WHERE id = 1
            """,
            (trade["margin"] + account_pnl,),
        )
        conn.execute(
            """
            UPDATE trades SET status = 'closed', closed_at = ?, exit_price = ?,
                exit_reason = ?, pnl_gross = ?, fee_usd = ?, pnl_usd = ?,
                r_multiple = ?, resolution_source = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                closed_at,
                exit_price,
                exit_reason,
                gross_pnl,
                fee_total,
                net_pnl,
                r_multiple,
                resolution_source,
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
        if trade["decision_id"]:
            conn.execute(
                """
                UPDATE training_samples SET outcome_resolved = 1,
                    outcome_label = ?, realized_net_r = ?, pnl_usd = ?,
                    realized_slippage_bps = ?, mistake = ?
                WHERE decision_id = ?
                """,
                (
                    int(net_pnl > 0),
                    net_pnl / trade["risk_amount"]
                    if trade["risk_amount"] > 0 else None,
                    net_pnl,
                    self._realized_slippage_bps(conn, trade),
                    None if net_pnl > 0 else exit_reason,
                    trade["decision_id"],
                ),
            )
            outcome = (
                "win" if net_pnl > 0 else
                "timeout" if "timeout" in exit_reason else "loss"
            )
            lesson = (
                f"{trade['side']} setup; {outcome} by {exit_reason}; "
                f"realized {r_multiple:.2f}R; MAE {trade['mae_r']:.2f}R, "
                f"MFE {trade['mfe_r']:.2f}R over {trade['bars_held']} bars. "
                + (
                    "Price reached +1R before the stop; review stop/target placement."
                    if net_pnl <= 0 and float(trade["mfe_r"] or 0) >= 1
                    else "This is a descriptive hypothesis, not a proven causal explanation."
                )
            ) if r_multiple is not None else (
                f"{trade['side']} setup; {outcome} by {exit_reason}. "
                "This is a descriptive hypothesis, not a proven causal explanation."
            )
            conn.execute(
                """
                UPDATE memory_episodes
                SET outcome = ?, r_multiple = ?, exit_reason = ?, mae_r = ?,
                    mfe_r = ?, bars_held = ?, resolution_source = ?,
                    lesson_text = ?, lesson_source = 'rule', unresolved_reason = NULL
                WHERE position_id = ?
                """,
                (
                    outcome,
                    r_multiple,
                    exit_reason,
                    trade["mae_r"],
                    trade["mfe_r"],
                    trade["bars_held"],
                    resolution_source,
                    lesson,
                    trade["id"],
                ),
            )
        self._record_trade_event(
            conn,
            trade_id=trade["id"],
            decision_id=trade["decision_id"],
            event_type="closed" if resolution_source == "live" else "catchup_closed",
            details={
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl_usd": net_pnl,
                "r_multiple": r_multiple,
                "fees_usd": fee_total,
                "funding_usd": float(trade["funding_usd"] or 0),
                "resolution_source": resolution_source,
            },
            created_at_ms=closed_at,
        )
        self._update_drawdown_control(conn)
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
                "resolution_source": resolution_source,
                "r_multiple": r_multiple,
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

    def settle_open_position(
        self,
        current_price: Optional[float] = None,
        intrabar_candles: Optional[Any] = None,
    ) -> Dict[str, Any]:
        return self._settle_open_position(current_price, intrabar_candles)

    def _settle_open_position(
        self,
        current_price: Optional[float],
        intrabar_candles: Optional[Any],
        catchup: bool = False,
    ) -> Dict[str, Any]:
        price = float(
            current_price
            if current_price is not None
            else fetch_current_price(str(self.config.get("symbol", "BTCUSDT")))
        )
        if price <= 0:
            raise ValueError("Settlement price must be greater than zero.")
        with self._connect() as conn:
            trade = self._get_open_trade(conn)
            if trade is None:
                return self.get_state()
            reason = None
            exit_price = price
            exit_time_ms = None
            if intrabar_candles is None:
                controls = conn.execute(
                    "SELECT last_settlement_at_ms FROM trading_controls WHERE id = 1"
                ).fetchone()
                last_checked = (
                    int(controls["last_settlement_at_ms"])
                    if controls and controls["last_settlement_at_ms"]
                    else int(trade["opened_at"])
                )
                try:
                    intrabar_candles = fetch_intrabar_candles(
                        str(self.config.get("symbol", "BTCUSDT")),
                        start_time_ms=last_checked // 60000 * 60000,
                    )
                    conn.execute(
                        "UPDATE trading_controls SET last_settlement_at_ms = ? WHERE id = 1",
                        (int(time.time() * 1000),),
                    )
                except RuntimeError as error:
                    logging.warning(
                        "Intrabar settlement data unavailable; using sampled price: %s",
                        error,
                    )
                    intrabar_candles = []
            candle_rows = (
                intrabar_candles.to_dict(orient="records")
                if hasattr(intrabar_candles, "to_dict")
                else list(intrabar_candles)
            )
            for candle in candle_rows:
                candle_open_ms = int(candle.get("open_time", 0) or 0)
                if (
                    candle_open_ms
                    and trade["last_candle_open_ms"] is not None
                    and candle_open_ms <= int(trade["last_candle_open_ms"])
                ):
                    continue
                candle_open = float(candle["open"])
                candle_high = float(candle["high"])
                candle_low = float(candle["low"])
                risk_amount = float(trade["risk_amount"] or 0)
                stop_touched_this_candle = (
                    candle_low <= trade["stop_loss"]
                    if trade["side"] == "long"
                    else candle_high >= trade["stop_loss"]
                )
                if risk_amount > 0:
                    if trade["side"] == "long":
                        mfe = (
                            float(trade["mfe_r"])
                            if stop_touched_this_candle
                            else max(
                                float(trade["mfe_r"]),
                                (candle_high - trade["entry"]) * trade["size"] / risk_amount,
                            )
                        )
                        mae = max(
                            float(trade["mae_r"]),
                            (trade["entry"] - candle_low) * trade["size"] / risk_amount,
                        )
                    else:
                        mfe = (
                            float(trade["mfe_r"])
                            if stop_touched_this_candle
                            else max(
                                float(trade["mfe_r"]),
                                (trade["entry"] - candle_low) * trade["size"] / risk_amount,
                            )
                        )
                        mae = max(
                            float(trade["mae_r"]),
                            (candle_high - trade["entry"]) * trade["size"] / risk_amount,
                        )
                else:
                    mfe = float(trade["mfe_r"])
                    mae = float(trade["mae_r"])
                candle_end_ms = int(candle.get("close_time") or candle_open_ms + 60_000)
                bars_held = int(trade["bars_held"])
                if candle_end_ms > int(trade["opened_at"]):
                    bars_held = max(
                        bars_held,
                        int(math.ceil(
                            (candle_end_ms - int(trade["opened_at"])) / 900_000
                        )),
                    )
                conn.execute(
                    """
                    UPDATE trades SET mfe_r = MAX(mfe_r, ?), mae_r = MAX(mae_r, ?),
                        bars_held = MAX(bars_held, ?),
                        last_candle_open_ms = COALESCE(?, last_candle_open_ms)
                    WHERE id = ? AND status = 'open'
                    """,
                    (mfe, mae, bars_held, candle_open_ms or None, trade["id"]),
                )
                trade = conn.execute(
                    "SELECT * FROM trades WHERE id = ?", (trade["id"],)
                ).fetchone()
                if trade["side"] == "long":
                    stop_hit = (
                        trade["stop_loss"] is not None
                        and candle_low <= trade["stop_loss"]
                    )
                    target_hit = (
                        trade["take_profit"] is not None
                        and candle_high >= trade["take_profit"]
                    )
                    liquidation_price = float(trade["liquidation_price"])
                    liquidation_hit = candle_low <= liquidation_price
                    if stop_hit:
                        reason = "stop_loss"
                        exit_price = min(candle_open, trade["stop_loss"])
                    elif target_hit:
                        reason = "take_profit"
                        exit_price = max(candle_open, trade["take_profit"])
                    elif liquidation_hit:
                        reason = "liquidation"
                        exit_price = min(candle_open, liquidation_price)
                else:
                    stop_hit = (
                        trade["stop_loss"] is not None
                        and candle_high >= trade["stop_loss"]
                    )
                    target_hit = (
                        trade["take_profit"] is not None
                        and candle_low <= trade["take_profit"]
                    )
                    liquidation_price = float(trade["liquidation_price"])
                    liquidation_hit = candle_high >= liquidation_price
                    if stop_hit:
                        reason = "stop_loss"
                        exit_price = max(candle_open, trade["stop_loss"])
                    elif target_hit:
                        reason = "take_profit"
                        exit_price = min(candle_open, trade["take_profit"])
                    elif liquidation_hit:
                        reason = "liquidation"
                        exit_price = max(candle_open, liquidation_price)
                if (
                    reason is None
                    and bars_held
                    >= max(1, int(self.full_config.get("catchup", {}).get("max_holding_bars", 48)))
                ):
                    reason = "timeout"
                    exit_price = float(candle.get("close", candle_open))
                if reason:
                    if candle.get("close_time") is not None:
                        exit_time_ms = int(candle["close_time"])
                    elif candle_open_ms:
                        exit_time_ms = candle_open_ms + 60_000
                    break

            if reason is None:
                unrealized_gross = (
                    (price - trade["entry"]) * trade["size"]
                    if trade["side"] == "long"
                    else (trade["entry"] - price) * trade["size"]
                )
                if unrealized_gross <= -trade["margin"]:
                    reason = "liquidation"
                    exit_price = price
            if reason is None:
                if trade["side"] == "long":
                    if trade["stop_loss"] is not None and price <= trade["stop_loss"]:
                        reason = "stop_loss"
                    elif trade["take_profit"] is not None and price >= trade["take_profit"]:
                        reason = "take_profit"
                        exit_price = trade["take_profit"]
                else:
                    if trade["stop_loss"] is not None and price >= trade["stop_loss"]:
                        reason = "stop_loss"
                    elif trade["take_profit"] is not None and price <= trade["take_profit"]:
                        reason = "take_profit"
                        exit_price = trade["take_profit"]
            if reason:
                trade = self._get_open_trade(conn)
                if trade is not None:
                    recorded_reason = f"catchup_{reason}" if catchup else reason
                    self._close_trade(
                        conn,
                        trade,
                        exit_price,
                        recorded_reason,
                        closed_at_ms=exit_time_ms if catchup else None,
                        resolution_source="catchup_replay" if catchup else "live",
                    )
            else:
                self._update_drawdown_control(conn, price)
        return self.get_state()

    def is_trading_blocked(self) -> Dict[str, Any]:
        with self._connect() as conn:
            if self._get_open_trade(conn):
                return {"blocked": True, "reason": "An open position already exists."}
            reason = self._risk_block_reason(conn)
            return {"blocked": reason is not None, "reason": reason}

    def _risk_block_reason(self, conn: sqlite3.Connection) -> Optional[str]:
        controls = conn.execute(
            "SELECT * FROM trading_controls WHERE id = 1"
        ).fetchone()
        if controls and controls["drawdown_paused"]:
            return "Drawdown kill-switch is active; re-enable trading after review."
        today = self._current_utc_date()
        daily = conn.execute(
            "SELECT pnl_usd FROM daily_pnl WHERE utc_date = ?", (today,)
        ).fetchone()
        daily_pnl = float(daily["pnl_usd"]) if daily else 0.0
        account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        daily_limit = account["starting_equity"] * float(
            self.config.get("max_daily_loss_pct", DAILY_LOSS_LIMIT_PCT)
        )
        if daily_pnl <= -daily_limit:
            return f"Daily loss limit reached ({daily_pnl:.2f} <= -{daily_limit:.2f})."

        recent = conn.execute(
            """
            SELECT pnl_usd, closed_at FROM trades
            WHERE status = 'closed' ORDER BY closed_at DESC, rowid DESC
            LIMIT ?
            """,
            (int(self.config.get("max_consecutive_losses", 3)),),
        ).fetchall()
        required_losses = int(self.config.get("max_consecutive_losses", 3))
        if (
            required_losses > 0
            and len(recent) >= required_losses
            and all(float(row["pnl_usd"] or 0) < 0 for row in recent)
        ):
            cooldown_ms = int(
                float(self.config.get("loss_cooldown_hours", 24)) * 60 * 60 * 1000
            )
            resume_at = int(recent[0]["closed_at"]) + cooldown_ms
            now_ms = int(time.time() * 1000)
            if now_ms < resume_at:
                return (
                    f"Loss cooldown active until "
                    f"{datetime.fromtimestamp(resume_at / 1000, timezone.utc).isoformat()}."
                )
        window = int(self.monitoring_config.get("rolling_trades_window", 30))
        if window > 0:
            rolling = conn.execute(
                """
                SELECT pnl_usd, initial_risk_usd FROM trades
                WHERE status = 'closed'
                ORDER BY closed_at DESC, rowid DESC LIMIT ?
                """,
                (window,),
            ).fetchall()
            if len(rolling) >= window:
                r_values = [
                    float(row["pnl_usd"] or 0) / float(row["initial_risk_usd"])
                    for row in rolling
                    if float(row["initial_risk_usd"] or 0) > 0
                ]
                expectancy = sum(r_values) / len(r_values) if r_values else 0.0
                minimum = float(
                    self.monitoring_config.get("min_rolling_expectancy_r", 0.0)
                )
                if expectancy < minimum:
                    if controls is not None and not controls["drawdown_paused"]:
                        conn.execute(
                            "UPDATE trading_controls SET drawdown_paused = 1 WHERE id = 1"
                        )
                        if self._verify_ledger(conn):
                            self._append_ledger(
                                conn,
                                "monitoring_auto_pause",
                                None,
                                {
                                    "rolling_trades": len(r_values),
                                    "expectancy_r": expectancy,
                                    "minimum_expectancy_r": minimum,
                                },
                            )
                    return (
                        "Rolling trade expectancy is below the configured limit; "
                        "re-enable trading after review."
                    )
        return None

    def _update_drawdown_control(
        self, conn: sqlite3.Connection, current_price: Optional[float] = None
    ) -> None:
        account = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        trade = self._get_open_trade(conn)
        equity = float(account["balance"])
        if trade is not None:
            equity += float(trade["margin"])
            if current_price is not None:
                gross = (
                    (current_price - trade["entry"]) * trade["size"]
                    if trade["side"] == "long"
                    else (trade["entry"] - current_price) * trade["size"]
                )
                fee = max(
                    0.0,
                    trade["notional"] * self.round_trip_fee_pct
                    - trade["fees_paid_before"],
                )
                equity += max(gross - fee, -float(trade["margin"]))
        controls = conn.execute(
            "SELECT * FROM trading_controls WHERE id = 1"
        ).fetchone()
        if controls is None:
            return
        peak = max(float(controls["peak_equity"]), equity)
        threshold = float(self.config.get("max_drawdown_pct", 0.10))
        paused = bool(controls["drawdown_paused"])
        if peak > 0 and (peak - equity) / peak > threshold:
            paused = True
        conn.execute(
            "UPDATE trading_controls SET peak_equity = ?, drawdown_paused = ? WHERE id = 1",
            (peak, int(paused)),
        )

    def record_training_sample(
        self,
        decision_id: str,
        features: Dict[str, Any],
        decision: Dict[str, Any],
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        quote_status: str = "not_collected",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO training_samples (
                    decision_id, created_at_ms, features_json, decision_json,
                    best_bid, best_ask, quote_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    int(time.time() * 1000),
                    json.dumps(features, sort_keys=True, allow_nan=False),
                    json.dumps(decision, sort_keys=True, allow_nan=False),
                    best_bid,
                    best_ask,
                    quote_status,
                ),
            )

    @staticmethod
    def _realized_slippage_bps(
        conn: sqlite3.Connection, trade: sqlite3.Row
    ) -> Optional[float]:
        sample = conn.execute(
            "SELECT best_bid, best_ask FROM training_samples WHERE decision_id = ?",
            (trade["decision_id"],),
        ).fetchone()
        if sample is None or not sample["best_bid"] or not sample["best_ask"]:
            return None
        if trade["side"] == "long":
            return (
                (float(trade["entry"]) - float(sample["best_ask"]))
                / float(sample["best_ask"])
                * 10_000
            )
        return (
            (float(sample["best_bid"]) - float(trade["entry"]))
            / float(sample["best_bid"])
            * 10_000
        )

    def get_training_samples(self, limit: int = 100) -> list[Dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("Training sample limit must be between 1 and 1000.")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM training_samples
                ORDER BY created_at_ms DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "features": json.loads(row["features_json"]),
                    "decision": json.loads(row["decision_json"]),
                }
                for row in rows
            ]

    def get_learning_summary(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total_row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome_resolved = 1 THEN 1 ELSE 0 END) AS resolved
                FROM training_samples
                """
            ).fetchone()
            rows = conn.execute(
                """
                SELECT outcome_label, realized_net_r, realized_slippage_bps, mistake,
                       decision_json
                FROM training_samples
                WHERE outcome_resolved = 1
                """
            ).fetchall()

        resolved = len(rows)
        r_values = [
            float(row["realized_net_r"])
            for row in rows
            if row["realized_net_r"] is not None
        ]
        slippage_values = [
            float(row["realized_slippage_bps"])
            for row in rows
            if row["realized_slippage_bps"] is not None
        ]
        loss_reasons: Dict[str, int] = {}
        model_versions: Dict[str, int] = {}
        for row in rows:
            if int(row["outcome_label"] or 0) == 0 and row["mistake"]:
                reason = str(row["mistake"])
                loss_reasons[reason] = loss_reasons.get(reason, 0) + 1
            decision = json.loads(row["decision_json"])
            version = decision.get("model_version") or "deterministic_rule_fallback"
            model_versions[version] = model_versions.get(version, 0) + 1

        return {
            "sample_count": int(total_row["total"] or 0),
            "resolved_count": resolved,
            "unresolved_count": int(total_row["total"] or 0) - resolved,
            "win_rate": (
                sum(int(row["outcome_label"] or 0) for row in rows) / resolved
                if resolved else None
            ),
            "mean_realized_net_r": (
                sum(r_values) / len(r_values) if r_values else None
            ),
            "mean_realized_slippage_bps": (
                sum(slippage_values) / len(slippage_values)
                if slippage_values else None
            ),
            "loss_reasons": loss_reasons,
            "resolved_samples_by_model": model_versions,
        }

    def retrieve_memory(
        self,
        feature_vector: Dict[str, float],
        side: str,
        now_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        settings = self.full_config.get("memory", {})
        if settings.get("mode", "advisory") == "off":
            return {
                "side": side,
                "neighbors": [],
                "n": 0,
                "effective_n": 0.0,
                "shrunk_win_rate": None,
                "average_r": None,
                "win_rate_confidence_interval": None,
                "sufficient": False,
                "mode": "off",
            }
        with self._connect() as conn:
            episodes = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM memory_episodes WHERE feature_schema_version = ?",
                    (FEATURE_SCHEMA_VERSION,),
                ).fetchall()
            ]
            stats = {
                str(row["feature_name"]): (
                    float(row["mean"]),
                    float(row["stddev"]),
                )
                for row in conn.execute(
                    """
                    SELECT feature_name, mean, stddev FROM memory_feature_stats
                    WHERE feature_schema_version = ?
                    """,
                    (FEATURE_SCHEMA_VERSION,),
                ).fetchall()
            }
        summary = retrieve_similar(
            feature_vector,
            side,
            episodes,
            k=int(settings.get("k", 20)),
            min_n=int(settings.get("min_n", 30)),
            min_gap_bars=int(settings.get("min_gap_bars", 24)),
            half_life_days=float(settings.get("half_life_days", 90)),
            prior_strength=float(settings.get("prior_strength", 20)),
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            now_ms=now_ms,
            feature_stats=stats,
        )
        summary["mode"] = str(settings.get("mode", "advisory"))
        return summary

    def record_decision(
        self,
        record: Dict[str, Any],
        direction: str,
        source: str,
        confidence: Optional[float],
        calibrated_probability: Optional[float],
        feature_vector: Dict[str, Any],
        indicator_snapshot: Dict[str, Any],
        trade_plan: Dict[str, Any],
        memory: Optional[Dict[str, Any]] = None,
        counterfactual: bool = False,
    ) -> None:
        import hashlib

        decision_id = str(record["decision_id"])
        config_snapshot = record.get("config_snapshot", {})
        model_version = record.get("learning", {}).get("model_version")
        config_hash = hashlib.sha256(
            canonicalize_json(config_snapshot).encode("utf-8")
        ).hexdigest()
        created_at = int(time.time() * 1000)
        side = direction if direction in ("long", "short") else None
        memory_data = memory or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO decisions (
                    decision_id, created_at_ms, symbol, decision, direction, source,
                    model_version, confidence, calibrated_probability, features_json,
                    feature_schema_version, indicator_snapshot_json, proposed_stop,
                    proposed_target, rejection_reason, config_hash, trade_plan_json,
                    memory_json, decision_hash, previous_decision_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    created_at,
                    str(record.get("symbol", "BTCUSDT")),
                    str(trade_plan.get("action", "no_trade")),
                    direction,
                    source,
                    model_version,
                    confidence,
                    calibrated_probability,
                    json.dumps(feature_vector, sort_keys=True, allow_nan=False),
                    FEATURE_SCHEMA_VERSION,
                    json.dumps(indicator_snapshot, sort_keys=True, allow_nan=False),
                    trade_plan.get("stop_loss"),
                    trade_plan.get("take_profit"),
                    trade_plan.get("reason_if_no_trade"),
                    config_hash,
                    json.dumps(trade_plan, sort_keys=True, allow_nan=False),
                    json.dumps(memory_data, sort_keys=True, allow_nan=False),
                    record.get("decision_hash"),
                    record.get("previous_decision_hash"),
                ),
            )
            if side is not None:
                features = {
                    key: float(value)
                    for key, value in feature_vector.items()
                    if isinstance(value, (int, float)) and math.isfinite(float(value))
                }
                episode_insert = conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_episodes (
                        id, decision_id, created_at_ms, symbol, side,
                        feature_vector_json, feature_schema_version, trend_bucket,
                        volatility_bucket, entry, stop_loss, take_profit, model_version,
                        counterfactual, unresolved_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"episode_{decision_id}_{side}",
                        decision_id,
                        created_at,
                        str(record.get("symbol", "BTCUSDT")),
                        side,
                        json.dumps(features, sort_keys=True, allow_nan=False),
                        FEATURE_SCHEMA_VERSION,
                        (
                            "up" if features.get("15m_close_ema50_atr", 0) > 0
                            else "down"
                        ),
                        (
                            "high" if features.get("15m_atr_pct_rank", 0.5) >= 0.75
                            else "low" if features.get("15m_atr_pct_rank", 0.5) <= 0.25
                            else "mid"
                        ),
                        trade_plan.get("entry"),
                        trade_plan.get("stop_loss"),
                        trade_plan.get("take_profit"),
                        model_version,
                        int(counterfactual),
                        (
                            "Candidate was not executed; counterfactual outcome requires replay."
                            if counterfactual else None
                        ),
                    ),
                )
                if episode_insert.rowcount and not counterfactual:
                    self._add_memory_feature_stats(
                        conn, FEATURE_SCHEMA_VERSION, features
                    )
            memory_action = trade_plan.get("memory_action", {})
            if memory_action.get("veto") or memory_action.get("size_multiplier", 1) < 1:
                self._record_trade_event(
                    conn,
                    None,
                    decision_id,
                    "memory_veto" if memory_action.get("veto") else "memory_size_reduced",
                    {
                        "reason": memory_action.get("reason"),
                        "size_multiplier": memory_action.get("size_multiplier", 1),
                        "memory": memory_data,
                    },
                    created_at,
                )

    def get_memory_episodes(
        self,
        limit: int = 100,
        offset: int = 0,
        outcome: Optional[str] = None,
        side: Optional[str] = None,
        include_counterfactual: bool = True,
    ) -> Dict[str, Any]:
        if limit < 1 or limit > 1000 or offset < 0:
            raise ValueError("Memory pagination is outside the allowed range.")
        conditions = []
        values: list[Any] = []
        if outcome:
            conditions.append("outcome = ?")
            values.append(outcome)
        if side:
            if side not in ("long", "short"):
                raise ValueError("Side filter must be long or short.")
            conditions.append("side = ?")
            values.append(side)
        if not include_counterfactual:
            conditions.append("counterfactual = 0")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory_episodes{where} "
                "ORDER BY created_at_ms DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM memory_episodes{where}", values
            ).fetchone()[0]
        return {
            "episodes": [
                {**dict(row), "feature_vector": json.loads(row["feature_vector_json"])}
                for row in rows
            ],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def get_memory_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(outcome != 'unresolved') AS resolved,
                    SUM(outcome = 'unresolved') AS unresolved,
                    SUM(counterfactual = 1) AS counterfactual
                FROM memory_episodes
                """
            ).fetchone()
            state_rows = conn.execute("SELECT key, value_json FROM system_state").fetchall()
            state = {row["key"]: json.loads(row["value_json"]) for row in state_rows}
            recent = conn.execute(
                """
                SELECT outcome, r_multiple FROM memory_episodes
                WHERE outcome != 'unresolved' AND counterfactual = 0
                ORDER BY created_at_ms DESC LIMIT 30
                """
            ).fetchall()
            retrain_check = state.get("learning_retrain_check", {})
        sample_count = len(recent)
        minimum = int(self.full_config.get("memory", {}).get("min_n", 30))
        return {
            "episodes_total": int(counts["total"] or 0),
            "resolved": int(counts["resolved"] or 0),
            "unresolved": int(counts["unresolved"] or 0),
            "counterfactual": int(counts["counterfactual"] or 0),
            "rolling": {
                "n": sample_count,
                "win_rate": (
                    sum(row["outcome"] == "win" for row in recent) / sample_count
                    if sample_count >= minimum else None
                ),
                "average_r": (
                    sum(float(row["r_multiple"] or 0) for row in recent) / sample_count
                    if sample_count >= minimum else None
                ),
                "insufficient_history": sample_count < minimum,
                "minimum_n": minimum,
            },
            "mode": self.full_config.get("memory", {}).get("mode", "advisory"),
            "last_restore_at_ms": state.get("memory_restored_at_ms"),
            "last_catchup_at_ms": state.get("last_catchup_at_ms"),
            "last_catchup_summary": state.get("last_catchup_summary", {}),
            "last_catchup_error": state.get("last_catchup_error"),
            "active_model_version": self.full_config.get("model", {}).get("active_version"),
            "challenger_status": self._challenger_status(),
            "retrain_check": retrain_check,
            "calibration_status": (
                "calibrated model active"
                if self.full_config.get("model", {}).get("active_version")
                else "uncalibrated rule fallback"
            ),
        }

    def _challenger_status(self) -> Dict[str, Any]:
        model_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        active_version = self.full_config.get("model", {}).get("active_version")
        if not os.path.isdir(model_root):
            return {
                "version": None,
                "status": "none",
                "reason": "No model candidate artifacts are present.",
            }
        candidates = []
        for name in os.listdir(model_root):
            metadata_path = os.path.join(model_root, name, "metadata.json")
            if not os.path.isfile(metadata_path):
                continue
            try:
                with open(metadata_path, "r", encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
            except (OSError, json.JSONDecodeError) as error:
                logging.warning("Unable to read model candidate metadata %s: %s", metadata_path, error)
                continue
            if metadata.get("version") == name:
                candidates.append(metadata)
        if not candidates:
            return {
                "version": None,
                "status": "none",
                "reason": "No valid model candidate metadata is present.",
            }
        candidate = max(
            candidates,
            key=lambda item: str(item.get("created_at_utc", "")),
        )
        version = str(candidate["version"])
        if version == active_version:
            return {
                "version": version,
                "status": "active",
                "reason": "This candidate is configured as the active paper-trial model.",
            }
        if candidate.get("promoted") and candidate.get("promotion_gate_passed"):
            return {
                "version": version,
                "status": "qualified, not active",
                "reason": "Candidate passed historical gates but is not the configured active version.",
            }
        return {
            "version": version,
            "status": "challenger",
            "reason": "Awaiting final holdout review and explicit paper-trial approval.",
        }

    def daily_learning_check(self, now_ms: Optional[int] = None) -> Dict[str, Any]:
        now = int(now_ms or time.time() * 1000)
        day = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
        with self._connect() as conn:
            existing_day = self._get_system_state(conn, "last_learning_check_date")
            if existing_day == day:
                return self._get_system_state(conn, "learning_retrain_check") or {}
            last_training = int(
                self._get_system_state(conn, "last_training_at_ms") or 0
            )
            resolved = int(
                conn.execute(
                    "SELECT COUNT(*) FROM training_samples WHERE outcome_resolved = 1"
                ).fetchone()[0]
            )
            new_resolved = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM training_samples
                    WHERE outcome_resolved = 1 AND created_at_ms > ?
                    """,
                    (last_training,),
                ).fetchone()[0]
            )
            settings = self.full_config.get("learning", {})
            minimum_new = int(settings.get("retrain_min_new", 50))
            minimum_total = int(settings.get("min_total_for_training", 200))
            result = {
                "checked_at_ms": now,
                "eligible": new_resolved >= minimum_new and resolved >= minimum_total,
                "new_resolved": new_resolved,
                "minimum_new": minimum_new,
                "resolved_total": resolved,
                "minimum_total": minimum_total,
                "reason": (
                    "Thresholds met; use python -m tools.retrain with a dated training range."
                    if new_resolved >= minimum_new and resolved >= minimum_total
                    else "Resolved-sample thresholds are not yet met."
                ),
            }
            self._set_system_state(conn, "learning_retrain_check", result)
            self._set_system_state(conn, "last_learning_check_date", day)
        return result

    def set_catchup_error(self, message: str) -> None:
        with self._connect() as conn:
            self._set_system_state(conn, "last_catchup_error", str(message))

    def get_decisions(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        if limit < 1 or limit > 1000 or offset < 0:
            raise ValueError("Decision pagination is outside the allowed range.")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM decisions ORDER BY created_at_ms DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        return {
            "decisions": [
                {
                    **dict(row),
                    "features": json.loads(row["features_json"]),
                    "indicator_snapshot": json.loads(row["indicator_snapshot_json"]),
                    "trade_plan": json.loads(row["trade_plan_json"]),
                    "memory": json.loads(row["memory_json"]),
                }
                for row in rows
            ],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "features": json.loads(row["features_json"]),
            "indicator_snapshot": json.loads(row["indicator_snapshot_json"]),
            "trade_plan": json.loads(row["trade_plan_json"]),
            "memory": json.loads(row["memory_json"]),
        }

    def get_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            events = conn.execute(
                "SELECT * FROM trade_events WHERE trade_id = ? ORDER BY created_at_ms",
                (trade_id,),
            ).fetchall()
            episode = conn.execute(
                "SELECT * FROM memory_episodes WHERE position_id = ?", (trade_id,)
            ).fetchone()
        if row is None:
            return None
        result = self._trade_to_dict(row)
        result["events"] = [
            {**dict(event), "details": json.loads(event["details_json"])}
            for event in events
        ]
        result["decision"] = self.get_decision(row["decision_id"]) if row["decision_id"] else None
        if episode is not None:
            result["memory_episode"] = {
                **dict(episode),
                "feature_vector": json.loads(episode["feature_vector_json"]),
            }
        return result

    def _backfill_missing_open_levels(self) -> bool:
        with self._connect() as conn:
            trade = self._get_open_trade(conn)
            if trade is None:
                return False
            if (
                trade["stop_loss"] is not None
                and trade["take_profit"] is not None
                and trade["liquidation_price"] is not None
            ):
                return False
            trade_data = dict(trade)

        saved_atr = trade_data.get("atr_at_entry")
        atr_source = "stored_at_entry"
        if saved_atr is not None and math.isfinite(float(saved_atr)) and float(saved_atr) > 0:
            atr = float(saved_atr)
        else:
            candles = fetch_closed_candles(
                str(self.full_config.get("symbol", "BTCUSDT")), "1h", 300
            )
            atr_values = calculate_atr(candles, 14).dropna()
            if atr_values.empty:
                raise RuntimeError(
                    "Cannot backfill legacy open position levels: current 1h ATR is unavailable."
                )
            atr = float(atr_values.iloc[-1])
            atr_source = "current_1h_atr"
        risk_config = self.full_config.get("risk", {})
        sl_mult = float(risk_config.get("sl_atr_mult", 1.5))
        tp_mult = float(risk_config.get("tp_atr_mult", 2.5))
        entry = float(trade_data["entry"])
        stop_distance = atr * sl_mult
        target_distance = atr * tp_mult
        stop = entry - stop_distance if trade_data["side"] == "long" else entry + stop_distance
        target = entry + target_distance if trade_data["side"] == "long" else entry - target_distance
        liquidation = (
            entry - float(trade_data["margin"]) / float(trade_data["size"])
            if trade_data["side"] == "long"
            else entry + float(trade_data["margin"]) / float(trade_data["size"])
        )
        stop, target = self._validate_position_levels(
            str(trade_data["side"]),
            entry,
            stop,
            target,
            liquidation,
            float(risk_config.get("stop_liquidation_buffer_pct", 0.2)),
        )
        now = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE trades SET stop_loss = ?, take_profit = ?,
                    liquidation_price = ?, atr_at_entry = ?, sl_atr_mult = ?,
                    tp_atr_mult = ?, risk_amount = ?, reward_to_risk = ?,
                    levels_backfilled = 1
                WHERE id = ? AND status = 'open'
                """,
                (
                    stop,
                    target,
                    liquidation,
                    atr,
                    sl_mult,
                    tp_mult,
                    stop_distance * float(trade_data["size"]),
                    target_distance / stop_distance,
                    trade_data["id"],
                ),
            )
            self._record_trade_event(
                conn,
                str(trade_data["id"]),
                trade_data["decision_id"],
                "levels_backfilled",
                {
                    "stop_loss": stop,
                    "take_profit": target,
                    "atr_at_entry": atr,
                    "source": atr_source,
                    "levels_backfilled": True,
                },
                now,
            )
        return True

    def record_heartbeat(self) -> None:
        now = int(time.time() * 1000)
        with self._connect() as conn:
            self._set_system_state(conn, "last_heartbeat_ms", now)
            self._set_system_state(conn, "app_version", "1.1.0")
        self.maybe_daily_backup(now)

    def maybe_daily_backup(self, now_ms: Optional[int] = None) -> Optional[str]:
        settings = self.full_config.get("backup", {})
        if not settings.get("daily", True):
            return None
        now = int(now_ms or time.time() * 1000)
        day = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
        with self._connect() as conn:
            if self._get_system_state(conn, "last_backup_date") == day:
                return None
        with self._connect() as source:
            destination = self._backup_database(source)
        with self._connect() as conn:
            self._set_system_state(conn, "last_backup_date", day)
        keep = max(1, int(settings.get("keep", 14)))
        backups = sorted(
            (
                os.path.join(self.backup_dir, name)
                for name in os.listdir(self.backup_dir)
                if name.startswith("mortis_") and name.endswith(".db")
            ),
            key=os.path.getmtime,
            reverse=True,
        )
        for old_backup in backups[keep:]:
            os.remove(old_backup)
        return destination

    def _resolve_counterfactual_episodes(self, now_ms: int) -> int:
        with self._connect() as conn:
            episodes = conn.execute(
                """
                SELECT episode.*, decision.trade_plan_json
                FROM memory_episodes AS episode
                JOIN decisions AS decision
                  ON decision.decision_id = episode.decision_id
                WHERE episode.counterfactual = 1
                  AND episode.outcome = 'unresolved'
                ORDER BY episode.created_at_ms
                """
            ).fetchall()

        max_bars = int(
            self.full_config.get("catchup", {}).get("max_holding_bars", 48)
        )
        max_age_ms = max_bars * 15 * 60 * 1000
        resolved = 0
        symbol = str(self.full_config.get("symbol", "BTCUSDT"))
        for episode in episodes:
            plan = json.loads(episode["trade_plan_json"])
            entry = episode["entry"] or plan.get("entry")
            stop = episode["stop_loss"] or plan.get("stop_loss")
            target = episode["take_profit"] or plan.get("take_profit")
            atr = plan.get("atr_at_entry")
            if entry is not None and atr is not None:
                entry_value = float(entry)
                atr_value = float(atr)
                if math.isfinite(entry_value) and math.isfinite(atr_value) and atr_value > 0:
                    sl_multiplier = float(
                        plan.get(
                            "sl_atr_mult",
                            self.full_config.get("risk", {}).get("sl_atr_mult", 1.5),
                        )
                    )
                    tp_multiplier = float(
                        plan.get(
                            "tp_atr_mult",
                            self.full_config.get("risk", {}).get("tp_atr_mult", 2.5),
                        )
                    )
                    if episode["side"] == "long":
                        stop = stop or entry_value - atr_value * sl_multiplier
                        target = target or entry_value + atr_value * tp_multiplier
                    else:
                        stop = stop or entry_value + atr_value * sl_multiplier
                        target = target or entry_value - atr_value * tp_multiplier
            if (
                entry is None or stop is None or target is None
                or not all(math.isfinite(float(value)) for value in (entry, stop, target))
                or float(entry) <= 0 or float(stop) <= 0 or float(target) <= 0
                or not (
                    float(stop) < float(entry) < float(target)
                    if episode["side"] == "long"
                    else float(target) < float(entry) < float(stop)
                )
            ):
                if now_ms - int(episode["created_at_ms"]) >= max_age_ms:
                    with self._connect() as conn:
                        reason = "Candidate did not have valid entry, stop, and target levels."
                        conn.execute(
                            """
                            UPDATE memory_episodes SET unresolved_reason = ?
                            WHERE id = ? AND outcome = 'unresolved'
                            """,
                            (reason, episode["id"]),
                        )
                        conn.execute(
                            """
                            UPDATE training_samples SET unresolved_reason = ?
                            WHERE decision_id = ? AND outcome_resolved = 0
                            """,
                            (reason, episode["decision_id"]),
                        )
                continue

            created_at = int(episode["created_at_ms"])
            cutoff = min(now_ms, created_at + max_age_ms)
            if cutoff <= created_at:
                continue
            candles = fetch_intrabar_candles(
                symbol,
                start_time_ms=created_at,
                end_time_ms=cutoff,
                closed_only=True,
            )
            candle_rows = (
                candles.to_dict(orient="records")
                if hasattr(candles, "to_dict")
                else list(candles)
            )
            if not candle_rows:
                if now_ms >= created_at + max_age_ms:
                    with self._connect() as conn:
                        reason = "No closed market candles were available for the replay window."
                        conn.execute(
                            """
                            UPDATE memory_episodes SET unresolved_reason = ?
                            WHERE id = ? AND outcome = 'unresolved'
                            """,
                            (reason, episode["id"]),
                        )
                        conn.execute(
                            """
                            UPDATE training_samples SET unresolved_reason = ?
                            WHERE decision_id = ? AND outcome_resolved = 0
                            """,
                            (reason, episode["decision_id"]),
                        )
                continue

            entry_value = float(entry)
            stop_value = float(stop)
            target_value = float(target)
            risk_distance = abs(entry_value - stop_value)
            size = float(plan.get("size_btc") or 1.0)
            if not math.isfinite(size) or size <= 0:
                size = 1.0
            risk_usd = risk_distance * size
            mfe_r = 0.0
            mae_r = 0.0
            exit_price = None
            exit_reason = None
            exit_at = None
            last_close = None
            for candle in candle_rows:
                opened = float(candle["open"])
                high = float(candle["high"])
                low = float(candle["low"])
                last_close = float(candle["close"])
                if episode["side"] == "long":
                    stop_hit = low <= stop_value
                    target_hit = high >= target_value
                    if not stop_hit:
                        mfe_r = max(mfe_r, (high - entry_value) / risk_distance)
                    mae_r = max(mae_r, (entry_value - low) / risk_distance)
                    if stop_hit:
                        exit_reason = "catchup_stop_loss"
                        exit_price = min(opened, stop_value)
                    elif target_hit:
                        exit_reason = "catchup_take_profit"
                        exit_price = max(opened, target_value)
                else:
                    stop_hit = high >= stop_value
                    target_hit = low <= target_value
                    if not stop_hit:
                        mfe_r = max(mfe_r, (entry_value - low) / risk_distance)
                    mae_r = max(mae_r, (high - entry_value) / risk_distance)
                    if stop_hit:
                        exit_reason = "catchup_stop_loss"
                        exit_price = max(opened, stop_value)
                    elif target_hit:
                        exit_reason = "catchup_take_profit"
                        exit_price = min(opened, target_value)
                if exit_reason:
                    exit_at = int(candle.get("close_time") or candle["open_time"] + 60_000)
                    break

            if exit_reason is None and now_ms >= created_at + max_age_ms:
                exit_reason = "catchup_timeout"
                exit_price = last_close
                exit_at = int(candle_rows[-1].get("close_time") or cutoff)
            if exit_reason is None or exit_price is None:
                continue

            gross = (
                (exit_price - entry_value) * size
                if episode["side"] == "long"
                else (entry_value - exit_price) * size
            )
            cost = entry_value * size * self.round_trip_fee_pct
            net = gross - cost
            net_r = net / risk_usd if risk_usd > 0 else 0.0
            outcome = (
                "timeout" if exit_reason == "catchup_timeout"
                else "win" if net > 0
                else "loss"
            )
            bars_held = max(
                1,
                math.ceil((exit_at - created_at) / (15 * 60 * 1000)),
            )
            lesson = (
                f"Counterfactual {episode['side']} candidate; {outcome} by "
                f"{exit_reason}; realized {net_r:.2f}R; MAE {mae_r:.2f}R, "
                f"MFE {mfe_r:.2f}R over {bars_held} bars. "
                "This simulated lesson is a hypothesis, not a causal conclusion."
            )
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE memory_episodes
                    SET outcome = ?, r_multiple = ?, exit_reason = ?, mae_r = ?,
                        mfe_r = ?, bars_held = ?, resolution_source = 'counterfactual',
                        lesson_text = ?, lesson_source = 'rule', unresolved_reason = NULL
                    WHERE id = ? AND outcome = 'unresolved'
                    """,
                    (
                        outcome, net_r, exit_reason, mae_r, mfe_r, bars_held,
                        lesson, episode["id"],
                    ),
                ).rowcount
                if changed:
                    conn.execute(
                        """
                        UPDATE training_samples SET outcome_resolved = 1,
                            outcome_label = ?, realized_net_r = ?, pnl_usd = ?,
                            mistake = ?, unresolved_reason = NULL
                        WHERE decision_id = ? AND outcome_resolved = 0
                        """,
                        (
                            int(net > 0), net_r, net, exit_reason,
                            episode["decision_id"],
                        ),
                    )
                    self._record_trade_event(
                        conn,
                        None,
                        episode["decision_id"],
                        "counterfactual_resolved",
                        {
                            "exit_price": exit_price,
                            "exit_reason": exit_reason,
                            "outcome": outcome,
                            "r_multiple": net_r,
                            "resolution_source": "counterfactual",
                            "bars_held": bars_held,
                        },
                        exit_at,
                    )
                    resolved += 1
        return resolved

    def catch_up(self, candles: Optional[Any] = None) -> Dict[str, Any]:
        if not self.full_config.get("catchup", {}).get("enabled", True):
            return {"enabled": False, "closed_positions": 0, "resolved_samples": 0}
        self._backfill_missing_open_levels()
        now = int(time.time() * 1000)
        with self._connect() as conn:
            heartbeat = int(
                self._get_system_state(conn, "last_heartbeat_ms") or now
            )
            open_trade = self._get_open_trade(conn)
            if open_trade is not None:
                start = min(heartbeat, int(open_trade["opened_at"]))
                if open_trade["last_candle_open_ms"] is not None:
                    start = max(
                        start, int(open_trade["last_candle_open_ms"]) + 60_000
                    )
            else:
                start = now
        rows = candles
        if open_trade is not None and rows is None:
            rows = fetch_intrabar_candles(
                str(self.full_config.get("symbol", "BTCUSDT")),
                start_time_ms=start,
                end_time_ms=now,
                closed_only=True,
            )
        before_closed = self.get_trade_count()
        closed_positions = 0
        if open_trade is not None:
            candle_rows = (
                rows.to_dict(orient="records")
                if hasattr(rows, "to_dict")
                else list(rows or [])
            )
            mark = (
                float(candle_rows[-1]["close"])
                if candle_rows
                else fetch_current_price(str(self.full_config.get("symbol", "BTCUSDT")))
            )
            before_state = self.get_state()
            self._settle_open_position(mark, candle_rows, catchup=True)
            after_state = self.get_state()
            closed_positions = int(
                before_state["open_position"] is not None
                and after_state["open_position"] is None
            )
        resolved_counterfactuals = self._resolve_counterfactual_episodes(now)
        max_age_ms = int(
            self.full_config.get("catchup", {}).get("max_holding_bars", 48)
        ) * 15 * 60 * 1000
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE training_samples
                SET outcome_resolved = 1,
                    outcome_label = CASE WHEN trades.pnl_usd > 0 THEN 1 ELSE 0 END,
                    realized_net_r = CASE
                        WHEN trades.risk_amount > 0
                        THEN trades.pnl_usd / trades.risk_amount ELSE NULL END,
                    pnl_usd = trades.pnl_usd,
                    mistake = CASE WHEN trades.pnl_usd <= 0
                        THEN COALESCE(trades.exit_reason, 'loss') ELSE NULL END,
                    unresolved_reason = NULL
                FROM trades
                WHERE training_samples.decision_id = trades.decision_id
                  AND trades.status = 'closed' AND trades.source = 'ai'
                  AND training_samples.outcome_resolved = 0
                """
            )
            conn.execute(
                """
                UPDATE training_samples
                SET unresolved_reason =
                    'No linked AI position exists; historical trade outcome cannot be inferred.'
                WHERE outcome_resolved = 0 AND unresolved_reason IS NULL
                  AND created_at_ms < ?
                  AND NOT EXISTS (
                    SELECT 1 FROM trades
                    WHERE trades.decision_id = training_samples.decision_id
                  )
                """,
                (now - max_age_ms,),
            )
            total_closed = self.get_trade_count()
            summary = {
                "closed_positions": closed_positions,
                "resolved_samples": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM training_samples "
                        "WHERE outcome_resolved = 1 AND created_at_ms >= ?",
                        (heartbeat,),
                    ).fetchone()[0]
                ),
                "resolved_counterfactuals": resolved_counterfactuals,
                "unresolvable_samples": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM training_samples "
                        "WHERE unresolved_reason IS NOT NULL"
                    ).fetchone()[0]
                ),
                "candles_replayed": (
                    len(rows) if hasattr(rows, "__len__") else 0
                ),
                "new_closed_trades": max(0, total_closed - before_closed),
            }
            self._set_system_state(conn, "last_catchup_at_ms", now)
            self._set_system_state(conn, "last_catchup_summary", summary)
            self._set_system_state(conn, "last_catchup_error", None)
            self._set_system_state(conn, "last_heartbeat_ms", now)
            if rows is not None:
                self._set_system_state(conn, "last_candle_1m_ms", now)
        self.daily_learning_check(now)
        self.maybe_daily_backup(now)
        return summary

    def reenable_trading(self) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._get_open_trade(conn):
                raise RuntimeError("Close the open position before re-enabling trading.")
            if not self._verify_ledger(conn):
                raise RuntimeError("Audit ledger verification failed; refusing to re-enable.")
            account = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
            conn.execute(
                """
                UPDATE trading_controls SET peak_equity = ?, drawdown_paused = 0
                WHERE id = 1
                """,
                (float(account["balance"]),),
            )
            self._append_ledger(
                conn,
                "trading_reenabled",
                None,
                {"equity_baseline": float(account["balance"])},
            )
        return self.get_state()

    @staticmethod
    def _validate_position_levels(
        side: str,
        entry: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        liquidation_price: float,
        buffer_pct: float,
    ) -> tuple[float, float]:
        if side not in ("long", "short"):
            raise ValueError("Side must be 'long' or 'short'.")
        if stop_loss is None or take_profit is None:
            raise ValueError("Every paper position requires both a stop-loss and take-profit.")
        if not math.isfinite(buffer_pct) or buffer_pct < 0:
            raise ValueError("Liquidation buffer must be a finite nonnegative percentage.")
        levels = (float(entry), float(stop_loss), float(take_profit), float(liquidation_price))
        if not all(math.isfinite(value) for value in levels) or min(levels[:3]) <= 0 or liquidation_price < 0:
            raise ValueError("Entry, stop, and target must be finite positive prices.")
        entry, stop_loss, take_profit, liquidation_price = levels
        if side == "long":
            correctly_ordered = stop_loss < entry < take_profit
            safely_inside_liquidation = (
                stop_loss - liquidation_price >= entry * buffer_pct / 100
            )
        else:
            correctly_ordered = take_profit < entry < stop_loss
            safely_inside_liquidation = (
                liquidation_price - stop_loss >= entry * buffer_pct / 100
            )
        if not correctly_ordered:
            raise ValueError(
                "Position levels are invalid: long requires stop < entry < target; "
                "short requires target < entry < stop."
            )
        if not safely_inside_liquidation:
            raise ValueError(
                "Stop-loss must remain beyond the configured buffer from liquidation."
            )
        return stop_loss, take_profit

    def _record_trade_event(
        self,
        conn: sqlite3.Connection,
        trade_id: Optional[str],
        decision_id: Optional[str],
        event_type: str,
        details: Dict[str, Any],
        created_at_ms: Optional[int] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO trade_events (
                trade_id, decision_id, event_type, created_at_ms, details_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                decision_id,
                event_type,
                int(created_at_ms or time.time() * 1000),
                json.dumps(details, sort_keys=True, allow_nan=False),
            ),
        )

    @staticmethod
    def _set_system_state(
        conn: sqlite3.Connection, key: str, value: Any
    ) -> None:
        conn.execute(
            """
            INSERT INTO system_state (key, value_json, updated_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at_ms = excluded.updated_at_ms
            """,
            (key, json.dumps(value, sort_keys=True, allow_nan=False), int(time.time() * 1000)),
        )

    @staticmethod
    def _get_system_state(conn: sqlite3.Connection, key: str) -> Any:
        row = conn.execute(
            "SELECT value_json FROM system_state WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def _refresh_memory_feature_stats(
        self, conn: sqlite3.Connection, schema_version: int
    ) -> None:
        rows = conn.execute(
            """
            SELECT feature_vector_json FROM memory_episodes
            WHERE feature_schema_version = ? AND counterfactual = 0
            """,
            (schema_version,),
        ).fetchall()
        vectors: Dict[str, list[float]] = {}
        for row in rows:
            vector = json.loads(row["feature_vector_json"])
            for name, value in vector.items():
                number = float(value)
                if math.isfinite(number):
                    vectors.setdefault(name, []).append(number)
        now = int(time.time() * 1000)
        conn.execute(
            "DELETE FROM memory_feature_stats WHERE feature_schema_version = ?",
            (schema_version,),
        )
        for name, values in vectors.items():
            conn.execute(
                """
                INSERT INTO memory_feature_stats (
                    feature_schema_version, feature_name, mean, stddev,
                    sample_count, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    schema_version,
                    name,
                    float(np.mean(values)),
                    float(np.std(values)),
                    len(values),
                    now,
                ),
            )

    def _add_memory_feature_stats(
        self,
        conn: sqlite3.Connection,
        schema_version: int,
        feature_vector: Dict[str, Any],
    ) -> None:
        now = int(time.time() * 1000)
        for name, value in feature_vector.items():
            number = float(value)
            if not math.isfinite(number):
                continue
            row = conn.execute(
                """
                SELECT mean, stddev, sample_count FROM memory_feature_stats
                WHERE feature_schema_version = ? AND feature_name = ?
                """,
                (schema_version, name),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO memory_feature_stats (
                        feature_schema_version, feature_name, mean, stddev,
                        sample_count, updated_at_ms
                    ) VALUES (?, ?, ?, 0, 1, ?)
                    """,
                    (schema_version, name, number, now),
                )
                continue
            count = int(row["sample_count"])
            previous_mean = float(row["mean"])
            previous_variance = float(row["stddev"]) ** 2
            updated_count = count + 1
            updated_mean = previous_mean + (number - previous_mean) / updated_count
            updated_variance = (
                count
                * (previous_variance + (previous_mean - updated_mean) ** 2)
                + (number - updated_mean) ** 2
            ) / updated_count
            conn.execute(
                """
                UPDATE memory_feature_stats
                SET mean = ?, stddev = ?, sample_count = ?, updated_at_ms = ?
                WHERE feature_schema_version = ? AND feature_name = ?
                """,
                (
                    updated_mean,
                    math.sqrt(max(0.0, updated_variance)),
                    updated_count,
                    now,
                    schema_version,
                    name,
                ),
            )

    def _record_level_rejection(
        self,
        decision_id: Optional[str],
        side: str,
        entry: Any,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        source: str,
        reason: str,
    ) -> None:
        timestamp = int(time.time() * 1000)
        decision_id = decision_id or f"rejected_{uuid.uuid4().hex}"

        def finite_or_none(value: Any) -> Optional[float]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if math.isfinite(number) else None

        entry_value = finite_or_none(entry)
        stop_value = finite_or_none(stop_loss)
        target_value = finite_or_none(take_profit)
        config_hash = hashlib.sha256(
            canonicalize_json(self.full_config).encode("utf-8")
        ).hexdigest()
        plan = {
            "action": "rejected",
            "entry": entry_value,
            "stop_loss": stop_value,
            "take_profit": target_value,
            "reason_if_no_trade": reason,
        }
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE decisions SET decision = 'rejected',
                        rejection_reason = ?, trade_plan_json = ?,
                        proposed_stop = ?, proposed_target = ?
                    WHERE decision_id = ?
                    """,
                    (
                        reason,
                        json.dumps(plan, sort_keys=True, allow_nan=False),
                        stop_value,
                        target_value,
                        decision_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO decisions (
                        decision_id, created_at_ms, symbol, decision, direction,
                        source, model_version, confidence, calibrated_probability,
                        features_json, feature_schema_version, indicator_snapshot_json,
                        proposed_stop, proposed_target, rejection_reason, config_hash,
                        trade_plan_json, memory_json
                    ) VALUES (?, ?, ?, 'rejected', ?, ?, NULL, NULL, NULL, '{}', 1,
                              '{}', ?, ?, ?, ?, ?, '{}')
                    """,
                    (
                        decision_id,
                        timestamp,
                        str(self.full_config.get("symbol", "BTCUSDT")),
                        side if side in ("long", "short") else "neutral",
                        source,
                        stop_value,
                        target_value,
                        reason,
                        config_hash,
                        json.dumps(plan, sort_keys=True, allow_nan=False),
                    ),
                )
            self._record_trade_event(
                conn,
                None,
                decision_id,
                reason,
                {
                    "side": side,
                    "entry": entry_value,
                    "stop_loss": stop_value,
                    "take_profit": target_value,
                    "source": source,
                },
                timestamp,
            )

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
        atr_at_entry: Optional[float] = None,
        sl_atr_mult: Optional[float] = None,
        tp_atr_mult: Optional[float] = None,
        confidence: Optional[float] = None,
        feature_vector: Optional[Dict[str, Any]] = None,
        feature_schema_version: int = FEATURE_SCHEMA_VERSION,
        decision_source: Optional[str] = None,
    ) -> Dict[str, Any]:
        if side not in ("long", "short"):
            raise ValueError("Side must be 'long' or 'short'.")
        if int(leverage) < 1 or int(leverage) > self.max_leverage:
            raise ValueError(
                f"Leverage must be between 1x and {self.max_leverage}x."
            )
        if (
            not math.isfinite(float(entry))
            or not math.isfinite(float(size_btc))
            or entry <= 0
            or size_btc <= 0
        ):
            raise ValueError("Entry price and BTC size must be greater than zero.")

        notional = float(entry) * float(size_btc)
        margin = notional / int(leverage)
        if not math.isfinite(notional) or not math.isfinite(margin):
            raise ValueError("Position notional and margin must be finite.")
        liquidation_price = (
            float(entry) - margin / float(size_btc)
            if side == "long"
            else float(entry) + margin / float(size_btc)
        )
        try:
            stop_loss, take_profit = self._validate_position_levels(
                side,
                float(entry),
                stop_loss,
                take_profit,
                liquidation_price,
                float(self.config.get("stop_liquidation_buffer_pct", 0.2)),
            )
        except ValueError as error:
            rejection_reason = (
                "rejected_missing_levels"
                if stop_loss is None or take_profit is None
                else "rejected_invalid_levels"
            )
            self._record_level_rejection(
                decision_id,
                side,
                entry,
                stop_loss,
                take_profit,
                source,
                rejection_reason,
            )
            raise ValueError(str(error)) from error
        stop_distance = abs(float(entry) - stop_loss)
        target_distance = abs(take_profit - float(entry))
        configured_sl_mult = float(
            sl_atr_mult or self.config.get("sl_atr_mult", 1.5)
        )
        configured_tp_mult = float(
            tp_atr_mult or self.config.get("tp_atr_mult", 2.5)
        )
        if atr_at_entry is None and configured_sl_mult > 0:
            atr_at_entry = stop_distance / configured_sl_mult
        if atr_at_entry is not None and (
            not math.isfinite(float(atr_at_entry)) or float(atr_at_entry) <= 0
        ):
            raise ValueError("ATR at entry must be a finite positive number.")
        if confidence is not None and (
            not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1
        ):
            raise ValueError("Confidence must be a finite probability between 0 and 1.")
        risk_amount = stop_distance * float(size_btc)
        if not math.isfinite(risk_amount) or risk_amount <= 0:
            raise ValueError("Stop-loss risk must be finite and greater than zero.")
        initial_risk = float(initial_risk_usd)
        if not math.isfinite(initial_risk) or initial_risk <= 0:
            initial_risk = risk_amount
        reward_to_risk = target_distance / stop_distance
        feature_vector = feature_vector or {}
        manual_decision = decision_id is None and source == "manual"
        if manual_decision:
            decision_id = f"manual_{uuid.uuid4().hex}"
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
            risk_block = self._risk_block_reason(conn)
            if risk_block:
                raise RuntimeError(risk_block)
            if not self._verify_ledger(conn):
                raise RuntimeError("Audit ledger verification failed; refusing to trade.")
            if margin > account["balance"]:
                raise RuntimeError(
                    f"Insufficient available paper balance for margin ({margin:.2f} required)."
                )
            if manual_decision:
                config_hash = hashlib.sha256(
                    canonicalize_json(self.full_config).encode("utf-8")
                ).hexdigest()
                manual_plan = {
                    "action": side,
                    "entry": float(entry),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "size_btc": float(size_btc),
                    "leverage": int(leverage),
                    "risk_amount_usd": risk_amount,
                }
                conn.execute(
                    """
                    INSERT INTO decisions (
                        decision_id, created_at_ms, symbol, decision, direction,
                        source, model_version, confidence, calibrated_probability,
                        features_json, feature_schema_version, indicator_snapshot_json,
                        proposed_stop, proposed_target, config_hash, trade_plan_json,
                        memory_json
                    ) VALUES (?, ?, ?, 'manual_order', ?, 'manual', NULL, NULL, NULL,
                              '{}', ?, '{}', ?, ?, ?, ?, '{}')
                    """,
                    (
                        decision_id,
                        opened_at,
                        str(self.full_config.get("symbol", "BTCUSDT")),
                        side,
                        int(feature_schema_version),
                        stop_loss,
                        take_profit,
                        config_hash,
                        json.dumps(manual_plan, sort_keys=True, allow_nan=False),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO memory_episodes (
                        id, decision_id, created_at_ms, symbol, side,
                        feature_vector_json, feature_schema_version, entry,
                        stop_loss, take_profit
                    ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?)
                    """,
                    (
                        f"episode_{decision_id}_{side}",
                        decision_id,
                        opened_at,
                        str(self.full_config.get("symbol", "BTCUSDT")),
                        side,
                        int(feature_schema_version),
                        float(entry),
                        stop_loss,
                        take_profit,
                    ),
                )
            conn.execute(
                "UPDATE account SET balance = balance - ? WHERE id = 1", (margin,)
            )
            conn.execute(
                """
                INSERT INTO trades (
                    id, decision_id, side, entry, size, notional, leverage, margin,
                    stop_loss, take_profit, opened_at, initial_risk_usd,
                    source, rationale, status, liquidation_price, atr_at_entry,
                    sl_atr_mult, tp_atr_mult, risk_amount, reward_to_risk,
                    decision_source, confidence, feature_vector_json,
                    feature_schema_version, last_candle_open_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open',
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    initial_risk,
                    source,
                    rationale,
                    liquidation_price,
                    atr_at_entry,
                    configured_sl_mult,
                    configured_tp_mult,
                    risk_amount,
                    reward_to_risk,
                    decision_source or source,
                    confidence,
                    json.dumps(feature_vector, sort_keys=True, allow_nan=False),
                    int(feature_schema_version),
                    opened_at // 60000 * 60000,
                ),
            )
            if decision_id:
                conn.execute(
                    "UPDATE memory_episodes SET position_id = ?, entry = ?, "
                    "stop_loss = ?, take_profit = ?, outcome = 'unresolved', "
                    "counterfactual = 0 WHERE decision_id = ? AND side = ?",
                    (trade_id, float(entry), stop_loss, take_profit, decision_id, side),
                )
            self._record_trade_event(
                conn,
                trade_id,
                decision_id,
                "opened",
                {
                    "side": side,
                    "entry": float(entry),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "liquidation_price": liquidation_price,
                    "risk_amount": risk_amount,
                    "reward_to_risk": reward_to_risk,
                    "decision_source": source,
                    "confidence": confidence,
                },
                opened_at,
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
                    "liquidation_price": liquidation_price,
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
            controls = conn.execute(
                "SELECT * FROM trading_controls WHERE id = 1"
            ).fetchone()
            return {
                "equity": round(float(account["balance"]) + margin, 2),
                "balance": round(float(account["balance"]), 2),
                "starting_equity": float(account["starting_equity"]),
                "reset_at": int(account["reset_at"]),
                "available_balance": round(float(account["balance"]), 2),
                "open_position": self._trade_to_dict(open_trade) if open_trade else None,
                "closed_trades": [self._trade_to_dict(trade) for trade in closed],
                "realized_pnl_by_day": {row["utc_date"]: row["pnl_usd"] for row in daily},
                "trading_controls": dict(controls) if controls else None,
            }

    def get_trades(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        side: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        if limit < 1 or offset < 0:
            raise ValueError("Trade history limit must be positive and offset cannot be negative.")
        conditions = []
        values: list[Any] = []
        for name, value in (("status", status), ("side", side), ("source", source)):
            if value is not None:
                allowed = {
                    "status": ("open", "closed"),
                    "side": ("long", "short"),
                    "source": ("ai", "manual"),
                }[name]
                if value not in allowed:
                    raise ValueError(f"Invalid {name} filter.")
                conditions.append(f"{name} = ?")
                values.append(value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades" + where
                + " ORDER BY opened_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
            return [self._trade_to_dict(row) for row in rows]

    def get_trade_count(
        self,
        status: Optional[str] = None,
        side: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        conditions = []
        values: list[Any] = []
        for name, value in (("status", status), ("side", side), ("source", source)):
            if value is not None:
                allowed = {
                    "status": ("open", "closed"),
                    "side": ("long", "short"),
                    "source": ("ai", "manual"),
                }[name]
                if value not in allowed:
                    raise ValueError(f"Invalid {name} filter.")
                conditions.append(f"{name} = ?")
                values.append(value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM trades" + where, values
            ).fetchone()
            return int(row["count"])

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
            conn.execute(
                """
                UPDATE trading_controls SET peak_equity = ?, drawdown_paused = 0
                WHERE id = 1
                """,
                (float(account["starting_equity"]),),
            )
            conn.execute("DELETE FROM daily_pnl")
            self._append_ledger(
                conn,
                "account_reset",
                None,
                {"starting_equity": account["starting_equity"]},
            )
        return self.get_state()
