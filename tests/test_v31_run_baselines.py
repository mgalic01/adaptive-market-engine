"""The baseline cells: the matched spot hold and the frozen V3 arms, each run once.

Synthetic only: the W1 pack is built from the shared market fixtures (labelled synthetic),
the V3 input pack from the same synthetic paths, and the registration with Task 6's test
helpers. V3's frozen walk-forward trains 18 months per quarter, which takes minutes even on
two synthetic coins, so a stand-in records real V3 attempts around one short frozen replay.
Nothing touches the network.
"""

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, replace
from decimal import Context, localcontext
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

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
from test_v31_run_cell import (
    ATTEMPT,
    CODE_PIN,
    FIRST,
    HEAD,
    SOURCES,
    SYMBOLS,
    W0_END,
    W0_START,
    W1_END,
    W1_START,
    coin,
    snapshot,
    window_document,
    window_pack,
)

from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.baseline_hold import HoldMarket
from crypto_grid_bot.combined.baseline_v3 import V3Inputs, window_picks
from crypto_grid_bot.combined.driver import run_baselines, run_cell
from crypto_grid_bot.combined.driver.packs import (
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
from crypto_grid_bot.combined.driver.run_baselines import (
    compute_v3_picks,
    run_hold_cell,
    run_v3_cell,
)
from crypto_grid_bot.combined.driver.serialize import decode_outcome, decode_report
from crypto_grid_bot.combined.driver.v3_pack import V3PackFields, read_v3_pack, write_v3_pack
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS, cost_profile
from crypto_grid_bot.combined.experiment import RunIdentity, capital_label
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import replay_window

HOUR = fx.HOUR
DAY = fx.DAY
GAP = W1_START + 30 * HOUR  # BTC has no spot bar at this hour, so W1 skips it
HOLD_PIN = "6" * 64
V3_PIN = "7" * 64
SELECTOR = "unchanged_v3_selector"
HOLD_CELL = "w1.matched_spot_hold.native.c1.owner_small"
SELECTOR_CELL = "w1.unchanged_v3_selector.native.c2.owner_small"
RULE_CELL = "w1.unchanged_v3_r2_long_only.native.c1.research"
# The frozen picks the stand-in walk-forward returns: one long before W1, the pick in
# force at W1's start, a change inside W1 and one after it.
PICKS = {
    W1_START - 40 * DAY: "R1",
    W1_START - DAY: "R2L",
    W1_START + DAY: "R3L",
    W1_END + DAY: None,
}
FILTERS = OrderFilters(
    D("0.001"), D("100000"), D("0.001"), D("5"), D("0.001"), D("100000"), D("0.001"), D("0")
)


def w1_pack() -> WindowPack:
    """W1 for both coins, BTC without its spot bar at ``GAP``: one derived skipped hour."""
    btc = coin("BTCUSDT", fx.uptrend, W1_START, W1_END)
    spot = tuple(bar for bar in btc.spot_hourly if bar.open_ms != GAP)
    btc = replace(btc, spot_hourly=spot, daily=daily_bars(spot))
    eth = coin("ETHUSDT", fx.downtrend, W1_START, W1_END)
    return build_window_pack("w1", W1_START, W1_END, [btc, eth], SOURCES)


def v3_fields() -> V3PackFields:
    """V3's inputs for the two synthetic coins, both joining in 2020-10."""
    hours = (W1_END - FIRST) // HOUR
    paths = {"BTCUSDT": fx.uptrend, "ETHUSDT": fx.downtrend}
    spot = {symbol: fx.hourly(path, hours) for symbol, path in paths.items()}
    funding = {r.calc_time_ms: dict.fromkeys(SYMBOLS, r.rate) for r in fx.funding(FIRST, W1_END)}
    return V3PackFields(
        first_months=dict.fromkeys(SYMBOLS, "2020-10"),
        spot_bars={symbol: daily_bars(bars) for symbol, bars in spot.items()},
        spot_exclusions=dict.fromkeys(SYMBOLS, frozenset()),
        futures_exclusions=dict.fromkeys(SYMBOLS, frozenset()),
        futures_filters=dict.fromkeys(SYMBOLS, FILTERS),
        futures_hourly={s: fx.hourly(path, hours, wick=0.02) for s, path in paths.items()},
        funding=funding,
    )


@dataclass(frozen=True)
class World:
    reg: DriverRegistration
    w1: WindowPack
    w1_sha: str
    v3: V3Inputs
    v3_sha: str
    config_sha: str
    manifest_sha: str


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """Written W1, W0 and V3 packs, and a loaded synthetic registration of all 216 cells
    whose run-manifest pins them, with distinct hold and V3 adapter pins."""
    root = tmp_path_factory.mktemp("repo")
    built = {"w1": w1_pack(), "w0": window_pack("w0", W0_START, W0_END)}
    assert built["w1"].skipped_hours == (GAP,)
    shas = {wid: write_pack(pack, root / f"{wid}.json.gz") for wid, pack in built.items()}
    packs = {wid: read_pack(root / f"{wid}.json.gz", sha) for wid, sha in shas.items()}
    v3_sha = write_v3_pack(v3_fields(), root / "v3.json.gz")
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
    manifest = run_manifest(prepared, window_packs=shas, v3_pack=v3_sha)
    manifest_sha = write_run_manifest(manifest, manifest_path)
    document = registration_document(prepared.sha256, manifest_sha, fx_sha)
    document["windows"] = [window_document(packs["w1"])]
    document["reported_windows"] = [window_document(packs["w0"])]
    for arm in document["adapter_pins"]:
        if arm == "matched_spot_hold":
            document["adapter_pins"][arm] = HOLD_PIN
        elif arm.startswith("unchanged_v3_"):
            document["adapter_pins"][arm] = V3_PIN
    registration_path = config / "v3_1_registration.json"
    config_sha = write_json(registration_path, document)
    reg = load_registration(registration_path, manifest_path, repo_root=root)
    v3 = read_v3_pack(root / "v3.json.gz", reg.run_manifest.v3_pack)
    return World(reg, packs["w1"], shas["w1"], v3, v3_sha, config_sha, manifest_sha)


def cell_of(world: World, cell_id: str):
    (cell,) = [c for c in world.reg.cells if c.cell_id == cell_id]
    return cell


def capital_of(world: World, capital_id: str):
    (capital,) = [c for c in world.reg.registration.capitals if c.id == capital_id]
    return capital


def hold(world: World, cell_id: str, out_dir: Path, attempt_id: str = ATTEMPT) -> Path:
    cell = cell_of(world, cell_id)
    return run_hold_cell(cell, world.w1, world.reg, out_dir, attempt_id=attempt_id, repo_head=HEAD)


def v3(world: World, cell_id: str, picks: Path, out_dir: Path, attempt_id: str = ATTEMPT):
    cell = cell_of(world, cell_id)
    return run_v3_cell(
        cell, world.v3, picks, world.reg, out_dir, attempt_id=attempt_id, repo_head=HEAD
    )


def canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")


def attempt_record(world: World, cell_id: str, pack_sha256: str) -> bytes:
    return canonical(
        {
            "cell_id": cell_id,
            "attempt_id": ATTEMPT,
            "repo_head": HEAD,
            "code_pin": CODE_PIN,
            "config_pin": world.config_sha,
            "pack_sha256": pack_sha256,
            "data_pin": world.manifest_sha,
        }
    )


def stand_in(calls: list[int]):
    """Stands in for V3's frozen walk-forward: records a started and a finished training
    attempt around one short frozen replay, under a fresh random run-id prefix as V3's own
    does, and returns ``PICKS``."""

    def walk(decisions, filters, hourly, funding, *, record):
        calls.append(1)
        run_id = f"{uuid.uuid4().hex}-train-2020-12-R2L"
        start, end = W1_START - 2 * DAY, W1_START
        schedule = ((start, "R2L"),)
        record(
            Attempt(
                run_id,
                "training",
                "R2L",
                start,
                end,
                None,
                None,
                state="started",
                pick_schedule=schedule,
            )
        )
        result = replay_window(
            decisions,
            filters,
            hourly,
            funding,
            start,
            end,
            dict(schedule),
            multiple=2,
            cost_multiple=1,
        )
        record(Attempt(run_id, "training", "R2L", start, end, result, None, pick_schedule=schedule))
        return SimpleNamespace(picks=dict(PICKS), out_of_sample=result)

    return walk


def picks_once(world: World, out_dir: Path, calls: list[int], attempt_id: str = ATTEMPT) -> Path:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(baseline_v3, "run_walk_forward", stand_in(calls))
        return compute_v3_picks(world.v3, world.reg, out_dir, attempt_id=attempt_id, repo_head=HEAD)


@pytest.fixture(scope="module")
def picked(world: World, tmp_path_factory) -> tuple[Path, list[int]]:
    """The frozen picks, computed once for every V3 cell; the stand-in's calls."""
    calls: list[int] = []
    return picks_once(world, tmp_path_factory.mktemp("cells"), calls), calls


# --- the matched spot hold -------------------------------------------------------------


def test_hold_cell_on_a_synthetic_pack(world, tmp_path, monkeypatch):
    seen = []
    replay = run_baselines.replay_hold_baseline

    def spy(markets, **options):
        seen.append((markets, options, replay(markets, **options)))
        return seen[-1][2]

    monkeypatch.setattr(run_baselines, "replay_hold_baseline", spy)
    base = hold(world, HOLD_CELL, tmp_path)
    doubled = hold(world, "w1.matched_spot_hold.native.c2.owner_small", tmp_path)

    owner = capital_of(world, "owner_small")
    refs = (f"v31-pack:{world.w1_sha}", f"v31-run-manifest:{world.manifest_sha}")
    (markets, options, evidence), (doubled_markets, doubled_options, _) = seen
    # The adapter scales the rates by the cell's multiple, so both cells pass base costs.
    for given in (markets, doubled_markets):
        assert given == {
            c.symbol: HoldMarket(c.spot_hourly, c.spot_rules, cost_profile(1, "spot"))
            for c in world.w1.coins
        }
    assert options == {
        "start_ms": W1_START,
        "end_ms": W1_END,
        "initial": owner.initial_equity,
        "cost_multiple": 1,
        "source_refs": refs,
        "adapter_pin": HOLD_PIN,
        "skipped_hours": (GAP,),
        "capital_label": capital_label(owner),
    }
    assert doubled_options == {**options, "cost_multiple": 2}

    assert base.name == HOLD_CELL
    assert sorted(path.name for path in base.iterdir()) == [
        "attempt.json",
        "native_evidence.json",
        "outcome.json",
        "report.json",
    ]
    assert (base / "attempt.json").read_bytes() == attempt_record(world, HOLD_CELL, world.w1_sha)
    report = decode_report((base / "report.json").read_text(encoding="ascii"))
    outcome = decode_outcome((base / "outcome.json").read_text(encoding="ascii"))
    (w1,) = world.reg.registration.windows
    assert outcome.identity == RunIdentity(
        arm="matched_spot_hold",
        window="w1",
        capital="owner_small",
        cost_multiple=1,
        data_pin=w1.data_pin,
        cost_profile_pin=COST_PROFILE_PINS[1],
        start_ms=W1_START,
        end_ms=W1_END,
        code_pin=CODE_PIN,
        config_pin=world.config_sha,
        fx_pin=owner.fx_pin,
        observation_policy=POLICY_ID,
        adapter_pin=HOLD_PIN,
        scenario="native",
    )
    assert report == evidence.report and outcome.report_evidence.report == report
    assert outcome.complete and not outcome.failed and outcome.attempt_id == ATTEMPT
    assert outcome.capital_label == capital_label(owner)
    assert report.source_refs == refs and report.skipped_hours == (GAP,)
    assert {c.asset for c in report.contributions} == set(SYMBOLS)  # both coins were bought

    # The doubled cell pays the doubled fee rate once (0.2%), never scaled twice (0.4%).
    doubled_report = decode_report((doubled / "report.json").read_text(encoding="ascii"))
    for paid, rate in ((report, D("0.001")), (doubled_report, D("0.002"))):
        assert paid.contributions
        assert all(c.fees == c.turnover * rate for c in paid.contributions)
    doubled_outcome = decode_outcome((doubled / "outcome.json").read_text(encoding="ascii"))
    assert doubled_outcome.identity.cost_profile_pin == COST_PROFILE_PINS[2]

    native = json.loads((base / "native_evidence.json").read_bytes())
    assert native["evidence"] == {
        "arm": "matched_spot_hold",
        "native_label": "hold-native",
        "status": None,
        "liquidations": 0,
        "accounting_residual": str(evidence.accounting_residual),
        "accounting_explained": evidence.accounting_explained,
        "wallet_quantity_exact": True,
        "disclosures": list(evidence.disclosures),
        "native_marks": [
            [m.timestamp_ms, m.kind, str(m.equity), str(m.spot_value), str(m.futures_collateral)]
            for m in evidence.native
        ],
    }
    outcome_raw = (base / "outcome.json").read_bytes()
    assert native["outcome_sha256"] == hashlib.sha256(outcome_raw).hexdigest()
    assert (
        native["report_sha256"] == hashlib.sha256((base / "report.json").read_bytes()).hexdigest()
    )
    assert (native["cell_id"], native["arm"], native["adapter_pin"]) == (
        HOLD_CELL,
        "matched_spot_hold",
        HOLD_PIN,
    )


# --- the frozen V3 arms ----------------------------------------------------------------


def test_v3_picks_are_computed_once_and_reused(world, picked, tmp_path, monkeypatch):
    path, calls = picked
    directory = path.parent
    assert (path.name, directory.name, calls) == ("v3_picks.json", "v3_picks", [1])
    assert sorted(p.name for p in directory.iterdir()) == [
        "attempt.json",
        "attempts.jsonl",
        "v3_picks.json",
    ]
    attempt = json.loads((directory / "attempt.json").read_bytes())
    assert attempt == {
        "job": "v3_picks",
        "attempt_id": ATTEMPT,
        "repo_head": HEAD,
        "code_pin": CODE_PIN,
        "config_pin": world.config_sha,
        "pack_sha256": world.v3_sha,
        "data_pin": world.manifest_sha,
    }
    # V3's own attempt records, one canonical line each, without the walk's random prefix.
    journal = (directory / "attempts.jsonl").read_bytes()
    rows = [json.loads(line) for line in journal.splitlines()]
    assert journal == b"".join(canonical(row) + b"\n" for row in rows)
    started, finished = rows
    assert (started["run"], started["state"], started["result"]) == (
        "train-2020-12-R2L",
        "started",
        None,
    )
    assert (finished["run"], finished["state"], finished["error"]) == (
        "train-2020-12-R2L",
        "finished",
        None,
    )
    assert finished["pick_schedule"] == [[W1_START - 2 * DAY, "R2L"]]
    assert (finished["phase"], finished["multiple"], finished["cost_multiple"]) == (
        "training",
        2,
        1,
    )
    assert finished["result"]["reason"] is None
    assert D(finished["result"]["final_equity"]) > 0

    document = json.loads(path.read_bytes())
    assert path.read_bytes() == canonical(document)
    assert document == {
        "schema": "v3.1-v3-picks-1",
        "v3_pack_sha256": world.v3_sha,
        "run_manifest_sha256": world.manifest_sha,
        "attempts_sha256": hashlib.sha256(journal).hexdigest(),
        "picks": {str(stamp): rule for stamp, rule in PICKS.items()},
    }

    # Computed once: a second computation is refused before any training.
    before = snapshot(directory)
    monkeypatch.setattr(baseline_v3, "run_walk_forward", stand_in(calls))
    with pytest.raises(FileExistsError):
        compute_v3_picks(
            world.v3, world.reg, directory.parent, attempt_id="attempt-2", repo_head=HEAD
        )
    assert calls == [1] and snapshot(directory) == before

    # Reused: every V3 cell reads the same file, and nothing trains again.
    for cell_id in (SELECTOR_CELL, "w1.unchanged_v3_selector.native.c1.research", RULE_CELL):
        outcome = decode_outcome((v3(world, cell_id, path, tmp_path) / "outcome.json").read_text())
        assert outcome.identity.arm == cell_of(world, cell_id).arm
    assert calls == [1]

    # The same inputs give byte-identical files, though V3's run ids are random.
    again_dir = tmp_path / "again"
    again_dir.mkdir()
    with localcontext(Context(prec=5, capitals=0)):
        again = picks_once(world, again_dir, calls)
    assert calls == [1, 1]
    first = {name: data for name, (data, _) in snapshot(directory).items()}
    assert {name: data for name, (data, _) in snapshot(again.parent).items()} == first


def test_v3_cell_uses_the_shared_picks(world, picked, tmp_path, monkeypatch):
    path, _ = picked
    seen = []
    replay = run_baselines.replay_v3_baseline

    def spy(arm, inputs, **options):
        seen.append((arm, inputs, options, replay(arm, inputs, **options)))
        return seen[-1][3]

    monkeypatch.setattr(run_baselines, "replay_v3_baseline", spy)
    selector = v3(world, SELECTOR_CELL, path, tmp_path)
    rule = v3(world, RULE_CELL, path, tmp_path)

    owner, research = capital_of(world, "owner_small"), capital_of(world, "research")
    refs = (f"v3-pack:{world.v3_sha}", f"v31-run-manifest:{world.manifest_sha}")
    picks_ref = f"v3-picks:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    (arm, inputs, options, evidence), (rule_arm, rule_inputs, rule_options, _) = seen
    assert (arm, rule_arm) == (SELECTOR, "unchanged_v3_r2_long_only")
    assert inputs is world.v3 and rule_inputs is world.v3
    assert options == {
        "start_ms": W1_START,
        "end_ms": W1_END,
        "initial": owner.initial_equity,
        "cost_multiple": 2,
        "source_refs": (*refs, picks_ref),
        "adapter_pin": V3_PIN,
        "picks": {W1_START: "R2L", W1_START + DAY: "R3L"},
        "skipped_hours": (GAP,),
        "capital_label": capital_label(owner),
    }
    assert options["picks"] == window_picks(PICKS, W1_START, W1_END)
    # A fixed long-only rule takes no picks: the adapter replays its own rule.
    assert rule_options == {
        **options,
        "initial": research.initial_equity,
        "cost_multiple": 1,
        "source_refs": refs,
        "picks": None,
        "capital_label": "research_10000_usdt",
    }

    assert (selector / "attempt.json").read_bytes() == attempt_record(
        world, SELECTOR_CELL, world.v3_sha
    )
    outcome = decode_outcome((selector / "outcome.json").read_text(encoding="ascii"))
    report = decode_report((selector / "report.json").read_text(encoding="ascii"))
    (w1,) = world.reg.registration.windows
    assert outcome.identity == RunIdentity(
        arm=SELECTOR,
        window="w1",
        capital="owner_small",
        cost_multiple=2,
        data_pin=w1.data_pin,
        cost_profile_pin=COST_PROFILE_PINS[2],
        start_ms=W1_START,
        end_ms=W1_END,
        code_pin=CODE_PIN,
        config_pin=world.config_sha,
        fx_pin=owner.fx_pin,
        observation_policy=POLICY_ID,
        adapter_pin=V3_PIN,
        scenario="native",
    )
    assert report == evidence.report and outcome.report_evidence.report == report
    assert report.source_refs == (*refs, picks_ref) and report.skipped_hours == (GAP,)
    assert "v3_selector_frozen_picks_on_registered_window" in report.disclosures
    assert outcome.capital_label == capital_label(owner)
    assert outcome.complete and not outcome.failed and report.fees > 0  # the picks traded
    native = json.loads((selector / "native_evidence.json").read_bytes())
    assert native["evidence"]["native_label"] == "v3-native"
    assert len(native["evidence"]["native_marks"]) == len(evidence.native) > 0
    rule_outcome = decode_outcome((rule / "outcome.json").read_text(encoding="ascii"))
    assert rule_outcome.identity.capital == "research" and rule_outcome.identity.fx_pin is None


@pytest.mark.parametrize("damage", ["pack", "manifest", "rule", "stamp", "spaces", "schema"])
def test_v3_cell_refuses_picks_it_cannot_trust(world, picked, tmp_path, damage):
    path, _ = picked
    document = json.loads(path.read_bytes())
    if damage == "pack":
        document["v3_pack_sha256"] = "0" * 64
    elif damage == "manifest":
        document["run_manifest_sha256"] = "0" * 64
    elif damage == "rule":
        document["picks"][str(W1_START - DAY)] = "R9L"
    elif damage == "stamp":
        document["picks"]["01"] = "R1"
    elif damage == "schema":
        document["schema"] = "v3.1-v3-picks-0"
    raw = canonical(document)
    if damage == "spaces":
        raw = json.dumps(document, sort_keys=True).encode()
    bad = tmp_path / "picks" / "v3_picks.json"
    bad.parent.mkdir()
    bad.write_bytes(raw)
    out = tmp_path / "cells"
    out.mkdir()
    with pytest.raises(ValueError):
        v3(world, SELECTOR_CELL, bad, out)
    assert list(out.iterdir()) == []


# --- the protocol ----------------------------------------------------------------------


def test_baseline_cells_follow_the_claim_failure_outcome_protocol(
    world, picked, tmp_path, monkeypatch
):
    path, _ = picked
    order = []
    for module in (run_cell, run_baselines):

        def logged(target, raw, write=module._write):
            if target.name == "v3_picks.json":
                assert (target.parent / "attempts.jsonl").is_file()  # streamed beforehand
            order.append(target.name)
            write(target, raw)

        monkeypatch.setattr(module, "_write", logged)

    # Claim first, outcome last: a directory without outcome.json is incomplete.
    hold(world, HOLD_CELL, tmp_path)
    expected = ["attempt.json", "native_evidence.json", "report.json", "outcome.json"]
    assert order == expected
    order.clear()
    v3(world, RULE_CELL, path, tmp_path)
    assert order == expected
    order.clear()
    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    picks_once(world, picks_dir, [])
    assert order == ["attempt.json", "v3_picks.json"]
    monkeypatch.undo()

    # An attempt that raises after its claim keeps attempt.json and failure.json, then
    # the exception propagates; working code cannot run the cell there again.
    def broken(*args, **kwargs):
        raise RuntimeError("forced baseline failure")

    def failing_walk(decisions, filters, hourly, funding, *, record):
        start = W1_START - 2 * DAY
        record(
            Attempt(
                f"{uuid.uuid4().hex}-train-2020-12-R1",
                "training",
                "R1",
                start,
                W1_START,
                None,
                None,
                state="started",
                pick_schedule=((start, "R1"),),
            )
        )
        raise RuntimeError("forced baseline failure")

    failed = tmp_path / "failed"
    failed.mkdir()
    jobs = {
        HOLD_CELL: (run_baselines, "replay_hold_baseline", broken),
        RULE_CELL: (run_baselines, "replay_v3_baseline", broken),
        "v3_picks": (baseline_v3, "run_walk_forward", failing_walk),
    }
    failure = b'{"message":"forced baseline failure","type":"RuntimeError"}'

    def run_job(name: str, attempt_id: str) -> None:
        if name == HOLD_CELL:
            hold(world, HOLD_CELL, failed, attempt_id)
        elif name == RULE_CELL:
            v3(world, RULE_CELL, path, failed, attempt_id)
        else:
            compute_v3_picks(world.v3, world.reg, failed, attempt_id=attempt_id, repo_head=HEAD)

    for name, (module, attribute, replacement) in jobs.items():
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(module, attribute, replacement)
            with pytest.raises(RuntimeError, match="forced baseline failure"):
                run_job(name, ATTEMPT)
        directory = failed / name
        names = sorted(p.name for p in directory.iterdir())
        if name == "v3_picks":
            assert names == ["attempt.json", "attempts.jsonl", "failure.json"]
            (row,) = (directory / "attempts.jsonl").read_bytes().splitlines()
            assert json.loads(row)["state"] == "started"  # persisted before the failure
        else:
            assert names == ["attempt.json", "failure.json"]
        assert (directory / "failure.json").read_bytes() == failure
        before = snapshot(directory)
        with pytest.raises(FileExistsError):
            run_job(name, "attempt-2")
        assert snapshot(directory) == before


def test_baseline_runs_refuse_other_cells_and_inputs_before_writing(world, picked, tmp_path):
    path, _ = picked
    reg = world.reg
    hold_cell, rule_cell = cell_of(world, HOLD_CELL), cell_of(world, RULE_CELL)
    combined = cell_of(world, "w1.combined.olhc.c1.research")
    options = {"attempt_id": ATTEMPT, "repo_head": HEAD}
    with pytest.raises(ValueError, match="hold"):
        run_hold_cell(rule_cell, world.w1, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="V3"):
        run_v3_cell(hold_cell, world.v3, path, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="V3"):
        run_v3_cell(combined, world.v3, path, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="not registered"):
        run_hold_cell(replace(hold_cell, capital_id="other"), world.w1, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="not registered"):
        run_v3_cell(replace(rule_cell, cost_multiple=3), world.v3, path, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="pack window"):
        w0 = replace(world.w1, window_id="w0")
        run_hold_cell(hold_cell, w0, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="skipped hours"):
        run_hold_cell(hold_cell, replace(world.w1, skipped_hours=()), reg, tmp_path, **options)
    with pytest.raises(ValueError, match="V3 inputs"):
        run_v3_cell(rule_cell, world.w1, path, reg, tmp_path, **options)
    with pytest.raises(ValueError, match="V3 inputs"):
        compute_v3_picks(world.w1, reg, tmp_path, **options)
    for bad in ({"attempt_id": " "}, {"repo_head": "HEAD"}):
        arguments = {**options, **bad}
        with pytest.raises(ValueError, match="attempt|repo head"):
            run_hold_cell(hold_cell, world.w1, reg, tmp_path, **arguments)
        with pytest.raises(ValueError, match="attempt|repo head"):
            run_v3_cell(rule_cell, world.v3, path, reg, tmp_path, **arguments)
        with pytest.raises(ValueError, match="attempt|repo head"):
            compute_v3_picks(world.v3, reg, tmp_path, **arguments)
    with pytest.raises(FileNotFoundError):
        run_v3_cell(rule_cell, world.v3, tmp_path / "missing.json", reg, tmp_path, **options)
    assert list(tmp_path.iterdir()) == []


def test_baseline_cells_give_byte_identical_artifacts(world, picked, tmp_path):
    path, _ = picked
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for cell_id in (HOLD_CELL, SELECTOR_CELL):
        runs = []
        for out_dir, context in ((first, Context()), (second, Context(prec=6, capitals=0))):
            with localcontext(context):
                if cell_id == HOLD_CELL:
                    runs.append(hold(world, cell_id, out_dir))
                else:
                    runs.append(v3(world, cell_id, path, out_dir))
        files = [{name: data for name, (data, _) in snapshot(d).items()} for d in runs]
        assert files[0] == files[1] and len(files[0]) == 4
