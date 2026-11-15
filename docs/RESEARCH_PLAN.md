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

## Results

### Track 1, intraday momentum: FAIL (2026-11-15)

Development period 2018-03 to 2025-04 (USTEC from 2022-07), half-hour bars, costs from
`config/symbols.yaml`. Code: `src/research/intraday_momentum.py`; reports in `reports/research/`.
The hold-out was **not** run, because neither trial passed on development data.

| Trial | Trades (per yr) | Avg R | t | Daily Sharpe (yr) | 2x costs | Shuffled data | Verdict |
|---|---|---|---|---|---|---|---|
| A noise band | 3,730 (525) | +0.036 | 1.40 | 0.41 | -125 R | beat all 20 runs (their mean -267 R) | FAIL |
| B Gao last half hour | 4,007 (564) | -0.216 | -8.3 | -2.39 | -1,379 R | worse than the shuffled 95th percentile | FAIL |

- **A, by index:** US500 +0.044 R (t 0.99), US30 0.000 R, USTEC +0.121 R (t 2.05, 568 trades).
- **A is the most interesting result so far.** Before costs it makes about +0.11 R per trade
  and it beats every shuffled run, so the intraday momentum effect looks real on this data.
  But costs (about 0.07 R per trade) take two thirds of it, and it loses at 2x costs. It
  would need materially cheaper index trading than this broker's spreads to be worth running.
  Per the plan it is not re-tuned.
- **B loses before costs** (about -0.09 R gross), so the published last-half-hour effect is
  absent or reversed here. Costs make it clearly negative.
- **Deflated Sharpe** is 0.00 for both, counted against the plan's 5 trials.
- **Data fix, decided before re-reading results:** the broker's Oct-Dec 2024 half-hour bars
  for all three indexes are near-flat (median bar range 0.1-0.5 bps against about 15-30
  normally), which produced trades of +/-1,000 R or more. Days whose median bar range is
  under a fifth of the symbol's typical day are now dropped (about 50 days per index).
  This was found and fixed after the first run; both trials still fail without it.

Trials used so far in this plan: 2 of 5.

### Track 2, trend following: FAIL (2026-11-15)

Development period 1995-12 to 2025-04, daily bars, 23 markets: 10 FX pairs, 5 metals (gold,
silver, platinum, palladium, copper) and 8 stock indexes. Each market joins once it has a
year of history; indexes only from 2012 to 2019, so the 1990s-2000s are mostly FX.
UK100 was left out before the run: its broker history has a 3-year hole.
Costs: `config/research_costs.yaml`, fixed before the run. They are on the pessimistic side:
they were written on a Sunday, when live spreads are wide, and today's swap rates are
applied to all history. Code: `src/research/trend_following.py`. The hold-out was **not** run.

| Trial | Sharpe (yr) | t | Return/yr | Vol/yr | Max drawdown | 2x costs | Shuffled data | Verdict |
|---|---|---|---|---|---|---|---|---|
| A 12-month trend | 0.16 | 0.90 | +1.3% | 19.5% | 70% | -2.5%/yr | beat 95% (p95 Sharpe 0.00) | FAIL |
| B 1/3/12-month blend | 0.06 | 0.30 | -0.4% | 15.6% | 74% | -3.2%/yr | did not beat 95% | FAIL |

- **Before costs** A made +4.5% a year (Sharpe 0.32, t 1.78) and B +2.1% (Sharpe 0.21).
  Costs per year: A 0.4% trading and 2.6% financing; B 0.6% and 1.7%. **Financing (swap)
  is the biggest cost**, and with no financing at all A still only reaches t 1.66.
- **A's trend effect looks real but weak.** It beats the shuffled-data runs, but at a
  Sharpe far below the published 0.7-1.0 (futures, 1985-2009), consistent with the widely
  reported weakening of trend following since 2009 and with a universe that is mostly FX.
- **Realised volatility was about twice the 10% target**, because the FX pairs move
  together; per-market sizing ignored correlation, as the plan specified.
- **By market (A, total over the period):** best GBPJPY +39%, USDJPY +36%, NZDUSD +28%;
  worst platinum -13%.
- **Deflated Sharpe** is 0.00 for both, counted against the plan's 5 trials.

Trials used so far in this plan: 4 of 5.
