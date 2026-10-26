# MORTIS ⚡
> **Accountable AI BTC Trading Agent with SHA-256 Proof of Reasoning**  
> *Built for Agentmaxxing Week 1 ("Get Agentic")*

---

## 📌 Overview

Mortis is a local Bitcoin paper-trading and research prototype. The Python engine evaluates the 4h/1h/15m BTC/USDT setup every 15 minutes and checks open positions against live public market prices every 5 seconds. A deterministic strategy proposes direction; a calibrated model is used only when a candidate has passed the promotion gate and is explicitly configured. Deterministic code validates decisions, sizes positions, and enforces risk limits.

### The Pitch
> *"A strategy proposes, code limits simulated risk, and a local hash chain records what happened."*

All trading is simulated. There is no exchange order integration, real wallet, or public-chain write.

---

## 🏗️ Architecture Diagram

```
                  ┌────────────────────────┐
                  │   User / Web Dashboard │
                  └───────────┬────────────┘
                              │ Prompt & Chat
                              ▼
                  ┌────────────────────────┐
                  │ Trading Analysis Agent │
                  │ Rules + gated model    │
                  └───────────┬────────────┘
                              │ Function Calls
     ┌────────────────────────┼────────────────────────┐
     ▼                        ▼                        ▼
┌───────────────┐   ┌───────────────────┐   ┌─────────────────────┐
│  Market Data  │   │    Risk Engine    │   │ Paper Trader Engine │
│ (Binance API) │   │ (ATR SL/TP/Sizing)│   │ (Settlement Engine) │
└───────┬───────┘   └─────────┬─────────┘   └──────────┬──────────┘
        │                     │                        │
        └─────────────────────┼────────────────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │ SQLite Trade Ledger    │
                  │ (SHA-256 Event Chain)  │
                  └────────────────────────┘
```

---

## ⚙️ Core Technical Rules

1. **Deterministic execution**: Direction proposals come from the deterministic multi-timeframe strategy. A calibrated model can only filter those proposals after promotion; model outputs never select leverage. Indicators, ATR stop-loss, take-profit, position size, and notional caps are calculated in deterministic code (`engine/risk.py`).
2. **Multi-Timeframe Analysis**:
   - **4h**: Macro trend direction (EMA 50/200 alignment).
   - **1h**: Market structure & ATR volatility measurement.
   - **15m**: Precision entry timing and momentum.
3. **ATR Risk Engine**:
   - **Stop-Loss (SL)**: $1.5 \times \text{ATR}_{1\text{h}}$
   - **Take-Profit (TP)**: $2.5 \times \text{ATR}_{1\text{h}}$
   - **Base equity risk**: 0.25% per trade, including estimated trading costs in sizing.
   - **Leverage**: 2x default and 5x maximum. Leverage does not increase with model confidence.
   - **Costs**: 0.1% round-trip paper fee, with configurable slippage and historical funding in research backtests.
   - **Guards**: 3% UTC daily loss limit, 3-loss/24-hour cooldown, and 10% drawdown pause with explicit re-enable.
4. **Proof of Reasoning SHA-256 Hashing**:
   - Every decision (including `no_trade`) is serialized into canonical JSON with sorted keys.
   - Trade open/close events (including fees, P&L, duration, and reason) are stored in `data/mortis.db` and linked by SHA-256 hashes. This local ledger detects edits but is not a public blockchain.

---

## 🚀 Quickstart & Setup

### Prerequisites
- Node.js 20+ installed (`node -v`)
- Python 3.10+ and pip
- No API key is required for the deterministic paper-trading strategy. Gemini is not used to choose or execute trades.

