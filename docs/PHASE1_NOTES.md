# Phase 1 implementation notes

## Assumptions and decisions

- Mortis remains paper-only. No order placement, exchange credentials, wallet, or withdrawal behavior was added.
- UTC timestamps and closed one-minute Binance candles are used for settlement replay. On an intrabar stop/target conflict, stop wins; a gap through a level fills at that candle's open.
- The default memory gap is 24 decision bars at the existing 15-minute strategy cadence. Memory is advisory by default and cannot increase size, leverage, or loosen levels.
- Counterfactuals are simulated from their saved entry/stop/target plan with round-trip paper fees. If no candidate size was proposed, they use a normalized 1 BTC unit for R-label calculation; this is not a simulated account fill. Candidates without valid levels or a replayable candle window remain unresolved and have a reason recorded.
- No automatic model activation was introduced. Existing explicit final-holdout review and paper-trial approval remain required; this avoids activating a candidate merely because an in-sample threshold was met.
- If historical samples lack a link to a trade or a replayable candidate plan, their outcome is not fabricated. They are retained and marked unresolvable when the replay horizon expires.

## Safety and migration

- The v2 migration is additive and idempotent. It takes a SQLite online backup before schema changes and records versions in `schema_migrations` and `PRAGMA user_version`.
- The original verified backup `data/backups/mortis_20261025_201904.db` has 36 unresolved samples, 8 trades, and 15 ledger rows. Before subsequent migration work, a second online backup `data/backups/mortis_20261025_203737.db` was created; it passed `PRAGMA integrity_check` and contained 51 samples at that point. The original process remained bound to ports 8000/3001, so the live database was intentionally not migrated while it was in use.
- Before the upgraded backend is deployed, stop the old backend, make sure `data/mortis.db` is backed up, then start the upgraded server once. Confirm the startup log and `/api/memory/stats`; retain both backups until the resulting account balances and original trade/ledger counts are checked.
- Legacy trades and samples remain in the same SQLite file. The new migration does not reset balances or delete records.

## Risk configuration

- Leverage remains deterministic: `risk.default_leverage` defaults to 2 and `risk.max_leverage` defaults to 5. Model confidence does not raise leverage.
- Stop and target remain the configured ATR multiples (`risk.sl_atr_mult`, `risk.tp_atr_mult`). No base risk percentage was increased.
- Rule-fallback confidence is explicitly uncalibrated and is capped at the base sizing threshold.

## Learning and model limitations

- The daily learning check only reports whether resolved sample thresholds are met. Run `python -m tools.retrain --start YYYY-MM-DD --end YYYY-MM-DD` to create challengers from the existing research pipeline.
- Retraining requires prepared historical candle and funding data. A candidate is not automatically active; final holdout evidence and explicit paper-trial approval remain mandatory.
- A replayed counterfactual is simulated, not an executed trade. Training metadata and feedback rows label counterfactual feedback separately.
- No claim of profitability follows from a backtest, memory match, or paper result. Few samples are advisory, not evidence of an edge.

## Commands

```powershell
python -m pytest -q
python -m tools.rebuild_memory
python -m tools.retrain --check
python -m tools.retrain --start 2020-01-01 --end 2024-01-01
python -m tools.export --table trades --format csv --out exports\trades.csv
python -m tools.export --table decisions --format json --out exports\decisions.json
python -m tools.gen_data_dictionary
```
