"""The V3.1 baseline cells, each run once: the matched spot hold and the frozen V3 arms.

``run_hold_cell`` replays the hold adapter on the cell's window pack. The frozen V3 arms
read the V3 input pack (``driver.v3_pack``, Rulings P9 and P15): ``compute_v3_picks``
trains V3's unchanged selector once, and ``run_v3_cell`` replays one V3 arm on a registered
window, the selector from those shared picks. Every job follows ``run_cell``'s protocol
(Ruling P13), with its helpers: cheap checks first, then the claim (the directory, created
once, and ``attempt.json``), then the work under a fresh default decimal context, then the
files, each an exclusive create, the completion marker last; an exception after the claim
leaves ``failure.json`` and propagates::

    <out_dir>/<cell_id>/attempt.json            the claim: cell id, attempt id, repo head,
                                                code and config pins, the pack's SHA-256
                                                (a V3 cell's is the V3 input pack's) and
                                                the data pin
    <out_dir>/<cell_id>/native_evidence.json    the cell's metadata (run_cell's fields)
                                                and the adapter's own evidence
    <out_dir>/<cell_id>/report.json             encode_report
    <out_dir>/<cell_id>/outcome.json            encode_outcome, last: the completion marker

    <out_dir>/v3_picks/attempt.json             the claim, with ``job`` for ``cell_id``
    <out_dir>/v3_picks/attempts.jsonl           V3's own attempt records, streamed
    <out_dir>/v3_picks/v3_picks.json            the picks, last: the completion marker

A baseline adapter returns ``BaselineEvidence``, which holds no funnel journal
(``Evidence``), so a baseline cell has no ``write_bundle`` bundle. ``native_evidence.json``
holds what the adapter records besides its report: the native marks in its own timing
(``[timestamp_ms, kind, equity, spot_value, futures_collateral]``), its stop status,
liquidations, accounting residual and checks, and its disclosures. Nothing here touches
the network.
"""

import hashlib
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from crypto_grid_bot.combined.artifacts import _canonical, _safe_path, _write
from crypto_grid_bot.combined.baseline_hold import HoldMarket, replay_hold_baseline
from crypto_grid_bot.combined.baseline_records import BaselineEvidence, refuse_sealed
from crypto_grid_bot.combined.baseline_v3 import (
    SELECTOR,
    V3Inputs,
    replay_v3_baseline,
    selector_picks,
    window_picks,
)
from crypto_grid_bot.combined.driver.packs import WindowPack
from crypto_grid_bot.combined.driver.registration import (
    Cell,
    CellKind,
    DriverRegistration,
    _strict_json,
)
from crypto_grid_bot.combined.driver.run_cell import (
    _attempt,
    _capital,
    _check_attempt,
    _claimed,
    _identity,
    _metadata,
    _pack_errors,
    _registered,
)
from crypto_grid_bot.combined.driver.serialize import encode_outcome, encode_report
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.experiment import Capital, Window, capital_label
from crypto_grid_bot.combined.outcomes import baseline_outcome
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.walk_forward import RULES

V3_PICKS = "v3_picks"  # the picks job's directory under out_dir
PICKS_FILE = "v3_picks.json"
ATTEMPTS_FILE = "attempts.jsonl"
NATIVE_EVIDENCE_FILE = "native_evidence.json"
BASELINE_SCHEMA = "v3.1-baseline-1"
PICKS_SCHEMA = "v3.1-v3-picks-1"
MAX_PICKS_BYTES = 1024 * 1024

_RESERVED = 1_735_689_600_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"0|[1-9][0-9]*")
_RUN_ID = re.compile(r"([0-9a-f]{32})-(.+)", re.DOTALL)
_PICKS_KEYS = frozenset(
    {"schema", "v3_pack_sha256", "run_manifest_sha256", "attempts_sha256", "picks"}
)


