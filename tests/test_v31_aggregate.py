"""Aggregation: every cell's artifacts into the acceptance verdict and the owner's summary.

Synthetic only. The matrix is the registration's 216 cells on the run-cell and baseline
tests' synthetic packs. The real cell functions run the 16 ``combined`` cells (W1 and W0),
the 4 hold cells and the 28 V3 cells (from one stand-in walk-forward's picks). Replaying
the 72 other component cells and the 96 minute cells is too slow for a test, so they are
realistic artifacts written with the real encoders: each other component cell is the
combined replay of its scenario, cost and capital under its own identity and attempt, its
bundle rewritten by ``write_bundle``; each minute cell is a hold replay under the minute
arm's adapter pin, written by ``run_baselines``' own cell writer. Nothing touches the
network.
"""

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from decimal import Context, localcontext
from fractions import Fraction
from pathlib import Path

import pytest
from test_v31_registration import (
    FX_PATH,
    MENU,
    fx_document,
    prepare_document,
    registration_document,
    write_json,
)
from test_v31_run_baselines import HOLD_PIN, V3_PIN, stand_in, v3_fields, w1_pack
from test_v31_run_cell import HEAD, SYMBOLS, W0_END, W0_START, window_document, window_pack

from crypto_grid_bot.combined import baseline_v3, dashboard
from crypto_grid_bot.combined.artifacts import (
    VerifiedBundle,
    _canonical,
    read_bundle,
    write_bundle,
)
from crypto_grid_bot.combined.baseline_hold import HoldMarket, replay_hold_baseline
from crypto_grid_bot.combined.baseline_v3 import V3Inputs
from crypto_grid_bot.combined.driver import run_baselines, run_cell
from crypto_grid_bot.combined.driver.aggregate import aggregate
from crypto_grid_bot.combined.driver.packs import WindowPack, read_pack, write_pack
from crypto_grid_bot.combined.driver.registration import (
    V1_VARIANTS,
    Cell,
    DriverRegistration,
    load_prepare_config,
    load_registration,
    minute_arms,
    run_manifest,
    write_run_manifest,
)
from crypto_grid_bot.combined.driver.run_baselines import (
    MINUTE_MANIFEST_PATH,
    compute_v3_picks,
    run_hold_cell,
    run_v3_cell,
)
from crypto_grid_bot.combined.driver.run_cell import run_v31_cell
from crypto_grid_bot.combined.driver.serialize import (
    decode_outcome,
    decode_report,
    encode_outcome,
)
from crypto_grid_bot.combined.driver.v3_pack import read_v3_pack, write_v3_pack
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.evidence import Evidence
from crypto_grid_bot.combined.experiment import (
    AcceptanceResult,
    ReportEvidence,
    RunOutcome,
    capital_label,
    cell_comparison,
    evaluate,
)

MINUTE_PIN = "8" * 64
MINUTE_ARMS = frozenset(minute_arms(V1_VARIANTS))
COMBINED = (  # the 8 full combined W1 cells, in registration order
    "w1.combined.olhc.c1.research",
    "w1.combined.olhc.c1.owner_small",
    "w1.combined.olhc.c2.research",
    "w1.combined.olhc.c2.owner_small",
    "w1.combined.ohlc.c1.research",
    "w1.combined.ohlc.c1.owner_small",
    "w1.combined.ohlc.c2.research",
    "w1.combined.ohlc.c2.owner_small",
)
HOLD_CELL = "w1.matched_spot_hold.native.c1.research"
MISSING = "w1.matched_spot_hold.native.c2.research"
FAILED = "w1.unchanged_v3_r1_long_only.native.c1.research"
KILLED = "w1.spot_grid.olhc.c1.research"
NO_RECEIPT = "w1.combined.ohlc.c2.owner_small"
W0_MISSING = "w0.combined.olhc.c1.research"
W0_CELL = "w0.combined.ohlc.c2.owner_small"
COMPONENT = "w1.spot_trend.ohlc.c2.research"


