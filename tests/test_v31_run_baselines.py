"""The baseline cells: the matched spot hold, the frozen V3 arms and the frozen minute
baselines (V0, V1, V2 and comparator D), each run once.

Synthetic only: the W1 pack is built from the shared market fixtures (labelled synthetic),
the V3 input pack from the same synthetic paths, and the registration with Task 6's test
helpers. V3's frozen walk-forward trains 18 months per quarter, which takes minutes even on
two synthetic coins, so a stand-in records real V3 attempts around one short frozen replay.
The minute cells read a tiny synthetic legacy dataset that the frozen fetch code stores
from a fake archive, laid out as ``backtest`` reads it. Nothing touches the network.
"""

import hashlib
import json
import math
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Context, localcontext
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import combined_market_fixtures as fx
import pytest
from test_backtest_loaders import FakeArchive
from test_full_stack import add_funding, add_klines, bar
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

from crypto_grid_bot.backtest.dataset import fetch_dataset, load_manifest, load_spec, write_manifest
from crypto_grid_bot.backtest.features import FeatureEngine
from crypto_grid_bot.backtest.jobs import SymbolMask, manifest_path, prepare_run, variant_policy
from crypto_grid_bot.backtest.replay import PATH_MODES, load_minutes
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.baseline_hold import HoldMarket
from crypto_grid_bot.combined.baseline_minute import MinuteJob, TrendJob
from crypto_grid_bot.combined.baseline_v3 import V3Inputs, window_picks
from crypto_grid_bot.combined.common_series import common_hourly_series
from crypto_grid_bot.combined.driver import run_baselines, run_cell
from crypto_grid_bot.combined.driver.packs import (
    WindowPack,
    build_window_pack,
    read_pack,
    write_pack,
)
from crypto_grid_bot.combined.driver.registration import (
    V1_VARIANTS,
    DriverRegistration,
    load_prepare_config,
    load_registration,
    minute_arms,
    run_manifest,
    write_run_manifest,
)
from crypto_grid_bot.combined.driver.run_baselines import (
    MINUTE_MANIFEST_PATH,
    MINUTE_PAIRS,
    compute_v3_picks,
    minute_version,
    run_hold_cell,
    run_minute_cell,
    run_v3_cell,
)
from crypto_grid_bot.combined.driver.serialize import decode_outcome, decode_report
from crypto_grid_bot.combined.driver.v3_pack import V3PackFields, read_v3_pack, write_v3_pack
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS, cost_profile
from crypto_grid_bot.combined.experiment import RunIdentity, capital_label
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.simulation.runner import MODE_SWITCH
from crypto_grid_bot.strategy.daily_sma import close_above_sma
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


# --- the frozen minute baselines ---------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]
BOT_CONFIG = REPO / "config/default.toml"  # the frozen runs' --config default
MINUTE = 60_000
MAY_2020 = int(datetime(2020, 5, 1, tzinfo=UTC).timestamp() * 1000)
NOV_2020 = int(datetime(2020, 11, 1, tzinfo=UTC).timestamp() * 1000)
DEC_2020 = int(datetime(2020, 12, 1, tzinfo=UTC).timestamp() * 1000)
M1_START = int(datetime(2020, 12, 3, tzinfo=UTC).timestamp() * 1000)  # the minute world's W1
M1_END = M1_START + 2 * DAY
M0_START = int(datetime(2020, 11, 28, tzinfo=UTC).timestamp() * 1000)
MINUTE_ADAPTER_PIN = "8" * 64
MINUTE_OFFSETS = (0, 30, 59)  # the minutes each synthetic hour holds
W1_MINUTES = 2 * 24 * len(MINUTE_OFFSETS)  # each pair's minutes inside the minute W1
MASKED_HOUR = M1_START + 5 * HOUR
IDLE_ISSUES = {
    "metric_unavailable:return_drawdown:zero_drawdown",
    "metric_unavailable:sharpe:zero_variance",
}
BASKET = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT")
V1_NAMES = dict(zip(V1_VARIANTS, ("A", "B", "C", "E", "F", "G", "C+G", "H", "C+H"), strict=True))
# Each minute version's (comparator D, frozen variant): None is V0, MODE_SWITCH is V2.
VERSIONS = {
    "v0_grid": (False, None),
    **{f"v1_{variant}_grid": (False, name) for variant, name in V1_NAMES.items()},
    "v2_grid": (False, MODE_SWITCH),
    "d_trend": (True, None),
}
# A full-range-shaped synthetic spec: the frozen traded pairs, BTCUSDT as the proxy, five
# basket members (the frozen breadth vote needs five), daily history long enough for A's
# 200 completed bars, and the frozen pricing inputs.
LEGACY_SPEC = """name = "minute-cells"
purpose = "synthetic minute-cell wiring test"
traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT"]
daily_warmup_start = "2020-05"
warmup_start = "2020-11"
start = "2020-12"
end = "2020-12"
initial_quote = "100"
# Binance base rate, as in full-range-2017-2024.
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""


def sine(hours_on: float) -> float:
    """The replay tests' daily sine around 1.0, at any time ``hours_on`` from 2020-11-01."""
    return 1.0 + 0.08 * math.sin(2 * math.pi * (hours_on + 8) / 24)


