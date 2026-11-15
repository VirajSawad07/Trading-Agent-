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

### Track 3, buying dips in rising indexes: FAIL by the plan's rules, but the strongest result (2026-11-15)

Development period 2013-05 to 2025-04, daily bars, 8 indexes (US500, US30, USTEC, DE40,
JPN225, AUS200, FRA40, EUSTX50). Code: `src/research/index_dips.py`. The hold-out was
**not** run, because two checks failed.

| Trades (per yr) | Win rate | Avg R | t | Daily Sharpe (yr) | 2x costs | Max drawdown | Shuffled data |
|---|---|---|---|---|---|---|---|
| 493 (41) | 73% | +0.062 | 2.96 | 0.60 | +17.5 R (+0.035 R) | 10.8 R | real +30.7 R vs shuffled mean +5.0 R, p95 +15.5 R |

**Checks:** passed enough trades, profit after costs with t > 2, 2x costs, and beating 95% of
shuffled runs. **Failed:**
- **Shuffled data made money on average (+5.0 R, 15 of 20 runs).** The strategy only buys,
  and stock indexes rise over time; shuffling the order of days keeps that rise, so a
  long-only rule profits on shuffled data too. The check was meant to catch harness bugs.
  Here it shows that part of the result is just the indexes going up. The real result
  beats the shuffled average by about 26 R, or about +0.05 R per trade.
- **Deflated Sharpe 0.002 over 5 trials.** The threshold comes from how spread out the five
  trials' Sharpes are, and Track 1's Gao trial (Sharpe -2.39, driven by costs) spreads them
  a lot. Without that, it would still need a Sharpe well above 0.6 to pass.

**Detail:**
- **By index:** US500 +0.116 R (t 2.5, 106 trades), US30 +0.088 R, USTEC +0.144 R, DE40
  +0.041 R; FRA40 and JPN225 slightly negative.
- **Exits:** 433 at the 5-day average, 60 at the stop (about -1.03 R each). Average hold 3 days.
- **By year:** losing years 2018, 2020, 2022 and early 2025; best 2024 (+14.6 R).
- **Costs** are small here (0.027 R per trade), because trades are short and stops wide.

Trials used: 5 of 5. **All three tracks failed the plan's rules.** Per the plan, the next
step is a written revision of the plan before any more testing.

## Revision 1 (2026-11-15): confirm Track 3, nothing else

Written after all 5 trials failed, before any further test. It does not add trials or
change rules. It gives the one strategy that passed the money checks (Track 3, index dip
buying) two confirmation steps, each of which can stop it.

### What is frozen

- **Rules and code:** `src/research/index_dips.py` exactly as in commit `01e911e`: RSI(2) < 10
  above the 200-day average, exit above the 5-day average or after 10 days, stop 3x ATR(14).
- **Markets:** all 8 indexes, including FRA40 and JPN225, which lost in development.
- **Costs:** `config/research_costs.yaml` unchanged.
- **Not allowed** at any step: a different RSI level, average, stop or hold time; extra
  filters; dropping markets because they lost; re-running after seeing a result. Any of
  these would be a new trial and needs another written revision.

### Step A: the hold-out, run once

- **Data:** trades entered from 2025-05-01 to the end of the downloaded data (2026-11-12),
  about 18 months. Indicators may use earlier bars. The broker's Jul-Sep 2025 index hole is
  handled by the existing gap rule.
- **Expected:** about 40-60 trades. That is too few to prove an edge; the step exists to
  catch a clear failure.
- **Pass:** total R after costs above 0 **and** above the 5th percentile of 10,000
  bootstrap samples of the same number of development trades.
- **Fail:** the strategy is dropped. No second hold-out exists.
- **Command:** `python -m src.research.index_dips --holdout`.

### Step B: demo trial, only if A passes

- **Account:** the existing MetaQuotes demo, alongside the gold bot, with its own magic
  number (777102) and its own ledger. Orders go through the same gateway, risk engine and
  demo-only lock.
- **Sizing, for research:** as a $100,000 account at 0.5% risk per trade (about $500), so
  every index can be traded at its stop. JPN225 is left out of the demo: its minimum lot
  (1.0) with a 3x ATR stop risks about $4,200. Results are measured in R, as in the backtest.
- **What $1,000 could trade:** at the minimum lot only US500 fits, about $43 risk (4.3%)
  with today's volatility, inside the 5% limit. Every other index risks $159 to $415 at
  its minimum lot, too much for $1,000.