@dataclass(frozen=True)
class World:
    reg: DriverRegistration
    packs: dict[str, WindowPack]
    v3: V3Inputs


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """Written W1, W0 and V3 packs, and a loaded synthetic registration of all 216 cells
    whose run-manifest pins them, with distinct hold, V3 and minute adapter pins."""
    root = tmp_path_factory.mktemp("repo")
    built = {"w1": w1_pack(), "w0": window_pack("w0", W0_START, W0_END)}
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
    manifest_file = config / "v3_1_run_manifest.json"
    manifest = run_manifest(prepared, window_packs=shas, v3_pack=v3_sha)
    manifest_sha = write_run_manifest(manifest, manifest_file)
    document = registration_document(prepared.sha256, manifest_sha, fx_sha)
    document["windows"] = [window_document(packs["w1"])]
    document["reported_windows"] = [window_document(packs["w0"])]
    for arm in document["adapter_pins"]:
        if arm == "matched_spot_hold":
            document["adapter_pins"][arm] = HOLD_PIN
        elif arm.startswith("unchanged_v3_"):
            document["adapter_pins"][arm] = V3_PIN
        elif arm in MINUTE_ARMS:
            document["adapter_pins"][arm] = MINUTE_PIN
    registration_path = config / "v3_1_registration.json"
    write_json(registration_path, document)
    reg = load_registration(registration_path, manifest_file, repo_root=root)
    return World(reg, packs, read_v3_pack(root / "v3.json.gz", reg.run_manifest.v3_pack))


def attempt_of(cell_id: str) -> str:
    return f"run-1-{cell_id}"


def cell_of(world: World, cell_id: str) -> Cell:
    (cell,) = [c for c in world.reg.cells if c.cell_id == cell_id]
    return cell


def invocation(cell_id: str) -> str:
    return cell_id.replace(".", "-")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Source:
    """A run combined cell's artifacts, read once for every component cell copied from it."""

    outcome: RunOutcome
    report_raw: bytes
    claim: dict
    bundle: VerifiedBundle


def source_of(directory: Path) -> Source:
    return Source(
        decode_outcome((directory / "outcome.json").read_text(encoding="ascii")),
        (directory / "report.json").read_bytes(),
        json.loads((directory / "attempt.json").read_bytes()),
        read_bundle(directory / invocation(directory.name)),
    )


def component_stand_in(cell: Cell, source: Source, out_dir: Path) -> None:
    """A component cell's artifacts from the combined replay of its window, scenario, cost
    and capital, under this cell's identity and attempt: the claim, the bundle (its
    journal, records and report JSON rewritten by ``write_bundle`` with this cell's
    metadata), the report and the outcome, in the run job's order."""
    attempt_id = attempt_of(cell.cell_id)
    assert source.outcome.report_evidence is not None
    identity = replace(source.outcome.identity, arm=cell.arm)
    report = source.outcome.report_evidence.report
    outcome = replace(
        source.outcome,
        identity=identity,
        attempt_id=attempt_id,
        report_evidence=ReportEvidence(identity, attempt_id, report),
    )
    outcome_raw = encode_outcome(outcome).encode("ascii")
    claim = {**source.claim, "cell_id": cell.cell_id, "attempt_id": attempt_id}
    journal = Evidence()
    for event in source.bundle.events:
        journal.record(event)
    metadata = {
        **json.loads(source.bundle.metadata_json),
        **claim,
        "arm": cell.arm,
        "outcome_sha256": hashlib.sha256(outcome_raw).hexdigest(),
        "report_sha256": hashlib.sha256(source.report_raw).hexdigest(),
    }
    directory = out_dir / cell.cell_id
    directory.mkdir()
    (directory / "attempt.json").write_bytes(_canonical(claim))
    write_bundle(
        directory,
        invocation(cell.cell_id),
        journal,
        metadata,
        records=source.bundle.records,
        report_json=source.bundle.report_json,
    )
    (directory / "report.json").write_bytes(source.report_raw)
    (directory / "outcome.json").write_bytes(outcome_raw)


