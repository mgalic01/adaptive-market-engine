"""The registered run's data guard: the v4-run workflow's check that the data it opens is the
registered data, and nothing else.

Owner decision v4-d03: no market data from 2025-01 onward is executed before V4's registered run.
``scripts/v4_cells_guard.py`` enforces that for the diagnostic workflow (``end_month`` at most
2024-12, and ``--config`` pins the pre-2025 config). The registered run is exactly where 2025+
data is opened, so this guard has no month bound. It opens only the registered data instead: the
data whose pins equal the run manifest's (``config/v4_run_manifest.json``, Ruling G5). The
rehearsal and timing modes run on synthetic worlds only, and the guard's synthetic mode refuses
anything else. ``v4_cells_guard.py`` itself is unchanged.

``--data D --manifest M [--repo R]`` reads ``D/data.json`` (format ``v4-data/1``) and the run
manifest ``M`` (``v4_registration.read_manifest``), and exits 0 only if

1. ``data.json``'s ``config_sha256``, ``end_month`` and the pins of its daily pack
   (``packs.daily.sha256``) and hourly index (``packs.hourly_index.sha256``) equal the manifest's
   ``config_sha256``, ``end_month``, ``daily_sha256`` and ``index_sha256``; and
2. the manifest's ``config_path``, under ``R`` (the current folder unless given), hashes to
   ``config_sha256``: the data was made from the very config file the run is registered with.

The packs themselves are verified against these pins when ``Market.load`` reads them, so the
check covers every coin pack too. Output on success: ``v4_run_guard: data end_month <month>,
config_sha256 <pin>: accepted (registered pins)``.

``--data D --synthetic`` exits 0 only if ``data.json``'s ``config_sha256`` is
``crypto_grid_bot.v4.synthetic.CONFIG_SHA256``, the config pin of the rehearsal and timing
worlds, which no real config file hashes to. A synthetic world may reach any month: it holds no
market data. (``scripts/v4_rehearsal.py``'s ``read_world`` does not itself require that pin, so
this is where a world's synthetic-ness is enforced.) Output: the same line, ending
``accepted (synthetic world)``.

``--data-run ID --commit C`` instead checks the data run itself, before anything of it is
downloaded (the ``plan`` job pipes ``gh api repos/<repository>/actions/runs/<ID>`` into it): the
run's JSON on standard input is checked by ``v4_cells_guard.check_data_run`` with the full
config's run name, ``FULL_DATA_RUN_TITLE``. It must be a successful run of the v4-data workflow
named ``v4-data full config/v4_data.json`` whose ``head_sha`` is ``C``, the commit this run
checked out (``github.sha``): the packs were made by the very code that opens them. The
diagnostic run's pre-2025 data run, a discover run, a failed or unfinished run and a run of
another commit are refused. ``--commit`` is needed with ``--data-run`` and refused with
``--data``; ``--manifest``, ``--synthetic`` and ``--repo`` are refused with ``--data-run``.

Exit 1 writes nothing and prints one line on standard error, ``::error::v4_run_guard: <what was
wrong>: refused``. The line names the pin or the file that is wrong, never a value of
``data.json`` or of the run's JSON beyond a validated month or pin, and never a price. A
``data.json`` that is missing, is not ASCII JSON with no duplicate key, is not an object of that
format, or lacks a well-formed ``end_month``, ``config_sha256`` or pack pin (a SHA-256, a pin and
not market data) is refused too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from v4_cells_guard import (
    DATA_FILE,
    DATA_FORMAT,
    MAX_RUN_BYTES,
    _unique_keys,
    check_data_run,
)
from v4_registration import RunManifest, read_manifest

from crypto_grid_bot.v4.synthetic import CONFIG_SHA256

# The registered run's data run: the v4-data workflow's run name (``run-name: v4-data <stage>
# <config>``) for the full stage with the full config, whose packs run to the data's end month.
FULL_DATA_RUN_TITLE = "v4-data full config/v4_data.json"

_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_RUN_ID = re.compile(r"[1-9][0-9]{0,19}")
_PIN = re.compile(r"[0-9a-f]{64}")


def _refuse(reason: str) -> int:
    """One line of standard error, the exit status 1: whatever whitespace ``reason`` holds is
    made single spaces, so no message can start a second line."""
    print(
        f"::error::v4_run_guard: {' '.join(reason.split())}: refused", file=sys.stderr, flush=True
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_run_guard.py", description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--data", type=Path, help="the data directory")
    target.add_argument(
        "--data-run", help="the data run's id; its JSON from the GitHub API on standard input"
    )
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument(
        "--manifest",
        type=Path,
        help="with --data: the run manifest whose pins data.json's must equal",
    )
    kind.add_argument(
        "--synthetic",
        action="store_true",
        help="with --data: accept only a synthetic world (its config_sha256 is CONFIG_SHA256)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        help="with --manifest: the checkout holding the manifest's config file (default: .)",
    )
    parser.add_argument(
        "--commit",
        help="with --data-run: the commit this run checked out, which the data run's must be",
    )
    return parser


def _data_pins(data_dir: Path) -> dict[str, str]:
    """``data.json``'s four pins: ``config_sha256``, ``end_month``, ``daily_sha256`` and
    ``index_sha256``, each validated (a SHA-256 of 64 lowercase hex digits, a month ``YYYY-MM``).
    Anything else is a ``ValueError`` naming what is wrong and no value of the file."""
    try:
        text = (data_dir / DATA_FILE).read_bytes().decode("ascii")
        document = json.loads(text, object_pairs_hook=_unique_keys)
    except (OSError, ValueError):  # UnicodeDecodeError, JSONDecodeError: ValueErrors
        raise ValueError(
            f"{DATA_FILE} is missing, unreadable or not JSON with unique keys"
        ) from None
    if not isinstance(document, dict):
        raise ValueError(f"{DATA_FILE} is not a JSON object")
    if document.get("format") != DATA_FORMAT:
        raise ValueError(f"{DATA_FILE} is not of format {DATA_FORMAT}")
    end_month = document.get("end_month")
    if not isinstance(end_month, str) or _MONTH.fullmatch(end_month) is None:
        raise ValueError(f"{DATA_FILE} has no end_month of the form YYYY-MM")
    config = _pin(document.get("config_sha256"), f"{DATA_FILE} has no config_sha256")
    packs = document.get("packs")
    if not isinstance(packs, dict):
        raise ValueError(f"{DATA_FILE} has no packs object")
    daily = _pack_pin(packs, "daily")
    index = _pack_pin(packs, "hourly_index")
    return {
        "config_sha256": config,
        "end_month": end_month,
        "daily_sha256": daily,
        "index_sha256": index,
    }


def _pin(value: object, what: str) -> str:
    if not isinstance(value, str) or _PIN.fullmatch(value) is None:
        raise ValueError(f"{what} of 64 lowercase hex digits")
    return value


def _pack_pin(packs: dict[str, Any], name: str) -> str:
    record = packs.get(name)
    if not isinstance(record, dict):
        raise ValueError(f"{DATA_FILE} has no {name} pack record")
    return _pin(record.get("sha256"), f"{DATA_FILE}'s {name} pack has no sha256")


def check_registered_data(data_dir: Path, manifest: RunManifest, repo: Path) -> dict[str, str]:
    """Accept only the registered data: ``data_dir``'s ``data.json`` pins (``config_sha256``,
    ``end_month``, ``daily_sha256`` and ``index_sha256``) must equal ``manifest``'s ``data``, and
    the manifest's ``config_path`` under ``repo`` must hash to ``config_sha256``. Returns the
    four pins. Anything else is a ``ValueError`` naming the pin or the file, never a value."""
    pins = _data_pins(data_dir)
    for key, found in pins.items():
        if found != manifest.data[key]:
            raise ValueError(f"{DATA_FILE}'s {key} is not the run manifest's")
    config_path = manifest.data["config_path"]
    shown = f"{config_path!r:.80}"
    try:
        digest = hashlib.sha256((repo / config_path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(
            f"the manifest's config file {shown} cannot be read ({type(exc).__name__})"
        ) from None
    if digest != pins["config_sha256"]:
        raise ValueError(f"the manifest's config file {shown} does not hash to config_sha256")
    return pins


def check_synthetic_data(data_dir: Path) -> dict[str, str]:
    """Accept only a synthetic world: ``data.json``'s ``config_sha256`` must be
    ``CONFIG_SHA256``. Returns the four pins. Anything else is a ``ValueError`` naming what is
    wrong, never a value."""
    pins = _data_pins(data_dir)
    if pins["config_sha256"] != CONFIG_SHA256:
        raise ValueError(f"{DATA_FILE}'s config_sha256 is not the synthetic worlds' pin")
    return pins


def _reason(exc: BaseException) -> str:
    """What a refusal says of ``exc``: the message of a ``ValueError`` (the checks above name no
    value), only the type of anything else."""
    return str(exc) if type(exc) is ValueError else type(exc).__name__


def _read_manifest(path: Path) -> RunManifest:
    """The run manifest at ``path``; a ``ValueError`` if it cannot be read or does not read."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"the run manifest cannot be read ({type(exc).__name__})") from None
    return read_manifest(raw)


