"""V4 step 4b task 8: the run workflow's plan (``scripts/v4_run_plan.py``) and its status record
(``scripts/v4_run_status.py``).

The plan job's ``matrix`` writes the two job matrices, and the verdict job's ``expected`` writes the
expected file ``scripts/v4_verdict.py`` judges the cells against (``verdict.inputs.read_expected``
reads it back). The status job's script turns ``toJSON(needs)`` into ``status.json``. Every test
runs on small synthetic worlds written into pytest's temporary folders (three months of one coin),
never a real pack and never the real-size worlds; the network is blocked for every test.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import socket
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine import run
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec, all_cells
from crypto_grid_bot.v4.engine.market import HOUR_MS, Market
from crypto_grid_bot.v4.synthetic import (
    CoinSpec,
    Series,
    World,
    every_month,
    month_start,
    path,
    write_world,
)
from crypto_grid_bot.v4.verdict.inputs import (
    EXPECTED_FORMAT,
    MODES,
    Expected,
    expected_cells,
    expected_record,
    read_expected,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cells_plan  # noqa: E402
import v4_run_plan  # noqa: E402
import v4_run_status  # noqa: E402
from v4_registration import (  # noqa: E402
    PLAN_JOB,
    SKIPPED_JOBS,
    SKIPPED_MATRIX_JOBS,
    read_manifest,
)
from v4_rehearsal import WORLD_FILE, WORLD_FORMAT  # noqa: E402


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


V3_PIN = sha("a synthetic v3 pack")
PICKS = sha("a synthetic set of v3 picks")
REGISTRATION = sha("a synthetic registration")
OTHER = sha("some other pin")
NON_V3 = tuple(cell.cell_id for cell in all_cells() if ARMS[cell.arm].family != "v3")


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in [
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ]:
        monkeypatch.setattr(owner, name, _refuse)


def run_cli(module: ModuleType, argv: Sequence[str]) -> tuple[int, str, str]:
    """``module.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# ---- a small synthetic world and the files that name it ---------------------------------------


def small_world() -> World:
    """Three months of one coin (2,160 hourly rows): a world a test writes in a moment."""
    btc = CoinSpec("BTCUSDT", Series(month_start("2025-01"), path("100", (24 * 90, "0.0002"))))
    return World("2025-03", (btc,), every_month("2025-01", "2025-03", ("BTCUSDT",)))


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    return write_world(tmp_path_factory.mktemp("planworld"), small_world())


@pytest.fixture(scope="module")
def market(data_dir) -> Market:
    return Market.load(data_dir)


def pins_of(market: Market) -> dict[str, object]:
    pins = run.data_record(market.pins)
    assert pins is not None
    return pins


def write_world_file(root: Path, market: Market, **changes: object) -> Path:
    """A rehearsal world's ``rehearsal.json`` for ``market``'s data, with ``changes``."""
    document: dict[str, object] = {
        "format": WORLD_FORMAT,
        "scale": "rehearsal",
        "data": pins_of(market),
        "v3_pack_sha256": V3_PIN,
        "registration_sha256": REGISTRATION,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / WORLD_FILE).write_bytes(_canonical(document | changes))
    return root


def write_manifest_file(target: Path, market: Market, **changes: object) -> Path:
    """A run manifest naming ``market``'s data and ``V3_PIN``, with ``changes``."""
    data = {"config_path": "config/v4_data.json", **pins_of(market)}
    document: dict[str, object] = {
        "schema": "v4-run-manifest-1",
        "data": data,
        "v3_pack_sha256": V3_PIN,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(document | changes))
    return target


def expected_argv(
    mode: str, data_dir: Path, out: Path, *, world: Path | None, manifest: Path | None, picks: str
) -> list[str]:
    argv = ["expected", "--mode", mode, "--data", str(data_dir), "--out", str(out)]
    if world is not None:
        argv += ["--world", str(world)]
    if manifest is not None:
        argv += ["--manifest", str(manifest)]
    if picks:
        argv += ["--picks-sha256", picks]
    return argv