def minute_stand_in(world: World, cell: Cell, out_dir: Path) -> None:
    """A minute cell's artifacts from a hold replay under the minute arm's adapter pin,
    claimed and written by ``run_baselines``' own helpers, as ``run_hold_cell`` does."""
    reg = world.reg
    (window,) = reg.registration.windows
    capital = run_cell._capital(reg, cell.capital_id)
    pin = dict(reg.registration.adapter_pins)[cell.arm]
    legacy = {p.path: p.sha256 for p in reg.run_manifest.data_manifests}[MINUTE_MANIFEST_PATH]
    attempt_id = attempt_of(cell.cell_id)
    claim = run_baselines._cell_attempt(cell, reg, window, attempt_id, HEAD, legacy)
    directory = out_dir / cell.cell_id
    with run_cell._claimed(directory, claim):
        markets = {
            coin.symbol: HoldMarket(coin.spot_hourly, coin.spot_rules, cost_profile(1, "spot"))
            for coin in world.packs["w1"].coins
        }
        evidence = replay_hold_baseline(
            markets,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            initial=capital.initial_equity,
            cost_multiple=cell.cost_multiple,
            source_refs=(f"legacy-manifest:{legacy}", f"v31-run-manifest:{reg.run_manifest_pin}"),
            adapter_pin=pin,
            skipped_hours=window.skipped_hours,
            capital_label=capital_label(capital),
        )
        run_baselines._write_cell(
            directory, claim, cell, reg, window, capital, pin, evidence, attempt_id
        )


@pytest.fixture(scope="module")
def matrix(world: World, tmp_path_factory) -> Path:
    """Every registered cell's artifacts and the V3 picks job, as the run jobs leave them."""
    out = tmp_path_factory.mktemp("matrix")
    reg = world.reg
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(baseline_v3, "run_walk_forward", stand_in([]))
        picks = compute_v3_picks(world.v3, reg, out, attempt_id="run-1-v3_picks", repo_head=HEAD)
    for cell in reg.cells:
        options = {"attempt_id": attempt_of(cell.cell_id), "repo_head": HEAD}
        if cell.arm == "combined":
            run_v31_cell(cell, world.packs[cell.window], reg, out, **options)
        elif cell.kind == "hold":
            run_hold_cell(cell, world.packs["w1"], reg, out, **options)
        elif cell.kind == "v3":
            run_v3_cell(cell, world.v3, picks, reg, out, **options)
    sources = {
        (c.window, c.scenario, c.cost_multiple, c.capital_id): source_of(out / c.cell_id)
        for c in reg.cells
        if c.arm == "combined" and not c.reported_only
    }
    for cell in reg.cells:
        if cell.kind == "v31" and cell.arm != "combined":
            key = (cell.window, cell.scenario, cell.cost_multiple, cell.capital_id)
            component_stand_in(cell, sources[key], out)
        elif cell.kind == "minute":
            minute_stand_in(world, cell, out)
    return out


@pytest.fixture(scope="module")
def outcomes(world: World, matrix: Path) -> dict[str, RunOutcome]:
    """Every W1 outcome of the matrix by cell id, in registration order."""
    return {
        cell.cell_id: decode_outcome(
            (matrix / cell.cell_id / "outcome.json").read_text(encoding="ascii")
        )
        for cell in world.reg.cells
        if not cell.reported_only
    }


@pytest.fixture(scope="module")
def expected(world: World, outcomes: dict[str, RunOutcome]) -> AcceptanceResult:
    """Acceptance of the full matrix's W1 outcomes, judged directly."""
    return evaluate(world.reg.registration, tuple(outcomes.values()))


