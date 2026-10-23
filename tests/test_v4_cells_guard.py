"""The v4-cells workflow's reserved-window guard (``scripts/v4_cells_guard.py``) on synthetic files.

Owner decision v4-d03: no market data from 2025-01 onward is executed before the registered run.
The guard reads one file, a data directory's ``data.json``, and refuses a data run whose
``end_month`` is after the latest allowed month, which is never later than 2024-12. These tests
write small ``data.json`` files into pytest's temporary folders. The data-run check (``--data-run``)
is tested on the JSON of a workflow run written here, never fetched. The tests never open the real
data packs (``E:`` and ``F:``), and the network is blocked for every test.
"""

from __future__ import annotations

import io
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cells_guard  # noqa: E402

# A config pin: the SHA-256 of a config file's bytes, not market data.
PIN = "58032f30391c7e66b239fe47e89b8f98e4a50ffbb33dc2d8a6b59f98b4d71b16"


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def data_json(**fields: object) -> bytes:
    document = {"format": "v4-data/1", "config_sha256": PIN, "end_month": "2024-12", **fields}
    return json.dumps(document).encode("ascii")


def write(folder: Path, content: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "data.json").write_bytes(content)
    return folder


def tree(folder: Path) -> list[tuple[str, bytes | None]]:
    """Every path under ``folder`` with its bytes (None for a folder): what 'no file written'
    compares."""
    return sorted(
        (str(path.relative_to(folder)), path.read_bytes() if path.is_file() else None)
        for path in folder.rglob("*")
    )