def legacy_dataset(work: Path) -> Path:
    """A synthetic legacy dataset under ``work``: its spec, the manifest the frozen fetch
    writes, and the hash-checked archives under ``work/data``; returns the spec's path.

    Hourly bars from 2020-11-01 to 2020-12-05 for the five basket members, rising daily
    bars from 2020-05-01, BTCUSDT's funding for 2020-11 and 2020-12, and minutes from
    2020-12-02 to 2020-12-05 for the three pairs: a day on each side of W1, which the cell
    must not replay. To keep the replays short, each hour holds only its minutes
    ``MINUTE_OFFSETS``: its opening minute, which marks the hour, and its last, so W1's final
    minute is there. Every pair has the same bars."""
    hourly = []
    for i in range(35 * 24):
        o, c = sine(i - 1), sine(i)
        hourly.append(bar(NOV_2020 + i * HOUR, o, max(o, c) * 1.004, min(o, c) * 0.996, c))
    minutes = []
    for hour in range(4 * 24):
        for offset in MINUTE_OFFSETS:
            start = DEC_2020 + DAY + hour * HOUR + offset * MINUTE
            at = (start - NOV_2020) / HOUR
            o, c = sine(at - 1), sine(at - 1 + 1 / 60)
            minutes.append(bar(start, o, max(o, c) * 1.0005, min(o, c) * 0.9995, c))
    days = [
        bar(MAY_2020 + i * DAY, *(0.5 + i / 500 + d for d in (0, 0.01, -0.01, 0)))
        for i in range(219)
    ]
    archive = FakeArchive()
    for pair in MINUTE_PAIRS:
        add_klines(archive, pair, "1m", MINUTE, minutes)
        add_klines(archive, pair, "1d", DAY, days)
    for symbol in BASKET:
        add_klines(archive, symbol, "1h", HOUR, hourly)
    funding = [add_funding(archive, NOV_2020, 90), add_funding(archive, DEC_2020, 93)]
    filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.0001"}
    filters |= {"quantity_step": "0.1", "min_notional": "5"}
    spec_path = work / "minute-cells.toml"
    spec_path.write_text(LEGACY_SPEC)
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: filters,
        previous={"files": funding},
    )
    assert all(entry["status"] == "ok" for entry in manifest["files"])
    write_manifest(manifest_path(spec_path), manifest)
    return spec_path


@dataclass(frozen=True)
class MinuteWorld:
    reg: DriverRegistration
    spec_path: Path
    data_dir: Path
    legacy_sha: str
    config_sha: str
    manifest_sha: str


