"""The second minute-bars fetch (docs/tasks/2026-10-12-bob-v3-1-minute-bars-2020-fetch.md):
five coins, 2020-02 to 2021-05, run by the same script as the first, scripts/fetch_minute_bars.py.

tests/test_fetch_minute_bars.py still tests the script's run, with a synthetic spec, and the
first task. This file adds what the second task changes: its spec (80 archives, 160 requests),
the table of reviewed tasks that ``start`` checks (a task's text, and the spec that task
fetches), and the task file itself. Everything runs offline against a fake host with the
network blocked (the first file's ``no_network`` fixture). Nothing touches the network,
nothing is dated after 2024-12, and nothing here is market data or evidence.
"""

from __future__ import annotations

import contextlib
import io
import re
import subprocess  # nosec B404: pytest's own collection of the two files
import sys
from calendar import monthrange
from pathlib import Path

import pytest

from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import archive_path, load_manifest
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_full_range  # noqa: E402
import fetch_minute_bars  # noqa: E402
import test_fetch_minute_bars as first  # noqa: E402
from test_fetch_minute_bars import NOW, Host, no_network, refuse_network  # noqa: E402, F401

SPEC = fetch_minute_bars.SPEC_2020
TASK = fetch_minute_bars.TASK_2020
APPROVED = ("ADAUSDT", "BNBUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT")
FIRST_SPEC = fetch_minute_bars.SPEC
REPORT = "docs/reviews/2026-10-12-bob-v3-1-minute-bars-2020-fetch.md"
DATA_DIR = "data/v3-1-minute-bars-2020"


# --- the committed spec is the owner's approved scope ----------------------------------------


def test_the_committed_2020_spec_is_exactly_the_approved_fetch() -> None:
    assert SPEC.parent == first.DATASETS / "v3-1-minute-bars"  # not a backtest dataset spec
    spec = fetch_minute_bars.load_minute_spec(SPEC)
    assert spec.name == SPEC.stem == "v3-1-minute-bars-2020-2021"
    assert spec.purpose == "V3.1 extra reported-only window, flow gate"
    assert spec.symbols == APPROVED
    assert (spec.start, spec.end) == ("2020-02", "2021-05")
    months = spec.months(spec.start)
    assert (len(months), months[0], months[-1]) == (16, "2020-02", "2021-05")
    files = spec.required()
    assert len(files) == len(set(files)) == 5 * 16 == 80
    assert {interval for _, interval, _ in files} == {"1m"}
    assert max(month for _, _, month in files) == "2021-05"  # nothing at or after 2025-01
    assert spec.traded == () and spec.breadth_basket == ()  # bars only: no hourly, no filters
    assert "Nothing at or after 2025-01 is in scope" in SPEC.read_text(encoding="utf-8")


def test_the_2020_window_is_the_five_coins_months_before_the_first_fetchs_without_overlap() -> None:
    held = load_manifest(first.DATASETS / "full-range-2017-2024.manifest.json")["files"]
    have_minutes = {e["symbol"] for e in held if e.get("interval") == "1m"}
    assert have_minutes == {"BTCUSDT", "ETHUSDT", "XRPUSDT"}
    assert not have_minutes & set(APPROVED)  # these five have no minute bars yet
    earlier = fetch_minute_bars.load_minute_spec(SPEC)
    later = fetch_minute_bars.load_minute_spec(FIRST_SPEC)
    assert set(earlier.symbols) <= set(later.symbols)  # five of the first fetch's seven
    assert not set(earlier.required()) & set(later.required())
    for symbol in APPROVED:
        covered = [m for s, _, m in earlier.required() + later.required() if s == symbol]
        assert covered == earlier.months(earlier.start) + later.months(later.start)
        assert (covered[0], covered[-1], len(covered)) == ("2020-02", "2024-12", 59)
    # With the three held coins, 2020-03 on has all eight coins that had futures then.
    assert have_minutes | set(APPROVED) == {
        "BTCUSDT", "ETHUSDT", "XRPUSDT", *APPROVED,
    }  # fmt: skip