# ---- matrix -----------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["registered", "rehearsal"])
def test_matrix_has_44_cells_and_4_v3_cells_in_run_order(mode):
    cells, v3_cells = v4_run_plan.matrix(mode)
    assert [cell["cell"] for cell in cells] == list(NON_V3)
    assert len(cells) == 44
    assert [cell["cell"] for cell in v3_cells] == [
        "v3_as_built-1000-1x",
        "v3_as_built-1000-2x",
        "v3_as_built-10000-1x",
        "v3_as_built-10000-2x",
    ]
    # Together they are the run's 48 cells, in all_cells() order, and the expected file's cells.
    both = [*cells, *v3_cells]
    assert [cell["cell"] for cell in both] == [cell.cell_id for cell in all_cells()]
    assert [cell["cell"] for cell in both] == list(expected_cells(mode))
    # Each entry is what the diagnostic workflow's matrix writes, which the cell CLIs take.
    assert both == json.loads(v4_cells_plan.matrix_json(all_cells()))["include"]
    for entry in both:
        spec = CellSpec(entry["arm"], entry["capital"], entry["costs"])
        assert entry["cell"] == spec.cell_id


def test_matrix_timing_has_no_v3_cells():
    cells, v3_cells = v4_run_plan.matrix("timing")
    assert [cell["cell"] for cell in cells] == list(NON_V3) == list(expected_cells("timing"))
    assert v3_cells == []


@pytest.mark.parametrize("mode", ["", "Registered", "registered ", "rehearse", "all", "timing\n"])
def test_matrix_refuses_a_mode_outside_the_runs_modes(mode):
    assert MODES == ("rehearsal", "timing", "registered")
    with pytest.raises(ValueError, match="mode"):
        v4_run_plan.matrix(mode)


def test_matrix_command_appends_the_matrices_ids_and_counts(tmp_path):
    output = tmp_path / "github_output"
    output.write_text("earlier=1\n", encoding="ascii")
    code, stdout, stderr = run_cli(
        v4_run_plan, ["matrix", "--mode", "registered", "--github-output", str(output)]
    )
    cells, v3_cells = v4_run_plan.matrix("registered")
    one_line = {"separators": (",", ":")}
    assert (code, stderr) == (0, "")
    assert output.read_text(encoding="ascii") == (
        "earlier=1\n"
        f"cells={json.dumps({'include': cells}, **one_line)}\n"
        f"v3_cells={json.dumps({'include': v3_cells}, **one_line)}\n"
        f"cell_ids={','.join(NON_V3)}\n"
        "cells_count=44\n"
        "v3_count=4\n"
    )
    assert stdout == "v4_run_plan matrix: mode registered, 44 cells, 4 v3 cells\n"


def test_matrix_command_for_timing_writes_an_empty_v3_matrix(tmp_path):
    output = tmp_path / "github_output"
    code, stdout, _ = run_cli(
        v4_run_plan, ["matrix", "--mode", "timing", "--github-output", str(output)]
    )
    lines = dict(line.split("=", 1) for line in output.read_text(encoding="ascii").splitlines())
    assert code == 0
    assert list(lines) == ["cells", "v3_cells", "cell_ids", "cells_count", "v3_count"]
    assert json.loads(lines["v3_cells"]) == {"include": []}
    assert (lines["cells_count"], lines["v3_count"]) == ("44", "0")
    assert len(json.loads(lines["cells"])["include"]) == 44
    assert lines["cell_ids"].split(",") == list(NON_V3)
    assert stdout == "v4_run_plan matrix: mode timing, 44 cells, 0 v3 cells\n"


def test_matrix_command_refuses_a_bad_mode_and_writes_nothing(tmp_path):
    output = tmp_path / "github_output"
    code, stdout, stderr = run_cli(
        v4_run_plan, ["matrix", "--mode", "live", "--github-output", str(output)]
    )
    assert code == 1 and stdout == ""
    assert stderr.startswith("::error::v4_run_plan: ") and stderr.endswith(": refused\n")
    assert "mode" in stderr
    assert not output.exists()


