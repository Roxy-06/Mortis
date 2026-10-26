# Mortis Phase 1 Prompt: Mandatory SL/TP, Persistent Memory, and Learning Loop

Paste the prompt below into your IDE agent · Builds on the existing Mortis code, not a rewrite · Date: October 25, 2026

## The prompt

You are working on Mortis, an existing BTCUSDT paper-trading system: Python FastAPI backend, Next.js dashboard, SQLite database, Binance market data, and hash-linked decision records. This is NOT a rewrite. Inspect the existing code first and extend it. Reuse existing tables, modules, the training and calibration pipeline, and the model activation flow wherever they already exist. Do not delete or rename existing tables, columns, or endpoints; add to them with migrations.

### Goals of Phase 1

- Every position has a stop-loss and a take-profit that are stored, enforced, and clearly visible in the UI.
- Every decision, trade, and outcome is stored in a structured, versioned, documented way that the user can browse and export.
- Mortis keeps a persistent memory of past trades that survives restarts and shutdowns, retrieves similar past situations before each decision, and feeds the result back into decisions safely.
- Outcomes are resolved automatically, including for time when the app was switched off, so learning does not stop when the laptop is closed.
- The dashboard shows all of the above.

### Ground rules

- Paper trading only. Do not add real order placement, trading keys, or withdrawal logic.
- Back up the database before any migration by copying it to `data/backups/mortis_YYYYMMDD_HHMMSS.db`. Migrations must be versioned (a `schema_migrations` table), additive, and idempotent.
- No lookahead. Anything computed at time t may use only candles closed at or before t.
- Learning must never increase risk. Memory may add information, veto a trade, or reduce size. It must never raise leverage, raise position size above the base size, or loosen a stop.
- Be honest in the UI and docs. Show the sample size (n) next to every statistic. Show 'insufficient history' instead of a number when n is too small. Label AI-written lessons as hypotheses.
- Work in small commits. Run `pytest` and the frontend lint/build after each workstream.
- If something is ambiguous, write your assumption in `docs/PHASE1_NOTES.md` and continue. Stop and ask only if an action would delete data or change money logic in a way not described here.

### Step 0: Audit before changing any code

Create `docs/PHASE1_AUDIT.md` answering the questions below with file paths and line references.

- Why does the user see an open trade with no visible stop-loss or take-profit? Trace the full path: risk calculation, position creation, database columns, API response, frontend component. State exactly where the levels are dropped, never computed, or not displayed. Confirm whether the paper trader enforces them when price crosses.
- Which tables exist today, with columns and row counts? What do the training samples (about 34, unresolved), decisions, positions, and trades contain, and how do outcomes link back to decisions?
- What do the existing training, calibration, and model activation flow do? Which config keys control them, and which steps are manual?
- What happens to open positions and unresolved samples when the app is off for hours?

Then proceed with the workstreams below.

### Workstream A: Mandatory stop-loss and take-profit

- A1. Each position record must store: side, entry\_price, entry\_time, size and notional, leverage, margin, liquidation\_price, stop\_loss, take\_profit, atr\_at\_entry, sl\_atr\_mult, tp\_atr\_mult, risk\_amount, reward\_to\_risk, decision\_id, decision\_source (model version or fallback), and confidence. Add any missing columns by migration.
- A2. Create one validation function used by every code path that can open a position (autonomous loop, chat endpoint, anything else). Reject an order unless stop and target are finite numbers on the correct side of entry (long: stop below entry below target; short: target below entry below stop), and the stop sits safely inside the liquidation price with a buffer. A rejected order is logged as a decision with reason `rejected_missing_levels` or `rejected_invalid_levels`. A position must be impossible to insert without both levels (code check plus NOT NULL for new rows).
- A3. Legacy open positions without levels: compute them from ATR at entry if available, otherwise from current ATR, set `levels_backfilled = true`, and log an event. Never leave an open position without levels.
- A4. Enforcement: on every price check, compare price to stop and target. On every cycle also fetch 1m candles since the last check and test their high and low, so wicks between samples are not missed. If both levels fall in one candle, assume the stop was hit first. If a candle opens beyond a level (gap), fill at the open price.
- A5. On close, store exit\_price, closed\_at, exit\_reason (`stop_loss`, `take_profit`, `liquidation`, `manual`, `timeout`, or a `catchup_` variant), realized\_pnl, fees, funding, and r\_multiple. While a position is open, track max adverse excursion (MAE) and max favorable excursion (MFE) in R. These are valuable for learning.
- A6. If leverage still depends on model confidence anywhere, cap it using config (`max_leverage` default 5, `default_leverage` default 2) and record that change in `docs/PHASE1_NOTES.md`.

### Workstream B: Structured storage and documentation

