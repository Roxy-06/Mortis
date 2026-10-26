# MOTS / Mortis: System and Trading-Behavior Guide

> **Repository-grounded technical guide.** This document describes the application in this repository as implemented, not a proposed future design. The repository names the product **Mortis**; “MOTS” is treated here as the user's name for this system. Trading described below is simulated paper trading only.

## Contents

1. [Executive summary](#executive-summary)
2. [What the system does—and does not do](#what-the-system-doesand-does-not-do)
3. [Technology stack](#technology-stack)
4. [Architecture and data flow](#architecture-and-data-flow)
5. [Market data and environmental inputs](#market-data-and-environmental-inputs)
6. [Indicators and analysis features](#indicators-and-analysis-features)
7. [Decision model and fallback behavior](#decision-model-and-fallback-behavior)
8. [Trade entry and position sizing](#trade-entry-and-position-sizing)
9. [Position monitoring and exits](#position-monitoring-and-exits)
10. [Risk controls and configuration](#risk-controls-and-configuration)
11. [Persistence, audit records, and verification](#persistence-audit-records-and-verification)
12. [Dashboard and API capabilities](#dashboard-and-api-capabilities)
13. [API keys and environment configuration](#api-keys-and-environment-configuration)
14. [How to run it](#how-to-run-it)
15. [Current capabilities and boundaries](#current-capabilities-and-boundaries)
16. [Implementation caveats and discrepancies](#implementation-caveats-and-discrepancies)
17. [Repository map](#repository-map)

## Executive summary

Mortis is a local BTC/USDT market-analysis and **paper-trading** application. A Python process periodically obtains public Binance market data, derives technical indicators for the 4-hour, 1-hour, and 15-minute intervals, and asks a configured Google Gemini model for a directional proposal when a Gemini API key is available. If Gemini is not configured or its response cannot be used, a deterministic technical-analysis fallback makes the proposal instead.

That proposal is not itself an order. Python code applies confidence thresholds, estimates an ATR-based stop and target, calculates a simulated position size and leverage, checks account guards, and—if allowed—opens a simulated position in a local SQLite account. The account polls public prices and closes positions when its programmed stop, target, or simulated margin-loss condition is reached. A local web dashboard exposes market, account, history, and manual paper-trading views.

At a high level:

> **Market data informs a model or rule-based proposal; deterministic code controls the simulated trade; local records preserve the outcome.**

There is no exchange order placement, wallet, on-chain transaction, or custom model training in the current implementation.

## What the system does—and does not do

### It does

- Reads BTC/USDT prices and closed candlesticks from public Binance endpoints.
- Computes technical-analysis indicators on 4h, 1h, and 15m candles.
- Produces a long, short, or neutral AI/rule-based proposal.
- Applies deterministic risk calculations and paper-account checks.
- Simulates AI-originated and user-entered BTC/USDT positions.
- Applies simulated fees, leverage, reserved margin, stop/target settlement, and liquidation loss caps.
- Stores account and trade state in a local SQLite database.
- Writes hash-based decision records and append-only-style audit ledger events.
- Presents a local Next.js dashboard and FastAPI endpoints.

### It does not

- Send real buy/sell orders or connect to an exchange account.
- Manage real funds, a wallet, or private keys.
- Use news, social sentiment, on-chain data, order-book depth, macroeconomic calendars, or user portfolio data to decide AI trades.
- Run multiple independent AI agents or a news/lead-agent consensus in the active decision path.
- Train or fine-tune Gemini, or learn from previous outcomes.
- Provide a calibrated probability of success, a profit guarantee, or financial advice.
- Provide a backtesting engine in the current implementation.
- Make its local hash records externally immutable. SHA-256 hashing is local tamper evidence, not a public blockchain.

## Technology stack

| Area | Technologies in this repository | Role |
|---|---|---|
| User interface | Next.js 14, React 18, TypeScript 5, Tailwind CSS, Lucide icons | Local dashboard and same-origin API proxy routes |
| Python API | Python, FastAPI, Uvicorn, Pydantic | HTTP API and lifecycle-managed autonomous trading worker |
| Market/data analysis | `requests`, pandas, NumPy | Public Binance REST calls, candle tables, and indicator calculations |
| AI provider | Google Gen AI Python SDK (`google-genai`) | Optional call to the Gemini Generative Language API |
| Risk and trade engine | Python standard library and repository modules | Deterministic sizing, risk checks, and simulated settlement |
| Persistence | SQLite via Python `sqlite3` | Paper-account, trade, daily P&L, and event-ledger storage |
| Decision proof | Python `hashlib` SHA-256 and canonical JSON | Per-decision hashes and local hash-linked records |
| Configuration | YAML (`PyYAML`), environment variables, `python-dotenv` | Strategy parameters and local runtime settings |
| Tests | pytest | Python API, risk, paper-trading, and hashing tests |

`requirements.txt` also lists packages such as `streamlit`, `google-generativeai`, and `httpx`; their presence in the dependency manifest does not mean they are the active frontend or primary Gemini integration. The visible web application is Next.js/React, and the current agent imports `google.genai` from `google-genai`.

## Architecture and data flow

```text
Browser
  │
  ├── Next.js dashboard (localhost:3001)
  │     └── Next.js /api/* proxy routes
  │             └── FastAPI Python service (127.0.0.1:8000)
  │
  └── dashboard views: account, market snapshot, trade history,
      manual paper trade, chat/analysis, and audit ledger

FastAPI / autonomous worker
  └── TAAgent.analyze_and_trade()
        ├── Binance public ticker + closed klines
        ├── pandas/NumPy indicator calculations
        ├── Gemini API, if configured; otherwise deterministic fallback
        ├── deterministic ATR-based risk calculation
        ├── paper-account guards and position opening
        ├── decision JSON + SHA-256 decision record
        └── SQLite trade/event ledger

Autonomous loop
  ├── analyze once every 900 seconds (15 minutes)
  └── while waiting, poll price and settle open paper position
      every 5 seconds by default
```

### Main evaluation cycle

1. `TAAgent` fetches the current public BTCUSDT ticker price.
2. It fetches 300 klines for each configured strategy timeframe (4h, 1h, 15m) and removes candles whose close time is still in the future.
3. It computes each timeframe's indicator snapshot.
4. It hashes a compact digest of the last five open-time/close pairs per timeframe.
5. It calls Gemini with the system instructions and indicator snapshot if `GEMINI_API_KEY` is present and appears long enough; otherwise, or on an exception/invalid response, it uses the deterministic fallback.
6. It settles any already-open position against the current fetched price, reads account state, and checks whether opening is blocked.
7. It calls the deterministic risk engine to get a paper trade plan. An open-position or daily-loss guard can turn a proposed trade into `no_trade`.
8. It writes a decision record, including `no_trade` decisions.
9. It opens a simulated position only when the final action is `long` or `short`.

The strategy loop is implemented in [engine/loop.py](./engine/loop.py), with the end-to-end analysis flow in [agents/ta_agent.py](./agents/ta_agent.py).

### Service lifecycle and polling

- `server.py` starts FastAPI on `127.0.0.1:8000` when run as a script.
- When the FastAPI lifespan starts, it starts a background worker unless `MORTIS_AUTOTRADE_ENABLED` is false-like.
- The worker performs a strategy cycle and then monitors the position between cycles. Defaults are a 900-second analysis interval and 5-second settlement polling.
- The dashboard independently refreshes account and market snapshot data about every 4 seconds. Those endpoints may also settle an open position as a side effect.
- `python server.py --once` is not a supported command: the `--once` option belongs to `engine/loop.py` when that module is run directly. The normal documented service command is `python server.py`.

## Market data and environmental inputs

### External market data

The active strategy symbol is hard-coded as `BTCUSDT` in several places. The market-data module tries these public Binance REST hosts in order:

1. `https://data-api.binance.vision`
2. `https://api.binance.com`

It requests:

- `/api/v3/ticker/price` for a current ticker price.
- `/api/v3/klines` for candle history.

The strategy uses 300 candles per interval through the fetch helper's default request limit. The YAML setting `candles_per_timeframe` exists, but the current agent does not pass that value through; its requests use the fetch function's fixed/default 300 limit.

The candle fetcher converts OHLCV fields to numeric values and filters out not-yet-closed candles. The live ticker price is separate from the last closed candle close and is used as the approximate entry/reference price.

### Inputs that can affect decisions or operation

| Input | Where it matters | Effect |
|---|---|---|
| BTCUSDT ticker price | Entry price, account valuation, and settlement | Changes simulated entry or current position P&L/exit checks |
| Closed 4h/1h/15m OHLCV candles | Indicators and Gemini/fallback proposal | Changes the trend/momentum/volatility context |
| Candle timestamps and market availability | Kline collection | API failure or insufficient data can prevent an analysis cycle |
| Gemini response | AI proposal when configured | Supplies direction, confidence, and rationale, subject to shape/range validation |
| `GEMINI_API_KEY` | Agent initialization | Enables an attempt to call Gemini; missing key selects fallback |
| `GEMINI_MODEL` | Gemini call and health metadata | Selects the model identifier; defaults to `gemini-2.5-flash` |
| `MORTIS_AUTOTRADE_ENABLED` | FastAPI startup | Starts/stops autonomous strategy loop; manual API trades remain separately available |
| `MORTIS_DATA_DIR` | PaperTrader initialization | Selects the local directory containing `mortis.db` |
| `config.yaml` | Risk calculation | Supplies confidence, ATR, size, notional, leverage, slippage, and fee parameters (subject to noted hard-coded exceptions) |
| Current UTC date | PaperTrader daily-loss guard | Selects the daily P&L bucket and applies the daily loss stop |
| Local SQLite ledger integrity | Position/account mutation | Trade mutations are refused if the ledger fails its internal hash-chain validation |
| Network reachability/API responses | Market fetch and optional model call | Binance failure can abort analysis; Gemini failure falls back to deterministic rules |

No news feed or sentiment variable currently influences a trade. The dashboard news card explicitly shows the feed as unconfigured.

## Indicators and analysis features

The indicator implementation is in [tools/indicators.py](./tools/indicators.py). Each timeframe requires at least 200 candles; otherwise indicator computation raises an error.

For each timeframe, Mortis computes:

- **EMA 20, EMA 50, EMA 200** from close prices.
- **RSI 14** using exponentially weighted smoothing with Wilder-style alpha (`1/period`); missing/undefined values are filled with 50.
- **ATR 14** from true range: maximum of high-low, absolute high-previous-close, and absolute low-previous-close; smoothed with alpha `1/period`.
- **ATR percentage** as ATR divided by last close.
- **MACD 12/26/9**: fast EMA minus slow EMA, an EMA signal line, and histogram. It also records whether the latest histogram is greater than the prior one.
- **Volume ratio**: most recent volume divided by the mean of the preceding 20 candles (or the available average if fewer rows).
- **Swing support/resistance**: local extrema in the last 100 candles, using a three-candle window on each side; nearest support below and resistance above current close are returned when found.
- **Trend flags**: latest close above EMA50; EMA20 above EMA50; EMA50 above EMA200.

The high-level intended timeframe interpretation is:

- **4h:** wider trend context.
- **1h:** setup context and ATR used for risk distances.
- **15m:** shorter-term momentum/entry timing.

This is not a full chart-pattern, order-book, or market-microstructure system. Although the UI displays timeframe signals and candles, those displayed diagnostics should not be confused with additional independent predictive agents.

## Decision model and fallback behavior

### Gemini path

The configured model defaults to **`gemini-2.5-flash`**, overridable with `GEMINI_MODEL`. The app does not contain the model weights; it sends a request to Google's hosted Gemini API. The agent uses a low temperature (`0.2`) and asks for JSON output.

The system instruction requests JSON with:

```json
{
  "direction": "long | short | neutral",
  "confidence": 0.0,
  "rationale": "At most three concise sentences"
}
```

The actual request contains a user-analysis message (truncated to 1,000 characters) and a JSON serialization of the current snapshot. The instructions tell Gemini to prefer the 4h trend, use 1h setup quality and 15m timing, and choose neutral when conditions conflict or are weak. They explicitly state that confidence is a setup rating, not a probability, and that the model must not calculate stops, targets, or size.

The application manually validates that:

- Direction is `long`, `short`, or `neutral`.
- Confidence is a finite number from 0 through 1.
- Rationale is a string.

It strips simple Markdown code fences before parsing. A missing/invalid key, SDK/API exception, malformed JSON, or invalid output triggers the deterministic fallback. This fallback is not a second ML model.

### Deterministic fallback

When Gemini is unavailable, the fallback checks:

- **Bullish 4h:** price above EMA50 **and** EMA20 above EMA50.
- **Bearish 4h:** price not above EMA50 **and** EMA20 not above EMA50.
- **Long proposal:** bullish 4h, 1h RSI below 65, and 15m MACD histogram rising.
- **Short proposal:** bearish 4h, 1h RSI above 35, and 15m MACD histogram not rising.
- Otherwise: neutral.

The fallback assigns a fixed confidence of `0.65` to qualifying long/short proposals and `0.50` to neutral. It does not produce learned or calibrated confidence. Note that the implementation uses the listed EMA/RSI/MACD rules; it does not combine every computed indicator into this rule-based decision.

### What can change the AI proposal

The Gemini proposal can change with:

- The latest calculated indicators and price snapshot.
- Gemini model version/behavior.
- `GEMINI_API_KEY` availability and Gemini service/API response.
- The optional analysis text supplied through the chat endpoint (up to 1,000 characters).
- The system prompt and its version in source.

The current API `/api/chat` calls `analyze_and_trade` rather than providing a read-only conversational analysis. As a result, a chat analysis request may also produce a decision record and open a simulated position if the proposal passes the controls.

The risk engine can subsequently reject or constrain a valid model proposal. Its decision does not depend on Gemini performing financial arithmetic.

## Trade entry and position sizing

The main implementation is in [engine/risk.py](./engine/risk.py). It treats the model/rule output as a proposal and creates a simulated trade plan.

### Entry gates

1. **Neutral direction:** always `no_trade`.
2. **Confidence:** the confidence is capped by `confidence_cap` (default 0.95), then must meet `confidence_threshold` (default 0.55).
3. **ATR stop distance:** the 1h ATR is multiplied by `sl_atr_mult` (default 1.5); a non-positive distance results in `no_trade`.
4. **Fee-to-target check:** the target distance must be greater than the entry notional's configured round-trip-fee rate; otherwise the setup is rejected.
5. **Account guard:** an existing open position or daily-loss stop blocks a new AI position.
6. **PaperTrader validations:** the account independently enforces one open position, available margin, supported leverage, ledger validity, and the daily loss limit when opening.

### Entry price and price levels

For configured slippage `s` and observed price `P`:

- Long simulated entry: `P × (1 + s)`.
- Short simulated entry: `P × (1 - s)`.

With `A` as 1h ATR, stop multiplier `S` and target multiplier `T`:

- Stop distance: `A × S`.
- Target distance: `A × T`.
- Long stop: `entry − stop distance`; long target: `entry + target distance`.
- Short stop: `entry + stop distance`; short target: `entry − target distance`.

Defaults are 1.5 ATR for the stop and 2.5 ATR for the target. The risk engine estimates these levels; the paper trader later monitors them against sampled ticker prices.

### Position size

The risk budget is based on equity, base risk percent, and a confidence multiplier:

```text
size_multiplier =
  min(max_size_multiplier,
      max(1, 1 + 0.5 × (clamped_confidence − confidence_threshold)
                   / (1 − confidence_threshold)))

risk_budget = account_equity × base_risk_pct × size_multiplier
risk_per_BTC = stop_distance + entry × fee_pct_round_trip
size_BTC = risk_budget / risk_per_BTC
```

The size is limited by the configured notional ceiling:

```text
max_notional = equity × max_notional_pct × selected_leverage
```

If the calculated notional exceeds that ceiling, size is reduced and the `capped_by_notional` flag is set. The final BTC size is rounded down to eight decimal places. `risk_amount_usd` is the estimate based on stop distance plus the fee component used by the sizing calculation.

### Leverage selection

For AI trades, leverage is automatically selected from supported tiers based on clamped confidence:

| Confidence minimum | Desired tier |
|---:|---:|
| 0.55 | 1x |
| 0.70 | 5x |
| 0.80 | 10x |
| 0.85 | 20x |
| 0.90 | 100x |
| 0.95 | 200x |

The selected tier is reduced if a simple stop-distance-derived ceiling is lower. The code aims to keep the stop distance at least a 1.25 buffer relative to the simulated liquidation threshold. A `leverage_reduced_for_stop` flag can note this reduction. This is a simplified paper model, not a production exchange margin calculator.

For manual trades, the user selects one of 1x, 5x, 10x, 20x, 100x, or 200x. Manual size is computed from entered margin multiplied by leverage, divided by the current price. Manual positions do not receive an automatic stop or take-profit.

### Opening a paper position

The paper account reserves margin:

```text
notional = entry × size_BTC
margin = notional / leverage
```

It subtracts margin from available balance and stores the open trade in SQLite. It refuses to open when there is already an open position, the daily loss limit has been reached, the audit ledger is invalid, or the account lacks sufficient available balance.

AI-originated positions include a decision ID, rationale, stop, and target. Manual positions are marked `manual`, have no decision ID, and currently have no stop or target.

## Position monitoring and exits

### Automatic AI position exits

During position settlement:

- **Long stop:** if current sampled ticker is at or below stop, close at the sampled current price with reason `SL`.
- **Long target:** if current sampled ticker is at or above target, close at the target price with reason `TP`.
- **Short stop:** if current sampled ticker is at or above stop, close at the sampled current price with reason `SL`.
- **Short target:** if current sampled ticker is at or below target, close at the target price with reason `TP`.

After those checks, the trader estimates gross unrealized P&L at the current sampled price. If it is at or below negative reserved margin, it closes with reason `LIQUIDATION` at the sampled price. The close calculation caps account loss at isolated margin.

Settlement runs every 5 seconds in the autonomous loop by default. Dashboard account and trade-history requests also call settlement, so they may trigger a close when a threshold has been crossed.

Because the application samples prices rather than maintaining an exchange-native stop, gaps between samples can affect the exit price. Target exits are recorded at the target price when the observed price has crossed it; stop and liquidation exits use the observed sampled price. This is a simulation, not guaranteed execution.

### Manual position exits

The user may close an open manual or AI position through the dashboard/API. The close uses a fresh ticker price and the reason `manual`, unless automatic settlement first sees a stop, target, or liquidation condition. The UI shows a paper-trading confirmation and reports estimated unrealized P&L while the position remains open.

### Fees and realized P&L

The paper trader uses a 0.1% round-trip fee on entry notional (`ROUND_TRIP_FEE_PCT = 0.001`). At close it computes directional gross P&L, charges the remaining amount needed to reach that target fee, and records net P&L. Losses are capped at the reserved margin.

The risk engine also uses a configured fee parameter when estimating sizing and rejecting targets that do not cover estimated fees. The configuration and ledger metadata discrepancy described below means the decision-record snapshot should not be treated as an authoritative record of the exact live runtime settings.

## Risk controls and configuration

The main YAML settings are in [config.yaml](./config.yaml). Current checked-in defaults include:

| Setting | Default | Purpose in current runtime |
|---|---:|---|
| `symbol` | `BTCUSDT` | Documents the target symbol; much of the active code also hard-codes it |
| `timeframes` | 4h, 1h, 15m | The strategy's multi-timeframe intervals |
| `candles_per_timeframe` | 300 | Intended candle count; current agent fetch helper defaults to 300 directly |
| `confidence_threshold` | 0.55 | Minimum confidence accepted by risk engine |
| `confidence_cap` | 0.95 | Caps confidence for risk sizing/leverage |
| `base_risk_pct` | 0.0075 | 0.75% base equity risk budget before sizing multiplier |
| `max_size_multiplier` | 1.5 | Upper limit for confidence size adjustment |
| `max_notional_pct` | 0.50 | Base notional ceiling, multiplied by leverage |
| `max_open_positions` | 1 | Intended max; the paper account enforces a single open position directly |
| `max_daily_loss_pct` | 0.03 | Intended 3% daily loss stop; current trader uses a hard-coded 3% constant |
| `sl_atr_mult` | 1.5 | ATR stop distance |
| `tp_atr_mult` | 2.5 | ATR target distance |
| `atr_timeframe` | `1h` | Documents ATR timeframe; active agent explicitly uses 1h ATR |
| `fee_pct_round_trip` | 0.001 | 0.1% runtime risk-engine fee estimate |
| `slippage_pct` | 0.0005 | 0.05% simulated entry slippage |
| `max_leverage` | 200 | Risk engine's maximum leverage setting |
| `gemini_model` | `gemini-2.5-flash` | Model label in YAML; runtime model can be overridden by `GEMINI_MODEL` |

Other YAML entries (`weights`, `threshold`, `min_agreeing`) resemble consensus-agent settings but are not used by the active trade decision path in `TAAgent`/`calculate_risk`. There is one active TA proposal path, not a weighted TA/news ensemble.

Daily P&L is bucketed by UTC date. The current account guard uses a 3% loss threshold against starting equity and allows no new position after the loss reaches that threshold. An open position also blocks a new one. There is no trailing portfolio-level risk manager, automatic strategy shutdown configuration per symbol, or portfolio diversification logic.

## Persistence, audit records, and verification

### SQLite paper account

`PaperTrader` stores data in `data/mortis.db` by default, or under `MORTIS_DATA_DIR` when set. It persists:

- Account balance, starting equity, and most recent reset time.
- Open and closed trades, including side, entry, size, notional, leverage, margin, stop/target, times, exit reason, gross/net P&L, and fee.
- Realized daily P&L by UTC date.
- Hash-linked ledger events such as account initialization, trade open, trade close, and account reset.

The account starts at 10,000 simulated USDT. On restart, it reads the existing database; it does not simply reset to the initial balance. Resetting requires no open position, resets the balance and daily P&L, and retains trade/audit history.

### Decision records

For each strategy cycle, including `no_trade`, the logger writes a JSON decision file and a sibling `.hash` file under `data/decisions/`. The JSON is hashed after canonicalization (sorted keys, compact separators, UTF-8) using SHA-256. A new record includes the prior decision hash as a field.

### Trade event ledger

The SQLite ledger stores canonicalized event payloads and a SHA-256 hash that includes the previous event hash. The application verifies the ledger before appending events and refuses sensitive trade mutations if the existing chain is invalid. The dashboard can display the recent ledger and its internal validity result.

### What the hashes prove—and do not prove

- A valid hash can show that a particular record still matches its recorded digest.
- The SQLite ledger checks internal event ordering and each event's previous-hash link.
- Decision-record verification recomputes an individual decision's digest. The decision record's `previous_decision_hash` is stored, but the single-record verification function does not independently recompute and validate the entire historical decision chain.
- Files and database are local and can be replaced together by someone with filesystem access. The system has no external timestamp authority or public-chain anchoring.
- The Next.js verification endpoint has an offline fallback that creates a new synthetic canonical payload and a matching hash. That fallback can return `valid: true` without authenticating the submitted original decision. Use the Python backend verification result for actual decision-record verification; do not treat the offline fallback response as proof of the supplied record.

## Dashboard and API capabilities

### Dashboard features

The current dashboard includes:

- Live BTC price and recent 15m candles.
- 4h/1h/15m timeframe indicator displays.
- Paper-account equity, available balance, current position, return, win-rate, drawdown, and daily realized P&L.
- Manual long/short paper-position opening with selected margin and leverage.
- Manual close action for the open position.
- Paginated trade history.
- Agent analysis/chat interface that calls the trade-analysis endpoint.
- Recent audit-ledger view and verification UI.
- A news card that says the provider is not configured; it does not claim live headlines.

The browser polls market/account data every four seconds. The strategy's autonomous analysis interval is separate and defaults to 15 minutes.

### Python API endpoints

FastAPI endpoints in [server.py](./server.py) include:

| Endpoint | Function |
|---|---|
| `GET /api/health` | Service status, model label, autonomous setting, paper-mode declaration |
| `GET /api/snapshot` | Live price, recent 15m candles, and multi-timeframe indicators |
| `GET /api/account` | Account state and dashboard statistics; may settle an open position |
| `POST /api/account/reset` | Reset paper balance when no position is open |
| `GET /api/trades` | Paginated trade history; may settle an open position |
| `POST /api/trades` | Open a manual paper position |
| `POST /api/trades/close` | Close current open position at current sampled price |
| `GET /api/ledger` | Recent ledger events and chain-validity flag |
| `POST /api/chat` | Run market analysis and possibly execute the resulting paper trade |
| `POST /api/verify` | Verify a provided or stored decision record's own hash |

The Next.js `/api/*` handlers proxy to `http://localhost:8000`; they do not implement a separate trading engine. The browser frontend is normally served at `http://localhost:3001`.

## API keys and environment configuration

### Gemini key

The Python process loads a root `.env` file through `python-dotenv` in `server.py` and `engine/loop.py`. `TAAgent` reads:

```text
GEMINI_API_KEY
GEMINI_MODEL
```

The key is passed to `genai.Client(api_key=...)` on the Python backend. The Next.js client components do not read or receive the Gemini key, and the key should not be placed in a `NEXT_PUBLIC_*` variable, committed to source control, embedded in a browser bundle, or included in screenshots/logs. The repository's `.gitignore` excludes `.env` and `.env*.local`.

Example local `.env`:

```env
GEMINI_API_KEY=replace_with_your_own_key
GEMINI_MODEL=gemini-2.5-flash
MORTIS_AUTOTRADE_ENABLED=true
MORTIS_DATA_DIR=
```

The blank `MORTIS_DATA_DIR` line is optional; omit it to use the default repository `data` folder. `MORTIS_AUTOTRADE_ENABLED` defaults to true if unset. False-like values `0`, `false`, `no`, and `off` disable startup of the autonomous worker. A missing Gemini key is supported and results in the deterministic fallback rather than a Gemini call.

Binance market endpoints used here are public and need no API credential. No exchange credentials should be supplied for this application; the current code has no real-order interface.

## How to run it

Prerequisites documented in the project include Python 3.10+, Node.js 20+, and package managers/pip.

```powershell
pip install -r requirements.txt
npm install
```

To run the backend, from the repository root:

```powershell
python server.py
```

To run the web app in a second terminal:

```powershell
npm run dev
```

Open `http://localhost:3001`. The frontend proxies API requests to the Python service on port 8000. Without a Gemini key, strategy decisions use the deterministic fallback; public market-data connectivity is still needed for live market inputs and settlement.

To run the Python tests:

```powershell
pytest
```

To disable autonomous AI/rule-based cycles while retaining the API/dashboard for manual paper trading, set `MORTIS_AUTOTRADE_ENABLED=false` in the backend environment before starting it.

## Current capabilities and boundaries

### Implemented today

- One BTCUSDT paper account.
- Multi-timeframe indicator calculation over closed Binance candles.
- Optional Gemini-based direction/confidence/rationale.
- Deterministic technical fallback.
- ATR-based AI stops and targets, confidence-tier leverage, risk-based sizing, notional cap, and entry slippage estimate.
- One-open-position account guard and 3% starting-equity daily realized-loss guard.
- Manual paper entries with a user-selected margin and leverage.
- Sampled-price stop/target/liquidation settlement.
- Local SQLite persistence, account reset, trade history, and hash-linked trade ledger.
- Local web dashboard and Python REST API.

### Not implemented or not active

- Real exchange connectivity, order routing, live broker stops, or wallet custody.
- News, sentiment, social, on-chain, or order-book analysis.
- Multi-agent consensus, despite some schema/config fields that suggest it.
- Config-driven optimization, strategy learning, or model fine-tuning.
- Historical backtests, parameter sweeps, walk-forward validation, or slippage modeling from historical fills.
- A guarantee that sampled stop/target behavior matches real exchange execution.
- Production-grade authentication, multi-user account isolation, or remote deployment hardening.
- Public blockchain audit writes.

## Implementation caveats and discrepancies

These source-level details matter when interpreting logs, configuration, or UI claims:

1. **Decision-record metadata can differ from the live configuration.** `chain/logger.py` currently constructs a hard-coded `config_snapshot`: it writes a confidence threshold of `0.60` while `config.yaml` sets `0.55`, and writes a fee value of `0.03` while the risk and paper-trading code use `0.001` (0.1%). The decision record also lists a few static settings rather than serializing the exact loaded configuration. Treat this snapshot as incomplete metadata, not an authoritative replay configuration.
2. **Some YAML options are currently unused or only partly wired.** `weights`, `threshold`, and `min_agreeing` do not drive an active consensus; `candles_per_timeframe` is not passed by the agent; `max_daily_loss_pct` and the one-position limit are enforced with constants/schema constraints in the trader; and the configured `atr_timeframe` is superseded by explicit use of the 1h indicators in the agent.
3. **`/api/chat` has a trading side effect.** It is not a read-only chat or a pure analysis request. It invokes `analyze_and_trade`, which writes a decision record and can open a paper position.
4. **The web verification fallback is not equivalent to verification.** If the Python verification backend is unavailable or errors, the Next.js route builds a fresh synthetic payload/hash and returns it as valid. Do not rely on this fallback to establish integrity of the submitted record.
5. **Confidence is not calibrated.** Gemini's score is a model-provided rating, while the fallback uses fixed values. Neither is a measured win probability.
6. **Position exits are sampled simulations.** A 5-second default polling cadence and dashboard-triggered settlement are not exchange-native stop orders; price gaps and outages can alter observed behavior.
7. **Manual positions have no stop/target by default.** They remain open until manually closed or the simulated isolated-margin liquidation condition is reached.
8. **A local hash chain is not immutable storage.** Local filesystem/database access can alter or replace the records; the chain is useful for detecting many accidental or partial modifications, not preventing a privileged attacker.
9. **Risk calculations are simplified.** Leverage and liquidation are simulated; exchange-specific maintenance margin, funding, maker/taker fees, order-book spreads, partial fills, and margin tiers are not modeled.
10. **Market/API failures affect operation.** Binance calls have timeouts and host fallback; persistent market-data failure can stop a cycle or make dashboard data unavailable. Gemini failure falls back, but market-data failure does not create an equivalent offline market snapshot.

## Repository map

| Path | Responsibility |
|---|---|
| [agents/ta_agent.py](./agents/ta_agent.py) | Snapshot, Gemini call/fallback, risk plan, decision logging, AI paper-trade open |
| [agents/schemas.py](./agents/schemas.py) | Pydantic-style decision and risk-record schemas |
| [tools/market_data.py](./tools/market_data.py) | Binance public ticker/candle retrieval and closed-candle filtering |
| [tools/indicators.py](./tools/indicators.py) | EMA, RSI, ATR, MACD, swing levels, per-timeframe feature output |
| [engine/risk.py](./engine/risk.py) | Confidence gating, stop/target calculations, size, notional cap, leverage |
| [engine/paper_trader.py](./engine/paper_trader.py) | SQLite account, positions, settlement, fee/P&L, liquidation, trade ledger |
| [engine/loop.py](./engine/loop.py) | Scheduled analysis and periodic open-position settlement |
| [chain/logger.py](./chain/logger.py) | Decision JSON files and SHA-256 hashes |
| [chain/verify.py](./chain/verify.py) | Command-line decision-file hash verification |
| [server.py](./server.py) | FastAPI routes and autonomous-worker lifecycle |
| [app/page.tsx](./app/page.tsx) | Dashboard composition and account/market polling |
| [app/api/](./app/api/) | Next.js API proxy routes |
| [components/](./components/) | Dashboard panels, charts, history, trade controls, and news placeholder |
| [config.yaml](./config.yaml) | Strategy and risk configuration defaults |
| [tests/](./tests/) | Python API, indicator/risk, persistence, settlement, and hashing coverage |

## Final interpretation

Mortis is best understood as a local research/demo stack with a model-assisted market read, deterministic risk calculations, and a simulated account. The model proposes direction and explains its view; Python—not the LLM—calculates the simulated entry, stop, target, position size, and leverage. Public price sampling and SQLite state determine simulated trade outcomes. The dashboard visualizes those values but does not turn the system into a live trading platform.

All results are dependent on market data, the configured model or fallback rules, the checked-in implementation details, and the current local configuration. Paper results do not establish that the strategy is profitable or safe to deploy with real funds.