@pytest.fixture(scope="module")
def minute_world(tmp_path_factory) -> MinuteWorld:
    """The synthetic legacy dataset, and a loaded registration of all 216 cells whose W1 is
    2020-12-03 to 2020-12-05 and whose run-manifest pins the dataset's manifest under the
    full-range path, with a distinct minute adapter pin."""
    spec_path = legacy_dataset(tmp_path_factory.mktemp("legacy"))
    legacy_sha = hashlib.sha256(manifest_path(spec_path).read_bytes()).hexdigest()
    root = tmp_path_factory.mktemp("minute-repo")
    config = root / "config"
    config.mkdir()
    shutil.copyfile(MENU, config / "v3_1_experiment_menu.json")
    windows = {"w1": (M1_START, M1_END), "w0": (M0_START, M0_START + 2 * DAY)}
    prepare = prepare_document()
    prepare["windows"] = [
        {"id": wid, "start_ms": start, "end_ms": end, "symbols": SYMBOLS}
        for wid, (start, end) in windows.items()
    ]
    assert MINUTE_MANIFEST_PATH in prepare["data_manifests"]
    prepare["data_manifests"][MINUTE_MANIFEST_PATH] = legacy_sha
    write_json(config / "v3_1_prepare.json", prepare)
    fx_sha = write_json(root / FX_PATH, fx_document())
    prepared = load_prepare_config(config / "v3_1_prepare.json")
    manifest_file = config / "v3_1_run_manifest.json"
    packs = {"w1": "1" * 64, "w0": "2" * 64}
    manifest_sha = write_run_manifest(
        run_manifest(prepared, window_packs=packs, v3_pack="3" * 64), manifest_file
    )
    document = registration_document(prepared.sha256, manifest_sha, fx_sha)
    document["windows"], document["reported_windows"] = (
        [{"id": wid, "start_ms": start, "end_ms": end, "skipped_hours": []}]
        for wid, (start, end) in windows.items()
    )
    for arm in minute_arms(V1_VARIANTS):
        document["adapter_pins"][arm] = MINUTE_ADAPTER_PIN
    registration_path = config / "v3_1_registration.json"
    config_sha = write_json(registration_path, document)
    reg = load_registration(registration_path, manifest_file, repo_root=root)
    data_dir = spec_path.parent / "data"
    return MinuteWorld(reg, spec_path, data_dir, legacy_sha, config_sha, manifest_sha)


def unmasked(spec_path, data_dir, symbol):
    """Stands in for the frozen ``mask_job`` as the frozen CLI's own tests do
    (``test_full_stack.no_mask``): a mask of None for every symbol. The real mask would
    mask almost the whole evaluation month, since the dataset holds days of minutes."""
    return SymbolMask(symbol, None, ())


@dataclass(frozen=True)
class MinuteRun:
    directory: Path
    arm: str
    jobs: dict
    options: dict
    evidence: object


def minute(world: MinuteWorld, cell_id: str, out_dir: Path, attempt_id: str = ATTEMPT, reg=None):
    reg = world.reg if reg is None else reg
    (cell,) = [c for c in reg.cells if c.cell_id == cell_id]
    return run_minute_cell(
        cell,
        world.data_dir,
        reg,
        out_dir,
        attempt_id=attempt_id,
        repo_head=HEAD,
        spec_path=world.spec_path,
        config_path=BOT_CONFIG,
    )


def recording(real, seen: list):
    """``real``, a frozen minute adapter, recording each call and its evidence in ``seen``."""

    def spy(arm, jobs, **options):
        seen.append((arm, jobs, options, real(arm, jobs, **options)))
        return seen[-1][3]

    return spy


def spied_minute(patch, world, cell_id, out_dir, mask=unmasked, reg=None) -> MinuteRun:
    """Run one minute cell with ``mask`` for the frozen mask job, recording what the cell
    hands its frozen adapter."""
    seen: list = []
    for name in ("replay_grid_baseline", "replay_trend_baseline"):
        patch.setattr(run_baselines, name, recording(getattr(run_baselines, name), seen))
    patch.setattr(run_baselines, "mask_job", mask)
    directory = minute(world, cell_id, out_dir, reg=reg)
    ((arm, jobs, options, evidence),) = seen
    return MinuteRun(directory, arm, jobs, options, evidence)


# Every version in both path modes at base cost and research capital; D with the
# owner_small capital; V0 and D doubled.
SPIED_CELLS = (
    *(
        f"w1.matched_{base}_{mode}.native.c1.research"
        for base in ("v0_grid", "v1_g_grid", "v2_grid", "d_trend")
        for mode in PATH_MODES
    ),
    "w1.matched_d_trend_high_first.native.c1.owner_small",
    "w1.matched_d_trend_high_first.native.c2.research",
    "w1.matched_v0_grid_low_first.native.c2.research",
)


