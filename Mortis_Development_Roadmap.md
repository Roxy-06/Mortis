# MORTIS - DEVELOPMENT ROADMAP
Phased plan with evaluation gates and a continuous-upgrade loop

Companion to `Mortis_Project_Plan.txt` (that file defines WHAT to build; this file defines the ORDER, the EVALUATION, and the UPGRADE PROCESS).

---

## 0. READ THIS FIRST: ground rules

1. **"Near perfection" is not a real target in trading.** Markets are noisy and change over time; strategies decay. The real goal is a system that is **robust, measurable, honest, and improvable**. This roadmap replaces "perfection" with **evaluation gates**: a new version ships only if it beats the current one on out-of-sample data after fees.
2. **"Training the model" has two meanings here.**
   - You are NOT training or fine-tuning Gemini. You use it via API and improve it through prompts, tools, and evaluation.
   - You CAN train small classical ML models (e.g., gradient boosting or logistic regression on indicator features) as an extra signal. That is Phase 5.
3. **Evaluation before intelligence.** Build the backtester and baselines first (Phase 1). Without them you cannot tell whether any later change helped.
4. **Paper trading and testnet only.** Real-money trading is not part of this roadmap. See section 12 for what would have to be true before anyone even considers it.
5. **One change at a time.** Every upgrade is a logged experiment with a hypothesis, a result, and a keep/revert decision.

---

## 1. PHASE OVERVIEW

| Phase | Name | Core output | Version tag |
|---|---|---|---|
| 0 | Foundations | Repo, env, data, wallet smoke test | v0.0 |
| 1 | Data, Paper Engine, Baselines, Backtester | Trustworthy evaluation harness | v0.1 |
| 2 | First Agent + Risk Engine | TA agent trading on paper with SL/TP | v0.2 |
| 3 | Multi-Agent Decision Engine | News + Lead agent, consensus, calibration | v0.3 |
| 4 | Web3 Layer | Wallet, on-chain decision hashes, verifier, guardrails | v0.4 |
| 5 | Quant ML Models ("training") | Trained signal model, walk-forward validated | v0.5 |
| 6 | Autonomous Operation | 24/7 runner, monitoring, forward paper test | v0.6 |
| 7 | UI/UX Dashboard | Decision timeline, equity curve, verify, controls | v0.7 |
| 8 | Hardening, Docs, Release | Security review, README, demo, submission | v1.0 |
| 9+ | Continuous Improvement Loop | Repeating upgrade cycle with gates | v1.x |

### Mapping to the Agentmaxxing calendar (Oct 5-25 is the real deadline)

| Program week | Dates | Phases to finish |
|---|---|---|
| Pre-program | before Oct 5 | Phase 0 |
| Week 1 | Oct 5-9 | Phase 1 + start Phase 2 (submit a working agent) |
| Week 2 | Oct 12-16 | Finish Phase 2 + Phase 3 + minimal Phase 7 |
| Week 3 | Oct 19-23 | Phase 4 (wallet + on-chain) |
| Week 4 | Oct 24-25 | Phase 8 only (polish, docs, demo, tweet) |
| After program | Oct 26+ | Phase 5, 6, full 7, then Phase 9 loop |

Be realistic: Phases 5 and 6 do NOT fit in the program window. The program version of Mortis is v0.4 + a minimal dashboard + docs. Everything after is the long-term build.

---

## 2. THE EVALUATION FRAMEWORK (build this in Phase 1, use it in every phase)

### 2.1 Baselines every version must be compared against
- Buy-and-hold BTC over the same period
- Simple moving-average crossover (e.g., EMA 20/50)
- RSI mean-reversion (buy <30, sell >70) with the same SL/TP rules
- Random-entry strategy with the same SL/TP and sizing (the "is this just luck?" test)

### 2.2 Metrics to report for every run
**Performance:** total return, annualized return, Sharpe, Sortino, max drawdown, profit factor, win rate, average win / average loss, expectancy per trade (in R-multiples), exposure time, number of trades, fees paid.
**Decision quality:** hit rate by confidence bucket, calibration curve and Brier score of agent confidences, "no_trade" rate, agent agreement rate, disagreement-vs-outcome analysis.
**System health:** LLM failure/retry rate, schema-validation failure rate, average and p95 latency per cycle, API cost per decision, uptime.
**Chain/audit:** hash-post success rate, verifier PASS rate, gas cost per log.

