"""One V3.1 cell: the execution gate, the replay of its window pack and its artifacts.

Synthetic only: the packs are built from the shared market fixtures (labelled synthetic),
and the registration is written under a temporary directory with Task 6's own test
helpers. The git helpers run on a tiny temporary repository. Nothing touches the network.
"""

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from decimal import Context, localcontext
from pathlib import Path

import combined_market_fixtures as fx
import pytest
from test_v31_registration import (
    FX_PATH,
    MENU,
    fx_document,
    prepare_document,
    registration_document,
    write_json,
)

from crypto_grid_bot.combined import dashboard
from crypto_grid_bot.combined.artifacts import read_bundle
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.driver import run_cell
from crypto_grid_bot.combined.driver.flow_schedule import build_flow_schedule
from crypto_grid_bot.combined.driver.packs import (
    CoinInputs,
    WindowPack,
    build_window_pack,
    read_pack,
    write_pack,
)
from crypto_grid_bot.combined.driver.registration import (
    DriverRegistration,
    load_prepare_config,
    load_registration,
    run_manifest,
    write_run_manifest,
)
from crypto_grid_bot.combined.driver.run_cell import (
    changed_since,
    execution_gate,
    head_commit,
    run_v31_cell,
)
from crypto_grid_bot.combined.driver.serialize import decode_outcome, decode_report
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS, cost_profile
from crypto_grid_bot.combined.experiment import RunIdentity, capital_label
from crypto_grid_bot.combined.observation_policy import POLICY_ID

HOUR = fx.HOUR
DAY = fx.DAY
MINUTE = 60_000
FIRST = fx.START - fx.HISTORY_DAYS * DAY  # the fixtures' first hourly bar
W0_START = fx.START
W0_END = W0_START + 3 * DAY
W1_START = W0_END
W1_END = W1_START + 3 * DAY
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
SOURCES = (("synthetic.manifest.json", "a" * 64),)
ATTEMPT = "attempt-1"
CELL = "w1.combined.olhc.c1.owner_small"
CODE_PIN = "4" * 40


def coin(symbol: str, path, start: int, end: int) -> CoinInputs:
    """A coin with futures, its history from the fixtures' first bar and a flow schedule
    from synthetic minutes."""
    hours = (end - FIRST) // HOUR
    spot = fx.hourly(path, hours)
    flow = build_flow_schedule(symbol, fx.minutes(start - 15 * MINUTE, end), start, end)
    return CoinInputs(
        symbol,
        FIRST,
        spot,
        fx.hourly(path, hours),
        daily_bars(spot),
        fx.funding(FIRST, end),
        fx.RULES,
        fx.RULES,
        flow,
        (),
        True,
    )


def window_pack(window_id: str, start: int, end: int) -> WindowPack:
    coins = [coin("BTCUSDT", fx.uptrend, start, end), coin("ETHUSDT", fx.downtrend, start, end)]
    return build_window_pack(window_id, start, end, coins, SOURCES)


def window_document(pack: WindowPack) -> dict[str, object]:
    return {
        "id": pack.window_id,
        "start_ms": pack.start_ms,
        "end_ms": pack.end_ms,
        "skipped_hours": list(pack.skipped_hours),
    }


