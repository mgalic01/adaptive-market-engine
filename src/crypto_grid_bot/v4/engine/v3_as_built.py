"""``v3_as_built``: V3's frozen walk-forward selector, run unchanged on V3's own coins and inputs,
as one arm of the V4 run, with V4-format records and a V4-format summary.

Implements ruling R3 of step 4a (the spec's step-4a amendment, "``v3_as_built``") and the arm's
part of "Pass rule" condition 2. Nothing of V3 is re-implemented: V3.1's reviewed runner
(``combined.baseline_v3``) replays V3's frozen code, and this module reads what it returns.

* **Window.** From ``V3_START_MS``, 2021-07-01 00:00 UTC (V3's first out-of-sample quarter), to
  the open of 2024-12-31 23:00, with V3's terminal mark at ``V3_END_MS``, 2025-01-01 00:00 UTC,
  as the final equity. V3's frozen code refuses data from 2025 on, so the arm ends there and the
  verdict compares it with V4 over their common period.
* **Picks** (``run_v3_picks``): computed once per run with ``selector_picks``, which trains V3's
  walk-forward at 10,000 USDT, V3's size multiple 2 and base cost, under the capital adapter's
  lock. They are written as canonical JSON, ``{"picks": {"<stamp ms>": rule | null}}`` (sorted
  keys, no spaces, ASCII, no newline), never over an existing file, and pinned by the file's
  SHA-256. Every v3 cell requires that pin (``read_v3_picks``), checked before the file is
  parsed.
* **A cell** (``run_v3_cell``): ``replay_v3_baseline(SELECTOR, ...)`` over the window at the
  cell's capital and V3's own cost multiple. That function applies ``window_picks`` and, for a
  capital other than 10,000, ``v3_capital``, with V3's disclosure
  ``v3_capital_adapter_sets_only_starting_capital``. The pins, the cell and an existing output
  are all checked, the picks and the pack read through their pins and the replay run, before
  anything is written: a refusal or an exception leaves nothing behind, not even the folder.
* **Open marks.** An hour's open mark is V3's ``open`` native mark. It is complete iff every one
  of V3's coins (``v3_coins``: the symbols of the pack's futures hourly bars, the bars V3 trades
  on; 10 in V3's pack) has its hourly bar that hour. This is conservative: V3 holds a subset.
* **Outcome.** V3's status None is ``complete``, unless V3's own accounting does not reconcile;
  ``liquidation``, V3's one native stop, is ``liquidated``, with the stop at its mark's hour (the
  last native mark, floored to the hour) and that mark as the final equity; every other V3 stop
  is ``engine_error``, type ``V3Stop`` and message the status (reason ``"V3Stop: <status>"``).
  So a V3 stop is incomplete, never a pass. A status None or a ``liquidation`` whose
  ``accounting_explained`` or ``wallet_quantity_exact`` (``BaselineEvidence``) is not true is
  ``engine_error`` too, type ``V3Accounting`` and message the first of those two flags that
  failed, in that order (controller rulings on task 6): the verdict relies on this comparison,
  so V3's own failed reconciliation makes the cell incomplete, never valid evidence. An
  ``engine_error``'s ``hour_ms`` is the hour of V3's last mark, null without one: for a
  ``V3Accounting`` of a completed run the terminal mark's, ``V3_END_MS``, and of a liquidation
  the liquidation mark's. An exception outside V3's own loop (a refused pin, bad inputs) is not
  an outcome: it propagates, and nothing is written.

**Records** (``records.jsonl`` through ``RecordWriter``, then ``receipt.json``), in this order:

* one ``hourly`` record per hour V3 marked, ``{open_ms, open_equity, complete}``, from the
  window's first hour;
* when V3 has a terminal mark, one ``event`` record ``{type: "terminal", hour_ms, coin: null,
  timestamp_ms, equity}``. The brief names it a ``terminal`` record; ``records.KINDS`` is step
  3's and has no such kind, so it is an ``event`` of that type (controller ruling). A complete
  cell and the ``V3Accounting`` of a completed run have exactly one, at ``V3_END_MS``; a
  liquidated cell and the ``V3Accounting`` of a liquidation have none (V3 marks no terminal
  after a liquidation); another V3 stop has at most one (V3's unavailable exclusion close marks
  one where it stops);
* the ``outcome`` record: ``outcome``, ``reason``, ``stop_ms``, ``hours`` (the open marks),
  ``final_equity``, ``equity_2025`` and ``final_after_close`` (both null), ``liquidations``,
  ``accounting_residual`` (V3's), ``accounting_explained`` and ``wallet_quantity_exact`` (V3's
  own audit flags), V3's ``disclosures``, V3's ``coins``, the ``cell`` (``cell_record``), the
  ``window`` (``{"start_ms": V3_START_MS, "end_ms": V3_END_MS - HOUR_MS}``) and the ``data``
  (``{"v3_pack_sha256", "picks_sha256"}``); plus ``type``, ``message`` and ``hour_ms`` for an
  ``engine_error``.

**The summary** (``build_v3_summary``, ``verify_v3_summary``) has the keys of ``summary.py``'s,
under the format ``v4-summary-v3-1``, built from the records alone by ``summary.py``'s rules: the
cell, window and data bound to the records, the first open mark the capital, the eras and years
of ``_Ending`` and ``ERAS``, every value exact. Its ``data`` is the two pins, ``equity_2025`` and
``final_after_close`` are null (V3's window ends before 2025-01-01 00:00 and V3 makes no closing
trade), and ``accounting_residual`` is the absolute value of V3's. A full summary also has
``disclosures``, V3's own list from the outcome record (a list of nonempty strings, holding
``V3_CAPITAL_ADAPTER`` exactly when the cell's capital is not V3's 10,000), so that the run
summary, which reads summaries only, can disclose the capital adapter of a 1,000 USDT cell; the
short failure summary has none. A complete cell's final equity
is read from its one terminal event, which must be at ``V3_END_MS``; its periods end there, the
window's end; a stop's at its hour. Records with another number of terminal events than their
outcome has (above) are refused. A full summary (``complete`` or ``liquidated``) requires both
of V3's accounting flags in the outcome record to be true and refuses the engine error's keys
(``type``, ``message``, ``hour_ms``) there, as it requires its ``liquidations``, ``hours`` and
nulls to be its outcome's. An ``engine_error`` has the short failure summary; a ``V3Accounting``
one must name the first flag the outcome record shows as not true, and be either a completed
run's (its terminal event at ``V3_END_MS``, every hour marked, its hour ``V3_END_MS``, no
liquidation) or a liquidation's (no terminal event, its hour the last one marked, one
liquidation). Verification
rebuilds the summary with the summary's own cell and requires equality, so a summary or records
of another cell, window, pack or picks do not verify.

**The page** (``render_v3_page``) follows ruling F2: ``summary.render_page`` and
``write_cell_outputs`` take only V4's summary format (and the page's "every position was closed"
does not hold for V3), so this module renders its own minimal page with ``summary.py``'s escaping,
tables, sparkline and style, and writes the two files with ``write_v3_outputs``. A full page lists
the disclosures. The outcome line of a ``V3Accounting`` is worded by case: a completed run (its
hour is ``V3_END_MS``) "ran to its window's end", a liquidation's was liquidated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path

from crypto_grid_bot.combined.artifacts import _canonical, _digest
from crypto_grid_bot.combined.baseline_records import BaselineEvidence, NativeMark
from crypto_grid_bot.combined.baseline_v3 import (
    SELECTOR,
    V3Inputs,
    replay_v3_baseline,
    selector_picks,
)
from crypto_grid_bot.combined.driver.v3_pack import read_v3_pack
from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.signals import RULES
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.records import (
    Receipt,
    RecordWriter,
    _loads,
    read_records,
    write_receipt,
)
from crypto_grid_bot.v4.engine.run import (
    ENGINE_ERROR,
    LIQUIDATED,
    OUTCOME_COMPLETE,
    RECEIPT_FILE,
    RECORDS_FILE,
    cell_record,
)
from crypto_grid_bot.v4.engine.summary import (
    _STYLE,
    ERAS,
    PAGE_FILE,
    SUMMARY_FILE,
    _e,
    _Ending,
    _failure_sections,
    _first_difference,
    _optional_int,
    _optional_str,
    _percent,
    _period_row,
    _plain,
    _receipt_sha256,
    _sparkline,
    _summary_cell,
    _table,
    _text,
    _usdt,
    _when,
    _year_of,
    _year_start,
)

V3_ARM = "v3_as_built"
V3_START_MS = 1625097600000  # 2021-07-01 00:00 UTC, V3's first out-of-sample quarter
V3_END_MS = 1735689600000  # 2025-01-01 00:00 UTC, V3's terminal mark
V3_SUMMARY_FORMAT = "v4-summary-v3-1"
PICKS_FILE = "v3_picks.json"
V3_STOP = "V3Stop"  # the exception type of an engine_error that is a V3 stop
# The exception type of an engine_error that is a V3 run, completed (status None) or liquidated,
# whose own accounting does not reconcile.
V3_ACCOUNTING = "V3Accounting"
# V3's own reconciliation flags (``BaselineEvidence``), in the order a failure names them.
ACCOUNTING_FLAGS = ("accounting_explained", "wallet_quantity_exact")
V3_CAPITAL = 10000  # V3's own starting capital: a cell at any other runs through the adapter
# V3.1's disclosure of that adapter (``replay_v3_baseline``), in the outcome record's list and so
# in a full summary's ``disclosures``, exactly when the cell's capital is not V3's own.
V3_CAPITAL_ADAPTER = "v3_capital_adapter_sets_only_starting_capital"
TERMINAL = "terminal"  # the event type of V3's terminal mark
# V3.1's registered adapter pin of the selector (config/v3_1_registration.json, adapter_pins):
# the comparison report V3.1's runner builds names it; this module reads only the native marks.
V3_ADAPTER_PIN = "b984d8391c97ec8d13185269f10a8e0ddd20ab1d80c4e29e389e404ef40858f8"
LIQUIDATION = "liquidation"  # V3's one native stop

_RESERVED_MS = 1735689600000  # 2025-01-01 00:00 UTC: no pick at or after it
_MAX_PICKS_BYTES = 1 << 20
_HEX64 = re.compile("[0-9a-f]{64}")
_STAMP = re.compile("0|[1-9][0-9]*")
_DATA_KEYS = frozenset({"v3_pack_sha256", "picks_sha256"})
_HOUR_KEYS = frozenset({"open_ms", "open_equity", "complete"})
_TERMINAL_KEYS = frozenset({"type", "hour_ms", "coin", "timestamp_ms", "equity"})
_FULL = frozenset({OUTCOME_COMPLETE, LIQUIDATED})
_ERROR_KEYS = frozenset({"type", "message", "hour_ms"})  # an engine error's, never a full outcome's
_NOTE = (
    "V3 as built: V3's walk-forward selector, unchanged, on its own coins and inputs, from its "
    "first out-of-sample quarter to its terminal mark at 2025-01-01 00:00 UTC. The verdict "
    "compares it with V4 over their common period."
)


def v3_window() -> dict[str, int]:
    """The window of every v3 cell: the opens of its first and its last hour."""
    return {"start_ms": V3_START_MS, "end_ms": V3_END_MS - HOUR_MS}


def v3_coins(inputs: V3Inputs) -> tuple[str, ...]:
    """V3's coins, read from its pack: the symbols of its futures hourly bars, in name order."""
    return tuple(sorted(inputs.hourly))


