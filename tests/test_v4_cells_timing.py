"""The v4-cells workflow's timing helper (``scripts/v4_cells_timing.py``) on fabricated GNU
``time -v`` output and synthetic cell folders.

Each cell job runs ``v4_cell.py`` under ``/usr/bin/time -v -o out/<cell>.time``. The helper turns
that file and the cell's ``records.jsonl`` into ``out/<cell>/timing.json``: the wall seconds, the
peak resident memory in MB and the records file's size in bytes. These are the numbers the spec's
timing run needs. Nothing here reads market data.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

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
