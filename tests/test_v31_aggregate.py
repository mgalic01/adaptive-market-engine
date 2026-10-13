"""Aggregation: every cell's artifacts into the acceptance verdict and the owner's summary.

Synthetic only. The matrix is the registration's 216 cells on the run-cell and baseline
tests' synthetic packs. The real cell functions run the 16 ``combined`` cells (W1 and W0),
the 4 hold cells and the 28 V3 cells (from one stand-in walk-forward's picks). Replaying
the 72 other component cells and the 96 minute cells is too slow for a test, so they are
realistic artifacts written with the real encoders: each other component cell is the
combined replay of its scenario, cost and capital under its own identity and attempt, its
bundle rewritten by ``write_bundle``; each minute cell is a hold replay under the minute
arm's adapter pin, written by ``run_baselines``' own cell writer. Each cell, and the
picks job, sits in its artifact folder (``cell-<cell_id>-attempt-1/`` and
``v3-picks-attempt-1/``), the only layout aggregation accepts. Nothing touches the network.
"""

import hashlib
import json
import os
import re
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
from crypto_grid_bot.combined.driver import aggregate as aggregation
from crypto_grid_bot.combined.driver import run_baselines, run_cell
from crypto_grid_bot.combined.driver.aggregate import aggregate as aggregate_cells
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
PICKS = "v3_picks"
RUN = "run-1-attempt-1"  # aggregation's own attempt id: the run of every attempt_of()


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


def aggregate(
    reg: DriverRegistration,
    cells: Path,
    out: Path,
    *,
    attempt_id: str = RUN,
    mode: str = "registered",
    other_dispatches: tuple[str, ...] = (),
) -> Path:
    """``aggregate`` as the workflow calls it, by default a registered run's attempt 1 of
    run ``run-1``, the run every cell of the matrix claims, whose dispatch check found no
    other dispatch of the registration."""
    return aggregate_cells(
        reg, cells, out, attempt_id=attempt_id, mode=mode, other_dispatches=other_dispatches
    )


def attempt_of(cell_id: str) -> str:
    """A unique attempt id per cell (acceptance requires it), ending in its attempt."""
    return f"run-1-{cell_id}-attempt-1"


def folder_of(cell_id: str, attempt: int = 1) -> str:
    """The artifact folder a cell, or the picks job, is downloaded into."""
    if cell_id == PICKS:
        return f"v3-picks-attempt-{attempt}"
    return f"cell-{cell_id}-attempt-{attempt}"


def cell_dir(cells: Path, cell_id: str, attempt: int = 1) -> Path:
    return cells / folder_of(cell_id, attempt) / cell_id


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
        picks = compute_v3_picks(world.v3, reg, out, attempt_id=attempt_of(PICKS), repo_head=HEAD)
    for cell in reg.cells:
        options = {"attempt_id": attempt_of(cell.cell_id), "repo_head": HEAD}
        if cell.arm == "combined":
            run_v31_cell(cell, world.packs[cell.window], reg, out, **options)
        elif cell.kind == "hold":
            run_hold_cell(cell, world.packs["w1"], reg, out, **options)
        elif cell.kind == "v3":
            given = picks if cell.arm == "unchanged_v3_selector" else None  # as run-cell
            run_v3_cell(cell, world.v3, given, reg, out, **options)
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
    for entry in sorted(out.iterdir()):  # each into its artifact folder, as downloaded
        (out / folder_of(entry.name)).mkdir()
        entry.rename(cell_dir(out, entry.name))
    return long_paths(out)


def long_paths(path: Path) -> Path:
    """``path`` as aggregation addresses a cells directory: on Windows its extended-length
    form, as the longest arms' nested bundle files pass the 260-character limit."""
    return aggregation._extended(path)


def outcome_text(cells: Path, cell_id: str) -> str:
    return (cell_dir(cells, cell_id) / "outcome.json").read_text(encoding="ascii")


@pytest.fixture(scope="module")
def decoded(world: World, matrix: Path) -> dict[str, RunOutcome]:
    """Every outcome of the matrix, decoded once, by its text."""
    texts = [outcome_text(matrix, cell.cell_id) for cell in world.reg.cells]
    return {text: decode_outcome(text) for text in texts}


@pytest.fixture(scope="module")
def outcomes(world: World, matrix: Path, decoded: dict[str, RunOutcome]) -> dict[str, RunOutcome]:
    """Every W1 outcome of the matrix by cell id, in registration order."""
    return {
        cell.cell_id: decoded[outcome_text(matrix, cell.cell_id)]
        for cell in world.reg.cells
        if not cell.reported_only
    }


@pytest.fixture(scope="module")
def expected(world: World, outcomes: dict[str, RunOutcome]) -> AcceptanceResult:
    """Acceptance of the full matrix's W1 outcomes, judged directly."""
    return evaluate(world.reg.registration, tuple(outcomes.values()))


