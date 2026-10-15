"""The V3.1 registration: its config files, the run-manifest, adapter pins and the cells.

Synthetic files only, written under ``tmp_path``; the one committed file read is the arm
menu. The adapter-pin test builds its own tiny git repository. Nothing touches the network.
"""

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import fields, replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.combined.driver.registration import (
    CAPITAL_IDS,
    PrepareConfig,
    adapter_pins,
    check_registration,
    load_prepare_config,
    load_registration,
    required_cells,
    run_manifest,
    write_run_manifest,
)
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS
from crypto_grid_bot.combined.experiment import CAPITALS as EXPERIMENT_CAPITALS
from crypto_grid_bot.combined.experiment import (
    SCENARIOS,
    _registration_errors,
    capital_label,
    required_baselines,
)
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.combined.report import CAPITAL_LABELS

REPO = Path(__file__).resolve().parents[1]
MENU = REPO / "config/v3_1_experiment_menu.json"
HOUR = 3_600_000
DAY = 24 * HOUR
W1_START = 1_625_097_600_000  # 2021-07-01 00:00 UTC
W0_START = 1_583_020_800_000  # 2020-03-01 00:00 UTC
END = 1_735_689_600_000  # 2025-01-01 00:00 UTC, the reserved boundary
W1_SKIPPED = [W1_START + 5 * HOUR, W1_START + 30 * HOUR]
TEN = ["ADAUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT"]
TEN += ["LINKUSDT", "LTCUSDT", "SOLUSDT", "TRXUSDT", "XRPUSDT"]
EIGHT = [symbol for symbol in TEN if symbol not in ("DOGEUSDT", "SOLUSDT")]
V1 = ("a", "b", "c", "e", "f", "g", "cg", "h", "ch")
COMPONENTS = (
    "spot_trend",
    "futures_trend",
    "futures_trend_long_only",
    "spot_grid",
    "combined",
    "combined_without_continuation",
    "combined_without_full_short_qualification",
    "combined_without_discretionary_trailing",
    "combined_without_funding_admission",
    "combined_without_recovery",
)
V3 = ("unchanged_v3_selector", *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)))
MINUTE = tuple(
    f"matched_{base}_{mode}"
    for base in ("v0_grid", *(f"v1_{v}_grid" for v in V1), "v2_grid", "d_trend")
    for mode in ("high_first", "low_first")
)
MENU_ARMS = json.loads(MENU.read_text(encoding="utf-8"))["arms"]
ARMS = tuple(
    arm for item in MENU_ARMS for arm in (MINUTE if item == "matched_spot_baselines" else (item,))
)
ABBREVIATION = {"open_low_high_close": "olhc", "open_high_low_close": "ohlc", "native": "native"}
# The owner's three USDT capitals (2026-10-14), in cell order, with their amounts.
CAPITALS = ("research", "medium", "small")
AMOUNTS = {"research": "10000", "medium": "1000", "small": "100"}
PACKS = {"w1": "1" * 64, "w0": "2" * 64}
V3_PACK = "3" * 64
CODE_PIN = "4" * 40
CELL_ID = re.compile(r"[a-z0-9._-]+")


def kind(arm: str) -> str:
    if arm in COMPONENTS:
        return "v31"
    if arm in V3:
        return "v3"
    if arm == "matched_spot_hold":
        return "hold"
    assert arm in MINUTE
    return "minute"


def cell(window: str, arm: str, scenario: str, cost: int, capital: str) -> dict[str, Any]:
    return {
        "cell_id": f"{window}.{arm}.{ABBREVIATION[scenario]}.c{cost}.{capital}",
        "arm": arm,
        "window": window,
        "scenario": scenario,
        "cost_multiple": cost,
        "capital_id": capital,
        "kind": kind(arm),
        "reported_only": window == "w0",
    }


def expected_cells() -> list[dict[str, Any]]:
    """The test's own expansion: W1 by arm, scenario, cost and capital, then W0."""
    cells = []
    for arm in ARMS:
        scenarios = SCENARIOS if arm in COMPONENTS else ("native",)
        cells += [cell("w1", arm, s, c, k) for s in scenarios for c in (1, 2) for k in CAPITALS]
    cells += [cell("w0", "combined", s, c, k) for s in SCENARIOS for c in (1, 2) for k in CAPITALS]
    return cells


