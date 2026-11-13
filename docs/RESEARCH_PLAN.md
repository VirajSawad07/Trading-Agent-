# Research plan: a better approach (declared 2026-11-13)

The goal is an experimental bot for research, aimed at the most profit the evidence
supports. Demo only. This plan is written before any of the new tests are run.

## What the first round taught us

- `meta_breakout_regime` on gold: +0.105 R per trade, t 1.34, about 16 trades a year. Not proven.
- The same strategy on six other markets: 0 of 6 passed (HANDOVER.md).
- The real blocker is **too few trades**. To tell a +0.1 R edge from luck (t = 2, with R
  results spread about 1.2 R per trade) takes about **580 trades**. At 16 a year that is
  36 years. At 250 a year it is about 2.3 years. A slow strategy cannot be proven or
  disproven in any useful time, in a backtest or on demo.
- Fitting a model and a grid per market spends trials and invites overfitting (PBO 0.66 on gold).

## What changes in the method

1. **Replicate, don't optimize.** Take rules and parameters from published research and
   fix them before looking at our data. No grids. Each strategy is one trial.
2. **Judge the portfolio, not each market.** One rule applied to many markets is one test
   with many trades, not many tests with few.
3. **Prefer strategies that trade often**, so both the backtest and the demo give an answer in months.
4. **Lock a hold-out.** Bars from 2025-05-01 onward are not used until a strategy's rules
   are final. It is then run on the hold-out once.
5. **Same harness, same costs.** R-unit simulator, costs from `config/symbols.yaml`, 2x cost
   stress, shuffled-bar test, deflated Sharpe counting every trial in this plan.
6. **Experimental demo slots.** A strategy that passes the backtest and the hold-out gets
   its own magic number and ledger on demo, next to the gold bot, at minimum size.

## Candidate tracks, in the order they will be run

| # | Track | Rule source | Bars | Trades/yr (est.) | Why it is here |
|---|---|---|---|---|---|
| 1 | Intraday momentum on US indexes (US500, US30, USTEC) | Gao, Han, Li, Zhou (2018); Zarattini, Aziz, Barbon (2024) | M5/M30 | 150-250 per index | Most trades, so the fastest honest verdict. Costs are the main risk. |
| 2 | Trend following across about 25 markets (FX pairs, metals, indexes) | Moskowitz, Ooi, Pedersen (2012); Hurst, Ooi, Pedersen (2017) | D1 | 100-200 in total | The best-documented edge open to small traders. Needs a check only once a day. |
| 3 | Buying short dips in rising stock indexes | Connors-style RSI(2) rule with a 200-day trend filter | D1 | 30-60 | Different behaviour from trend, so it may offset trend's losing periods. |

Not pursued for now: order-flow or tick models (no data edge at retail speed), more
machine learning on single markets (the first round), and stock picking across the
broker's 12,000 share CFDs (cost and data quality unknown).

## Rules for each track (fixed now)

**Track 1, intraday momentum.** Trade the direction of the day's move once price leaves a
"noise band" around the open: band = open x (1 +/- average absolute move from the open at
that time of day over the last 14 days). Enter on a break of the band at a half-hour mark,
trail the stop along the band or the day's VWAP, and close everything before the session
ends. One position per index, risk per trade fixed in R. The older Gao rule (the first half
hour's direction predicts the last half hour) is run as a second, separate trial.

**Track 2, trend.** For each market: long if the 12-month return is positive, short if
negative, size by inverse 60-day volatility so each market risks the same, rebalance
weekly. A second trial averages 1-, 3- and 12-month signals. Portfolio risk target fixed
in advance.

**Track 3, dips.** Index above its 200-day average and RSI(2) below 10: buy at the close,
exit when the close is above the 5-day average or after 10 days, with a stop of 3x ATR.

That is 5 trials in total. Any change to a rule after seeing results counts as a new trial
and is recorded here.

## Pass and stop rules

- **Pass:** positive after costs with t > 2 across the whole portfolio, still positive at
  2x costs, beats 95% of shuffled runs, deflated Sharpe at least 0.95 over all trials in this
  plan, and positive on the hold-out.
- **Stop:** a track that fails is dropped, not re-tuned. If all three fail, that is a
  result, and the plan is revised in writing before more testing.

## Limits known in advance

- **Published edges shrink after publication**, often by half or more (McLean and Pontiff, 2016).
- **Broker history:** D1 runs from the 1990s for FX and 2004 for gold, but only from 2012
  for US500, US30 and DE40, and from 2022 for USTEC. Intraday history is shorter still and
  will be measured before Track 1 starts. No oil or crypto on this broker.
- **Costs:** the spread is 0.2-0.7% of the daily range on the main markets. Intraday
  strategies give up a larger share of each trade to it.
- **$1,000 account:** at the minimum lot, one day's range is about $5 on an FX pair and $7
  on US500, but $52 on US30 and $96 on gold. A daily strategy with normal-sized stops only
  fits FX and US500 at this size, so trading the full portfolio for real needs a cent
  account or more capital. Research and demo results in R are unaffected.
- **Running hours:** Track 1 needs the PC on during the US session (about 20:15 to 02:45
  Nepal time). Tracks 2 and 3 need one check a day.