@pytest.fixture(scope="module")
def expected_defective(world: World, outcomes: dict[str, RunOutcome]) -> AcceptanceResult:
    """Acceptance of the W1 outcomes of the defective matrix's completed cells: the cell
    without its bundle receipt is invalid, so its outcome is withheld as missing."""
    unfinished = (MISSING, FAILED, KILLED, NO_RECEIPT)
    kept = (row for cell_id, row in outcomes.items() if cell_id not in unfinished)
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
    cells = long_paths(tmp_path_factory.mktemp("defective")) / "cells"
    shutil.copytree(matrix, cells)
    break_cells(cells, (MISSING, W0_MISSING, FAILED, KILLED, NO_RECEIPT))
    return cells, aggregate(world.reg, cells, tmp_path_factory.mktemp("out"))


def break_cells(cells: Path, cell_ids: tuple[str, ...]) -> None:
    """Each named cell (or the picks job) left as a defect: MISSING and W0_MISSING never
    run, FAILED with its claim and failure.json alone, KILLED and the picks job with their
    claim alone, NO_RECEIPT's bundle without its receipt. Files are only removed or added,
    never rewritten, so a hard-linked copy of the matrix stays intact."""
    for cell_id in cell_ids:
        directory = cell_dir(cells, cell_id)
        if cell_id in (MISSING, W0_MISSING):
            shutil.rmtree(cells / folder_of(cell_id))
        elif cell_id in (FAILED, KILLED, PICKS):
            for path in directory.iterdir():
                if path.name != "attempt.json":
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            if cell_id == FAILED:
                failure = {"type": "ValueError", "message": "synthetic replay failure"}
                (directory / "failure.json").write_bytes(_canonical(failure))
        else:
            assert cell_id == NO_RECEIPT
            (directory / invocation(NO_RECEIPT) / "receipt.json").unlink()


def copy_cells(matrix: Path, target: Path, cell_ids: tuple[str, ...]) -> Path:
    """A cells directory holding only ``cell_ids``' artifact folders from the matrix."""
    target = long_paths(target)
    target.mkdir()
    for cell_id in cell_ids:
        shutil.copytree(matrix / folder_of(cell_id), target / folder_of(cell_id))
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
    assert verdict["mode"] == "registered"
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
        entry, directory = cells[cell.cell_id], cell_dir(matrix, cell.cell_id)
        assert entry["state"] == "completed" and entry["reasons"] == []
        assert entry["attempt_id"] == attempt_of(cell.cell_id) and entry["failure"] is None
        assert (entry["artifact_attempt"], entry["run_id"]) == (1, "run-1")
        assert entry["outcome_sha256"] == sha256(directory / "outcome.json")
        assert entry["report_sha256"] == sha256(directory / "report.json")
        if cell.kind == "v31":
            receipt = read_bundle(directory / invocation(cell.cell_id)).receipt
            assert entry["bundle_receipt_sha256"] == receipt.receipt_sha256
            folder = "w0" if cell.reported_only else "pages"
            page = summary / folder / cell.cell_id / "report.html"
            assert sorted(os.listdir(page.parent)) == ["report.html"]  # no large report
            assert entry["page"] == {
                "path": f"{folder}/{cell.cell_id}/report.html",
                "sha256": sha256(page),
                "report_json": None,
            }
        else:
            assert entry["bundle_receipt_sha256"] is None and entry["page"] is None
    assert verdict["v3_picks"] == {
        "state": "completed",
        "artifact_attempt": 1,
        "run_id": "run-1",
        "receipt_sha256": sha256(cell_dir(matrix, PICKS) / "outcome.json"),
        "reasons": [],
    }
    # Aggregation's own run, and no re-run: every folder is attempt 1 of run-1.
    assert verdict["run"] == {
        "attempt_id": RUN,
        "run_id": "run-1",
        "aggregate_attempt": 1,
        "rerun_detected": False,
        "reruns": [],
        "reported_only_reruns": [],
        "other_dispatches": [],
    }

    # The pages: the full combined cells carry acceptance's judgment of their cell, the
    # other W1 components none; baselines get no page.
    pages = sorted(path.name for path in (summary / "pages").iterdir())
    assert pages == sorted(c.cell_id for c in reg.cells if c.kind == "v31" and not c.reported_only)
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
        html = (summary / "pages" / cell_id / "report.html").read_text(encoding="utf-8")
        assert f"Acceptance: {comparison.status}" in html
        assert f"This cell: {comparison.cell_status}" in html
        assert "Synthetic demonstration" not in html  # rendered as evidence, not a demo
    other = (summary / "pages" / COMPONENT / "report.html").read_text(encoding="utf-8")
    assert "Acceptance:" not in other and '<p class="empty">Not supplied</p>' in other

    # The owner's table: one row per full combined cell, the verdict and the W0 section.
    text = (summary / "summary.md").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# V3.1 run summary: registered run"
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
        c.cell_id for c in w0_cells
    )
    html = (summary / "w0" / W0_CELL / "report.html").read_text(encoding="utf-8")
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
    receipt = sha256(cell_dir(matrix, PICKS) / "outcome.json")
    assert verdict["v3_picks"]["receipt_sha256"] == receipt


