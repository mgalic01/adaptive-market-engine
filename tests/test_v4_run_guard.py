"""The v4-run workflow's data guard (``scripts/v4_run_guard.py``) on synthetic files.

Owner decision v4-d03: no market data from 2025-01 onward is executed before the registered run.
``v4_cells_guard`` enforces that for the diagnostic workflow; this guard is the registered run's:
the one place where 2025+ data is opened, and only the registered data, the data whose pins equal
the run manifest's (Ruling G5). The rehearsal and timing modes run on synthetic worlds only, and
the guard's synthetic mode refuses everything else. These tests write small ``data.json`` files,
config files and manifests into pytest's temporary folders, and the data run's JSON is written
here, never fetched. The tests never open the real data packs (``E:`` and ``F:``), and the network
is blocked for every test.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.synthetic import CONFIG_SHA256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_cells_guard  # noqa: E402
import v4_run_guard  # noqa: E402
from v4_registration import read_manifest  # noqa: E402


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


# ---- the registered data: files, pins and manifests -------------------------------------------

CONFIG_PATH = "config/v4_data.json"
CONFIG_BYTES = b'{"end_month": "2026-09", "note": "the registered data config"}\n'
PIN = hashlib.sha256(CONFIG_BYTES).hexdigest()
DAILY = "1" * 64
INDEX = "2" * 64
END_MONTH = "2026-09"
V3_PACK = "3" * 64
OTHER = "f" * 64  # a pin that is none of the above

# The pre-2025 config's pin: the diagnostic data run's, which no registered run may use.
PRE2025_PIN = hashlib.sha256((ROOT / "config" / "v4_data_pre2025.json").read_bytes()).hexdigest()

DATA_PINS = {
    "config_sha256": PIN,
    "end_month": END_MONTH,
    "daily_sha256": DAILY,
    "index_sha256": INDEX,
}


def data_json(**fields: object) -> bytes:
    """A ``data.json`` as the v4-data workflow writes it (it holds counts too, none of them
    echoed), with ``fields`` replacing what they name."""
    document: dict[str, object] = {
        "format": "v4-data/1",
        "config_sha256": PIN,
        "end_month": END_MONTH,
        "packs": {
            "daily": {"file": "daily.pack.json.gz", "sha256": DAILY, "json_bytes": 11},
            "hourly_index": {"file": "hourly-index.json.gz", "sha256": INDEX, "json_bytes": 12},
        },
        "hourly_rows": 987654321,
    }
    document.update(fields)
    return json.dumps(document, indent=1, sort_keys=True).encode("ascii")


def packs(daily: object = DAILY, index: object = INDEX) -> dict[str, object]:
    return {"daily": {"sha256": daily}, "hourly_index": {"sha256": index}}


def manifest_bytes(**data: str) -> bytes:
    fields = {"config_path": CONFIG_PATH, "config_sha256": PIN, "end_month": END_MONTH}
    fields |= {"daily_sha256": DAILY, "index_sha256": INDEX, **data}
    return _canonical({"schema": "v4-run-manifest-1", "data": fields, "v3_pack_sha256": V3_PACK})


def write_data(folder: Path, content: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "data.json").write_bytes(content)
    return folder


def write_repo(folder: Path, config: bytes = CONFIG_BYTES) -> Path:
    """A checkout holding the manifest's config file."""
    target = folder / CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(config)
    return folder


@dataclass
class Registered:
    """One registered run's files: the data directory, the checkout and the manifest file, all
    under ``root``."""

    root: Path
    data: Path
    repo: Path
    manifest: Path


@pytest.fixture
def registered(tmp_path) -> Registered:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(manifest_bytes())
    return Registered(
        tmp_path,
        write_data(tmp_path / "v4data", data_json()),
        write_repo(tmp_path / "repo"),
        manifest,
    )


def tree(folder: Path) -> list[tuple[str, bytes | None]]:
    """Every path under ``folder`` with its bytes (None for a folder): what 'no file written'
    compares."""
    return sorted(
        (str(path.relative_to(folder)), path.read_bytes() if path.is_file() else None)
        for path in folder.rglob("*")
    )


