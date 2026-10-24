"""The v4-cells workflow's timing helper (``scripts/v4_cells_timing.py``) on fabricated GNU
``time -v`` output and synthetic cell folders.

Each cell job runs ``v4_cell.py`` under ``/usr/bin/time -v -o out/<cell>.time``. The helper turns
that file and the cell's ``records.jsonl`` into ``out/<cell>/timing.json``: the wall seconds, the
peak resident memory in MB and the records file's size in bytes. These are the numbers the spec's
timing run needs. The diagnose job times its diagnosis the same way into
``diagnosis/diagnose-timing.json``, with the exit status, since a diagnosis that refused a cell
exits 1 after writing the others'; v4-run's verdict job times its verdict step and its expected
step into ``verdict/verdict-timing.json`` and ``verdict/expected-timing.json``. Nothing here reads
market data.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cells_timing  # noqa: E402

CELL = "v4_main-10000-1x"


def gnu_time(elapsed: str = "0:03.47", kilobytes: int = 51248, exit_status: int = 0) -> str:
    """The text of ``/usr/bin/time -v`` (GNU time 1.9, as ubuntu runners have it)."""
    return (
        f'\tCommand being timed: "python scripts/v4_cell.py run --arm v4_main --out out"\n'
        "\tUser time (seconds): 3.20\n"
        "\tSystem time (seconds): 0.25\n"
        "\tPercent of CPU this job got: 99%\n"
        f"\tElapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}\n"
        "\tAverage shared text size (kbytes): 0\n"
        "\tAverage unshared data size (kbytes): 0\n"
        "\tAverage stack size (kbytes): 0\n"
        "\tAverage total size (kbytes): 0\n"
        f"\tMaximum resident set size (kbytes): {kilobytes}\n"
        "\tAverage resident set size (kbytes): 0\n"
        "\tMajor (requiring I/O) page faults: 0\n"
        "\tMinor (reclaiming a frame) page faults: 9783\n"
        "\tVoluntary context switches: 7\n"
        "\tInvoluntary context switches: 12\n"
        "\tSwaps: 0\n"
        "\tFile system inputs: 0\n"
        "\tFile system outputs: 8\n"
        "\tSocket messages sent: 0\n"
        "\tSocket messages received: 0\n"
        "\tSignals delivered: 0\n"
        "\tPage size (bytes): 4096\n"
        f"\tExit status: {exit_status}\n"
    )


# A long cell as GNU time 1.9 (Ubuntu's `time` package, what `ubuntu-latest` has) reports it, as
# literally as it can be written: one tab before each field, the command line quoted, and the
# hour-long wall clock as h:mm:ss with no fraction (below an hour it is m:ss.ss). 98% of the CPU:
# (4870.12 + 61.40) s of a 5025 s run.
REALISTIC = (
    '\tCommand being timed: "python scripts/v4_cell.py run --data v4data --arm v4_main'
    ' --capital 10000 --costs 1 --out out"\n'
    "\tUser time (seconds): 4870.12\n"
    "\tSystem time (seconds): 61.40\n"
    "\tPercent of CPU this job got: 98%\n"
    "\tElapsed (wall clock) time (h:mm:ss or m:ss): 1:23:45\n"
    "\tAverage shared text size (kbytes): 0\n"
    "\tAverage unshared data size (kbytes): 0\n"
    "\tAverage stack size (kbytes): 0\n"
    "\tAverage total size (kbytes): 0\n"
    "\tMaximum resident set size (kbytes): 2154308\n"
    "\tAverage resident set size (kbytes): 0\n"
    "\tMajor (requiring I/O) page faults: 3\n"
    "\tMinor (reclaiming a frame) page faults: 4863201\n"
    "\tVoluntary context switches: 1812\n"
    "\tInvoluntary context switches: 94211\n"
    "\tSwaps: 0\n"
    "\tFile system inputs: 1259328\n"
    "\tFile system outputs: 263480\n"
    "\tSocket messages sent: 0\n"
    "\tSocket messages received: 0\n"
    "\tSignals delivered: 0\n"
    "\tPage size (bytes): 4096\n"
    "\tExit status: 0\n"
)
# The same command failing: GNU time adds a first line, and still prints "Exit status".
REALISTIC_FAILED = "\tCommand exited with non-zero status 1\n" + REALISTIC.replace(
    "Exit status: 0", "Exit status: 1"
)
# The same command killed by a signal (9: the kernel's out-of-memory kill): GNU time adds a first
# line, and prints "Exit status: 0", the status of a killed command being undefined.
REALISTIC_KILLED = "Command terminated by signal 9\n" + REALISTIC


def test_parse_reads_the_wall_seconds_and_the_peak_resident_kilobytes():
    timing = v4_cells_timing.parse_time_output(gnu_time())
    assert timing == v4_cells_timing.Timing(Decimal("3.47"), 51248)


def test_parse_reads_a_realistic_gnu_time_report_of_an_hour_long_cell():
    timing = v4_cells_timing.parse_time_output(REALISTIC)
    assert timing == v4_cells_timing.Timing(Decimal(5025), 2154308)  # 1:23:45; 2.05 GiB


@pytest.mark.parametrize(
    ("elapsed", "seconds"),
    [
        ("0:00.00", "0"),
        ("0:03.47", "3.47"),
        ("12:34.56", "754.56"),
        ("59:59.99", "3599.99"),
        ("1:02:03.45", "3723.45"),
        ("10:00:00.00", "36000"),
        # From an hour on GNU time prints no fraction: h:mm:ss.
        ("1:00:00", "3600"),
        ("1:02:03", "3723"),
        ("1:23:45", "5025"),
        ("2:59:59", "10799"),
        ("10:00:00", "36000"),
    ],
)
def test_parse_reads_both_elapsed_formats(elapsed, seconds):
    timing = v4_cells_timing.parse_time_output(gnu_time(elapsed=elapsed))
    assert timing.wall_seconds == Decimal(seconds)


REFUSED = [
    ("", "0 elapsed wall clock lines, expected one: not GNU time -v output"),
    (  # a shell's time, not GNU time -v
        "real\t0m 3.47s\nuser\t0m 3.20s\nsys\t0m 0.25s\n",
        "0 elapsed wall clock lines, expected one: not GNU time -v output",
    ),
    (  # BusyBox time and the like: no -v
        "/usr/bin/time: invalid option -- 'v'\n",
        "0 elapsed wall clock lines, expected one: not GNU time -v output",
    ),
    (
        gnu_time().replace("Elapsed (wall clock)", "Elapsed"),
        "0 elapsed wall clock lines, expected one: not GNU time -v output",
    ),
    (
        gnu_time().replace("Maximum resident set size (kbytes)", "Max RSS"),
        "0 maximum resident set size lines, expected one: not GNU time -v output",
    ),
    (gnu_time(elapsed="1:75.00"), "has minutes or seconds of 60 or more"),
    (gnu_time(elapsed="75:00"), "has minutes or seconds of 60 or more"),  # h:mm:ss from an hour
    (gnu_time(elapsed="1:61:00"), "has minutes or seconds of 60 or more"),
    (gnu_time(elapsed="1:02:61"), "has minutes or seconds of 60 or more"),
    (gnu_time(elapsed="abc"), "is not h:mm:ss.ss or m:ss.ss"),
    (gnu_time(elapsed="1:2:3:4.00"), "is not h:mm:ss.ss or m:ss.ss"),
    (gnu_time(elapsed="-0:03.47"), "is not h:mm:ss.ss or m:ss.ss"),
    (gnu_time(elapsed="1:02:3"), "is not h:mm:ss.ss or m:ss.ss"),
    (gnu_time(elapsed="3"), "is not h:mm:ss.ss or m:ss.ss"),
    (gnu_time(kilobytes=0), "the maximum resident set size is not positive"),
    (gnu_time(exit_status=1), "the timed command exited with status 1"),
    (REALISTIC_FAILED, "the timed command exited with status 1"),
    (REALISTIC_KILLED, "the timed command was terminated by signal 9"),
    (  # two values: ambiguous
        gnu_time() + "\tMaximum resident set size (kbytes): 99\n",
        "2 maximum resident set size lines, expected one: not GNU time -v output",
    ),
    (
        gnu_time() + "\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:01.00\n",
        "2 elapsed wall clock lines, expected one: not GNU time -v output",
    ),
]


@pytest.mark.parametrize(("text", "message"), REFUSED)
def test_parse_refuses_anything_but_one_gnu_time_report_of_a_clean_exit(text, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        v4_cells_timing.parse_time_output(text)


def cell_folder(tmp_path: Path, records: bytes = b"x" * 12345) -> Path:
    folder = tmp_path / "out" / CELL
    folder.mkdir(parents=True)
    (folder / "records.jsonl").write_bytes(records)
    return folder


def time_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "out" / f"{CELL}.time"
    path.write_text(text, encoding="ascii")
    return path


def run(tmp_path: Path, capsys) -> tuple[int, str, str]:
    code = v4_cells_timing.main(
        [
            "--time-file",
            str(tmp_path / "out" / f"{CELL}.time"),
            "--cell-dir",
            str(tmp_path / "out" / CELL),
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_timing_json_holds_the_seconds_the_megabytes_and_the_records_bytes(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    time_file(tmp_path, gnu_time(elapsed="1:02:03.45", kilobytes=51248))
    code, out, err = run(tmp_path, capsys)
    assert code == 0 and err == ""
    text = (folder / "timing.json").read_text(encoding="ascii")
    assert json.loads(text) == {
        "cell": CELL,
        "wall_seconds": 3723.45,
        "peak_rss_mb": 50.0,  # 51248 kB / 1024
        "records_bytes": 12345,
    }
    assert text.endswith("\n") and text.count("\n") == 1  # one canonical line
    # Sizes and times only.
    assert out == f"v4_cells_timing: {CELL}: 3723.45 s, 50.0 MB peak, 12345 record bytes\n"


def test_a_realistic_report_makes_a_timing_json(tmp_path, capsys):
    folder = cell_folder(tmp_path, records=b"x" * 1_350_000)
    time_file(tmp_path, REALISTIC)
    code, out, err = run(tmp_path, capsys)
    assert code == 0 and err == ""
    assert json.loads((folder / "timing.json").read_text(encoding="ascii")) == {
        "cell": CELL,
        "wall_seconds": 5025.0,  # 1:23:45, no fraction
        "peak_rss_mb": 2103.8,  # 2154308 kB / 1024 = 2103.816...
        "records_bytes": 1_350_000,
    }
    assert out == f"v4_cells_timing: {CELL}: 5025.00 s, 2103.8 MB peak, 1350000 record bytes\n"


def test_a_failed_realistic_report_makes_no_timing_json(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    time_file(tmp_path, REALISTIC_FAILED)
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == ""
    assert "the timed command exited with status 1" in err
    assert not (folder / "timing.json").exists()


def test_megabytes_are_kilobytes_over_1024_to_one_decimal(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    time_file(tmp_path, gnu_time(kilobytes=1536 * 1024 + 614))  # 1536.5996... MB
    assert run(tmp_path, capsys)[0] == 0
    assert json.loads((folder / "timing.json").read_text())["peak_rss_mb"] == 1536.6


def test_the_records_size_is_the_files_size_in_bytes(tmp_path, capsys):
    folder = cell_folder(tmp_path, records=b"")
    time_file(tmp_path, gnu_time())
    assert run(tmp_path, capsys)[0] == 0
    assert json.loads((folder / "timing.json").read_text())["records_bytes"] == 0


def test_a_missing_time_file_fails_clearly_and_writes_nothing(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == ""
    assert "GNU time" in err and "/usr/bin/time" in err
    assert not (folder / "timing.json").exists()


def test_a_report_that_is_not_gnu_time_fails_and_writes_nothing(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    time_file(tmp_path, "real\t0m 3.47s\n")
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == ""
    assert "the time file is not a clean GNU time -v report" in err
    assert "0 elapsed wall clock lines" in err
    assert not (folder / "timing.json").exists()


def test_a_missing_records_file_fails_and_writes_nothing(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    (folder / "records.jsonl").unlink()
    time_file(tmp_path, gnu_time())
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == "" and "records.jsonl" in err
    assert not (folder / "timing.json").exists()


def test_an_existing_timing_json_is_never_replaced(tmp_path, capsys):
    folder = cell_folder(tmp_path)
    (folder / "timing.json").write_text("earlier\n", encoding="ascii")
    time_file(tmp_path, gnu_time())
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == "" and "timing.json" in err
    assert (folder / "timing.json").read_text(encoding="ascii") == "earlier\n"


class ShortWrite:
    """A created file whose write stops part way and raises, as on a full disk."""

    def __init__(self, handle: Any) -> None:
        self.handle = handle

    def __enter__(self) -> ShortWrite:
        return self

    def __exit__(self, *exc: object) -> None:
        self.handle.close()

    def write(self, text: str) -> int:
        self.handle.write(text[:5])
        raise OSError(28, "No space left on device")


def fail_created_writes(monkeypatch) -> None:
    """Every file opened with mode "x" is created, then its write fails part way."""
    real_open = Path.open

    def open_short(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        handle = real_open(self, mode, *args, **kwargs)
        return ShortWrite(handle) if "x" in mode else handle

    monkeypatch.setattr(Path, "open", open_short)


def test_a_timing_json_whose_write_fails_is_removed(tmp_path, capsys, monkeypatch):
    """Codex P2 on #294: a timing.json created but not fully written is removed again, so the
    workflow keeps the replay without a timing.json rather than with a partial one the diagnosis
    would refuse; the cell's own files stay."""
    folder = cell_folder(tmp_path)
    time_file(tmp_path, gnu_time())
    fail_created_writes(monkeypatch)
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == ""
    assert err == f"::error::v4_cells_timing: cannot create timing.json of {CELL} (OSError)\n"
    assert sorted(path.name for path in folder.iterdir()) == ["records.jsonl"]