@pytest.fixture(scope="module")
def expected_defective(world: World, outcomes: dict[str, RunOutcome]) -> AcceptanceResult:
    """Acceptance of the W1 outcomes the defective matrix still holds: the cell without its
    bundle receipt keeps its outcome."""
    kept = (row for cell_id, row in outcomes.items() if cell_id not in (MISSING, FAILED, KILLED))
    return evaluate(world.reg.registration, tuple(kept))


def exact(value: Fraction | None) -> str | None:
    return None if value is None else str(value)


def read_verdict(summary: Path) -> dict:
    return json.loads((summary / "verdict.json").read_bytes())


def mkdir(path: Path) -> Path:
    path.mkdir()
    return path


def files_of(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def summary(world: World, matrix: Path, tmp_path_factory) -> Path:
    """The full matrix aggregated once."""
    return aggregate(world.reg, matrix, tmp_path_factory.mktemp("out"))


@pytest.fixture(scope="module")
def defective(world: World, matrix: Path, tmp_path_factory) -> tuple[Path, Path]:
    """The matrix with one W1 cell missing, one failed, one killed, one V3.1 cell without
    its bundle receipt and one W0 cell missing, aggregated once; (cells, summary)."""
    cells = tmp_path_factory.mktemp("defective") / "cells"
    shutil.copytree(matrix, cells)
    shutil.rmtree(cells / MISSING)
    shutil.rmtree(cells / W0_MISSING)
    for cell_id in (FAILED, KILLED):
        for path in (cells / cell_id).iterdir():
            if path.name != "attempt.json":
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    failure = {"type": "ValueError", "message": "synthetic replay failure"}
    (cells / FAILED / "failure.json").write_bytes(_canonical(failure))
    (cells / NO_RECEIPT / invocation(NO_RECEIPT) / "receipt.json").unlink()
    return cells, aggregate(world.reg, cells, tmp_path_factory.mktemp("out"))


def copy_cells(matrix: Path, target: Path, cell_ids: tuple[str, ...]) -> Path:
    """A cells directory holding only ``cell_ids``' artifacts from the matrix."""
    target.mkdir()
    for cell_id in cell_ids:
        shutil.copytree(matrix / cell_id, target / cell_id)
    return target


def rewrite_outcome(path: Path, **identity_changes: object) -> None:
    """Re-encode the outcome at ``path`` with its identity changed, report evidence too."""
    outcome = decode_outcome(path.read_text(encoding="ascii"))
    identity = replace(outcome.identity, **identity_changes)
    assert outcome.report_evidence is not None
    evidence = replace(outcome.report_evidence, identity=identity)
    changed = replace(outcome, identity=identity, report_evidence=evidence)
    path.write_bytes(encode_outcome(changed).encode("ascii"))


# --- a full matrix ---------------------------------------------------------------------


def test_full_synthetic_matrix_aggregates_to_a_verdict(world, matrix, summary, expected):
    reg = world.reg
    assert expected.status in ("pass", "fail")  # every cell is present: a verdict
    verdict = read_verdict(summary)
    assert summary.name == "summary"
    assert verdict["schema"] == "v3.1-verdict-1"
    assert verdict["status"] == verdict["acceptance_status"] == expected.status
    assert verdict["failures"] == list(expected.failures)
    assert verdict["incomplete_reasons"] == list(expected.incomplete_reasons)
    assert verdict["cell_incomplete_reasons"] == []
    assert verdict["skipped_hours"] == {"w1": list(reg.registration.windows[0].skipped_hours)}
    assert verdict["registration"] == {
        "code_pin": reg.registration.code_pin,
        "config_pin": reg.registration.config_pin,
        "data_pin": reg.run_manifest_pin,
        "prepare_pin": reg.prepare_pin,
        "acceptance_windows": ["w1"],
        "reported_windows": ["w0"],
    }

    # Every baseline against every full combined cell, exactly as acceptance compared them.
    assert len(expected.comparisons) == 8 * len(reg.registration.baseline_arms) == 8 * 32
    assert verdict["comparisons"] == [
        {
            "window": row.window,
            "capital": row.capital,
            "cost_multiple": row.cost_multiple,
            "scenario": row.scenario,
            "baseline": row.baseline,
            "full_return": exact(row.full_return),
            "full_max_drawdown": exact(row.full_max_drawdown),
            "baseline_return": exact(row.baseline_return),
            "baseline_max_drawdown": exact(row.baseline_max_drawdown),
            "beats_return": row.beats_return,
            "beats_return_drawdown": row.beats_return_drawdown,
            "baseline_native_stop": row.baseline_native_stop,
        }
        for row in expected.comparisons
    ]

    # Each cell's state and the SHA-256 of its files; a V3.1 cell's bundle receipt.
    cells = verdict["cells"]
    assert list(cells) == sorted(c.cell_id for c in reg.cells)
    for cell in reg.cells:
        entry, directory = cells[cell.cell_id], matrix / cell.cell_id
        assert entry["state"] == "completed" and entry["reasons"] == []
        assert entry["attempt_id"] == attempt_of(cell.cell_id) and entry["failure"] is None
        assert entry["outcome_sha256"] == sha256(directory / "outcome.json")
        assert entry["report_sha256"] == sha256(directory / "report.json")
        if cell.kind == "v31":
            receipt = read_bundle(directory / invocation(cell.cell_id)).receipt
            assert entry["bundle_receipt_sha256"] == receipt.receipt_sha256
            folder = "w0" if cell.reported_only else "pages"
            page = summary / folder / f"{cell.cell_id}.html"
            assert entry["page"] == {
                "path": f"{folder}/{cell.cell_id}.html",
                "sha256": sha256(page),
                "report_json": None,
            }
        else:
            assert entry["bundle_receipt_sha256"] is None and entry["page"] is None
    assert verdict["v3_picks"] == {
        "state": "completed",
        "receipt_sha256": sha256(matrix / "v3_picks" / "outcome.json"),
        "reasons": [],
    }

    # The pages: the full combined cells carry acceptance's judgment of their cell, the
    # other W1 components none; baselines get no page.
    pages = sorted(path.name for path in (summary / "pages").iterdir())
    assert pages == sorted(
        f"{c.cell_id}.html" for c in reg.cells if c.kind == "v31" and not c.reported_only
    )
    for cell_id in COMBINED:
        cell = cell_of(world, cell_id)
        comparison = cell_comparison(
            reg.registration,
            expected,
            window="w1",
            capital=cell.capital_id,
            cost_multiple=cell.cost_multiple,
            scenario=cell.scenario,
        )
        html = (summary / "pages" / f"{cell_id}.html").read_text(encoding="utf-8")
        assert f"Acceptance: {comparison.status}" in html
        assert f"This cell: {comparison.cell_status}" in html
        assert "Synthetic demonstration" not in html  # rendered as evidence, not a demo
    other = (summary / "pages" / f"{COMPONENT}.html").read_text(encoding="utf-8")
    assert "Acceptance:" not in other and '<p class="empty">Not supplied</p>' in other

    # The owner's table: one row per full combined cell, the verdict and the W0 section.
    text = (summary / "summary.md").read_text(encoding="utf-8")
    assert f"**{expected.status.upper()}**" in text
    for cell_id in COMBINED:
        assert sum(line.startswith(f"| `{cell_id}` |") for line in text.splitlines()) == 1
    assert "## W0 (reported only, no acceptance)" in text
    assert sorted(path.name for path in summary.iterdir()) == [
        "pages",
        "summary.md",
        "verdict.json",
        "w0",
    ]


def test_w0_reports_carry_no_verdict(world, summary, defective, expected_defective):
    w0_cells = [c for c in world.reg.cells if c.reported_only]
    assert len(w0_cells) == 8 and {c.window for c in w0_cells} == {"w0"}
    assert sorted(path.name for path in (summary / "w0").iterdir()) == sorted(
        f"{c.cell_id}.html" for c in w0_cells
    )
    html = (summary / "w0" / f"{W0_CELL}.html").read_text(encoding="utf-8")
    assert "Reported only (W0): no acceptance" in html
    assert "Acceptance:" not in html and '<p class="empty">Not supplied</p>' in html
    verdict = read_verdict(summary)
    # W0 is never given to acceptance (it would be an unregistered outcome) nor compared.
    reasons = (*verdict["failures"], *verdict["incomplete_reasons"])
    assert not any("'w0'" in reason or "w0." in reason for reason in reasons)
    assert {row["window"] for row in verdict["comparisons"]} == {"w1"}

    # A missing W0 cell leaves the W1 verdict as acceptance gave it, and shows in W0 alone.
    _, defective_summary = defective
    broken = read_verdict(defective_summary)
    assert broken["acceptance_status"] == expected_defective.status
    assert broken["failures"] == list(expected_defective.failures)
    assert broken["incomplete_reasons"] == list(expected_defective.incomplete_reasons)
    assert broken["cells"][W0_MISSING]["state"] == "missing"
    assert not any(W0_MISSING in reason for reason in broken["cell_incomplete_reasons"])
    text = (defective_summary / "summary.md").read_text(encoding="utf-8")
    w0_section = text.split("## W0 (reported only, no acceptance)")[1]
    assert f"`{W0_MISSING}` | missing" in w0_section


def test_v3_picks_directory_is_exempt_and_its_receipt_recorded(world, matrix, summary):
    verdict = read_verdict(summary)
    assert "v3_picks" not in verdict["cells"]
    assert verdict["v3_picks"]["receipt_sha256"] == sha256(matrix / "v3_picks" / "outcome.json")


def test_the_same_cells_give_byte_identical_summaries(world, defective, tmp_path):
    # Cells in every state: completed, missing, failed, killed and invalid, W1 and W0.
    # (The full matrix is aggregated twice above; a second full run would add no path.)
    cells, _ = defective
    chosen = (*COMBINED, FAILED, KILLED, HOLD_CELL, W0_CELL, "v3_picks")
    subset = copy_cells(cells, tmp_path / "cells", chosen)
    first = aggregate(world.reg, subset, mkdir(tmp_path / "first"))
    # Another decimal context in the caller changes nothing.
    with localcontext(Context(prec=5, capitals=0)):
        again = aggregate(world.reg, subset, mkdir(tmp_path / "again"))
    assert files_of(again) == files_of(first)
    verdict = read_verdict(first)
    states = {verdict["cells"][cell_id]["state"] for cell_id in (*chosen[:-1], MISSING)}
    assert states == {"completed", "failed", "killed", "invalid", "missing"}


# --- incomplete cells ------------------------------------------------------------------


def test_a_missing_cell_is_incomplete_not_a_crash(world, defective, expected_defective):
    _, summary = defective
    verdict = read_verdict(summary)
    assert expected_defective.status != "pass"
    assert verdict["status"] == ("fail" if expected_defective.failures else "incomplete")
    assert verdict["incomplete_reasons"] == list(expected_defective.incomplete_reasons)
    missing = cell_of(world, MISSING)
    key = (missing.arm, "w1", missing.capital_id, missing.cost_multiple, "native")
    assert f"{key}: missing or repeated cell (0 outcomes)" in verdict["incomplete_reasons"]
    assert verdict["cells"][MISSING] == {
        "state": "missing",
        "attempt_id": None,
        "failure": None,
        "reasons": [],
        "outcome_sha256": None,
        "report_sha256": None,
        "bundle_receipt_sha256": None,
        "page": None,
    }
    assert f"{MISSING}: missing, never run" in verdict["cell_incomplete_reasons"]


def test_a_w1_cell_with_only_failure_json_is_incomplete_and_records_the_failure(world, defective):
    _, summary = defective
    verdict = read_verdict(summary)
    assert verdict["status"] != "pass"
    entry = verdict["cells"][FAILED]
    assert entry["state"] == "failed" and entry["attempt_id"] == attempt_of(FAILED)
    assert entry["failure"] == {"type": "ValueError", "message": "synthetic replay failure"}
    assert entry["outcome_sha256"] is None
    reason = f"{FAILED}: failed attempt (ValueError: synthetic replay failure)"
    assert reason in verdict["cell_incomplete_reasons"]
    text = (summary / "summary.md").read_text(encoding="utf-8")
    assert f"`{FAILED}` | failed | ValueError: synthetic replay failure" in text


def test_a_killed_cell_and_a_bundle_without_its_receipt_are_incomplete(world, defective):
    _, summary = defective
    verdict = read_verdict(summary)
    killed = verdict["cells"][KILLED]
    assert killed["state"] == "killed" and killed["page"] is None
    assert f"{KILLED}: killed, claimed without an outcome" in verdict["cell_incomplete_reasons"]
    assert not (summary / "pages" / f"{KILLED}.html").exists()

    unreceipted = verdict["cells"][NO_RECEIPT]
    assert unreceipted["state"] == "invalid" and unreceipted["bundle_receipt_sha256"] is None
    assert any("bundle" in reason for reason in unreceipted["reasons"])
    assert any(
        reason.startswith(f"{NO_RECEIPT}: ") and "bundle" in reason
        for reason in verdict["cell_incomplete_reasons"]
    )
    assert verdict["status"] != "pass"


def test_a_large_report_json_is_written_beside_its_page(world, matrix, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "_INLINE_JSON_LIMIT", 0)
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[0], W0_CELL))
    summary = aggregate(world.reg, cells, tmp_path)
    verdict = read_verdict(summary)
    for cell_id, folder in ((COMBINED[0], "pages"), (W0_CELL, "w0")):
        page = summary / folder / f"{cell_id}.html"
        report_json = summary / folder / f"{cell_id}.report.json"
        assert verdict["cells"][cell_id]["page"] == {
            "path": f"{folder}/{cell_id}.html",
            "sha256": sha256(page),
            "report_json": {
                "path": f"{folder}/{cell_id}.report.json",
                "sha256": sha256(report_json),
            },
        }
        assert sha256(report_json) in page.read_text(encoding="utf-8")
    report = decode_report((cells / W0_CELL / "report.json").read_text(encoding="ascii"))
    exact = json.loads((summary / "w0" / f"{W0_CELL}.report.json").read_bytes())
    assert exact["cross_version_comparison"] is None and exact["synthetic"] is False
    assert exact["report"]["final_equity"] == str(report.final_equity)


