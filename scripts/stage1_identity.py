"""Stage-1 identity check: a re-run of stage 1 must leave every results.json unchanged.

    python scripts/stage1_identity.py <stage-1 results dir> <re-run results dir> [--expect N]

Spec v1 section 6, "Two stages" (owner decision 2026-10-05; decision 18 in the test-plan
record): the data-handling code that lands between the stages must leave every stage-1
result identical. The re-run is stage 1's 24 workflow runs (2 datasets x 12 inputs) on the
code that merges the long-window data handling; this script compares its ``results.json``
files with stage 1's downloads. It reads JSON only, and needs neither the engine nor the
data. ``json.loads`` keeps the last of a key repeated within one object, so an earlier
duplicate in a file is never seen.

**The two sides must be two places.** Both arguments are resolved first (``..`` and symbolic
links followed). The inventory fails when they are the same directory, or when either lies inside
the other: a re-run kept under the stage-1 directory, or the reverse, is found from both sides and
would be compared with itself. It fails too when one ``results.json`` is reached from both sides
whatever the directories, as through a symbolic link to a stage-1 file. A hard link is a second
name for the same data, not a path that resolves to it, and is not detected.

**Inventory next.** Each ``results.json`` under either directory (found at any depth) is
keyed by ``(dataset, policy, structure)``:

* ``dataset`` is the file's ``dataset``;
* ``policy`` is its ``policy`` identity as compact JSON, or ``V0`` when the file has no
  ``policy`` key (the CLI writes one only for a variant or structure run);
* ``structure`` is whether any row's ``strategy`` label names the V2 structure features.

Both intrabar paths and both gate settings are rows of one file, and are compared inside
it, so the path is not part of the key. The two key sets must be equal, with no two files
on one key on either side, and every file must be readable as a backtest ``results.json``.
Otherwise the check fails before it compares anything, naming each missing, extra or
duplicate key and each unreadable file, so a re-run that lost a download cannot pass on
the files that remain. An empty side fails too. The script does not assume a count unless
told: it prints the count, and ``--expect N`` fails the inventory when either side holds
other than N files, naming each count. Stage 1 had 24 (``--expect 24``); without the
flag, a download set and a re-run that lost the same file alike would still match.

**Then each pair.** The two documents must be equal once the top-level ``code_commit`` and
``code_sha256`` are set aside: every value, with its JSON type (``1`` is not ``1.0``), and
every field and list item, in list order. The order of a document's keys is not compared.
Nothing else is exempt: not ``spec_sha256``, ``manifest_sha256`` or ``config_sha256``, and
not a nested field of the same name. The six fields the long-window plan adds (spec v1
section 5 rules 1, 3 and 8; ``MASK_FIELDS``) fail wherever they appear, at any depth and
on either side, whatever their value: stage 1 predates them, and the plan has a run write
each one only when it is non-empty or non-zero (Plan 2, Global Constraints), so a clean
stage-1 re-run has none. Spec section 6 leaves them out of the comparison as long as they
are empty or zero; this check does not leave them out, and fails on any, as the plan's
"no new mask field" says.

Prints ``<key> IDENTICAL|DIFFERENT`` for each pair, with what differs indented beneath a
different pair (at most ``MAX_SHOWN`` lines and a count of the rest), and then ``ALL
IDENTICAL`` or ``SOME DIFFER``. An inventory failure prints ``INVENTORY DIFFERS`` and no
pair, and each key or file it names goes to stderr. Exits 0 only on ``ALL IDENTICAL``.

**What it proves.** Identical files prove that the engine's output is unchanged. They
cannot show which reader ran: a repair that matched exactly would change no bar and write
no key, because ``Kline`` does not keep the close timestamp the repair rewrites. The
companion check is ``python -m crypto_grid_bot.backtest mask-report`` on ``practice-2022``
and ``verify-2024h1``, which must print ``None`` for every symbol's mask and zero repaired,
dropped and masked counts. Together they show that every stage-1 symbol took the strict
path and that the repairing reader finds nothing to repair in stage 1's archives.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, NamedTuple

# The provenance fields: the only top-level fields that may differ.
FINGERPRINTS = frozenset({"code_commit", "code_sha256"})
# The mask-report fields of spec v1 section 5 rule 1 and the plan's rows and cross-checks.
MASK_FIELDS = frozenset(
    {
        "masked_hours",
        "days_skipped_for_masks",
        "fills_after_masked_span",
        "comparison_mask",
        "daily_days_skipped_for_masks",
        "tick_limit_quotes",
    }
)
# A structure run's gated rows are labelled ``gated grid (<version>+structure-v2)``.
STRUCTURE_MARK = "+structure"
MAX_SHOWN = 10
STAGE1, RERUN = "stage 1", "the re-run"


class Key(NamedTuple):
    dataset: str
    policy: str
    structure: bool

    def __str__(self) -> str:
        return f"{self.dataset} | {self.policy} | structure={self.structure}"


def key_of(document: Any) -> Key:
    """The key of a parsed results.json; ValueError when it is not one."""
    try:
        dataset = document["dataset"]
        rows = document["results"]
        policy = (
            json.dumps(document["policy"], sort_keys=True, separators=(",", ":"))
            if "policy" in document
            else "V0"
        )
        labels = [row["strategy"] for row in rows]
    except (KeyError, TypeError) as error:
        raise ValueError(f"not a results.json of the backtest CLI ({error!r})") from None
    for label in labels:
        # ``in`` also answers for a list or a dict, so a label must be text.
        if not isinstance(label, str):
            raise ValueError(f"not a results.json of the backtest CLI (strategy {label!r})")
    structure = any(STRUCTURE_MARK in label for label in labels)
    if not isinstance(dataset, str):
        raise ValueError(f"not a results.json of the backtest CLI (dataset {dataset!r})")
    return Key(dataset, policy, structure)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def scan(root: Path, side: str) -> tuple[dict[Key, list[Path]], list[str]]:
    """Every results.json under ``root`` by key, and what stopped the scan from reading a
    side as an inventory: no such directory, no file, or a file that is not a results.json."""
    if not root.is_dir():
        return {}, [f"{side}: {root} is not a directory"]
    found: dict[Key, list[Path]] = {}
    problems: list[str] = []
    for path in sorted(root.rglob("results.json")):
        if not path.is_file():
            continue
        try:
            found.setdefault(key_of(load(path)), []).append(path)
        except (OSError, ValueError) as error:  # a JSONDecodeError is a ValueError
            problems.append(f"{side}: {path}: {error}")
    if not found and not problems:
        problems.append(f"{side}: no results.json under {root}")
    return found, problems


def overlap_problems(stage1: Path, rerun: Path) -> list[str]:
    """Why the two arguments are not two places: the same directory, or one inside the other,
    compared after ``resolve`` so ``..`` and symbolic links cannot hide it."""
    first, second = stage1.resolve(), rerun.resolve()
    if first == second:
        return [f"stage 1 and the re-run are the same directory: {first}"]
    if second.is_relative_to(first):
        return [f"the re-run directory {second} is inside stage 1's directory {first}"]
    if first.is_relative_to(second):
        return [f"stage 1's directory {first} is inside the re-run directory {second}"]
    return []


def shared_files(stage1: dict[Key, list[Path]], rerun: dict[Key, list[Path]]) -> list[Path]:
    """Each results.json that both sides reach, as its resolved path: a file compared with
    itself proves nothing."""
    first = {path.resolve() for paths in stage1.values() for path in paths}
    second = {path.resolve() for paths in rerun.values() for path in paths}
    return sorted(first & second)


def inventory_problems(
    stage1: dict[Key, list[Path]], rerun: dict[Key, list[Path]], expect: int | None = None
) -> list[str]:
    """Duplicate keys on either side, the keys on one side only, and with ``expect`` a
    side that does not hold that many files."""
    problems = [
        f"two files with one key in {side}: {key}: {', '.join(map(str, paths))}"
        for side, found in ((STAGE1, stage1), (RERUN, rerun))
        for key, paths in sorted(found.items())
        if len(paths) > 1
    ]
    problems += [
        f"missing from the re-run: {key} (stage 1: {stage1[key][0]})"
        for key in sorted(stage1.keys() - rerun.keys())
    ]
    problems += [
        f"extra in the re-run: {key} ({rerun[key][0]})"
        for key in sorted(rerun.keys() - stage1.keys())
    ]
    if expect is not None:
        problems += [
            f"expected {expect} results.json files in {side}, found {len(found)}"
            for side, found in ((STAGE1, stage1), (RERUN, rerun))
            if len(found) != expect
        ]
    return problems


def field(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def mask_fields(value: Any, path: str = "") -> Iterator[str]:
    """The path of every mask field in ``value``, at any depth."""
    if isinstance(value, dict):
        for name, item in value.items():
            where = field(path, name)
            if name in MASK_FIELDS:
                yield where
            else:
                yield from mask_fields(item, where)
    elif isinstance(value, list):
        for number, item in enumerate(value):
            yield from mask_fields(item, f"{path}[{number}]")


def shown(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "..."


def differences(old: Any, new: Any, path: str = "") -> Iterator[str]:
    """Where ``old`` and ``new`` differ, one line per difference, in document order. Mask
    fields are left to ``mask_fields``. A scalar is equal only to a scalar with the same
    JSON text, so ``1`` differs from ``1.0`` and from ``true``."""
    if isinstance(old, dict) and isinstance(new, dict):
        for name in old:
            if name in MASK_FIELDS:
                continue
            if name in new:
                yield from differences(old[name], new[name], field(path, name))
            else:
                yield f"{field(path, name)}: only in stage 1"
        for name in new:
            if name not in old and name not in MASK_FIELDS:
                yield f"{field(path, name)}: only in the re-run"
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            yield f"{path}: {len(old)} items in stage 1, {len(new)} in the re-run"
        for number, (a, b) in enumerate(zip(old, new, strict=False)):
            yield from differences(a, b, f"{path}[{number}]")
    elif json.dumps(old) != json.dumps(new):
        yield f"{path}: {shown(old)} in stage 1, {shown(new)} in the re-run"


def compare(old_path: Path, new_path: Path) -> list[str]:
    """What stops a pair from being identical; empty when it is."""
    old, new = load(old_path), load(new_path)
    problems = [f"mask field {where} in stage 1, which predates them" for where in mask_fields(old)]
    problems += [f"new mask field {where}" for where in mask_fields(new)]
    problems += differences(
        {k: v for k, v in old.items() if k not in FINGERPRINTS},
        {k: v for k, v in new.items() if k not in FINGERPRINTS},
    )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage1", type=Path, help="directory of stage 1's results.json files")
    parser.add_argument("rerun", type=Path, help="directory of the re-run's results.json files")
    parser.add_argument(
        "--expect",
        type=int,
        metavar="N",
        help="fail the inventory unless each side holds N results.json files (stage 1: 24)",
    )
    args = parser.parse_args(argv)
    if args.expect is not None and args.expect < 1:
        parser.error("--expect must be at least 1")
    problems = overlap_problems(args.stage1, args.rerun)
    stage1: dict[Key, list[Path]] = {}
    rerun: dict[Key, list[Path]] = {}
    if not problems:  # nested or equal directories: scanning them would only repeat the files
        stage1, problems = scan(args.stage1, STAGE1)
        rerun, rerun_problems = scan(args.rerun, RERUN)
        problems += rerun_problems
        if stage1 and rerun:  # an unreadable side is already explained; its keys are not "missing"
            problems += inventory_problems(stage1, rerun, args.expect)
            problems += [
                f"the same file is reached from both sides: {path}"
                for path in shared_files(stage1, rerun)
            ]
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr, flush=True)
        print("INVENTORY DIFFERS")
        return 1
    print(f"{len(stage1)} results.json files on each side, one per key", flush=True)
    same = True
    for key in sorted(stage1):
        found = compare(stage1[key][0], rerun[key][0])
        same &= not found
        print(f"{key} {'DIFFERENT' if found else 'IDENTICAL'}", flush=True)
        for line in found[:MAX_SHOWN]:
            print(f"  {line}", flush=True)
        if len(found) > MAX_SHOWN:
            print(f"  and {len(found) - MAX_SHOWN} more", flush=True)
    print("ALL IDENTICAL" if same else "SOME DIFFER")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
