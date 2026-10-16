# MORTIS ⚡
> **Accountable AI BTC Trading Agent with SHA-256 Proof of Reasoning**  
> *Built for Agentmaxxing Week 1 ("Get Agentic")*

---

## 📌 Overview

Mortis is a local autonomous Bitcoin paper-trading prototype. While the Python engine is running, it evaluates the 4h/1h/15m BTC/USDT setup every 15 minutes and checks open positions against live public market prices every 5 seconds. Gemini provides a direction and rationale when configured; deterministic Python code validates decisions, sizes positions, and enforces risk limits.

### The Pitch
> *"The AI proposes, code limits simulated risk, and a local hash chain records what happened."*

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
                  │    Mortis AI Agent     │
                  │ (Gemini 2.5 Flash API) │
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

1. **No LLM Math**: Gemini outputs direction (`long` | `short` | `neutral`), confidence score (0.0 to 1.0), and concise rationale. Indicators, ATR stop-loss, take-profit, position size, and notional caps are calculated in deterministic code (`engine/risk.py`).
2. **Multi-Timeframe Analysis**:
   - **4h**: Macro trend direction (EMA 50/200 alignment).
   - **1h**: Market structure & ATR volatility measurement.
   - **15m**: Precision entry timing and momentum.
3. **ATR Risk Engine**:
   - **Stop-Loss (SL)**: $1.5 \times \text{ATR}_{1\text{h}}$
   - **Take-Profit (TP)**: $2.5 \times \text{ATR}_{1\text{h}}$
   - **Base Equity Risk**: 0.75% risk budget per trade, including the round-trip fee in position sizing.
   - **Confidence Sizing Multiplier**: Scaled dynamically between 1.0x and 1.5x for higher confidence setups.
   - **Leverage**: AI paper trades select a confidence-based tier; manual paper positions can select 1x, 5x, 10x, 20x, 100x, or 200x. Isolated margin caps a position's loss to its reserved margin.
   - **Fee**: 0.1% round-trip of entry notional, charged when a position closes. AI setups whose target does not clear this fee are rejected.
   - **Confidence-based leverage**: AI selections use 1x, 5x, 10x, 20x, 100x, or 200x tiers. Leverage is reduced when the planned stop would sit too close to simulated liquidation, and position sizing remains bounded by the equity-risk budget.
   - **Hard Daily Loss Limit**: -3.0% UTC daily drawdown kill-switch.
4. **Proof of Reasoning SHA-256 Hashing**:
   - Every decision (including `no_trade`) is serialized into canonical JSON with sorted keys.
   - Trade open/close events (including fees, P&L, duration, and reason) are stored in `data/mortis.db` and linked by SHA-256 hashes. This local ledger detects edits but is not a public blockchain.

---

## 🚀 Quickstart & Setup

### Prerequisites
- Node.js 20+ installed (`node -v`)
- Python 3.10+ and pip
- Optional Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey). Without it, Mortis uses its deterministic technical-analysis fallback.

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
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
# Optional: set to false to disable autonomous paper trading on backend startup.
MORTIS_AUTOTRADE_ENABLED=true
```

### 3. Run the Python tests
```bash
pytest
```

### 4. Launch the backend and dashboard
In one terminal, start the Python engine. This starts autonomous paper trading by default:
```bash
python server.py
```

In another terminal, start the dashboard:
```bash
npm run dev
```
Open [http://localhost:3001](http://localhost:3001). The Python API is bound to `127.0.0.1:8000`.

Trades and hash-chain events persist in the ignored local database `data/mortis.db`. The balance, open positions, and trade history are loaded from this database on restart rather than reset to the starting balance. Keep the same `data/mortis.db` file and `MORTIS_DATA_DIR` setting between deployments; the dashboard's explicit Reset Account action resets the balance. Use the dashboard to open/close a manual paper position, select leverage, view account P&L, and verify the local audit ledger. Do not delete this file if you want to retain transaction history.

---

## 🔒 Safety & Honesty Disclaimer

- **Paper Trading Only**: Manual and autonomous positions are simulations; Mortis never sends real orders. The default account starts at 10,000 simulated USDT. Supported leverage choices run from 1x to 200x; leverage can cause rapid simulated liquidation and is not a recommendation for real trading. A 0.1% round-trip fee is applied to entry notional on close.
- **No HFT**: AI analysis runs every 15 minutes and open-position monitoring every 5 seconds. This is not a microsecond trading system.
- **No training/profit guarantee**: Gemini's model weights are not retrained by this app. Results are recorded for later evaluation; historical wins do not guarantee future performance.
- **Local audit chain**: SQLite plus SHA-256 chaining is tamper-evident when verified, but it is not an on-chain blockchain or externally immutable storage.
- **Not Financial Advice**: Mortis is an educational & research prototype built for the Agentmaxxing hackathon.
- **Uncalibrated Confidence**: LLM confidence scores represent internal setup rating, not mathematical win probabilities.

---

## 🗺️ Agentmaxxing Roadmap

- [x] **Week 1 ("Get Agentic")**: Multi-timeframe TA Agent + ATR Risk Engine + Paper Engine + SHA-256 Decision Hash Chain + Next.js Dashboard.
- [ ] **Week 2 ("Build & Ship")**: News Sentiment Agent (Tavily/NewsAPI) + Consensus Lead Agent + Backtesting Engine.
- [ ] **Week 3 ("Give It A Wallet")**: Separate future work: testnet wallet + DecisionLog Smart Contract on-chain transaction logging + Verifier.
- [ ] **Week 4 ("Maxx It Out")**: Polish, demonstration video, final docs release.
