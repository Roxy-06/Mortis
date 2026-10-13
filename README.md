# MORTIS ⚡
> **Accountable AI BTC Trading Agent with SHA-256 Proof of Reasoning**  
> *Built for Agentmaxxing Week 1 ("Get Agentic")*

---

## 📌 Overview

Mortis is an autonomous AI trading agent powered by **Google Gemini 2.5 Flash**. Mortis analyzes live Bitcoin (`BTC/USDT`) market data across multi-timeframe candle intervals (4h trend, 1h structure, 15m entry timing), computes technical indicators (EMA, RSI, MACD, ATR, Swing S/R) deterministically in code, and executes simulated paper trades governed by strict ATR risk rules.

### The Pitch
> *"The AI decides, code limits the risk, and logs prove what the AI decided and when."*

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
                  │ SHA-256 Decision Log   │
                  │ (Canonical Hash Chain) │
                  └────────────────────────┘
```

---

## ⚙️ Core Technical Rules

1. **No LLM Math**: Gemini outputs direction (`long` | `short` | `neutral`), confidence score (0.0 to 1.0), and concise rationale. Indicators, ATR stop-loss, take-profit, position size, and notional caps are strictly calculated in deterministic code (`agent/risk.ts`).
2. **Multi-Timeframe Analysis**:
   - **4h**: Macro trend direction (EMA 50/200 alignment).
   - **1h**: Market structure & ATR volatility measurement.
   - **15m**: Precision entry timing and momentum.
3. **ATR Risk Engine**:
   - **Stop-Loss (SL)**: $1.5 \times \text{ATR}_{1\text{h}}$
   - **Take-Profit (TP)**: $2.5 \times \text{ATR}_{1\text{h}}$
   - **Base Equity Risk**: 0.75% of equity per trade.
   - **Confidence Sizing Multiplier**: Scaled dynamically between 1.0x and 1.5x for higher confidence setups.
   - **Max Notional Cap**: 50% of equity (1x spot leverage).
   - **Hard Daily Loss Limit**: -3.0% UTC daily drawdown kill-switch.
4. **Proof of Reasoning SHA-256 Hashing**:
   - Every decision (including `no_trade`) is serialized into canonical JSON with sorted keys.
   - A SHA-256 digest is generated and chained (`previousDecisionHash`) to guarantee tamper-evident auditability.

---

## 🚀 Quickstart & Setup

### Prerequisites
- Node.js 20+ installed (`node -v`)
- Gemini API Key from [Google AI Studio](https://aistudio.google.com/apikey)

### 1. Installation
```bash
git clone https://github.com/your-username/mortis.git
cd mortis
npm install
```

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
TAVILY_API_KEY=your_tavily_key_here
NEWS_API_KEY=your_news_api_key_here
```

### 3. Run Automated Sanity & Risk Verification
Verify indicator calculations, ATR risk math, and SHA-256 hashing tamper tests:
```bash
npm run sanity
```

### 4. Launch Development Server
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser to interact with the Mortis Dashboard & Chat Terminal.

---

## 🔒 Safety & Honesty Disclaimer

- **Paper Trading Only**: Mortis operates strictly in a simulated paper trading account. No real capital or mainnet funds are ever placed at risk.
- **Not Financial Advice**: Mortis is an educational & research prototype built for the Agentmaxxing hackathon.
- **Uncalibrated Confidence**: LLM confidence scores represent internal setup rating, not mathematical win probabilities.

---

## 🗺️ Agentmaxxing Roadmap

- [x] **Week 1 ("Get Agentic")**: Multi-timeframe TA Agent + ATR Risk Engine + Paper Engine + SHA-256 Decision Hash Chain + Next.js Dashboard.
- [ ] **Week 2 ("Build & Ship")**: News Sentiment Agent (Tavily/NewsAPI) + Consensus Lead Agent + Backtesting Engine.
- [ ] **Week 3 ("Give It A Wallet")**: Coinbase AgentKit Base Sepolia Wallet + DecisionLog Smart Contract on-chain transaction logging + Verifier.
- [ ] **Week 4 ("Maxx It Out")**: Polish, demonstration video, final docs release.