def guard(capsys, *argv: object) -> tuple[int, str, str]:
    code = v4_run_guard.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def registered_argv(run: Registered) -> list[object]:
    return ["--data", run.data, "--manifest", run.manifest, "--repo", run.repo]


def assert_one_refusal(code: int, out: str, err: str) -> str:
    """Exit 1, nothing on standard output, one ``::error::`` line on standard error."""
    assert code == 1 and out == ""
    assert err.count("\n") == 1 and err.endswith(": refused\n")
    assert err.startswith("::error::v4_run_guard: ")
    return err


# ---- the registered data ---------------------------------------------------------------------


def test_run_guard_accepts_the_manifests_pins(registered, capsys):
    """data.json's four pins equal the manifest's, and the config file hashes to the pin: the
    run's data is accepted even though it ends in 2026-09. The line carries the end month and
    the config pin, and nothing else of data.json."""
    before = tree(registered.root)
    code, out, err = guard(capsys, *registered_argv(registered))
    assert (code, err) == (0, "")
    assert out == (
        f"v4_run_guard: data end_month {END_MONTH}, config_sha256 {PIN}: "
        "accepted (registered pins)\n"
    )
    assert "987654321" not in out and DAILY not in out and INDEX not in out
    assert tree(registered.root) == before  # nothing written, anywhere


def test_run_guard_checks_return_the_pins_they_checked(registered):
    manifest = read_manifest(manifest_bytes())
    found = v4_run_guard.check_registered_data(registered.data, manifest, registered.repo)
    assert found == DATA_PINS
    synthetic = write_data(registered.root / "synthetic", data_json(config_sha256=CONFIG_SHA256))
    assert v4_run_guard.check_synthetic_data(synthetic) == {
        **DATA_PINS,
        "config_sha256": CONFIG_SHA256,
    }


def test_run_guard_has_no_latest_month_bound():
    """The registered run is where 2025+ data is opened (v4-d03): the cells guard's
    --latest-month bound does not exist here."""
    parser = v4_run_guard.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--data", "d", "--manifest", "m", "--latest-month", "2024-12"])
    assert not hasattr(v4_run_guard, "LATEST_ALLOWED")


PIN_CHANGES = {
    "config_sha256": {"config_sha256": OTHER},
    "end_month": {"end_month": "2026-08"},
    "daily_sha256": {"packs": packs(daily=OTHER)},
    "index_sha256": {"packs": packs(index=OTHER)},
}


@pytest.mark.parametrize("key", PIN_CHANGES)
def test_run_guard_refuses_other_pins(registered, capsys, key):
    """Each of the four pins of data.json, changed in turn, is refused: the data is then not
    the manifest's. The line names the key and echoes no value."""
    write_data(registered.data, data_json(**PIN_CHANGES[key]))
    before = tree(registered.root)
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert key in err and OTHER not in err and "2026-08" not in err
    assert tree(registered.root) == before


@pytest.mark.parametrize("key", PIN_CHANGES)
def test_run_guard_refuses_a_manifest_of_other_pins(registered, capsys, key):
    """The same four pins changed in the manifest instead: still not the same data."""
    other = {"config_sha256": OTHER, "end_month": "2026-08"}
    other |= {"daily_sha256": OTHER, "index_sha256": OTHER}
    registered.manifest.write_bytes(manifest_bytes(**{key: other[key]}))
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert key in err


def test_run_guard_registered_refuses_synthetic_data_whatever_the_manifest(registered, capsys):
    """A second line of defence: data whose config_sha256 is the synthetic worlds' pin is refused
    with --manifest even when the manifest names exactly those pins and the config file hashes to
    the pin (b"v4 synthetic world" does). Without the guard's own check this would be accepted:
    only the verdict job's expected file would refuse it, after the cells ran."""
    synthetic_config = b"v4 synthetic world"
    assert hashlib.sha256(synthetic_config).hexdigest() == CONFIG_SHA256
    write_data(registered.data, data_json(config_sha256=CONFIG_SHA256))
    registered.manifest.write_bytes(manifest_bytes(config_sha256=CONFIG_SHA256))
    write_repo(registered.repo, synthetic_config)
    before = tree(registered.root)
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert "synthetic" in err and "config_sha256" in err and CONFIG_SHA256 not in err
    assert tree(registered.root) == before
    manifest = read_manifest(registered.manifest.read_bytes())
    with pytest.raises(ValueError, match="synthetic"):
        v4_run_guard.check_registered_data(registered.data, manifest, registered.repo)