def prepare_document() -> dict[str, Any]:
    return {
        "schema": "v3.1-prepare-1",
        "windows": [
            {"id": "w1", "start_ms": W1_START, "end_ms": END, "symbols": TEN},
            {"id": "w0", "start_ms": W0_START, "end_ms": END, "symbols": EIGHT},
        ],
        "data_manifests": {
            "config/datasets/v3-20261009/inventory.manifest.json": "a" * 64,
            "config/datasets/full-range-2017-2024.manifest.json": "b" * 64,
        },
        "filter_snapshots": {
            "spot": {"path": "config/datasets/v3-20261009/snapshots/spot.json", "sha256": "c" * 64},
            "futures": {
                "path": "config/datasets/v3-20261009/snapshots/futures.json",
                "sha256": "d" * 64,
            },
        },
    }


def capitals_document() -> list[dict[str, str]]:
    """The owner's three capitals as a registration lists them: USDT, opening at their
    amount."""
    return [
        {"id": c, "currency": "USDT", "amount": AMOUNTS[c], "initial_equity": AMOUNTS[c]}
        for c in CAPITALS
    ]


def registration_document(prepare_sha: str, manifest_sha: str) -> dict[str, Any]:
    return {
        "schema": "v3.1-registration-1",
        "code_pin": CODE_PIN,
        "prepare_sha256": prepare_sha,
        "run_manifest_sha256": manifest_sha,
        "observation_policy": POLICY_ID,
        "scenarios": list(SCENARIOS),
        "v1_variants": list(V1),
        "arms": list(ARMS),
        "adapter_pins": {arm: "5" * 64 for arm in ARMS},
        "cost_profiles": [{"multiple": m, "sha256": COST_PROFILE_PINS[m]} for m in (1, 2)],
        "capitals": capitals_document(),
        "windows": [{"id": "w1", "start_ms": W1_START, "end_ms": END, "skipped_hours": W1_SKIPPED}],
        "reported_windows": [
            {"id": "w0", "start_ms": W0_START, "end_ms": END, "skipped_hours": []}
        ],
        "cells": expected_cells(),
    }