def test_a_diagnose_timing_whose_write_fails_is_removed(tmp_path, capsys, monkeypatch):
    fail_created_writes(monkeypatch)
    code, out, err = diagnose(tmp_path, capsys, gnu_time())
    assert code == 1 and out == "" and "cannot create diagnose-timing.json (OSError)" in err
    assert list((tmp_path / "diagnosis").iterdir()) == []


# ---- the diagnose step's own timing ----


def diagnose(
    tmp_path: Path, capsys, text: str | None, *, folder: bool = True
) -> tuple[int, str, str]:
    """``--diagnosis-dir``: ``text`` as ``diagnose.time`` (none when None), into the folder
    ``diagnosis`` the diagnosis made (missing when ``folder`` is false)."""
    if folder:
        (tmp_path / "diagnosis").mkdir()
    if text is not None:
        (tmp_path / "diagnose.time").write_text(text, encoding="ascii")
    argv = ["--time-file", str(tmp_path / "diagnose.time")]
    code = v4_cells_timing.main([*argv, "--diagnosis-dir", str(tmp_path / "diagnosis")])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_diagnose_timing_holds_the_seconds_the_megabytes_and_the_exit_status(tmp_path, capsys):
    code, out, err = diagnose(tmp_path, capsys, REALISTIC)
    assert (code, err) == (0, "")
    text = (tmp_path / "diagnosis" / "diagnose-timing.json").read_text(encoding="ascii")
    assert json.loads(text) == {
        "step": "diagnose",
        "wall_seconds": 5025.0,
        "peak_rss_mb": 2103.8,
        "exit_status": 0,
    }
    assert text.endswith("\n") and text.count("\n") == 1
    assert out == "v4_cells_timing: diagnose: 5025.00 s, 2103.8 MB peak, exit status 0\n"