@dataclass(frozen=True)
class World:
    root: Path
    reg: DriverRegistration
    packs: dict[str, WindowPack]
    pack_shas: dict[str, str]
    config_sha: str
    manifest_sha: str


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """Written packs for W1 and W0, and a loaded synthetic registration of all 216 cells
    whose run-manifest pins those packs."""
    root = tmp_path_factory.mktemp("repo")
    built = {"w1": window_pack("w1", W1_START, W1_END), "w0": window_pack("w0", W0_START, W0_END)}
    shas = {wid: write_pack(pack, root / f"{wid}.json.gz") for wid, pack in built.items()}
    packs = {wid: read_pack(root / f"{wid}.json.gz", sha) for wid, sha in shas.items()}
    config = root / "config"
    config.mkdir()
    shutil.copyfile(MENU, config / "v3_1_experiment_menu.json")
    prepare = prepare_document()
    prepare["windows"] = [
        {"id": wid, "start_ms": pack.start_ms, "end_ms": pack.end_ms, "symbols": SYMBOLS}
        for wid, pack in packs.items()
    ]
    write_json(config / "v3_1_prepare.json", prepare)
    fx_sha = write_json(root / FX_PATH, fx_document())
    prepared = load_prepare_config(config / "v3_1_prepare.json")
    manifest_path = config / "v3_1_run_manifest.json"
    manifest = run_manifest(prepared, window_packs=shas, v3_pack="3" * 64)
    manifest_sha = write_run_manifest(manifest, manifest_path)
    document = registration_document(prepared.sha256, manifest_sha, fx_sha)
    document["windows"] = [window_document(packs["w1"])]
    document["reported_windows"] = [window_document(packs["w0"])]
    registration_path = config / "v3_1_registration.json"
    config_sha = write_json(registration_path, document)
    reg = load_registration(registration_path, manifest_path, repo_root=root)
    return World(root, reg, packs, shas, config_sha, manifest_sha)


def cell_of(world: World, cell_id: str):
    (cell,) = [c for c in world.reg.cells if c.cell_id == cell_id]
    return cell


def gate(world: World, cell_id: str = CELL, **changes):
    window = cell_id.split(".")[0]
    arguments = {
        "repo_head": "9" * 40,
        "pack_sha256": world.pack_shas.get(window, "0" * 64),
        "config_sha256": world.config_sha,
        "manifest_sha256": world.manifest_sha,
        "changed_paths": (),
        "adapter_pins_now": dict(world.reg.registration.adapter_pins),
        "pack": world.packs.get(window, world.packs["w1"]),
    }
    arguments.update(changes)
    return execution_gate(world.reg, cell_id, **arguments)


def run(world: World, cell_id: str, out_dir: Path, attempt_id: str = ATTEMPT) -> Path:
    cell = cell_of(world, cell_id)
    return run_v31_cell(cell, world.packs[cell.window], world.reg, out_dir, attempt_id=attempt_id)


def snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def ran(world: World, tmp_path_factory) -> Path:
    """The W1 combined cell at base cost with the owner_small capital, run once."""
    return run(world, CELL, tmp_path_factory.mktemp("cells"))


# --- the execution gate ----------------------------------------------------------------

REGISTRATION_ARTIFACTS = (
    "config/v3_1_registration.json",
    "config/v3_1_run_manifest.json",
    "config/v3_1_prepare.json",
    "config/v3_1_experiment_menu.json",
    FX_PATH,
    "docs/trials/register.jsonl",
    "docs/reviews/2026-10-13-claude-v3-1-registration.md",
    "docs/tasks/2026-10-13-v31-run.md",
)