def test_run_guard_refuses_a_config_file_with_another_hash(registered, capsys):
    """The pins agree, but the config file of the checkout is not the one data.json was made
    from: its bytes hash to another value."""
    write_repo(registered.repo, CONFIG_BYTES + b" ")
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert CONFIG_PATH in err and "config_sha256" in err


def test_run_guard_refuses_a_config_file_it_cannot_read(registered, capsys):
    (registered.repo / CONFIG_PATH).unlink()
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert CONFIG_PATH in err and "FileNotFoundError" in err


def test_run_guard_reads_the_config_file_from_the_repo_given(registered, tmp_path, capsys):
    """--repo defaults to the current folder, as in the workflow's checkout."""
    (tmp_path / "elsewhere").mkdir()
    argv = ["--data", registered.data, "--manifest", registered.manifest]
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(tmp_path / "elsewhere")  # no config file here
        err = assert_one_refusal(*guard(capsys, *argv))
        assert CONFIG_PATH in err and "FileNotFoundError" in err
        patch.chdir(registered.repo)
        code, out, err = guard(capsys, *argv)
    assert (code, err) == (0, "") and "accepted (registered pins)" in out


BAD_MANIFESTS = {
    "missing": None,
    "not_json": b"{",
    "not_canonical": json.dumps(json.loads(manifest_bytes()), indent=1).encode("ascii"),
    "another_schema": manifest_bytes().replace(b"v4-run-manifest-1", b"v4-run-manifest-0"),
    "no_data": _canonical({"schema": "v4-run-manifest-1", "v3_pack_sha256": V3_PACK}),
}


@pytest.mark.parametrize("case", BAD_MANIFESTS)
def test_run_guard_refuses_a_manifest_that_does_not_read(registered, capsys, case):
    if BAD_MANIFESTS[case] is None:
        registered.manifest.unlink()
    else:
        registered.manifest.write_bytes(BAD_MANIFESTS[case])
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert "manifest" in err.lower()


def test_a_refusal_is_one_line_whatever_the_message(registered, capsys, monkeypatch):
    """No message, a library's included, can start a second line (``::error::`` commands)."""

    def failing(raw: bytes) -> None:
        raise ValueError("first\n::error::second\r\nthird")

    monkeypatch.setattr(v4_run_guard, "read_manifest", failing)
    err = assert_one_refusal(*guard(capsys, *registered_argv(registered)))
    assert err == "::error::v4_run_guard: first ::error::second third: refused\n"


# ---- data.json itself --------------------------------------------------------------------------

BAD_DATA_JSON = {
    "invalid_json": b'{"format": "v4-data/1", ',
    "not_ascii": b"\xff\xfe{}",
    "not_an_object": b'["v4-data/1"]',
    "wrong_format": data_json(format="v4-data/2"),
    "missing_format": json.dumps(
        {"config_sha256": PIN, "end_month": END_MONTH, "packs": packs()}
    ).encode("ascii"),
    "end_month_not_text": data_json(end_month=202609),
    "end_month_malformed": data_json(end_month="2026-13"),
    "end_month_with_a_day": data_json(end_month="2026-09-30"),
    "missing_end_month": json.dumps(
        {"format": "v4-data/1", "config_sha256": PIN, "packs": packs()}
    ).encode("ascii"),
    "config_pin_not_hex": data_json(config_sha256="not a pin\n::error::injected"),
    "config_pin_short": data_json(config_sha256=PIN[:-1]),
    "config_pin_upper": data_json(config_sha256=PIN.upper()),
    "missing_config_pin": json.dumps(
        {"format": "v4-data/1", "end_month": END_MONTH, "packs": packs()}
    ).encode("ascii"),
    "no_packs": json.dumps(
        {"format": "v4-data/1", "config_sha256": PIN, "end_month": END_MONTH}
    ).encode("ascii"),
    "packs_not_an_object": data_json(packs=[DAILY, INDEX]),
    "no_daily_pack": data_json(packs={"hourly_index": {"sha256": INDEX}}),
    "no_index_pack": data_json(packs={"daily": {"sha256": DAILY}}),
    "pack_not_an_object": data_json(packs={"daily": DAILY, "hourly_index": {"sha256": INDEX}}),
    "daily_pin_not_hex": data_json(packs=packs(daily="x\n::error::injected")),
    "index_pin_short": data_json(packs=packs(index=INDEX[:-1])),
    "daily_pin_not_text": data_json(packs=packs(daily=5)),
    # A reader taking the first duplicate would see the manifest's month; one taking the last, not.
    "duplicate_end_month": (
        b'{"format":"v4-data/1","config_sha256":"' + PIN.encode("ascii") + b'",'
        b'"end_month":"2026-09","end_month":"2026-08","packs":'
        + json.dumps(packs()).encode("ascii")
        + b"}"
    ),
}