# --- refusals --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin", ["code_pin", "config_pin", "data_pin"], ids=["code", "config", "data"]
)
def test_a_cell_from_another_commit_is_refused(world, matrix, tmp_path, pin):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL, COMBINED[0]))
    other = "8" * (40 if pin == "code_pin" else 64)
    rewrite_outcome(cells / HOLD_CELL / "outcome.json", **{pin: other})
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=HOLD_CELL) as refused:
        aggregate(world.reg, cells, out)
    assert pin in str(refused.value) and COMBINED[0] not in str(refused.value)
    assert list(out.iterdir()) == []  # refused before anything is written


@pytest.mark.parametrize("pin", ["code_pin", "config_pin", "data_pin", "pack_sha256"])
def test_a_claim_under_other_pins_is_refused(world, matrix, tmp_path, pin):
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[1],))
    path = cells / COMBINED[1] / "attempt.json"
    claim = json.loads(path.read_bytes())
    claim[pin] = "8" * len(claim[pin])
    path.write_bytes(_canonical(claim))
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=COMBINED[1]):
        aggregate(world.reg, cells, out)
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        {"arm": "spot_trend"},
        {"window": "w0"},
        {"capital": "owner_small"},
        {"cost_multiple": 2},
        {"scenario": "open_high_low_close"},
    ],
    ids=["arm", "window", "capital", "cost", "scenario"],
)
def test_an_outcome_of_another_cell_is_refused(world, matrix, tmp_path, change):
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[0],))
    rewrite_outcome(cells / COMBINED[0] / "outcome.json", **change)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=COMBINED[0]):
        aggregate(world.reg, cells, out)
    assert list(out.iterdir()) == []