def test_the_same_cells_give_byte_identical_summaries(world, defective, tmp_path):
    # Cells in every state: completed, missing, failed, killed and invalid, W1 and W0.
    # (The full matrix is aggregated twice above; a second full run would add no path.)
    cells, _ = defective
    chosen = (*COMBINED, FAILED, KILLED, HOLD_CELL, W0_CELL, PICKS)
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
        "artifact_attempt": None,
        "run_id": None,
        "attempt_id": None,
        "failure": None,
        "reasons": [],
        "outcome_sha256": None,
        "report_sha256": None,
        "bundle_receipt_sha256": None,
        "page": None,
    }
    reason = f"{MISSING}: no artifact: not run, or failed before its claim"
    assert reason in verdict["cell_incomplete_reasons"]


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
    assert not (summary / "pages" / KILLED).exists()

    unreceipted = verdict["cells"][NO_RECEIPT]
    assert unreceipted["state"] == "invalid" and unreceipted["bundle_receipt_sha256"] is None
    assert any("bundle" in reason for reason in unreceipted["reasons"])
    assert any(
        reason.startswith(f"{NO_RECEIPT}: ") and "bundle" in reason
        for reason in verdict["cell_incomplete_reasons"]
    )
    # Its outcome is withheld from acceptance, which finds the cell missing itself.
    cell = cell_of(world, NO_RECEIPT)
    key = ("combined", "w1", cell.capital_id, cell.cost_multiple, cell.scenario)
    assert f"{key}: missing or repeated cell (0 outcomes)" in verdict["incomplete_reasons"]
    assert verdict["status"] != "pass"
    html = (summary / "pages" / NO_RECEIPT / "report.html").read_text(encoding="utf-8")
    title = re.search("<title>([^<]*)</title>", html)
    assert title is not None and "INVALID cell artifacts, not judged" in title[1]


def test_a_large_report_json_is_written_beside_its_page(world, matrix, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "_INLINE_JSON_LIMIT", 0)
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[0], W0_CELL))
    summary = aggregate(world.reg, cells, tmp_path)
    verdict = read_verdict(summary)
    for cell_id, folder in ((COMBINED[0], "pages"), (W0_CELL, "w0")):
        directory = summary / folder / cell_id
        page = directory / "report.html"
        # The page's own link resolves beside it, to the file whose SHA-256 it states.
        links = re.findall(
            r'href="([^"]+)" data-report-json-sha256="([0-9a-f]{64})"',
            page.read_text(encoding="utf-8"),
        )
        assert len(links) == 1
        ((href, stated),) = links
        target = directory / href
        assert href == "report.json" and target.is_file() and sha256(target) == stated
        assert sorted(os.listdir(directory)) == ["report.html", "report.json"]
        assert verdict["cells"][cell_id]["page"] == {
            "path": f"{folder}/{cell_id}/report.html",
            "sha256": sha256(page),
            "report_json": {"path": f"{folder}/{cell_id}/report.json", "sha256": stated},
        }
    w0_report = cell_dir(cells, W0_CELL) / "report.json"
    report = decode_report(w0_report.read_text(encoding="ascii"))
    exact = json.loads((summary / "w0" / W0_CELL / "report.json").read_bytes())
    assert exact["cross_version_comparison"] is None and exact["synthetic"] is False
    assert exact["report"]["final_equity"] == str(report.final_equity)


# --- refusals --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin", ["code_pin", "config_pin", "data_pin"], ids=["code", "config", "data"]
)
def test_a_cell_from_another_commit_is_refused(world, matrix, tmp_path, pin):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL, COMBINED[0]))
    other = "8" * (40 if pin == "code_pin" else 64)
    rewrite_outcome(cell_dir(cells, HOLD_CELL) / "outcome.json", **{pin: other})
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=HOLD_CELL) as refused:
        aggregate(world.reg, cells, out)
    assert pin in str(refused.value) and COMBINED[0] not in str(refused.value)
    assert list(out.iterdir()) == []  # refused before anything is written


@pytest.mark.parametrize("pin", ["code_pin", "config_pin", "data_pin", "pack_sha256"])
def test_a_claim_under_other_pins_is_refused(world, matrix, tmp_path, pin):
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[1],))
    path = cell_dir(cells, COMBINED[1]) / "attempt.json"
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
    rewrite_outcome(cell_dir(cells, COMBINED[0]) / "outcome.json", **change)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=COMBINED[0]):
        aggregate(world.reg, cells, out)
    assert list(out.iterdir()) == []


def test_duplicate_cell_is_refused(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[0],))
    for attempt in (1, 2):
        shutil.copytree(cell_dir(matrix, HOLD_CELL), cell_dir(cells, HOLD_CELL, attempt))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError, match="duplicate") as refused:
        aggregate(world.reg, cells, out)
    assert HOLD_CELL in str(refused.value) and COMBINED[0] not in str(refused.value)
    assert list(out.iterdir()) == []

    # Two picks folders are duplicates too.
    shutil.rmtree(cells / folder_of(HOLD_CELL, 2))
    for attempt in (1, 2):
        shutil.copytree(cell_dir(matrix, PICKS), cell_dir(cells, PICKS, attempt))
    with pytest.raises(ValueError, match="v3_picks: duplicate artifact sets"):
        aggregate(world.reg, cells, out)
    assert list(out.iterdir()) == []