@pytest.mark.parametrize("mode", ["manifest", "synthetic"])
@pytest.mark.parametrize("case", ["missing", "no_folder", *BAD_DATA_JSON])
def test_run_guard_refuses_bad_data_json(registered, capsys, mode, case):
    if case == "missing":
        (registered.data / "data.json").unlink()
    elif case == "no_folder":
        registered.data = registered.root / "nowhere"
    else:
        write_data(registered.data, BAD_DATA_JSON[case])
    if mode == "manifest":
        argv = registered_argv(registered)
    else:
        argv = ["--data", registered.data, "--synthetic"]
    before = tree(registered.root)
    err = assert_one_refusal(*guard(capsys, *argv))
    assert "injected" not in err  # nothing from the file is echoed into the log
    assert tree(registered.root) == before


def test_run_guard_opens_data_json_and_the_config_file_only(registered, capsys, monkeypatch):
    # The folder holds a pack the guard has no business reading.
    (registered.data / "daily.pack.json.gz").write_bytes(b"not read")
    opened: list[Path] = []
    original = Path.open

    def spy(self: Path, *args, **kwargs):
        opened.append(self)  # read_bytes and read_text both go through Path.open
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    code, _, _ = guard(capsys, *registered_argv(registered))
    assert code == 0
    assert sorted(opened) == sorted(
        [registered.data / "data.json", registered.manifest, registered.repo / CONFIG_PATH]
    )


# ---- synthetic worlds --------------------------------------------------------------------------


def test_run_guard_synthetic_accepts_only_the_synthetic_pin(tmp_path, capsys):
    """A rehearsal or timing world carries ``CONFIG_SHA256``, which no real config file hashes
    to. The real pre-2025 config's pin, and the registered config's, are refused: a real data
    run never passes for a synthetic one."""
    world = write_data(tmp_path / "world", data_json(config_sha256=CONFIG_SHA256))
    code, out, err = guard(capsys, "--data", world, "--synthetic")
    assert (code, err) == (0, "")
    assert out == (
        f"v4_run_guard: data end_month {END_MONTH}, config_sha256 {CONFIG_SHA256}: "
        "accepted (synthetic world)\n"
    )
    for pin in (PRE2025_PIN, PIN, OTHER):
        real = write_data(tmp_path / f"real-{pin[:6]}", data_json(config_sha256=pin))
        before = tree(tmp_path)
        err = assert_one_refusal(*guard(capsys, "--data", real, "--synthetic"))
        assert "synthetic" in err and pin not in err
        assert tree(tmp_path) == before


def test_run_guard_synthetic_has_no_month_bound(tmp_path, capsys):
    """A synthetic world may reach any month: it holds no market data."""
    world = write_data(
        tmp_path / "world", data_json(config_sha256=CONFIG_SHA256, end_month="2025-02")
    )
    code, out, err = guard(capsys, "--data", world, "--synthetic")
    assert (code, err) == (0, "") and "data end_month 2025-02," in out


def test_the_pre2025_config_pin_is_the_diagnostic_runs():
    """The pin refused above is the checked-in pre-2025 config's, the one
    ``v4_cells_guard``'s tests pin."""
    assert PRE2025_PIN == "58032f30391c7e66b239fe47e89b8f98e4a50ffbb33dc2d8a6b59f98b4d71b16"


# ---- the command line --------------------------------------------------------------------------