def test_gate_passes_a_registered_cell_with_registration_only_changes(world):
    assert world.reg.fx_record_paths == (FX_PATH,)
    assert gate(world, changed_paths=REGISTRATION_ARTIFACTS) == cell_of(world, CELL)
    w0 = "w0.combined.ohlc.c2.research"
    assert gate(world, w0) == cell_of(world, w0)
    baseline = "w1.matched_spot_hold.native.c1.research"
    assert gate(world, baseline) == cell_of(world, baseline)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"config_sha256": "0" * 64}, "config SHA-256"),
        ({"manifest_sha256": "0" * 64}, "run-manifest SHA-256"),
        ({"pack_sha256": "0" * 64}, "pack SHA-256"),
        ({"changed_paths": ("src/crypto_grid_bot/combined/engine.py",)}, "engine.py"),
        ({"repo_head": "HEAD"}, "repo head"),
    ],
)
def test_gate_refuses_another_commit_pack_or_config(world, change, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        gate(world, **change)


def test_gate_names_every_mismatch_at_once(world):
    with pytest.raises(ValueError) as refused:
        gate(
            world,
            config_sha256="0" * 64,
            manifest_sha256="1" * 64,
            pack_sha256="2" * 64,
            changed_paths=("scripts/v31_driver.py", "docs/reviews/note.md"),
        )
    text = str(refused.value)
    assert CELL in text
    for part in ("config SHA-256", "run-manifest SHA-256", "pack SHA-256", "scripts/v31_driver.py"):
        assert part in text
    assert "docs/reviews/note.md" not in text  # an allowed path is not a mismatch


@pytest.mark.parametrize(
    "cell_id", ["w2.combined.olhc.c1.research", "w1.combined.native.c1.research", ""]
)
def test_gate_refuses_an_unregistered_cell(world, cell_id):
    with pytest.raises(ValueError, match="not registered"):
        gate(world, cell_id)


def test_gate_refuses_a_src_change_a_wrong_adapter_pin_and_other_skipped_hours(world):
    pins = {**dict(world.reg.registration.adapter_pins), "combined": "8" * 64}
    pack = replace(world.packs["w1"], skipped_hours=(W1_START + 5 * HOUR,))
    with pytest.raises(ValueError) as refused:
        gate(
            world,
            changed_paths=("src/crypto_grid_bot/combined/driver/run_cell.py",),
            adapter_pins_now=pins,
            pack=pack,
        )
    text = str(refused.value)
    assert "src/crypto_grid_bot/combined/driver/run_cell.py" in text
    assert "adapter pin of combined" in text
    assert "skipped hours" in text


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_v31_run_cell.py",
        ".github/workflows/v31-run.yml",
        "scripts/v31_driver.py",
        "config/v3_1_other.json",
        "config/datasets/v3-20261009/inventory.manifest.json",
        "docs/V3_1_SOURCE_INVENTORY.md",
        "docs/reviews",
        "docs/reviews/../../src/crypto_grid_bot/combined/engine.py",
        "README.md",
    ],
)
def test_gate_refuses_a_change_outside_the_registration_artifacts(world, path):
    with pytest.raises(ValueError, match=re.escape(path)):
        gate(world, changed_paths=(path,))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"pack": "w0"}, "pack window"),
        ({"start_ms": W1_START + DAY}, "pack window"),
        ({"end_ms": W1_END - DAY}, "pack window"),
    ],
)
def test_gate_refuses_a_pack_of_another_window(world, change, message):
    pack = world.packs["w0"] if change.get("pack") else replace(world.packs["w1"], **change)
    with pytest.raises(ValueError, match=message):
        gate(world, pack=pack)


def test_gate_refuses_missing_adapter_pins(world):
    pins = dict(world.reg.registration.adapter_pins)
    del pins["combined"]
    with pytest.raises(ValueError, match="adapter pin of combined"):
        gate(world, adapter_pins_now=pins)


# --- running a cell --------------------------------------------------------------------


