"""Forward ledger: an append-only, hash-chained log of every live decision and trade.

Each line is one JSON record. A record's hash covers its content plus the previous
record's hash, so editing, deleting or reordering any past line breaks the chain and
`verify` reports where. This is what makes forward results trustworthy: they cannot be
quietly tidied up after the fact.

    python -m src.live.ledger verify reports/live/ledger_XAUUSD_H1.jsonl
    python -m src.live.ledger summary reports/live/ledger_XAUUSD_H1.jsonl
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq, self.last_hash = 0, GENESIS
        if self.path.exists():
            ok, n, msg = verify(self.path)
            if not ok:
                raise RuntimeError(f"Ledger {self.path} is corrupted ({msg}); refusing to append.")
            if n:
                last = json.loads(self.path.read_text(encoding="utf-8").splitlines()[-1])
                self.seq, self.last_hash = last["seq"], last["hash"]

    def append(self, event: str, reason: str, **data) -> dict:
        """reason: one plain-English sentence saying why this happened."""
        record = {"seq": self.seq + 1, "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": event, "reason": reason, **data, "prev_hash": self.last_hash}
        record["hash"] = _digest(record)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self.seq, self.last_hash = record["seq"], record["hash"]
        return record


def read(path) -> list:
    p = Path(path)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def verify(path):
    """Returns (ok, n_records, message)."""
    prev = GENESIS
    records = read(path)
    for i, r in enumerate(records, 1):
        if r.get("seq") != i:
            return False, len(records), f"record {i}: sequence number is {r.get('seq')}"
        if r.get("prev_hash") != prev:
            return False, len(records), f"record {i}: chain broken (a record before it was changed or removed)"
        if _digest(r) != r.get("hash"):
            return False, len(records), f"record {i}: content was edited"
        prev = r["hash"]
    return True, len(records), "ok"


def summary(path) -> dict:
    records = read(path)
    closed = [r for r in records if r["event"] == "trade_closed"]
    rs = [r["r_net"] for r in closed if r.get("r_net") is not None]
    decisions = [r for r in records if r["event"] == "decision"]
    return {
        "records": len(records),
        "bars_decided": len(decisions),
        "breakouts_seen": sum(1 for r in decisions if r.get("breakout")),
        "trades_opened": sum(1 for r in records if r["event"] == "order_filled"),
        "trades_closed": len(closed),
        "total_r": round(sum(rs), 3),
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None,
        "pnl_usd": round(sum(r.get("pnl_usd", 0) for r in closed), 2),
        "risk_blocks": sum(1 for r in records if r["event"] == "risk_blocked"),
        "errors": sum(1 for r in records if r["event"] == "error"),
    }


def main():
    p = argparse.ArgumentParser(description="Verify or summarise a forward ledger")
    p.add_argument("command", choices=["verify", "summary"])
    p.add_argument("path")
    args = p.parse_args()
    if args.command == "verify":
        ok, n, msg = verify(args.path)
        print(f"{'OK' if ok else 'BROKEN'}: {n} records, {msg}")
        raise SystemExit(0 if ok else 1)
    print(json.dumps(summary(args.path), indent=2))


if __name__ == "__main__":
    main()