def guard(folder: Path, capsys, *extra: str) -> tuple[int, str, str]:
    code = v4_cells_guard.main(["--data", str(folder), *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_latest_allowed_month_is_2024_12():
    assert v4_cells_guard.LATEST_ALLOWED == "2024-12"


@pytest.mark.parametrize("end_month", ["2025-01", "2025-12", "2026-09"])
def test_guard_refuses_a_data_run_reaching_2025(tmp_path, capsys, end_month):
    folder = write(tmp_path / "v4data", data_json(end_month=end_month))
    before = tree(tmp_path)
    code, out, err = guard(folder, capsys)
    assert code == 1
    assert out == ""
    assert "refused" in err and end_month in err
    assert tree(tmp_path) == before  # nothing written, anywhere


@pytest.mark.parametrize("end_month", ["2024-12", "2024-11", "2024-01", "2018-01"])
def test_guard_accepts_2024_12_and_earlier(tmp_path, capsys, end_month):
    folder = write(tmp_path / "v4data", data_json(end_month=end_month))
    before = tree(tmp_path)
    code, out, err = guard(folder, capsys)
    assert code == 0
    assert err == ""
    assert out == (
        f"v4_cells_guard: data end_month {end_month}, config_sha256 {PIN}: "
        "accepted (latest allowed month 2024-12)\n"
    )
    assert tree(tmp_path) == before


def test_guard_prints_only_the_end_month_the_verdict_and_the_pin(tmp_path, capsys):
    # data.json also holds counts about the run; none of it is echoed.
    extra = {"hourly_rows": 987654321, "packs": {"daily": {"file": "daily.pack.json.gz"}}}
    folder = write(tmp_path / "v4data", data_json(**extra))
    code, out, err = guard(folder, capsys)
    assert code == 0 and err == ""
    assert out.count("\n") == 1
    assert "987654321" not in out and "daily.pack" not in out


@pytest.mark.parametrize("latest", ["2025-01", "2026-09", "2099-12"])
def test_guard_refuses_a_latest_month_after_2024_12(tmp_path, capsys, latest):
    # Even a data run that ends long before 2025 is refused when the ceiling asked for is
    # after 2024-12: the window cannot be widened from the command line.
    folder = write(tmp_path / "v4data", data_json(end_month="2024-06"))
    before = tree(tmp_path)
    code, out, err = guard(folder, capsys, "--latest-month", latest)
    assert code == 1
    assert out == ""
    assert "refused" in err and "2024-12" in err
    assert tree(tmp_path) == before


@pytest.mark.parametrize("latest", ["2024-13", "2024-00", "2024-1", "december", "", "2024-12 "])
def test_guard_refuses_a_malformed_latest_month(tmp_path, capsys, latest):
    folder = write(tmp_path / "v4data", data_json())
    code, out, err = guard(folder, capsys, "--latest-month", latest)
    assert code == 1 and out == "" and "refused" in err


def test_guard_takes_an_earlier_latest_month(tmp_path, capsys):
    folder = write(tmp_path / "v4data", data_json(end_month="2024-12"))
    code, out, err = guard(folder, capsys, "--latest-month", "2024-06")
    assert code == 1 and out == "" and "refused" in err and "2024-12" in err
    code, out, err = guard(folder, capsys, "--latest-month", "2024-12")
    assert code == 0 and "accepted" in out and err == ""
    folder = write(tmp_path / "earlier", data_json(end_month="2024-06"))
    code, out, err = guard(folder, capsys, "--latest-month", "2024-06")
    assert code == 0 and "accepted (latest allowed month 2024-06)" in out


BAD_DATA_JSON = {
    "invalid_json": b'{"format": "v4-data/1", ',
    "not_utf8": b"\xff\xfe{}",
    "not_an_object": b'["v4-data/1"]',
    "wrong_format": data_json(format="v4-data/2"),
    "missing_format": json.dumps({"config_sha256": PIN, "end_month": "2024-12"}).encode("ascii"),
    "missing_end_month": json.dumps({"format": "v4-data/1", "config_sha256": PIN}).encode("ascii"),
    "end_month_not_text": data_json(end_month=202412),
    "end_month_malformed": data_json(end_month="2024-13"),
    "end_month_short": data_json(end_month="2024-1"),
    "end_month_with_a_day": data_json(end_month="2024-12-31"),
    # A reader that takes the first duplicate would see 2024-12; one that takes the last, 2025-01.
    "duplicate_end_month": (
        b'{"format":"v4-data/1","config_sha256":"' + PIN.encode("ascii") + b'",'
        b'"end_month":"2024-12","end_month":"2025-01"}'
    ),
    "missing_config_pin": json.dumps({"format": "v4-data/1", "end_month": "2024-12"}).encode(
        "ascii"
    ),
    "config_pin_not_hex": data_json(config_sha256="not a pin\n::error::injected"),
    "config_pin_short": data_json(config_sha256=PIN[:-1]),
    "config_pin_upper": data_json(config_sha256=PIN.upper()),
}


@pytest.mark.parametrize("case", ["missing", *BAD_DATA_JSON])
def test_guard_refuses_bad_data_json(tmp_path, capsys, case):
    folder = tmp_path / "v4data"
    if case == "missing":
        folder.mkdir()
    else:
        write(folder, BAD_DATA_JSON[case])
    before = tree(tmp_path)
    code, out, err = guard(folder, capsys)
    assert code == 1
    assert out == ""
    assert "refused" in err
    assert "injected" not in err  # nothing from the file is echoed into the log
    assert tree(tmp_path) == before


def test_guard_refuses_a_data_folder_that_does_not_exist(tmp_path, capsys):
    code, out, err = guard(tmp_path / "nowhere", capsys)
    assert code == 1 and out == "" and "refused" in err


def test_guard_opens_only_data_json(tmp_path, capsys, monkeypatch):
    # The folder holds a pack the guard has no business reading.
    folder = write(tmp_path / "v4data", data_json())
    (folder / "daily.pack.json.gz").write_bytes(b"not read")
    opened: list[Path] = []
    original = Path.open

    def spy(self: Path, *args, **kwargs):
        opened.append(self)  # read_bytes and read_text both go through Path.open
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    code, _, _ = guard(folder, capsys)
    assert code == 0
    assert opened == [folder / "data.json"]


def test_the_default_latest_month_is_2024_12():
    args = v4_cells_guard.build_parser().parse_args(["--data", "v4data"])
    assert args.data == Path("v4data")
    assert args.latest_month == "2024-12"


# ---- the data run itself, checked before its artifact is downloaded ----

RUN_ID = "18734501234"


def run_json(**fields: object) -> dict[str, object]:
    """The fields of the GitHub API's workflow-run object that the check reads, as the API
    returns them for a successful run of the full stage with the pre-2025 config, among others
    it ignores (a real answer holds about a hundred)."""
    document: dict[str, object] = {
        "id": int(RUN_ID),
        "name": "v4-data",
        "display_title": "v4-data full config/v4_data_pre2025.json",
        "path": ".github/workflows/v4-data.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": "7653d7d" + "0" * 33,
        "run_attempt": 1,
        "html_url": f"https://github.com/owner/repo/actions/runs/{RUN_ID}",
    }
    document.update(fields)
    return document


def check_run(capsys, monkeypatch, raw: bytes, run_id: str = RUN_ID) -> tuple[int, str, str]:
    """``--data-run`` with ``raw`` on standard input, as ``gh api`` pipes it there."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    code = v4_cells_guard.main(["--data-run", run_id])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_data_run_check_accepts_the_pre2025_full_data_run():
    v4_cells_guard.check_data_run(run_json(), RUN_ID)
    assert v4_cells_guard.DATA_WORKFLOW_PATH == ".github/workflows/v4-data.yml"
    assert v4_cells_guard.DATA_RUN_TITLE == "v4-data full config/v4_data_pre2025.json"


def test_the_data_run_title_is_the_data_workflows_run_name_for_the_pre2025_full_stage():
    """The title the check wants is what the v4-data workflow's ``run-name`` makes of the full
    stage and the pre-2025 config, both among its inputs' choices."""
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/v4-data.yml").read_text(
        encoding="utf-8"
    )
    assert "\nrun-name: v4-data ${{ inputs.stage }} ${{ inputs.config }}\n" in workflow
    assert "          - full\n" in workflow
    assert "          - config/v4_data_pre2025.json\n" in workflow
    assert v4_cells_guard.DATA_RUN_TITLE == "v4-data full config/v4_data_pre2025.json"


REFUSED_RUNS = {
    # The full config's run: packs to 2026-09, the reserved window's data.
    "full_config": run_json(display_title="v4-data full config/v4_data.json"),
    "discover_stage": run_json(display_title="v4-data discover config/v4_data_pre2025.json"),
    "other_workflow": run_json(path=".github/workflows/v4-cells.yml"),
    # The API names a workflow's file alone (a real v4-data run's path was checked on
    # 2026-10-23); anything else is not that file.
    "workflow_at_a_ref": run_json(path=".github/workflows/v4-data.yml@refs/heads/main"),
    # The data workflow's runs before the config input existed: the full config's.
    "before_the_config_input": run_json(display_title="v4-data full"),
    "failed": run_json(conclusion="failure"),
    "cancelled": run_json(conclusion="cancelled"),
    "still_running": run_json(status="in_progress", conclusion=None),
    "no_conclusion": {k: v for k, v in run_json().items() if k != "conclusion"},
    "no_path": {k: v for k, v in run_json().items() if k != "path"},
    "no_title": {k: v for k, v in run_json().items() if k != "display_title"},
    "another_run": run_json(id=int(RUN_ID) + 1),
    "id_as_text": run_json(id=RUN_ID),
    "id_as_bool": run_json(id=True),
}


@pytest.mark.parametrize("case", REFUSED_RUNS)
def test_the_data_run_check_refuses_any_other_run(case):
    with pytest.raises(ValueError):
        v4_cells_guard.check_data_run(REFUSED_RUNS[case], RUN_ID)


@pytest.mark.parametrize("value", [None, [], "run", 18734501234])
def test_the_data_run_check_refuses_an_answer_that_is_not_an_object(value):
    with pytest.raises(ValueError, match="not a JSON object"):
        v4_cells_guard.check_data_run(value, RUN_ID)


@pytest.mark.parametrize("run_id", ["", "0", "012", "12a", "1" * 21, "-5", " 5"])
def test_the_data_run_check_refuses_a_malformed_run_id(run_id):
    with pytest.raises(ValueError, match="run id"):
        v4_cells_guard.check_data_run(run_json(), run_id)


def test_data_run_prints_only_the_run_id_and_the_verdict(capsys, monkeypatch):
    code, out, err = check_run(capsys, monkeypatch, json.dumps(run_json()).encode("ascii"))
    assert (code, err) == (0, "")
    assert out == (
        f"v4_cells_guard: data run {RUN_ID}: a successful "
        "'v4-data full config/v4_data_pre2025.json' run: accepted\n"
    )
    assert "7653d7d" not in out and "github.com" not in out


@pytest.mark.parametrize("case", REFUSED_RUNS)
def test_data_run_refuses_any_other_run_and_echoes_none_of_it(capsys, monkeypatch, case):
    document = {**REFUSED_RUNS[case], "head_branch": "::error::injected"}
    code, out, err = check_run(capsys, monkeypatch, json.dumps(document).encode("ascii"))
    assert code == 1 and out == ""
    (line,) = err.splitlines()
    assert line.startswith(f"::error::v4_cells_guard: data run {RUN_ID}: ")
    assert line.endswith(": refused")
    assert "injected" not in err and "v4_data.json" not in err and "failure" not in err


BAD_ANSWERS = {
    "empty": b"",  # gh api failed and wrote nothing
    "not_json": b'{"id": 18734501234, ',
    "not_utf8": b'{"id": 18734501234, "path": "\xff"}',
    "duplicate_conclusion": (
        json.dumps(run_json(conclusion="failure"))[:-1] + ', "conclusion": "success"}'
    ).encode("ascii"),
    "too_large": json.dumps(run_json(padding="x" * 1_000_000)).encode("ascii"),
}


def test_data_run_reads_an_answer_with_free_text_in_utf8(capsys, monkeypatch):
    """The API's answer is UTF-8 JSON with free text in it, a commit message among it."""
    message = "v4 cells: Codex → Claude, déjà vu"
    raw = json.dumps(run_json(head_commit={"message": message}), ensure_ascii=False).encode("utf-8")
    assert not raw.isascii()
    code, out, err = check_run(capsys, monkeypatch, raw)
    assert (code, err) == (0, "") and "accepted" in out and "Codex" not in out


@pytest.mark.parametrize("case", BAD_ANSWERS)
def test_data_run_refuses_an_answer_that_is_not_one_runs_json(capsys, monkeypatch, case):
    code, out, err = check_run(capsys, monkeypatch, BAD_ANSWERS[case])
    assert code == 1 and out == ""
    assert err.count("\n") == 1 and "refused" in err and RUN_ID in err


def test_data_run_never_shows_a_malformed_run_id(capsys, monkeypatch):
    raw = json.dumps(run_json()).encode("ascii")
    code, out, err = check_run(capsys, monkeypatch, raw, run_id="12\n::error::injected")
    assert code == 1 and out == ""
    assert "injected" not in err and "(not a run id)" in err


def test_data_run_and_data_are_one_or_the_other():
    parser = v4_cells_guard.build_parser()
    assert parser.parse_args(["--data-run", RUN_ID]).data_run == RUN_ID
    assert parser.parse_args(["--data-run", RUN_ID]).data is None
    for argv in ([], ["--data", "v4data", "--data-run", RUN_ID]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