def test_matrix_command_names_an_output_file_it_cannot_write(tmp_path):
    code, _, stderr = run_cli(
        v4_run_plan, ["matrix", "--mode", "registered", "--github-output", str(tmp_path)]
    )
    assert code == 1
    assert "writing the output file failed" in stderr


# ---- expected ---------------------------------------------------------------------------------


def test_expected_from_a_synthetic_world(tmp_path, data_dir, market):
    """Rehearsal: the v3 pins are rehearsal.json's and the picks' pin is the one given."""
    world = write_world_file(tmp_path / "world", market)
    out = tmp_path / "expected.json"
    argv = expected_argv("rehearsal", data_dir, out, world=world, manifest=None, picks=PICKS)
    code, stdout, stderr = run_cli(v4_run_plan, argv)
    assert (code, stderr) == (0, "")
    want = Expected(
        "rehearsal",
        expected_cells("rehearsal"),
        run.window_record(market),  # type: ignore[arg-type]
        run.data_record(market.pins),  # type: ignore[arg-type]
        V3_PIN,
        PICKS,
    )
    raw = out.read_bytes()
    assert raw == _canonical(expected_record(want))  # byte for byte what read_expected reads
    read = read_expected(out)
    assert read == want
    assert len(read.cells) == 48 and read.cells == tuple(cell.cell_id for cell in all_cells())
    assert read.window == {
        "start_ms": month_start("2025-01"),
        "end_ms": month_start("2025-04") - 1 * HOUR_MS,
    }
    assert json.loads(raw)["format"] == EXPECTED_FORMAT
    assert stdout == (
        "v4_run_plan expected: mode rehearsal, 48 cells, 2160 window hours, data end_month "
        f"2025-03, expected sha256 {hashlib.sha256(raw).hexdigest()}\n"
    )
    assert re.search(r"[0-9]+\.[0-9]", stdout) is None  # counts and pins, never a price


def test_expected_registered_takes_the_manifests_v3_pin(tmp_path, data_dir, market):
    manifest = write_manifest_file(tmp_path / "config" / "v4_run_manifest.json", market)
    out = tmp_path / "expected.json"
    argv = expected_argv("registered", data_dir, out, world=None, manifest=manifest, picks=PICKS)
    code, stdout, stderr = run_cli(v4_run_plan, argv)
    assert (code, stderr) == (0, "")
    read = read_expected(out)
    assert (read.mode, read.v3_pack_sha256, read.picks_sha256) == ("registered", V3_PIN, PICKS)
    assert read.cells == expected_cells("registered") and len(read.cells) == 48
    assert read.data == pins_of(market) and read.window == run.window_record(market)
    assert stdout.startswith("v4_run_plan expected: mode registered, 48 cells, ")


@pytest.mark.parametrize("empty_pin_given", [False, True])
def test_expected_timing_has_44_cells_and_no_v3_pins(tmp_path, data_dir, empty_pin_given):
    """A timing run has no picks job: its pin is absent, or given empty by a workflow that passes
    the same arguments in every mode."""
    out = tmp_path / "expected.json"
    argv = expected_argv("timing", data_dir, out, world=None, manifest=None, picks="")
    if empty_pin_given:
        argv += ["--picks-sha256", ""]
    code, stdout, stderr = run_cli(v4_run_plan, argv)
    assert (code, stderr) == (0, "")
    read = read_expected(out)
    assert read.cells == expected_cells("timing") and len(read.cells) == 44
    assert (read.v3_pack_sha256, read.picks_sha256) == (None, None)
    assert "44 cells" in stdout


def test_write_expected_is_the_commands_function(tmp_path, data_dir, market):
    out = tmp_path / "e" / "expected.json"  # its folder is made
    manifest = read_manifest(write_manifest_file(tmp_path / "m.json", market).read_bytes())
    v4_run_plan.write_expected(
        "registered", data_dir, out, manifest=manifest, world=None, picks_sha256=PICKS
    )
    assert read_expected(out).picks_sha256 == PICKS