@pytest.fixture(scope="module")
def minute_runs(minute_world, tmp_path_factory) -> dict[str, MinuteRun]:
    """``SPIED_CELLS``, each run once."""
    out_dir = tmp_path_factory.mktemp("minute-cells")
    runs = {}
    for cell_id in SPIED_CELLS:
        with pytest.MonkeyPatch.context() as patch:
            runs[cell_id] = spied_minute(patch, minute_world, cell_id, out_dir)
    return runs


def window_minutes(world: MinuteWorld, pair: str) -> tuple:
    """The pair's minutes the frozen loader reads, inside W1."""
    manifest = load_manifest(manifest_path(world.spec_path))
    minutes = load_minutes(world.data_dir, manifest, pair)
    return tuple(bar for bar in minutes if M1_START <= bar.open_ms < M1_END)


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_minute_cell_for_each_version_and_both_path_modes(minute_world, minute_runs):
    # Every registered minute arm names its frozen version and its path mode.
    arms = minute_arms(V1_VARIANTS)
    assert len(arms) == 24
    for arm in arms:
        version = minute_version(arm)
        (mode,) = [mode for mode in PATH_MODES if arm.endswith(f"_{mode}")]
        base = arm.removeprefix("matched_").removesuffix(f"_{mode}")
        assert (version.arm, version.path_mode) == (arm, mode)
        assert (version.trend, version.variant) == VERSIONS[base]
        if not version.trend:
            variant_policy(version.variant)  # a frozen variant name
    for other in ("combined", "matched_spot_hold", "matched_v1_d_grid_high_first"):
        with pytest.raises(ValueError, match="minute"):
            minute_version(other)

    world = minute_world
    research = capital_of(world, "research")
    refs = (f"legacy-manifest:{world.legacy_sha}", f"v31-run-manifest:{world.manifest_sha}")
    (w1,) = world.reg.registration.windows
    for base in ("v0_grid", "v1_g_grid", "v2_grid", "d_trend"):
        trend, variant = VERSIONS[base]
        for mode in PATH_MODES:
            arm = f"matched_{base}_{mode}"
            cell_id = f"w1.{arm}.native.c1.research"
            ran = minute_runs[cell_id]
            assert ran.arm == arm and tuple(ran.jobs) == MINUTE_PAIRS
            assert ran.options == {
                "start_ms": M1_START,
                "end_ms": M1_END,
                "initial": research.initial_equity,
                "source_refs": refs,
                "adapter_pin": MINUTE_ADAPTER_PIN,
                "skipped_hours": (),
                "capital_label": "research_10000_usdt",
            }
            for pair, job in ran.jobs.items():
                # At base cost a job is the frozen job setup's own, in the cell's path mode.
                frozen = prepare_run(
                    world.spec_path,
                    BOT_CONFIG,
                    world.data_dir,
                    pair,
                    mode,
                    not trend,
                    basket=not trend,
                )
                assert job.run == frozen.run and job.run.path_mode == mode
                assert (job.window, job.masked, job.days_skipped_for_masks) == (
                    (M1_START, M1_END),
                    frozenset(),
                    0,
                )
                # Only W1's minutes, though the archive holds a day on each side.
                assert tuple(job.minutes) == window_minutes(world, pair)
                assert len(job.minutes) == W1_MINUTES
                if trend:
                    assert type(job) is TrendJob
                    assert job.evaluated.__func__ is FeatureEngine.warmed
                    assert job.evaluated(M1_START) is frozen.features.warmed(M1_START) is True
                    # D's closes are the pair's daily bars: rising, so D holds.
                    assert close_above_sma(job.closes, M1_START, 50) is True
                else:
                    assert type(job) is MinuteJob
                    assert job.policy == variant_policy(variant)
                    assert job.config == frozen.config
                    assert job.features.at(M1_START) == frozen.features.at(M1_START)
                    assert (job.daily, job.hourly) == (frozen.daily, frozen.hourly)
                    if base == "v1_g_grid":
                        # G reads BTCUSDT's funding for every pair, as the frozen job does.
                        assert job.funding is not None and len(job.funding) == 90 + 93
                    else:
                        assert job.funding is None
            outcome = decode_outcome((ran.directory / "outcome.json").read_text())
            report = decode_report((ran.directory / "report.json").read_text())
            assert outcome.identity == RunIdentity(
                arm=arm,
                window="w1",
                capital="research",
                cost_multiple=1,
                data_pin=w1.data_pin,
                cost_profile_pin=COST_PROFILE_PINS[1],
                start_ms=M1_START,
                end_ms=M1_END,
                code_pin=CODE_PIN,
                config_pin=world.config_sha,
                fx_pin=None,
                observation_policy=POLICY_ID,
                adapter_pin=MINUTE_ADAPTER_PIN,
                scenario="native",
            )
            assert ran.evidence.status is None, report.issues
            assert report == ran.evidence.report and report.source_refs == refs
            # Every boundary is marked. A grid the frozen gate keeps idle on this synthetic
            # market has a flat equity, so only its ratio metrics are unavailable.
            assert report.structural_complete and not outcome.failed, report.issues
            assert set(report.issues) <= IDLE_ISSUES
            assert outcome.complete is (not report.issues)
            assert [b.timestamp_ms for b in report.policy_evidence.boundaries] == list(
                range(M1_START, M1_END + HOUR, HOUR)
            )
            assert (ran.directory / "attempt.json").read_bytes() == canonical(
                {
                    "cell_id": cell_id,
                    "attempt_id": ATTEMPT,
                    "repo_head": HEAD,
                    "code_pin": CODE_PIN,
                    "config_pin": world.config_sha,
                    "pack_sha256": world.legacy_sha,
                    "data_pin": world.manifest_sha,
                }
            )
            native = json.loads((ran.directory / "native_evidence.json").read_bytes())
            assert native["evidence"]["native_label"] == (
                "minute-trend-d-native" if trend else "minute-grid-native"
            )
            inputs = native["minute_inputs"]
            assert inputs["legacy_manifest_sha256"] == world.legacy_sha
            assert inputs["dataset_spec_sha256"] == sha_of(world.spec_path)
            assert inputs["bot_config_sha256"] == sha_of(BOT_CONFIG)
            assert inputs["version"] == {"trend": trend, "variant": variant}
            assert sorted(inputs["pairs"]) == list(MINUTE_PAIRS)
            for described in inputs["pairs"].values():
                assert described["path_mode"] == mode
                assert described["gated"] is (not trend)
                assert described["minutes"] == W1_MINUTES
    # D traded: it holds the pairs through W1, and its comparison is complete.
    for mode in PATH_MODES:
        d_run = minute_runs[f"w1.matched_d_trend_{mode}.native.c1.research"]
        assert d_run.evidence.report.fees > 0 and not d_run.evidence.report.issues