def test_artifact_folders_are_accepted_and_anything_else_refused(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL, PICKS, COMBINED[0]))
    verdict = read_verdict(aggregate(world.reg, cells, tmp_path))
    assert verdict["cells"][HOLD_CELL]["state"] == "completed"
    assert verdict["cells"][COMBINED[0]]["state"] == "completed"
    assert verdict["v3_picks"]["state"] == "completed"

    unregistered = "w1.no_such_arm.native.c1.research"
    bad = {  # what: (the entry the refusal names, how to make it)
        "a loose cell": (MISSING, lambda root: copy(MISSING, root / MISSING)),
        "a loose picks job": (PICKS, lambda root: copy(PICKS, root / PICKS)),
        "an unregistered cell's folder": (
            folder_of(unregistered),
            lambda root: (root / folder_of(unregistered) / unregistered).mkdir(parents=True),
        ),
        "a stray file": ("notes.txt", lambda root: (root / "notes.txt").write_text("x")),
        "a folder holding another cell": (
            folder_of(COMBINED[1]),
            lambda root: copy(HOLD_CELL, root / folder_of(COMBINED[1]) / HOLD_CELL),
        ),
        "a folder holding two entries": (
            folder_of(MISSING),
            lambda root: (
                copy(MISSING, cell_dir(root, MISSING)),
                (root / folder_of(MISSING) / "extra").mkdir(),
            ),
        ),
        "a deeper nesting": (
            "downloads",
            lambda root: copy(MISSING, root / "downloads" / folder_of(MISSING) / MISSING),
        ),
        "a leading zero": (
            f"cell-{MISSING}-attempt-01",
            lambda root: copy(MISSING, root / f"cell-{MISSING}-attempt-01" / MISSING),
        ),
        "attempt zero": (
            f"cell-{MISSING}-attempt-0",
            lambda root: copy(MISSING, root / f"cell-{MISSING}-attempt-0" / MISSING),
        ),
    }

    def copy(cell_id: str, target: Path) -> None:
        shutil.copytree(cell_dir(matrix, cell_id), target)

    for index, (what, (named, make)) in enumerate(bad.items()):
        root = copy_cells(matrix, tmp_path / f"bad-{index}", (COMBINED[0],))
        make(root)
        out = mkdir(tmp_path / f"out-{index}")
        with pytest.raises(ValueError) as refused:
            aggregate(world.reg, root, out)
        assert f"- {named}: " in str(refused.value), what
        assert COMBINED[0] not in str(refused.value), what
        assert list(out.iterdir()) == [], what


def test_a_claim_of_another_attempt_than_its_folder_is_refused(world, matrix, tmp_path):
    for owner in (HOLD_CELL, PICKS):
        cells = long_paths(tmp_path / f"cells-{owner}")
        shutil.copytree(cell_dir(matrix, owner), cell_dir(cells, owner, 2))
        out = mkdir(tmp_path / f"out-{owner}")
        with pytest.raises(ValueError, match=re.escape(owner)) as refused:
            aggregate(world.reg, cells, out)
        assert "names attempt 1, but its artifact folder is attempt 2" in str(refused.value)
        assert list(out.iterdir()) == []

    # An attempt id that ends in no attempt number binds no folder: accepted.
    cells = long_paths(tmp_path / "unnumbered")
    directory = cell_dir(cells, HOLD_CELL, 2)
    shutil.copytree(cell_dir(matrix, HOLD_CELL), directory)
    claim = json.loads((directory / "attempt.json").read_bytes())
    (directory / "attempt.json").write_bytes(_canonical({**claim, "attempt_id": "gha-77"}))
    outcome = decode_outcome((directory / "outcome.json").read_text(encoding="ascii"))
    assert outcome.report_evidence is not None
    evidence = replace(outcome.report_evidence, attempt_id="gha-77")
    retagged = replace(outcome, attempt_id="gha-77", report_evidence=evidence)
    (directory / "outcome.json").write_bytes(encode_outcome(retagged).encode("ascii"))
    verdict = read_verdict(aggregate(world.reg, cells, mkdir(tmp_path / "out")))
    entry = verdict["cells"][HOLD_CELL]
    assert (entry["state"], entry["attempt_id"]) == ("completed", "gha-77")
    # ...but it names no run, and its folder is attempt 2: a re-run, never a verdict.
    assert (entry["artifact_attempt"], entry["run_id"]) == (2, None)
    assert verdict["run"]["reruns"] == [
        f"{HOLD_CELL}: artifact attempt 2, not 1; claimed by an unreadable run, not this run run-1"
    ]
    assert verdict["status"] == "incomplete"


