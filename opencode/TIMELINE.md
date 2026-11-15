# Timeline of the project

All times are Nepal time (UTC+5:45). Commit hashes link the history in git. Earlier work
(before 2026-10-28) is described in `HANDOVER.md`.

## 2026-10-28: honest testing, the gold bot, and the first live plumbing

- 20:45 `1470b37` Test harness built: realistic costs, walk-forward tests, overfitting
  checks (deflated Sharpe, PBO), shuffled-data and doubled-cost tests, look-ahead check.
- 21:25 `64b8f45` Gold model round: LightGBM filter on a 100-hour breakout with market-regime
  features. Result: +0.105 R a trade, about 16 trades a year. Not proven (t 1.34).
- Decision: AI may propose trades, but fixed risk rules decide. Demo account only.
- 23:21 `bc89905` Live plumbing: risk engine fixes, demo order gateway (no double fills),
  gold paper trader, hash-chained ledger of every decision.
- 23:38 `03dcaff` First read-only dashboard.
- 23:46 `ef724ad` Owner plans a $100k funded account: bot sized as $100k at 0.5% risk.

## 2026-10-29 to 10-31: crash fix and the six-market test

- 01:18 (10-29) `a9d44b9` Fix: a Windows file lock was being treated as a live-account stop.
- 02:27 (10-29) `45bbe94` Test declared in advance: the gold strategy on 6 more markets.
- 22:41 (10-30) `f7d0bbd`, `9698edd`, `f1f6697` Silver result recorded; data downloader no
  longer writes fake prices silently; paper-trading guide.
- 17:03 (10-31) `7cbd3b9` Result: **0 of 6 markets pass**. Gold stays the only market.
- Owner asked how to earn more; answer recorded: more trades need a real edge, not more risk.

## 2026-11-01 to 11-10: the bot was off

- The PC was shut down on 11-01 at 02:34 and most nights after, so the bot missed about
  6 trading days.
- 11:38 (11-10) `a248742` Autostart at login, and a restart loop if the bot exits.
- Owner's plan changed: **$1,000 real account, no funded account.**
- 12:23 (11-10) `82e988b` Bot sized as $1,000 trading gold at the minimum lot (about 3-4.5%
  risk per trade, up to 5%, halt at -40%). Owner accepted that risk.

## 2026-11-12 to 11-13: reliability, then a new research plan

- 19:28 (11-12) `5a7288e` MT5 froze for up to 6 hours ("IPC timeout"); watchdog now
  restarts it after 10 minutes. Gold's second breakout was skipped (model 41%).
- 10:33 (11-13) `b45eb9b` New research plan declared before any test: three strategies
  from published research, rules fixed in advance, recent data locked away.

## 2026-11-15: research results, the dip bot, and the real account

- 19:18 `5b3da17`, `23d69be` Plain-language status and plan (`docs/STATUS_AND_PLAN.md`).
- 19:29 `9a81dfa` Track 1, intraday index momentum: **fail**. Real effect before costs,
  but the broker's spreads take two thirds.
- 19:38 `5056f14` Track 2, trend following on 23 markets: **fail**. +4.5%/yr before costs,
  +1.3% after; overnight fees are the biggest cost.
- 19:41 `01e911e` Track 3, buying dips in rising indexes: +0.062 R over 493 trades (t 2.96),
  survives doubled costs, but fails two of the plan's checks.
- 19:43 `a19c922` Plan revision: Track 3 gets one hold-out run and a demo trial, rules frozen.
- 19:48 `62499d1` Hold-out run once: **pass**, +0.051 R over 88 unseen trades.
- 19:57 `194fc67` Index dip bot starts on demo next to the gold bot (7 indexes, magic 777102).
- About 23:00: owner logged MT5 in to a **real Switch Markets account (£100, 1:1000)**.
  Both bots refused it, as designed.
- 23:09 `c87e04b` Dashboard overview of both bots.
- 23:30 `592e078` **Signals-only mode** on real accounts: bots log decisions on the real
  prices with orders disabled; broker names mapped (`XAUUSDs`, `US500s`, `F40s`,
  `STOXX50s`...). Dashboard rebuilt: account stats plus one tab per market.
- 23:42 `1c5ba42` Dashboard shows each market open or closed and when it reopens, in local time.

## 2026-11-16: moving to the second laptop

- 00:30 `1a6906e` Ledgers committed; repo pushed to `VirajSawad07/Trading-Agent-` (public)
  as well as the private `VirajSawad1021/Trading-Agent`.
- Owner decided to run the bots on a cousin's laptop in the UK on the **same account**, so
  the Nepal laptop's bots were stopped and its autostart disabled.
- This `opencode/` folder added for OpenCode on that laptop. The history downloader now
  reads prices on real accounts too (read-only) and maps broker names.

## Where things stand

- Gold bot: 0 trades on demo since 2026-10-28. Unproven edge.
- Index dip bot: demo trial started 2026-11-15, 0 trades. Needs 40+ trades / 12+ months.
- Real account: signals only. With £100, every signal would be skipped by the 5% risk rule.
- No strategy has passed every check. See `opencode/LIVE_ACCOUNT.md` before any thought
  of real-money trading.