@pytest.mark.parametrize(
    "picks",
    ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, " " + "a" * 63, "a" * 64 + "\n", "0x" + "a" * 62]
    + ["١" * 64],
)
@pytest.mark.parametrize("mode", ["rehearsal", "registered"])
def test_expected_refuses_a_bad_picks_pin(tmp_path, data_dir, market, mode, picks):
    world = write_world_file(tmp_path / "world", market) if mode == "rehearsal" else None
    manifest = None
    if mode == "registered":
        manifest = write_manifest_file(tmp_path / "m.json", market)
    out = tmp_path / "expected.json"
    argv = expected_argv(mode, data_dir, out, world=world, manifest=manifest, picks="")
    argv += ["--picks-sha256", picks]  # given as is, the empty text included
    code, stdout, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and stdout == ""
    assert "picks" in stderr and stderr.endswith(": refused\n")
    assert not out.exists()


@pytest.mark.parametrize("mode", ["rehearsal", "registered"])
def test_expected_needs_the_picks_pin_when_the_mode_has_v3_cells(tmp_path, data_dir, market, mode):
    world = write_world_file(tmp_path / "world", market) if mode == "rehearsal" else None
    manifest = write_manifest_file(tmp_path / "m.json", market) if mode == "registered" else None
    out = tmp_path / "expected.json"
    argv = expected_argv(mode, data_dir, out, world=world, manifest=manifest, picks="")
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "picks" in stderr
    assert not out.exists()


def test_expected_timing_refuses_a_picks_pin_and_any_v3_source(tmp_path, data_dir, market):
    world = write_world_file(tmp_path / "world", market)
    manifest = write_manifest_file(tmp_path / "m.json", market)
    for kwargs in (
        {"picks": PICKS, "world": None, "manifest": None},
        {"picks": "", "world": world, "manifest": None},
        {"picks": "", "world": None, "manifest": manifest},
    ):
        out = tmp_path / "expected.json"
        code, _, stderr = run_cli(v4_run_plan, expected_argv("timing", data_dir, out, **kwargs))
        assert code == 1 and "timing" in stderr
        assert not out.exists()


def test_expected_refuses_the_wrong_source_of_v3_pins(tmp_path, data_dir, market):
    world = write_world_file(tmp_path / "world", market)
    manifest = write_manifest_file(tmp_path / "m.json", market)
    cases = {
        ("registered", "world only"): {"world": world, "manifest": None},
        ("registered", "both"): {"world": world, "manifest": manifest},
        ("registered", "neither"): {"world": None, "manifest": None},
        ("rehearsal", "manifest only"): {"world": None, "manifest": manifest},
        ("rehearsal", "both"): {"world": world, "manifest": manifest},
        ("rehearsal", "neither"): {"world": None, "manifest": None},
    }
    for (mode, label), sources in cases.items():
        out = tmp_path / "expected.json"
        argv = expected_argv(mode, data_dir, out, picks=PICKS, **sources)
        code, _, stderr = run_cli(v4_run_plan, argv)
        assert code == 1, (mode, label)
        assert "--manifest" in stderr or "--world" in stderr, (mode, label)
        assert not out.exists(), (mode, label)


def test_expected_rehearsal_needs_a_rehearsal_world_of_these_data(tmp_path, data_dir, market):
    timing_world = write_world_file(
        tmp_path / "timing", market, scale="timing", v3_pack_sha256=None, registration_sha256=None
    )
    other_data = write_world_file(
        tmp_path / "other", market, data=pins_of(market) | {"end_month": "2025-02"}
    )
    for world in (timing_world, other_data):
        out = tmp_path / "expected.json"
        argv = expected_argv("rehearsal", data_dir, out, world=world, manifest=None, picks=PICKS)
        code, _, stderr = run_cli(v4_run_plan, argv)
        assert code == 1 and "rehearsal" in stderr
        assert not out.exists()