# --- never a pass with missing comparisons ---------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [(), (MISSING,), (FAILED,), (KILLED,), (NO_RECEIPT,), (PICKS,)],
    ids=["none", "missing", "failed", "killed", "invalid", "picks"],
)
def test_an_acceptance_pass_with_any_unfinished_cell_is_incomplete(
    world, matrix, decoded, tmp_path, monkeypatch, broken
):
    """Acceptance stubbed to pass: one unfinished W1 cell, or an unfinished picks job,
    alone makes the summary incomplete. The matrix's outcomes come from their one decode
    (the same objects for the same text) and pages render as a stub, to keep six full
    aggregations fast; neither affects the status."""
    cells = long_paths(tmp_path / "cells")
    shutil.copytree(matrix, cells, copy_function=os.link)
    break_cells(cells, broken)
    judged: list[RunOutcome] = []

    def passing(registration, outcomes):
        judged.extend(outcomes)
        return AcceptanceResult("pass", (), (), tuple(outcomes))

    monkeypatch.setattr(aggregation, "evaluate", passing)
    monkeypatch.setattr(aggregation, "decode_outcome", lambda text: decoded[text])
    monkeypatch.setattr(
        aggregation, "render_bundle_report", lambda report, title, **_: (title, None)
    )
    verdict = read_verdict(aggregate(world.reg, cells, mkdir(tmp_path / "out")))
    assert verdict["acceptance_status"] == "pass"
    reasons = verdict["cell_incomplete_reasons"]
    if not broken:
        assert verdict["status"] == "pass" and reasons == [] and len(judged) == 208
        return
    (owner,) = broken
    assert verdict["status"] == "incomplete"
    assert len(reasons) == 1 and reasons[0].startswith(f"{owner}: ")
    withheld = 0 if owner == PICKS else 1  # an invalid cell's outcome too (Ruling R3)
    assert len(judged) == 208 - withheld
    assert attempt_of(owner) not in {row.attempt_id for row in judged} or owner == PICKS


