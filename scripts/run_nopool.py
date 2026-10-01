"""Run a backtest spec sequentially in the main process — no ProcessPoolExecutor.

Windows Python 3.14 'spawn' pool is slow to start workers; this avoids it entirely.
Results are written to data/backtests/<spec>/<stamp>/results.json and summary.md,
same layout as the CLI.

Usage:
    python scripts/run_nopool.py long-recovery-2023-2024
    python scripts/run_nopool.py long-bull-bear-2022
    python scripts/run_nopool.py long-bull-bear-2022 --variant-a
"""

import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_grid_bot.backtest.__main__ import _identity, _table, result_failures
from crypto_grid_bot.backtest.dataset import load_manifest, load_spec
from crypto_grid_bot.backtest.features import FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import manifest_path, run_job
from crypto_grid_bot.backtest.replay import (
    ENGINE_VERSION,
    INTEGRITY_RULES,
    PATH_MODES,
    VOLUME_DRIFT_TOLERANCE,
)
from crypto_grid_bot.simulation.runner import SimulationPolicy

VARIANT_A = "--variant-a" in sys.argv
VARIANT_B = "--variant-b" in sys.argv
VARIANT_C = "--variant-c" in sys.argv
VARIANT_E = "--variant-e" in sys.argv
VARIANT_F = "--variant-f" in sys.argv
SPEC_NAME = next((a for a in sys.argv[1:] if not a.startswith("--")), "long-recovery-2023-2024")
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
            if VARIANT_C:
                policy = SimulationPolicy(trend_switch=True, inventory_cap=Decimal("0.40"))
            elif VARIANT_A:
                policy = SimulationPolicy(trend_switch=True)
            elif VARIANT_B:
                policy = SimulationPolicy(inventory_cap=Decimal("0.40"))
            elif VARIANT_E:
                policy = SimulationPolicy(volume_exit=True)
            elif VARIANT_F:
                policy = SimulationPolicy(flow_block_entry=True)
            else:
                policy = None
            r = run_job(SPEC_PATH, CONFIG_PATH, DATA_DIR, symbol, mode, gated, policy=policy)
            elapsed = time.time() - t0
            ret = r["return_pct"]
            grids = r["grids_opened"]
            print(f"  done in {elapsed:.1f}s  return={ret:.2f}%  grids={grids}", flush=True)
            results.append(r)

failures = result_failures(results)
if VARIANT_C:
    _variant_suffix = "-variant-c"
elif VARIANT_A:
    _variant_suffix = "-variant-a"
elif VARIANT_B:
    _variant_suffix = "-variant-b"
elif VARIANT_E:
    _variant_suffix = "-variant-e"
elif VARIANT_F:
    _variant_suffix = "-variant-f"
else:
    _variant_suffix = ""
# Read fee from spec so the stamp and results.json accurately reflect what was used.
# run_job() receives fees=None and falls back to spec.fee_rate for both maker and taker.
_fee = str(spec.fee_rate)
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-m{_fee}-t{_fee}" + _variant_suffix
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
    "fees": {"maker": _fee, "taker": _fee},
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