def test_expected_registered_refuses_data_that_is_not_the_manifests(tmp_path, data_dir, market):
    for key in ("config_sha256", "end_month", "daily_sha256", "index_sha256"):
        changed = OTHER if key != "end_month" else "2025-02"
        data = {"config_path": "config/v4_data.json", **pins_of(market), key: changed}
        manifest = write_manifest_file(tmp_path / f"{key}.json", market, data=data)
        out = tmp_path / "expected.json"
        argv = expected_argv(
            "registered", data_dir, out, world=None, manifest=manifest, picks=PICKS
        )
        code, _, stderr = run_cli(v4_run_plan, argv)
        assert code == 1 and "manifest" in stderr, key
        assert not out.exists(), key


@pytest.mark.parametrize("mode", ["rehearsal", "timing"])
def test_rehearsal_and_timing_refuse_data_that_is_not_synthetic(
    tmp_path, monkeypatch, data_dir, market, mode
):
    """v4-d03: the two synthetic modes refuse real data. A real config has another digest than
    the synthetic worlds' ``CONFIG_SHA256``."""
    monkeypatch.setattr(v4_run_plan, "CONFIG_SHA256", sha("a real config"))
    world = write_world_file(tmp_path / "world", market) if mode == "rehearsal" else None
    out = tmp_path / "expected.json"
    picks = PICKS if mode == "rehearsal" else ""
    argv = expected_argv(mode, data_dir, out, world=world, manifest=None, picks=picks)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "synthetic" in stderr
    assert not out.exists()


def test_expected_refuses_an_existing_file_before_loading_the_data(tmp_path, market):
    out = tmp_path / "expected.json"
    out.write_bytes(b"mine")
    world = write_world_file(tmp_path / "world", market)
    missing = tmp_path / "no-such-data"  # never loaded: the file is refused first
    argv = expected_argv("rehearsal", missing, out, world=world, manifest=None, picks=PICKS)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "already exists" in stderr
    assert out.read_bytes() == b"mine"


def test_expected_refuses_an_output_folder_it_cannot_create(tmp_path, market, data_dir):
    blocker = tmp_path / "a-file"
    blocker.write_bytes(b"not a folder")
    world = write_world_file(tmp_path / "world", market)
    out = blocker / "expected.json"
    argv = expected_argv("rehearsal", data_dir, out, world=world, manifest=None, picks=PICKS)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "creating the output folder failed" in stderr


def test_expected_refuses_a_data_directory_that_does_not_load(tmp_path, market):
    world = write_world_file(tmp_path / "world", market)
    out = tmp_path / "expected.json"
    argv = expected_argv(
        "rehearsal", tmp_path / "none", out, world=world, manifest=None, picks=PICKS
    )
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "loading the data directory failed" in stderr
    assert not out.exists()


def test_expected_refuses_a_bad_mode_a_bad_manifest_and_a_bad_world(tmp_path, data_dir, market):
    out = tmp_path / "expected.json"
    argv = expected_argv("live", data_dir, out, world=None, manifest=None, picks=PICKS)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "mode" in stderr

    broken = tmp_path / "broken.json"
    broken.write_bytes(b'{"schema": "v4-run-manifest-1"}')
    argv = expected_argv("registered", data_dir, out, world=None, manifest=broken, picks=PICKS)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "--manifest" in stderr

    empty = tmp_path / "empty-world"
    empty.mkdir()
    argv = expected_argv("rehearsal", data_dir, out, world=empty, manifest=None, picks=PICKS)
    code, _, stderr = run_cli(v4_run_plan, argv)
    assert code == 1 and "--world" in stderr
    assert not out.exists()


# ---- the status record ------------------------------------------------------------------------

JOBS = (PLAN_JOB, *SKIPPED_JOBS, *SKIPPED_MATRIX_JOBS)