def test_v31_cell_on_a_synthetic_pack_writes_a_complete_outcome(world, ran):
    reg = world.reg
    capital = {c.id: c for c in reg.registration.capitals}["owner_small"]
    invocation = CELL.replace(".", "-")
    assert ran.name == CELL
    assert sorted(path.name for path in ran.iterdir()) == [
        "outcome.json",
        "report.json",
        invocation,
    ]

    outcome_text = (ran / "outcome.json").read_text(encoding="ascii")
    report_text = (ran / "report.json").read_text(encoding="ascii")
    outcome = decode_outcome(outcome_text)
    report = decode_report(report_text)
    (w1,) = reg.registration.windows
    assert outcome.identity == RunIdentity(
        arm="combined",
        window="w1",
        capital="owner_small",
        cost_multiple=1,
        data_pin=w1.data_pin,
        cost_profile_pin=COST_PROFILE_PINS[1],
        start_ms=W1_START,
        end_ms=W1_END,
        code_pin=CODE_PIN,
        config_pin=world.config_sha,
        fx_pin=capital.fx_pin,
        observation_policy=POLICY_ID,
        adapter_pin=dict(reg.registration.adapter_pins)["combined"],
        scenario="open_low_high_close",
    )
    assert w1.data_pin == world.manifest_sha and capital.fx_pin is not None
    assert outcome.complete and not outcome.failed and outcome.accounting_explained
    assert outcome.attempt_id == ATTEMPT
    assert outcome.initial_equity == capital.initial_equity
    assert outcome.capital_label == capital_label(capital)
    assert outcome.report_evidence is not None
    assert outcome.report_evidence.report == report
    assert outcome.final_equity == report.final_equity
    assert report.skipped_hours == world.packs["w1"].skipped_hours
    assert report.contributions and report.fees > 0  # the replay traded
    refs = (f"v31-pack:{world.pack_shas['w1']}", f"v31-run-manifest:{world.manifest_sha}")
    assert report.source_refs == refs

    bundle = read_bundle(ran / invocation)
    assert bundle.events and bundle.records is not None
    assert bundle.records.run.source_refs == refs
    assert bundle.records.lifecycles and bundle.report_json is None and bundle.report_html is None
    metadata = json.loads(bundle.metadata_json)
    assert metadata["cell_id"] == CELL and metadata["attempt_id"] == ATTEMPT
    assert metadata["outcome_sha256"] == hashlib.sha256(outcome_text.encode()).hexdigest()
    assert metadata["report_sha256"] == hashlib.sha256(report_text.encode()).hexdigest()
    assert metadata["pack_sha256"] == world.pack_shas["w1"]
    assert metadata["code_pin"] == CODE_PIN and metadata["config_pin"] == world.config_sha
    assert metadata["initial_equity"] == str(capital.initial_equity)


def test_doubled_cost_cell_runs_with_doubled_costs(world, ran, tmp_path, monkeypatch):
    seen = []
    replay = run_cell.replay_strategy

    def spy(replay_run, markets):
        seen.append(markets)
        return replay(replay_run, markets)

    monkeypatch.setattr(run_cell, "replay_strategy", spy)
    doubled = run(world, "w1.combined.olhc.c2.owner_small", tmp_path)

    (markets,) = seen
    assert [m.symbol for m in markets] == SYMBOLS
    for market in markets:
        assert market.spot.costs == cost_profile(2, "spot") != cost_profile(1, "spot")
        assert market.futures.costs == cost_profile(2, "futures") != cost_profile(1, "futures")
        assert market.minutes == () and market.flow is not None
    outcome = decode_outcome((doubled / "outcome.json").read_text(encoding="ascii"))
    assert outcome.identity.cost_multiple == 2
    assert outcome.identity.cost_profile_pin == COST_PROFILE_PINS[2]
    base = decode_report((ran / "report.json").read_text(encoding="ascii"))
    report = decode_report((doubled / "report.json").read_text(encoding="ascii"))
    assert 0 < base.fees < report.fees


def test_second_write_of_a_cell_is_refused(world, ran):
    before = snapshot(ran)
    for attempt in (ATTEMPT, "attempt-2"):
        with pytest.raises(FileExistsError):
            run(world, CELL, ran.parent, attempt)
    assert snapshot(ran) == before


def test_a_w0_cell_runs_from_the_reported_window(world, tmp_path):
    directory = run(world, "w0.combined.ohlc.c1.research", tmp_path)
    outcome = decode_outcome((directory / "outcome.json").read_text(encoding="ascii"))
    (w0,) = world.reg.reported_windows
    identity = outcome.identity
    assert (identity.window, identity.start_ms, identity.end_ms) == ("w0", W0_START, W0_END)
    assert identity.data_pin == w0.data_pin and identity.fx_pin is None
    assert (identity.scenario, identity.capital) == ("open_high_low_close", "research")
    assert outcome.complete and outcome.capital_label == "research_10000_usdt"
    report = decode_report((directory / "report.json").read_text(encoding="ascii"))
    assert report.source_refs[0] == f"v31-pack:{world.pack_shas['w0']}"


