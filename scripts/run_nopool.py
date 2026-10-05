"""Run a backtest spec sequentially in the main process — no ProcessPoolExecutor.

Windows Python 3.14 'spawn' pool is slow to start workers; this avoids it entirely.
It is exactly the backtest CLI's ``run`` with ``--jobs 1``, which runs every job in
this process: the dataset is verified against its manifest, the hourly and daily
integrity cross-checks run before any replay (a pair whose own check fails is excluded
and not replayed, spec v1 §5), fees come from the spec unless a fee flag overrides
them, and results are marked valid only when every replayed run is.
Results are written to data/backtests/<spec>/<stamp>/results.json and summary.md.

Usage:
    python scripts/run_nopool.py long-recovery-2023-2024
    python scripts/run_nopool.py long-bull-bear-2022
    python scripts/run_nopool.py long-bull-bear-2022 --variant-a

Every flag after the spec name is passed to the CLI (``--variant-a``, ``--variant-b``,
``--variant-c``, ``--variant-e``, ``--variant-f``, ``--variant-g``, ``--variant-h``,
``--variant-cg``, ``--variant-ch``, ``--variant-full``, ``--structure``,
``--trend-benchmark``, ``--maker-fee`` ...).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_grid_bot.backtest.__main__ import main

DEFAULT_SPEC = "long-recovery-2023-2024"


def cli_args(argv: list[str]) -> list[str]:
    """The CLI arguments for ``run_nopool.py [spec-name] [CLI flags...]``."""
    named = bool(argv) and not argv[0].startswith("-")
    spec, flags = (argv[0], argv[1:]) if named else (DEFAULT_SPEC, argv)
    return ["run", "--spec", f"config/datasets/{spec}.toml", *flags, "--jobs", "1"]


if __name__ == "__main__":
    sys.exit(main(cli_args(sys.argv[1:])))