def needs_of(**results: str) -> dict[str, object]:
    """``toJSON(needs)``: every job with its result and its outputs, as GitHub writes them."""
    needs: dict[str, object] = {job: {"result": "success", "outputs": {}} for job in JOBS}
    needs[PLAN_JOB] = {
        "result": "success",
        "outputs": {"cells": '{"include":[{"cell":"v4_main-1000-1x"}]}', "cell_ids": "a,b"},
    }
    for job, result in results.items():
        needs[job.replace("_", "-")] = {"result": result, "outputs": {}}
    return needs


def status_env(monkeypatch, needs: object = None, **env: str) -> None:
    values = {"RUN_ID": "40123456789", "RUN_ATTEMPT": "1"}
    values["NEEDS"] = needs if isinstance(needs, str) else json.dumps(needs or needs_of(), indent=2)
    for name, value in (values | env).items():
        monkeypatch.setenv(name, value)


def status_argv(
    out: Path, *, mode: str = "registered", registration: str = REGISTRATION
) -> list[str]:
    return ["--mode", mode, "--registration-sha256", registration, "--out", str(out)]


def test_status_jobs_are_the_workflows_other_jobs():
    assert v4_run_status.JOBS == (
        "plan",
        "v3-pack",
        "v3-picks",
        "scenarios",
        "verdict",
        "analysis",
        "cell",
        "v3-cell",
    )
    assert v4_run_status.STATUS_FORMAT == "v4-run-status-1"


def test_status_reads_needs_from_the_environment_and_writes_canonical_json(tmp_path, monkeypatch):
    needs = needs_of(v3_pack="skipped", cell="failure", scenarios="skipped")
    status_env(monkeypatch, needs)
    target = tmp_path / "status.json"
    code, stdout, stderr = run_cli(v4_run_status, status_argv(target))
    assert (code, stderr) == (0, "")
    raw = target.read_bytes()
    document = json.loads(raw)
    assert raw == _canonical(document)  # sorted keys, no spaces, no newline
    assert document == {
        "format": "v4-run-status-1",
        "mode": "registered",
        "run_id": 40123456789,
        "run_attempt": 1,
        "registration_sha256": REGISTRATION,
        "jobs": {
            "plan": "success",
            "v3-pack": "skipped",
            "v3-picks": "success",
            "scenarios": "skipped",
            "verdict": "success",
            "analysis": "success",
            "cell": "failure",
            "v3-cell": "success",
        },
        "verdict_ran": True,
    }
    assert b"include" not in raw  # the jobs' outputs are not kept: results only
    assert stdout == (
        "v4_run_status: mode registered, run 40123456789 attempt 1, 8 jobs (5 success, "
        "1 failure, 0 cancelled, 2 skipped), verdict job ran\n"
    )


@pytest.mark.parametrize(
    ("result", "ran"),
    [("success", True), ("failure", True), ("skipped", False), ("cancelled", False)],
)
def test_status_says_the_verdict_job_ran_only_on_success_or_failure(
    tmp_path, monkeypatch, result, ran
):
    status_env(monkeypatch, needs_of(verdict=result))
    target = tmp_path / "status.json"
    code, stdout, _ = run_cli(v4_run_status, status_argv(target))
    document = json.loads(target.read_bytes())
    assert code == 0
    assert document["verdict_ran"] is ran
    assert document["jobs"]["verdict"] == result
    assert stdout.endswith("verdict job ran\n" if ran else "verdict job did not run\n")


def test_status_of_a_rehearsal_or_timing_run_may_have_no_registration(tmp_path, monkeypatch):
    status_env(monkeypatch)
    for mode in ("rehearsal", "timing"):
        target = tmp_path / f"{mode}.json"
        code, _, _ = run_cli(v4_run_status, status_argv(target, mode=mode, registration=""))
        document = json.loads(target.read_bytes())
        assert code == 0
        assert (document["mode"], document["registration_sha256"]) == (mode, None)