def write_json(path: Path, document: Any) -> str:
    """Write ``document`` pretty-printed (as a person would) and return the file's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(document, indent=2).encode("utf-8") + b"\n"
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


Edit = Callable[[dict[str, Any]], object]


def make_repo(root: Path, edit: Edit | None = None) -> tuple[Path, Path]:
    """A synthetic checkout under ``root``: menu copy, prepare, run-manifest and
    registration; returns the registration and run-manifest paths."""
    config = root / "config"
    config.mkdir(parents=True)
    shutil.copyfile(MENU, config / "v3_1_experiment_menu.json")
    write_json(config / "v3_1_prepare.json", prepare_document())
    prepare = load_prepare_config(config / "v3_1_prepare.json")
    manifest_path = config / "v3_1_run_manifest.json"
    manifest = run_manifest(prepare, window_packs=PACKS, v3_pack=V3_PACK)
    manifest_sha = write_run_manifest(manifest, manifest_path)
    document = registration_document(prepare.sha256, manifest_sha)
    if edit is not None:
        edit(document)
    registration_path = config / "v3_1_registration.json"
    write_json(registration_path, document)
    return registration_path, manifest_path


def load(root: Path, edit: Edit | None = None) -> Any:
    registration_path, manifest_path = make_repo(root, edit)
    return load_registration(registration_path, manifest_path, repo_root=root)


# --- the cell list ---------------------------------------------------------------------


def test_required_cells_count(tmp_path: Path) -> None:
    """The owner's three capitals (2026-10-14): every cell once per capital, 324 in all."""
    reg = load(tmp_path)
    cells = required_cells(reg)
    assert cells == reg.cells
    assert len(cells) == 324 == 3 * 108
    counts = Counter((c.window, c.kind) for c in cells)
    assert counts == {
        ("w1", "v31"): 120,
        ("w0", "v31"): 12,
        ("w1", "v3"): 42,
        ("w1", "hold"): 6,
        ("w1", "minute"): 144,
    }
    # Each capital runs the same 108 cells, split the same way, and no other capital runs.
    assert Counter(c.capital_id for c in cells) == {"research": 108, "medium": 108, "small": 108}
    for capital in CAPITALS:
        mine = Counter((c.window, c.kind) for c in cells if c.capital_id == capital)
        assert mine == {key: count // 3 for key, count in counts.items()}, capital
    by_capital = {
        capital: [c.cell_id.rsplit(".", 1)[0] for c in cells if c.capital_id == capital]
        for capital in CAPITALS
    }
    assert by_capital["research"] == by_capital["medium"] == by_capital["small"]
    assert {c.arm for c in cells if c.window == "w0"} == {"combined"}
    assert all(c.reported_only == (c.window == "w0") for c in cells)
    assert all(c.scenario in SCENARIOS for c in cells if c.kind == "v31")
    assert all(c.scenario == "native" for c in cells if c.kind != "v31")
    # All 32 baselines, V1 in its nine variants and both path modes.
    baselines = {c.arm for c in cells if c.kind != "v31"}
    assert baselines == required_baselines(V1) and len(baselines) == 32


def test_the_capital_constants_are_the_owners_three_usdt_capitals() -> None:
    """One source for the capitals: the report's labels; acceptance and the cell list read
    them, research first, then medium and small."""
    assert CAPITAL_LABELS == {
        "research_10000_usdt": ("research", 10000),
        "medium_1000_usdt": ("medium", 1000),
        "small_100_usdt": ("small", 100),
    }
    assert EXPERIMENT_CAPITALS == (("research", 10000), ("medium", 1000), ("small", 100))
    assert CAPITAL_IDS == CAPITALS == ("research", "medium", "small")


def test_the_menu_states_the_owners_three_usdt_capitals() -> None:
    """The committed menu, which the owner reads and no loader checks for capitals, states
    exactly ``experiment.CAPITALS``: ids, currency, amount, initial equity and order, as a
    registration lists them; and no FX assumption is pending (owner decision, 2026-10-14).
    Its status is authorized for one registered execution: set at the owner's go of
    2026-10-15T00:56Z, with the V3.1 registration's code pin (no code reads it)."""
    menu = json.loads(MENU.read_text(encoding="utf-8"))
    assert menu["capital_scenarios"] == [
        {"id": capital_id, "currency": "USDT", "amount": str(amount), "initial_equity": str(amount)}
        for capital_id, amount in EXPERIMENT_CAPITALS
    ]
    assert menu["capital_scenarios"] == capitals_document()
    assert [scenario["id"] for scenario in menu["capital_scenarios"]] == list(CAPITAL_IDS)
    assert "fx_assumption" not in menu["pending_registration"]
    assert menu["status"] == "AUTHORIZED_FOR_ONE_REGISTERED_EXECUTION"


def test_a_registration_missing_a_cell_is_refused(tmp_path: Path) -> None:
    dropped = "w1.matched_v1_cg_grid_low_first.native.c2.medium"

    def drop(document: dict[str, Any]) -> None:
        document["cells"] = [c for c in document["cells"] if c["cell_id"] != dropped]

    with pytest.raises(ValueError, match=f"cells missing: {re.escape(dropped)}"):
        load(tmp_path / "file", drop)

    reg = load(tmp_path / "valid")
    check_registration(reg)  # the complete registration passes
    with pytest.raises(ValueError, match=re.escape(reg.cells[-1].cell_id)):
        check_registration(replace(reg, cells=reg.cells[:-1]))


def test_cell_ids_are_unique_and_stable(tmp_path: Path) -> None:
    reg = load(tmp_path)
    ids = [c.cell_id for c in required_cells(reg)]
    assert len(set(ids)) == len(ids) == 324
    assert all(CELL_ID.fullmatch(cell_id) for cell_id in ids)
    assert ids == [c["cell_id"] for c in expected_cells()]  # deterministic, in this order
    assert required_cells(reg) == required_cells(reg)
    # Within each cost multiple: research, medium, small.
    assert ids[:6] == [
        "w1.unchanged_v3_selector.native.c1.research",
        "w1.unchanged_v3_selector.native.c1.medium",
        "w1.unchanged_v3_selector.native.c1.small",
        "w1.unchanged_v3_selector.native.c2.research",
        "w1.unchanged_v3_selector.native.c2.medium",
        "w1.unchanged_v3_selector.native.c2.small",
    ]
    for cell_id in (
        "w1.combined.olhc.c1.research",
        "w1.combined_without_recovery.ohlc.c2.small",
        "w1.matched_spot_hold.native.c1.medium",
        "w1.matched_d_trend_high_first.native.c2.research",
        "w0.combined.ohlc.c2.small",
        "w0.combined.olhc.c1.medium",
    ):
        assert cell_id in ids
    assert not [cell_id for cell_id in ids if "owner_small" in cell_id]
    by_id = {c.cell_id: c for c in reg.cells}
    w0 = by_id["w0.combined.olhc.c1.research"]
    assert (w0.arm, w0.window, w0.scenario, w0.cost_multiple, w0.capital_id) == (
        "combined",
        "w0",
        "open_low_high_close",
        1,
        "research",
    )
    assert (w0.kind, w0.reported_only) == ("v31", True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reported_only", False, "cells differing"),
        ("kind", "v3", "cells differing"),
        ("cell_id", "w1.Combined.olhc.c1.research", "cells missing"),
    ],
)
def test_a_cell_with_altered_fields_is_refused(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    def alter(document: dict[str, Any]) -> None:
        target = "w0.combined.olhc.c1.research" if field == "reported_only" else None
        for item in document["cells"]:
            if item["cell_id"] == (target or "w1.combined.olhc.c1.research"):
                item[field] = value

    with pytest.raises(ValueError, match=message):
        load(tmp_path, alter)


def test_a_duplicated_or_reordered_cell_is_refused(tmp_path: Path) -> None:
    reg = load(tmp_path)
    with pytest.raises(ValueError, match="cells duplicated: w1.unchanged_v3_selector"):
        check_registration(replace(reg, cells=(reg.cells[0], *reg.cells)))
    with pytest.raises(ValueError, match="cells out of the required order"):
        check_registration(replace(reg, cells=(reg.cells[1], reg.cells[0], *reg.cells[2:])))


# --- the experiment registration -------------------------------------------------------


def test_registration_matches_experiment_registration_checks(tmp_path: Path) -> None:
    registration_path, manifest_path = make_repo(tmp_path)
    reg = load_registration(registration_path, manifest_path, repo_root=tmp_path)
    assert _registration_errors(reg.registration) == []
    manifest_pin = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    config_pin = hashlib.sha256(registration_path.read_bytes()).hexdigest()
    assert reg.registration.config_pin == config_pin  # computed, never read from the file
    assert reg.run_manifest_pin == manifest_pin
    (w1,) = reg.registration.windows
    (w0,) = reg.reported_windows
    assert (w1.id, w1.start_ms, w1.end_ms, w1.skipped_hours) == (
        "w1",
        W1_START,
        END,
        tuple(W1_SKIPPED),
    )
    assert (w0.id, w0.start_ms, w0.end_ms, w0.skipped_hours) == ("w0", W0_START, END, ())
    assert w1.data_pin == w0.data_pin == manifest_pin
    assert reg.registration.code_pin == CODE_PIN
    assert reg.registration.cost_profiles == ((1, COST_PROFILE_PINS[1]), (2, COST_PROFILE_PINS[2]))
    assert reg.registration.arms == ARMS and len(ARMS) == 42
    assert set(reg.registration.baseline_arms) == required_baselines(V1)
    assert reg.registration.v1_variants == V1
    assert reg.registration.scenarios == SCENARIOS
    assert reg.registration.observation_policy == POLICY_ID
    assert dict(reg.registration.adapter_pins) == {arm: "5" * 64 for arm in ARMS}
    assert reg.prepare_pin == reg.run_manifest.prepare
    assert dict(reg.run_manifest.window_packs) == PACKS
    assert reg.run_manifest.v3_pack == V3_PACK


def test_the_three_usdt_capitals_load_with_their_labels(tmp_path: Path) -> None:
    """The owner's capitals (2026-10-14): each USDT, opening at exactly its amount, with
    no currency conversion, and each labelled with its id and amount."""
    reg = load(tmp_path)
    capitals = reg.registration.capitals
    assert [c.id for c in capitals] == list(CAPITALS)
    assert [(c.currency, c.amount, c.initial_equity) for c in capitals] == [
        ("USDT", D("10000"), D("10000")),
        ("USDT", D("1000"), D("1000")),
        ("USDT", D("100"), D("100")),
    ]
    assert all(isinstance(c.amount, D) and isinstance(c.initial_equity, D) for c in capitals)
    assert [capital_label(c) for c in capitals] == [
        "research_10000_usdt",
        "medium_1000_usdt",
        "small_100_usdt",
    ]
    # No capital carries a conversion: a capital is exactly these four fields.
    assert [field.name for field in fields(capitals[0])] == [
        "id",
        "initial_equity",
        "currency",
        "amount",
    ]


def _capital(index: int, **changes: str) -> Edit:
    return lambda d: d["capitals"][index].update(changes)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (_capital(1, amount="1001", initial_equity="1001"), "medium capital must be 1000 USDT"),
        (_capital(2, initial_equity="103.89"), "small capital must be 100 USDT"),
        (_capital(2, currency="EUR"), "small capital must be 100 USDT"),
        (_capital(0, amount="10001"), "research capital must be 10000 USDT"),
        (lambda d: d["capitals"].pop(), "the research, medium and small USDT capitals required"),
        (
            lambda d: d["capitals"].append(d["capitals"][0]),
            "the research, medium and small USDT capitals required",
        ),
        (
            _capital(1, id="research", amount="10000", initial_equity="10000"),
            "the research, medium and small USDT capitals required",
        ),
        (_capital(2, id="owner_small"), "capital 'owner_small' is not research, medium or small"),
    ],
)
def test_capitals_other_than_the_three_usdt_ones_are_refused(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load(tmp_path, edit)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        # The replaced owner_small capital, EUR 100 at the ECB rate with its FX record.
        (
            lambda d: d["capitals"].__setitem__(
                2,
                {
                    "id": "owner_small",
                    "currency": "EUR",
                    "amount": "100",
                    "initial_equity": "103.89",
                    "fx_rate": "1.0389",
                    "fx_record": {"path": "config/v3_1_fx_record.json", "sha256": "e" * 64},
                },
            ),
            "capital: unexpected fields: fx_rate, fx_record",
        ),
        (_capital(2, fx_rate="1"), "capital: unexpected fields: fx_rate"),
        (_capital(0, fx_pin="e" * 64), "capital: unexpected fields: fx_pin"),
    ],
    ids=["the EUR 100 capital", "an FX rate", "an FX pin"],
)
def test_a_capital_carrying_an_fx_field_is_refused(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    """No capital converts a currency (owner decision, 2026-10-14): an FX rate, record or
    pin is no field of a capital, whatever its value, and the record is never read."""
    with pytest.raises(ValueError, match=message):
        load(tmp_path, edit)


def test_a_registration_file_holding_its_own_config_pin_is_refused(tmp_path: Path) -> None:
    def pin(document: dict[str, Any]) -> None:
        document["config_pin"] = "6" * 64

    with pytest.raises(ValueError, match="config_pin"):
        load(tmp_path, pin)


def test_a_run_manifest_other_than_the_pinned_one_is_refused(tmp_path: Path) -> None:
    registration_path, manifest_path = make_repo(tmp_path)
    prepare = load_prepare_config(tmp_path / "config/v3_1_prepare.json")
    other = run_manifest(prepare, window_packs={**PACKS, "w1": "7" * 64}, v3_pack=V3_PACK)
    manifest_path.unlink()
    write_run_manifest(other, manifest_path)
    with pytest.raises(ValueError, match="run-manifest: .* has SHA-256 .* the registration pins"):
        load_registration(registration_path, manifest_path, repo_root=tmp_path)


def test_a_non_canonical_run_manifest_is_refused(tmp_path: Path) -> None:
    registration_path, manifest_path = make_repo(tmp_path)
    pretty_sha = write_json(manifest_path, json.loads(manifest_path.read_bytes()))
    document = json.loads(registration_path.read_bytes())
    document["run_manifest_sha256"] = pretty_sha
    write_json(registration_path, document)
    with pytest.raises(ValueError, match="canonical"):
        load_registration(registration_path, manifest_path, repo_root=tmp_path)


def test_cost_profiles_other_than_the_pinned_ones_are_refused(tmp_path: Path) -> None:
    def swap(document: dict[str, Any]) -> None:
        document["cost_profiles"][0]["sha256"] = "8" * 64

    with pytest.raises(ValueError, match="cost profiles must be"):
        load(tmp_path, swap)


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["arms"].remove("spot_grid"),
        lambda d: d["arms"].reverse(),
        lambda d: d.update(
            arms=[a for a in d["arms"] if a not in MINUTE] + ["matched_spot_baselines"]
        ),
    ],
    ids=["missing", "reordered", "unexpanded"],
)
def test_arms_other_than_the_expanded_menu_are_refused(tmp_path: Path, edit: Edit) -> None:
    with pytest.raises(ValueError, match="arms must equal the menu"):
        load(tmp_path, edit)