def run_hold_cell(
    cell: Cell,
    pack: WindowPack,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Replay the registered matched spot hold cell ``cell`` on ``pack`` once and return
    its artifact directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    Each pack coin is one market: its spot hourly bars and spot rules at the base spot
    costs, ``cost_profile(1, "spot")``, because ``replay_hold_baseline`` itself scales the
    fee and slippage rates by ``cost_multiple``, which is the cell's. The capital, window,
    skipped hours (the pack's, equal to the registered window's) and adapter pin come from
    the registration. Refuses, before anything is written, a cell that is not a registered
    native hold cell, a pack of another window, an empty attempt id, a repo head that is
    not 40 lowercase hex and an existing cell directory.
    """
    window = _baseline_window(cell, reg, "hold", "a matched spot hold cell required")
    if errors := _pack_errors(pack, window):
        raise ValueError(f"cell {cell.cell_id}: " + "; ".join(errors))
    _check_attempt(attempt_id, repo_head)
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(reg.registration.adapter_pins)[cell.arm]
    pack_pin = dict(reg.run_manifest.window_packs)[cell.window]
    attempt = _cell_attempt(cell, reg, window, attempt_id, repo_head, pack_pin)
    directory = Path(out_dir) / cell.cell_id
    with _claimed(directory, attempt):
        base = cost_profile(1, "spot")  # scaled by the adapter, never here as well
        markets = {
            coin.symbol: HoldMarket(coin.spot_hourly, coin.spot_rules, base) for coin in pack.coins
        }
        evidence = replay_hold_baseline(
            markets,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            initial=capital.initial_equity,
            cost_multiple=cell.cost_multiple,
            source_refs=(f"v31-pack:{pack_pin}", f"v31-run-manifest:{reg.run_manifest_pin}"),
            adapter_pin=adapter_pin,
            skipped_hours=pack.skipped_hours,
            capital_label=capital_label(capital),
        )
        _write_cell(
            directory, attempt, cell, reg, window, capital, adapter_pin, evidence, attempt_id
        )
    return directory


def compute_v3_picks(
    v3_inputs: V3Inputs,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Train V3's unchanged selector once and return the path of its picks,
    ``out_dir/v3_picks/v3_picks.json``, which every V3 cell then reads.

    ``selector_picks`` runs V3's frozen walk-forward at research capital (10,000 USDT)
    and base cost, holding the capital adapter's lock. Each attempt V3 records is written
    at once as one canonical line of ``attempts.jsonl`` (``_AttemptLog``), so a failed
    walk-forward keeps every attempt it made. ``v3_picks.json`` is canonical JSON: the
    schema, the V3 input pack's and the run-manifest's SHA-256, the SHA-256 of
    ``attempts.jsonl`` and ``picks``, each pick time in ms as a decimal string mapped to
    its rule, or null for a flat quarter.

    ``v3_inputs`` must be ``read_v3_pack(path, reg.run_manifest.v3_pack)``: the V3 input
    pack read against the run-manifest's ``v3_pack_sha256``. Refuses, before anything is
    written, other inputs, an empty attempt id, a repo head that is not 40 lowercase hex
    and an existing picks directory.
    """
    if not isinstance(v3_inputs, V3Inputs):
        raise ValueError("V3 inputs (read_v3_pack) required")
    if not isinstance(reg, DriverRegistration):
        raise ValueError("a DriverRegistration required")
    _check_attempt(attempt_id, repo_head)
    pin = reg.run_manifest.v3_pack
    attempt: dict[str, object] = {
        "job": V3_PICKS,
        **_attempt(
            reg,
            attempt_id=attempt_id,
            repo_head=repo_head,
            pack_sha256=pin,
            data_pin=reg.run_manifest_pin,
        ),
    }
    directory = Path(out_dir) / V3_PICKS
    with _claimed(directory, attempt):
        with _AttemptLog(directory / ATTEMPTS_FILE) as log:
            picks, _ = selector_picks(v3_inputs, record=log)
        document = {
            "schema": PICKS_SCHEMA,
            "v3_pack_sha256": pin,
            "run_manifest_sha256": reg.run_manifest_pin,
            "attempts_sha256": log.sha256(),
            "picks": _picks_document(picks),
        }
        _write(directory / PICKS_FILE, _canonical(document))  # last: the completion marker
    return directory / PICKS_FILE


def run_v3_cell(
    cell: Cell,
    v3_inputs: V3Inputs,
    picks_path: Path,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Replay the registered frozen V3 cell ``cell`` once and return its artifact
    directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    ``v3_inputs`` must be ``read_v3_pack(path, reg.run_manifest.v3_pack)``: a V3 cell's
    data is the V3 input pack, read against the run-manifest's ``v3_pack_sha256``, never a
    window pack's pin. The execution gate checks the cell's window pack (W1), whose skipped
    hours are the registered window's that this cell's report uses. ``picks_path`` is
    ``compute_v3_picks``'s file; it must name the same V3 pack and run-manifest. The
    selector replays ``window_picks`` of those picks over the window; a fixed long-only
    rule takes no picks, as its adapter replays the rule itself. The capital's starting
    equity, the cell's cost multiple (V3's own native cost multiple), the window and the
    adapter pin come from the registration. Refuses, before anything is written, a cell
    that is not a registered native V3 cell, other inputs, an unreadable or untrusted
    picks file, an empty attempt id, a repo head that is not 40 lowercase hex and an
    existing cell directory.
    """
    window = _baseline_window(cell, reg, "v3", "a frozen V3 baseline cell required")
    if not isinstance(v3_inputs, V3Inputs):
        raise ValueError("V3 inputs (read_v3_pack) required")
    _check_attempt(attempt_id, repo_head)
    picks, picks_sha256 = _read_picks(picks_path, reg)
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(reg.registration.adapter_pins)[cell.arm]
    pin = reg.run_manifest.v3_pack
    attempt = _cell_attempt(cell, reg, window, attempt_id, repo_head, pin)
    refs = (f"v3-pack:{pin}", f"v31-run-manifest:{reg.run_manifest_pin}")
    selector = cell.arm == SELECTOR
    directory = Path(out_dir) / cell.cell_id
    with _claimed(directory, attempt):
        evidence = replay_v3_baseline(
            cell.arm,
            v3_inputs,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            initial=capital.initial_equity,
            cost_multiple=cell.cost_multiple,
            source_refs=(*refs, f"v3-picks:{picks_sha256}") if selector else refs,
            adapter_pin=adapter_pin,
            picks=window_picks(picks, window.start_ms, window.end_ms) if selector else None,
            skipped_hours=window.skipped_hours,
            capital_label=capital_label(capital),
        )
        _write_cell(
            directory, attempt, cell, reg, window, capital, adapter_pin, evidence, attempt_id
        )
    return directory


def _baseline_window(cell: Cell, reg: DriverRegistration, kind: CellKind, required: str) -> Window:
    """The registered window of ``cell``, a registered baseline cell of ``kind``; a
    baseline runs in V3.1's native scenario only."""
    window = _registered(cell, reg, kind, required)
    if cell.scenario != "native":
        raise ValueError(f"cell {cell.cell_id}: a baseline cell runs native")
    return window


def _cell_attempt(
    cell: Cell,
    reg: DriverRegistration,
    window: Window,
    attempt_id: str,
    repo_head: str,
    pack_sha256: str,
) -> dict[str, object]:
    return {
        "cell_id": cell.cell_id,
        **_attempt(
            reg,
            attempt_id=attempt_id,
            repo_head=repo_head,
            pack_sha256=pack_sha256,
            data_pin=window.data_pin,
        ),
    }


def _write_cell(
    directory: Path,
    attempt: Mapping[str, object],
    cell: Cell,
    reg: DriverRegistration,
    window: Window,
    capital: Capital,
    adapter_pin: str,
    evidence: BaselineEvidence,
    attempt_id: str,
) -> None:
    """The cell's outcome under its registered identity, then its files in order:
    the native evidence, the report and, last, the outcome."""
    identity = _identity(cell, reg, window, capital, adapter_pin)
    outcome = baseline_outcome(evidence, identity, attempt_id=attempt_id)
    outcome_raw = encode_outcome(outcome).encode("ascii")
    report_raw = encode_report(evidence.report).encode("ascii")
    metadata = _metadata(
        BASELINE_SCHEMA, attempt, cell, capital, reg, adapter_pin, outcome_raw, report_raw
    )
    native = {**metadata, "evidence": _evidence_document(evidence)}
    _write(directory / NATIVE_EVIDENCE_FILE, _canonical(native))
    _write(directory / "report.json", report_raw)
    _write(directory / "outcome.json", outcome_raw)  # last: the completion marker


def _evidence_document(evidence: BaselineEvidence) -> dict[str, object]:
    """The adapter's evidence besides its report, Decimals as their ``str()``."""
    return {
        "arm": evidence.arm,
        "native_label": evidence.native_label,
        "status": evidence.status,
        "liquidations": evidence.liquidations,
        "accounting_residual": _text(evidence.accounting_residual),
        "accounting_explained": evidence.accounting_explained,
        "wallet_quantity_exact": evidence.wallet_quantity_exact,
        "disclosures": list(evidence.disclosures),
        "native_marks": [
            [
                mark.timestamp_ms,
                mark.kind,
                _text(mark.equity),
                _text(mark.spot_value),
                _text(mark.futures_collateral),
            ]
            for mark in evidence.native
        ],
    }


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise ValueError("baseline evidence values must be Decimals")
    return str(value)


class _AttemptLog:
    """V3's ``record`` callback: each ``Attempt`` becomes one canonical JSON line of a new
    file, written, flushed and synced before the walk-forward goes on (V3's contract: the
    caller persists each record before returning); no runner is kept.

    A line holds the attempt's fields (its run id as ``run``) and, for a result, its stop
    reason, trade reconciliation residual and final equity. V3 prefixes every run id of a
    walk-forward with one random ``uuid4().hex``, the only part that differs between two
    runs on the same inputs: it is dropped, so the file is byte-identical across runs; the
    rest of the run id and the state name each record uniquely.
    """

    def __init__(self, path: Path) -> None:
        self._stream: BinaryIO = _safe_path(path).open("xb")
        self._digest = hashlib.sha256()
        self._prefix: str | None = None

    def __enter__(self) -> "_AttemptLog":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stream.close()

    def __call__(self, attempt: Attempt) -> None:
        if not isinstance(attempt, Attempt):
            raise ValueError("V3 attempt record required")
        row = {
            "run": self._run(attempt.run_id),
            "state": attempt.state,
            "phase": attempt.phase,
            "rule": attempt.rule,
            "start_ms": attempt.start_ms,
            "end_ms_exclusive": attempt.end_ms_exclusive,
            "multiple": attempt.multiple,
            "cost_multiple": attempt.cost_multiple,
            "pick_schedule": [[stamp, rule] for stamp, rule in attempt.pick_schedule],
            "error": attempt.error,
            "result": None if attempt.result is None else _result(attempt.result),
        }
        line = _canonical(row) + b"\n"
        self._stream.write(line)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._digest.update(line)

    def sha256(self) -> str:
        """The SHA-256 of every line written."""
        return self._digest.hexdigest()

    def _run(self, run_id: str) -> str:
        match = _RUN_ID.fullmatch(run_id) if type(run_id) is str else None
        if match is None:
            raise ValueError(f"V3 run id {run_id!r}: a walk-forward's hex prefix required")
        prefix, run = match.groups()
        if self._prefix is None:
            self._prefix = prefix
        elif prefix != self._prefix:
            raise ValueError("V3 attempts of more than one walk-forward")
        return run


def _result(result: ReplayResult) -> dict[str, object]:
    runner = result.runner
    path = runner.equity_path if runner is not None else []
    return {
        "reason": result.reason,
        "trade_reconciliation_residual": _text(result.trade_reconciliation_residual),
        "final_equity": _text(path[-1].equity) if path else None,
    }


def _picks_document(picks: Mapping[int, str | None]) -> dict[str, str | None]:
    """The picks as JSON: each time in ms as a decimal string, before the reserved
    boundary, mapped to a frozen rule or null."""
    refuse_sealed(picks, "V3 picks")
    if not picks or any(rule is not None and rule not in RULES for rule in picks.values()):
        raise ValueError("V3 picks: one or more picks of frozen rules or null required")
    return {str(stamp): rule for stamp, rule in sorted(picks.items())}


def _read_picks(path: Path, reg: DriverRegistration) -> tuple[dict[int, str | None], str]:
    """The picks in ``compute_v3_picks``'s file at ``path``, and the file's SHA-256.

    The file must be the canonical JSON ``compute_v3_picks`` writes, for the registered
    V3 input pack and run-manifest; any other text, schema, pin, time or rule is refused.
    """
    raw = Path(path).read_bytes()
    if len(raw) > MAX_PICKS_BYTES:
        raise ValueError(f"{path}: a V3 picks file of at most {MAX_PICKS_BYTES} bytes required")
    document = _strict_json(raw, "V3 picks")
    if not isinstance(document, dict) or set(document) != _PICKS_KEYS:
        raise ValueError(f"V3 picks: the fields {sorted(_PICKS_KEYS)} required")
    if _canonical(document) != raw:
        raise ValueError("V3 picks: not the canonical encoding (sorted keys, no spaces, ASCII)")
    if document["schema"] != PICKS_SCHEMA:
        raise ValueError(f"V3 picks: schema {PICKS_SCHEMA!r} required")
    if document["v3_pack_sha256"] != reg.run_manifest.v3_pack:
        raise ValueError("V3 picks: computed from another V3 pack than the run-manifest's")
    if document["run_manifest_sha256"] != reg.run_manifest_pin:
        raise ValueError("V3 picks: computed under another run-manifest")
    attempts = document["attempts_sha256"]
    if not isinstance(attempts, str) or _SHA256.fullmatch(attempts) is None:
        raise ValueError("V3 picks: the attempts' SHA-256 must be 64 lowercase hex")
    given = document["picks"]
    if not isinstance(given, dict):
        raise ValueError("V3 picks: an object of picks required")
    picks: dict[int, str | None] = {}
    for stamp, rule in given.items():
        if _STAMP.fullmatch(stamp) is None or int(stamp) >= _RESERVED:
            raise ValueError(f"V3 picks: time {stamp!r} must be ms before the reserved boundary")
        if rule is not None and rule not in RULES:
            raise ValueError(f"V3 picks: {rule!r} is not a frozen V3 rule")
        picks[int(stamp)] = rule
    if not picks:
        raise ValueError("V3 picks: one or more picks required")
    return dict(sorted(picks.items())), hashlib.sha256(raw).hexdigest()