def test_a_diagnosis_that_refused_a_cell_is_timed_with_its_exit_status(tmp_path, capsys):
    """The diagnosis exits 1 when it refused a cell and wrote the others' diagnosis: that run is
    the one the timing must not lose."""
    code, out, err = diagnose(tmp_path, capsys, REALISTIC_FAILED)
    assert (code, err) == (0, "")
    document = json.loads((tmp_path / "diagnosis" / "diagnose-timing.json").read_text())
    assert document["exit_status"] == 1 and document["peak_rss_mb"] == 2103.8
    assert out.endswith("exit status 1\n")


def test_the_cell_timing_still_refuses_a_failed_command(tmp_path, capsys):
    with pytest.raises(ValueError, match="exited with status 1"):
        v4_cells_timing.parse_time_output(REALISTIC_FAILED)
    assert v4_cells_timing.parse_time_output(REALISTIC_FAILED, allow_failure=True) == (
        v4_cells_timing.Timing(Decimal(5025), 2154308, 1)
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "/usr/bin/time"),
        ("real\t0m 3.47s\n", "0 elapsed wall clock lines"),
        (gnu_time() + "\tExit status: 0\n", "2 exit status lines"),
    ],
    ids=["missing", "not-gnu-time", "two-exit-lines"],
)
def test_the_diagnose_timing_refuses_a_bad_time_file(tmp_path, capsys, text, message):
    code, out, err = diagnose(tmp_path, capsys, text)
    assert code == 1 and out == "" and message in err
    assert list((tmp_path / "diagnosis").iterdir()) == []