def test_v1_variants_are_pinned(tmp_path: Path) -> None:
    def fewer(document: dict[str, Any]) -> None:
        document["v1_variants"] = ["a", "b", "c"]

    with pytest.raises(ValueError, match="V1 variants must be a, b, c, e, f, g, cg, h, ch"):
        load(tmp_path, fewer)


def test_menu_expansion_matches_the_documented_baselines() -> None:
    assert MENU_ARMS.count("matched_spot_baselines") == 1 and len(MENU_ARMS) == 19
    assert set(MINUTE) | set(V3) | {"matched_spot_hold"} == required_baselines(V1)
    assert set(ARMS) == set(COMPONENTS) | required_baselines(V1)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["windows"][0].update(id="w2"), "acceptance window must be w1"),
        (lambda d: d["reported_windows"][0].update(id="w9"), "reported window must be w0"),
        (lambda d: d["reported_windows"][0].update(end_ms=END + DAY), "w0: invalid window"),
        (lambda d: d["reported_windows"][0].update(skipped_hours=[W0_START]), "w0: skipped"),
        (lambda d: d["windows"][0].update(skipped_hours=[W1_START]), "skipped hours must"),
        (lambda d: d["windows"][0].update(end_ms=END + DAY), "invalid window dates"),
    ],
)
def test_windows_are_w1_for_acceptance_and_w0_reported_only(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load(tmp_path, edit)


def test_check_registration_lists_every_problem(tmp_path: Path) -> None:
    def break_three(document: dict[str, Any]) -> None:
        document["code_pin"] = "abc"
        document["prepare_sha256"] = "9" * 64
        document["cells"].pop()

    with pytest.raises(ValueError) as refused:
        load(tmp_path, break_three)
    text = str(refused.value)
    assert "full code/config pins required" in text
    assert "prepare pin differs from the run-manifest's" in text
    assert "cells missing: w0.combined.ohlc.c2.small" in text


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["capitals"][0].update(amount=10000), "decimal string"),
        (lambda d: d["windows"][0].update(start_ms=float(W1_START)), "JSON float"),
        (lambda d: d.update(extra=1), "unexpected fields: extra"),
        (lambda d: d.pop("arms"), "missing fields: arms"),
        (lambda d: d["cells"][0].update(cost_multiple=True), "an integer"),
    ],
)
def test_malformed_registration_fields_are_refused(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        load(tmp_path, edit)


def test_a_duplicate_json_key_is_refused(tmp_path: Path) -> None:
    registration_path, manifest_path = make_repo(tmp_path)
    text = registration_path.read_text(encoding="utf-8")
    registration_path.write_text(text.replace('"code_pin"', '"code_pin": "x", "code_pin"', 1))
    with pytest.raises(ValueError, match="duplicate JSON key 'code_pin'"):
        load_registration(registration_path, manifest_path, repo_root=tmp_path)


# --- the prepare config and the run-manifest -------------------------------------------


def test_prepare_config_loads_with_its_file_pin(tmp_path: Path) -> None:
    path = tmp_path / "prepare.json"
    sha = write_json(path, prepare_document())
    prepare = load_prepare_config(path)
    assert isinstance(prepare, PrepareConfig)
    assert prepare.sha256 == sha
    assert [(w.id, w.start_ms, w.end_ms, w.symbols) for w in prepare.windows] == [
        ("w1", W1_START, END, tuple(TEN)),
        ("w0", W0_START, END, tuple(EIGHT)),
    ]
    assert [(p.path, p.sha256) for p in prepare.data_manifests] == [
        ("config/datasets/full-range-2017-2024.manifest.json", "b" * 64),
        ("config/datasets/v3-20261009/inventory.manifest.json", "a" * 64),
    ]
    assert prepare.spot_filters.path.endswith("snapshots/spot.json")
    assert prepare.futures_filters.sha256 == "d" * 64


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d["windows"][0].update(end_ms=END + DAY), "whole UTC days before"),
        (lambda d: d["windows"][0].update(start_ms=W1_START + HOUR), "whole UTC days before"),
        (lambda d: d["windows"][1].update(id="w1"), "window ids must be unique"),
        (lambda d: d["windows"][1].update(id="W0"), "window id"),
        (lambda d: d["windows"][0].update(symbols=["BTCUSDT", "BTCUSDT"]), "symbols"),
        (lambda d: d["windows"][0].update(symbols=["btcusdt"]), "symbol"),
        (lambda d: d["data_manifests"].update({"../outside.json": "a" * 64}), "relative"),
        (lambda d: d["data_manifests"].update({"x.json": "A" * 64}), "64 lowercase hex"),
        (lambda d: d["filter_snapshots"].pop("futures"), "missing fields: futures"),
        (lambda d: d["windows"][0].update(start_ms=1.5e12), "JSON float"),
        (lambda d: d.update(schema="v3.1-prepare-0"), "schema"),
    ],
)
def test_prepare_config_refusals(tmp_path: Path, edit: Edit, message: str) -> None:
    document = prepare_document()
    edit(document)
    path = tmp_path / "prepare.json"
    write_json(path, document)
    with pytest.raises(ValueError, match=message):
        load_prepare_config(path)