def test_data_needs_a_manifest_or_the_synthetic_flag(registered, capsys):
    err = assert_one_refusal(*guard(capsys, "--data", registered.data))
    assert "--manifest" in err and "--synthetic" in err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--data", "d", "--data-run", "5"],
        ["--data", "d", "--manifest", "m", "--synthetic"],
    ],
)
def test_the_options_that_exclude_each_other(argv):
    with pytest.raises(SystemExit):
        v4_run_guard.build_parser().parse_args(argv)


def test_the_options_that_go_with_one_mode_only(registered, capsys):
    synthetic_repo = ["--data", registered.data, "--synthetic", "--repo", registered.repo]
    err = assert_one_refusal(*guard(capsys, *synthetic_repo))
    assert "--repo" in err
    commit = ["--data", registered.data, "--synthetic", "--commit", "a" * 40]
    err = assert_one_refusal(*guard(capsys, *commit))
    assert "--commit" in err
    for extra in (["--synthetic"], ["--manifest", registered.manifest], ["--repo", "."]):
        err = assert_one_refusal(*guard(capsys, "--data-run", RUN_ID, "--commit", HEAD, *extra))
        assert "--data-run" in err


# ---- the data run itself, checked before its artifact is downloaded ---------------------------

RUN_ID = "40123456789"
# The commit the run checked out (github.sha), which the data run's head_sha must be.
HEAD = "cafe0d1" + "0" * 33
OTHER_COMMIT = "a" * 40


def run_json(**fields: object) -> dict[str, object]:
    """The fields of the GitHub API's workflow-run object that the check reads, as the API
    returns them for a successful run of the full stage with the full config."""
    document: dict[str, object] = {
        "id": int(RUN_ID),
        "name": "v4-data",
        "display_title": "v4-data full config/v4_data.json",
        "path": ".github/workflows/v4-data.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": HEAD,
        "run_attempt": 1,
    }
    document.update(fields)
    return document


def check_run(
    capsys, monkeypatch, raw: bytes, run_id: str = RUN_ID, head: str = HEAD
) -> tuple[int, str, str]:
    """``--data-run`` with ``raw`` on standard input, as ``gh api`` pipes it there."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    code = v4_run_guard.main(["--data-run", run_id, "--commit", head])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_full_data_run_title_is_the_data_workflows_run_name_for_the_full_stage():
    """The title the check wants is what the v4-data workflow's ``run-name`` makes of the full
    stage and the full config, both among its inputs' choices."""
    workflow = (ROOT / ".github/workflows/v4-data.yml").read_text(encoding="utf-8")
    assert "\nrun-name: v4-data ${{ inputs.stage }} ${{ inputs.config }}\n" in workflow
    assert "          - full\n" in workflow
    assert "          - config/v4_data.json\n" in workflow
    assert v4_run_guard.FULL_DATA_RUN_TITLE == "v4-data full config/v4_data.json"


REFUSED_RUNS = {
    "another_title": run_json(display_title="v4-data full config/v4_data_pre2025.json"),
    "discover_stage": run_json(display_title="v4-data discover config/v4_data.json"),
    "failed": run_json(conclusion="failure"),
    "cancelled": run_json(conclusion="cancelled"),
    "still_running": run_json(status="in_progress", conclusion=None),
    "another_head_sha": run_json(head_sha=OTHER_COMMIT),
    "no_head_sha": {k: v for k, v in run_json().items() if k != "head_sha"},
    "other_workflow": run_json(path=".github/workflows/v4-cells.yml"),
    "another_run": run_json(id=int(RUN_ID) + 1),
}


def test_full_data_run_check():
    """The right title is accepted; another title, a failed conclusion and another head_sha are
    refused (``check_data_run`` with the full title; the command line is tested below)."""
    title = v4_run_guard.FULL_DATA_RUN_TITLE
    v4_cells_guard.check_data_run(run_json(), RUN_ID, HEAD, title=title)
    for other in (
        {"display_title": v4_cells_guard.DATA_RUN_TITLE},
        {"display_title": "v4-data discover config/v4_data.json"},
        {"conclusion": "failure"},
        {"head_sha": OTHER_COMMIT},
    ):
        with pytest.raises(ValueError):
            v4_cells_guard.check_data_run(run_json(**other), RUN_ID, HEAD, title=title)


