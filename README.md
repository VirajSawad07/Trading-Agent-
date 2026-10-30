# 🏛️ MT5 AI Quantitative Multi-Agent Trading Desk

> An institutional-grade, autonomous algorithmic trading platform for **MetaTrader 5 (MT5)** combining **Machine Learning (LightGBM)**, **Frontier LLM Macro Analysis (GPT-5.6)**, **Multi-Regime Technical Models**, and **Deterministic Mathematical Risk Controls**.

> **Current status:** research and demo paper trading only. No strategy has passed the test harness, and older performance figures in this README came from an unreliable backtest. See [HANDOVER.md](HANDOVER.md) for results and [docs/PAPER_TRADING.md](docs/PAPER_TRADING.md) to run the bot.

---

## 📑 Table of Contents
1. [Executive Summary: What Are We Doing?](#-executive-summary-what-are-we-doing)
2. [What Have We Done? (Milestones Completed)](#-what-have-we-done-milestones-completed)
3. [System Architecture & The Multi-Agent Council](#-system-architecture--the-multi-agent-council)
4. [Trading Strategies & Market Regimes](#-trading-strategies--market-regimes)
5. [Multi-Asset Scanning Universe](#-multi-asset-scanning-universe)
6. [Strict Risk Management & Safety Controls](#-strict-risk-management--safety-controls)
7. [What Is Going on Right Now? (Live Status)](#-what-is-going-on-right-now-live-status)
8. [CLI Commands & Operations Guide](#-cli-commands--operations-guide)
9. [Project Directory Layout](#-project-directory-layout)

---

## 🎯 Executive Summary: What Are We Doing?

Most retail trading bots fail because they either:
* **Overfit simple indicators** (e.g. basic EMA cross or RSI) and get destroyed when market conditions change.
* **Overtrade low-probability noise**, losing all profits to broker spreads, slippage, and commissions.
* **Rely blindly on LLMs**, which hallucinate specific price numbers and lack sub-millisecond execution control.

### Our Solution & Core Philosophy:
> **"AI and Machine Learning propose candidate opportunities; deterministic mathematical risk controls decide whether those decisions are allowed to execute."**

We have built a **hybrid quantitative desk** that connects directly into your desktop **MetaTrader 5 (MT5)** terminal on Windows. It monitors live candle closes on **Gold (`XAUUSD`)** and major currency pairs (**`EURUSD`**, **`GBPUSD`**), requires a consensus vote from specialized sub-agents, mathematically computes Expected Value ($EV > 0$) after friction, and executes orders automatically with hard Stop Loss (SL) and Take Profit (TP) levels.

---

## 🏆 What Have We Done? (Milestones Completed)

### 1. Data Engineering & Realistic Backtesting
* **MT5 Direct IPC**: Built high-performance Windows IPC connector (`src/data/mt5_connector.py`) fetching tick-by-tick and OHLCV data directly from MetaQuotes desktop memory without requiring third-party REST bridge servers.
* **Downloaded Real Data**: Downloaded 10,000 live broker M15 candles and 5,000 M5 candles.
* **Realistic Friction Engine**: Engineered event-driven backtesting (`src/backtest/engine.py`) accounting for exact broker spreads (25–40 pts), commissions ($7/lot round-trip), and execution slippage ($0.05/oz).

### 2. Machine Learning Signal Engine (LightGBM)
* **21 Stationary Alpha Features** (`src/features/alpha_features.py`):
  * **Momentum**: Rate-of-Change (ROC) across 3, 5, 10, and 20 bars.
  * **Volatility**: ATR ratios and Bollinger Bandwidth expansion.
  * **Mean-Reversion**: RSI (14) and Bollinger %B band position.
  * **Trend Alignment**: MACD histogram normalized by ATR, distance from EMA 50.
  * **Liquidity & Timing**: Volume Z-scores and cyclic session clocks (London / New York overlap).
* **Walk-Forward Validation** (`src/models/train_ml.py`): Chronological split (70% train, 15% validation, 15% out-of-sample test) preventing future-data leakage.
* **Calibrated Models**:
  * `models/ml/lightgbm_gold_m15.pkl`: Optimized for 15-minute trends.
  * `models/ml/lightgbm_gold_m5.pkl`: Calibrated for 5-minute price action.

### 3. Specialized Multi-Agent Consensus System
* **Regime Agent** (`src/agents/regime_agent.py`): Classifies market states into `TRENDING_BULL`, `TRENDING_BEAR`, `RANGING`, or `HIGH_VOLATILITY` (92nd percentile ATR volatility lockout to protect capital during news spikes).
* **Quant Agent** (`src/agents/quant_agent.py`): Evaluates ML probabilities and computes net dollar Expected Value ($EV$) against live broker spread, slippage, and commission.
* **Macro Agent** (`src/agents/llm_agent.py`): Integrated with OpenAI's flagship **`gpt-5.6-luna`** (with fallback to `gpt-5.5`, `gpt-4.1`, or `gpt-4o`) to evaluate institutional macro variables: US 10Y real yields, DXY dollar index, central bank gold reserves, and news calendar blackouts (CPI, NFP, FOMC).
* **Decision Coordinator** (`src/orchestration/coordinator.py`): Audits all sub-agents, detects conflicting signals, vetoes dangerous trades (e.g. shorting into a bullish trend), and builds structured `OrderProposal` objects.

### 4. Broader Multi-Regime & Multi-Asset Expansion
* **Multi-Regime Strategy**: Added **Trend-Pullback** entries (buying healthy dips in uptrends) and **Range Mean-Reversion** entries (buying oversold channel bottoms, selling overbought resistance).
* **Multi-Asset Universe**: Upgraded `live_trader.py` to scan multiple instruments simultaneously (`XAUUSD`, `EURUSD`, `GBPUSD`) with dynamic contract sizing (100 oz for Gold vs. 100,000 units for FX).

### 5. Live Execution & Safety Gateway
* **Demo Execution Gateway** (`src/execution/demo_gateway.py`): Dispatches native MT5 orders with attached SL/TP.
* **Hard Demo Verification**: Cryptographically checks `account.trade_mode == DEMO`. Strictly blocks real money accounts.
* **Portfolio CLI** (`src/portfolio.py`): Live account dashboard for floating PnL, balance, margin, and open tickets.
* **Emergency Kill Switch** (`src/kill_switch.py`): Instantly liquidates all positions and cancels pending orders.
* **Full Automated Test Suite**: 19 out of 19 unit and integration tests passing (`pytest`).

---

## 🏛️ System Architecture & The Multi-Agent Council

```
                        +-----------------------------+
                        |    MetaTrader 5 Terminal    |
                        | (Live Ticks, OHLCV, Spreads)|
                        +--------------+--------------+
                                       |
                                       v
                        +-----------------------------+
                        |   Data & Feature Engine     |
                        | (21 Alphas: EMA, ATR, RSI)  |
                        +--------------+--------------+
                                       |
                  +--------------------+--------------------+
                  |                    |                    |
                  v                    v                    v
           +--------------+     +--------------+     +--------------+
           | Regime Agent |     |  Quant Model |     | Macro Agent  |
           | Trend/Range/ |     |  (LightGBM)  |     | (GPT-5.6)    |
           | Vol Lockout  |     |   EV > 0     |     | Yields / DXY |
           +-------+------+     +------+-------+     +-------+------+
                   |                   |                     |
                   +-------------------+---------------------+
                                       |
                                       v
                        +-----------------------------+
                        |    Decision Coordinator     |
                        |  - Arbitrates Consensus     |
                        |  - Vetoes Contradictions    |
                        |  - Technical Fallbacks      |
                        +--------------+--------------+
                                       | Trade Proposal
                                       v
                        +-----------------------------+
                        |  DETERMINISTIC RISK ENGINE  |
                        |  - Dynamic ATR Lot Sizing   |
                        |  - Max 1% Risk / Trade      |
                        |  - 3% Daily Loss Lockout    |
                        |  - Max Spread Filter        |
                        |  - Mandatory Broker SL & TP |
                        |  - Demo-Only Verification   |
                        +--------------+--------------+
                                       | Approved Orders Only
                                       v
                        +-----------------------------+
                        |   MT5 Execution Gateway     |
                        |  (Sends Order into MT5)     |
                        +-----------------------------+
```

---

## 📊 Trading Strategies & Market Regimes

The desk does not rely on a single rigid setup. It dynamically adapts based on the active market regime:

| Market Regime | Strategy Activated | Technical Trigger | Risk / Exit Rule |
|---|---|---|---|
| **`TRENDING_BULL`** | **Trend Pullback Buy** | Price > EMA50, healthy RSI pullback (38–68), Bullish Macro | SL = Entry - 2.0×ATR<br>TP = Entry + 3.0×ATR |
| **`TRENDING_BEAR`** | **Trend Pullback Sell** | Price < EMA50, healthy RSI bounce (32–62), Bearish Macro | SL = Entry + 2.0×ATR<br>TP = Entry - 3.0×ATR |
| **`RANGING`** | **Range Mean Reversion** | Price $\le$ Lower Bollinger Band + RSI $\le 38$ (Buy)<br>Price $\ge$ Upper Bollinger Band + RSI $\ge 62$ (Sell) | SL = Entry $\pm$ 1.5×ATR<br>TP = Entry $\mp$ 2.0×ATR |
| **`HIGH_VOLATILITY`** | **Capital Preservation** | ATR ratio in 92nd+ percentile (news spikes/illiquidity) | **TRADING VETOED** (Zero exposure) |
| **Any Regime** | **Quant ML Alpha** | LightGBM directional probability dominance $\ge 55\%$ & $EV > 0$ | Friction-adjusted dynamic target |

---

## 🌐 Multi-Asset Scanning Universe

The bot can scan a multi-asset watch basket simultaneously on every candle close:

* **`XAUUSD` (Gold)**: High volatility safe-haven bullion asset ($100 oz contract size).
* **`EURUSD` (Euro / US Dollar)**: High liquidity FX pair with tightest spreads (~0.0 to 1.0 pt).
* **`GBPUSD` (British Pound / US Dollar)**: High momentum FX pair with institutional volume.

If Gold is consolidating or showing conflicting signals, the bot automatically evaluates setups across EUR/USD and GBP/USD!

---

## 🛡️ Strict Risk Management & Safety Controls

The system adheres to institutional risk rules defined in `config/risk_limits.yaml`:

1. **AI Never Executes Orders Directly**: Every proposal is vetted by `RiskEngine.validate_proposal()`.
2. **Fixed Fractional Equity Risk (1.0%)**:
   $$\text{Lots} = \frac{\text{Equity} \times 1.0\%}{\text{Distance to Stop Loss} \times \text{Contract Size}}$$
3. **Hard Circuit Breaker (3.0% Daily Drawdown)**: If floating or realized losses reach 3% in a single day, all trading is halted until the next session.
4. **Max Spread Filter**: If broker spread exceeds 50 points on Gold (or 20 points on FX), orders are blocked to prevent news slippage.
5. **Mandatory Stop Loss & Take Profit**: Every order is placed with hard SL/TP attached directly on the MT5 broker server.
6. **Hardware Demo Safety Lock**: The code validates `account.trade_mode == DEMO`. It is physically impossible to trade real funds with this repository.

---

## 🟢 What Is Going on Right Now? (Live Status)

* **Broker Account**: MetaQuotes-Demo `#114665794` (Viraj Sawad).
* **Balance**: `$99,999.80 USD` (100% Capital Preserved).
* **Active LLM Agent**: **`gpt-5.6-luna`** (Frontier Flagship Macro Model).
* **Timeframe**: **M5 (5-Minute Candles)**.
* **Active Watchlist**: `XAUUSD`, `EURUSD`, `GBPUSD`.
* **Tests**: 19/19 passing.

---

## 💻 CLI Commands & Operations Guide

### 1. Launch the Multi-Asset Live Trader
Monitors 5-minute candle closes across Gold, EUR/USD, and GBP/USD:
```powershell
.\.venv\Scripts\python.exe -m src.live_trader --symbols XAUUSD EURUSD GBPUSD --timeframe M5
```
*(To trade Gold only: `.\.venv\Scripts\python.exe -m src.live_trader --symbol XAUUSD --timeframe M5`)*

### 2. Check Live Portfolio & Earnings Dashboard
Run anytime in a separate terminal to view account equity, margin, and open tickets:
```powershell
.\.venv\Scripts\python.exe -m src.portfolio
```

### 3. Emergency Kill Switch (Close All Positions)
Liquidates all open positions and cancels all pending orders instantly:
```powershell
.\.venv\Scripts\python.exe -m src.kill_switch
```

### 4. Run Automated Test Suite
Verifies all 19 risk, ML, execution, and indicator tests:
```powershell
.\.venv\Scripts\pytest.exe -v
```

### 5. Retrain Machine Learning Models
```powershell
# Train M5 model:
.\.venv\Scripts\python.exe -m src.models.train_ml --csv data/raw/XAUUSD_M5.csv --horizon 6 --threshold 0.001

# Train M15 model:
.\.venv\Scripts\python.exe -m src.models.train_ml --csv data/raw/XAUUSD_M15.csv --horizon 8 --threshold 0.002
```

---

## 📁 Project Directory Layout

```
Trading plat/
├── config/
│   ├── config.yaml          # Symbol, timeframe, broker friction, and strategy defaults
│   └── risk_limits.yaml     # 1% risk per trade, 3% daily drawdown lock, max positions
├── data/
│   └── raw/                 # Downloaded MT5 live bars (XAUUSD_M5.csv, XAUUSD_M15.csv)
├── models/
│   └── ml/                  # Trained LightGBM artifacts (lightgbm_gold_m5.pkl, m15.pkl)
├── reports/                 # Backtest performance reports & metrics
├── src/
│   ├── agents/
│   │   ├── llm_agent.py     # GPT-5.6 Macro Analyst (Yields, DXY, Central Bank flows)
│   │   ├── quant_agent.py   # LightGBM Expected Value ($EV) Evaluator
│   │   └── regime_agent.py  # Market Regime Classifier (Trend, Range, Vol Lockout)
│   ├── backtest/
│   │   └── engine.py        # Event-driven backtesting engine with friction
│   ├── data/
│   │   └── mt5_connector.py # Windows IPC direct connection to MetaTrader 5
│   ├── execution/
│   │   └── demo_gateway.py  # MT5 live order execution gateway (Demo verified)
│   ├── features/
│   │   ├── alpha_features.py# 21 stationary quantitative alpha features
│   │   └── indicators.py    # Vectorized EMA, ATR, RSI, Bollinger Bands
│   ├── models/
│   │   └── train_ml.py      # Chronological walk-forward ML training script
│   ├── orchestration/
│   │   └── coordinator.py   # Multi-agent decision coordinator & consensus arbitrator
│   ├── risk/
│   │   └── risk_engine.py   # Deterministic risk engine, ATR lot sizer, circuit breaker
│   ├── live_trader.py       # Live multi-asset autonomous trading daemon
│   ├── portfolio.py         # Real-time portfolio status & PnL CLI
│   └── kill_switch.py       # Emergency position liquidator
├── tests/                   # 19 Unit & integration test files
├── .env                     # OpenAI API Key & Model Configuration (OPENAI_MODEL=gpt-5.6-luna)
├── requirements.txt         # Project Python dependencies
└── README.md                # System documentation
```