def test_an_existing_summary_is_never_replaced(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    out = tmp_path / "out"
    (out / "summary").mkdir(parents=True)
    (out / "summary" / "verdict.json").write_text("earlier")
    with pytest.raises(FileExistsError):
        aggregate(world.reg, cells, out)
    assert (out / "summary" / "verdict.json").read_text() == "earlier"


# --- re-runs (Ruling F1) ---------------------------------------------------------------


def retag(directory: Path, attempt_id: str) -> None:
    """A baseline cell's claim and outcome under ``attempt_id``. Each file is replaced,
    unlinked first, so a hard-linked copy of the matrix stays intact."""
    claim_path, outcome_path = directory / "attempt.json", directory / "outcome.json"
    claim = json.loads(claim_path.read_bytes())
    outcome = decode_outcome(outcome_path.read_text(encoding="ascii"))
    assert outcome.report_evidence is not None
    evidence = replace(outcome.report_evidence, attempt_id=attempt_id)
    retagged = replace(outcome, attempt_id=attempt_id, report_evidence=evidence)
    for path, raw in (
        (claim_path, _canonical({**claim, "attempt_id": attempt_id})),
        (outcome_path, encode_outcome(retagged).encode("ascii")),
    ):
        path.unlink()
        path.write_bytes(raw)


def rerun(cells: Path, cell_id: str, attempt: int, run: str = "run-1") -> None:
    """``cell_id`` as a re-run leaves it: its folder named for ``attempt``, and its claim
    and outcome those of attempt ``attempt`` of ``run``."""
    target = cells / folder_of(cell_id, attempt)
    if attempt != 1:
        (cells / folder_of(cell_id)).rename(target)
    retag(target / cell_id, f"{run}-{cell_id}-attempt-{attempt}")


def stub_acceptance(monkeypatch, decoded: dict[str, RunOutcome], status: str = "pass") -> None:
    """Acceptance stubbed to ``status``; the matrix's outcomes from their one decode and
    pages as a stub, to keep full aggregations fast (neither affects the status)."""
    decode = aggregation.decode_outcome

    def accept(registration, outcomes):
        failures = ("a stubbed failure",) if status == "fail" else ()
        return AcceptanceResult(status, failures, (), tuple(outcomes))

    monkeypatch.setattr(aggregation, "evaluate", accept)
    monkeypatch.setattr(
        aggregation, "decode_outcome", lambda text: decoded.get(text) or decode(text)
    )
    monkeypatch.setattr(
        aggregation, "render_bundle_report", lambda report, title, **_: (title, None)
    )


SECOND_HOLD = MISSING  # w1.matched_spot_hold.native.c2.research
W0_RERUN = W0_CELL  # a W0 cell: reported only


@pytest.mark.parametrize(
    ("case", "attempt_id", "expected"),
    [
        ("lone attempt 2", RUN, [f"{HOLD_CELL}: artifact attempt 2, not 1"]),
        (
            "mixed attempts",
            RUN,
            [
                f"{HOLD_CELL}: artifact attempt 2, not 1",
                f"{SECOND_HOLD}: artifact attempt 3, not 1",
            ],
        ),
        ("foreign run id", RUN, [f"{HOLD_CELL}: claimed by run run-9, not this run run-1"]),
        ("aggregated by another run", "run-2-attempt-1", None),
        ("aggregate re-run alone", "run-1-attempt-2", []),
        ("a W0 re-run", RUN, []),
    ],
)
def test_a_rerun_makes_an_acceptance_pass_incomplete(
    world, matrix, decoded, tmp_path, monkeypatch, case, attempt_id, expected
):
    """Acceptance stubbed to pass: any W1 cell (or the picks job) from an artifact attempt
    other than 1, or claimed by another run than aggregation's, makes it incomplete. A
    lone attempt-2 folder is one: attempt 1 of that cell left no artifact at all."""
    cells = long_paths(tmp_path / "cells")
    shutil.copytree(matrix, cells, copy_function=os.link)
    if case == "lone attempt 2":
        rerun(cells, HOLD_CELL, 2)
    elif case == "mixed attempts":
        rerun(cells, HOLD_CELL, 2)
        rerun(cells, SECOND_HOLD, 3)
    elif case == "foreign run id":
        rerun(cells, HOLD_CELL, 1, run="run-9")
    elif case == "a W0 re-run":
        shutil.rmtree(cells / folder_of(W0_RERUN))  # W0 is reported only
        shutil.copytree(cell_dir(matrix, W0_RERUN), cell_dir(cells, W0_RERUN, 2))
        claim = cell_dir(cells, W0_RERUN, 2) / "attempt.json"
        document = json.loads(claim.read_bytes())
        # Its claim names attempt 2 (its outcome still names 1, so the cell is invalid;
        # W0 never reaches the status either way).
        retagged = f"run-1-{W0_RERUN}-attempt-2"
        claim.write_bytes(_canonical({**document, "attempt_id": retagged}))
    stub_acceptance(monkeypatch, decoded)
    verdict = read_verdict(
        aggregate(world.reg, cells, mkdir(tmp_path / "out"), attempt_id=attempt_id)
    )
    assert verdict["acceptance_status"] == "pass"
    reruns = verdict["run"]["reruns"]
    if expected is None:  # every artifact claims run-1, aggregation is run-2: all 209
        assert len(reruns) == 208 + 1
        assert reruns[-1] == f"{PICKS}: claimed by run run-1, not this run run-2"
    else:
        assert reruns == expected
    assert verdict["run"]["rerun_detected"] is bool(reruns)
    if not reruns:
        assert verdict["status"] == "pass"
        if case == "a W0 re-run":
            assert verdict["run"]["reported_only_reruns"] == [
                f"{W0_RERUN}: artifact attempt 2, not 1"
            ]
            assert verdict["cells"][W0_RERUN]["artifact_attempt"] == 2
        else:
            assert verdict["run"]["aggregate_attempt"] == 2  # re-running aggregate alone
        return
    assert verdict["status"] == "incomplete"
    text = (tmp_path / "out" / "summary" / "summary.md").read_text(encoding="utf-8")
    assert "Verdict: **INCOMPLETE** (re-run detected:" in text
    section = text.split("## Re-run detected", 1)[1].split("\n## ", 1)[0]
    for item in reruns[:3]:
        assert f"- {item}" in section
    if case == "lone attempt 2":
        entry = verdict["cells"][HOLD_CELL]
        assert entry["state"] == "completed"  # the cell itself holds together
        assert (entry["artifact_attempt"], entry["run_id"]) == (2, "run-1")
    if case == "foreign run id":
        assert verdict["cells"][HOLD_CELL]["run_id"] == "run-9"


DISPATCHES = {
    "an earlier dispatch": ("another dispatch of this registration: run 400",),
    "two of them": (
        "another dispatch of this registration: run 300",
        "another dispatch of this registration: run 400",
    ),
    "a check that failed": (
        "another dispatch of this registration could not be ruled out: GitHub API "
        "/repos/o/r/actions/runs/500: HTTP 502",
    ),
}


@pytest.mark.parametrize("acceptance", ["pass", "fail"])
@pytest.mark.parametrize("case", list(DISPATCHES))
def test_another_dispatch_of_the_registration_leaves_the_verdict_incomplete(
    world, matrix, decoded, tmp_path, monkeypatch, case, acceptance
):
    """Ruling R4-2: a registration is dispatched once. Another registered dispatch of it,
    or a dispatch check that could not rule one out, makes the verdict incomplete (neither
    a pass nor a fail), names it, and is disclosed in the summary, the cells unchanged."""
    cells = long_paths(tmp_path / "cells")
    shutil.copytree(matrix, cells, copy_function=os.link)
    stub_acceptance(monkeypatch, decoded, status=acceptance)
    found = DISPATCHES[case]
    summary = aggregate(world.reg, cells, mkdir(tmp_path / "out"), other_dispatches=found)
    verdict = read_verdict(summary)
    assert (verdict["acceptance_status"], verdict["status"]) == (acceptance, "incomplete")
    assert verdict["run"]["other_dispatches"] == list(found)
    assert verdict["run"]["reruns"] == [] and verdict["run"]["rerun_detected"] is False
    text = (summary / "summary.md").read_text(encoding="utf-8")
    assert "Verdict: **INCOMPLETE** (another dispatch of this registration" in text
    section = text.split("## Another dispatch of this registration", 1)[1].split("\n## ", 1)[0]
    for item in found:
        assert f"- {item}" in section
    # Without it, the same cells and stub give acceptance's own verdict.
    clean = read_verdict(aggregate(world.reg, cells, mkdir(tmp_path / "clean")))
    assert (clean["status"], clean["run"]["other_dispatches"]) == (acceptance, [])
    clean_text = (tmp_path / "clean" / "summary" / "summary.md").read_text(encoding="utf-8")
    assert "None: no other run of this workflow dispatched this registration" in clean_text


@pytest.mark.parametrize("mode", ["rehearsal", "smoke"])
def test_a_synthetic_runs_summary_says_its_dispatches_were_not_checked(
    world, matrix, tmp_path, mode
):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    summary = aggregate(world.reg, cells, mkdir(tmp_path / "out"), mode=mode)
    assert read_verdict(summary)["run"]["other_dispatches"] == []
    text = (summary / "summary.md").read_text(encoding="utf-8")
    section = text.split("## Another dispatch of this registration", 1)[1].split("\n## ", 1)[0]
    assert f"Not checked: a {mode} run dispatches no registration" in section


@pytest.mark.parametrize("bad", [("",), (" ",), (None,), ("run 400", 400), "run 400"])
def test_malformed_other_dispatches_are_refused_before_anything_is_written(
    world, matrix, tmp_path, bad
):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError, match="other dispatches"):
        aggregate(world.reg, cells, out, other_dispatches=bad)
    assert list(out.iterdir()) == []