def test_the_cells_guards_default_title_is_unchanged():
    """With no title the check is the diagnostic workflow's: the pre-2025 run, not the full one."""
    pre2025 = run_json(display_title=v4_cells_guard.DATA_RUN_TITLE)
    v4_cells_guard.check_data_run(pre2025, RUN_ID, HEAD)
    with pytest.raises(
        ValueError, match="it is not the run named 'v4-data full config/v4_data_pre"
    ):
        v4_cells_guard.check_data_run(run_json(), RUN_ID, HEAD)
    with pytest.raises(ValueError, match="it is not the run named 'v4-data full config/v4_data.js"):
        v4_cells_guard.check_data_run(pre2025, RUN_ID, HEAD, title=v4_run_guard.FULL_DATA_RUN_TITLE)


def test_data_run_accepts_the_full_data_run_of_this_commit(capsys, monkeypatch):
    code, out, err = check_run(capsys, monkeypatch, json.dumps(run_json()).encode("ascii"))
    assert (code, err) == (0, "")
    assert out == (
        f"v4_run_guard: data run {RUN_ID}: a successful "
        "'v4-data full config/v4_data.json' run of this commit: accepted\n"
    )
    assert "cafe0d1" not in out and "github.com" not in out


@pytest.mark.parametrize("case", REFUSED_RUNS)
def test_data_run_refuses_any_other_run_and_echoes_none_of_it(capsys, monkeypatch, case):
    document = {**REFUSED_RUNS[case], "head_branch": "::error::injected"}
    code, out, err = check_run(capsys, monkeypatch, json.dumps(document).encode("ascii"))
    err = assert_one_refusal(code, out, err)
    assert err.startswith(f"::error::v4_run_guard: data run {RUN_ID}: ")
    assert "injected" not in err and "failure" not in err and OTHER_COMMIT not in err


def test_data_run_refuses_the_pre2025_data_run(capsys, monkeypatch):
    """The diagnostic data run (pre-2025 config) is not the registered run's data."""
    document = run_json(display_title=v4_cells_guard.DATA_RUN_TITLE)
    code, out, err = check_run(capsys, monkeypatch, json.dumps(document).encode("ascii"))
    assert_one_refusal(code, out, err)


BAD_ANSWERS = {
    "empty": b"",  # gh api failed and wrote nothing
    "not_json": b'{"id": 40123456789, ',
    "not_utf8": b'{"id": 40123456789, "path": "\xff"}',
    "not_an_object": b"[]",
    "duplicate_conclusion": (
        json.dumps(run_json(conclusion="failure"))[:-1] + ', "conclusion": "success"}'
    ).encode("ascii"),
    "too_large": json.dumps(run_json(padding="x" * 1_000_000)).encode("ascii"),
}


@pytest.mark.parametrize("case", BAD_ANSWERS)
def test_data_run_refuses_an_answer_that_is_not_one_runs_json(capsys, monkeypatch, case):
    err = assert_one_refusal(*check_run(capsys, monkeypatch, BAD_ANSWERS[case]))
    assert RUN_ID in err


def test_data_run_reads_an_answer_with_free_text_in_utf8(capsys, monkeypatch):
    """The API's answer is UTF-8 JSON with free text in it, a commit message among it."""
    message = "v4 run: Codex → Claude, déjà vu"
    raw = json.dumps(run_json(head_commit={"message": message}), ensure_ascii=False).encode("utf-8")
    code, out, err = check_run(capsys, monkeypatch, raw)
    assert (code, err) == (0, "") and "accepted" in out and "Codex" not in out


def test_data_run_never_shows_a_malformed_run_id_or_commit(capsys, monkeypatch):
    raw = json.dumps(run_json()).encode("ascii")
    err = assert_one_refusal(*check_run(capsys, monkeypatch, raw, run_id="12\n::error::injected"))
    assert "injected" not in err and "(not a run id)" in err
    err = assert_one_refusal(*check_run(capsys, monkeypatch, raw, head="cafe0d1"))
    assert "40 lowercase hex" in err


def test_data_run_needs_a_commit(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8"))
    err = assert_one_refusal(*guard(capsys, "--data-run", RUN_ID))
    assert "--commit" in err