- **Length:** until 40 closed trades or 12 months, whichever comes later. Expected rate
  is about 3 trades a month across 7 indexes.
- **Stop early if:** cumulative R falls below -12 R (worse than development's worst
  drawdown of 10.8 R), or the bot is found to have traded differently from the backtest
  on the same bars (checked by replaying each demo trade through `trades_for`).
- **Pass:** average R after costs above 0 over the 40+ trades, and no rule mismatches.
  That is a low bar; it shows only that the strategy runs as tested and does not obviously
  fail. Money on a real account would need a further written decision by the account owner.

### Known weaknesses, stated now

- Part of the development result comes from indexes rising over time (shuffled data made
  +5 R on average). In a long bear market this strategy will mostly sit out or lose.
- The deflated Sharpe over this plan's 5 trials is 0.002. Passing A and B would not change
  that: the strategy stays unproven by the plan's strictest test.
- 40 trades cannot separate +0.06 R from 0 (that would need about 1,500). Step B is a
  check that nothing is broken, not proof of profit.

### Step A result: PASS (2026-11-15)

Run once with `python -m src.research.index_dips --holdout`, code unchanged since `01e911e`.

| Trades (2025-05 to 2026-11) | Win rate | Avg R | Total R | t | 2x costs | Bootstrap 5th pct (n=88) | Bootstrap median |
|---|---|---|---|---|---|---|---|
| 88 | 64% | +0.051 | +4.5 R | 1.26 | +2.0 R | -1.9 R | +5.5 R |

- **Pass:** total R is above 0 and above the bootstrap's 5th percentile. It sits at the 41st
  percentile of what the development trades would produce, so it looks like development, not better.
- **By index:** JPN225 +4.1 R (18 trades), US500 +2.8 R (9, all winners), US30 +1.0 R,
  USTEC +0.7 R, DE40 0.0 R; AUS200 -1.9 R, FRA40 -1.7 R, EUSTX50 -0.4 R. Five stops, all
  in AUS200, FRA40 and EUSTX50.
- **Data hole effect:** the broker's Jul-Sep 2025 hole in the US indexes and DE40 restarts
  the 200-day average, so those 4 indexes took no trades from about July 2025 to June 2026.
  Most hold-out trades come from JPN225, AUS200, FRA40 and EUSTX50.
- **What it does not show:** t 1.26 on 88 trades is not proof. It shows the strategy did not
  break on data it had never seen. Step B (demo) is next under the revision's rules.

### Step B started (2026-11-15)

`src/live/dip_trader.py` is running on the demo account from 2026-11-15, started at login
with the gold bot. Its rule decisions are tested against the backtest bar by bar
(`tests/test_research.py`), and `python -m src.live.dip_trader check` replays every logged
decision. Trade sizes at today's volatility: US500 1.1 lots ($473 risk), DE40 0.3 ($477),
FRA40 1.0 ($415), EUSTX50 1.0 ($361), US30 0.1 ($279), USTEC 0.1 ($267), AUS200 0.1 ($252).
The last three are at their minimum lot, so they risk less than $500; R is measured
against each trade's actual risk.

## Revision 2 (2026-11-16): two strategies that trade more often, declared before testing

Written before any Revision 2 test is run. Goal from the owner: more trades a year, still
passing the tests. Lessons from Tracks 1-3: costs decide (spread and overnight fees ate
Tracks 1 and 2), and short holds in rising stock indexes did best (Track 3).

### Track 4: turn of the month in stock indexes (daily bars)

- **Source:** Lakonishok & Smidt (1988); McConnell & Xu (2008): index returns concentrate
  in the last trading day of a month and the first three of the next.
- **Markets:** the 8 indexes of Track 3 (US500, US30, USTEC, DE40, JPN225, AUS200, FRA40,
  EUSTX50), daily bars from `data/raw/*_D1_mt5.csv`.
- **Rule:** buy at the close of the first bar on or after the second-to-last weekday
  (Mon-Fri) of the month; sell at the close of the third bar of the next month. Stop
  3x ATR(14) below entry (R = stop distance), checked against each day's low.
- **Expected:** about 12 trades a year per index, about 80-90 a year in total.

### Track 5: Track 3's dip rule on 4-hour bars

- **Source:** the Track 3 rule unchanged, applied to 4-hour bars instead of daily. This is
  an extension, not a published result.