def test_a_rerun_voids_an_acceptance_fail_too(world, matrix, decoded, tmp_path, monkeypatch):
    cells = long_paths(tmp_path / "cells")
    shutil.copytree(matrix, cells, copy_function=os.link)
    rerun(cells, HOLD_CELL, 2)
    stub_acceptance(monkeypatch, decoded, status="fail")
    verdict = read_verdict(aggregate(world.reg, cells, mkdir(tmp_path / "out")))
    assert (verdict["acceptance_status"], verdict["status"]) == ("fail", "incomplete")
    assert verdict["failures"] == ["a stubbed failure"]  # still disclosed
    # Without the re-run the same stub is a fail.
    clean = copy_cells(matrix, tmp_path / "clean", (HOLD_CELL,))
    assert read_verdict(aggregate(world.reg, clean, mkdir(tmp_path / "out2")))["status"] == "fail"


@pytest.mark.parametrize(
    "bad", ["run-1", "run-1-attempt-01", "run-1-attempt-0", "-attempt-1", "", None]
)
def test_a_malformed_aggregate_attempt_id_is_refused_before_anything_is_written(
    world, matrix, tmp_path, bad
):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError, match="aggregate attempt id"):
        aggregate(world.reg, cells, out, attempt_id=bad)
    assert list(out.iterdir()) == []


# --- the other invalid and refused branches (Ruling F12) --------------------------------


def test_a_report_labelled_with_another_capital_is_refused(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))  # a research cell
    path = cell_dir(cells, HOLD_CELL) / "outcome.json"
    outcome = decode_outcome(path.read_text(encoding="ascii"))
    assert outcome.report_evidence is not None
    owner = run_cell._capital(world.reg, "owner_small")
    report = replace(outcome.report_evidence.report, capital_label=capital_label(owner))
    evidence = replace(outcome.report_evidence, report=report)
    path.write_bytes(encode_outcome(replace(outcome, report_evidence=evidence)).encode("ascii"))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError) as refused:
        aggregate(world.reg, cells, out)
    assert f"{HOLD_CELL}: its report is labelled with another capital" in str(refused.value)
    assert list(out.iterdir()) == []


def invalid_reasons(world: World, cells: Path, tmp_path: Path, cell_id: str) -> list[str]:
    """Aggregate ``cells``; ``cell_id`` must be invalid and the run incomplete: its
    reasons."""
    verdict = read_verdict(aggregate(world.reg, cells, mkdir(tmp_path / "out")))
    entry = verdict["cells"][cell_id]
    assert entry["state"] == "invalid" and verdict["status"] != "pass"
    assert any(r.startswith(f"{cell_id}: ") for r in verdict["cell_incomplete_reasons"])
    return entry["reasons"]


def test_a_report_json_that_is_not_the_outcomes_report_makes_the_cell_invalid(
    world, matrix, tmp_path
):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    other = cell_dir(matrix, SECOND_HOLD) / "report.json"  # the doubled-cost cell's report
    (cell_dir(cells, HOLD_CELL) / "report.json").write_bytes(other.read_bytes())
    reasons = invalid_reasons(world, cells, tmp_path, HOLD_CELL)
    assert reasons == ["report.json is not the outcome's report evidence"]


