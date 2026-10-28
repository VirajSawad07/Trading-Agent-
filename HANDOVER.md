# Handover: Reliable MT5 Trading Bot (Trading plat)

Written 2026-10-28. Read this first in the next session. No code has been changed so far. All work to date was assessment and planning.

## 1. Who and what

- **User:** Viraj. A complete beginner in trading. They explicitly want to be **taught along the way**, and they want the AI agents to make most decisions, including buy/sell.
- **Teaching style:** use the `socratic-study-method` skill. Give a mental model first, then a few problems to try cold. Do not hand over solutions to learning exercises. Name bugs directly. End with one check question. Skip this style for pure production work or plan discussion, which should get direct answers.
- **Goal:** a **reliable** MT5 bot, built on the existing project in `C:\Users\Viraj\Downloads\Trading plat`.
- **Capital:** an example of $200 to $400. This is demo only for now. Real money only much later, if the evidence supports it.

## 2. Decisions agreed so far

| Topic | Decision |
|---|---|
| M5 timeframe | **Dropped.** Costs dominate small moves, and there is only about 18 days of data (overfit risk). |
| Main timeframe | **H1** (the agent decides once per hour at candle close). |
| Comparison | **H4** (once every 4 hours). M15 is kept only for comparison. |
| Instruments | **Undecided.** FX (EURUSD, GBPUSD) fits $200 to $400. Gold needs about $1,500 or more for a normal H1 stop at 1% risk. |
| Who decides | Agents decide buy/sell/hold. **Deterministic code owns** risk limits, validation and demo-only enforcement. |
| LLM macro agent | **Advisory only** until a forward ledger shows it adds value. |
| Principle | "AI proposes, deterministic risk controls decide." |
| Instrument (2026-10-28) | **XAUUSD is the main focus** (project built for it). EURUSD runs through the same harness as a comparison. |
| Real capital (2026-10-28) | User plans **$600** for the first real account. Gold at min lot (0.01 = 1 oz) with a 1.5x H1 ATR stop risks ~$29 = **~4.8% of $600** (H4 ~9.8%). 1% risk on gold H1 needs ~$2,900. Unresolved: see section 7. |
| Demo length | Can shrink to 2-4 weeks if the 5-year backtest is strong; not skipped. |
| Model roadmap | 1) baselines (EMA trend, breakout) + LightGBM benchmark, 2) high-impact USD news blackout filter, 3) meta-labeling + regime detection, 4) challengers (transformer, RL for exits) kept only if they win in the harness, 5) LLM news sentiment advisory, judged forward. Scheduled retraining gated by the harness, no unsupervised self-modification. |
| Teaching style | `socratic-study-method` skill deleted by user. Explain in plain language; practice questions only if asked. |

## 3. Agreed order of work

1. Download multi-year data (H1/H4, plus M15 for comparison) for the chosen instruments.
2. Build the **honest test harness** before any retraining.
3. Run the **existing** strategy through the harness and compare M15, H1 and H4.
4. Retrain and judge with the same harness.
5. Fix the live plumbing (section 5).
6. Add a forward ledger (hash-chained decision log, with a plain-English reason per decision).
7. Demo forward-test for 4 to 8 weeks.
8. Real money only much later, and only if the evidence supports it.

### Harness contents (step 2)
- Cost model taken from MT5 symbol specs (spread, commission, slippage).
- Purged and embargoed walk-forward validation. Train on older data, grade on later unseen data, then slide forward.
- Deflated Sharpe Ratio.
- Probability of Backtest Overfitting (CSCV/CPCV).
- Random-walk sanity test: the strategy must **lose** after costs on shuffled or synthetic data.
- 2x cost stress test.
- Judge by **profit after costs**, not accuracy or F1.

## 4. Assessment of the current project

### Headline numbers are not credible
`reports/backtest_summary.json` reports Sharpe 11.2, +268% return, 64.7% win rate, profit factor 2.43, max drawdown 4.29% and 241 trades. Likely causes:
- Label overlap and leakage (no purge or embargo).
- In-sample evaluation.
- Optimistic fills.
- Tiny sample (M5 about 18 days, M15 about 4 months of data).

