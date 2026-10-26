# Mortis data dictionary

The generated section below is regenerated from the configured SQLite database with `python -m tools.gen_data_dictionary`. `Nullable` reflects SQLite's schema constraints; examples are taken from the local database and can be empty. Human-written descriptions above and below the markers are preserved by the generator.

<!-- BEGIN GENERATED SCHEMA -->
### `account`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `id` | `INTEGER` | no | id | `1` | `engine.paper_trader` |
| `balance` | `REAL` | no | balance | `4977.232862331938` | `engine.paper_trader` |
| `starting_equity` | `REAL` | no | starting equity | `10000.0` | `engine.paper_trader` |
| `reset_at` | `INTEGER` | no | reset at (UTC Unix timestamp in milliseconds where applicable) | `0` | `engine.paper_trader` |

### `daily_pnl`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `utc_date` | `TEXT` | no | utc date | `2026-10-13` | `engine.paper_trader` |
| `pnl_usd` | `REAL` | no | pnl usd (US dollars) | `-97.44058232010008` | `engine.paper_trader` |

### `decisions`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `decision_id` | `TEXT` | no | decision id | `dec_1792931915581_2a8782` | `engine.paper_trader` |
| `created_at_ms` | `INTEGER` | no | created at ms (UTC Unix timestamp in milliseconds where applicable) | `1792942233546` | `engine.paper_trader` |
| `symbol` | `TEXT` | no | symbol | `BTCUSDT` | `engine.paper_trader` |
| `decision` | `TEXT` | no | decision | `no_trade` | `engine.paper_trader` |
| `direction` | `TEXT` | no | direction | `short` | `engine.paper_trader` |
| `source` | `TEXT` | no | source | `deterministic_rule_fallback` | `engine.paper_trader` |
| `model_version` | `TEXT` | yes | model version | `—` | `engine.paper_trader` |
| `confidence` | `REAL` | yes | confidence | `0.65` | `engine.paper_trader` |
| `calibrated_probability` | `REAL` | yes | calibrated probability | `—` | `engine.paper_trader` |
| `features_json` | `TEXT` | no | features json (serialized JSON) | `{"15m_atr14": 120.7, "15m_atr_pct": 0.0015, "15m_ema20": 80445.8…` | `engine.paper_trader` |
| `feature_schema_version` | `INTEGER` | no | feature schema version | `1` | `engine.paper_trader` |
| `indicator_snapshot_json` | `TEXT` | no | indicator snapshot json (serialized JSON) | `{}` | `engine.paper_trader` |
| `proposed_stop` | `REAL` | yes | proposed stop | `80824.7` | `engine.paper_trader` |
| `proposed_target` | `REAL` | yes | proposed target | `79657.62` | `engine.paper_trader` |
| `rejection_reason` | `TEXT` | yes | rejection reason | `An open position already exists.` | `engine.paper_trader` |
| `config_hash` | `TEXT` | no | config hash | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` | `engine.paper_trader` |
| `trade_plan_json` | `TEXT` | no | trade plan json (serialized JSON) | `{"action": "no_trade", "clamped_confidence": 0.65, "entry": 8038…` | `engine.paper_trader` |
| `memory_json` | `TEXT` | no | memory json (serialized JSON) | `{"mode": "legacy_unavailable", "n": 0, "neighbors": []}` | `engine.paper_trader` |
| `decision_hash` | `TEXT` | yes | decision hash | `—` | `engine.paper_trader` |
| `previous_decision_hash` | `TEXT` | yes | previous decision hash | `—` | `engine.paper_trader` |

### `ledger`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `sequence` | `INTEGER` | no | sequence | `8` | `engine.paper_trader` |
| `event_id` | `TEXT` | no | event id | `evt_179b52c64ff54dcf8055fbfe9e63b70f` | `engine.paper_trader` |
| `timestamp_utc` | `TEXT` | no | timestamp utc | `2026-10-13T18:07:39.070030+00:00` | `engine.paper_trader` |
| `event_type` | `TEXT` | no | event type | `legacy_import` | `engine.paper_trader` |
| `trade_id` | `TEXT` | yes | trade id | `pos_1791877833759` | `engine.paper_trader` |
| `payload_json` | `TEXT` | no | payload json (serialized JSON) | `{"migrated_closed_trades":0,"migrated_open_position":true,"start…` | `engine.paper_trader` |
| `previous_hash` | `TEXT` | yes | previous hash | `ccaa2f92667239cc4b7e52ae67c27ed85909096fde43c53cbe27aadf78e462bd` | `engine.paper_trader` |
| `record_hash` | `TEXT` | no | record hash | `14f9aca113bb5fa5b91f33bc3258dff02425ca958cf9bd83d71219e9d2b42061` | `engine.paper_trader` |

### `memory_episodes`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `id` | `TEXT` | no | id | `episode_dec_1792931915581_2a8782_short` | `engine.paper_trader` |
| `decision_id` | `TEXT` | no | decision id | `dec_1792931915581_2a8782` | `engine.paper_trader` |
| `position_id` | `TEXT` | yes | position id | `—` | `engine.paper_trader` |
| `created_at_ms` | `INTEGER` | no | created at ms (UTC Unix timestamp in milliseconds where applicable) | `1792931915735` | `engine.paper_trader` |
| `symbol` | `TEXT` | no | symbol | `BTCUSDT` | `engine.paper_trader` |
| `side` | `TEXT` | no | side | `short` | `engine.paper_trader` |
| `feature_vector_json` | `TEXT` | no | feature vector json (serialized JSON) | `{"15m_atr14": 120.7, "15m_atr_pct": 0.0015, "15m_ema20": 80445.8…` | `engine.paper_trader` |
| `feature_schema_version` | `INTEGER` | no | feature schema version | `1` | `engine.paper_trader` |
| `trend_bucket` | `TEXT` | yes | trend bucket | `—` | `engine.paper_trader` |
| `volatility_bucket` | `TEXT` | yes | volatility bucket | `—` | `engine.paper_trader` |
| `entry` | `REAL` | yes | entry | `80387.05` | `engine.paper_trader` |
| `stop_loss` | `REAL` | yes | stop loss | `80824.7` | `engine.paper_trader` |
| `take_profit` | `REAL` | yes | take profit | `79657.62` | `engine.paper_trader` |
| `outcome` | `TEXT` | no | outcome | `unresolved` | `engine.paper_trader` |
| `r_multiple` | `REAL` | yes | r multiple | `—` | `engine.paper_trader` |
| `exit_reason` | `TEXT` | yes | exit reason | `—` | `engine.paper_trader` |
| `mae_r` | `REAL` | yes | mae r (R multiple) | `—` | `engine.paper_trader` |
| `mfe_r` | `REAL` | yes | mfe r (R multiple) | `—` | `engine.paper_trader` |
| `bars_held` | `INTEGER` | no | bars held | `0` | `engine.paper_trader` |
| `resolution_source` | `TEXT` | yes | resolution source | `—` | `engine.paper_trader` |
| `model_version` | `TEXT` | yes | model version | `—` | `engine.paper_trader` |
| `lesson_text` | `TEXT` | yes | lesson text | `—` | `engine.paper_trader` |
| `lesson_source` | `TEXT` | yes | lesson source | `—` | `engine.paper_trader` |
| `counterfactual` | `INTEGER` | no | counterfactual | `1` | `engine.paper_trader` |
| `unresolved_reason` | `TEXT` | yes | unresolved reason | `Legacy candidate requires historical replay.` | `engine.paper_trader` |

### `memory_feature_stats`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `feature_schema_version` | `INTEGER` | no | feature schema version | `—` | `engine.paper_trader` |
| `feature_name` | `TEXT` | no | feature name | `—` | `engine.paper_trader` |
| `mean` | `REAL` | no | mean | `—` | `engine.paper_trader` |
| `stddev` | `REAL` | no | stddev | `—` | `engine.paper_trader` |
| `sample_count` | `INTEGER` | no | sample count | `—` | `engine.paper_trader` |
| `updated_at_ms` | `INTEGER` | no | updated at ms (UTC Unix timestamp in milliseconds where applicable) | `—` | `engine.paper_trader` |

### `schema_migrations`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `version` | `INTEGER` | no | version | `1` | `engine.paper_trader` |
| `applied_at_ms` | `INTEGER` | no | applied at ms (UTC Unix timestamp in milliseconds where applicable) | `1792942256102` | `engine.paper_trader` |
| `description` | `TEXT` | no | description | `Existing SQLite paper-account schema` | `engine.paper_trader` |

### `system_state`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `key` | `TEXT` | no | key | `app_version` | `engine.paper_trader` |
| `value_json` | `TEXT` | no | value json (serialized JSON) | `1792942256123` | `engine.paper_trader` |
| `updated_at_ms` | `INTEGER` | no | updated at ms (UTC Unix timestamp in milliseconds where applicable) | `1792942256123` | `engine.paper_trader` |

### `trade_events`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `id` | `INTEGER` | no | id | `—` | `engine.paper_trader` |
| `trade_id` | `TEXT` | yes | trade id | `—` | `engine.paper_trader` |
| `decision_id` | `TEXT` | yes | decision id | `—` | `engine.paper_trader` |
| `event_type` | `TEXT` | no | event type | `—` | `engine.paper_trader` |
| `created_at_ms` | `INTEGER` | no | created at ms (UTC Unix timestamp in milliseconds where applicable) | `—` | `engine.paper_trader` |
| `details_json` | `TEXT` | no | details json (serialized JSON) | `—` | `engine.paper_trader` |

### `trades`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `id` | `TEXT` | no | id | `pos_1791877833759` | `engine.paper_trader` |
| `decision_id` | `TEXT` | yes | decision id | `dec_1791877833763_3cc1be` | `engine.paper_trader` |
| `side` | `TEXT` | no | side | `short` | `engine.paper_trader` |
| `entry` | `REAL` | no | entry | `83908.03` | `engine.paper_trader` |
| `size` | `REAL` | no | size | `0.059589` | `engine.paper_trader` |
| `notional` | `REAL` | no | notional | `4999.99559967` | `engine.paper_trader` |
| `leverage` | `INTEGER` | no | leverage | `1` | `engine.paper_trader` |
| `margin` | `REAL` | no | margin | `4999.99559967` | `engine.paper_trader` |
| `stop_loss` | `REAL` | yes | stop loss | `84657.43` | `engine.paper_trader` |
| `take_profit` | `REAL` | yes | take profit | `82659.03` | `engine.paper_trader` |
| `opened_at` | `INTEGER` | no | opened at (UTC Unix timestamp in milliseconds where applicable) | `1792931574431` | `engine.paper_trader` |
| `closed_at` | `INTEGER` | yes | closed at (UTC Unix timestamp in milliseconds where applicable) | `1791916776233` | `engine.paper_trader` |
| `exit_price` | `REAL` | yes | exit price | `83026.0` | `engine.paper_trader` |
| `exit_reason` | `TEXT` | yes | exit reason | `manual` | `engine.paper_trader` |
| `pnl_gross` | `REAL` | yes | pnl gross | `52.55928566999993` | `engine.paper_trader` |
| `fee_usd` | `REAL` | yes | fee usd (US dollars) | `149.9998679901` | `engine.paper_trader` |
| `pnl_usd` | `REAL` | yes | pnl usd (US dollars) | `-97.44058232010008` | `engine.paper_trader` |
| `initial_risk_usd` | `REAL` | no | initial risk usd (US dollars) | `79.69` | `engine.paper_trader` |
| `fees_paid_before` | `REAL` | no | fees paid before | `5.0` | `engine.paper_trader` |
| `source` | `TEXT` | no | source | `ai` | `engine.paper_trader` |
| `rationale` | `TEXT` | yes | rationale | `4h EMA trend bearish, 1h RSI (59.8) in sell zone, 15m MACD momen…` | `engine.paper_trader` |
| `status` | `TEXT` | no | status | `closed` | `engine.paper_trader` |
| `liquidation_price` | `REAL` | yes | liquidation price | `160614.6` | `engine.paper_trader` |
| `atr_at_entry` | `REAL` | yes | atr at entry | `—` | `engine.paper_trader` |
| `sl_atr_mult` | `REAL` | yes | sl atr mult | `—` | `engine.paper_trader` |
| `tp_atr_mult` | `REAL` | yes | tp atr mult | `—` | `engine.paper_trader` |
| `risk_amount` | `REAL` | yes | risk amount | `44.65599659999965` | `engine.paper_trader` |
| `reward_to_risk` | `REAL` | yes | reward to risk | `1.666697132411784` | `engine.paper_trader` |
| `decision_source` | `TEXT` | yes | decision source | `—` | `engine.paper_trader` |
| `confidence` | `REAL` | yes | confidence | `—` | `engine.paper_trader` |
| `feature_vector_json` | `TEXT` | no | feature vector json (serialized JSON) | `{}` | `engine.paper_trader` |
| `feature_schema_version` | `INTEGER` | no | feature schema version | `1` | `engine.paper_trader` |
| `levels_backfilled` | `INTEGER` | no | levels backfilled | `0` | `engine.paper_trader` |
| `mae_r` | `REAL` | no | mae r (R multiple) | `0.0` | `engine.paper_trader` |
| `mfe_r` | `REAL` | no | mfe r (R multiple) | `0.0` | `engine.paper_trader` |
| `bars_held` | `INTEGER` | no | bars held | `0` | `engine.paper_trader` |
| `last_candle_open_ms` | `INTEGER` | yes | last candle open ms (UTC Unix timestamp in milliseconds where applicable) | `—` | `engine.paper_trader` |
| `funding_usd` | `REAL` | no | funding usd (US dollars) | `0.0` | `engine.paper_trader` |
| `r_multiple` | `REAL` | yes | r multiple | `-2.1820268214571845` | `engine.paper_trader` |
| `resolution_source` | `TEXT` | yes | resolution source | `—` | `engine.paper_trader` |

### `trading_controls`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `id` | `INTEGER` | no | id | `1` | `engine.paper_trader` |
| `peak_equity` | `REAL` | no | peak equity | `10000.0` | `engine.paper_trader` |
| `drawdown_paused` | `INTEGER` | no | drawdown paused | `0` | `engine.paper_trader` |
| `last_settlement_at_ms` | `INTEGER` | no | last settlement at ms (UTC Unix timestamp in milliseconds where applicable) | `1792940436331` | `engine.paper_trader` |

### `training_samples`

| Column | SQLite type | Nullable | Meaning / units | Example | Writer |
|---|---|---|---|---|---|
| `decision_id` | `TEXT` | no | decision id | `dec_1792931915581_2a8782` | `engine.paper_trader / research pipeline` |
| `created_at_ms` | `INTEGER` | no | created at ms (UTC Unix timestamp in milliseconds where applicable) | `1792931915735` | `engine.paper_trader / research pipeline` |
| `features_json` | `TEXT` | no | features json (serialized JSON) | `{"15m_atr14": 120.7, "15m_atr_pct": 0.0015, "15m_ema20": 80445.8…` | `engine.paper_trader / research pipeline` |
| `decision_json` | `TEXT` | no | decision json (serialized JSON) | `{"calibrated": false, "confidence": 0.65, "direction": "short", …` | `engine.paper_trader / research pipeline` |
| `best_bid` | `REAL` | yes | best bid | `80421.78` | `engine.paper_trader / research pipeline` |
| `best_ask` | `REAL` | yes | best ask | `80421.79` | `engine.paper_trader / research pipeline` |
| `outcome_resolved` | `INTEGER` | no | outcome resolved | `0` | `engine.paper_trader / research pipeline` |
| `outcome_label` | `INTEGER` | yes | outcome label | `—` | `engine.paper_trader / research pipeline` |
| `realized_net_r` | `REAL` | yes | realized net r (R multiple) | `—` | `engine.paper_trader / research pipeline` |
| `pnl_usd` | `REAL` | yes | pnl usd (US dollars) | `—` | `engine.paper_trader / research pipeline` |
| `mistake` | `TEXT` | yes | mistake | `—` | `engine.paper_trader / research pipeline` |
| `quote_status` | `TEXT` | no | quote status | `not_collected` | `engine.paper_trader / research pipeline` |
| `realized_slippage_bps` | `REAL` | yes | realized slippage bps (basis points) | `—` | `engine.paper_trader / research pipeline` |
| `feature_schema_version` | `INTEGER` | no | feature schema version | `1` | `engine.paper_trader / research pipeline` |
| `indicator_snapshot_json` | `TEXT` | no | indicator snapshot json (serialized JSON) | `{}` | `engine.paper_trader / research pipeline` |
| `unresolved_reason` | `TEXT` | yes | unresolved reason | `—` | `engine.paper_trader / research pipeline` |
<!-- END GENERATED SCHEMA -->