@pytest.mark.parametrize("name", ["RUN_ID", "RUN_ATTEMPT", "NEEDS"])
def test_status_refuses_a_missing_environment_variable(tmp_path, monkeypatch, name):
    status_env(monkeypatch)
    monkeypatch.delenv(name)
    target = tmp_path / "status.json"
    code, stdout, stderr = run_cli(v4_run_status, status_argv(target))
    assert code == 1 and stdout == ""
    assert name in stderr and stderr.startswith("::error::v4_run_status: ")
    assert not target.exists()


@pytest.mark.parametrize(
    ("name", "value"),
    [("RUN_ID", value) for value in ["", "0", "012", "-1", "12a", " 12", "1" * 21, "１２"]]
    + [("RUN_ATTEMPT", value) for value in ["", "0", "01", "-1", "x", "1.0", "1234567"]],
)
def test_status_refuses_a_run_id_or_attempt_that_is_not_plain_digits(
    tmp_path, monkeypatch, name, value
):
    status_env(monkeypatch, **{name: value})
    target = tmp_path / "status.json"
    code, _, stderr = run_cli(v4_run_status, status_argv(target))
    assert code == 1 and name in stderr
    assert not target.exists()


def broken_needs() -> dict[str, str]:
    """NEEDS texts that are not ``toJSON(needs)`` of this workflow, each with what refuses it."""
    good = needs_of()
    without_cell = {job: item for job, item in good.items() if job != "cell"}
    return {
        "not json": "plan: success",
        "not an object": "[]",
        "duplicate key": '{"plan": {"result": "success"}, "plan": {"result": "failure"}}',
        "a job missing": json.dumps(without_cell),
        "an unknown job": json.dumps({**good, "status": {"result": "success"}}),
        "no result": json.dumps({**good, "plan": {"outputs": {}}}),
        "not an object job": json.dumps({**good, "plan": "success"}),
        "an unknown result": json.dumps({**good, "plan": {"result": "SECRET-1234.5"}}),
        "a result that is not text": json.dumps({**good, "plan": {"result": 1}}),
        "a null result": json.dumps({**good, "plan": {"result": None}}),
    }


@pytest.mark.parametrize("label", list(broken_needs()))
def test_status_refuses_a_needs_that_is_not_the_workflows(tmp_path, monkeypatch, label):
    status_env(monkeypatch, broken_needs()[label])
    target = tmp_path / "status.json"
    code, stdout, stderr = run_cli(v4_run_status, status_argv(target))
    assert code == 1 and stdout == ""
    assert "NEEDS" in stderr and "SECRET" not in stderr  # a value is never echoed
    assert not target.exists()


@pytest.mark.parametrize(
    ("mode", "registration"),
    [("live", REGISTRATION), ("registered", "A" * 64), ("registered", "a" * 63)]
    + [("registered", "a" * 64 + "\n"), ("", REGISTRATION)],
)
def test_status_refuses_a_bad_mode_or_registration(tmp_path, monkeypatch, mode, registration):
    status_env(monkeypatch)
    target = tmp_path / "status.json"
    code, _, stderr = run_cli(
        v4_run_status, status_argv(target, mode=mode, registration=registration)
    )
    assert code == 1
    assert ("mode" in stderr) or ("registration" in stderr)
    assert not target.exists()


def test_status_never_replaces_an_existing_file(tmp_path, monkeypatch):
    status_env(monkeypatch)
    target = tmp_path / "status.json"
    target.write_bytes(b"mine")
    code, _, stderr = run_cli(v4_run_status, status_argv(target))
    assert code == 1 and "already exists" in stderr
    assert target.read_bytes() == b"mine"


def test_status_line_holds_counts_and_names_no_outcome(tmp_path, monkeypatch):
    status_env(monkeypatch)
    target = tmp_path / "status.json"
    _, stdout, _ = run_cli(v4_run_status, status_argv(target))
    for word in ("pass", "incomplete", "equity", "return"):
        assert word not in stdout
    assert re.search(r"[0-9]+\.[0-9]", stdout) is None