### 2.3 Data discipline (prevents fooling yourself)
- **No lookahead:** at time t, the strategy only sees data up to t. Unit-test this.
- **Realistic costs:** fees and slippage on every simulated fill. Results without costs are not valid.
- **Three data splits:**
  - Development set (tune freely)
  - Validation set (choose between versions)
  - **Holdout set (touch it rarely, at major milestones only; never tune on it)**
- **Walk-forward testing:** train/tune on a window, test on the next window, roll forward. Report the average and the worst window, not just the best one.
- **Regime breakdown:** report results separately for uptrend, downtrend, and sideways/chop periods.
- **Minimum sample size:** do not draw conclusions from fewer than ~100 trades. Report confidence intervals (bootstrap) on key metrics.
- **Multiple-testing awareness:** the more variants you try, the more likely one looks good by chance. Keep a count of experiments in `EXPERIMENTS.md` and be skeptical of the best-looking result.

### 2.4 Promotion gates (starting suggestions; tune with experience)
A new version replaces the current one only if ALL hold on validation data, after fees:
- Risk-adjusted return (Sharpe or Sortino) is better than the current version AND better than buy-and-hold
- Max drawdown is not worse than the current version by more than a set tolerance (e.g., 10% relative)
- At least ~100 trades (or the improvement is clearly in a non-trading metric, like reliability)
- Beats the random-entry baseline with a clear margin
- No regression in system-health metrics (failure rate, latency, cost)
- Results hold in at least 2 of 3 market regimes
- All unit tests pass and the change is logged in `EXPERIMENTS.md`

If a gate is not met: revert. Failed experiments are valuable results, so log them.

---

## 3. PHASE 0 - FOUNDATIONS (pre-program, target: before Oct 5)

**Goal:** remove all setup risk so build time is spent building.

**Tasks**
- Create repo, venv, `requirements.txt`, `.env.example`, `.gitignore`, folder skeleton
- Hello-world `google-adk` agent calling Gemini
- Create a Base Sepolia wallet, get faucet ETH, post ONE dummy hash from a script
- Download 2-3 months of BTC candles (15m, 1h, 4h); consider 12+ months for later phases
- Create `README.md`, `EXPERIMENTS.md`, `CHANGELOG.md`
- Windows check: confirm TA-Lib (or fallback pandas-ta / ta) installs

**Exit gate:** hello-world agent runs; dummy hash visible on a Base Sepolia explorer; candles load into a DataFrame.

**Risks:** AgentKit setup friction (fallback: web3.py), TA-Lib install on Windows (fallback: pandas-ta).

---

## 4. PHASE 1 - DATA, PAPER ENGINE, BASELINES, BACKTESTER (v0.1)

**Goal:** a trustworthy evaluation harness BEFORE any AI is involved.

**Tasks**
- `tools/market_data.py`: fetch and cache candles, live price
- `tools/indicators.py`: RSI, MACD, EMA, ATR, support/resistance (deterministic, unit tested)
- `engine/paper_trader.py`: account, positions, fees, slippage, PnL, SL/TP fills (SL-first on ambiguous candles)
- `engine/risk.py`: ATR-based SL/TP, position sizing, caps, daily-loss kill switch
- `engine/backtest.py`: replay candles through the exact same code path used live
- Implement the 4 baselines from section 2.1
- Metrics module computing everything in section 2.2
- Data splits defined and stored in config (dev / validation / holdout)

**Evaluation:** run all baselines; produce a report table. This is your reference scoreboard.

**Exit gate**
- Unit tests prove no lookahead and correct fee/PnL math (hand-calculated examples)
- Baseline results are reproducible (same input -> same output)
- Report generated automatically from one command

**Upgrade loop for this phase:** add more baselines, more metrics, more data history.

---

## 5. PHASE 2 - FIRST AGENT + RISK ENGINE (v0.2) [Program Week 1 submission]

**Goal:** an LLM agent that reads indicator data and drives paper trades, with risk handled by code.

**Tasks**
- `agents/schemas.py`: Pydantic models (agent output, decision record)
- `agents/ta_agent.py` (google-adk): input = precomputed multi-timeframe indicators (4h trend, 1h setup, 15m entry); output = direction + confidence + short rationale
- Retry/validation logic for malformed LLM output
- Wire TA agent -> threshold -> risk engine -> paper trader
- Log every cycle (including no_trade) to a decision JSON
- Prompt versioning: store prompt text + hash with each decision

**Evaluation**
- Backtest the TA-agent strategy on the dev set and compare with all baselines
- Check confidence calibration (do higher-confidence calls win more often?)
- Measure LLM cost, latency, failure rate
- Ablation: TA agent alone vs plain rule-based indicator strategy (does the LLM add anything?)