def test_a_bundle_that_does_not_bind_its_outcome_makes_the_cell_invalid(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (COMBINED[0],))
    path = cell_dir(cells, COMBINED[0]) / "outcome.json"
    outcome = decode_outcome(path.read_text(encoding="ascii"))
    changed = replace(outcome, disclosures=(*outcome.disclosures, "edited after the bundle"))
    path.write_bytes(encode_outcome(changed).encode("ascii"))
    reasons = invalid_reasons(world, cells, tmp_path, COMBINED[0])
    invocation_name = invocation(COMBINED[0])
    assert reasons == [
        f"evidence bundle {invocation_name}/ does not bind this cell's outcome and report"
    ]


def test_an_outcome_of_another_attempt_than_its_claim_makes_the_cell_invalid(
    world, matrix, tmp_path
):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    path = cell_dir(cells, HOLD_CELL) / "outcome.json"
    outcome = decode_outcome(path.read_text(encoding="ascii"))
    assert outcome.report_evidence is not None
    other = "run-1-another-attempt-1"
    evidence = replace(outcome.report_evidence, attempt_id=other)
    path.write_bytes(
        encode_outcome(replace(outcome, attempt_id=other, report_evidence=evidence)).encode()
    )
    reasons = invalid_reasons(world, cells, tmp_path, HOLD_CELL)
    assert reasons == ["the outcome is of another attempt than the claim"]


def test_an_unreadable_outcome_makes_the_cell_invalid(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    (cell_dir(cells, HOLD_CELL) / "outcome.json").write_bytes(b'{"schema": "not an outcome"}')
    (reason,) = invalid_reasons(world, cells, tmp_path, HOLD_CELL)
    assert reason.startswith("outcome.json unreadable: ")


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("job", "w1.combined.olhc.c1.research", "its attempt.json claims job"),
        ("code_pin", "8" * 40, "attempt.json code_pin"),
        ("config_pin", "8" * 64, "attempt.json config_pin"),
        ("data_pin", "8" * 64, "attempt.json data_pin"),
        ("pack_sha256", "8" * 64, "attempt.json pack_sha256"),
    ],
)
def test_a_picks_claim_of_another_job_or_other_pins_is_refused(
    world, matrix, tmp_path, field, value, named
):
    cells = copy_cells(matrix, tmp_path / "cells", (PICKS, HOLD_CELL))
    path = cell_dir(cells, PICKS) / "attempt.json"
    path.write_bytes(_canonical({**json.loads(path.read_bytes()), field: value}))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError) as refused:
        aggregate(world.reg, cells, out)
    assert f"{PICKS}: " in str(refused.value) and named in str(refused.value)
    assert HOLD_CELL not in str(refused.value)
    assert list(out.iterdir()) == []


def test_two_picks_jobs_are_refused_as_duplicates(world, matrix, tmp_path):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    for attempt in (1, 3):
        shutil.copytree(cell_dir(matrix, PICKS), cell_dir(cells, PICKS, attempt))
    claim = cell_dir(cells, PICKS, 3) / "attempt.json"
    document = json.loads(claim.read_bytes())
    claim.write_bytes(_canonical({**document, "attempt_id": "run-1-v3_picks-attempt-3"}))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError) as refused:
        aggregate(world.reg, cells, out)
    message = str(refused.value)
    assert "v3_picks: duplicate artifact sets (v3-picks-attempt-1, v3-picks-attempt-3)" in message
    assert list(out.iterdir()) == []


# --- the run's mode (a rehearsal never looks like the registered verdict) ---------------


@pytest.mark.parametrize(
    ("mode", "title"),
    [
        ("registered", "# V3.1 run summary: registered run"),
        (
            "rehearsal",
            "# V3.1 run summary: REHEARSAL (a synthetic world; no verdict on market data)",
        ),
        ("smoke", "# V3.1 run summary: SMOKE (a synthetic world; no verdict on market data)"),
    ],
)
def test_the_verdict_and_the_summary_name_the_runs_mode(world, matrix, tmp_path, mode, title):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    summary = aggregate(world.reg, cells, mkdir(tmp_path / "out"), mode=mode)
    assert read_verdict(summary)["mode"] == mode
    text = (summary / "summary.md").read_text(encoding="utf-8")
    assert text.splitlines()[0] == title


@pytest.mark.parametrize("bad", ["", "Registered", "prepare-only", "timing", None])
def test_an_unknown_mode_is_refused_before_anything_is_written(world, matrix, tmp_path, bad):
    cells = copy_cells(matrix, tmp_path / "cells", (HOLD_CELL,))
    out = mkdir(tmp_path / "out")
    with pytest.raises(ValueError, match="aggregate mode"):
        aggregate(world.reg, cells, out, mode=bad)
    assert list(out.iterdir()) == []