def test_the_2020_plan_lists_80_archives_and_their_checksums_and_nothing_else(
    tmp_path: Path,
) -> None:
    lines: list[str] = []
    args = fetch_minute_bars._parser().parse_args([str(tmp_path / "data"), "--spec", str(SPEC)])
    plan = fetch_minute_bars.make_plan(args, lines.append)
    assert len(plan.paths) == 160
    assert sum(path.endswith(".CHECKSUM") for path in plan.paths) == 80
    for path in plan.paths:
        assert re.fullmatch(
            r"/data/spot/monthly/klines/([A-Z]+)/1m/\1-1m-(2020-(0[2-9]|1[0-2])|2021-0[1-5])"
            r"\.zip(\.CHECKSUM)?",
            path,
        ), path
    assert plan.paths == {
        archive_path(s, "1m", m) + suffix
        for s, _, m in plan.spec.required()
        for suffix in ("", ".CHECKSUM")
    }
    assert (tmp_path / "data" / SPEC.name).read_bytes() == SPEC.read_bytes()
    symbols = ", ".join(APPROVED)
    assert lines[0].startswith(
        f"PLAN v3-1-minute-bars-2020-2021: 80 1m kline files, 5 symbols ({symbols}) x 16 "
        "months 2020-02..2021-05; spec "
    )
    assert lines[1].startswith(
        "PLAN latest month 2021-05; 160 planned paths: 80 archives and 80 .CHECKSUM, so 160 "
        "requests if nothing is retried or stored already; data dir "
    )
    assert len(lines) == 2


def test_requests_outside_the_2020_plan_are_refused(tmp_path: Path) -> None:
    args = fetch_minute_bars._parser().parse_args([str(tmp_path / "data"), "--spec", str(SPEC)])
    plan = fetch_minute_bars.make_plan(args, fetch_full_range.Log())
    reached: list[str] = []

    def host(path: str) -> bytes | None:
        reached.append(path)
        return None

    requests = fetch_full_range.Requests(host, plan.paths, lambda s: None, lambda line: None)
    refused = [
        archive_path("ADAUSDT", "1m", "2025-01"),  # the reserved window
        archive_path("ADAUSDT", "1m", "2025-01") + ".CHECKSUM",
        archive_path("ADAUSDT", "1m", "2021-06"),  # the first fetch's first month
        archive_path("ADAUSDT", "1m", "2020-01"),  # before this spec's first month
        archive_path("ADAUSDT", "1h", "2020-06"),  # an hourly archive
        archive_path("ADAUSDT", "1d", "2020-06"),  # a daily archive
        archive_path("BTCUSDT", "1m", "2020-06"),  # a coin whose minutes the project holds
        archive_path("SOLUSDT", "1m", "2021-03"),  # a coin of the first fetch, not this one
        archive_path("DOGEUSDT", "1m", "2021-03"),  # likewise
        "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-06.zip",
        "/data/futures/um/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-06.zip",  # the futures host
        "/data/spot/monthly/klines/ADAUSDT/1m/",  # a directory listing
        "/api/v3/exchangeInfo",
    ]
    for path in refused:
        with pytest.raises(fetch_full_range.OutOfScope):
            requests(path)
    assert reached == [] and requests.paths == []
    # The spec loader refuses the reserved window before a plan exists.
    late = tmp_path / "late.toml"
    late.write_text(
        SPEC.read_text(encoding="utf-8").replace('end = "2021-05"', 'end = "2025-01"'),
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="reserved window"):
        fetch_minute_bars.load_minute_spec(late)