### `src/models/train_ml.py`
- A LightGBM 3-class model (HOLD/BUY/SELL). It uses a 70/15/15 chronological split with **no purge or embargo**.
- Labels look 8 bars ahead with a 0.002 threshold, so they overlap and leak across the split boundary.
- It reports accuracy and F1 only. It does not report profit after costs.
- Planned improvement: label by **"did price hit take profit before stop loss?"**, which matches how a trade ends. Add purge and embargo.
- Features come from `src/features/alpha_features.py` (`create_ml_dataset`, `get_feature_columns`) and `src/features/indicators.py`. **These have not been read yet.** Read them and audit for look-ahead use.

### `src/live_trader.py` flaws
- Lines 92-95 overwrite real equity with the fake `capital`, so the daily-loss and drawdown breakers can never trip.
- `daily_starting_equity` is set once and never reset each day.
- Line 153: `target_lots = fixed_lots if fixed_lots else calculated_lots` bypasses risk-engine sizing.
- Lines 136-140 force TP to 3x the SL distance, which invalidates the quant agent's EV calculation. The QuantAgent is built with `atr_multiplier_sl=1.5, atr_multiplier_tp=4.5`.
- Per-symbol exceptions are only printed, not logged or alerted.
- Defaults are still M5.
- Missing: stale-data handling, reconnect logic, and order idempotency.

### `src/execution/demo_gateway.py`
- The demo-only check is good. Magic number is 888999.
- The retry falls back from IOC to RETURN on **any** non-DONE result, which risks a **double fill**.
- Open positions are not filtered by magic number, so it can see or close other positions.
- `close_all_positions` has the same lack of magic filtering.

### `config/risk_limits.yaml`
- 1% risk per trade, 3% daily loss, 10% total drawdown.
- Max 2 positions, max spread 50 points, lots 0.01 to 2.0.
- `demo_account_only: true` and `enforce_stop_loss: true`.
- These limits are sensible, but the live code defeats them (see above).

## 5. Fixes to make to the live plumbing (step 5)
- Use real broker equity for risk checks. Keep any "simulated capital" as a separate sizing input.
- Reset daily starting equity each day. Measure drawdown from the equity peak.
- Always use the risk engine's lot size (cap it by the fixed lot if wanted, never bypass).
- Do not override the agent's TP. Keep the RR logic consistent with the EV math.
- Filter positions by magic number.
- Make orders idempotent: check whether a position or order already exists before retrying, and only retry on specific retcodes.
- Add reconnect, stale-bar and market-closed handling, and real logging.

## 6. Concepts already taught (do not re-teach from scratch)
- Candles (OHLC), timeframes M1/M5/M15/H1/H4/D1, one decision per candle close, mostly HOLD.
- Spread and commission as fixed costs, which take a bigger share of small moves.
- Overfitting vs underfitting (the user first called M5 "underfitting"; it is overfitting risk).
- Pip basics: 1 pip = 0.0001 and about $0.10 on 0.01 lots of EURUSD. 0.01 lots of gold = 1 oz, so $1 per $1 move.
- Position sizing: 1% rule, ATR-based stops, fractional Kelly (quarter to half).
- Why a model can't be graded on its own training data.
- LLM look-ahead bias: an LLM can't be honestly backtested on dates it has seen, so it needs forward evaluation.
- Model-training ingredients: data, features (past-only), label, LightGBM, walk-forward exam.

## 7. Open items

### Waiting on the user
- **Check question (latest):** "Pick one feature, e.g. ATR, and say in your own words why it might help the model decide when to trade." Unanswered.
- Earlier unanswered exercises: why a model can't be graded on its training data, problems 1 to 4, the pip question, and the 3-days-of-HOLD question.
- **Instrument choice:** FX vs gold.
- **Capital intent:** $200, $300 or $400, and whether it may grow.
- **MT5 readiness:** is MT5 open and logged in to the demo account, so multi-year H1/H4/M15 data can be downloaded for XAUUSD, EURUSD and GBPUSD?

