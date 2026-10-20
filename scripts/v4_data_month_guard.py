"""Refuse any file named for a month after ``end_month``: the v4-data workflow's second check.

Every job of ``.github/workflows/v4-data.yml`` runs this after its last ``v4_data.py`` step and
before its upload, on ``v4/``, the folder that holds everything the job fetched, downloaded or
made. ``v4_data.py`` already refuses such a month before any request or read; this check is
independent of it and looks only at file names.

A file is named for a month when its name (not its folder's) holds ``YYYY-MM`` with no digit on
either side, as an archive's ``<SYMBOL>-1h-2024-01.zip`` does. ``end_month`` comes from the data
config, ``config/v4_data.json`` by default. Exit 0 when no file is named for a later month; exit
1, listing the files, when one is, and also when the folder does not exist or the config is
refused.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from crypto_grid_bot.v4.data.config import load_data_config

ROOT = Path(__file__).resolve().parents[1]
_MONTH = re.compile(r"(?<![0-9])([0-9]{4}-(?:0[1-9]|1[0-2]))(?![0-9])")


def files_after_end(root: Path, end_month: str) -> tuple[int, list[Path]]:
    """How many files are under ``root``, and those named for a month after ``end_month``."""
    if not root.is_dir():
        raise ValueError(f"{root} is not a folder")
    checked, found = 0, []
    for folder, _, names in os.walk(root):
        for name in names:
            checked += 1
            # YYYY-MM strings order like the months they name.
            if any(month > end_month for month in _MONTH.findall(name)):
                found.append(Path(folder) / name)
    return checked, sorted(found)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v4_data_month_guard.py", description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "v4_data.json")
    parser.add_argument("--root", type=Path, required=True, help="the folder to check")
    args = parser.parse_args(argv)
    try:
        end_month = load_data_config(args.config).end_month
        checked, found = files_after_end(args.root, end_month)
    except (ValueError, OSError) as exc:
        print(f"::error::The month guard could not check {args.root}: {exc}", file=sys.stderr)
        return 1
    for path in found:
        print(path)
    if found:
        print(f"::error::{len(found)} files are named for a month after end_month {end_month}.")
        return 1
    print(f"{checked} files checked; none is named for a month after end_month {end_month}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
