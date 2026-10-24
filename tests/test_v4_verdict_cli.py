"""V4 step 4b, task 4: the resumable verdict step (``scripts/v4_verdict.py``) and the run summary
page (``v4.verdict.report``).

Every test runs the real CLI over hand-built summaries (``v4_verdict_fixtures.full_set``: 48
cells of 50 hours, valid by task 2's checks, no replay), so the tests stay fast and read only
synthetic data. The base set passes: ``v4_main`` rises without a drawdown and beats both
comparison arms on every measure. Each test changes one thing: a stopped or refused cell, a
missing one, a re-run, a dispatch, an interruption, a changed input.

The module's tests follow the brief: the bytes of the outputs, resuming (an interruption in each
of the three phases, and a changed input), the two-cells bound, the exclusive outputs, the output
rule (counts only), the dispatch reasons, the rehearsal banner and the v3 adapter's disclosure.
Then the rest of the ledger's rulings (a refused liquidated ``v4_main`` is incomplete, not fail;
the marks' digest; the dispatch file's shape; the progress file's shape), the record forms the
progress file and ``verdict.json`` use, and the page's escaping.

The network is blocked for every test (the autouse fixture and, for the module's shared run, the
module-scoped one).
"""

from __future__ import annotations

import dataclasses
import gc
import json
import re
import shutil
import socket
import sys
import weakref
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import v4_verdict_fixtures
from v4_verdict_fixtures import (
    HOURS,
    START_MS,
    edit_summary,
    expected_for,
    full_set,
    marks_for,
    standard_cell,
    write_expected,
    write_summary,
)

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine import v3_as_built
from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES, all_cells
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    ENGINE_ERROR,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
)
from crypto_grid_bot.v4.engine.v3_as_built import V3_CAPITAL_ADAPTER
from crypto_grid_bot.v4.verdict import inputs, rule
from crypto_grid_bot.v4.verdict.inputs import read_cell
from crypto_grid_bot.v4.verdict.report import (
    DISPATCH_FORMAT,
    PROGRESS_FORMAT,
    VERDICT_FORMAT,
    check_from_record,
    check_record,
    measure_from_record,
    measure_record,
    read_dispatch_reasons,
    render_verdict_page,
    rerun_cells,
    verdict_document,
)
from crypto_grid_bot.v4.verdict.rule import (
    INFINITY,
    Check,
    PathMeasure,
    decide,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_verdict  # noqa: E402

D = Decimal
SYNTHETIC = "Synthetic data: this is a test of the pipeline, not a result"
NOTE = (
    "Only the third era, 2025-01-01 to the end, was unseen when V4 was designed, so a pass means "
    "promising, not proven."
)
HEADINGS = (
    "## The verdict",
    "## The four conditions",
    "## A note from the spec",
    "## The comparison table",
    "## The eras",
    "## Variants and neighbours at 1x",
    "## Disclosures",
    "## Missing, refused and re-run cells, and other dispatches",
    "## The analysis artifact",
)
NON_V3 = [name for name, spec in ARMS.items() if spec.family != "v3"]
CELLS = 48
CHECKS = 8
PAIRS = len(NON_V3) * len(CAPITALS) * len(COST_MULTIPLES) * 2
STEPS = CELLS + CHECKS + PAIRS
MAIN = "v4_main-1000-1x"
HOLD = "hold_universe-1000-1x"
REPORTED = "v4_vol25-10000-2x"  # a cell no condition reads


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


_SOCKET_CALLS = [
    (socket, "getaddrinfo"),
    (socket, "create_connection"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
]


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in _SOCKET_CALLS:
        monkeypatch.setattr(owner, name, _refuse)


@pytest.fixture(scope="module", autouse=True)
def short_v3_period():
    """The fixtures' cells have 50 hours and V3's period is three and a half years, so with the
    real period the check of condition 2 would list about 30,000 skipped hours (and the progress
    file and the page would carry them in every one of 144 saves). This module runs with a V3
    period of the cells' own 50 hours; ``test_v4_verdict_rule`` covers the real constants."""
    end = START_MS + HOURS * HOUR_MS
    patch = pytest.MonkeyPatch()
    for module in (v3_as_built, inputs, rule, v4_verdict_fixtures):
        patch.setattr(module, "V3_END_MS", end)
    yield
    patch.undo()


@pytest.fixture(scope="module")
def module_network_blocked():
    """The same, for the module's shared run."""
    patch = pytest.MonkeyPatch()
    for owner, name in _SOCKET_CALLS:
        patch.setattr(owner, name, _refuse)
    yield
    patch.undo()


# ---- a world and a run ------------------------------------------------------------------------


@dataclasses.dataclass
class World:
    """A folder of summaries, its expected file and the folders the step writes."""

    root: Path
    expected: inputs.Expected
    source: World | None = None  # another world whose summaries and expected file this one reads

    @property
    def summaries(self) -> Path:
        return (self.source or self).root / "summaries"

    @property
    def expected_file(self) -> Path:
        return (self.source or self).root / "expected.json"

    @property
    def progress(self) -> Path:
        return self.root / "progress"

    @property
    def out(self) -> Path:
        return self.root / "out"

    def folder(self, cell_id: str, attempt: int = 1) -> Path:
        return self.summaries / f"v4-summary-{cell_id}-attempt-{attempt}"

    def args(self, *extra: str) -> list[str]:
        return [
            "--summaries",
            str(self.summaries),
            "--expected",
            str(self.expected_file),
            "--progress",
            str(self.progress),
            "--out",
            str(self.out),
            *extra,
        ]

    def run(self, *extra: str) -> int:
        return v4_verdict.main(self.args(*extra))

    def document(self) -> dict[str, Any]:
        loaded = json.loads((self.out / "verdict.json").read_bytes())
        assert isinstance(loaded, dict)
        return loaded

    def page(self) -> str:
        return (self.out / "verdict.md").read_text(encoding="utf-8")

    def outputs(self) -> tuple[bytes, bytes]:
        return (self.out / "verdict.json").read_bytes(), (self.out / "verdict.md").read_bytes()

    def written(self) -> list[str]:
        return sorted(path.name for path in self.out.iterdir()) if self.out.exists() else []


def world(root: Path, hours: int = 50, **keywords: Any) -> World:
    """Write a set of summaries and its expected file under ``root``."""
    summaries = root / "summaries"
    summaries.mkdir(parents=True)
    expected = full_set(summaries, hours, **keywords)
    made = World(root, expected)
    write_expected(made.expected_file, expected)
    return made


def reasons_file(root: Path, earlier: list[str]) -> Path:
    path = root / "reasons.json"
    path.write_bytes(_canonical({"format": DISPATCH_FORMAT, "earlier": earlier}))
    return path


def dispatch_check_of(made: World) -> tuple[str, ...]:
    """The arguments the workflow adds in ``made``'s mode: a registered run's verdict reads the
    dispatch check's file (here, no earlier dispatch); a rehearsal's and a timing run's none."""
    if made.expected.mode != "registered":
        return ()
    return ("--dispatch-reasons", str(reasons_file(made.root, [])))


def stopped(
    cell_id: str = MAIN, *, spoiled: bool = False, outcome: str = LIQUIDATED
) -> dict[str, dict[str, Any]]:
    """An override that makes a cell liquidated (or ``outcome``, another stop) after 20 hours;
    ``spoiled`` also gives a liquidation a reason it does not have, so ``read_cell`` refuses it."""
    keywords: dict[str, Any] = {
        "outcome": outcome,
        "marks": marks_for(cell_id)[:20],
        "final_after_close": None,
        "equity_2025": None,
    }
    if spoiled:
        keywords["reason"] = "ceiling"
    return {cell_id: keywords}


@pytest.fixture(scope="module")
def base(module_network_blocked, tmp_path_factory):
    """One uninterrupted run of the base set: the reference of the byte tests."""
    made = world(tmp_path_factory.mktemp("base"))
    stdout = _run_capturing(made)
    return made, stdout


@pytest.fixture
def shared(base, tmp_path):
    """A world that reads the base set's summaries and expected file, and never changes them: its
    progress and its outputs are under its own folder. For the tests that only run the step."""
    return World(tmp_path, base[0].expected, source=base[0])


def interrupt_after(monkeypatch, made: World, saves: int, *extra: str) -> None:
    """Run the step until its ``saves``-th save of the progress, stop it there with a
    ``KeyboardInterrupt`` (what a cancelled job is) and put the real save back."""
    real = v4_verdict.save_progress
    done: list[int] = []

    def interrupting(path, document):
        real(path, document)
        done.append(1)
        if len(done) == saves:
            raise KeyboardInterrupt

    monkeypatch.setattr(v4_verdict, "save_progress", interrupting)
    with pytest.raises(KeyboardInterrupt):
        made.run(*extra)
    monkeypatch.setattr(v4_verdict, "save_progress", real)


def _run_capturing(made: World, *extra: str) -> str:
    """Run the step and return its standard output (a module-scope-safe capsys)."""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        status = made.run(*extra)
    assert status == 0
    return buffer.getvalue()


# ---- the outputs ------------------------------------------------------------------------------


def test_writes_the_verdict_and_the_page(base):
    made, stdout = base
    document = made.document()
    raw, page = made.outputs()
    assert made.written() == ["verdict.json", "verdict.md"]
    assert raw == _canonical(document)  # canonical JSON: sorted keys, no spaces, no newline
    assert document["format"] == VERDICT_FORMAT
    assert document["verdict"]["outcome"] == "pass"
    assert document["verdict"]["reasons"] == []
    assert len(document["cells"]) == CELLS
    assert document["missing"] == [] and document["refused"] == []
    assert document["reruns"] == [] and document["dispatches"] == []
    assert len(document["verdict"]["checks"]) == CHECKS
    assert all(check["holds"] is True for check in document["verdict"]["checks"])
    assert sum(len(rows) for rows in document["pairs"].values()) == PAIRS
    text = page.decode("utf-8")
    assert text.startswith(SYNTHETIC + "\n\n# V4.0 verdict: ")  # the base world is a rehearsal's
    assert text.endswith("\n")
    positions = [text.index(f"\n{heading}\n") for heading in HEADINGS]
    assert positions == sorted(positions)
    assert NOTE in text
    assert "Synthetic data" in text  # the base world is a rehearsal's
    assert (made.progress / "progress.json").is_file()
    assert "wrote verdict.json and verdict.md" in stdout


def test_the_page_carries_every_cell_and_both_comparisons(base):
    made, _ = base
    text = made.page()
    for cell in all_cells():
        assert cell.cell_id in text
    document = made.document()
    # Every non-v3 arm at each capital and cost, against hold_universe and against v3_as_built.
    assert sorted(document["pairs"]) == sorted(
        f"{arm}-{capital}-{multiple}x"
        for arm in NON_V3
        for capital in CAPITALS
        for multiple in COST_MULTIPLES
    )
    for rows in document["pairs"].values():
        assert sorted(rows) == ["hold", "v3"]
    # The pass rule's own measures are the pairs' for v4_main at 1x.
    for capital in (1000, 10000):
        cell = f"v4_main-{capital}-1x"
        checks = {
            (check["capital"], check["condition"]): check for check in document["verdict"]["checks"]
        }
        assert checks[(capital, 1)]["main"] == document["pairs"][cell]["hold"]["main"]
        assert checks[(capital, 1)]["other"] == document["pairs"][cell]["hold"]["other"]
        assert checks[(capital, 2)]["main"] == document["pairs"][cell]["v3"]["main"]
        assert checks[(capital, 2)]["other"] == document["pairs"][cell]["v3"]["other"]


def test_the_variants_and_neighbours_sit_beside_v4_main(base):
    made, _ = base
    text = made.page()
    section = text.split("\n## Variants and neighbours at 1x\n")[1].split("\n## ")[0]
    for arm in ("v4_main", "v4_long_only", "v4_vol25", "v4_vol60", "v4_faster", "v4_slower"):
        assert arm in section
    for arm in ("v4_btc200_shorts", "v4_confirm3"):
        assert arm in section
    assert "v4_main-1000-2x" not in section  # 1x only


def test_the_page_names_the_analysis_artifact(base):
    made, _ = base
    section = made.page().split("\n## The analysis artifact\n")[1]
    assert "diagnosis.md" in section
    assert "v4-rehearsal-analysis-attempt-" in section  # the base world is a rehearsal's


@pytest.mark.parametrize(
    ("mode", "artifact"),
    [("registered", "v4-analysis-attempt-"), ("timing", "v4-timing-analysis-attempt-")],
)
def test_the_analysis_artifact_is_named_by_mode(tmp_path, mode, artifact):
    made = world(tmp_path, mode=mode)
    assert made.run(*dispatch_check_of(made)) == 0
    section = made.page().split("\n## The analysis artifact\n")[1]
    assert f"`{artifact}<n>`" in section


# ---- resuming ---------------------------------------------------------------------------------


@pytest.mark.parametrize("step", [10, CELLS + 3, CELLS + CHECKS + 20, STEPS - 1])
def test_resume_gives_the_same_bytes(base, shared, monkeypatch, step):
    reference = base[0].outputs()
    made = shared
    real = v4_verdict.save_progress
    saves: list[int] = []

    def interrupting(path, document):
        real(path, document)
        saves.append(1)
        if len(saves) == step:
            raise KeyboardInterrupt

    monkeypatch.setattr(v4_verdict, "save_progress", interrupting)
    with pytest.raises(KeyboardInterrupt):
        made.run()
    assert len(saves) == step
    assert made.written() == []  # nothing is written until the last step is done
    saved = json.loads((made.progress / "progress.json").read_bytes())
    assert saved["format"] == PROGRESS_FORMAT
    monkeypatch.setattr(v4_verdict, "save_progress", real)
    reads: list[Path] = []
    real_read = v4_verdict.read_cell
    monkeypatch.setattr(
        v4_verdict,
        "read_cell",
        lambda folder, expected: reads.append(folder) or real_read(folder, expected),
    )
    assert made.run() == 0
    assert made.outputs() == reference
    assert len(reads) == max(0, CELLS - step)  # a finished cell is never read again


def test_a_finished_progress_gives_the_same_bytes_in_a_fresh_out_folder(base, tmp_path):
    made, _ = base
    out = tmp_path / "again"
    status = v4_verdict.main(
        [
            "--summaries",
            str(made.summaries),
            "--expected",
            str(made.expected_file),
            "--progress",
            str(made.progress),
            "--out",
            str(out),
        ]
    )
    assert status == 0
    assert (
        (out / "verdict.json").read_bytes(),
        (out / "verdict.md").read_bytes(),
    ) == made.outputs()


def _replace_a_summary(made: World, tmp_path: Path) -> None:
    edit_summary(made.folder("hold_btc-1000-1x"), compounded_return="0.5")


def _add_a_folder(made: World, tmp_path: Path) -> None:
    (made.summaries / "stray").mkdir()


def _remove_a_folder(made: World, tmp_path: Path) -> None:
    shutil.rmtree(made.folder("hold_btc-1000-1x"))


def _change_a_receipt(made: World, tmp_path: Path) -> None:
    path = made.folder("hold_btc-1000-1x") / "receipt.json"
    path.write_bytes(path.read_bytes() + b" ")


def _change_the_expected_file(made: World, tmp_path: Path) -> None:
    write_expected(made.expected_file, expected_for(hours=51))


@pytest.mark.parametrize(
    "change",
    [
        _replace_a_summary,
        _add_a_folder,
        _remove_a_folder,
        _change_a_receipt,
        _change_the_expected_file,
    ],
)
def test_resume_with_changed_inputs_is_refused(tmp_path, monkeypatch, capsys, change):
    made = world(tmp_path)
    interrupt_after(monkeypatch, made, 10)
    saved = (made.progress / "progress.json").read_bytes()
    change(made, tmp_path)
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert (made.progress / "progress.json").read_bytes() == saved  # never mixed, never touched
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("v4_verdict: ")
    assert "changed" in err[0]


def test_resume_with_other_dispatch_reasons_is_refused(shared, monkeypatch, capsys):
    made = shared
    first = reasons_file(shared.root, [])
    interrupt_after(monkeypatch, made, 5, "--dispatch-reasons", str(first))
    second = reasons_file(shared.root, ["an earlier dispatch"])
    capsys.readouterr()
    assert made.run("--dispatch-reasons", str(second)) == 1
    assert made.written() == []
    assert "changed" in capsys.readouterr().err
    assert made.run() == 0  # no file is no dispatch, as an empty list is: the same inputs
    assert made.document()["dispatches"] == []


def test_a_summary_replaced_after_it_was_listed_is_refused(tmp_path, monkeypatch, capsys):
    made = world(tmp_path)
    real = v4_verdict.read_cell
    calls: list[Path] = []

    def swapping(folder, expected):
        calls.append(folder)
        if len(calls) == 1:
            edit_summary(folder, compounded_return="0.5")
        return real(folder, expected)

    monkeypatch.setattr(v4_verdict, "read_cell", swapping)
    assert made.run() == 1
    assert made.written() == []
    assert not (made.progress / "progress.json").exists()
    assert "changed" in capsys.readouterr().err


def test_marks_of_a_summary_changed_after_its_acceptance_are_refused(tmp_path, monkeypatch, capsys):
    """``read_marks`` takes the capital from the file and ignores the digest, so the step checks
    that the file is still the one that was accepted."""
    made = world(tmp_path)
    real = v4_verdict.save_progress
    saves: list[int] = []

    def swapping(path, document):
        real(path, document)
        saves.append(1)
        if len(saves) == CELLS:  # every cell is read; the measures are next
            edit_summary(made.folder(HOLD), compounded_return="0.5")

    monkeypatch.setattr(v4_verdict, "save_progress", swapping)
    assert made.run() == 1
    assert made.written() == []
    assert "changed" in capsys.readouterr().err


@pytest.mark.parametrize(
    "damage",
    [
        lambda raw: b"not json",
        lambda raw: raw + b"\n",
        lambda raw: _canonical({**json.loads(raw), "format": "v4-verdict-progress-0"}),
        lambda raw: _canonical({**json.loads(raw), "extra": 1}),
        lambda raw: _canonical({**json.loads(raw), "cells": {"nope": {"refused": {}}}}),
        lambda raw: _canonical({**json.loads(raw), "checks": {"1000:1": {}}}),
        lambda raw: _canonical({**json.loads(raw), "pairs": {"x:hold": {"incomputable": "x"}}}),
    ],
)
def test_a_damaged_progress_is_refused_and_left_alone(shared, monkeypatch, capsys, damage):
    made = shared
    interrupt_after(monkeypatch, made, 5)
    path = made.progress / "progress.json"
    path.write_bytes(damage(path.read_bytes()))
    damaged = path.read_bytes()
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert path.read_bytes() == damaged
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def test_a_tampered_fact_in_the_progress_is_refused(shared, monkeypatch, capsys):
    made = shared
    interrupt_after(monkeypatch, made, 5)
    path = made.progress / "progress.json"
    saved = json.loads(path.read_bytes())
    entry = next(iter(saved["cells"].values()))
    entry["facts"]["summary_sha256"] = "0" * 64  # a fact that is not the listed file's
    path.write_bytes(_canonical(saved))
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert "did not write" in capsys.readouterr().err  # refused on load, not at its first use


def test_a_check_that_contradicts_itself_in_the_progress_is_refused(shared, monkeypatch, capsys):
    made = shared
    interrupt_after(monkeypatch, made, CELLS + 3)  # three checks are done
    path = made.progress / "progress.json"
    saved = json.loads(path.read_bytes())
    assert len(saved["checks"]) == 3
    check = saved["checks"]["1000:3"]  # 1090 against 1000: it holds
    assert check["holds"] is True
    check["holds"] = False  # its two sides say it holds
    path.write_bytes(_canonical(saved))
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert "did not write" in capsys.readouterr().err


def test_a_check_in_the_progress_that_is_not_planned_is_not_used(base, tmp_path, monkeypatch):
    """A record of the progress file counts only for a measure the accepted cells plan."""
    made = world(tmp_path, omit=(HOLD,))
    interrupt_after(monkeypatch, made, 10)
    path = made.progress / "progress.json"
    saved = json.loads(path.read_bytes())
    stray = json.loads((base[0].progress / "progress.json").read_bytes())["checks"]["1000:1"]
    assert stray["holds"] is True
    saved["checks"]["1000:1"] = stray  # a valid record of a check whose cell is missing here
    path.write_bytes(_canonical(saved))
    assert made.run() == 0
    checks = {
        (check["capital"], check["condition"]): check
        for check in made.document()["verdict"]["checks"]
    }
    assert checks[(1000, 1)]["holds"] is None
    assert made.document()["verdict"]["outcome"] == "incomplete"


def test_the_progress_holds_numbers_never_marks(base):
    made, _ = base
    saved = json.loads((made.progress / "progress.json").read_bytes())

    def rows(value: Any) -> Iterator[list[Any]]:
        if isinstance(value, list):
            yield value
            for item in value:
                yield from rows(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from rows(item)

    text = json.dumps(saved)
    assert "open_marks" not in text
    assert str(START_MS + HOUR_MS) not in text  # no hour of a cell's marks, only a path's ends
    for row in rows(saved):  # no [hour, equity, complete] row anywhere
        assert not (
            len(row) == 3 and type(row[0]) is int and type(row[1]) is str and type(row[2]) is bool
        )


def test_the_progress_is_replaced_atomically(base, shared, monkeypatch):
    """Each save is a whole temporary file moved over the progress, so a stop at any moment
    leaves the last whole progress, never a torn file."""
    made = shared
    real_replace = v4_verdict.os.replace
    seen: list[str] = []

    def watching(source, target):
        if Path(target).name != "progress.json":
            return real_replace(source, target)
        seen.append(str(target))
        assert json.loads(Path(source).read_bytes())["format"] == PROGRESS_FORMAT  # whole already
        if len(seen) == 5:
            raise OSError("the machine stopped between the write and the replace")
        return real_replace(source, target)

    monkeypatch.setattr(v4_verdict.os, "replace", watching)
    assert made.run() == 1  # a stop on the 5th save
    saved = json.loads((made.progress / "progress.json").read_bytes())
    assert len(saved["cells"]) == 4  # the 4th save's progress, whole
    monkeypatch.setattr(v4_verdict.os, "replace", real_replace)
    assert made.run() == 0
    assert made.outputs() == base[0].outputs()
    assert not list(made.progress.glob("*.tmp"))
    assert len(seen) == 5


# ---- the two-cells bound ----------------------------------------------------------------------


class _Marks(list):
    """A list a weak reference can name (a plain list cannot be weakly referenced)."""


def test_never_holds_more_than_two_cells_marks(shared, monkeypatch):
    made = shared
    real = v4_verdict.read_marks
    live = 0
    peak = 0
    calls = 0

    def counting(folder):
        nonlocal live, peak, calls
        calls += 1
        held = _Marks(real(folder))
        live += 1
        peak = max(peak, live)

        def gone() -> None:
            nonlocal live
            live -= 1

        weakref.finalize(held, gone)
        return held

    monkeypatch.setattr(v4_verdict, "read_marks", counting)
    assert made.run() == 0
    gc.collect()
    assert live == 0  # nothing is kept after the last step
    assert calls > 100  # the two cells of each check and pair, one for a self-comparison
    assert peak == 2


# ---- the outputs are exclusive ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["verdict.json", "verdict.md"])
def test_an_existing_output_is_never_overwritten(shared, capsys, name):
    made = shared
    made.out.mkdir()
    existing = made.out / name
    existing.write_bytes(b"mine")
    assert made.run() == 1
    assert existing.read_bytes() == b"mine"
    assert made.written() == [name]
    assert not made.progress.exists()  # refused before anything was written
    assert capsys.readouterr().err.startswith("v4_verdict: ")


def test_the_first_output_is_removed_if_the_second_fails(shared, monkeypatch, capsys):
    made = shared
    real = v4_verdict._create

    def failing(path, data):
        if path.name == "verdict.md":
            raise OSError("the disk is full")
        real(path, data)

    monkeypatch.setattr(v4_verdict, "_create", failing)
    assert made.run() == 1
    assert made.written() == []  # verdict.json was created, then removed
    assert not made.out.exists()  # the folder the step made is removed too
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "OSError" in err[0] and "disk is full" not in err[0]


def test_outputs_are_exclusive_and_the_first_is_removed_if_the_second_fails(
    shared, monkeypatch, capsys
):
    """V14 in one test (the cases are spelled out one by one in the tests around it)."""
    made = shared
    for name in ("verdict.json", "verdict.md"):  # exclusive: a file that is there is kept
        made.out.mkdir()
        (made.out / name).write_bytes(b"mine")
        assert made.run() == 1
        assert (made.out / name).read_bytes() == b"mine" and made.written() == [name]
        (made.out / name).unlink()
        made.out.rmdir()
    real = v4_verdict._create

    def failing(path, data):
        if path.name == "verdict.md":
            raise OSError("no")
        real(path, data)

    monkeypatch.setattr(v4_verdict, "_create", failing)
    assert made.run() == 1
    assert not made.out.exists()  # the first file, and the folder this step made, are gone
    monkeypatch.setattr(v4_verdict, "_create", real)
    capsys.readouterr()
    assert made.run() == 0  # nothing was left behind, so the same run now writes both
    assert made.written() == ["verdict.json", "verdict.md"]


def test_a_failed_second_output_leaves_a_folder_that_was_already_there(shared, monkeypatch):
    made = shared
    made.out.mkdir()
    real = v4_verdict._create

    def failing(path, data):
        if path.name == "verdict.md":
            raise OSError("no")
        real(path, data)

    monkeypatch.setattr(v4_verdict, "_create", failing)
    assert made.run() == 1
    assert made.out.is_dir() and made.written() == []


def test_the_outputs_are_created_exclusively(shared, monkeypatch):
    """A file that appears between the check and the write is not overwritten."""
    made = shared
    real = v4_verdict._create
    seen: list[str] = []

    def racing(path, data):
        seen.append(path.name)
        if path.name == "verdict.md":
            path.write_bytes(b"someone else's")  # appears just before the exclusive create
        real(path, data)

    monkeypatch.setattr(v4_verdict, "_create", racing)
    assert made.run() == 1
    assert (made.out / "verdict.md").read_bytes() == b"someone else's"
    assert not (made.out / "verdict.json").exists()
    assert seen == ["verdict.json", "verdict.md"]


# ---- the output rule --------------------------------------------------------------------------


def _every_equity(made: World) -> set[str]:
    found: set[str] = set()
    for path in made.summaries.glob("*/summary.json"):
        document = json.loads(path.read_bytes())
        for key in ("final_equity", "final_after_close", "equity_2025", "compounded_return"):
            if isinstance(document.get(key), str):
                found.add(document[key])
        found.update(row[1] for row in document.get("open_marks", ()))
    return {item for item in found if "." in item or len(item) > 3}


@pytest.mark.parametrize(
    "keywords",
    [
        {},
        {"overrides": stopped()},  # a fail
        {"overrides": stopped(spoiled=True)},  # an incomplete
        {"omit": (HOLD,)},  # an incomplete
    ],
    ids=["a pass", "a stopped v4_main", "a refused cell", "a missing cell"],
)
def test_stdout_names_no_outcome_and_no_number_but_counts(tmp_path, capsys, keywords):
    made = world(tmp_path, **keywords)
    assert made.run() == 0
    captured = capsys.readouterr()
    out = captured.out
    assert out.strip()
    assert not re.search(r"pass|fail|incomplete|complete|liquidated|stop|engine", out, re.I)
    assert not re.search(r"\d\.\d", out)  # no Decimal with a point
    assert all(int(number) < 500 for number in re.findall(r"\d+", out))  # counts, no equity
    assert not any(equity in out for equity in _every_equity(made))
    assert not re.search(r"v4_main|hold_|v3_as_built", out)  # no cell, no arm
    assert all(line.startswith("v4_verdict: ") for line in out.strip().splitlines())
    assert captured.err == ""


def test_a_failure_writes_one_line_naming_the_step_and_the_type_only(tmp_path, capsys):
    made = world(tmp_path)
    made.expected_file.write_bytes(b'{"secret": "8675309.4271"}')
    assert made.run() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("v4_verdict: ")
    assert "ValueError" in lines[0] and "8675309" not in lines[0] and "secret" not in lines[0]
    assert made.written() == [] and not made.progress.exists()


def test_the_counts_line_names_what_was_read_and_what_was_resumed(shared, monkeypatch, capsys):
    made = shared
    interrupt_after(monkeypatch, made, 10)
    capsys.readouterr()
    assert made.run() == 0
    out = capsys.readouterr().out
    assert "48 accepted, 0 refused, 0 missing" in out
    assert "(38 read, 10 resumed)" in out
    assert f"{CHECKS} checks, {PAIRS} pairs ({CHECKS + PAIRS} computed, 0 resumed)" in out


# ---- the verdict's precedence, through the step -----------------------------------------------


def test_a_stopped_v4_main_fails(tmp_path):
    made = world(tmp_path, overrides=stopped())
    assert made.run() == 0  # the step exits 0 whatever the verdict
    document = made.document()
    assert document["verdict"]["outcome"] == "fail"
    assert any("stopped" in reason for reason in document["verdict"]["reasons"])


def test_a_refused_liquidated_v4_main_is_incomplete_not_fail(tmp_path):
    """V2: a refused summary counts as missing, and its outcome is never read."""
    made = world(tmp_path, overrides=stopped(spoiled=True))
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["missing"] == [MAIN]
    assert [row["folder"] for row in document["refused"]] == [made.folder(MAIN).name]
    assert document["refused"][0]["step"] == "keys"
    assert MAIN not in {cell["cell_id"] for cell in document["cells"]}
    assert not any("stopped" in reason for reason in document["verdict"]["reasons"])
    assert "liquidated" not in made.page().split("\n## Missing")[1].split("\n## ")[0]


def test_a_missing_required_cell_is_incomplete(tmp_path):
    made = world(tmp_path, omit=(HOLD,))
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["missing"] == [HOLD]
    checks = {
        (check["capital"], check["condition"]): check for check in document["verdict"]["checks"]
    }
    assert checks[(1000, 1)]["holds"] is None  # a check needing the missing cell is not computed
    assert checks[(1000, 3)]["holds"] is True and checks[(10000, 1)]["holds"] is True
    assert HOLD in made.page()


def test_a_rerun_is_incomplete_and_the_first_attempt_stays(tmp_path):
    made = world(tmp_path)
    write_summary(made.summaries, MAIN, expected=made.expected, attempt=2, **standard_cell(MAIN))
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["reruns"] == [MAIN]
    assert document["refused"] == [
        {
            "folder": made.folder(MAIN, 2).name,
            "step": "rerun",
            "reason": "the folder is a re-run: its attempt is not 1",
        }
    ]
    assert MAIN in {cell["cell_id"] for cell in document["cells"]}  # attempt 1 is accepted
    assert document["missing"] == []
    assert "re-run" in made.page()


def test_a_rerun_of_a_stopped_v4_main_still_fails(tmp_path):
    """The fail precedence is above the re-run's incomplete."""
    made = world(tmp_path, overrides=stopped())
    write_summary(made.summaries, MAIN, expected=made.expected, attempt=2, **standard_cell(MAIN))
    assert made.run() == 0
    assert made.document()["verdict"]["outcome"] == "fail"


def test_a_cell_in_an_engine_error_is_incomplete_and_its_pairs_are_incomputable(tmp_path):
    made = world(tmp_path, overrides={"hold_universe-1000-1x": {"outcome": ENGINE_ERROR}})
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert {cell["cell_id"] for cell in document["cells"]} >= {HOLD}
    assert "incomputable" in document["pairs"]["v4_main-1000-1x"]["hold"]
    assert "incomputable" not in document["pairs"]["v4_main-10000-1x"]["hold"]
    assert "incomputable" in document["pairs"][HOLD]["hold"]  # the cell's own, no path to compare
    assert made.page()


def test_a_v3_engine_error_is_incomplete(tmp_path):
    made = world(tmp_path, overrides={"v3_as_built-1000-1x": {"outcome": ENGINE_ERROR}})
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert "incomputable" in document["pairs"][MAIN]["v3"]


def test_a_missing_reported_cell_is_incomplete(tmp_path):
    """Owner decision v4-d25: every cell of the run counts, so a missing cell that no condition
    reads makes the verdict incomplete while every check holds. The page lists it."""
    made = world(tmp_path, omit=(REPORTED,))
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["missing"] == [REPORTED]
    assert all(check["holds"] is True for check in document["verdict"]["checks"])
    assert document["verdict"]["reasons"] == [f"cell {REPORTED} is missing or refused"]
    section = made.page().split("\n## Missing, refused and re-run cells, and other dispatches\n")[1]
    assert REPORTED in section


@pytest.mark.parametrize("outcome", [ENGINE_ERROR, ACCOUNTING_FAILURE])
def test_a_reported_cell_that_failed_is_incomplete(tmp_path, outcome):
    """v4-d25: an engine error, or outside v4_main an accounting failure, in a cell no condition
    reads is accepted (neither missing nor refused) and still makes the verdict incomplete."""
    made = world(tmp_path, overrides={REPORTED: {"outcome": outcome}})
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["missing"] == [] and document["refused"] == []
    assert REPORTED in {cell["cell_id"] for cell in document["cells"]}
    assert all(check["holds"] is True for check in document["verdict"]["checks"])
    reasons = document["verdict"]["reasons"]
    assert len(reasons) == 1 and reasons[0].startswith(f"cell {REPORTED} ended in an ")


@pytest.mark.parametrize("outcome", [LIQUIDATED, LIMIT_UNRESTORABLE])
def test_a_reported_stop_is_a_result_and_the_set_still_passes(tmp_path, outcome):
    """v4-d25: a reported arm's liquidation or unrestorable limit is a full summary, a result:
    it is reported (its pairs cannot be measured) and the verdict is still the conditions'."""
    made = world(tmp_path, overrides=stopped(REPORTED, outcome=outcome))
    assert made.run() == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "pass"
    assert document["verdict"]["reasons"] == []
    assert "incomputable" in document["pairs"][REPORTED]["hold"]


def test_the_timing_set_has_no_v3_cell_and_is_incomplete(tmp_path):
    made = world(tmp_path, mode="timing")
    assert made.run() == 0
    document = made.document()
    assert len(document["cells"]) == 44
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["missing"] == []  # the expected file lists the 44 only
    # its 44 cells count (v4-d25); the v3 cells are not its, so only condition 2 is incomplete
    assert not any("missing or refused" in reason for reason in document["verdict"]["reasons"])
    assert [c["condition"] for c in document["verdict"]["checks"] if c["holds"] is None] == [2, 2]
    assert made.page().startswith(SYNTHETIC)
    assert all("v3" not in key for key in document["pairs"])
    assert all(sorted(rows) == ["hold"] for rows in document["pairs"].values())


# ---- the dispatch reasons ---------------------------------------------------------------------


def test_dispatch_reasons_make_it_incomplete(shared):
    made = shared
    path = reasons_file(shared.root, ["run 7 of this registration was dispatched earlier"])
    assert made.run("--dispatch-reasons", str(path)) == 0
    document = made.document()
    assert document["verdict"]["outcome"] == "incomplete"
    assert document["dispatches"] == ["run 7 of this registration was dispatched earlier"]
    assert any("dispatch" in reason for reason in document["verdict"]["reasons"])
    section = made.page().split("\n## Missing, refused and re-run cells, and other dispatches\n")[1]
    assert "run 7 of this registration was dispatched earlier" in section


def test_no_earlier_dispatch_is_a_pass(shared):
    made = shared
    assert made.run("--dispatch-reasons", str(reasons_file(shared.root, []))) == 0
    assert made.document()["verdict"]["outcome"] == "pass"


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"[]",
        b"{}",
        _canonical({"format": "v4-dispatch-check-2", "earlier": []}),
        _canonical({"format": DISPATCH_FORMAT}),
        _canonical({"format": DISPATCH_FORMAT, "earlier": "x"}),
        _canonical({"format": DISPATCH_FORMAT, "earlier": [""]}),
        _canonical({"format": DISPATCH_FORMAT, "earlier": [1]}),
        _canonical({"format": DISPATCH_FORMAT, "earlier": [], "extra": 1}),
        _canonical({"format": DISPATCH_FORMAT, "earlier": []}) + b"\n",
        b'{"earlier":[],"format":"v4-dispatch-check-1","format":"v4-dispatch-check-1"}',
        b'{"earlier":[1.5],"format":"v4-dispatch-check-1"}',
    ],
)
def test_any_other_dispatch_reasons_shape_is_refused(shared, capsys, content):
    made = shared
    path = shared.root / "reasons.json"
    path.write_bytes(content)
    assert made.run("--dispatch-reasons", str(path)) == 1
    assert made.written() == [] and not made.progress.exists()
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def test_a_missing_dispatch_reasons_file_is_refused(shared):
    made = shared
    assert made.run("--dispatch-reasons", str(shared.root / "nope.json")) == 1
    assert made.written() == []


def test_a_registered_verdict_without_dispatch_reasons_is_refused(tmp_path, capsys):
    """A registered run's other dispatches are an input of its verdict (Ruling G4): without the
    dispatch check's file, none could be told from a check that never ran. Refused, exit 1,
    nothing written (no output, no progress); with the file, the same set is judged."""
    made = world(tmp_path, mode="registered")
    assert made.run() == 1
    err = capsys.readouterr().err
    assert err == "v4_verdict: refused: a registered run's verdict needs --dispatch-reasons\n"
    assert made.written() == [] and not made.out.exists() and not made.progress.exists()
    assert made.run(*dispatch_check_of(made)) == 0
    assert made.document()["verdict"]["outcome"] == "pass"
    capsys.readouterr()


def test_read_dispatch_reasons(tmp_path):
    path = reasons_file(tmp_path, ["a", "b"])
    assert read_dispatch_reasons(path) == ("a", "b")


# ---- the page ---------------------------------------------------------------------------------


def test_rehearsal_page_says_synthetic(tmp_path):
    made = world(tmp_path, mode="rehearsal")
    assert made.run() == 0
    page = made.page()
    assert page.startswith(SYNTHETIC)
    assert "rehearsal" in page.split("\n", 3)[2].lower()  # then the title names the mode


def test_timing_page_says_synthetic(tmp_path):
    made = world(tmp_path, mode="timing")
    assert made.run() == 0
    page = made.page()
    assert page.startswith(SYNTHETIC)
    assert "timing" in page.split("\n", 3)[2].lower()


def test_a_registered_page_is_not_called_synthetic(tmp_path):
    made = world(tmp_path, mode="registered")
    assert made.run(*dispatch_check_of(made)) == 0
    page = made.page()
    assert "synthetic" not in page.lower()
    first = page.split("\n", 1)[0]
    assert first.startswith("# ") and "registered" in first.lower()
    # Only a registered run's pass is V4.0's pass under the registered rule.
    assert made.document()["verdict"]["outcome"] == "pass"
    assert "**PASS.** v4_main met all 8 checks" in page
    assert "under the registered rule V4.0 passes" in page


def test_a_synthetic_pass_names_its_mode_never_the_registered_rule(base):
    """A rehearsal's or a timing run's pass is a test of the pipeline: its headline names the
    mode and never says V4.0 passes under the registered rule."""
    made, _ = base  # a rehearsal's set, which passes
    page = made.page()
    assert made.document()["verdict"]["outcome"] == "pass"
    assert "**PASS.** The synthetic rehearsal's verdict is pass" in page
    assert "registered rule" not in page and "V4.0 passes" not in page
    # The same document as a timing run's (a timing set has no v3 cell, so the CLI never
    # passes one): the page names the timing run.
    document = made.document()
    timing = {**document, "expected": {**document["expected"], "mode": "timing"}}
    timing_page = render_verdict_page(timing)
    assert "**PASS.** The synthetic timing run's verdict is pass" in timing_page
    assert "registered rule" not in timing_page and "V4.0 passes" not in timing_page


def test_a_synthetic_fail_names_its_mode(tmp_path):
    """A stopped v4_main fails a rehearsal's set: its headline names the rehearsal, not V4.0."""
    made = world(tmp_path, mode="rehearsal", overrides=stopped())
    assert made.run() == 0
    page = made.page()
    assert made.document()["verdict"]["outcome"] == "fail"
    assert "fails the synthetic rehearsal's verdict" in page and "fails V4.0" not in page


def test_v3_adapter_disclosed(base):
    made, _ = base
    document = made.document()
    page = made.page()
    section = page.split("\n## Disclosures\n")[1].split("\n## ")[0]
    assert V3_CAPITAL_ADAPTER in section
    assert "v3_as_built-1000-1x" in section and "v3_as_built-1000-2x" in section
    assert "v3_as_built-10000-1x" not in section  # V3's own capital needs no adapter
    assert "synthetic" in section.lower()  # the world of a rehearsal is disclosed too
    carried = {
        cell["cell_id"]: cell["disclosures"] for cell in document["cells"] if cell["disclosures"]
    }
    assert set(carried) == {"v3_as_built-1000-1x", "v3_as_built-1000-2x"}


def test_a_registered_page_discloses_the_adapter_and_not_a_synthetic_world(tmp_path):
    made = world(tmp_path, mode="registered")
    assert made.run(*dispatch_check_of(made)) == 0
    section = made.page().split("\n## Disclosures\n")[1].split("\n## ")[0]
    assert V3_CAPITAL_ADAPTER in section
    assert "synthetic" not in section.lower()


def test_the_conditions_show_both_sides_numbers(base):
    made, _ = base
    section = made.page().split("\n## The four conditions\n")[1].split("\n## ")[0]
    assert "1000" in section and "10000" in section
    for word in ("return", "drawdown", "ratio"):
        assert word in section
    for condition in ("1", "2", "3", "4"):
        assert re.search(rf"\|\s*{condition}\b", section)
    # A condition-1 side with no drawdown has an infinite ratio.
    assert "infinite" in section


def test_the_eras_and_the_years_of_v4_main(base):
    made, _ = base
    section = made.page().split("\n## The eras\n")[1].split("\n## ")[0]
    for era in ("start-2020", "2021-2024", "2025-end"):
        assert era in section
    assert "| Year |" in section  # the years of v4_main follow the eras


def test_the_comparison_table_has_a_row_per_cell_with_both_measures(base):
    made, _ = base
    section = made.page().split("\n## The comparison table\n")[1].split("\n## ")[0]
    rows = [line for line in section.splitlines() if re.match(r"\| [a-z0-9_]+-\d+-[12]x \|", line)]
    cells = {row.split("|")[1].strip() for row in rows}
    assert cells == {cell.cell_id for cell in all_cells()}
    main_row = next(row for row in rows if row.split("|")[1].strip() == MAIN)
    assert "complete" in main_row and "%" in main_row


# ---- skipped hours: "skipped for all arms alike and listed" ---------------------------------


def hour(index: int) -> int:
    """The open of the set's ``index``-th hour."""
    return START_MS + index * HOUR_MS


def gap_overrides() -> dict[str, dict[str, Any]]:
    """Hours missing at different places, at 1,000 USDT and normal costs: v4_main's mark at hour
    5 is incomplete, hold_universe has no mark at hour 9 and v3_as_built's at hour 7 is
    incomplete."""
    v3_cell = "v3_as_built-1000-1x"
    main, v3 = marks_for(MAIN), marks_for(v3_cell)
    main[5] = (main[5][0], main[5][1], False)
    v3[7] = (v3[7][0], v3[7][1], False)
    hold = [mark for index, mark in enumerate(marks_for(HOLD)) if index != 9]
    return {MAIN: {"marks": main}, HOLD: {"marks": hold}, v3_cell: {"marks": v3}}


def test_the_skipped_hours_are_listed_in_the_checks_and_counted_in_the_pairs(tmp_path):
    made = world(tmp_path, overrides=gap_overrides())
    assert made.run() == 0
    document = made.document()
    checks = {
        (check["capital"], check["condition"]): check for check in document["verdict"]["checks"]
    }
    # each arm misses a different hour: both are listed, sorted, as integers
    assert checks[(1000, 1)]["skipped_ms"] == [hour(5), hour(9)]
    assert checks[(1000, 2)]["skipped_ms"] == [hour(5), hour(7)]
    assert all(type(item) is int for item in checks[(1000, 1)]["skipped_ms"])
    assert checks[(10000, 1)]["skipped_ms"] == checks[(10000, 2)]["skipped_ms"] == []
    for key in ((1000, 3), (1000, 4), (10000, 3), (10000, 4)):
        assert checks[key]["skipped_ms"] is None  # no hourly path
    pairs = document["pairs"]
    assert set(pairs[MAIN]["hold"]) == {"main", "other", "skipped_hours"}
    assert pairs[MAIN]["hold"]["skipped_hours"] == 2  # a count only, never a list
    assert pairs[MAIN]["v3"]["skipped_hours"] == 2
    assert pairs["v4_long_only-1000-1x"]["hold"]["skipped_hours"] == 1  # hold's hour 9
    assert pairs["v4_long_only-1000-1x"]["v3"]["skipped_hours"] == 1  # v3's hour 7
    assert pairs[HOLD]["hold"]["skipped_hours"] == 1  # hold_universe against itself
    assert pairs["v4_main-10000-1x"]["hold"]["skipped_hours"] == 0
    assert not any("skipped_ms" in pair for rows in pairs.values() for pair in rows.values())


def test_the_base_set_skips_no_hour(base):
    document = base[0].document()
    for check in document["verdict"]["checks"]:
        assert check["skipped_ms"] == ([] if check["condition"] in (1, 2) else None)
    assert all(
        pair["skipped_hours"] == 0 for rows in document["pairs"].values() for pair in rows.values()
    )


@pytest.mark.parametrize("step", [CELLS + 2, CELLS + CHECKS + 10])
def test_a_resume_with_skipped_hours_gives_the_same_bytes(tmp_path, monkeypatch, step):
    reference = world(tmp_path / "reference", overrides=gap_overrides())
    assert reference.run() == 0
    made = world(tmp_path / "resumed", overrides=gap_overrides())
    interrupt_after(monkeypatch, made, step)
    saved = json.loads((made.progress / "progress.json").read_bytes())
    assert saved["checks"]["1000:1"]["skipped_ms"] == [hour(5), hour(9)]  # kept in the progress
    assert made.run() == 0
    assert made.outputs() == reference.outputs()
    assert made.document()["verdict"]["checks"][0]["skipped_ms"] == [hour(5), hour(9)]


@pytest.mark.parametrize(
    "hours", [[2 * HOUR_MS, HOUR_MS], [HOUR_MS, HOUR_MS], [HOUR_MS + 1], None, "x"]
)
def test_a_check_with_malformed_skipped_hours_in_the_progress_is_refused(
    shared, monkeypatch, capsys, hours
):
    made = shared
    interrupt_after(monkeypatch, made, CELLS + 1)  # the first check, condition 1, is done
    path = made.progress / "progress.json"
    saved = json.loads(path.read_bytes())
    saved["checks"]["1000:1"]["skipped_ms"] = hours
    path.write_bytes(_canonical(saved))
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert "did not write" in capsys.readouterr().err


@pytest.mark.parametrize("count", [-1, True, "2", None])
def test_a_pair_with_a_malformed_skipped_count_in_the_progress_is_refused(
    shared, monkeypatch, capsys, count
):
    made = shared
    interrupt_after(monkeypatch, made, CELLS + CHECKS + 1)  # the first pair is done
    path = made.progress / "progress.json"
    saved = json.loads(path.read_bytes())
    (record,) = saved["pairs"].values()
    record["skipped_hours"] = count
    path.write_bytes(_canonical(saved))
    capsys.readouterr()
    assert made.run() == 1
    assert made.written() == []
    assert "did not write" in capsys.readouterr().err


def test_the_page_counts_the_skipped_hours(tmp_path):
    made = world(tmp_path, overrides=gap_overrides())
    assert made.run() == 0
    section = made.page().split("\n## The four conditions\n")[1].split("\n## ")[0]
    assert "verdict.json" in section and "skipped_ms" in section  # where the hours are listed

    def column(capital: int) -> dict[str, str]:
        """The 'Skipped hours' cell of each condition's row, for one capital."""
        table = section.split(f"### Capital {capital} USDT")[1].split("###")[0]
        rows = [line.split("|")[1:-1] for line in table.splitlines() if line.startswith("| ")]
        head, body = [cell.strip() for cell in rows[0]], rows[2:]
        assert "Skipped hours" in head
        return {row[0].strip(): row[head.index("Skipped hours")].strip() for row in body}

    assert column(1000) == {"1": "2", "2": "2", "3": "n/a", "4": "n/a"}
    assert column(10000) == {"1": "0", "2": "0", "3": "n/a", "4": "n/a"}


def test_a_check_that_could_not_be_computed_has_no_skipped_hours_on_the_page(tmp_path):
    made = world(tmp_path, omit=(HOLD,))
    assert made.run() == 0
    checks = {
        (check["capital"], check["condition"]): check
        for check in made.document()["verdict"]["checks"]
    }
    assert checks[(1000, 1)]["holds"] is None and checks[(1000, 1)]["skipped_ms"] is None
    assert checks[(1000, 2)]["skipped_ms"] == []  # v3's cell is there
    section = made.page().split("\n## The four conditions\n")[1].split("\n## ")[0]
    row = next(line for line in section.splitlines() if line.startswith("| 1 | return over"))
    assert "cannot be computed" in row and " n/a " in row


# ---- escaping ---------------------------------------------------------------------------------


def _document_with(**keywords: Any) -> dict[str, Any]:
    expected = expected_for()
    verdict = decide({}, [], expected=(), missing=[], reruns=[], dispatches=[])
    arguments: dict[str, Any] = {
        "accepted": {},
        "refused": {},
        "missing": [],
        "pairs": {},
        "dispatches": [],
    }
    arguments.update(keywords)
    return verdict_document(expected, verdict, **arguments)


def test_every_value_is_escaped_for_markdown():
    separator = chr(0x2028)  # a line break the Unicode standard has and Python's source has not
    document = _document_with(
        refused={"v4-summary-a|b`c-attempt-1": ("folder", "line one\nline two | `tick` \\ <b>")},
        dispatches=[f"a|b`c\nd\re{separator}f"],
        missing=["x|y"],
    )
    page = render_verdict_page(document)
    assert "a\\|b\\`c d e f" in page  # `|` and backticks escaped, every line break a space
    assert "line one line two \\| \\`tick\\` \\\\ \\<b>" in page
    assert "x\\|y" in page
    for line in page.splitlines():
        if "tick" in line:  # a row of three columns: four pipes that are not escaped
            assert len(re.findall(r"(?<!\\)\|", line)) == 4
    assert "\r" not in page and separator not in page


def test_rerun_cells_are_the_cells_of_the_rerun_folders():
    refused = {
        "v4-summary-v4_main-1000-1x-attempt-2": ("rerun", "x"),
        "v4-summary-v4_main-1000-1x-attempt-3": ("rerun", "x"),
        "v4-summary-hold_btc-1000-1x-attempt-1": ("keys", "x"),
        "v4-summary-v3_as_built-10000-1x-attempt-2": ("rerun", "x"),
    }
    assert rerun_cells(refused) == ["v3_as_built-10000-1x", "v4_main-1000-1x"]


# ---- the classification (V3) ------------------------------------------------------------------


def test_two_accepted_folders_of_one_cell_refuse_both(tmp_path):
    made = world(tmp_path, omit=(MAIN,))
    folder = write_summary(made.summaries, MAIN, expected=made.expected, **standard_cell(MAIN))
    facts = read_cell(folder, made.expected)
    entries: dict[str, Any] = {
        folder.name: facts,
        "second": dataclasses.replace(facts, folder="second"),
        "refused": ("keys", "a reason"),
    }
    sorted_entries = dict(sorted(entries.items()))
    classified = v4_verdict.classify(sorted_entries, made.expected.cells)
    assert MAIN not in classified.accepted
    assert classified.refused[folder.name][0] == "duplicate"
    assert classified.refused["second"][0] == "duplicate"
    assert classified.refused["refused"] == ("keys", "a reason")
    assert MAIN in classified.missing
    assert classified.reruns == []


# ---- the record forms -------------------------------------------------------------------------


def measure(**changes: Any) -> PathMeasure:
    values: dict[str, Any] = {
        "hours": 3,
        "first_ms": START_MS,
        "last_ms": START_MS + 2 * HOUR_MS,
        "start_equity": D("100"),
        "end_equity": D("120"),
        "compounded_return": D("0.2"),
        "max_drawdown": D("0.04545454545454545454545454545454545454545454545454545454545"),
        "ratio": D("4.4"),
    }
    values.update(changes)
    return PathMeasure(**values)


def test_a_measure_round_trips_with_an_infinite_ratio():
    for item in (measure(), measure(max_drawdown=D(0), ratio=INFINITY)):
        record = measure_record(item)
        assert all(type(value) in (int, str) for value in record.values())
        assert measure_from_record(json.loads(json.dumps(record))) == item
    assert measure_record(measure(ratio=INFINITY))["ratio"] == "Infinity"
    assert _canonical(measure_record(measure()))


SKIPPED_HOURS = (START_MS + HOUR_MS, START_MS + 5 * HOUR_MS)


@pytest.mark.parametrize(
    "check",
    [
        Check(1, 1000, True, measure(), measure(ratio=D("1.5")), None, SKIPPED_HOURS),
        Check(2, 10000, False, measure(), measure(), None, ()),
        Check(3, 1000, True, D("1018"), D("1000"), None),
        Check(4, 10000, False, D("990.5"), D("1000"), None),
        Check(1, 1000, None, None, None, "the two arms have no common hour"),
        Check(4, 1000, None, None, None, "the cell has no equity at 2025-01-01 00:00"),
    ],
)
def test_a_check_round_trips(check):
    record = check_record(check)
    assert check_from_record(json.loads(_canonical(record))) == check


def test_a_check_record_lists_its_skipped_hours_as_integers_or_null():
    listed = check_record(Check(1, 1000, True, measure(), measure(), None, SKIPPED_HOURS))
    assert listed["skipped_ms"] == list(SKIPPED_HOURS)
    assert all(type(hour) is int for hour in listed["skipped_ms"])
    for check in (
        Check(3, 1000, True, D("1018"), D("1000"), None),
        Check(2, 1000, None, None, None, "no common hour"),
    ):
        assert check_record(check)["skipped_ms"] is None


def good_record(**changes: Any) -> dict[str, Any]:
    """A good condition-3 record, changed."""
    base: dict[str, Any] = {
        "condition": 3,
        "capital": 1000,
        "holds": True,
        "main": "2",
        "other": "1",
        "note": None,
        "skipped_ms": None,
    }
    return {**base, **changes}


def hours_record(**changes: Any) -> dict[str, Any]:
    """A good condition-1 record, changed."""
    check = Check(1, 1000, True, measure(), measure(ratio=D("1.5")), None, SKIPPED_HOURS)
    return {**check_record(check), **changes}


UNCOMPUTED = {"holds": None, "main": None, "other": None, "note": "x"}


@pytest.mark.parametrize(
    "record",
    [
        {},
        good_record(condition=5, **UNCOMPUTED),
        good_record(capital=5, **UNCOMPUTED),
        good_record(note="x"),  # it holds, and has a note
        good_record(holds=None, main=None, other=None),  # it cannot be computed, and has none
        good_record(main="NaN"),
        good_record(main="1e3"),
        good_record(holds="yes"),
        good_record(main=None),
        good_record(condition=1),  # Decimals for a condition that compares paths
        {**good_record(), "x": 1},
        {key: value for key, value in good_record().items() if key != "skipped_ms"},
        good_record(skipped_ms=[]),  # condition 3 has no hours
        good_record(skipped_ms=[], **UNCOMPUTED),  # an uncomputed check has none
        hours_record(skipped_ms=None),  # a computed condition 1 has its list
        hours_record(skipped_ms="x"),
        hours_record(skipped_ms=[2 * HOUR_MS, HOUR_MS]),  # not increasing
        hours_record(skipped_ms=[HOUR_MS, HOUR_MS]),  # an hour twice
        hours_record(skipped_ms=[HOUR_MS + 1]),  # not an hour open
        hours_record(skipped_ms=[-HOUR_MS]),
        hours_record(skipped_ms=[True]),
        hours_record(skipped_ms=[str(HOUR_MS)]),
        hours_record(holds=False),  # its sides say it holds
    ],
)
def test_a_malformed_check_record_is_refused(record):
    with pytest.raises(ValueError):
        check_from_record(record)


def test_a_malformed_measure_record_is_refused():
    good = measure_record(measure())
    for broken in (
        {**good, "ratio": "-Infinity"},
        {**good, "ratio": "NaN"},
        {**good, "max_drawdown": "Infinity"},
        {**good, "hours": True},
        {**good, "hours": 0},
        {**good, "extra": 1},
        {key: value for key, value in good.items() if key != "ratio"},
    ):
        with pytest.raises(ValueError):
            measure_from_record(broken)


def test_the_document_is_exact_json_and_a_verdict_without_cells_is_incomplete():
    document = _document_with()
    assert _canonical(document)
    assert document["verdict"]["outcome"] == "incomplete"
    assert render_verdict_page(document)