**Exit gate**
- End-to-end cycle runs without crashing for 24h of replayed data
- Schema failure rate under ~2% after retries
- Results reported honestly vs baselines (even if the LLM does not beat them)

**Upgrade loop:** prompt variants, indicator sets, timeframe combinations, temperature, model variants (speed vs quality).

**Risks:** LLM nondeterminism makes backtests irreproducible. Mitigation: cache LLM responses per (prompt, inputs) during backtests; use low temperature; record model version.

---

## 6. PHASE 3 - MULTI-AGENT DECISION ENGINE (v0.3) [Program Week 2]

**Goal:** multiple specialized agents combined by a consensus engine that is calibrated and measurable.

**Tasks**
- `tools/news_feed.py`: RSS (CoinDesk, Cointelegraph, etc.) via feedparser + Tavily search; NewsAPI optional
- `agents/news_agent.py`: sentiment direction + confidence, with source digest
- `agents/lead_agent.py`: weighted score, threshold, min-agreeing rule, optional veto
- Confidence handling: cap at 0.95, flag suspicious values
- **Calibration layer:** after enough logged decisions, fit a simple calibrator (e.g., isotonic or Platt scaling) mapping raw agent confidence to observed win frequency
- Weight tuning via walk-forward backtests (not by gut)
- Optional stretch: Whale agent via mempool.space / Blockstream (BTC-native data)

**Evaluation**
- Ablations: TA only vs TA+News vs TA+News+Whale
- Threshold sweep (0.5 ... 0.8) with trade count and risk-adjusted return
- Agreement analysis: are trades where agents agree better than trades where they conflict?
- News lag/leakage check: make sure historical headlines used in backtests were truly available at the time

**Exit gate**
- Multi-agent version passes promotion gates (section 2.4) against the Phase 2 version, OR the roadmap records that it did not and the simpler version stays
- Calibration report generated

**Upgrade loop:** better news sources, sentiment prompt tuning, dynamic weights by recent agent accuracy (only if it passes gates), Devil's Advocate/risk-critic agent.

**Risks:** news sentiment from LLMs is noisy and often late; backtests with news are easy to contaminate with hindsight.

---

## 7. PHASE 4 - WEB3 LAYER (v0.4) [Program Week 3, 25% of judging]

**Goal:** a meaningful, verifiable on-chain role for the agent wallet.

**Tasks**
- `chain/wallet.py`: Coinbase AgentKit wallet on Base Sepolia (fallback: web3.py)
- `contracts/DecisionLog.sol`: `logDecision(bytes32 hash, string uri)` + `DecisionLogged` event; optional per-day cap and owner pause
- `chain/logger.py`: canonical JSON -> hash -> store JSON -> post hash -> record tx hash. Hash is posted BEFORE the paper trade opens
- Hash chaining via `previous_decision_hash`
- `chain/verify.py`: tx hash -> fetch event -> fetch JSON -> recompute -> PASS/FAIL
- On-chain/wallet guardrails: spend permissions or policy contract (per-trade and per-day caps), kill switch
- Outcome logging (trade closed, PnL) linked by decision_id
- STRETCH: x402 integration (agent pays for premium data per request, or Mortis serves paywalled signals)

**Evaluation**
- Verifier PASS on genuine records; FAIL when a single character in the JSON is changed (test this explicitly)
- Hash-post success rate and gas cost per log
- Failure behavior test: what happens if the chain is down? (Decision: do not open the trade; log the failure)
- Security review of key handling (keys only in `.env`, never in logs/commits)

**Exit gate**
- 100+ consecutive decisions logged and verified in replay/testnet
- Tamper test fails as expected
- Guardrail test: attempt to exceed the cap -> blocked

**Upgrade loop:** IPFS storage, agent registry contract, on-chain outcome attestations, reputation score built from verified outcomes, account abstraction / session keys, additional chains.

**Risks:** faucet limits, RPC rate limits, AgentKit API changes. Keep the web3.py fallback ready.

---

## 8. PHASE 5 - QUANT ML MODELS ("TRAINING") (v0.5) [post-program]

**Goal:** add a trained, statistically validated signal and compare it fairly against the LLM agents.

**Important framing:** this is classical ML on engineered features. It is not Gemini fine-tuning. Start simple; complex models overfit financial data badly.