def test_minute_cell_capital_split_remainder_is_disclosed(minute_world, minute_runs):
    research = minute_runs["w1.matched_d_trend_high_first.native.c1.research"].evidence.report
    owner_run = minute_runs["w1.matched_d_trend_high_first.native.c1.owner_small"]
    owner = owner_run.evidence.report
    # 10,000 USDT over three pairs: each gets 3333.33333333 and 0.00000001 stays cash.
    assert "equal_capital_share_per_pair" in research.disclosures
    assert "minute_baseline_capital_remainder_cash:0.00000001" in research.disclosures
    assert research.equity_points[0].equity == D(10000)
    assert research.capital_label == "research_10000_usdt"
    nets = {c.asset: c.gross_pnl - c.fees for c in research.contributions}
    assert sorted(nets) == list(MINUTE_PAIRS)
    # The uninvested remainder is in the final equity besides the three pairs' own.
    finals = sum((D("3333.33333333") + net for net in nets.values()), D(0))
    assert research.final_equity == finals + D("0.00000001")
    # EUR 100 at 1.0389 is 103.89 USDT: 34.63 each, an exact split, so no remainder.
    capital = capital_of(minute_world, "owner_small")
    assert owner.equity_points[0].equity == capital.initial_equity == D("103.89")
    assert owner.capital_label == capital_label(capital)
    assert not [d for d in owner.disclosures if d.startswith("minute_baseline_capital_remainder")]
    assert owner_run.options["initial"] == D("103.89")
    outcome = decode_outcome((owner_run.directory / "outcome.json").read_text())
    assert outcome.identity.capital == "owner_small" and outcome.identity.fx_pin == capital.fx_pin