- B1. Decisions table: one row per cycle, including no-trade cycles. Store timestamp, symbol, decision, source, model\_version, confidence, calibrated probability if any, feature vector JSON with a `feature_schema_version`, indicator snapshot, proposed stop and target, rejection reason, config hash, and the existing hash-chain fields.
- B2. Append-only `trade_events` table: opened, levels\_backfilled, closed, catch-up closed, memory\_veto, and so on, each with timestamp and JSON details.
- B3. `docs/DATA_DICTIONARY.md`: every table and column with type, meaning, units, nullable, example value, and which module writes it. Add `python -m tools.gen_data_dictionary` that regenerates the schema portion from the live database so the document cannot drift, while preserving hand-written descriptions.
- B4. Read-only API with filters and pagination: `GET /api/trades`, `GET /api/trades/{id}`, `GET /api/decisions`, `GET /api/memory/episodes`, `GET /api/memory/stats`. Add an export tool: `python -m tools.export --table trades --format csv|json --out PATH`. Add `docs/QUERIES.md` with about 10 useful SQL queries (win rate by exit reason, average R by hour, trades by regime, and similar).
- B5. Automatic daily database backup, keeping the last 14 (configurable).

### Workstream C: Persistent learning memory (RAG-style)

Market state is numeric, so retrieval uses numeric similarity over stored feature vectors rather than text embeddings. No external vector database is needed; SQLite is the source of truth and an in-memory index is rebuilt from it.

- C1. Table `memory_episodes`: id, decision\_id, position\_id (nullable), created\_at, symbol, side considered, feature\_vector JSON, feature\_schema\_version, regime tags (trend bucket, volatility bucket), entry/stop/target levels, outcome (`win`, `loss`, `timeout`, `unresolved`), r\_multiple, exit\_reason, MAE, MFE, bars\_held, resolution\_source (`live`, `catchup_replay`, `counterfactual`), model\_version, lesson\_text (nullable), lesson\_source (`rule` or `llm`). Counterfactual episodes (skipped or no-trade candidates resolved by simulation) must be flagged so they can be filtered or down-weighted.
- C2. `retrieve_similar(feature_vector, side, k=20)`: standardize features with statistics stored for that `feature_schema_version`, compute distance with numpy, filter to the same side and schema version, exclude the query's own episode and neighbors too close in time (default: within 24 bars) so near-duplicates do not count as independent evidence, and apply time-decay weights (configurable half-life). Return the neighbors with distances plus aggregates: n, effective n, weighted win rate shrunk toward the global win rate (prior strength configurable), average R, standard deviation, a bootstrap confidence interval, and `sufficient = effective n >= min_n`.
- C3. Persistence: on startup load all episodes, rebuild the index, and log 'Memory restored: N episodes (R resolved, U unresolved), schema vX, last catch-up at T'. Save the same summary to `system_state` so the UI can show it. Support incremental adds without a full rebuild.
- C4. Use in decisions, safely. Config `memory.mode` is `off`, `advisory`, or `gate`, with default `advisory`.
  - Always store the retrieved analogs and aggregates in the decision record, and give them to Gemini (if used) as clearly labeled data, for example 'historical analogs: n=24, shrunk win rate 0.41, avg R -0.2'.
  - In `gate` mode and only when `sufficient` is true: if the shrunk win rate is clearly below this trade's breakeven probability, veto with reason `memory_veto`; if marginally below, reduce size (never below 0.5x). Breakeven is computed from the actual stop, target, and costs: `p_be = (1 + c) / (1 + R_tp)`, where R\_tp is target distance divided by stop distance and c is round-trip cost in R.
  - Memory never increases size, leverage, or widens stops.
- C5. Lessons: after each closed trade, write a rule-based lesson (regime, outcome, exit reason, MAE/MFE, and whether price reached +1R before the stop hit, which suggests the stop or target placement may be a problem). If a Gemini key is configured, also store a short LLM reflection. Show lessons in the UI labeled as hypotheses. Lessons are never numeric inputs to decisions; the statistics are.
- C6. If the feature set changes, bump `feature_schema_version`. Never mix episodes across versions. Provide `python -m tools.rebuild_memory` to recompute vectors for old episodes from stored snapshots when possible.
- C7. Document the design, limits, and tuning knobs in `docs/MEMORY.md`, including a plain statement that memory with few samples is advisory and not evidence of an edge.

### Workstream D: Resolution and catch-up so learning continues across shutdowns

- D1. Add a `system_state` table with last\_heartbeat, last processed candle per timeframe, last\_catchup\_at, and app\_version. Update the heartbeat every cycle and on graceful shutdown.
- D2. Implement `catch_up()` and run it on startup and at the start of every cycle. Fetch candles since last\_heartbeat (paginate if needed). Then: (a) for each open position replay candles in order and close it if stop, target, or liquidation was hit, using the Workstream A rules (stop first on conflict, gap fills at open, exit time from the candle), updating the paper account; (b) resolve unresolved samples and episodes by triple-barrier simulation using their recorded stop and target, or the configured ATR rule if missing, with a maximum holding period; (c) write `trade_events` and set `resolution_source` correctly.
- D3. Resolve the existing unresolved samples (about 34) this way and link outcomes back to their decisions and positions. Record counts before and after in `docs/PHASE1_NOTES.md`.
- D4. Catch-up must be idempotent: running it twice makes no further changes.
- D5. After catch-up, show a dashboard banner such as 'While the app was off: closed 1 position, resolved 12 samples.'

