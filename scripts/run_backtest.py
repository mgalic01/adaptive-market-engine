"""Thin wrapper so ProcessPoolExecutor child workers can import run_job by module name.

Usage:
    python scripts/run_backtest.py --spec config/datasets/long-recovery-2023-2024.toml \
        --config config/default.toml --data-dir data --out data/backtests --jobs 4

Why this exists: on Windows, ProcessPoolExecutor uses the 'spawn' start method, which
means each worker re-imports the module containing run_job. When the CLI is invoked
via 'python -c "..."', that module path is __main__ and child workers cannot find it.
Invoking via 'python scripts/run_backtest.py' keeps the script as __main__ while
run_job lives in crypto_grid_bot.backtest.jobs — a proper importable path — so workers
find it correctly and the pool runs end-to-end.
"""

import sys
from pathlib import Path

# Make sure the package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_grid_bot.backtest.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