def test_run_manifest_is_canonical_and_written_once(tmp_path: Path) -> None:
    path = tmp_path / "prepare.json"
    prepare_sha = write_json(path, prepare_document())
    prepare = load_prepare_config(path)
    manifest = run_manifest(prepare, window_packs=PACKS, v3_pack=V3_PACK)
    assert manifest == {
        "schema": "v3.1-run-manifest-1",
        "data_manifests": {
            "config/datasets/full-range-2017-2024.manifest.json": "b" * 64,
            "config/datasets/v3-20261009/inventory.manifest.json": "a" * 64,
        },
        "filter_snapshots": {
            "config/datasets/v3-20261009/snapshots/futures.json": "d" * 64,
            "config/datasets/v3-20261009/snapshots/spot.json": "c" * 64,
        },
        "window_packs": PACKS,
        "v3_pack_sha256": V3_PACK,
        "prepare_sha256": prepare_sha,
    }
    out = tmp_path / "run_manifest.json"
    pin = write_run_manifest(manifest, out)
    data = out.read_bytes()
    assert data == (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert pin == hashlib.sha256(data).hexdigest()
    again = tmp_path / "again.json"
    assert (
        write_run_manifest(run_manifest(prepare, window_packs=PACKS, v3_pack=V3_PACK), again) == pin
    )
    with pytest.raises(FileExistsError):
        write_run_manifest(manifest, out)
    assert out.read_bytes() == data


@pytest.mark.parametrize(
    ("packs", "v3_pack", "message"),
    [
        ({"w1": "1" * 64}, V3_PACK, "window packs must be exactly"),
        ({**PACKS, "w2": "1" * 64}, V3_PACK, "window packs must be exactly"),
        ({**PACKS, "w1": "1" * 63}, V3_PACK, "64 lowercase hex"),
        (PACKS, "Z" * 64, "64 lowercase hex"),
    ],
)
def test_run_manifest_refuses_other_windows_and_malformed_pins(
    tmp_path: Path, packs: dict[str, str], v3_pack: str, message: str
) -> None:
    path = tmp_path / "prepare.json"
    write_json(path, prepare_document())
    with pytest.raises(ValueError, match=message):
        run_manifest(load_prepare_config(path), window_packs=packs, v3_pack=v3_pack)


# --- adapter pins ----------------------------------------------------------------------

PKG = "src/crypto_grid_bot/"
MODULES = {
    PKG + "combined/engine.py": b"ENGINE = 1\n",
    PKG + "combined/driver/registration.py": b"REGISTRATION = 1\n",
    PKG + "combined/baseline_hold.py": b"HOLD = 1\n",
    PKG + "combined/baseline_v3.py": b"V3 = 1\n",
    PKG + "combined/baseline_minute.py": b"MINUTE = 1\n",
    PKG + "combined/baseline_records.py": b"RECORDS = 1\n",
    PKG + "trend/data.py": b"TREND = 1\n",
    PKG + "backtest/replay.py": b"BACKTEST = 1\n",
    PKG + "simulation/runner.py": b"SIMULATION = 1\n",
    PKG + "strategy/grid.py": b"STRATEGY = 1\n",
    PKG + "market_data/parsing.py": b"PARSING = 1\n",
    PKG + "portfolio/other.py": b"OTHER = 1\n",
    "README.md": b"readme\n",
}
MODULE_SETS = {  # each kind's expected modules, without the shared market_data one
    "v31": ("combined/engine.py", "combined/driver/registration.py"),
    "v3": ("combined/baseline_v3.py", "combined/baseline_records.py", "trend/data.py"),
    "hold": ("combined/baseline_hold.py", "combined/baseline_records.py"),
    "minute": (
        "combined/baseline_minute.py",
        "combined/baseline_records.py",
        "backtest/replay.py",
        "simulation/runner.py",
        "strategy/grid.py",
    ),
}


def blob_id(content: bytes) -> str:
    """Git's blob id, computed without git: SHA-1 of the header and the bytes."""
    return hashlib.sha1(b"blob %d\x00" % len(content) + content).hexdigest()


def listing_pin(names: tuple[str, ...]) -> str:
    """The expected pin: canonical JSON of sorted ``[path, blob id]``, market_data included."""
    paths = sorted(PKG + name for name in (*names, "market_data/parsing.py"))
    listing = [[path, blob_id(MODULES[path])] for path in paths]
    return hashlib.sha256(json.dumps(listing, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_adapter_pins_read_blob_ids_at_the_commit(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, check=True, text=True
        )
        return done.stdout.strip()

    def commit(modules: dict[str, bytes], message: str) -> str:
        for name, content in modules.items():
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_bytes(content)
        git("add", "-A")
        git("commit", "-q", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "test@example.invalid")
    first = commit(MODULES, "modules")
    pins = adapter_pins(tmp_path, first)

    assert set(pins) == set(ARMS) and len(pins) == 42
    expected = {label: listing_pin(names) for label, names in MODULE_SETS.items()}
    assert pins == {arm: expected[kind(arm)] for arm in ARMS}
    assert len(set(expected.values())) == 4

    # A working-tree edit is invisible: the pins read the commit's blobs.
    (tmp_path / PKG / "combined/engine.py").write_bytes(b"ENGINE = 2\r\n")
    assert adapter_pins(tmp_path, first) == pins

    # A committed hold change moves the hold pin only; a module outside every set, none.
    # (``commit`` rewrites every module, so the engine edit above is undone.)
    changed = {**MODULES, PKG + "combined/baseline_hold.py": b"HOLD = 2\n"}
    changed[PKG + "portfolio/other.py"] = b"OTHER = 2\n"
    moved = adapter_pins(tmp_path, commit(changed, "hold changes"))
    assert {arm for arm in ARMS if moved[arm] != pins[arm]} == {"matched_spot_hold"}

    # A commit without a named adapter module, an unknown commit and a non-hex id are refused.
    git("rm", "-q", PKG + "combined/baseline_minute.py")
    git("commit", "-q", "-m", "no minute adapter")
    with pytest.raises(ValueError, match="baseline_minute.py"):
        adapter_pins(tmp_path, git("rev-parse", "HEAD"))
    with pytest.raises(ValueError, match="cannot read commit"):
        adapter_pins(tmp_path, "0" * 40)
    with pytest.raises(ValueError, match="40 lowercase hex"):
        adapter_pins(tmp_path, "HEAD")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize(
    "path",
    [
        "config/v3_1_prepare.json",
        "config/v3_1_run_manifest.json",
        "config/v3_1_registration.json",
        "config/v3_1_experiment_menu.json",
        # The V3.1 minute-bar datasets the prepare config pins, by their committed names.
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.toml",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.manifest.json",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.digest.txt",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.toml",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.manifest.json",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.digest.txt",
    ],
)
def test_every_pinned_v31_file_is_lf_in_every_checkout(path: str) -> None:
    """Every pin is the SHA-256 of raw bytes, so .gitattributes keeps each pinned V3.1 file
    LF whatever core.autocrlf says (Ruling F5); a file need not exist to be covered."""
    done = subprocess.run(
        ["git", "-C", str(REPO), "check-attr", "text", "eol", "--", path],
        capture_output=True,
        check=True,
        text=True,
    )
    assert done.stdout.splitlines() == [f"{path}: text: set", f"{path}: eol: lf"]
