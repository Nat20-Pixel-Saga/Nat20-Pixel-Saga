#!/usr/bin/env python3
"""The overnight production queue (production/queue.json).

    python scripts/production.py status              # table of tasks
    python scripts/production.py lock SESSION        # take the lock (exit 1 if another session holds a fresh one)
    python scripts/production.py heartbeat SESSION   # refresh the lock's timestamp
    python scripts/production.py unlock SESSION
    python scripts/production.py next                # the next task whose prerequisites are done (JSON), or exit 2
    python scripts/production.py start ID
    python scripts/production.py done ID [NOTE]
    python scripts/production.py block ID REASON
    python scripts/production.py log TEXT            # append a line to production/LOG.md

A lock older than LOCK_MINUTES is stale: its session ran out of usage or
died, and the next session may take over and resume the in-progress task.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "production" / "queue.json"
LOG = ROOT / "production" / "LOG.md"
LOCK_MINUTES = 90


def now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict:
    return json.loads(QUEUE.read_text())


def save(q: dict) -> None:
    QUEUE.write_text(json.dumps(q, indent=1, ensure_ascii=False) + "\n")


def find(q: dict, tid: str) -> dict:
    for t in q["tasks"]:
        if t["id"] == tid:
            return t
    raise SystemExit(f"no task {tid!r}")


def ready(q: dict) -> list[dict]:
    done = {t["id"] for t in q["tasks"] if t["status"] == "done"}
    out = []
    for t in q["tasks"]:
        if t["status"] in ("todo", "in_progress") and all(a in done for a in t.get("after", [])):
            out.append(t)
    # Resume what was in progress first, then take tasks in queue order.
    return sorted(out, key=lambda t: (t["status"] != "in_progress", q["tasks"].index(t)))


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    q = load()
    if cmd == "status":
        for t in q["tasks"]:
            extra = t.get("note") or t.get("reason") or ""
            print(f"{t['status']:<12} {t['id']:<32} {extra[:80]}")
        lock = q.get("lock")
        print(f"lock: {lock}")
        return 0
    if cmd in ("lock", "heartbeat"):
        who = argv[1]
        lock = q.get("lock")
        if lock and lock["session"] != who:
            age = now() - datetime.fromisoformat(lock["at"])
            if age < timedelta(minutes=LOCK_MINUTES):
                print(f"locked by {lock['session']} {int(age.total_seconds() // 60)} min ago")
                return 1
            print(f"taking over a stale lock from {lock['session']}")
        q["lock"] = {"session": who, "at": now().isoformat(timespec="seconds")}
        save(q)
        return 0
    if cmd == "unlock":
        if q.get("lock") and q["lock"]["session"] == argv[1]:
            q["lock"] = None
            save(q)
        return 0
    if cmd == "next":
        r = ready(q)
        if not r:
            remaining = [t["id"] for t in q["tasks"] if t["status"] not in ("done",)]
            print(json.dumps({"next": None, "remaining": remaining}))
            return 2
        print(json.dumps(r[0], indent=1, ensure_ascii=False))
        return 0
    if cmd == "start":
        t = find(q, argv[1])
        t["status"] = "in_progress"
        t.setdefault("started_at", now().isoformat(timespec="seconds"))
        save(q)
        return 0
    if cmd == "done":
        t = find(q, argv[1])
        t["status"] = "done"
        t["done_at"] = now().isoformat(timespec="seconds")
        if len(argv) > 2:
            t["note"] = " ".join(argv[2:])
        save(q)
        return 0
    if cmd == "block":
        t = find(q, argv[1])
        t["status"] = "blocked"
        t["reason"] = " ".join(argv[2:])
        save(q)
        return 0
    if cmd == "log":
        LOG.parent.mkdir(exist_ok=True)
        if not LOG.exists():
            LOG.write_text("# Production log\n\n")
        with LOG.open("a") as f:
            f.write(f"- {now().strftime('%Y-%m-%d %H:%M')} UTC - {' '.join(argv[1:])}\n")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
