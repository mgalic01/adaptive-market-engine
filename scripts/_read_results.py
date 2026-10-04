import json
from pathlib import Path

results_dir = Path("data/backtests/full-range-2017-2024")
runs = sorted(results_dir.iterdir())

for run in runs:
    p = run / "results.json"
    if not p.exists():
        continue
    d = json.loads(p.read_text())
    print(f"=== {d['dataset']} | {run.name} ===")
    for r in d["results"]:
        strat = "V0" if "price-only" in r["strategy"] else "UNGATED"
        halt = r["halted_at"][:10] if r["halted_at"] else "no"
        print(
            f"  {strat:7} {r['symbol']:10} {r['path_mode']:10}"
            f"  ret={r['return_pct']:+7.2f}%"
            f"  dd={r['max_drawdown_pct']:5.1f}%"
            f"  bh={r['buy_and_hold_return_pct']:+8.1f}%"
            f"  grids={r['grids_opened']:3}"
            f"  exits={r['range_exits']:3}"
            f"  halt={halt}"
        )
    print()