def test_duplicate_cell_is_refused(world, matrix, tmp_path):
    cells = tmp_path / "cells"
    for attempt in (1, 2):
        shutil.copytree(
            matrix / HOLD_CELL, cells / f"cell-{HOLD_CELL}-attempt-{attempt}" / HOLD_CELL
        )
    shutil.copytree(matrix / COMBINED[0], cells / COMBINED[0])
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="duplicate") as refused:
        aggregate(world.reg, cells, out)
    assert HOLD_CELL in str(refused.value) and COMBINED[0] not in str(refused.value)
    assert list(out.iterdir()) == []

    # A cell both downloaded under its artifact name and loose is a duplicate too.
    shutil.rmtree(cells / f"cell-{HOLD_CELL}-attempt-2")
    shutil.copytree(matrix / HOLD_CELL, cells / HOLD_CELL)
    with pytest.raises(ValueError, match=HOLD_CELL):
        aggregate(world.reg, cells, out)
    assert list(out.iterdir()) == []


def test_artifact_directories_are_accepted_and_other_nesting_refused(world, matrix, tmp_path):
    cells = tmp_path / "cells"
    shutil.copytree(matrix / HOLD_CELL, cells / f"cell-{HOLD_CELL}-attempt-3" / HOLD_CELL)
    shutil.copytree(matrix / "v3_picks", cells / "v3-picks-attempt-1" / "v3_picks")
    shutil.copytree(matrix / COMBINED[0], cells / COMBINED[0])
    summary = aggregate(world.reg, cells, tmp_path)
    verdict = read_verdict(summary)
    assert verdict["cells"][HOLD_CELL]["state"] == "completed"
    assert verdict["cells"][COMBINED[0]]["state"] == "completed"
    assert verdict["v3_picks"]["state"] == "completed"

    bad = {
        "an unregistered cell": lambda root: (root / "w1.no_such_arm.native.c1.research").mkdir(),
        "a stray file": lambda root: (root / "notes.txt").write_text("x"),
        "an artifact of another cell": lambda root: shutil.copytree(
            matrix / HOLD_CELL, root / f"cell-{COMBINED[1]}-attempt-1" / HOLD_CELL
        ),
        "an artifact holding two entries": lambda root: (
            shutil.copytree(matrix / MISSING, root / f"cell-{MISSING}-attempt-1" / MISSING),
            (root / f"cell-{MISSING}-attempt-1" / "extra").mkdir(),
        ),
        "a deeper nesting": lambda root: shutil.copytree(
            matrix / MISSING, root / "downloads" / f"cell-{MISSING}-attempt-1" / MISSING
        ),
    }
    for index, (what, make) in enumerate(bad.items()):
        root = tmp_path / f"bad-{index}"
        shutil.copytree(matrix / COMBINED[0], root / COMBINED[0])
        make(root)
        out = tmp_path / f"out-{index}"
        out.mkdir()
        with pytest.raises(ValueError):
            aggregate(world.reg, root, out)
        assert list(out.iterdir()) == [], what


def test_an_existing_summary_is_never_replaced(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    out = tmp_path / "out"
    (out / "summary").mkdir(parents=True)
    (out / "summary" / "verdict.json").write_text("earlier")
    with pytest.raises(FileExistsError):
        aggregate(world.reg, cells, out)
    assert (out / "summary" / "verdict.json").read_text() == "earlier"
