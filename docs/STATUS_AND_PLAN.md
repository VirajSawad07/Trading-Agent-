# Status and plan (2026-11-15)

Plain-language summary of where the trading bot stands, what we plan to do, and what it
would take for it to win. Details are in `HANDOVER.md` and `docs/RESEARCH_PLAN.md`.

## 1. The goal

A bot that trades by itself on MT5 and makes money that holds up in real trading, not
just in a backtest. The AI model proposes trades; fixed risk rules decide whether they are
allowed. The first real account is planned at **$1,000**. Everything runs on a **demo
account** until the evidence says otherwise.

## 2. Where we are now

**What is built and working**

| Part | State |
|---|---|
| Testing harness (walk-forward tests, overfitting checks, cost stress, shuffled-data test) | Working, 62 tests pass |
| Gold bot on demo (hourly breakout strategy with a model that filters trades) | Running |
| Risk rules ($1,000 sizing, 5% max risk per trade, 6% daily stop, 40% total stop) | Working |
| Tamper-evident trade ledger, with a plain reason for every decision | Working |
| Live dashboard at http://127.0.0.1:8050 | Working |
| Autostart at login, auto-restart after a crash, MT5 watchdog | Working |

**The gold bot's record so far (demo, since 2026-10-28)**

- Trades: **0**. Profit or loss: **$0**.
- Hourly checks made: 69. Breakouts seen: 2. Both were skipped because the model gave
  them a 39% and 41% chance of profit, and it needs 50%.
- The bot has missed many hours: the PC was off (including 9 days from Nov 1 to Nov 10)
  and MT5 froze for hours. Since the watchdog went in on Nov 12, outages have lasted at
  most 8 minutes.
- Not yet tested live: a real order fill and the recording of a closed trade. The first
  trade will test them.

**What the tests say**

| Test | Result |
|---|---|
| Gold strategy, 2011-2026 backtest | +0.105 R per trade, about 16 trades a year. **Not proven** (t 1.34; needs 2). |
| Same strategy on 6 other markets | **0 of 6 passed.** |

R is the amount risked on one trade (about $32 on the $1,000 account).

## 3. The honest problem

1. **The edge is unproven.** Gold's backtest result could still be luck.
2. **It trades too rarely.** About 16 trades a year means that, even if the edge is real,
   $1,000 earns about **$50 a year**, and it would take decades of trades to prove the edge.
3. **$1,000 is small.** Even a very good strategy (+25% a year) earns about $250 a year on it.

So the current bot is safe and working, but it cannot earn meaningful money as it is.

## 4. The plan

**Step 1. Keep the gold bot running on demo.** It costs nothing and tests the machinery
(orders, stops, records).

**Step 2. Test three new strategies that trade far more often.** The rules come from
published research and are fixed before testing, so we are not fitting them to our data.
Recent prices (from May 2025) are locked away for one final check.

| # | Strategy | Trades per year | Status |
|---|---|---|---|
| 1 | Intraday momentum on US stock indexes: follow the index when it breaks out of its normal range for that time of day, close before the session ends | 150-250 per index | **Next.** Data checked: half-hour prices from 2018 for the S&P 500 and Dow, from 2022 for the Nasdaq. |
| 2 | Trend following across about 25 markets, checked once a day | 100-200 in total | After 1 |
| 3 | Buying short dips in rising stock indexes | 30-60 | After 2 |

**Step 3. Put anything that passes on demo** next to the gold bot, with its own record,
for at least 4-8 weeks.

**Step 4. Go live small**, only for a strategy whose demo results match its backtest.
Going live is done by the account owner, not by the bot's developer tools.

**Step 5. Grow the account** with savings, or a funded account later, once results justify it.

## 5. What a winning bot needs

A bot wins when all five of these hold together:

1. **A real edge.** Positive after costs, still positive when costs are doubled, and not
   explained by luck or by trying many settings.
2. **Enough trades.** Hundreds a year across markets, so the edge shows up in months and
   bad luck averages out.
3. **Small risk per trade.** So a normal losing streak cannot end the account.
4. **Reliable running.** Always on, no missed hours. A cheap always-on server (VPS) fixes
   the PC-off problem.
5. **Demo results that match the backtest** before any real money.

Today we have 3 working, 4 partly working, and 1, 2 and 5 still open. The research in
Step 2 is aimed at 1 and 2.

## 6. What could go wrong

- All three new strategies may fail. Published edges often shrink by half or more once
  they are public.
- Trading costs matter most for the intraday strategy.
- At $1,000 and the smallest trade size, only currency pairs and the S&P 500 fit a
  normal risk level. A cent account or more capital would be needed for the rest.
- No strategy is guaranteed. Most people who trade lose money.

## 7. Things to avoid

Raising risk to earn faster, doubling trade size after losses, picking the best of many
backtests, and paying for signals or courses.
