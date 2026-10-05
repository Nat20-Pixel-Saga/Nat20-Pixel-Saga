#!/usr/bin/env python3
"""Cost projection from a measured episode ledger (episodes/<id>/cost.json).

Re-prices the measured token counts for the situations the show will meet:
a premiere/finale (Opus writes), an ordinary day (Sonnet writes and reuses the
planner's cache), a bad day (one rewrite), and the same without the Batch API
or caching. Then scales to a month of weekdays and to the whole series.

    python scripts/cost_report.py C01-E001
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pqc.pipeline.claude import BATCH_DISCOUNT, MODELS, PRICES  # noqa: E402

EPISODES_PER_MONTH = 22
SERIES_EPISODES = 474          # bible 07: ten campaigns + nine interludes
CAMPAIGNS = 10 + 9             # the campaign planner also plans each interlude
# Campaign planner (Fable 5.1, once per campaign): whole bible + arc in, beat file out.
CAMPAIGN_CALL = {"model": MODELS["fable"], "input": 45_000, "output": 30_000}


def price(model, inp=0, out=0, cw=0, cr=0, batch=True):
    p = PRICES[model]
    c = (inp * p["in"] + out * p["out"] + cw * p["cache_write"] + cr * p["cache_read"]) / 1e6
    return c * (BATCH_DISCOUNT if batch else 1.0)


def scenario(steps: dict, writer: str, share_cache: bool, retries: int, batch: bool, cache: bool) -> float:
    total = 0.0
    for name, s in steps.items():
        model = MODELS[writer] if name == "script" else s["model"]
        prefix = s["cache_write"] + s["cache_read"]
        fresh = s["input"]
        out = s["output"]
        calls = 1 + (retries if name in ("script", "continuity") else 0)
        for k in range(calls):
            if not cache:
                total += price(model, fresh + prefix, out, batch=batch)
                continue
            # Sonnet planner and Sonnet writer share one prefix; retries reuse their own.
            warm = k > 0 or (name == "script" and share_cache and model == steps["plan"]["model"]) or \
                (name == "packaging")
            total += price(model, fresh, out, cw=0 if warm else prefix, cr=prefix if warm else 0, batch=batch)
    return total


def main() -> int:
    eid = sys.argv[1] if len(sys.argv) > 1 else "C01-E001"
    cost = json.loads((ROOT / "episodes" / eid / "cost.json").read_text())
    steps = cost["steps"]
    rows = [
        ("Premiere / finale (Opus 5.5 writes), measured", scenario(steps, "opus", False, 0, True, True)),
        ("Ordinary episode (Sonnet 5.5 writes, shared cache)", scenario(steps, "sonnet", True, 0, True, True)),
        ("Ordinary episode with one rewrite", scenario(steps, "sonnet", True, 1, True, True)),
        ("Ordinary episode, no Batch API", scenario(steps, "sonnet", True, 0, False, True)),
        ("Ordinary episode, no Batch API, no caching", scenario(steps, "sonnet", False, 0, False, False)),
    ]
    camp = price(CAMPAIGN_CALL["model"], CAMPAIGN_CALL["input"], CAMPAIGN_CALL["output"], batch=True)
    ordinary, rewrite, premiere = rows[1][1], rows[2][1], rows[0][1]
    # Mix: 1 in 20 episodes is a premiere/finale/milestone; 1 in 5 needs a rewrite.
    mix = 0.05 * premiere + 0.95 * (0.8 * ordinary + 0.2 * rewrite)
    lines = [f"# Claude API cost per episode (from the {eid} ledger)", "",
             f"Measured tokens ({'estimated offline' if cost.get('estimated') else 'live'}):", "",
             "| Step | Model | Input | Cache write | Cache read | Output |", "| --- | --- | --- | --- | --- | --- |"]
    for name, s in steps.items():
        lines.append(f"| {name} | {s['model']} | {s['input']:,} | {s['cache_write']:,} | {s['cache_read']:,} | "
                     f"{s['output']:,} |")
    lines += ["", "| Scenario | USD per episode |", "| --- | --- |"]
    lines += [f"| {k} | ${v:.3f} |" for k, v in rows]
    lines += ["", "| Projection | USD |", "| --- | --- |",
              f"| Blended episode (5% premieres, 20% rewrites) | ${mix:.3f} |",
              f"| Month (22 weekday episodes) | ${mix * EPISODES_PER_MONTH:.2f} |",
              f"| Campaign planner, per campaign (Fable 5.1, batch) | ${camp:.2f} |",
              f"| Whole series ({SERIES_EPISODES} episodes + {CAMPAIGNS} campaign plans) | "
              f"${mix * SERIES_EPISODES + camp * CAMPAIGNS:.2f} |", "",
              "Prices: USD per million tokens from `pqc/pipeline/claude.py` (Batch API -50%). Offline token counts "
              "are estimated at 3.2 characters per token; a live run records the API's own usage figures."]
    text = "\n".join(lines)
    (ROOT / "episodes" / eid / "cost_report.md").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