def test_a_run_of_the_2020_spec_asks_for_exactly_its_160_paths_and_reads_a_leap_february(
    tmp_path: Path,
) -> None:
    """The committed 2020 spec through ``main``, against a fake host that publishes one
    archive, ADAUSDT's complete 2020-02 (a leap month: 29 days), and answers 404 for the other
    79 months: every planned path is asked for once, none other, and the digest rebuilds."""
    objects: dict[str, bytes] = {}
    name = "ADAUSDT-1m-2020-02.csv"
    body = first.zip_of((name, first.csv_text(first.minute_bars("2020-02", "10"))))
    first.serve(objects, archive_path("ADAUSDT", "1m", "2020-02"), body)
    host, sleeps, out = Host(objects, set(), set()), [], io.StringIO()
    data = tmp_path / "data"
    with pytest.MonkeyPatch.context() as patch, contextlib.redirect_stdout(out):
        for attribute in ("https_connection", "PublicClient", "exchange_filters", "archive_get"):
            patch.setattr(dataset, attribute, refuse_network)
        code = fetch_minute_bars.main(
            [str(data), "--spec", str(SPEC)],
            fetcher=host,
            sleep=sleeps.append,
            now=lambda: NOW,
        )
    lines = out.getvalue().splitlines()
    plan = fetch_minute_bars.make_plan(
        fetch_minute_bars._parser().parse_args([str(tmp_path / "again"), "--spec", str(SPEC)]),
        lambda line: None,
    )
    assert len(host.requests) == len(set(host.requests)) == 160  # each path once, no retry
    assert set(host.requests) == plan.paths
    assert sleeps == []
    assert max(re.findall(r"-(\d{4}-\d{2})\.zip", "".join(host.requests))) == "2021-05"
    (requests,) = [line for line in lines if line.startswith("REQUESTS ")]
    assert requests.startswith("REQUESTS 160 to data.binance.vision, 80 of them .CHECKSUM; ")
    assert "latest month 2021-05; after 2024-12: 0" in requests
    assert (data / "requests.txt").read_text(encoding="utf-8").splitlines() == host.requests
    # One complete month, 79 not published: a problem, as it would be for a real gap.
    assert code == 1
    assert "KLINES v3-1-minute-bars-2020-2021: 80 files; missing 79, ok 1; complete months 1" in (
        out.getvalue()
    )
    assert "VERIFY v3-1-minute-bars-2020-2021 valid: 80 files match the spec, and 1 local" in (
        out.getvalue()
    )
    # 2020-02 is a leap month (29 days of 1440 minutes), and the 16 months have 486 days.
    spec = fetch_minute_bars.load_minute_spec(SPEC)
    days = [monthrange(int(m[:4]), int(m[5:]))[1] for m in spec.months(spec.start)]
    assert (days[0], sum(days)) == (29, 486)
    (coverage,) = [line for line in lines if line.startswith("COVERAGE ADAUSDT: ")]
    assert coverage.endswith(f"; complete months 1; rows {29 * 1440} of {486 * 1440} expected")
    assert lines[-2].startswith("PROBLEM 79 archive(s) missing: ")
    assert lines[-1] == "RESULT 1 problem(s)"
    digest = (data / "v3-1-minute-bars-2020-2021.digest.txt").read_text(encoding="utf-8")
    rows = digest.splitlines()
    assert len(rows) == 2 + 80
    ok = [row for row in rows[2:] if " ok " in row]
    assert len(ok) == 1 and ok[0].startswith("ADAUSDT-1m-2020-02.zip ")
    assert ok[0].endswith(" full")  # 29 x 1440 minutes, all present
    assert sum(row.endswith(" missing") for row in rows[2:]) == 79
    assert "rebuilds the manifest byte for byte: True" in out.getvalue()


# --- start: a reviewed task text, and the spec that task fetches ------------------------------
# Each test that launches starts a real child of the script with its hidden --fake-run option,
# so the child sleeps briefly and exits instead of fetching anything: no network.


def test_the_table_of_reviewed_tasks_holds_both_tasks_with_their_specs() -> None:
    table = fetch_minute_bars.REVIEWED_TASKS
    assert table == {
        fetch_minute_bars.TASK.name: (fetch_minute_bars.TASK_SHA256, FIRST_SPEC),
        TASK.name: (fetch_minute_bars.TASK_2020_SHA256, SPEC),
    }
    assert TASK.name == "2026-10-12-bob-v3-1-minute-bars-2020-fetch.md"
    assert TASK.parent == fetch_minute_bars.TASK.parent == ROOT / "docs" / "tasks"
    for task, (digest, spec) in zip((fetch_minute_bars.TASK, TASK), table.values(), strict=True):
        assert fetch_full_range.task_digest(task) == digest, task.name
        assert spec.is_file() and spec.parent == SPEC.parent
    # The workflow starts only tasks named so (bob-task.yml).
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-bob-[a-z0-9-]+\.md", TASK.name)