### Data downloaded (2026-10-28)
- MT5 terminal: `MetaQuotes-Demo`, DEMO mode, 1:100 leverage. This is MetaQuotes' generic demo, **not the user's future real broker**; specs/spreads may differ.
- `data/raw/{XAUUSD,EURUSD}_{H1,H4}_mt5.csv`: 2021-01-04 to 2026-10-28, no gaps over 4 days. Columns include per-bar `spread`.
- M15 refused ("Invalid params", likely terminal max-bars limit). Skipped; M15 is comparison only.
- Historical median gold spread in the file is 5 points, but the live spread was 39 points. **The cost model must not trust the file's spread column**; use a realistic or stressed spread.
- The older `data/raw/XAUUSD_M5.csv` / `XAUUSD_M15.csv` may be synthetic: `src/download_data.py` silently falls back to generated data when MT5 is not connected. Don't use them.
- Download script: `python -m src.data.fetch_history --symbols XAUUSD EURUSD --timeframes H1 H4` (demo-only, no synthetic fallback).

### Harness built (2026-10-28) — step 2 done
- Code: `src/harness/` (`costs.py`, `simulator.py`, `account.py`, `stats.py`, `walkforward.py`, `sanity.py`, `strategies.py`), CLI `src/run_harness.py`, specs `config/symbols.yaml`, tests `tests/test_harness.py` (11 tests; full suite 37 pass).
- Run: `python -m src.run_harness --symbol XAUUSD --timeframe H1 --strategy ema_cross --random-runs 20`. Output in `reports/harness/`.
- Simulator rules: signal at bar close, fill at next open; bid bars, buys pay spread; slippage on entries and stops; gap through stop fills at open; SL wins if SL and TP share a bar; swap per night (triple Wed); results in R.
- Walk-forward: rolling 2y train / 3m test, 24-bar embargo, train trades must close before the embargo (purge). Config chosen by t-stat of R on train. Rule strategies simulate once per config and slice; trainable strategies (`trainable=True`, `fit`, `label_horizon_bars`) fit on 80% / validate on purged 20% / refit per fold.
- Stats: Deflated Sharpe (trials = grid size), PBO via CSCV (16 blocks), no-look-ahead check (truncated vs full signals), shuffled-bar random-walk test, 2x cost stress, account sim at $600 and $3,000 (capped at 2% risk vs forced min lot, 10% DD kill switch).
- Note: on pure noise CSCV gives PBO > 0.5 (not ~0.5), because IS and OOS halves share one fixed sample. That is expected.
- Strategies so far: `ema_cross` (the existing baseline, 81 configs), `donchian_breakout` (27 configs).
- First result, gold H1 ema_cross, OOS 2023-01 to 2026-10: 191 trades, +0.034 R/trade, t=0.46, DSR 0.01, PBO 0.24 -> **FAIL** (no real edge). At $600, 173 of 191 trades skipped because min lot exceeded 2% risk.

### Step 3 results: all 8 baseline runs FAIL (2026-10-28, OOS 2023-01 to 2026-10, 10 shuffled runs each)
| Run | Trades | Avg R | t | DSR | PBO |
|---|---|---|---|---|---|
| XAUUSD H1 donchian | 418 | +0.095 | 1.59 | 0.34 | 0.24 |
| XAUUSD H4 donchian | 191 | +0.080 | 1.01 | 0.50 | 0.68 |
| XAUUSD H4 ema | 134 | +0.064 | 0.73 | 0.09 | 0.45 |
| XAUUSD H1 ema | 191 | +0.034 | 0.46 | 0.01 | 0.24 |
| EURUSD (all 4) | 110-698 | -0.05 to -0.17 | <0 | 0.00 | — |
- Shuffled data lost money in every run, so the harness is sane.
- Gold breakout's small edge is **all longs** (H1: longs +0.18 R x 267, shorts -0.06 R x 151) while gold went 1,837 -> 4,049. It is probably riding the bull market, not a timing skill. Any gold model must be compared against "long-only" to tell skill from trend.
- EURUSD trend rules lose after costs on H1 and H4.
- Next: step 4 (LightGBM / meta-labeling on top of gold breakout signals) judged by the same harness, plus a long-only benchmark.

