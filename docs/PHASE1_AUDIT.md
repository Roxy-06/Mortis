# Mortis Phase 1 audit

Audit source: the pre-migration SQLite backup and the checked-in source before the Phase 1 changes. The live account database is not migrated by this report.

## Stop-loss and take-profit path

- `engine/risk.py` calculates ATR-based proposed stop and target values for an AI plan. The legacy execution path could still accept absent levels, so the values were not a database invariant.
- `engine/paper_trader.py` stored levels in nullable `trades.stop_loss` and `trades.take_profit` columns. An existing row could therefore represent an open trade without either field. The old manual API contract and form also did not require the operator to provide them.
- `server.py` returned the open trade, but a missing database value naturally remained `null` in the response. The original position card did not render the protective levels prominently.
- A price check could not enforce a level that was not stored. The pre-migration setup did not guarantee stop/target enforcement on every path and did not replay one-minute candles after downtime.
- Phase 1 now validates levels at the position boundary, adds SQLite open-position guards, requires levels in the manual API, applies stop-first candle settlement, and surfaces the levels and missing-level warning in the dashboard.

## Database snapshot

The verified pre-migration backup `data/backups/mortis_20261025_201904.db` has `PRAGMA user_version=1` and passes `PRAGMA integrity_check`. It contains 1 account, 8 trades (5 closed AI, 2 closed manual, 1 open AI), 36 training samples (all 36 unresolved), and 15 hash-linked ledger rows. It has no structured `decisions`, `trade_events`, `memory_episodes`, `memory_feature_stats`, or `system_state` tables.

The records present in the original database are more recent than the older backup. A second consistent backup was made before this implementation's migration work. The backend was listening during inspection and the account continued receiving samples; no live migration was run concurrently with that process.

Legacy `training_samples` store feature and decision JSON. Trade outcomes are linkable only where `trades.decision_id` matches a sample's decision ID. Manual trades have no decision ID. In the inspected snapshot the 8 trades were not linked to any of the 36 legacy samples, so their outcomes cannot be assigned to those samples. Phase 1 migration preserves all rows and backfills structured decision/memory records from the JSON where possible; historical candidates without valid replay levels or available candles remain explicitly unresolved with a reason.

## Training, calibration, and activation

- Research features, labels, walk-forward evaluation, model fitting, and calibration live under `research/`. The training command produces challenger artifacts; it does not make one active.
- `config.yaml` selects a model using `model.active_version`, with `null` selecting the deterministic rule fallback. Risk configuration owns the base risk budget, stop/target ATR multipliers, default leverage, and maximum leverage.
- Training and final-holdout evaluation are operator-run steps. Paper-trial activation requires the existing explicit approval and holdout evidence; the fallback remains uncalibrated and its score does not increase risk or leverage.
- Phase 1 adds a resolved-sample threshold check and retrain command. Candidate generation does not silently bypass the holdout/approval flow.

## Shutdown behavior

Before Phase 1, open positions were persisted, but there was no durable heartbeat/catch-up replay for candles missed while the app was off. Unresolved samples could remain unresolved indefinitely. The new lifecycle records heartbeats, replays closed one-minute candles at startup and cycle boundaries, resolves eligible counterfactuals, and marks candidates that cannot be reconstructed with an explicit reason.

## Source map

- Risk and ATR sizing: `engine/risk.py`
- Persistent schema, position validation, settlement, migrations, and memory: `engine/paper_trader.py`
- API contracts and lifecycle: `server.py`
- Agent decision/execution path: `agents/ta_agent.py`
- Public candle pagination: `tools/market_data.py`
- Manual/open-position UI: `components/ManualTradePanel.tsx`
- Trade details UI: `components/TradeHistoryCard.tsx`
- Memory status UI: `components/MemoryLearningCard.tsx`