- **Markets:** the same 8 indexes, 4-hour bars downloaded from the MT5 terminal
  (SwitchMarkets-Live feed; history from 2012 for US500 and US30).
- **Rule:** close above its 200-bar average and RSI(2) below 10: buy at the close. Sell at
  the close once above the 5-bar average or after 10 bars. Stop 3x ATR(14).
- **Expected:** several times Track 3's 41 trades a year; costs will matter more.

### Fixed for both

- **Costs:** `config/research_costs.yaml`, unchanged (pessimistic, from the demo broker).
- **Development data:** up to 2025-04-30. **Hold-out:** from 2025-05-01. That period was
  used once, by Track 3; it has not been used for these two rules.
- **Trial count:** 7 (the 5 of the plan plus these 2), for the deflated Sharpe.
- **Pass on development data:** at least 100 trades; average R after costs above 0 with
  t > 2; positive at 2x costs; beats the 95th percentile of 20 shuffled-data runs;
  deflated Sharpe at least 0.95 over the 7 trials.
- **Changed from Track 3, and why:** the check "shuffled data loses on average" is
  replaced by "beats the shuffled-data average by at least 2 standard errors of the
  strategy's total R". Both strategies only buy rising stock indexes, so shuffled data
  (which keeps the indexes' rise) makes money on average, as Track 3 showed; the check
  was meant to catch harness bugs, and the 95th-percentile check already tests edge.
  This change is declared before either track runs.
- **Then:** a track that passes runs once on the hold-out (pass = total R above 0 and above
  the 5th percentile of a bootstrap of its development trades). A track that fails is
  dropped, not re-tuned.
- **Known in advance:** the deflated Sharpe over 7 trials is likely to be the binding check:
  Track 1's Gao trial (Sharpe -2.39) widens the spread of trial Sharpes a lot.

### Track 4, turn of the month: FAIL (2026-11-16)

Development period 2012-08 to 2025-04, daily bars, 8 indexes. Code: `src/research/revision2.py`.

| Trades (per yr) | Win rate | Avg R | t | Daily Sharpe (yr) | 2x costs | Shuffled data |
|---|---|---|---|---|---|---|
| 773 (61) | 49% | -0.025 | -1.40 | -0.20 | -41.1 R | real -19.0 R vs shuffled mean +9.8 R, p95 +34.9 R |

- **Worse than random days.** Buying the same indexes for the same number of days at
  random (shuffled data) made +9.8 R on average; the turn-of-month timing made -19.0 R.
  No index was positive: US500, US30, DE40 and JPN225 were about flat; AUS200, FRA40 and
  EUSTX50 lost 5-6 R each.
- **Consistent with reports that the effect has faded** since it was published.
- Costs were small (0.029 R a trade), so this is not a cost problem.
- Dropped, not re-tuned. Hold-out not run.

### Track 5, dip rule on 4-hour bars: FAIL (2026-11-16)

Development period 2013-05 to 2025-04, 4-hour bars from the SwitchMarkets-Live terminal.
**7 indexes, not 8:** the terminal returned no 4-hour history for JPN225 ("Call failed",
retried once), found before the run.

| Trades (per yr) | Win rate | Avg R | t | Daily Sharpe (yr) | 2x costs | Shuffled data |
|---|---|---|---|---|---|---|
| 2,738 (229) | 63% | -0.029 | -3.09 | -0.60 | -245 R | real -80.0 R vs shuffled mean -94.1 R, p95 -52.6 R |

- **It did trade often:** 229 a year, against Track 3's 41.
- **Before costs it made about +0.03 R a trade; costs took about 0.06 R.** The European
  indexes lost the most (EUSTX50 -52 R, FRA40 -36 R), where the cost file's spreads are
  widest relative to a 4-hour move (0.20 and 0.14 R a trade).
- **US indexes were slightly positive** (US30 +0.041 R, t 1.75; US500 +0.013; USTEC +0.012),
  not enough to pass, and picking them now would be choosing winners after the fact.
- **Barely better than random:** shuffled data lost -94 R on average, the real rule -80 R.
- Dropped, not re-tuned. Hold-out not run.

### Where Revision 2 leaves things

Both new tracks failed. Seven trials in this plan have now run: only Track 3 (daily index
dips) has cleared the profit checks, and it is in its demo trial. The pattern holds: faster
strategies find small real effects before costs, and this broker's costs remove them.