### Step 4 results: meta-labeling (2026-10-28)
- Code: `src/harness/meta_strategy.py` (`MetaLabelBreakout`, LightGBM on 17 point-in-time features, labels = each breakout signal graded as its own trade inside the fit window only; fixed 2x/3x ATR bracket chosen before testing; grid lookback {20,50,100} x threshold {0.50,0.55,0.60}). `long_only=True` variant. Benchmark `donchian_long` in `strategies.py`. Simulator got `independent=True` and a `signal_time` column. Walk-forward: trainable strategies need `min_val_trades=10` in the validation slice (was 30, which made the model sit out 12 of 16 folds and produced a misleading +0.46 R from a single 2025 rally). Meta fits/features cached by lookback. 17 harness tests, 40 total pass.
- Results, gold, OOS 2023-01 to 2026-10 (buy & hold +120%):

| Run | Trades | Avg R | t | DSR | PBO | Verdict |
|---|---|---|---|---|---|---|
| H1 meta (both directions) | 145 | +0.153 | 1.47 | 0.44 | 0.23 | FAIL |
| H1 meta long-only | 129 | +0.276 | 2.47 | 0.86 | 0.38 | FAIL (DSR) |
| H1 donchian long-only | 321 | +0.084 | 1.20 | 0.75 | 0.38 | FAIL |
| H4 donchian long-only | 131 | +0.420 | 3.85 | 1.00 | 0.91 | FAIL (PBO, shuffled profitable) |
| H4 meta / meta long | 76 / 49 | +0.22 | ~1.3-1.5 | ~0.6 | 0.47-0.76 | FAIL (too few trades) |

- **Key finding: every "edge" is gold's bull market.** Quarterly R tracks gold's quarterly return. H1 meta long-only lost ~4 R over 2023-2024 and made ~36 R in 2025Q1-2026Q1 (gold +19%, +17%, +12% quarters); it lost in 2026Q2 when gold fell 14%. The meta-filter does improve long-only breakout (+0.28 vs +0.08 R/trade), but no strategy shows timing skill independent of trend.
- The shuffled-bar test keeps the overall drift, so for long-only strategies it measures trend exposure (beta). "Beats 95% of shuffled" is the meaningful check there, and "shuffled loses" is not.
- DSR counts only each run's own grid. Across all runs we have now tried ~10 strategy variants, so the real trial count is higher and the DSRs are optimistic.
- Recommended next: get data that includes a gold bear market (2011-2015, the 2013 crash) to test the long-bias strategies out of a bull regime; add a trend/regime filter that can stand aside or go short in downtrends; count all trials globally.

