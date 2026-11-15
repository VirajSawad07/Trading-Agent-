# Real-money trading: for the account owner

Written 2026-11-16. This is for the person whose money is in the account, not for a
coding agent. Switching the bots to real-money trading is the account owner's decision,
made and carried out by hand. Coding agents (Claude Code, OpenCode) must not make that
change or place real trades. Nothing here is financial advice; the authors are not
licensed advisors.

## What the bots do on a real account today

They **do not trade**. On a non-demo account both bots run in **signals-only** mode: they
read the broker's prices, make their decisions and log them (dashboard, `*_signals`
ledgers), but their order functions are replaced with ones that raise an error
(`src/live/signals.py`). This is the safe way to watch them on the real account's prices.

## The evidence so far

- **Gold breakout bot:** backtest 2011-2026 made +0.105 R per trade over 258 trades, about
  16 trades a year. Not proven: t 1.34, against the 2 the project requires. 0 live trades so far.
- **Index dip bot:** backtest 2013-2025 made +0.062 R per trade over 493 trades (t 2.96), and
  +0.051 R over 88 trades on unseen 2025-2026 data. It still fails the project's
  overfitting check, and its demo trial (40+ trades, 12+ months) started only on 2026-11-15
  with 0 trades so far.
- Six other markets and four other strategies were tested; all failed.
- R = the amount risked on one trade. +0.06 R a trade means about 6p profit per £1 risked,
  on average, over many trades, with long losing runs in between (backtest worst: 10.8 R).

## What would happen on the £100 Switch Markets account

Facts as of 2026-11-16 (account equity £100, about $132):

| Market | Smallest trade | Loss if the bot's stop is hit | Share of the account |
|---|---|---|---|
| Gold (XAUUSDs) | 0.01 lots | about $32-42 | about 25-30% |
| S&P 500 (US500s) | 0.1 lots | about $43 | about 33% |
| Dow, Nasdaq, Germany 40 | 0.1 lots | about $160-280 | more than the account |
| France 40, Euro Stoxx 50, Australia 200 | 0.1 lots | about $25-41 | about 19-31% |

- The bots' own risk rule allows at most 5% of the account per trade (about £5 here), so
  with the rules as they are, **every signal on this account would be skipped**.
- Making them trade at £100 would mean allowing roughly a quarter of the account, or more,
  to be lost on a single trade. Two or three normal losses in a row would take most of it.
- This broker charges about 5 times the demo broker's overnight fee on gold longs, and the
  strategies have not been tested at its costs.

## What stands between the bots and real-money trading

So the owner knows what is involved, not as a recommendation:

1. **The demo-only lock**, `demo_account_only: true`, in `config/risk_limits.yaml` (used by
   the order gateway) and `config/risk_limits_1k.yaml` (used by the gold bot's risk
   checks). With either set, an order on a real account is refused.
2. **The signals-only switch** in `scripts/start_bot.ps1` and `scripts/start_dips.ps1`,
   which restarts the bots with `--signals-only` on a real account.
3. **Sizing that does not match the real account.** The gold bot's start script sizes
   trades as a $1,000 account, not the real £100; the dip bot sizes as a $100,000 account
   (about $500 risk per trade). Run against a real £100 account without changes, the dip
   bot would try to risk several times the whole balance on one trade.
4. **No live test of order handling** yet: no order has ever been filled, stopped out or
   closed by these bots, even on demo.

## A safer order of steps, if the owner goes ahead later

1. Let the demo trials run until each bot has real closed trades, and compare them with
   the backtest (`docs/RESEARCH_PLAN.md`, Revision 1, Step B).
2. Keep watching the real account in signals-only mode and compare its signals with demo.
3. Decide on an account size where the smallest trade risks a few percent, not a quarter,
   or a broker/account type with smaller lots (a cent account).
4. Only then, the owner changes the settings above by hand and watches the first trades closely.