### Workstream E: Wire outcomes into the existing training pipeline

- E1. Feed resolved outcomes (live trades and counterfactual episodes, clearly marked) into the existing training and calibration pipeline. Do not build a second pipeline.
- E2. Add a `retrain` command and a daily check. When new resolved samples since the last training are at least `retrain_min_new` (default 50) and total resolved samples are at least `min_total_for_training` (default 200), train a challenger using the existing code with time-ordered validation only (no random splits). Save artifacts with metadata: training range, sample counts, metrics, git hash, feature\_schema\_version.
- E3. Promotion gate: a challenger becomes active only if it passes thresholds in config (minimum out-of-sample samples, calibration error below a limit, and net expectancy above the fallback baseline on time-ordered validation). Otherwise it stays a challenger and the UI says why. `active_version` stays null until one passes. Never activate silently; log every activation or rollback as an event and provide a rollback command.
- E4. Until a model is active, the rule-based fallback runs. Label its confidence 'uncalibrated' in the UI, and do not let it drive leverage or position size beyond the base.

### Workstream F: Dashboard

- F1. Open position card: side, entry, mark price, **stop loss** and **take profit** prominently, each with distance in percent and in R; unrealized PnL in dollars, percent, and R; leverage; liquidation price; size; time open; decision source; confidence labeled calibrated or uncalibrated; MAE and MFE so far. If any open position lacks stop or target, show a red 'MISSING LEVELS' badge (this should never occur).
- F2. If a price chart exists, draw horizontal lines for entry, stop, target, and liquidation. If not, add a compact range bar showing where price sits between stop and target.
- F3. Closed trades table: opened and closed times, side, entry, exit, stop, target, exit\_reason, PnL, R, bars held. Clicking a row opens detail with decision features, the analogs that were retrieved, and the lesson (labeled hypothesis).
- F4. Memory and Learning panel: episodes total, resolved, unresolved, and counterfactual; rolling win rate and average R with n; memory mode; last restore time; last catch-up summary; active model version or 'none (fallback)'; challenger status with the reason it is or is not active; calibration status.
- F5. Decision detail view: show the analogs used (n, shrunk win rate, average R, nearest few trades) and whether memory vetoed or reduced size.
- F6. Low-data states must be honest, for example 'Insufficient history (n=12, need 30)'.
- F7. Use the existing refresh mechanism and avoid heavy new dependencies.

### Config additions

Add to `config.yaml` (merge with existing keys, do not duplicate):

```yaml
risk:
  default_leverage: 2
  max_leverage: 5
  require_stop_and_target: true
  stop_liquidation_buffer_pct: 0.2
memory:
  mode: advisory        # off | advisory | gate
  k: 20
  min_n: 30
  min_gap_bars: 24
  half_life_days: 90
  prior_strength: 20
  min_size_multiplier: 0.5
catchup:
  enabled: true
  max_holding_bars: 48
learning:
  retrain_min_new: 50
  min_total_for_training: 200
  auto_promote: true          # only if the gate passes
  max_calibration_error: 0.08
backup:
  daily: true
  keep: 14
```

### Tests required

- Opening without stop or target (or on the wrong side) is rejected through every entry path, including the chat endpoint.
- Stop hit, target hit, both in one candle (stop first), gap through stop (fill at open), and liquidation each produce the correct exit\_price, exit\_reason, PnL, and R.
- Catch-up: open a position, simulate downtime with candles that cross the stop, run catch-up, and verify the position is closed correctly; run it again and verify nothing changes.
- Retrieval: no self-match, no near-in-time neighbors, schema-version filtering, shrinkage toward the global rate when n is small, and `sufficient` false when n is below `min_n`.
- Memory never increases size or leverage (property test over random inputs).
- Migrations are idempotent and a backup is created first.
- Restart persistence: write episodes, restart, and confirm the memory restored count matches.
- API endpoints return correct filtered, paginated data; export produces valid CSV and JSON.

### Acceptance criteria

- The dashboard shows stop-loss and take-profit for every open position, and no open position can exist without them.
- Closing the app with an open position and reopening after price crossed a level results in that position being closed correctly with a `catchup_` exit reason and an explanatory banner.
- The existing unresolved samples are resolved or explicitly marked unresolvable with a reason.
- Memory restores on startup, and the UI shows episode counts and last restore time.
- Decision records include retrieved analogs and aggregates; in `advisory` mode memory changes no trades.
- `docs/PHASE1_AUDIT.md`, `docs/PHASE1_NOTES.md`, `docs/DATA_DICTIONARY.md`, `docs/MEMORY.md`, and `docs/QUERIES.md` exist and are accurate.
- `pytest` and the frontend build pass.

### Deliverables and final report

When finished, write a short summary listing what changed, what is still manual, known limitations, and the exact commands to run catch-up, export data, rebuild memory, and retrain. State plainly that persistent memory improves record-keeping and risk control but does not by itself create a profitable edge.

### Out of scope for Phase 1

Real-money trading, new indicators or features, the historical backtester (Phase 2), rewriting the agent, or changing risk percentages beyond the safety caps above.