def _check_data(args: argparse.Namespace) -> int:
    """``--data`` with ``--manifest`` or ``--synthetic``."""
    try:
        if args.synthetic:
            pins = check_synthetic_data(args.data)
            verdict = "synthetic world"
        else:
            manifest = _read_manifest(args.manifest)
            pins = check_registered_data(args.data, manifest, args.repo or Path("."))
            verdict = "registered pins"
    except ValueError as exc:
        return _refuse(_reason(exc))
    print(
        f"v4_run_guard: data end_month {pins['end_month']}, "
        f"config_sha256 {pins['config_sha256']}: accepted ({verdict})",
        flush=True,
    )
    return 0


def _check_run(run_id: str, head_sha: str) -> int:
    """``--data-run``: the run's JSON from standard input, through ``check_data_run`` with the
    full config's run name."""
    shown = run_id if _RUN_ID.fullmatch(run_id) else "(not a run id)"
    try:
        raw = sys.stdin.buffer.read(MAX_RUN_BYTES + 1)
        if len(raw) > MAX_RUN_BYTES:
            raise ValueError(f"the API's answer is larger than {MAX_RUN_BYTES} bytes")
        # UTF-8, not ASCII: the answer holds free text (the head commit's message, say).
        run = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
        check_data_run(run, run_id, head_sha, title=FULL_DATA_RUN_TITLE)
    except (OSError, ValueError) as exc:  # a decoding or JSON error is a ValueError
        return _refuse(f"data run {shown}: {_reason(exc)}")
    print(
        f"v4_run_guard: data run {run_id}: a successful {FULL_DATA_RUN_TITLE!r} run of this "
        "commit: accepted",
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.data_run is not None:
        if args.manifest is not None or args.synthetic or args.repo is not None:
            return _refuse("--manifest, --synthetic and --repo go with --data, not with --data-run")
        if args.commit is None:
            return _refuse("--data-run needs --commit, the commit this run checked out")
        return _check_run(args.data_run, args.commit)
    if args.commit is not None:
        return _refuse("--commit goes with --data-run, not with --data")
    if args.manifest is None and not args.synthetic:
        return _refuse("--data needs --manifest (the registered run) or --synthetic")
    if args.synthetic and args.repo is not None:
        return _refuse("--repo goes with --manifest, not with --synthetic")
    return _check_data(args)


if __name__ == "__main__":
    raise SystemExit(main())