def test_start_refuses_a_2020_task_text_that_is_not_the_reviewed_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = TASK.read_text(encoding="utf-8")
    data = tmp_path / "data"
    arguments = ["start", str(data), "--spec", str(SPEC), "--fake-run", "0.1"]

    def refused(task: Path) -> str:
        assert fetch_minute_bars.main([*arguments, "--task", str(task)]) == 1
        assert not data.exists()  # nothing written, nothing launched
        return capsys.readouterr().out

    edited = tmp_path / TASK.name
    edited.write_text(
        text.replace("## Stop conditions", "## Stop conditions\n\nGo on.", 1), encoding="utf-8"
    )
    out = refused(edited)
    assert out.startswith(f"NOT STARTED: the task file {TASK.name} is not the reviewed text")
    # The reviewed text under another name is no reviewed task either.
    other = tmp_path / "2026-10-12-bob-copy.md"
    other.write_text(text, encoding="utf-8")
    assert refused(other).startswith("NOT STARTED: the task file 2026-10-12-bob-copy.md is not")
    # The first fetch's task text is not the second's, whichever name it is given.
    impostor = tmp_path / "impostor" / TASK.name
    impostor.parent.mkdir()
    impostor.write_bytes(fetch_minute_bars.TASK.read_bytes())
    assert "is not the reviewed text" in refused(impostor)
    # A task file that is missing, or has no pin block, is a refusal and not a traceback.
    assert "cannot be read as a task" in refused(tmp_path / "missing.md")
    nopins = tmp_path / "nopins.md"
    nopins.write_text("# no pins here\n", encoding="utf-8")
    assert "cannot be read as a task" in refused(nopins)
    # A changed pin block (every new SHA-256 of a pinned file) leaves the text as it was.
    pin = re.compile(r"(?m)^[0-9a-f]{64}(  scripts/fetch_minute_bars\.py)$")
    assert pin.search(text)
    repinned = tmp_path / "repinned" / TASK.name
    repinned.parent.mkdir()
    repinned.write_text(pin.sub("f" * 64 + r"\1", text), encoding="utf-8")
    assert fetch_full_range.task_digest(repinned) == fetch_minute_bars.TASK_2020_SHA256


def test_start_refuses_a_spec_that_is_not_the_one_the_task_fetches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    fake = ["--fake-run", "0.1"]
    # The 2020 task with the first fetch's spec (the default), or with none named.
    assert fetch_minute_bars.main(["start", str(data), "--task", str(TASK), *fake]) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"NOT STARTED: the task file {TASK.name} fetches the spec {SPEC.name}")
    # The first task (the default) with the 2020 spec.
    assert fetch_minute_bars.main(["start", str(data), "--spec", str(SPEC), *fake]) == 1
    out = capsys.readouterr().out
    assert f"fetches the spec {FIRST_SPEC.name}, not " in out
    # The 2020 spec's text under another path, even with the same file name.
    copy = tmp_path / "copy" / SPEC.name
    copy.parent.mkdir()
    copy.write_bytes(SPEC.read_bytes())
    arguments = ["start", str(data), "--spec", str(copy), "--task", str(TASK), *fake]
    assert fetch_minute_bars.main(arguments) == 1
    assert "NOT STARTED" in capsys.readouterr().out
    assert not data.exists()  # none of these wrote anything or launched anything