def _require_pin(name: str, value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 lowercase hex digits")
    return value


def _require_cell(cell: object) -> CellSpec:
    if not isinstance(cell, CellSpec):
        raise ValueError(f"a CellSpec is required, got {cell!r:.60}")
    if ARMS[cell.arm].family != "v3":
        raise ValueError(f"{cell.cell_id} is not a cell of {V3_ARM}")
    return cell


# ---- the picks ------------------------------------------------------------------------------


def _ignore(attempt: Attempt) -> None:
    """The training's attempts are not kept: the picks file is the run's evidence (the brief)."""


def _picks_bytes(picks: Mapping[int, str | None]) -> bytes:
    for stamp, rule in picks.items():
        if type(stamp) is not int or not 0 <= stamp < _RESERVED_MS:
            raise ValueError("V3 picks: pick times in ms before 2025-01-01 required")
        if rule is not None and rule not in RULES:
            raise ValueError("V3 picks: frozen V3 rules or null required")
    if not picks:
        raise ValueError("V3 picks: one or more picks required")
    return _canonical({"picks": {str(stamp): rule for stamp, rule in sorted(picks.items())}})


def run_v3_picks(pack_path: Path, pack_sha256: str, out: Path) -> str:
    """Train V3's selector once on the pack (``selector_picks``: 10,000 USDT, size multiple 2,
    base cost) and write ``out/v3_picks.json`` (module docstring); return its SHA-256. An
    existing picks file, or a pack that is not ``pack_sha256``, is a ValueError, and nothing is
    written."""
    _require_pin("the V3 pack's sha256", pack_sha256)
    target = Path(out) / PICKS_FILE
    if target.exists():
        raise ValueError(f"{target} already exists; the run's picks are never replaced")
    inputs = read_v3_pack(pack_path, pack_sha256)
    picks, _ = selector_picks(inputs, record=_ignore)
    raw = _picks_bytes(picks)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(raw)
    return _digest(raw)


def read_v3_picks(path: Path, picks_sha256: str) -> dict[int, str | None]:
    """The picks of the file at ``path``, whose SHA-256 must be ``picks_sha256`` (checked before
    the file is parsed), and which must be exactly what ``run_v3_picks`` writes: canonical JSON
    with the one key ``picks``, each time in ms as a decimal string before 2025-01-01 mapped to
    a frozen rule or null, at least one."""
    _require_pin("the picks' sha256", picks_sha256)
    source = Path(path)
    if source.stat().st_size > _MAX_PICKS_BYTES:
        raise ValueError(f"{source.name}: a picks file of at most {_MAX_PICKS_BYTES} bytes")
    raw = source.read_bytes()
    if _digest(raw) != picks_sha256:
        raise ValueError(f"{source.name} is not the pinned picks (SHA-256 differs)")
    document = _loads(raw)
    if not isinstance(document, dict) or set(document) != {"picks"}:
        raise ValueError("V3 picks: an object with the one key picks required")
    given = document["picks"]
    if not isinstance(given, dict):
        raise ValueError("V3 picks: an object of picks required")
    picks: dict[int, str | None] = {}
    for stamp, rule in given.items():
        if _STAMP.fullmatch(stamp) is None:
            raise ValueError(f"V3 picks: {stamp!r:.40} is not a time in ms")
        picks[int(stamp)] = rule
    if _picks_bytes(picks) != raw:
        raise ValueError("V3 picks: not the canonical encoding run_v3_picks writes")
    return picks


# ---- a cell ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Outcome:
    """R3's outcome of a V3 replay: its record's own fields, and the terminal mark if any."""

    fields: Mapping[str, object]
    terminal: NativeMark | None


def run_v3_cell(
    pack_path: Path,
    pack_sha256: str,
    picks_path: Path,
    picks_sha256: str,
    cell: CellSpec,
    out_dir: Path,
) -> Receipt:
    """Replay the v3 cell ``cell`` into ``out_dir`` (its own folder): ``records.jsonl`` and
    ``receipt.json`` (module docstring); return the receipt. Everything is checked and the
    replay run before anything is written, and the folder's existing files are never replaced."""
    _require_cell(cell)
    data = {
        "v3_pack_sha256": _require_pin("the V3 pack's sha256", pack_sha256),
        "picks_sha256": _require_pin("the picks' sha256", picks_sha256),
    }
    folder = Path(out_dir)
    records, receipt_file = folder / RECORDS_FILE, folder / RECEIPT_FILE
    for existing in (records, receipt_file):
        if existing.exists():
            raise ValueError(f"{existing} already exists; a cell's files are never replaced")
    picks = read_v3_picks(Path(picks_path), picks_sha256)
    inputs = read_v3_pack(pack_path, pack_sha256)
    evidence = replay_v3_baseline(
        SELECTOR,
        inputs,
        start_ms=V3_START_MS,
        end_ms=V3_END_MS,
        initial=Decimal(cell.capital),
        cost_multiple=cell.cost_multiple,
        source_refs=(f"v3-pack:{pack_sha256}", f"v3-picks:{picks_sha256}"),
        adapter_pin=V3_ADAPTER_PIN,
        picks=picks,
    )
    coins = v3_coins(inputs)
    opens = [mark for mark in evidence.native if mark.kind == "open"]
    outcome = _outcome(evidence, cell, opens)
    present = {coin: frozenset(bar.open_ms for bar in inputs.hourly[coin]) for coin in coins}
    folder.mkdir(parents=True, exist_ok=True)
    with RecordWriter(records) as writer:
        for mark in opens:
            hour = mark.timestamp_ms
            complete = all(hour in present[coin] for coin in coins)
            writer.append(
                "hourly", {"open_ms": hour, "open_equity": mark.equity, "complete": complete}
            )
        if outcome.terminal is not None:
            stamp = outcome.terminal.timestamp_ms
            writer.append(
                "event",
                {
                    "type": TERMINAL,
                    "hour_ms": stamp - stamp % HOUR_MS,
                    "coin": None,
                    "timestamp_ms": stamp,
                    "equity": outcome.terminal.equity,
                },
            )
        writer.append(
            "outcome",
            {
                **outcome.fields,
                "hours": len(opens),
                "equity_2025": None,
                "final_after_close": None,
                "liquidations": evidence.liquidations,
                "accounting_residual": evidence.accounting_residual,
                "accounting_explained": evidence.accounting_explained,
                "wallet_quantity_exact": evidence.wallet_quantity_exact,
                "disclosures": list(evidence.disclosures),
                "coins": list(coins),
                "cell": cell_record(cell),
                "window": v3_window(),
                "data": data,
            },
        )
        receipt = writer.close()
    write_receipt(receipt_file, receipt)
    return receipt


def _outcome(evidence: BaselineEvidence, cell: CellSpec, opens: Sequence[NativeMark]) -> _Outcome:
    """R3's outcome of V3's status (module docstring), checked against V3's marks."""
    native = evidence.native
    status = evidence.status
    if opens and opens[0].timestamp_ms != V3_START_MS:
        raise ValueError("V3's first open mark is not the window's first hour")
    last = native[-1] if native else None
    terminal = last if last is not None and last.kind == TERMINAL else None
    if status is None:
        if terminal is None or terminal.timestamp_ms != V3_END_MS:
            raise ValueError("a complete V3 replay ends with its terminal mark at the window's end")
        if not opens or opens[-1].timestamp_ms != V3_END_MS - HOUR_MS:
            raise ValueError("a complete V3 replay marks every hour of the window")
        failed = _accounting_failure(evidence)
        if failed is not None:  # V3's reconciliation failed: incomplete, never complete
            return _accounting_outcome(failed, terminal, V3_END_MS, terminal)
        fields: dict[str, object] = {
            "outcome": OUTCOME_COMPLETE,
            "reason": None,
            "stop_ms": None,
            "final_equity": terminal.equity,
        }
        return _Outcome(fields, terminal)
    if status == LIQUIDATION:
        if last is None or terminal is not None:
            raise ValueError("a V3 liquidation ends at its own mark, with no terminal mark")
        stop_ms = last.timestamp_ms - last.timestamp_ms % HOUR_MS
        if not opens or opens[-1].timestamp_ms != stop_ms:
            raise ValueError("a V3 liquidation's hour is not its last open mark's")
        failed = _accounting_failure(evidence)
        if failed is not None:  # as for a completed run: incomplete, never liquidated
            return _accounting_outcome(failed, last, stop_ms, None)
        fields = {
            "outcome": LIQUIDATED,
            "reason": None,
            "stop_ms": stop_ms,
            "final_equity": last.equity,
        }
        return _Outcome(fields, None)
    hour_ms = None if last is None else last.timestamp_ms - last.timestamp_ms % HOUR_MS
    fields = {
        "outcome": ENGINE_ERROR,
        "reason": f"{V3_STOP}: {status}",
        "stop_ms": None,
        "final_equity": Decimal(cell.capital) if last is None else last.equity,
        "type": V3_STOP,
        "message": status,
        "hour_ms": hour_ms,
    }
    return _Outcome(fields, terminal)


def _accounting_outcome(
    failed: str, mark: NativeMark, hour_ms: int, terminal: NativeMark | None
) -> _Outcome:
    """The ``V3Accounting`` engine error of a V3 run that completed or was liquidated but whose
    flag ``failed`` is not true: its final equity is V3's last mark, at ``hour_ms``."""
    fields: dict[str, object] = {
        "outcome": ENGINE_ERROR,
        "reason": f"{V3_ACCOUNTING}: {failed}",
        "stop_ms": None,
        "final_equity": mark.equity,
        "type": V3_ACCOUNTING,
        "message": failed,
        "hour_ms": hour_ms,
    }
    return _Outcome(fields, terminal)


def _accounting_failure(evidence: BaselineEvidence) -> str | None:
    """The first of V3's reconciliation flags that is not true, or None if both are."""
    flags = (evidence.accounting_explained, evidence.wallet_quantity_exact)
    for name, flag in zip(ACCOUNTING_FLAGS, flags, strict=True):
        if flag is not True:
            return name
    return None


# ---- the summary ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _V3Records:
    """A v3 cell's records, read and checked: its open marks, its terminal mark (the time and
    the equity as spelled), and its outcome record."""

    hours: tuple[tuple[int, str, bool], ...]
    terminal: tuple[int, str] | None
    outcome: Mapping[str, object]


def build_v3_summary(cell: CellSpec, records_path: Path, receipt: Receipt) -> dict[str, object]:
    """The v3 cell's summary, from its records (read to the end against ``receipt``, which must
    be the ``receipt.json`` next to them) and the cell asked for (module docstring)."""
    _require_cell(cell)
    path = Path(records_path)
    receipt_sha256 = _receipt_sha256(path, receipt)
    records = _read(path, receipt, cell)
    name = records.outcome.get("outcome")
    if name in _FULL:
        return _full(cell, records, receipt_sha256)
    if name == ENGINE_ERROR:
        return _failure(cell, records)
    raise ValueError(f"{name!r:.40} is not an outcome of a v3 cell")


def verify_v3_summary(summary: dict[str, object], records_path: Path, receipt: Receipt) -> None:
    """Rebuild ``summary`` from the records with the summary's own cell and require equality;
    otherwise a ValueError names the first field that differs."""
    if not isinstance(summary, dict):
        raise ValueError("a summary must be a JSON object")
    expected = build_v3_summary(_summary_cell(summary), records_path, receipt)
    where = _first_difference(summary, expected, "")
    if where is not None:
        raise ValueError(f"summary field {where} does not match the cell's records")


def _read(path: Path, receipt: Receipt, cell: CellSpec) -> _V3Records:
    """The records of ``path`` to the end (so ``read_records`` checks the receipt), once they are
    the v3 cell ``cell``'s: only its kinds, in order, and an outcome record naming the cell, R3's
    window and the two pins, its first open mark the capital at the window's first hour."""
    hours: list[tuple[int, str, bool]] = []
    terminal: tuple[int, str] | None = None
    outcome: dict[str, object] | None = None
    for kind, record in read_records(path, receipt):
        if outcome is not None:
            raise ValueError(f"a {kind} record follows the outcome record")
        if kind == "hourly":
            hours.append(_hour(record, hours))
        elif kind == "event" and record.get("type") == TERMINAL and terminal is None:
            terminal = _terminal(record)
        elif kind == "outcome":
            outcome = record
        else:
            raise ValueError(f"a {kind} record is not one of a v3 cell's records")
    if outcome is None:
        raise ValueError("the records hold no outcome record")
    named = outcome.get("cell")
    if _first_difference(named, cell_record(cell), "cell") is not None:
        label = named.get("id") if isinstance(named, dict) else named
        raise ValueError(f"the records are of the cell {label!r:.60}, not {cell.cell_id}")
    if _first_difference(outcome.get("window"), v3_window(), "window") is not None:
        raise ValueError("the outcome record's window is not R3's window of a v3 cell")
    data = outcome.get("data")
    if (
        not isinstance(data, dict)
        or set(data) != _DATA_KEYS
        or not all(type(pin) is str and _HEX64.fullmatch(pin) for pin in data.values())
    ):
        raise ValueError("the outcome record's data must be the V3 pack's and the picks' pins")
    if hours:
        first_ms, first_equity, _ = hours[0]
        if first_ms != V3_START_MS:
            raise ValueError(f"the first hour, {first_ms}, is not the window's first")
        if Decimal(first_equity) != Decimal(cell.capital):
            raise ValueError(f"the first open mark is not the capital of {cell.cell_id}")
        if hours[-1][0] > V3_END_MS - HOUR_MS:
            raise ValueError(f"the hour {hours[-1][0]} is after the window's last")
    return _V3Records(tuple(hours), terminal, outcome)


def _hour(
    record: Mapping[str, object], previous: Sequence[tuple[int, str, bool]]
) -> tuple[int, str, bool]:
    """One hourly record: exactly its three fields, the hour after the previous one."""
    if set(record) != _HOUR_KEYS:
        raise ValueError(f"an hourly record of a v3 cell has exactly {sorted(_HOUR_KEYS)}")
    open_ms, complete = record["open_ms"], record["complete"]
    if type(open_ms) is not int or open_ms % HOUR_MS:
        raise ValueError(f"hourly record: open_ms {open_ms!r:.40} is not an hour's open")
    if previous and open_ms != previous[-1][0] + HOUR_MS:
        raise ValueError(f"hourly record at {open_ms}: not the hour after {previous[-1][0]}")
    if type(complete) is not bool:
        raise ValueError(f"hourly record at {open_ms}: complete must be a boolean")
    return (open_ms, _text(record["open_equity"], f"the open mark at {open_ms}"), complete)


def _terminal(record: Mapping[str, object]) -> tuple[int, str]:
    if set(record) != _TERMINAL_KEYS or record["coin"] is not None:
        raise ValueError(f"V3's terminal record has exactly {sorted(_TERMINAL_KEYS)}, coin null")
    stamp, hour = record["timestamp_ms"], record["hour_ms"]
    if type(stamp) is not int or type(hour) is not int or hour != stamp - stamp % HOUR_MS:
        raise ValueError("V3's terminal record needs its time and that time's hour")
    return stamp, _text(record["equity"], "V3's terminal mark")


def _full(cell: CellSpec, records: _V3Records, receipt_sha256: str) -> dict[str, object]:
    """A full summary of a complete or liquidated v3 cell (module docstring)."""
    outcome = records.outcome
    name = str(outcome["outcome"])
    reason = _optional_str(outcome.get("reason"), "the outcome's reason")
    stop_ms = _optional_int(outcome.get("stop_ms"), "the outcome's stop_ms")
    if not records.hours:
        raise ValueError(f"a {name} cell has no hourly records")
    if reason is not None:
        raise ValueError(f"a {name} v3 cell has no reason, got {reason!r:.40}")
    first_ms, last_ms = records.hours[0][0], records.hours[-1][0]
    final_text = _text(outcome.get("final_equity"), "the final equity")
    if name == OUTCOME_COMPLETE:
        if stop_ms is not None:
            raise ValueError("a complete cell has no stop")
        if last_ms != V3_END_MS - HOUR_MS:
            raise ValueError(f"a complete cell ends at the window's last hour, not {last_ms}")
        if records.terminal != (V3_END_MS, final_text):
            raise ValueError("a complete v3 cell's final equity is V3's terminal mark at its end")
        end_ms = V3_END_MS
    else:
        if stop_ms != last_ms:
            raise ValueError(f"the stop at {stop_ms} is not the last hour, {last_ms}")
        if records.terminal is not None:
            raise ValueError("a liquidated v3 cell has no terminal mark")
        end_ms = last_ms
    if outcome.get("hours") != len(records.hours):
        raise ValueError(f"the outcome record's hours is not the {len(records.hours)} open marks")
    if outcome.get("equity_2025") is not None or outcome.get("final_after_close") is not None:
        raise ValueError("a v3 cell has no equity at 2025-01-01 00:00 and no closing trade")
    liquidations = 1 if name == LIQUIDATED else 0
    if type(outcome.get("liquidations")) is not int or outcome["liquidations"] != liquidations:
        raise ValueError(f"the outcome record's liquidations is not {liquidations}")
    for flag in ACCOUNTING_FLAGS:  # else it is a V3Accounting engine error, never a full summary
        if outcome.get(flag) is not True:
            raise ValueError(f"a {name} v3 cell needs {flag} true; else it is a {V3_ACCOUNTING}")
    error_keys = sorted(_ERROR_KEYS & set(outcome))
    if error_keys:
        raise ValueError(f"a {name} outcome record has no {', '.join(error_keys)}")
    residual = _text(outcome.get("accounting_residual"), "the accounting residual")
    disclosures = _disclosures(outcome.get("disclosures"), cell)
    by_ms = {ms: equity for ms, equity, _ in records.hours}
    ending = _Ending(first_ms, last_ms, by_ms, final_text, end_ms)
    initial = Decimal(cell.capital)
    final = Decimal(final_text)
    with localcontext(CONTEXT):
        compounded = final / initial - 1
    drawdown = maximum_drawdown([Decimal(equity) for _, equity, _ in records.hours] + [final])
    years = range(_year_of(first_ms), _year_of(last_ms) + 1)
    return {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_record(cell),
        "window": v3_window(),
        "data": dict(_mapping(outcome["data"])),
        "outcome": name,
        "reason": None,
        "stop_ms": stop_ms,
        "initial_equity": str(initial),
        "final_equity": final_text,
        "equity_2025": None,
        "final_after_close": None,
        "max_drawdown": str(drawdown),
        "compounded_return": str(compounded),
        "liquidations": liquidations,
        "accounting_residual": str(Decimal(residual).copy_abs()),
        "disclosures": disclosures,
        "receipt_sha256": receipt_sha256,
        "eras": [{"name": era, **ending.period(start, end)} for era, start, end in ERAS],
        "years": [
            {"year": number, **ending.period(_year_start(number), _year_start(number + 1))}
            for number in years
        ],
        "open_marks": [[ms, equity, flag] for ms, equity, flag in records.hours],
    }


def _disclosures(value: object, cell: CellSpec) -> list[str]:
    """The outcome record's disclosures, V3's own list: nonempty strings, and the capital
    adapter's among them exactly when the cell's capital is not V3's, so a 1,000 USDT cell is
    never summarised without its disclosure, nor a 10,000 cell with one."""
    if not isinstance(value, list) or not all(type(item) is str and item for item in value):
        raise ValueError("the outcome record's disclosures must be a list of nonempty strings")
    if (V3_CAPITAL_ADAPTER in value) != (cell.capital != V3_CAPITAL):
        raise ValueError(
            f"the outcome record's disclosures must hold {V3_CAPITAL_ADAPTER} exactly for a "
            f"capital other than {V3_CAPITAL}, not for {cell.cell_id}"
        )
    return list(value)


def _failure(cell: CellSpec, records: _V3Records) -> dict[str, object]:
    """The short failure summary of a V3 stop that is not a liquidation, or of V3's failed
    reconciliation (module docstring)."""
    outcome = records.outcome
    kind, message = outcome.get("type"), outcome.get("message")
    if kind not in (V3_STOP, V3_ACCOUNTING) or type(message) is not str:
        raise ValueError(f"an engine error of a v3 cell is a {V3_STOP} or a {V3_ACCOUNTING}")
    if outcome.get("reason") != f"{kind}: {message}" or outcome.get("stop_ms") is not None:
        raise ValueError("the engine error's reason is not its type and message, or it has a stop")
    hour_ms = _optional_int(outcome.get("hour_ms"), "the engine error's hour_ms")
    if (hour_ms is None) != (not records.hours):
        raise ValueError("the engine error's hour is null exactly when V3 marked no hour")
    if kind == V3_ACCOUNTING:
        failed = next((flag for flag in ACCOUNTING_FLAGS if outcome.get(flag) is not True), None)
        if message != failed:
            raise ValueError(f"a {V3_ACCOUNTING} names the first flag the outcome shows not true")
        if not records.hours:
            raise ValueError(f"a {V3_ACCOUNTING} is a V3 run that marked its hours")
        last_ms = records.hours[-1][0]
        if records.terminal is not None:  # a completed run's
            if last_ms != V3_END_MS - HOUR_MS or records.terminal[0] != V3_END_MS:
                raise ValueError(f"a completed {V3_ACCOUNTING} run marked its window and its end")
            if hour_ms != V3_END_MS:
                raise ValueError(f"a completed {V3_ACCOUNTING}'s hour is its terminal mark's")
            liquidations = 0
        else:  # a liquidation's
            if hour_ms != last_ms:
                raise ValueError(
                    f"a {V3_ACCOUNTING} without a terminal mark is a liquidation's, at its hour"
                )
            liquidations = 1
        if type(outcome.get("liquidations")) is not int or outcome["liquidations"] != liquidations:
            raise ValueError(f"this {V3_ACCOUNTING}'s liquidations is not {liquidations}")
    return {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_record(cell),
        "window": v3_window(),
        "data": dict(_mapping(outcome["data"])),
        "outcome": ENGINE_ERROR,
        "type": kind,
        "message": message,
        "hour_ms": hour_ms,
    }


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError("a JSON object is required")
    return value


# ---- the files and the page -----------------------------------------------------------------


def write_v3_outputs(out_dir: Path, summary: dict[str, object], page: str) -> str:
    """Create ``summary.json`` (canonical JSON) and ``report.html`` in ``out_dir``, both
    exclusively, as ``summary.write_cell_outputs`` does for V4's format; return the SHA-256 of
    the summary's bytes."""
    if not isinstance(summary, dict) or summary.get("format") != V3_SUMMARY_FORMAT:
        raise ValueError(f"a {V3_SUMMARY_FORMAT} summary is required")
    if type(page) is not str:
        raise ValueError("the page must be a string")
    raw = _canonical(summary)
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    targets = (folder / SUMMARY_FILE, folder / PAGE_FILE)
    for target in targets:
        if target.exists():
            raise ValueError(f"{target} already exists; a cell's files are never replaced")
    for target, data in zip(targets, (raw, page.encode("utf-8")), strict=True):
        with target.open("xb") as handle:
            handle.write(data)
    return _digest(raw)


def render_v3_page(summary: Mapping[str, object]) -> str:
    """The v3 cell's page (ruling F2): self-contained HTML with no script, every text value
    escaped by ``summary.py``'s rules."""
    if not isinstance(summary, Mapping) or summary.get("format") != V3_SUMMARY_FORMAT:
        raise ValueError(f"a {V3_SUMMARY_FORMAT} summary is required")
    outcome = summary.get("outcome")
    cell = summary.get("cell")
    ident = cell.get("id") if isinstance(cell, Mapping) else None
    body = [f"<h1>V4 cell {_e(ident)}</h1>", f"<p>{_outcome_line(summary)}</p>"]
    body.append(f'<p class="note">{_e(_NOTE)}</p>')
    if outcome == ENGINE_ERROR:
        body += _failure_sections(summary)
    elif outcome in _FULL:
        body += _full_sections(summary)
    else:
        raise ValueError(f"{outcome!r:.40} is not an outcome of a v3 cell")
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta http-equiv="Content-Security-Policy" '
            "content=\"default-src 'none'; style-src 'unsafe-inline'\">",
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>V4 cell {_e(ident)}</title>",
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
            "",
        ]
    )