def test_minute_cell_doubles_costs_with_the_fill_trigger_at_base_slippage(minute_runs):
    base = minute_runs["w1.matched_v0_grid_low_first.native.c1.research"]
    doubled = minute_runs["w1.matched_v0_grid_low_first.native.c2.research"]
    for pair in MINUTE_PAIRS:
        b, d = base.jobs[pair].run, doubled.jobs[pair].run
        assert (b.rules.fee_rate, b.rules.taker_fee, b.rules.slippage_rate) == (
            D("0.001"),
            D("0.001"),
            D("0.0005"),
        )
        assert b.rules.fill_trigger == D("0.0005")
        # Maker, taker and slippage doubled; the fill trigger stays at base slippage, so
        # only the costs change; the spread, path, gate and every filter are unchanged.
        assert (d.rules.fee_rate, d.rules.taker_fee, d.rules.slippage_rate) == (
            D("0.002"),
            D("0.002"),
            D("0.001"),
        )
        assert d.rules.fill_trigger == D("0.0005")
        assert replace(d, rules=b.rules) == b and d.spread == D("0.0005")
        assert replace(d.rules, fee_rate=D("0.001"), slippage_rate=D("0.0005")) == replace(
            b.rules, fill_trigger_rate=D("0.0005")
        )
        # The frozen grid prices its own round trip from the doubled costs.
        assert doubled.jobs[pair].features._cost == float(2 * (D("0.003")) + d.spread)
        assert base.jobs[pair].features._cost == float(2 * (D("0.0015")) + b.spread)
        assert tuple(doubled.jobs[pair].minutes) == tuple(base.jobs[pair].minutes)
    outcome = decode_outcome((doubled.directory / "outcome.json").read_text())
    assert outcome.identity.cost_profile_pin == COST_PROFILE_PINS[2]
    described = json.loads((doubled.directory / "native_evidence.json").read_bytes())
    pairs = described["minute_inputs"]["pairs"]
    doubled_costs = {
        "maker_fee": "0.002",
        "taker_fee": "0.002",
        "slippage": "0.001",
        "fill_trigger": "0.0005",
        "spread": "0.0005",
    }
    assert {name: pairs[name]["costs"] for name in MINUTE_PAIRS} == dict.fromkeys(
        MINUTE_PAIRS, doubled_costs
    )

    # Comparator D pays the taker fee on every fill: twice the rate at doubled cost.
    for cost, rate in ((1, D("0.001")), (2, D("0.002"))):
        ran = minute_runs[f"w1.matched_d_trend_high_first.native.c{cost}.research"]
        contributions = ran.evidence.report.contributions
        assert contributions and all(c.turnover > 0 for c in contributions)
        assert all(c.fees == c.turnover * rate for c in contributions)