def test_the_same_cell_gives_byte_identical_artifacts(world, ran, tmp_path):
    # Even under a caller's coarse decimal context with lowercase exponents.
    with localcontext(Context(prec=6, capitals=0)):
        again = run(world, CELL, tmp_path)
    assert (again / "outcome.json").read_bytes() == (ran / "outcome.json").read_bytes()
    assert (again / "report.json").read_bytes() == (ran / "report.json").read_bytes()
    first = {name: data for name, (data, _) in snapshot(ran).items()}
    assert {name: data for name, (data, _) in snapshot(again).items()} == first


def test_run_refuses_other_cells_and_packs_before_writing(world, tmp_path):
    reg, cell = world.reg, cell_of(world, CELL)
    with pytest.raises(ValueError, match="v31"):
        hold = cell_of(world, "w1.matched_spot_hold.native.c1.research")
        run_v31_cell(hold, world.packs["w1"], reg, tmp_path, attempt_id=ATTEMPT)
    with pytest.raises(ValueError, match="not registered"):
        run_v31_cell(
            replace(cell, cost_multiple=2), world.packs["w1"], reg, tmp_path, attempt_id=ATTEMPT
        )
    with pytest.raises(ValueError, match="pack window"):
        run_v31_cell(cell, world.packs["w0"], reg, tmp_path, attempt_id=ATTEMPT)
    with pytest.raises(ValueError, match="attempt"):
        run_v31_cell(cell, world.packs["w1"], reg, tmp_path, attempt_id=" ")
    assert list(tmp_path.iterdir()) == []


def test_a_report_json_above_the_inline_limit_goes_into_the_bundle(world, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "_INLINE_JSON_LIMIT", 0)
    directory = run(world, "w1.spot_trend.olhc.c1.research", tmp_path)
    report = decode_report((directory / "report.json").read_text(encoding="ascii"))
    _, expected = dashboard.render_bundle_report(report, synthetic=False)
    bundle = read_bundle(directory / "w1-spot_trend-olhc-c1-research")
    assert expected is not None and bundle.report_json == expected
    assert bundle.report_html is None


# --- git helpers -----------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_changed_since_lists_committed_renamed_and_uncommitted_paths(tmp_path):
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, check=True, text=True
        )
        return done.stdout.strip()

    def write(name: str, text: str) -> None:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")

    git("init", "-q")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.autocrlf", "false")
    for name in ("src/pkg/module.py", "docs/tasks/task.md", "README.md"):
        write(name, f"{name}\n")
    git("add", "-A")
    git("commit", "-q", "-m", "code")
    code = head_commit(tmp_path)
    assert code == git("rev-parse", "HEAD") and re.fullmatch("[0-9a-f]{40}", code)
    assert changed_since(tmp_path, code) == ()

    # A rename out of src/ lists both paths, so the removal cannot hide behind it.
    (tmp_path / "docs/reviews").mkdir()
    git("mv", "src/pkg/module.py", "docs/reviews/module.py")
    write("config/v3_1_registration.json", "{}\n")
    git("add", "-A")
    git("commit", "-q", "-m", "registration")
    write("docs/tasks/task.md", "edited, not committed\n")
    write("untracked.txt", "never listed\n")
    assert head_commit(tmp_path) == git("rev-parse", "HEAD") != code
    assert changed_since(tmp_path, code) == (
        "config/v3_1_registration.json",
        "docs/reviews/module.py",
        "docs/tasks/task.md",
        "src/pkg/module.py",
    )

    with pytest.raises(ValueError, match="40 lowercase hex"):
        changed_since(tmp_path, "HEAD")
    with pytest.raises(ValueError, match="git"):
        changed_since(tmp_path, "0" * 40)
    with pytest.raises(ValueError, match="git"):
        head_commit(tmp_path / "missing")