### 1. Installation
```bash
git clone https://github.com/your-username/mortis.git
cd mortis
npm install
pip install -r requirements.txt
```

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
# Recommended while reviewing the local setup; explicit paper execution remains available.
MORTIS_AUTOTRADE_ENABLED=false
```

### 3. Run the Python tests
```bash
python -m pytest -q
```

### 4. Launch the backend and dashboard
In one terminal, start the Python engine. Autonomous paper trading is enabled only when `MORTIS_AUTOTRADE_ENABLED=true`:
```bash
python server.py
```

In another terminal, start the dashboard:
```bash
npm run dev
```
Open [http://localhost:3001](http://localhost:3001). The Python API is bound to `127.0.0.1:8000`.

Trades and hash-chain events persist in the ignored local database `data/mortis.db`. The balance, open positions, and trade history are loaded from this database on restart rather than reset to the starting balance. Keep the same `data/mortis.db` file and `MORTIS_DATA_DIR` setting between deployments; the dashboard's explicit Reset Account action resets the balance. Use the dashboard to open/close a manual paper position, select leverage, view account P&L, and verify the local audit ledger. Do not delete this file if you want to retain transaction history.

### Dashboard history and signal interpretation

- **Trade history** shows each simulated position's UTC open/close time, long/buy or short/sell direction, AI/manual source, entry and exit/mark prices, net realized P&L after fees, and close reason. Open-position P&L is an estimate, not realized profit. History loads newest-first in pages of 25 and can be refreshed from the dashboard.
- **Account equity** is plotted oldest-to-newest from the current account reset. Scroll horizontally through trade milestones; click or focus a point to inspect its exact recorded value and timestamp. This is paper-account equity, not wallet balance.
- **Timeframe signals** expose the underlying EMA trend, RSI/MACD momentum, volume, ATR volatility, and nearby support/resistance. Their directional agreement is a rule-based diagnostic, not a calibrated probability or a set of independent AI agents.
- **Bitcoin news** is intentionally shown as unavailable until a verified news provider is configured. Headlines and sentiment are not currently connected to the trading engine.
- **Learning records** retain decision features, model version, quote status, and resolved paper-trade outcomes, including net R and exit reason. The API summarizes outcome, slippage, and loss-reason counts. An exit reason is recorded evidence, not proof of the cause of a loss. Offline training may use resolved AI paper trades as feedback; this does not trigger automatic retraining or promotion.
- **Phase 1 persistent memory** stores versioned decisions, trade events, and outcome episodes in SQLite. Similar numeric states are shown to the agent as historical analogs; the default `advisory` mode does not change trades. The optional `gate` mode can veto or reduce size only after sufficient history and never raises leverage or risk. The dashboard labels low-data statistics as insufficient and lessons as hypotheses.
- **Catch-up and exports** replay closed 1-minute candles after downtime, with a conservative stop-first conflict rule. Review memory and catch-up state in `/api/memory/stats`; browse decision and trade details in the dashboard or read-only APIs. Export locally with `python -m tools.export --table trades --format csv --out exports\trades.csv`. See [Phase 1 notes](./docs/PHASE1_NOTES.md), [memory design](./docs/MEMORY.md), [data dictionary](./docs/DATA_DICTIONARY.md), and [SQL queries](./docs/QUERIES.md).

### Historical research and candidate training

Research downloads are opt-in and use public Binance USD-M futures market data:

```bash
python -m research.data_loader --update --start 2020-01-01 --end 2024-01-01
python -m research.backtest --start 2020-01-01 --end 2023-01-01
python -m research.train --start 2020-01-01 --end 2023-01-01
```

Choose date ranges that leave a separate, untouched final holdout. The backtest compares deterministic strategies against random-entry and buy-and-hold baselines, includes funding and a 2x transaction-cost run, and reports data gaps. Training writes candidate artifacts only; candidates are never promoted automatically. The live agent refuses any configured artifact without explicit paper-trial approval and matching historical gate evidence. A candidate entering paper trial is not a validated model; prospective evidence is still required.

After training, evaluate candidate artifacts against the protected final interval once, in a single command:

```bash
python -m research.holdout --start 2024-01-01 --end 2024-03-01 --candidate models/candidate-<version>-logistic --candidate models/candidate-<version>-lightgbm
```

The evaluator creates `research/reports/final-holdout-consumed.json` and refuses to overwrite an existing holdout report or marker. It never activates models. If historical gates pass and you explicitly approve a candidate for **paper-only trial**, run:

```bash
python -m research.promotion --candidate models/candidate-<version>-logistic --approve-paper-trial
```

Then set `model.active_version` in `config.yaml` to that candidate version and restart the backend. The forward-validation report is based only on resolved AI paper trades made by that model after its trial start:

```bash
python -m research.forward_validation --candidate models/candidate-<version>-logistic
```

Forward validation requires at least 56 elapsed days, 100 closed paper trades, positive net expectancy, and a positive lower 95% bootstrap confidence bound. It only reports the evidence; it does not permit real-money trading or automatically change model status.

The application remains a local paper-trading prototype. It has not been certified for production, exchange execution, real wallets, or profitability; observed drawdowns and losses are possible, and the dashboard must not be used as evidence that a strategy will profit.

---

## 🔒 Safety & Honesty Disclaimer

- **Paper Trading Only**: Manual and autonomous positions are simulations; Mortis never sends real orders. The default account starts at 10,000 simulated USDT. Supported leverage choices are 1x through the configured 5x cap; leverage can cause simulated liquidation and is not a recommendation for real trading. A 0.1% round-trip fee is applied to entry notional on close.
- **No HFT**: AI analysis runs every 15 minutes and open-position monitoring every 5 seconds. This is not a microsecond trading system.
- **No training/profit guarantee**: Paper outcomes are retained and may be included in offline candidate training, but do not update active model weights automatically. Historical results do not guarantee future performance.
- **Local audit chain**: SQLite plus SHA-256 chaining is tamper-evident when verified, but it is not an on-chain blockchain or externally immutable storage.
- **Not Financial Advice**: Mortis is an educational & research prototype built for the Agentmaxxing hackathon.
- **Uncalibrated confidence**: Until a promoted calibrated artifact is active, the displayed rule score is not a mathematical win probability.
- **Promotion limits**: No candidate has passed final-holdout and forward paper-validation gates. A coding session cannot establish the required weeks of prospective evidence or prove outperformance of a human trader.

---

## 🗺️ Agentmaxxing Roadmap

- [x] **Week 1 ("Get Agentic")**: Multi-timeframe TA Agent + ATR Risk Engine + Paper Engine + SHA-256 Decision Hash Chain + Next.js Dashboard.
- [ ] **Week 2 ("Build & Ship")**: News Sentiment Agent (Tavily/NewsAPI) + Consensus Lead Agent + Backtesting Engine.
- [ ] **Week 3 ("Give It A Wallet")**: Separate future work: testnet wallet + DecisionLog Smart Contract on-chain transaction logging + Verifier.
- [ ] **Week 4 ("Maxx It Out")**: Polish, demonstration video, final docs release.