def _outcome_line(summary: Mapping[str, object]) -> str:
    outcome = summary.get("outcome")
    line = f"Outcome: <strong>{_e(outcome)}</strong>"
    if outcome == OUTCOME_COMPLETE:
        return line + (
            ". V3 ran to its window's end; the final equity is V3's terminal mark at "
            "2025-01-01 00:00 UTC, with no closing trade."
        )
    if outcome == LIQUIDATED:
        return line + (
            f" at {_e(_when(summary.get('stop_ms')))}. The figures run to the stop, and the "
            "stop's mark is the final equity."
        )
    if summary.get("type") == V3_ACCOUNTING:
        # A completed run's hour is its terminal mark's, V3's window end; a liquidation's is the
        # hour of its own mark, before it (``_failure``).
        flag = _e(summary.get("message"))
        if summary.get("hour_ms") == V3_END_MS:
            return line + (
                ": V3 ran to its window's end, but its own accounting did not reconcile "
                f"({flag}). The cell has no figures."
            )
        return line + (
            f": V3 was liquidated, and its own accounting did not reconcile ({flag}). "
            "The cell has no figures."
        )
    return line + ": V3 stopped before its window's end. The cell has no figures."


def _full_sections(summary: Mapping[str, object]) -> list[str]:
    raw_marks = summary.get("open_marks")
    marks = raw_marks if isinstance(raw_marks, list) else []
    complete = sum(1 for row in marks if isinstance(row, list) and len(row) == 3 and row[2] is True)
    stopped = summary.get("outcome") != OUTCOME_COMPLETE
    window = summary.get("window")
    first, last = (
        (window.get("start_ms"), window.get("end_ms"))
        if isinstance(window, Mapping)
        else (None, None)
    )
    data = summary.get("data")
    pins = data if isinstance(data, Mapping) else {}
    headline = [
        ("Window (first and last hour)", f"{_when(first)} to {_when(last)}"),
        ("Initial equity", _usdt(summary.get("initial_equity"))),
        (
            "Final equity" + (" (the stop's mark)" if stopped else " (V3's terminal mark)"),
            _usdt(summary.get("final_equity")),
        ),
        ("Compounded return", _percent(summary.get("compounded_return"), signed=True)),
        ("Maximum drawdown", _percent(summary.get("max_drawdown"), signed=False)),
        ("Hours with an open mark", f"{len(marks):,}"),
        ("Of which complete (every V3 coin had its bar)", f"{complete:,}"),
        ("Liquidations", _plain(summary.get("liquidations"))),
        ("Accounting residual (V3's, absolute)", _plain(summary.get("accounting_residual"))),
        ("V3 pack SHA-256", _plain(pins.get("v3_pack_sha256"))),
        ("Picks SHA-256", _plain(pins.get("picks_sha256"))),
        ("Receipt SHA-256", _plain(summary.get("receipt_sha256"))),
    ]
    sections = [
        "<h2>Headline</h2>",
        _table(("Figure", "Value"), headline),
        '<p class="muted">Rounded for reading; summary.json holds the exact values.</p>',
        "<h2>Equity path</h2>",
        _sparkline(summary, marks),
    ]
    head = ("From", "To", "Start equity", "End equity", "Return")
    for title, key, label in (("Eras", "eras", "name"), ("Years", "years", "year")):
        periods = summary.get(key)
        rows = [_period_row(item, label) for item in (periods if isinstance(periods, list) else [])]
        sections += [f"<h2>{title}</h2>", _table((title[:-1], *head), rows)]
    notes = summary.get("disclosures")
    if isinstance(notes, list) and notes:
        sections += ["<h2>Disclosures</h2>", _table(("Disclosure",), [(_plain(n),) for n in notes])]
    return sections
