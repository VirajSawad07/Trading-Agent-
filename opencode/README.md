# For OpenCode (or any coding agent) on the second laptop

This folder hands the project over from the first laptop (Nepal, Claude Code) to a second
laptop (UK, OpenCode). Read these in order:

1. `opencode/TIMELINE.md`: what was built and decided, with dates and times.
2. `opencode/SETUP.md`: how to install and start the bots on this laptop.
3. `opencode/LIVE_ACCOUNT.md`: for the account owner, about real-money trading.
4. Deeper detail: `HANDOVER.md`, `docs/STATUS_AND_PLAN.md`, `docs/RESEARCH_PLAN.md`,
   `docs/PAPER_TRADING.md`.

## Rules for the agent

- **Never place, change or close a trade on a real-money account, and never switch the
  bots to real-money trading.** The bots are locked to demo accounts
  (`demo_account_only: true` in `config/risk_limits*.yaml`, enforced in
  `src/execution/demo_gateway.py`). On a real account they run "signals only": they log
  decisions and their order functions are disabled (`src/live/signals.py`). Changing that
  is the account owner's decision and must be done by the owner by hand, not by an agent.
- **Never commit `.env`** (it holds API keys) and never paste keys into chat or files.
- **Only one laptop may run the bots on a given MT5 account.** Two copies on the same
  account can double-open a trade and double-count results. The Nepal laptop's bots were
  stopped and its autostart disabled on 2026-11-16 for this hand-over.
- **Don't re-tune strategies after seeing results.** The research rules are in
  `docs/RESEARCH_PLAN.md`: rules are fixed before a test, each test runs once, and a
  failed strategy is dropped. Any change is a new trial and must be written down first.
- **Keep the ledgers append-only.** `reports/live/ledger_*.jsonl` are hash-chained;
  editing a line breaks `python -m src.live.ledger verify`.
- Run `pytest` before committing. 75 tests passed at hand-over.

## What runs

| Bot | Code | Markets | Timeframe | Magic | Demo ledger | Real-account (signals) ledger |
|---|---|---|---|---|---|---|
| Gold breakout | `src/live/paper_trader.py` | XAUUSD | 1 hour | 777101 | `ledger_XAUUSD_H1.jsonl` | `ledger_XAUUSD_H1_signals.jsonl` |
| Index dips | `src/live/dip_trader.py` | US500, US30, USTEC, DE40, AUS200, FRA40, EUSTX50 | 1 day | 777102 | `ledger_DIPS_D1.jsonl` | `ledger_DIPS_D1_signals.jsonl` |

Dashboard: `python -m src.live.dashboard`, then http://127.0.0.1:8050 (read-only).