**Tasks**
- Feature engineering: multi-timeframe indicators, returns, volatility, volume, funding/OI data if available, time-of-day effects
- Labeling: e.g., "did price hit +2.5 ATR before -1.5 ATR within N bars?" (triple-barrier style labels matching your actual TP/SL)
- Models in order of complexity: logistic regression -> gradient boosting (LightGBM/XGBoost) -> (only if justified) small sequence models
- **Proper validation:** walk-forward splits with purging/embargo to avoid leakage between overlapping labels; final holdout untouched until the end
- Feature importance and stability analysis (does importance change wildly across windows? that signals overfitting)
- Probability calibration (the model's output should be a calibrated probability, unlike raw LLM confidence)
- Package as a `quant_agent` returning the same schema as other agents (direction + confidence), so the Lead Agent treats it like any other agent
- Model registry: save model file + feature list + training window + metrics + data hash per version

**Evaluation**
- Compare: Quant alone vs LLM agents alone vs combined, using the same backtester and gates
- Information coefficient / AUC / log-loss out of sample, plus trading metrics after fees
- Stability across regimes and across walk-forward windows (report the worst window)
- Overfit tests: shuffle labels (should destroy performance), reduce features, test on a different time period

**Exit gate:** the quant agent passes promotion gates on validation data, then is checked ONCE on the holdout. If it only works on the dev set, it does not ship.

**Upgrade loop:** retraining schedule (e.g., monthly), drift detection, feature additions, ensembling, LLM-assisted hypothesis generation (LLM proposes features; you test them with the harness).

**Risks:** data leakage, overfitting, regime change. Treat any "amazing" backtest as a bug until proven otherwise.

---

## 9. PHASE 6 - AUTONOMOUS OPERATION (v0.6) [post-program]

**Goal:** the system runs unattended on paper/testnet, safely, and you can trust its logs.

**Tasks**
- Scheduler/orchestrator: 15-min slow loop + fast price watcher as separate processes (or async tasks)
- Persistent state: open positions, equity, last decision hash, loop heartbeat (SQLite is fine); recover cleanly after crash/restart
- Idempotency: a restarted loop must not double-open trades or double-post hashes
- Watchdog/health agent (can be plain code): checks heartbeat, data freshness, API errors, chain connectivity; alerts and pauses trading on anomalies
- Alerts: Telegram/Discord/email on trade open/close, errors, kill-switch events
- Post-trade review agent: summarizes each closed trade, tags the failure/success pattern, and **proposes** hypotheses for `EXPERIMENTS.md`. It never changes live parameters by itself; humans run the experiment through the gates
- Cost controls: LLM call budgets, caching, graceful degradation if an API is down (agent -> neutral, not crash)
- Deployment: small VM or always-on machine; process supervisor; log rotation

**Evaluation: forward paper test (the most honest test you can run)**
- Run live on paper for at least 4-8 weeks with a frozen version
- Compare forward results to backtest expectations; large gaps mean the backtest was flattering
- Track uptime, missed cycles, duplicate actions, alert quality
- Chaos tests: kill the process mid-cycle, drop the network, return garbage from the LLM, return stale candles

**Exit gate:** forward paper test completes with no unhandled crashes, no duplicate trades, and performance within a reasonable band of backtest expectations (or the gap is understood and documented).

**Upgrade loop:** multi-asset support (ETH, SOL) using the same engine, shadow-mode testing (new version runs in parallel without trading, compared to the live one), smarter scheduling around volatility events.

---

## 10. PHASE 7 - UI/UX DASHBOARD (v0.7)

**Goal:** make decisions, risk, and proof easy to see and trust. Minimal version in Program Week 2-3; full version post-program.

**MVP (Streamlit)**
- Decision timeline: time, action, score, per-agent direction/confidence, rationale, tx link, Verify button
- Equity curve vs buy-and-hold, drawdown chart
- Open position card: entry, SL, TP, unrealized PnL
- Agent contribution panel: who agreed/disagreed on each trade
- System status: last heartbeat, kill-switch state, wallet balance, last tx

**Full version (post-program)**
- Calibration chart, performance by regime, trade list with filters
- Experiment/version comparison view (v0.3 vs v0.5 scoreboard)
- Controls: pause/resume, kill switch, parameter view (read-only for live; edits go through the experiment process)
- Replay mode for demos
- Public "proof page": paste a tx hash and see verification result
- If it is worth it later: move to Next.js; not before the core is solid

**Evaluation**
- Usability check with 2-3 people: can they explain what the agent did and why after 2 minutes?
- Load/time check: dashboard stays responsive with thousands of decisions
- Accuracy check: every number on screen matches the underlying files/DB

**Exit gate:** a new viewer can verify a decision end to end without help.

---

## 11. PHASE 8 - HARDENING, DOCS, RELEASE (v1.0) [Program Week 4]

**Tasks**
- Security pass: secrets, dependency check, no keys in git history, `.env.example` complete, wallet funded with testnet funds only
- Error handling and retries everywhere an external API is called
- README: problem, architecture diagram, setup (Windows-tested), how to run backtest / live paper / dashboard / verifier
- `EXPERIMENTS.md` cleaned into a readable story of what was tried and what worked
- Honest limitations section (paper only, not financial advice, LLM confidence uncalibrated, hash proves timing not correctness)
- Demo video: replay mode of a volatile day -> decision -> hash posted -> verify PASS -> tamper test FAIL
- Tweet + submission link before Oct 25

**Exit gate:** a fresh clone, following the README only, reaches a running demo.

---

## 12. REAL-MONEY NOTE (not part of this roadmap)

This roadmap does not include live trading with real funds. If you ever consider it, treat it as a separate project with its own bar, at minimum:
- Months of forward paper results that match backtests, across more than one market regime
- Statistically meaningful trade count and acceptable drawdown
- Hard capital limits you can afford to lose entirely, enforced by code and by wallet permissions
- A tested kill switch and a monitoring/alerting setup that has already caught real faults
- Awareness of legal and tax rules where you live

Most retail trading systems lose money after costs. Treat any early success with suspicion.

---

## 13. PHASE 9+ - CONTINUOUS IMPROVEMENT LOOP

Run this loop for every upgrade after v1.0. It is how you "keep upgrading" without fooling yourself.

1. **Observe:** review dashboard, post-trade reviews, failure logs, calibration plots
2. **Hypothesize:** write one testable idea (e.g., "adding funding-rate features improves out-of-sample AUC")
3. **Experiment:** implement on a branch; run backtest + walk-forward on dev data
4. **Evaluate:** compare against the current version and baselines using section 2.2 metrics
5. **Gate:** check section 2.4; if it fails, log and revert
6. **Shadow:** run the candidate in shadow mode alongside the live paper version for 1-2 weeks
7. **Promote:** tag a new version, update `CHANGELOG.md`, keep the old version for rollback
8. **Monitor:** watch for drift; schedule retraining and periodic holdout re-checks
9. **Repeat**

### Upgrade backlog (pick by expected value, not excitement)
- Better data: order book/funding/open interest, more reliable news feeds, BTC on-chain metrics
- Better models: retraining pipeline, ensembles, regime detection model
- Better agents: critic/risk agent, reflection agent, dynamic weighting by track record
- Better execution: exchange testnet OCO orders, smarter entries (limit vs market), partial take-profits
- Better Web3: IPFS, agent registry, on-chain outcome attestations, x402 data purchases, agent reputation score
- Better ops: monitoring dashboards, cost optimization, multi-asset support
- Better UX: public proof page, mobile-friendly view, alerts

### When to stop upgrading a component
Stop when the last 3 experiments on that component improved the validation metric by less than the noise level (use bootstrap confidence intervals to define "noise"). Move effort to the next weakest part of the system. That is what "converged" looks like, not perfection.

---

## 14. PHASE CHECKLIST (copy into your tracker)

- [ ] Phase 0: foundations, dummy hash posted
- [ ] Phase 1: backtester + baselines + metrics, no-lookahead tests pass
- [ ] Phase 2: TA agent + risk engine, ablation vs rules-only done
- [ ] Phase 3: News + Lead agents, threshold sweep, calibration report
- [ ] Phase 4: wallet, contract, hash-before-trade, verifier, tamper test, guardrails
- [ ] Phase 5: quant model trained with walk-forward, holdout checked once
- [ ] Phase 6: autonomous runner, watchdog, alerts, 4-8 week forward paper test
- [ ] Phase 7: dashboard MVP, then full version
- [ ] Phase 8: hardening, docs, demo, tweet, submission (by Oct 25)
- [ ] Phase 9: improvement loop running with versioned releases

---

## 15. VERSIONING AND RECORD-KEEPING

- Semantic-ish tags: `v0.x` per phase, `v1.0` at release, `v1.x` for gated upgrades
- Every decision record stores: code version (git commit), config snapshot, prompt hashes, model id
- `CHANGELOG.md`: what changed, which experiment justified it, metrics before/after
- Keep results in `reports/<version>/` so any past version's scoreboard can be reproduced
- Never overwrite the holdout set or its results history

---

*Not financial advice. Paper trading and testnet only.*