def test_the_diagnose_timing_needs_the_diagnosis_folder_and_never_replaces_it(tmp_path, capsys):
    code, out, err = diagnose(tmp_path, capsys, gnu_time(), folder=False)
    assert code == 1 and out == "" and "diagnose-timing.json" in err
    assert not (tmp_path / "diagnosis").exists()
    (tmp_path / "diagnosis").mkdir()
    (tmp_path / "diagnosis" / "diagnose-timing.json").write_text("earlier\n", encoding="ascii")
    code, out, err = diagnose(tmp_path, capsys, gnu_time(), folder=False)
    assert code == 1 and out == ""
    assert (tmp_path / "diagnosis" / "diagnose-timing.json").read_text() == "earlier\n"


def test_cell_dir_and_diagnosis_dir_are_one_or_the_other():
    parser = v4_cells_timing.build_parser()
    for argv in (
        ["--time-file", "t"],
        ["--time-file", "t", "--cell-dir", "c", "--diagnosis-dir", "d"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


# ---- the verdict step's own timing (v4-run.yml's verdict job) ----


def test_verdict_dir_writes_verdict_timing(tmp_path, capsys):
    """``--verdict-dir`` times the v4-run verdict job's verdict step as ``--diagnosis-dir`` times
    the diagnosis: ``<verdict dir>/verdict-timing.json`` with the step, the wall seconds, the
    peak memory and the exit status, in the folder the verdict made, never replacing a file. It
    is one of the three targets, never with another."""

    def verdict(text: str | None) -> tuple[int, str, str]:
        if text is not None:
            (tmp_path / "verdict.time").write_text(text, encoding="ascii")
        argv = ["--time-file", str(tmp_path / "verdict.time")]
        code = v4_cells_timing.main([*argv, "--verdict-dir", str(tmp_path / "verdict")])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    # The folder must exist: the verdict made it (a verdict that failed leaves none).
    code, out, err = verdict(REALISTIC)
    assert code == 1 and out == "" and "verdict-timing.json" in err
    assert not (tmp_path / "verdict").exists()

    (tmp_path / "verdict").mkdir()
    (tmp_path / "verdict" / "verdict.json").write_bytes(b"{}")  # the verdict's own files stay
    code, out, err = verdict(REALISTIC)
    assert (code, err) == (0, "")
    text = (tmp_path / "verdict" / v4_cells_timing.VERDICT_TIMING_FILE).read_text(encoding="ascii")
    assert v4_cells_timing.VERDICT_TIMING_FILE == "verdict-timing.json"
    assert json.loads(text) == {
        "step": "verdict",
        "wall_seconds": 5025.0,
        "peak_rss_mb": 2103.8,
        "exit_status": 0,
    }
    assert text.endswith("\n") and text.count("\n") == 1  # one canonical line
    # Times only: never a count of cells, an outcome or the verdict.
    assert out == "v4_cells_timing: verdict: 5025.00 s, 2103.8 MB peak, exit status 0\n"
    assert sorted(p.name for p in (tmp_path / "verdict").iterdir()) == [
        "verdict-timing.json",
        "verdict.json",
    ]

    # Never replaced.
    code, out, err = verdict(gnu_time())
    assert code == 1 and out == "" and "verdict-timing.json" in err
    assert (tmp_path / "verdict" / "verdict-timing.json").read_text(encoding="ascii") == text

    # A time file that is missing or not GNU time's writes nothing.
    (tmp_path / "verdict" / "verdict-timing.json").unlink()
    (tmp_path / "verdict.time").unlink()
    for bad in (None, "real\t0m 3.47s\n"):
        code, out, err = verdict(bad)
        assert code == 1 and out == "" and "::error::" in err, bad
        assert not (tmp_path / "verdict" / "verdict-timing.json").exists(), bad

    # One target of the three, never two.
    parser = v4_cells_timing.build_parser()
    args = parser.parse_args(["--time-file", "t", "--verdict-dir", "v"])
    assert (args.verdict_dir, args.diagnosis_dir, args.cell_dir) == (Path("v"), None, None)
    for other in (["--cell-dir", "c"], ["--diagnosis-dir", "d"], ["--expected-dir", "e"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["--time-file", "t", "--verdict-dir", "v", *other])
    capsys.readouterr()


# ---- the expected step's own timing (v4-run.yml's verdict job) ----


def test_expected_dir_writes_expected_timing_beside_the_verdicts(tmp_path, capsys):
    """``--expected-dir`` times the verdict job's ``expected`` step (``v4_run_plan.py expected``,
    which loads the whole data pack) as ``--verdict-dir`` times the verdict:
    ``<verdict dir>/expected-timing.json`` with the step, the wall seconds, the peak memory and
    the exit status, beside ``verdict-timing.json`` in the same folder, never replacing a file.
    It is one of the four targets, never with another."""

    def expected(text: str | None) -> tuple[int, str, str]:
        if text is not None:
            (tmp_path / "expected.time").write_text(text, encoding="ascii")
        argv = ["--time-file", str(tmp_path / "expected.time")]
        code = v4_cells_timing.main([*argv, "--expected-dir", str(tmp_path / "verdict")])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    # The folder must exist: the workflow makes it.
    code, out, err = expected(REALISTIC)
    assert code == 1 and out == "" and "expected-timing.json" in err
    assert not (tmp_path / "verdict").exists()

    (tmp_path / "verdict").mkdir()
    (tmp_path / "verdict" / "verdict-timing.json").write_bytes(b"{}\n")  # the verdict's stays
    code, out, err = expected(REALISTIC)
    assert (code, err) == (0, "")
    path = tmp_path / "verdict" / v4_cells_timing.EXPECTED_TIMING_FILE
    assert v4_cells_timing.EXPECTED_TIMING_FILE == "expected-timing.json"
    text = path.read_text(encoding="ascii")
    assert json.loads(text) == {
        "step": "expected",
        "wall_seconds": 5025.0,
        "peak_rss_mb": 2103.8,
        "exit_status": 0,
    }
    assert text.endswith("\n") and text.count("\n") == 1
    assert out == "v4_cells_timing: expected: 5025.00 s, 2103.8 MB peak, exit status 0\n"
    assert sorted(p.name for p in (tmp_path / "verdict").iterdir()) == [
        "expected-timing.json",
        "verdict-timing.json",
    ]
    assert (tmp_path / "verdict" / "verdict-timing.json").read_bytes() == b"{}\n"

    # Never replaced.
    code, out, err = expected(gnu_time())
    assert code == 1 and out == "" and "expected-timing.json" in err
    assert path.read_text(encoding="ascii") == text

    # One target of the four, never two.
    parser = v4_cells_timing.build_parser()
    args = parser.parse_args(["--time-file", "t", "--expected-dir", "v"])
    assert (args.expected_dir, args.verdict_dir, args.diagnosis_dir, args.cell_dir) == (
        Path("v"),
        None,
        None,
        None,
    )
    for other in (["--cell-dir", "c"], ["--diagnosis-dir", "d"], ["--verdict-dir", "v"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["--time-file", "t", "--expected-dir", "v", *other])
    capsys.readouterr()


@pytest.mark.parametrize(
    ("flag", "file_name", "step"),
    [
        ("--verdict-dir", "verdict-timing.json", "verdict"),
        ("--diagnosis-dir", "diagnose-timing.json", "diagnose"),
        ("--expected-dir", "expected-timing.json", "expected"),
    ],
)
def test_a_step_that_failed_or_was_killed_is_timed_with_its_status(
    tmp_path, capsys, flag, file_name, step
):
    """A timing run must not lose the run that failed (Ruling W2): a verdict, a diagnosis or an
    expected step that exited 1, or that was killed (out of memory: GNU time says "Exit status:
    0" then), is timed with its peak memory and a status that says so, 128 + the signal for a
    killed one (the status GNU time itself exits with)."""
    for text, status in ((REALISTIC_FAILED, 1), (REALISTIC_KILLED, 128 + 9)):
        folder = tmp_path / str(status)
        folder.mkdir()
        (tmp_path / "step.time").write_text(text, encoding="ascii")
        code = v4_cells_timing.main(["--time-file", str(tmp_path / "step.time"), flag, str(folder)])
        captured = capsys.readouterr()
        assert (code, captured.err) == (0, ""), status
        assert json.loads((folder / file_name).read_text(encoding="ascii")) == {
            "step": step,
            "wall_seconds": 5025.0,
            "peak_rss_mb": 2103.8,
            "exit_status": status,
        }
        assert captured.out == (
            f"v4_cells_timing: {step}: 5025.00 s, 2103.8 MB peak, exit status {status}\n"
        )


def test_signal_lines_are_read_once_and_refused_for_a_cell(tmp_path, capsys):
    killed = v4_cells_timing.parse_time_output(REALISTIC_KILLED, allow_failure=True)
    assert killed == v4_cells_timing.Timing(Decimal(5025), 2154308, 137)
    with pytest.raises(ValueError, match="2 terminating signal lines"):
        v4_cells_timing.parse_time_output(
            "Command terminated by signal 9\n" + REALISTIC_KILLED, allow_failure=True
        )
    # A cell's timing refuses a killed command, as a failed one, and writes nothing.
    folder = cell_folder(tmp_path)
    time_file(tmp_path, REALISTIC_KILLED)
    code, out, err = run(tmp_path, capsys)
    assert code == 1 and out == "" and "terminated by signal 9" in err
    assert not (folder / "timing.json").exists()
