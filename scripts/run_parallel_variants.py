"""
Parallel variant runner — runs all experiment variants on a given spec.
Spawns one subprocess per variant (up to MAX_PARALLEL at a time).
Each variant writes its output directly to data/run-<variant>.log.
No pipe buffering — processes run at full speed.

Usage (from crypto-grid-bot directory):
    python scripts/run_parallel_variants.py full-range-2017-2024

Progress: tail the log files, e.g.:
    Get-Content data/run-a.log -Wait
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SPEC = sys.argv[1] if len(sys.argv) > 1 else "full-range-2017-2024"
MAX_PARALLEL = 4

VARIANTS = [
    ("V0",  [],               "data/run-v0.log"),
    ("A",   ["--variant-a"],  "data/run-a.log"),
    ("B",   ["--variant-b"],  "data/run-b.log"),
    ("C",   ["--variant-c"],  "data/run-c.log"),
    ("E",   ["--variant-e"],  "data/run-e.log"),
    ("F",   ["--variant-f"],  "data/run-f.log"),
    ("G",   ["--variant-g"],  "data/run-g.log"),
    ("H",   ["--variant-h"],  "data/run-h.log"),
    ("C+G", ["--variant-cg"], "data/run-cg.log"),
    ("C+H", ["--variant-ch"], "data/run-ch.log"),
]

results_dir = Path("data/backtests") / SPEC

def already_done(label: str) -> bool:
    """Check if a results.json for this variant already exists."""
    if not results_dir.exists():
        return False
    suffix = "" if label == "V0" else f"-variant-{label.lower().replace('+', '')}"
    for d in results_dir.iterdir():
        if suffix == "" and "-variant-" not in d.name:
            rj = d / "results.json"
            if rj.exists():
                return True
        elif suffix and suffix.replace("-variant-", "-variant-") in d.name:
            rj = d / "results.json"
            if rj.exists():
                return True
    return False

todo = []
for label, flags, log in VARIANTS:
    if already_done(label):
        print(f"[SKIP] {label:5} -- already complete")
    else:
        todo.append((label, flags, log))

if not todo:
    print("All variants already complete.")
else:
    print(f"\nRunning {len(todo)} variants on {SPEC} ({MAX_PARALLEL} parallel)")
    print(f"Progress logs: data/run-<variant>.log\n")
    print("-" * 60)

    queue = list(todo)
    active = {}  # label -> (proc, start, logfile)

    while queue or active:
        # start new ones up to the limit
        while queue and len(active) < MAX_PARALLEL:
            label, flags, logpath = queue.pop(0)
            log_fh = open(logpath, "w", buffering=1)
            cmd = [sys.executable, "scripts/run_nopool.py", SPEC] + flags
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
            )
            active[label] = (proc, time.time(), log_fh)
            print(f"[START] {label:5} pid={proc.pid:6}  log={logpath}", flush=True)

        time.sleep(10)

        # check for finished
        for label in list(active):
            proc, t0, log_fh = active[label]
            if proc.poll() is not None:
                elapsed = time.time() - t0
                log_fh.close()
                status = "OK" if proc.returncode == 0 else f"ERROR({proc.returncode})"
                print(f"[DONE ] {label:5} {elapsed/60:6.1f} min -- {status}", flush=True)
                del active[label]

        # show still-running
        if active:
            running = ", ".join(
                f"{lbl}({(time.time()-t0)/60:.0f}m)"
                for lbl, (_, t0, _) in active.items()
            )
            print(f"  running: {running}", flush=True)

    print("\n" + "=" * 60)
    print(f"ALL DONE -- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

# Always print results summary from whatever is on disk
print("\nRESULTS SUMMARY (gated strategy only)")
print("=" * 60)
if results_dir.exists():
    for run_dir in sorted(results_dir.iterdir()):
        rj = run_dir / "results.json"
        if not rj.exists():
            continue
        d = json.loads(rj.read_text())
        name = run_dir.name
        if "-variant-" in name:
            tag = name.split("-variant-")[1].split("-m")[0].upper()
        else:
            tag = "V0"
        print(f"\n  {tag} ({name})")
        for r in d["results"]:
            if "ungated" in r["strategy"]:
                continue
            halt = r["halted_at"][:10] if r["halted_at"] else "no"
            print(
                f"    {r['symbol']:10} {r['path_mode']:10}"
                f"  ret={r['return_pct']:+7.2f}%"
                f"  dd={r['max_drawdown_pct']:5.1f}%"
                f"  grids={r['grids_opened']:3}"
                f"  exits={r['range_exits']:3}"
                f"  halt={halt}"
            )