@pytest.mark.parametrize("skipped", [False, True], ids=["unregistered", "registered"])
def test_a_masked_hour_drops_its_minutes_and_needs_a_registered_skip(
    minute_world, tmp_path, monkeypatch, skipped
):
    # The frozen mask drops a masked hour's minutes, so no opening quote marks that hour:
    # the comparison is complete only if the registration skips the hour for everyone.
    calls = []

    def masked(spec_path, data_dir, symbol):
        calls.append((spec_path, data_dir, symbol))
        return SymbolMask(symbol, frozenset({MASKED_HOUR}) if symbol == "BTCUSDT" else None, ())

    reg = minute_world.reg
    if skipped:
        (w1,) = reg.registration.windows
        windows = (replace(w1, skipped_hours=(MASKED_HOUR,)),)
        reg = replace(reg, registration=replace(reg.registration, windows=windows))
    # Comparator D trades this market, so only the boundaries decide its completeness.
    ran = spied_minute(
        monkeypatch,
        minute_world,
        "w1.matched_d_trend_high_first.native.c1.research",
        tmp_path,
        mask=masked,
        reg=reg,
    )
    # Every symbol whose data reaches a decision is masked once, on the frozen spec.
    assert calls == [(minute_world.spec_path, minute_world.data_dir, s) for s in BASKET]
    btc = ran.jobs["BTCUSDT"]
    assert btc.masked == frozenset({MASKED_HOUR}) and btc.days_skipped_for_masks == 1
    assert [b.open_ms for b in btc.minutes] == [
        b.open_ms
        for b in window_minutes(minute_world, "BTCUSDT")
        if not MASKED_HOUR <= b.open_ms < MASKED_HOUR + HOUR
    ]
    assert ran.jobs["ETHUSDT"].masked == frozenset()
    assert len(ran.jobs["ETHUSDT"].minutes) == W1_MINUTES
    report = decode_report((ran.directory / "report.json").read_text())
    outcome = decode_outcome((ran.directory / "outcome.json").read_text())
    stamps = [b.timestamp_ms for b in report.policy_evidence.boundaries]
    assert MASKED_HOUR not in stamps and len(stamps) == 2 * 24
    assert report.skipped_hours == ((MASKED_HOUR,) if skipped else ())
    assert outcome.complete, report.issues  # the cell's own evidence is whole either way
    # The comparison's common hourly series needs every hour the registration schedules.
    series = {
        "start_ms": M1_START,
        "end_ms": M1_END,
        "skipped_hours": report.skipped_hours,
    }
    if skipped:
        common = common_hourly_series(report.equity_points, report.policy_evidence, **series)
        assert MASKED_HOUR not in [point.timestamp_ms for point in common.points]
    else:
        with pytest.raises(ValueError):
            common_hourly_series(report.equity_points, report.policy_evidence, **series)
    described = json.loads((ran.directory / "native_evidence.json").read_bytes())
    pairs = described["minute_inputs"]["pairs"]
    assert pairs["BTCUSDT"]["masked_hours_in_window"] == [MASKED_HOUR]
    assert pairs["ETHUSDT"]["masked_hours_in_window"] == []


def test_minute_cell_follows_the_claim_failure_outcome_protocol(
    minute_world, tmp_path, monkeypatch
):
    monkeypatch.setattr(run_baselines, "mask_job", unmasked)
    order = []
    write = run_baselines._write

    def logged(target, raw):
        order.append(target.name)
        write(target, raw)

    # Claim first, outcome last: a directory without outcome.json is incomplete.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run_baselines, "_write", logged)
        patch.setattr(run_cell, "_write", logged)
        minute(minute_world, "w1.matched_d_trend_low_first.native.c1.research", tmp_path)
    assert order == ["attempt.json", "native_evidence.json", "report.json", "outcome.json"]

    # An attempt that raises after its claim keeps attempt.json and failure.json, then the
    # exception propagates; working code cannot run the cell there again.
    def broken(*args, **kwargs):
        raise RuntimeError("forced minute failure")

    failed = tmp_path / "failed"
    failed.mkdir()
    grid_cell = "w1.matched_v2_grid_low_first.native.c2.owner_small"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run_baselines, "replay_grid_baseline", broken)
        with pytest.raises(RuntimeError, match="forced minute failure"):
            minute(minute_world, grid_cell, failed)
    directory = failed / grid_cell
    assert sorted(p.name for p in directory.iterdir()) == ["attempt.json", "failure.json"]
    failure = b'{"message":"forced minute failure","type":"RuntimeError"}'
    assert (directory / "failure.json").read_bytes() == failure
    before = snapshot(directory)
    with pytest.raises(FileExistsError):
        minute(minute_world, grid_cell, failed, attempt_id="attempt-2")
    assert snapshot(directory) == before

    # A legacy archive missing from the dataset is a failure after the claim, recorded.
    broken_data = tmp_path / "data"
    shutil.copytree(minute_world.data_dir, broken_data)
    klines = broken_data / "binance/data/spot/monthly/klines"
    (klines / "XRPUSDT/1m/XRPUSDT-1m-2020-12.zip").unlink()
    damaged = replace(minute_world, data_dir=broken_data)
    e_cell = "w1.matched_v1_e_grid_high_first.native.c1.research"
    with pytest.raises(OSError):
        minute(damaged, e_cell, failed)
    assert sorted(p.name for p in (failed / e_cell).iterdir()) == ["attempt.json", "failure.json"]