### Long-history test, 2011-2026 incl. gold bear market (2026-10-28)
- Data: `data/raw/XAUUSD_{H1,H4}_mt5_2009.csv` (H1 from 2009-09-25, 99,997 bars at the terminal's 100k max-bars limit; H4 from 2008-01). Run with `--data-tag _2009`. `fetch_history.py` now fetches per year, takes `--tag`, and drops the still-forming last bar.
- Results (OOS from ~2011, 61 folds H1 / 68 folds H4):

| Run | Trades | Avg R | t | DSR | PBO | Notes |
|---|---|---|---|---|---|---|
| H1 meta (both directions) | 598 | +0.063 | 1.25 | 0.61 | 0.38 | Beats every shuffled run (shuffled p95 -18 R vs real +38 R). Fails t>2 and DSR. Best lead. |
| H1 meta long-only | 433 | +0.020 | 0.33 | 0.30 | 0.69 | The 2023-26 "+0.28 R" collapsed: it was the bull market |
| H4 donchian long-only | 484 | +0.118 | 2.07 | 0.97 | 0.97 | Only 3 configs; PBO 0.97; shuffled (drift kept) also profits -> trend exposure |
| H4 meta (both) | 200 | +0.097 | 1.13 | 0.43 | 0.31 | Sat out half the folds |
| EMA cross H1/H4, donchian both H1/H4, H1 donchian long, H4 meta long | | <= +0.01 or negative | | | | FAIL |

- Losses cluster in choppy/sideways years (2018, 2019, 2021, 2022) for almost every strategy. Trend/breakout rules on gold have no robust edge after costs across regimes.
- Conclusion: **nothing is tradeable yet.** Long-only gold edges were the 2023-26 bull market. The only skill-like lead is the H1 meta-model on both directions (consistent with a weak filter effect), not yet significant.
- Ideas for next round (each adds trials; set a global trial budget first): chop/regime feature or stand-aside rule for sideways markets, expanding (not 2y rolling) training window for the meta-model, news blackout filter (roadmap item 2), a mean-reversion primary for ranging regimes.

### Meta-model improvement round (trial budget: 2 variants x 9 configs, declared before running)
- Added: `--anchored` (expanding training window, `make_folds(anchored=True)`), `meta_breakout_regime` (adds efficiency ratio 20/100, choppiness 14/100, EMA200 slope, ATR percentile), and "DSR (all trials)" that counts every config in every saved XAUUSD report (525 at this point). The pass check now uses the all-trials DSR. 42 tests pass.
- Results, gold H1 2011-2026:

| Variant | Trades | Avg R | t | DSR (all 525 trials) | PBO | Notes |
|---|---|---|---|---|---|---|
| Rolling 2y (previous) | 598 | +0.063 | 1.25 | n/a | 0.38 | Account sim hit the 10% kill switch in Dec 2017 |
| Anchored | 246 | +0.013 | 0.16 | 0.09 | 0.44 | Worse; loses at 2x costs |
| Anchored + regime features | 258 | +0.105 | 1.34 | 0.33 | 0.66 | Chop-year losses mostly gone (2018 +5, 2021-22 +3 vs -26 before), but profit concentrated in 2012 and 2026; PBO 0.66 |

- **Budget spent; all fail.** Regime features do what they were meant to (fewer losses in sideways years) but the edge is still not significant and the config choice looks overfit (PBO 0.66).
- Recommendation: stop tuning the breakout family. Either (a) research a different signal family (mean reversion in ranges, session effects) under a new declared budget, or (b) do step 5 (live plumbing) + step 6 (forward ledger) and paper-trade the regime variant on demo purely to collect truly unseen data. Not for real money.

### Steps 5 and 6 done: live plumbing + forward ledger (2026-10-28)
- **Risk engine** (`src/risk/risk_engine.py`): total-drawdown breaker measured from the equity peak; `sizing_equity` input kept separate from the breakers. The "any account under $500 may trade 0.01 lots" rule is gone: the min lot is allowed only if it risks at most `max_min_lot_risk_pct` (2%, in `config/risk_limits.yaml`).
- **Gateway** (`src/execution/demo_gateway.py`): every query and close is filtered by magic number. The filling mode is read from the symbol, with no IOC-to-RETURN fallback. Orders carry a client tag, and before any retry the gateway checks whether the tagged position already exists. Only REQUOTE / PRICE_CHANGED / PRICE_OFF are retried, so there are no double fills. New methods: `modify_sltp` and `position_deals`.
- **`src/live_trader.py`** (old multi-agent path): no longer overwrites real equity; resets the daily baseline each day; tracks peak equity; always uses risk-engine lots (`--lot-size` is now only a cap); no TP override; defaults to H1. It still runs the untested QuantAgent, so **use the paper trader instead**.
- **`src/live/paper_trader.py`** (new): runs the harness-tested `meta_breakout_regime` with anchored training, using the same rules as the simulator (`plan_actions`):
  - decide at bar close, enter at the next open, stop 2x ATR / target 3x ATR re-anchored to the fill;
  - an opposite signal reverses the position; close after 240 bars.
  - **Refit:** every 3 months via `fit_for_live`, which reuses the walk-forward fold code (a test proves it picks the same config as the backtest fold).
  - **Safety:** demo check every loop; reconnect with backoff; no new entries if the bar opened more than 15 minutes ago or the price feed has been stale for 2 minutes.
  - **Equity:** sizing equity (default $3,000) plus the bot's own P&L, which feeds the daily and total breakers. A 10% drawdown halts trading for good.
  - **State:** kept in `reports/live/state_*.json`; the model is saved in `models/live/` (both gitignored).
  - Default magic is **777101**, separate from the old trader's 888999.
- **`src/live/ledger.py`** (new): append-only SHA-256 hash chain. Every bar decision, order, block, error and closed trade gets a plain-English `reason`. Closed trades record P&L in USD and in R, plus the fill cost compared with the tested next-open fill. Commands: `python -m src.live.ledger verify|summary <file>`. Dry runs write to a separate `_dry` ledger.
- **Verified on demo #114665794 (dry run):**
  - History 2009 to now has 100,004 bars; the fit takes about 2s and chose lookback 100 / threshold 0.5.
  - The first decision was "No breakout". A forced-signal dry run gave "would BUY 0.01 lots, risking $23.54 (0.78%)" at $3,000. At $600 it was blocked because the min lot would risk more than 2%.
- 55 tests pass, including the new `tests/test_live.py` (13 tests).
- **To start paper trading:** `python -m src.live.paper_trader` with MT5 open on demo; leave it running for 4 to 8 weeks (step 7). Check progress with `python -m src.live.ledger summary reports/live/ledger_XAUUSD_H1.jsonl`. Expect only a few trades per month.

- **Dashboard** (`src/live/dashboard.py` + `dashboard.html`, read-only): `python -m src.live.dashboard`, then open http://127.0.0.1:8050. It shows running status (from the state-file heartbeat), ledger integrity, the demo check, bot equity, the open position, hourly candles with the breakout channel, cumulative R vs the backtest pace, and the activity feed. It cannot trade. The old `src/web/` dashboard belongs to the old multi-agent bot.

### Not yet done
- Run step 7: 4 to 8 weeks of demo paper trading, then compare forward R with the backtest (+0.105 R per trade, about 17 trades a year).
- Not yet tested on demo: a real order fill, the SL/TP re-anchor, and closed-trade reconciliation. The first real signal will exercise them, so check the ledger after it.
- `src/download_data.py` still silently generates synthetic data; fix or delete it. Session flags in `indicators.py`/`alpha_features.py` assume UTC but bars are server time (UTC+2/+3).
- Decide how to handle gold sizing at $600 (fund more, find a broker with 0.001 lots, or trade EURUSD live first).
- Read `src/features/alpha_features.py` and `src/features/indicators.py` and audit them for leakage.
- Read the agents, risk engine, backtest code and data connector (`src/agents/`, `src/risk/risk_engine.py`, `src/data/mt5_connector.py`, `src/orchestration/coordinator.py`).

## 8. External sources reviewed
- **TradingAgents**: a research scaffold for equities with a simulated exchange only. Not production-ready for MT5.
- **ai-hedge-fund**: an educational proof of concept that makes no real trades.
- **gs-quant**: needs Goldman institutional credentials and is derivatives-focused. Not usable here.
- **QuantGPT (quantgpt.co)**: an unverified promo, US stocks via Alpaca only. Irrelevant to MT5.
- The X posts could not be fetched (HTTP 402). The user pasted the contents, and the claims were critiqued, not trusted.
- Methods used as references: purged k-fold with embargo, CPCV, PBO, Deflated Sharpe Ratio. I did not read full papers or repo code, only summaries. Flag that when citing.

## 9. How to start the next session
1. Say hi and give a short recap of section 2.
2. Re-ask the ATR check question, or let the user ask what they want first.
3. Once the user picks the instruments and confirms MT5 is open and logged in to the demo account, start step 1 (data download).
4. Do not write code or download data until the user says go.