def test_start_launches_the_2020_task_with_its_spec_and_wait_reports_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first.background(monkeypatch, 60)
    data = tmp_path / "data"
    arguments = [str(data), "--spec", str(SPEC), "--task", str(TASK), "--fake-run", "0.2"]
    assert fetch_minute_bars.main(["start", *arguments]) == 0
    pid = int((data / "run.pid").read_text(encoding="utf-8"))
    log, exit_file = (data / "run.log").as_posix(), (data / "run.exit").as_posix()
    assert capsys.readouterr().out == f"STARTED pid {pid}; log {log}; exit file {exit_file}\n"
    assert fetch_minute_bars.main(["wait", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (lines[0], lines[-2]) == ("DONE exit=0", "RESULT 0 problem(s)")
    assert lines[-1] == fetch_full_range.NEXT_DONE
    # A run that has ended is never started again in the same data dir.
    assert fetch_minute_bars.main(["start", *arguments]) == 1
    assert capsys.readouterr().out.startswith("NOT STARTED")


# --- the task file ---------------------------------------------------------------------------


@pytest.fixture
def second_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first file's task-file checks (commands, the pin-failure path), on this task."""
    monkeypatch.setattr(first, "TASK_FILE", TASK)


def test_the_2020_task_file_asks_bob_only_for_commands_his_prompt_allows(
    second_task: None,
) -> None:
    first.test_the_task_file_asks_bob_only_for_commands_his_prompt_allows()


def test_a_pin_failure_in_the_2020_task_runs_no_script(second_task: None) -> None:
    first.test_a_pin_failure_runs_no_script()


def test_the_2020_task_file_states_the_scope_and_the_pins_name_real_files() -> None:
    text = TASK.read_text(encoding="utf-8")
    # The scope table's numbers are the spec's, computed here.
    spec = fetch_minute_bars.load_minute_spec(SPEC)
    files = len(spec.required())
    for fact in (
        f"{files} archives",
        f"{2 * files} requests",
        f"{len(spec.symbols)} symbols x {len(spec.months(spec.start))} months",
        *spec.symbols,
        REPORT,
        SPEC.name,
        "2025-01",
    ):
        assert fact in text, fact
    block = text.split("## Pinned inputs", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    pinned = [line.split("  ", 1)[1] for line in block.splitlines()]
    assert pinned == [
        "scripts/fetch_minute_bars.py",
        "tests/test_fetch_minute_bars.py",
        "tests/test_fetch_minute_bars_2020.py",
        "scripts/fetch_full_range.py",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.toml",
    ]
    for path in pinned:
        assert (ROOT / path).is_file(), path
    assert all(re.fullmatch(r"[0-9a-f]{64}  \S+", line) for line in block.splitlines())
    assert f"`{len(pinned)} pins`" in text
    # The Step 3 count is the number of tests in the two files, as pytest collects them.
    result = subprocess.run(  # nosec B603: pytest's own collection of these two files
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         str(ROOT / "tests" / "test_fetch_minute_bars.py"), str(Path(__file__).resolve())],
        capture_output=True, text=True, check=False, cwd=ROOT,
    )  # fmt: skip
    counts = [int(n) for n in re.findall(r"^\S+\.py: (\d+)$", result.stdout, re.M)]
    if not counts:  # pytest's other output form, "N tests collected"
        collected = re.search(r"(\d+) tests? collected", result.stdout)
        assert collected, result.stdout
        counts = [int(collected.group(1))]
    count = sum(counts)
    assert f"`{count} passed`" in text


def test_the_2020_task_names_its_own_report_and_data_dir_and_nothing_of_the_first_fetchs() -> None:
    text = TASK.read_text(encoding="utf-8")
    reports = set(re.findall(r"docs/reviews/[0-9a-z-]+\.md", text))
    assert reports == {REPORT}  # no copy of the first task's report path survives
    assert not re.search(r"data/v3-1-minute-bars(?!-2020)", text)  # the first fetch's data dir
    # What a copy of the first task would leave behind.
    stale = (r"\b602\b", r"\b301 (archives|files|requests)", "43 months", "7 symbols", "24 passed")
    for pattern in (*stale, r"2021-2024\.toml"):
        assert not re.search(pattern, text), pattern
    # Every working file Bob names under data/ is this task's: its data dir, pins, tests log,
    # passages and checks.
    names = re.findall(r"(?<![\w/])data/[\w./-]+", text)
    assert sum(name.startswith(DATA_DIR) for name in names) >= 10, names
    ours = (DATA_DIR, "data/minute-bars-2020-", "data/mb20-")
    assert [name for name in names if not name.startswith(ours)] == []


def test_step_4_of_the_2020_task_starts_and_waits_in_the_data_dir_that_step_5_measures(
    second_task: None,
) -> None:
    commands = [" ".join(words) for _, words in first.task_commands()]
    start = (
        f"python scripts/fetch_minute_bars.py start {DATA_DIR} --spec "
        f"config/datasets/v3-1-minute-bars/{SPEC.name} --task docs/tasks/{TASK.name}"
    )
    assert commands.count(start) == 1
    assert f"python scripts/fetch_minute_bars.py wait {DATA_DIR}" in commands
    assert f"python scripts/fetch_minute_bars.py measure {DATA_DIR} data" in commands
    # The start command's two paths are the ones the script holds for this task.
    assert ROOT / f"config/datasets/v3-1-minute-bars/{SPEC.name}" == SPEC
    assert ROOT / f"docs/tasks/{TASK.name}" == TASK
