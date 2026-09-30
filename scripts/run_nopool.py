"""Run a backtest spec sequentially in the main process — no ProcessPoolExecutor.

Windows Python 3.14 'spawn' pool is slow to start workers; this avoids it entirely.
Results are written to data/backtests/<spec>/<stamp>/results.json and summary.md,
same layout as the CLI.

Usage:
    python scripts/run_nopool.py long-recovery-2023-2024
    python scripts/run_nopool.py long-bull-bear-2022
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_grid_bot.backtest.__main__ import _identity, _table, result_failures
from crypto_grid_bot.backtest.dataset import load_manifest, load_spec
from crypto_grid_bot.backtest.features import FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import manifest_path, run_job
from crypto_grid_bot.backtest.replay import ENGINE_VERSION, INTEGRITY_RULES, PATH_MODES, VOLUME_DRIFT_TOLERANCE

SPEC_NAME = sys.argv[1] if len(sys.argv) > 1 else "long-recovery-2023-2024"
SPEC_PATH = Path(f"config/datasets/{SPEC_NAME}.toml")
CONFIG_PATH = Path("config/default.toml")
DATA_DIR = Path("data")
OUT_DIR = Path("data/backtests")

spec = load_spec(SPEC_PATH)
manifest = load_manifest(manifest_path(SPEC_PATH))

integrity = {
    "version": INTEGRITY_RULES,
    "volume_drift_tolerance": str(VOLUME_DRIFT_TOLERANCE),
}

total = len(spec.traded) * len(PATH_MODES) * 2
done = 0
results = []

for symbol in spec.traded:
    for mode in PATH_MODES:
        for gated in (True, False):
            done += 1
            label = f"{symbol}/{mode}/{'gated' if gated else 'ungated'}"
            print(f"[{done}/{total}] {label} ...", flush=True)
            t0 = time.time()
            r = run_job(SPEC_PATH, CONFIG_PATH, DATA_DIR, symbol, mode, gated)
            elapsed = time.time() - t0
            ret = r["return_pct"]
            grids = r["grids_opened"]
            print(f"  done in {elapsed:.1f}s  return={ret:.2f}%  grids={grids}", flush=True)
            results.append(r)

failures = result_failures(results)
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-m0.001-t0.001"
out = OUT_DIR / spec.name / stamp
out.mkdir(parents=True, exist_ok=True)

document = {
    "dataset": spec.name,
    "purpose": spec.purpose,
    "feature_version": FEATURE_VERSION,
    "engine_version": ENGINE_VERSION,
    "manifest_created_at": manifest["created_at"],
    **_identity(SPEC_PATH, CONFIG_PATH),
    "integrity_rules": integrity,
    "fees": {"maker": "0.001", "taker": "0.001"},
    "valid": not failures,
    "failures": failures,
    "results": results,
}

(out / "results.json").write_text(json.dumps(document, indent=1, default=str) + "\n")
table = _table(results)
(out / "summary.md").write_text(table + "\n")

print(f"\nOutput: {out}")
print(f"Valid: {not failures}")
print()
print(table)