def test_minute_cell_refuses_other_cells_and_inputs_before_writing(minute_world, tmp_path):
    world = minute_world
    reg = world.reg
    cell_id = "w1.matched_v0_grid_high_first.native.c1.research"
    (cell,) = [c for c in reg.cells if c.cell_id == cell_id]
    hold_cell = next(c for c in reg.cells if c.kind == "hold")
    out_dir = tmp_path / "cells"
    out_dir.mkdir()

    def run(c=cell, r=reg, spec_path=world.spec_path, **changes):
        arguments = {"attempt_id": ATTEMPT, "repo_head": HEAD, **changes}
        return run_minute_cell(
            c, world.data_dir, r, out_dir, spec_path=spec_path, config_path=BOT_CONFIG, **arguments
        )

    with pytest.raises(ValueError, match="minute"):
        run(hold_cell)
    with pytest.raises(ValueError, match="not registered"):
        run(replace(cell, capital_id="other"))
    for bad in ({"attempt_id": " "}, {"repo_head": "HEAD"}):
        with pytest.raises(ValueError, match="attempt|repo head"):
            run(**bad)

    # A dataset whose manifest is not the one the run-manifest pins.
    other = tmp_path / "other"
    other.mkdir()
    shutil.copyfile(world.spec_path, other / world.spec_path.name)
    manifest = json.loads(manifest_path(world.spec_path).read_bytes())
    manifest["created_at"] = "another fetch"
    (other / manifest_path(world.spec_path).name).write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="run-manifest"):
        run(spec_path=other / world.spec_path.name)
    unpinned = replace(
        reg,
        run_manifest=replace(
            reg.run_manifest,
            data_manifests=tuple(
                pin for pin in reg.run_manifest.data_manifests if pin.path != MINUTE_MANIFEST_PATH
            ),
        ),
    )
    with pytest.raises(ValueError, match="run-manifest"):
        run(r=unpinned)

    # A spec of another shape than the frozen one: other pairs, other base costs, no daily
    # history, or an evaluation that does not cover W1.
    original = world.spec_path.read_text()
    for old, new, message in (
        ('"ETHUSDT", "XRPUSDT"]\nmarket', '"ETHUSDT"]\nmarket', "pairs"),
        ('fee_rate = "0.001"', 'fee_rate = "0.0009"', "base cost"),
        ('slippage_rate = "0.0005"', 'slippage_rate = "0.001"', "base cost"),
        ('daily_warmup_start = "2020-05"\n', "", "daily"),
        ('start = "2020-12"\nend = "2020-12"', 'start = "2021-01"\nend = "2021-01"', "evaluation"),
    ):
        changed = tmp_path / "changed" / message.replace(" ", "-") / str(len(new))
        changed.mkdir(parents=True)
        text = original.replace(old, new)
        assert text != original
        spec_path = changed / world.spec_path.name
        spec_path.write_text(text)
        shutil.copyfile(manifest_path(world.spec_path), manifest_path(spec_path))
        with pytest.raises(ValueError, match=message):
            run(spec_path=spec_path)
    assert list(out_dir.iterdir()) == []


def test_minute_cells_give_byte_identical_artifacts(
    minute_world, minute_runs, tmp_path, monkeypatch
):
    # The doubled cell builds its cost spec in a temporary directory; nothing of it shows.
    cell_id = "w1.matched_v0_grid_low_first.native.c2.research"
    monkeypatch.setattr(run_baselines, "mask_job", unmasked)
    with localcontext(Context(prec=6, capitals=0)):
        again = minute(minute_world, cell_id, tmp_path)
    first = {name: data for name, (data, _) in snapshot(minute_runs[cell_id].directory).items()}
    assert {name: data for name, (data, _) in snapshot(again).items()} == first
    assert len(first) == 4
