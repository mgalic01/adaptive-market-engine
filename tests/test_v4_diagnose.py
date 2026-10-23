"""V4 diagnostic run, task 3: the diagnosis (``scripts/v4_diagnose.py``) on synthetic worlds.

The module's world (``diag_world``) runs two cells through ``scripts/v4_cell.py``, ``v4_main`` and
``hold_universe``, in well under a minute (owner rule: no heavy work on the owner's PC). The
window is four months, 2023-11 to 2024-02, so it crosses a year end; daily history from 2023-07
feeds the signals. The cells land as the cells workflow downloads them, in
``cells/v4-cell-<cell id>/``, and the ``v4_main`` one carries a ``timing.json``. Four coins:

* BTCUSDT (with its perpetual) falls until 2023-12-15 and then rises: a short, closed by the
  signal, then a long, censored at the window end; funding is charged on the short;
* ETHUSDT (spot only) rises; its spot hours 01:00 and 02:00 of 2023-11-10 and 2024-01-10 are
  masked, so the orders of those days' decisions are deferred to 03:00;
* SOLUSDT (with its perpetual) zigzags in 18-day legs, so its speeds flip and it opens and closes
  lifecycles on both sides; it leaves the universe in February (a universe exit);
* LUNAUSDT (spot only) stops trading on 2024-01-20, so a dead-market close sells it 168 hours
  later (a synthetic close, exit reason ``delisting``).

Every expected figure of these cells is rebuilt here from the records, read with
``read_records``, and from the verified ``summary.json``. Records written by hand through
``RecordWriter`` cover what the world does not: a stopped cell's last periods, known answers for
every figure (a win is a net, not a gross, gain), and a long file for the memory bound. The
market-regime test builds its own small BTC-only worlds (a steady uptrend and a sawtooth). The
network is blocked for every test, and only synthetic worlds in pytest's temporary folders are
read (none reaches 2025 except the one the guard must refuse).
"""

from __future__ import annotations

import contextlib
import gc
import io
import json
import re
import shutil
import socket
import sys
import tracemalloc
import weakref
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from v4_synthetic import (
    DAY,
    HOUR,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    day_hours,
    every_month,
    hours_in,
    month_start,
    path,
    write_world,
)

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine import hold, run
from crypto_grid_bot.v4.engine.arms import CellSpec
from crypto_grid_bot.v4.engine.ledger import Audit
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal
from crypto_grid_bot.v4.engine.records import (
    Receipt,
    RecordWriter,
    read_receipt,
    read_records,
    write_receipt,
)
from crypto_grid_bot.v4.engine.signals import long_fraction
from crypto_grid_bot.v4.engine.summary import SUMMARY_FILE, build_summary

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cell  # noqa: E402
import v4_diagnose  # noqa: E402

D = Decimal
F = Fraction
Rows = list[tuple[str, dict[str, Any]]]

CAPITAL = 10000
COSTS = 1
ARMS_RUN = ("v4_main", "hold_universe")
PERIOD_KEYS = ("start_ms", "end_ms", "start_equity", "end_equity", "return")
SPEEDS = ("fast", "medium", "slow")

HISTORY, FIRST, LAST = "2023-07", "2023-11", "2024-02"
START = month_start(HISTORY)
WINDOW_START = month_start(FIRST)
HOURS = hours_in(HISTORY, LAST)
WINDOW_HOURS = hours_in(FIRST, LAST)
LAST_HOUR = WINDOW_START + (WINDOW_HOURS - 1) * HOUR
TURN = month_start("2023-12") + 14 * DAY  # BTCUSDT turns from falling to rising
DEAD = month_start("2024-01") + 19 * DAY  # LUNAUSDT's last bar opens at 23:00 on 2024-01-19
MASKED_DAYS = (month_start("2023-11") + 9 * DAY, month_start("2024-01") + 9 * DAY)

LIFECYCLE_SUMS = ("gross_pnl", "fees", "funding", "given_back")


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


_SOCKET_CALLS = [
    (socket, "getaddrinfo"),
    (socket, "create_connection"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
]


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in _SOCKET_CALLS:
        monkeypatch.setattr(owner, name, _refuse)


# ---- the worlds ---------------------------------------------------------------------------


def diag_world() -> World:
    """The module's world (module docstring)."""
    btc = CoinSpec(
        "BTCUSDT",
        Series(
            START,
            path(
                "30000",
                ((TURN - START) // HOUR, "-0.0003"),
                (HOURS - (TURN - START) // HOUR, "0.0005"),
                noise="0.002",
                seed=1,
            ),
        ),
        perpetual=PerpetualSpec(),
    )
    masked = tuple(hour for day in MASKED_DAYS for hour in day_hours(day, (1, 2)))
    eth = CoinSpec(
        "ETHUSDT",
        Series(START, path("2000", (HOURS, "0.0002"), noise="0.003", seed=2), masked=masked),
    )
    legs: list[tuple[int, str]] = []
    left, rate = HOURS, "-0.0012"
    while left > 0:
        legs.append((min(left, 18 * 24), rate))
        left -= 18 * 24
        rate = "0.0012" if rate.startswith("-") else "-0.0012"
    sol = CoinSpec(
        "SOLUSDT",
        Series(START, path("20", *legs, noise="0.004", seed=3)),
        perpetual=PerpetualSpec(months={"2024-01": "missing_slot"}),
    )
    luna = CoinSpec(
        "LUNAUSDT",
        Series(START, path("5", ((DEAD - START) // HOUR, "0.0005"), noise="0.008", seed=4)),
    )
    everyone = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LUNAUSDT")
    universes = {
        "2023-11": everyone,
        "2023-12": everyone,
        "2024-01": everyone,
        "2024-02": ("BTCUSDT", "ETHUSDT"),
    }
    return World(LAST, (btc, eth, sol, luna), universes)


def btc_world(closes: Sequence[Decimal], first: str, last: str, universe_from: str) -> World:
    """BTCUSDT alone (spot only), hourly ``closes`` from the start of ``first``, in the universe
    from ``universe_from`` to ``last``: the window, so the regime's months, are those months."""
    btc = CoinSpec("BTCUSDT", Series(month_start(first), tuple(closes)))
    return World(last, (btc,), every_month(universe_from, last, ("BTCUSDT",)))


def tiny_2025_world() -> World:
    """BTCUSDT flat at 100 in 2025-01: a data run that reaches the reserved window."""
    hours = hours_in("2025-01", "2025-01")
    btc = CoinSpec("BTCUSDT", Series(month_start("2025-01"), ("100",) * hours))
    return World("2025-01", (btc,), every_month("2025-01", "2025-01", ("BTCUSDT",)))


# ---- running the scripts ------------------------------------------------------------------


def run_main(module: Any, argv: Sequence[str]) -> tuple[int, str, str]:
    """``module.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def diagnose_argv(data: Path, cells: Path, out: Path) -> list[str]:
    return ["--data", str(data), "--cells", str(cells), "--out", str(out)]


def cell_folder(cells: Path, arm: str) -> Path:
    return cells / f"v4-cell-{CellSpec(arm, CAPITAL, COSTS).cell_id}"


def write_timing(folder: Path, cell_id: str) -> dict[str, Any]:
    """A ``timing.json`` as ``scripts/v4_cells_timing.py`` writes it."""
    document = {
        "cell": cell_id,
        "wall_seconds": 5025.37,
        "peak_rss_mb": 2103.8,
        "records_bytes": (folder / run.RECORDS_FILE).stat().st_size,
    }
    (folder / "timing.json").write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii"
    )
    return document


@pytest.fixture(scope="module")
def world_dir(tmp_path_factory) -> Path:
    return write_world(tmp_path_factory.mktemp("diag-world"), diag_world())


@pytest.fixture(scope="module")
def cells_dir(world_dir, tmp_path_factory) -> Path:
    """Each arm of ``ARMS_RUN`` through ``v4_cell.py``, moved to ``cells/v4-cell-<id>/`` as the
    workflow downloads it; ``v4_main``'s folder gets a ``timing.json``, and a stray folder with
    no ``summary.json`` sits beside them."""
    root = tmp_path_factory.mktemp("diag-cells")
    cells = root / "cells"
    cells.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        # The autouse block is per test; this module-wide run blocks the network itself.
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        for arm in ARMS_RUN:
            argv = ["run", "--data", str(world_dir), "--arm", arm, "--capital", str(CAPITAL)]
            argv += ["--costs", str(COSTS), "--out", str(root / "replays")]
            code, _, stderr = run_main(v4_cell, argv)
            assert (code, stderr) == (0, ""), arm
            spec = CellSpec(arm, CAPITAL, COSTS)
            (root / "replays" / spec.cell_id).rename(cell_folder(cells, arm))
    write_timing(cell_folder(cells, "v4_main"), CellSpec("v4_main", CAPITAL, COSTS).cell_id)
    (cells / "stray").mkdir()
    return cells


@dataclass
class Diagnosis:
    code: int
    stdout: str
    stderr: str
    out: Path
    document: dict[str, Any]
    markdown: str


@pytest.fixture(scope="module")
def diagnosis(world_dir, cells_dir, tmp_path_factory) -> Diagnosis:
    """The diagnosis of the module's cells, run once."""
    out = tmp_path_factory.mktemp("diag-out") / "diagnosis"
    with pytest.MonkeyPatch.context() as patch:
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        code, stdout, stderr = run_main(v4_diagnose, diagnose_argv(world_dir, cells_dir, out))
    document = json.loads((out / "diagnosis.json").read_text(encoding="ascii"))
    markdown = (out / "diagnosis.md").read_text(encoding="utf-8")
    return Diagnosis(code, stdout, stderr, out, document, markdown)


@pytest.fixture(scope="module")
def records(cells_dir) -> dict[str, Rows]:
    """Each cell's records, read and verified to the end, by arm."""
    rows: dict[str, Rows] = {}
    for arm in ARMS_RUN:
        folder = cell_folder(cells_dir, arm)
        receipt = read_receipt(folder / run.RECEIPT_FILE)
        rows[arm] = list(read_records(folder / run.RECORDS_FILE, receipt))
    return rows


def summary_of(cells: Path, arm: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((cell_folder(cells, arm) / SUMMARY_FILE).read_bytes())
    return document


def entry_of(diagnosis: Diagnosis, arm: str) -> dict[str, Any]:
    (found,) = [
        cell
        for cell in diagnosis.document["cells"]
        if cell["cell"]["id"] == CellSpec(arm, CAPITAL, COSTS).cell_id
    ]
    return found


def of_kind(rows: Rows, kind: str) -> list[dict[str, Any]]:
    return [record for name, record in rows if name == kind]


def month_of(ms: int) -> str:
    return v4_diagnose.month_of(ms)


def year_of(ms: int) -> int:
    return int(month_of(ms)[:4])


def exact(value: Fraction) -> str:
    """The exact Decimal string of a terminating Fraction, as the diagnosis writes it."""
    return str(to_decimal(value))


def share(count: int, total: int) -> str | None:
    if total == 0:
        return None
    with localcontext(CONTEXT):
        return str(D(count) / D(total))


# ---- Review Focus 3: the periods are the summary's ----------------------------------------


def months_between(first: str, last: str) -> list[str]:
    months, month = [], first
    while month <= last:
        months.append(month)
        year, number = int(month[:4]), int(month[5:])
        month = f"{year + number // 12:04d}-{number % 12 + 1:02d}"
    return months


def expected_period(summary: Mapping[str, Any], start: int, end: int) -> dict[str, Any]:
    """One period rebuilt from the summary's own open marks (summary.py's docstring), with its
    largest drawdown: ``maximum_drawdown`` over the marks inside it, then its end equity."""
    marks = {ms: equity for ms, equity, _ in summary["open_marks"]}
    first = max(start, summary["window"]["start_ms"])
    if end in marks:
        end_ms, end_equity = end, marks[end]
    else:
        stop = summary["stop_ms"]
        end_ms = summary["window"]["end_ms"] + HOUR if stop is None else stop
        end_equity = summary["final_equity"]
    inside = [D(marks[ms]) for ms in sorted(marks) if first <= ms < end]
    with localcontext(CONTEXT):
        change = str(D(end_equity) / D(marks[first]) - 1)
    return {
        "start_ms": first,
        "end_ms": end_ms,
        "start_equity": marks[first],
        "end_equity": end_equity,
        "return": change,
        "max_drawdown": str(maximum_drawdown([*inside, D(end_equity)])),
    }


def test_year_returns_equal_the_summary(diagnosis, cells_dir):
    """Review Focus 3: each cell's years are the summary's years exactly (start and end open
    marks, the hours they stand for, and the return), and each month is summary.py's period
    rule applied to the month: it starts at the open mark of its first hour, ends at the open
    mark that starts the next month (the final equity at the window's end for the last), and
    its drawdown is ``maximum_drawdown`` over its marks and then its end equity. The months
    chain without a gap and tile each year."""
    assert diagnosis.code == 0, diagnosis.stderr
    for arm in ARMS_RUN:
        entry = entry_of(diagnosis, arm)
        summary = summary_of(cells_dir, arm)
        assert entry["outcome"] == summary["outcome"] == "complete"
        assert [{k: year[k] for k in ("year", *PERIOD_KEYS)} for year in entry["years"]] == (
            summary["years"]
        )
        assert [year["year"] for year in entry["years"]] == [2023, 2024]
        months = [month["month"] for month in entry["months"]]
        assert months == months_between(FIRST, LAST)
        for month in entry["months"]:
            start, end = month_bounds_ms(month["month"])
            expected = expected_period(summary, start, end)
            assert {key: month[key] for key in expected} == expected, (arm, month["month"])
        for year in entry["years"]:
            start = month_bounds_ms(f"{year['year']}-01")[0]
            end = month_bounds_ms(f"{year['year'] + 1}-01")[0]
            expected = expected_period(summary, start, end)
            assert year["max_drawdown"] == expected["max_drawdown"], (arm, year["year"])
            inside = [m for m in entry["months"] if m["month"].startswith(f"{year['year']}-")]
            assert inside[0]["start_equity"] == year["start_equity"]
            assert inside[-1]["end_equity"] == year["end_equity"]
        for before, after in zip(entry["months"], entry["months"][1:], strict=False):
            assert (before["end_ms"], before["end_equity"]) == (
                after["start_ms"],
                after["start_equity"],
            )
        assert entry["months"][-1]["end_equity"] == summary["final_equity"]


def fake_cell(out: Path, first_ms: int, equities: Sequence[str | None], final: str) -> Receipt:
    """A liquidated cell's records by hand, in the engine's ``hourly`` and ``outcome`` shapes:
    one hour from ``first_ms`` per entry of ``equities``, each that hour's open mark (None for
    the last hour when the stop came before its open mark), then the outcome; and its receipt."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for index, equity in enumerate(equities):
        rows.append(
            (
                "hourly",
                {
                    "open_ms": first_ms + index * HOUR,
                    "open_equity": None if equity is None else D(equity),
                    "complete": None if equity is None else True,
                    "equity": D(final if equity is None else equity),
                    "gross_notional": D(0),
                    "gross": D(0),
                    "margin_ratio": None,
                    "equity_residual": D(0),
                },
            )
        )
    last = first_ms + (len(equities) - 1) * HOUR
    rows.append(
        (
            "outcome",
            {
                "outcome": "liquidated",
                "reason": None,
                "stop_ms": last,
                "hours": sum(equity is not None for equity in equities),
                "final_equity": D(final),
                "equity_2025": None,
                "final_after_close": None,
                "audit": {
                    "wallet_residual": D(0),
                    "equity_residual": D(0),
                    "quantity_residuals": [],
                },
                "cell": run.cell_record(CellSpec("v4_main", CAPITAL, COSTS)),
                "window": {"start_ms": first_ms, "end_ms": last + 100 * HOUR},
                "data": None,
                "check": "adverse_extremes",
            },
        )
    )
    out.mkdir(parents=True)
    with RecordWriter(out / run.RECORDS_FILE) as writer:
        for kind, record in rows:
            writer.append(kind, record)
        receipt = writer.close()
    write_receipt(out / run.RECEIPT_FILE, receipt)
    return receipt


@pytest.mark.parametrize("stop_mark", [True, False], ids=["stop-after-mark", "stop-before-mark"])
def test_periods_of_a_stopped_cell_end_at_the_stop(tmp_path, stop_mark):
    """Review Focus 3 for a stop: a cell liquidated at 02:00 on 2024-01-01, with or without that
    hour's open mark, has the summary's years exactly; its last month and year end at the stop
    with the final equity, and no later period is listed."""
    first = month_start("2024-01") - 4 * HOUR
    equities: list[str | None] = ["10000", "10400", "9600", "9900", "9000", "8100"]
    equities.append("7000" if stop_mark else None)
    receipt = fake_cell(tmp_path / "cell", first, equities, "6500")
    marks = [
        (first + index * HOUR, D(equity), True)
        for index, equity in enumerate(equities)
        if equity is not None
    ]
    result = run.CellResult(
        "liquidated",
        None,
        first + 6 * HOUR,
        tuple(marks),
        D("6500"),
        None,
        None,
        Audit(D(0), {}, D(0)),
        receipt,
    )
    spec = CellSpec("v4_main", CAPITAL, COSTS)
    summary = build_summary(spec, result, tmp_path / "cell" / run.RECORDS_FILE)
    figures = v4_diagnose.cell_figures(tmp_path / "cell" / run.RECORDS_FILE, receipt)
    assert [{k: y[k] for k in ("year", *PERIOD_KEYS)} for y in figures["years"]] == (
        summary["years"]
    )
    assert [month["month"] for month in figures["months"]] == ["2023-12", "2024-01"]
    january = figures["months"][1]
    assert (january["end_ms"], january["end_equity"]) == (first + 6 * HOUR, "6500")
    path_of_january = [D(9000), D(8100), *([D(7000)] if stop_mark else []), D(6500)]
    assert january["max_drawdown"] == str(maximum_drawdown(path_of_january))
    december = figures["months"][0]
    assert december["max_drawdown"] == str(
        maximum_drawdown([D(e) for e in ("10000", "10400", "9600", "9900", "9000")])
    )


def reading(fast: int | None, medium: int | None, slow: int | None, *, confirmed: bool) -> dict:
    """The reading fields of a ``daily_coin`` record that the diagnosis reads."""
    return {
        "reading_day_ms": 0,
        "speeds": {
            name: {"vote": vote} for name, vote in zip(SPEEDS, (fast, medium, slow), strict=True)
        },
        "downtrend": {"confirmed": confirmed},
        "L": long_fraction(fast, medium, slow),
        "S": D("0.5") if confirmed and medium == -1 else D(0),
    }


def known_records(out: Path) -> Receipt:
    """A complete cell by hand over four hours, 2024-01-31 22:00 to 2024-02-01 01:00, with
    records of each kind the diagnosis counts, in January or in February."""
    jan, feb = month_start("2024-02") - 2 * HOUR, month_start("2024-02")
    rows: list[tuple[str, dict[str, Any]]] = []

    def add(kind: str, **record: Any) -> None:
        rows.append((kind, record))

    def daily(decision: int, coin: str, target: str | None, fields: dict | None) -> None:
        empty = dict.fromkeys(("reading_day_ms", "speeds", "downtrend", "L", "S"))
        target_value = None if target is None else D(target)
        add("daily_coin", decision_ms=decision, coin=coin, target=target_value, **(fields or empty))

    def hourly(index: int, equity: str) -> None:
        add("hourly", open_ms=jan + index * HOUR, open_equity=D(equity), complete=True)

    spot = {"coin": "AAAUSDT", "venue": "spot", "symbol": "AAAUSDT"}
    order = {"type": "order", "coin": "AAAUSDT", "source": "signal"}
    lifecycle = {"coin": "AAAUSDT", "given_back": D("1.5")}
    # January: a fill with slippage, a funding payment, a band-kept order filled three hours
    # after its decision with one refused leg, a margin cut, and two coin-days.
    daily(jan, "AAAUSDT", "0.2", reading(1, 1, None, confirmed=False))
    daily(jan, "BBBUSDT", None, None)
    fill = {"quantity": D(2), "price": D(101), "unslipped_price": D(100), "fee": D("0.2")}
    add("fill", **spot, hour_ms=jan + HOUR, side=1, **fill)
    add("funding", hour_ms=jan + HOUR, coin="AAAUSDT", amount=D("-0.5"))
    refused = [{"refusal": "min_qty"}, {"refusal": None}]
    add("event", **order, hour_ms=jan + HOUR, decision_ms=jan - 2 * HOUR, band="keep", legs=refused)
    add("event", type="margin_cut", hour_ms=jan + HOUR, coin=None)
    hourly(0, "10000")
    hourly(1, "10100")
    # February: a synthetic close of two legs (no slippage), a funding receipt, a ceiling cut, a
    # cash-clip cut, a superseded order that had waited a day (a deferral), an order cancelled
    # in its own decision hour and an order filled at its first fill hour (neither is one), the
    # two lifecycles, and two coin-days, the first a flip of the fast and medium speeds.
    daily(feb, "AAAUSDT", "-0.1", reading(-1, -1, -1, confirmed=True))
    daily(feb, "BBBUSDT", "0", reading(1, None, None, confirmed=False))
    close = {"quantity": D(2), "price": D(90), "unslipped_price": D(90), "fee": D("0.18")}
    add("fill", **spot, hour_ms=feb, side=-1, **close)
    add("funding", hour_ms=feb, coin="AAAUSDT", amount=D("0.25"))
    legs = [{"reason": "delisting"}, {"reason": "funding-month exit"}]
    add("event", type="synthetic_closes", hour_ms=feb, coin=None, legs=legs)
    add("event", type="ceiling_cut", hour_ms=feb, coin=None)
    add("event", type="increase_cut", hour_ms=feb, coin="AAAUSDT")
    add("event", type="order_superseded", hour_ms=feb, coin="BBBUSDT", decision_ms=feb - DAY)
    add("event", type="order_cancelled", hour_ms=feb, coin="BBBUSDT", decision_ms=feb)
    add("event", **order, hour_ms=feb + HOUR, decision_ms=feb, band="trade", legs=[])
    long_trade = {"gross_pnl": D(5), "fees": D(6), "funding": D(0), "exit_reason": "signal"}
    add("lifecycle", **lifecycle, side="long", entry_ms=jan + HOUR, exit_ms=feb, **long_trade)
    hourly(2, "9900")
    hourly(3, "10200")
    short_trade = {"gross_pnl": D(-1), "fees": D("0.5"), "funding": D(3)}
    short_trade["exit_reason"] = "window end"
    add("lifecycle", **lifecycle, side="short", entry_ms=feb, exit_ms=feb + HOUR, **short_trade)
    add("outcome", outcome="complete", final_equity=D(10300))
    out.mkdir(parents=True)
    with RecordWriter(out / run.RECORDS_FILE) as writer:
        for kind, record in rows:
            writer.append(kind, record)
        return writer.close()


def test_the_figures_of_a_known_cell(tmp_path):
    """Known answers, by hand: a long lifecycle (gross 5, fees 6: a net loss, so no win) and a
    short one (gross -1, funding 3: a net win), costs and events on both sides of a month end,
    and four coin-days of signals, one coin flipping its fast and medium speeds."""
    receipt = known_records(tmp_path / "cell")
    figures = v4_diagnose.cell_figures(tmp_path / "cell" / run.RECORDS_FILE, receipt)
    assert figures["record_count"] == receipt.record_count
    january, february = figures["months"]
    (year,) = figures["years"]
    with localcontext(CONTEXT):
        worst = str(D(200) / D(10100))
        assert (january["return"], january["max_drawdown"]) == (str(D(9900) / 10000 - 1), worst)
        assert (february["return"], february["max_drawdown"]) == (str(D(10300) / 9900 - 1), "0")
        assert (year["return"], year["max_drawdown"]) == (str(D(10300) / 10000 - 1), worst)
    assert january["lifecycles"] == {
        **dict.fromkeys(("opened_short", "closed_long", "closed_short", "wins"), 0),
        "opened_long": 1,
        "win_rate": None,
        **dict.fromkeys(
            ("gross_pnl", "gross_profit", "gross_loss", "fees", "funding", "net_pnl"), "0"
        ),
        "given_back": "0",
    }
    assert february["lifecycles"] == {
        "opened_long": 0,
        "opened_short": 1,
        "closed_long": 1,
        "closed_short": 1,
        "wins": 1,
        "win_rate": "0.5",
        "gross_pnl": "4",
        "gross_profit": "5",
        "gross_loss": "-1",
        "fees": "6.5",
        "funding": "3",
        "net_pnl": "0.5",
        "given_back": "3",
    }
    assert january["costs"] == {
        "fills": 1,
        "traded_notional": "202",
        "fees": "0.2",
        "slippage": "2",
        "funding_records": 1,
        "funding": "-0.5",
    }
    assert february["costs"] == {
        "fills": 1,
        "traded_notional": "180",
        "fees": "0.18",
        "slippage": "0",
        "funding_records": 1,
        "funding": "0.25",
    }
    nothing = dict.fromkeys(v4_diagnose.COUNT_NAMES, 0)
    assert january["counts"] == {
        **nothing,
        "margin_cuts": 1,
        "deferrals": 1,
        "refused_orders": 1,
        "band_skips": 1,
    }
    assert february["counts"] == {
        **nothing,
        "ceiling_cuts": 1,
        "dead_market_closes": 1,
        "funding_month_closes": 1,
        "cash_clip_cuts": 1,
        "deferrals": 1,
    }
    assert year["counts"] == {
        key: january["counts"][key] + february["counts"][key] for key in nothing
    }
    sides = {row["side"]: row for row in figures["sides"]}
    assert (sides["long"]["wins"], sides["long"]["net_pnl"]) == (0, "-1")
    assert (sides["short"]["wins"], sides["short"]["net_pnl"]) == (1, "1.5")
    assert [(row["exit_reason"], row["lifecycles"]) for row in figures["exit_reasons"]] == [
        ("signal", 1),
        ("window end", 1),
    ]
    assert [(row["coin"], row["lifecycles"], row["wins"]) for row in figures["coins"]] == [
        ("AAAUSDT", 2, 1)
    ]
    (signals,) = figures["signals"]
    quarter, half = share(1, 4), share(2, 4)
    assert signals == {
        "year": 2024,
        "coin_days": 4,
        "decisions": 2,
        "no_reading": quarter,
        "speeds": {
            "fast": {"up": half, "down": quarter, "warming": quarter, "flips": 1},
            "medium": {"up": quarter, "down": quarter, "warming": half, "flips": 1},
            "slow": {"up": "0", "down": quarter, "warming": share(3, 4), "flips": 0},
        },
        "confirmed_downtrend": quarter,
        "short_positive": quarter,
        "long_fraction": {"0": quarter, "1/3": quarter, "2/3": quarter, "1": "0"},
        "mean_coins_with_target": "1",
    }


# ---- the lifecycles, by period, side, exit reason and coin --------------------------------


def lifecycle_sums(lifecycles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sums = {key: sum((F(D(item[key])) for item in lifecycles), F(0)) for key in LIFECYCLE_SUMS}
    net = sum(
        (
            F(D(item["gross_pnl"])) - F(D(item["fees"])) + F(D(item["funding"]))
            for item in lifecycles
        ),
        F(0),
    )
    wins = sum(
        F(D(item["gross_pnl"])) - F(D(item["fees"])) + F(D(item["funding"])) > 0
        for item in lifecycles
    )
    return {
        "lifecycles": len(lifecycles),
        "wins": wins,
        **{key: exact(value) for key, value in sums.items()},
        "net_pnl": exact(net),
    }


def test_side_and_exit_breakdowns_add_up_to_the_lifecycles(diagnosis, records):
    """Each breakdown is the sum over the lifecycle records it covers, exactly: a lifecycle
    counts in the period and year it ends (``exit_ms``) and as opened in the period of its
    ``entry_ms``. By side, exit reason and coin, per year, the count, wins (net P&L above 0),
    gross P&L, fees, funding and net P&L; and the totals of each breakdown are the totals of
    every lifecycle record. The world has both sides and four exit reasons."""
    for arm in ARMS_RUN:
        entry = entry_of(diagnosis, arm)
        lifecycles = of_kind(records[arm], "lifecycle")
        assert lifecycles, arm
        for name, key in (("sides", "side"), ("exit_reasons", "exit_reason"), ("coins", "coin")):
            groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
            for item in lifecycles:
                groups.setdefault((year_of(item["exit_ms"]), item[key]), []).append(item)
            found = {(row["year"], row[key]): row for row in entry[name]}
            for group, items in groups.items():
                expected = lifecycle_sums(items)
                assert {k: found[group][k] for k in expected} == expected, (arm, name, group)
            # Rows with no lifecycle may be listed (both sides every year); they hold zeros.
            for group, row in found.items():
                if group not in groups:
                    assert row["lifecycles"] == 0 and row["gross_pnl"] == "0", (arm, name, group)
            totals = lifecycle_sums(lifecycles)
            for field in ("lifecycles", "wins"):
                assert sum(row[field] for row in entry[name]) == totals[field]
            for field in (*LIFECYCLE_SUMS[:3], "net_pnl"):
                assert exact(sum((F(D(row[field])) for row in entry[name]), F(0))) == totals[field]
        for period, size in (("months", 7), ("years", 4)):
            for row in entry[period]:
                label = str(row["month" if period == "months" else "year"])
                closed = [item for item in lifecycles if month_of(item["exit_ms"])[:size] == label]
                opened = [item for item in lifecycles if month_of(item["entry_ms"])[:size] == label]
                sums = lifecycle_sums(closed)
                gross = [F(D(item["gross_pnl"])) for item in closed]
                expected = {
                    "opened_long": sum(item["side"] == "long" for item in opened),
                    "opened_short": sum(item["side"] == "short" for item in opened),
                    "closed_long": sum(item["side"] == "long" for item in closed),
                    "closed_short": sum(item["side"] == "short" for item in closed),
                    "wins": sums["wins"],
                    "win_rate": share(sums["wins"], len(closed)),
                    "gross_pnl": sums["gross_pnl"],
                    "gross_profit": exact(sum((g for g in gross if g > 0), F(0))),
                    "gross_loss": exact(sum((g for g in gross if g < 0), F(0))),
                    "fees": sums["fees"],
                    "funding": sums["funding"],
                    "net_pnl": sums["net_pnl"],
                    "given_back": sums["given_back"],
                }
                assert row["lifecycles"] == expected, (arm, label)
    main = of_kind(records["v4_main"], "lifecycle")
    assert {item["side"] for item in main} == {"long", "short"}
    assert {item["exit_reason"] for item in main} == {
        "signal",
        "universe exit",
        "delisting",
        "window end",
    }


# ---- costs ---------------------------------------------------------------------------------


def cost_sums(fills: Sequence[Mapping[str, Any]], funding: Sequence[Mapping[str, Any]]) -> dict:
    def total(values: Iterator[Fraction]) -> str:
        return exact(sum(values, F(0)))

    return {
        "fills": len(fills),
        "traded_notional": total(F(D(f["quantity"])) * F(D(f["price"])) for f in fills),
        "fees": total(F(D(f["fee"])) for f in fills),
        "slippage": total(
            abs(F(D(f["price"])) - F(D(f["unslipped_price"]))) * F(D(f["quantity"])) for f in fills
        ),
        "funding_records": len(funding),
        "funding": total(F(D(f["amount"])) for f in funding),
    }


def test_costs_add_up_to_the_fills_and_funding_records(diagnosis, records):
    """Each period's costs are the sums over the fill and funding records of its hours (each
    record's ``hour_ms``), exactly: fills, traded notional (quantity x price), fees, slippage
    (|price - unslipped price| x quantity) and funding (the records' signed amounts); the
    months add up to the years, and the years to every record. The V4 cell pays slippage and
    funding; a synthetic close has none of the first."""
    for arm in ARMS_RUN:
        entry = entry_of(diagnosis, arm)
        fills, funding = of_kind(records[arm], "fill"), of_kind(records[arm], "funding")
        for period, size in (("months", 7), ("years", 4)):
            for row in entry[period]:
                label = str(row["month" if period == "months" else "year"])
                expected = cost_sums(
                    [f for f in fills if month_of(f["hour_ms"])[:size] == label],
                    [f for f in funding if month_of(f["hour_ms"])[:size] == label],
                )
                assert row["costs"] == expected, (arm, label)
        everything = cost_sums(fills, funding)
        for period in ("months", "years"):
            for key in ("fills", "funding_records"):
                assert sum(row["costs"][key] for row in entry[period]) == everything[key]
            for key in ("traded_notional", "fees", "slippage", "funding"):
                assert (
                    exact(sum((F(D(row["costs"][key])) for row in entry[period]), F(0)))
                    == everything[key]
                )
    main = cost_sums(of_kind(records["v4_main"], "fill"), of_kind(records["v4_main"], "funding"))
    assert D(main["slippage"]) > 0 and main["funding_records"] > 0 and D(main["fees"]) > 0
    synthetic = [f for f in of_kind(records["v4_main"], "fill") if f["reason"] == "delisting"]
    assert synthetic and all(f["price"] == f["unslipped_price"] for f in synthetic)


def expected_counts(rows: Rows, label: str, size: int) -> dict[str, int]:
    """The event counts of one period, from the records (the diagnosis' docstring)."""
    counts: Counter[str] = Counter()
    for record in of_kind(rows, "event"):
        if month_of(record["hour_ms"])[:size] != label:
            continue
        kind = record["type"]
        if kind in ("margin_cut", "ceiling_cut"):
            counts[f"{kind}s"] += 1
        elif kind == "increase_cut":
            counts["cash_clip_cuts"] += 1
        elif kind == "synthetic_closes":
            for leg in record["legs"]:
                key = (
                    "dead_market_closes" if leg["reason"] == "delisting" else "funding_month_closes"
                )
                counts[key] += 1
        elif kind == "order":
            counts["band_skips"] += record["band"] == "keep"
            counts["refused_orders"] += sum(leg["refusal"] is not None for leg in record["legs"])
            if record["source"] in ("signal", "rebalance"):
                counts["deferrals"] += record["hour_ms"] > record["decision_ms"] + HOUR
        elif kind in ("order_superseded", "order_cancelled"):
            counts["deferrals"] += record["hour_ms"] > record["decision_ms"] + HOUR
    names = (
        "margin_cuts",
        "ceiling_cuts",
        "dead_market_closes",
        "funding_month_closes",
        "deferrals",
        "refused_orders",
        "cash_clip_cuts",
        "band_skips",
    )
    return {name: counts[name] for name in names}


def test_event_counts_match_the_records(diagnosis, records):
    """Each period's counts are its events': margin and ceiling cuts, the legs of synthetic
    closes by reason (a dead market, a funding month), deferrals (a daily order that did not
    fill in its first fill hour, counted when it fills, is superseded or is cancelled), refused
    order legs, cash-clip cuts and band skips. The world has three deferrals: ETHUSDT's orders
    of its two masked days, which fill at 03:00, and LUNAUSDT's last order, which waits 168 hours
    for a bar until its dead-market close cancels it; and that one dead-market close."""
    for arm in ARMS_RUN:
        entry = entry_of(diagnosis, arm)
        for period, size in (("months", 7), ("years", 4)):
            for row in entry[period]:
                label = str(row["month" if period == "months" else "year"])
                assert row["counts"] == expected_counts(records[arm], label, size), (arm, label)
    totals = Counter[str]()
    for row in entry_of(diagnosis, "v4_main")["years"]:
        totals.update(row["counts"])
    assert totals["deferrals"] == 3 and totals["dead_market_closes"] == 1
    assert totals["band_skips"] > 0 and totals["refused_orders"] >= 1


# ---- signals -------------------------------------------------------------------------------


def test_signal_behaviour_counts_the_daily_records(diagnosis, records):
    """Per year of the decisions: each speed's share of coin-days up, down or warming (no
    reading, warming up or an exact tie) and its flips (a vote opposite to the coin's last up
    or down vote); the shares of a confirmed downtrend, of
    S > 0 and of each L level; and the mean number of coins with a nonzero target per decision.
    A hold arm has no daily records, so its shares are null."""
    rows = of_kind(records["v4_main"], "daily_coin")
    by_year: dict[int, list[dict[str, Any]]] = {}
    for record in rows:
        by_year.setdefault(year_of(record["decision_ms"]), []).append(record)
    entry = entry_of(diagnosis, "v4_main")
    assert [row["year"] for row in entry["signals"]] == sorted(by_year) == [2023, 2024]
    last_vote: dict[tuple[str, str], int] = {}
    for row in entry["signals"]:
        days = by_year[row["year"]]
        assert row["coin_days"] == len(days)
        assert row["decisions"] == len({r["decision_ms"] for r in days})
        flips: Counter[str] = Counter()
        for record in days:
            if record["speeds"] is None:
                continue
            for speed in ("fast", "medium", "slow"):
                vote = record["speeds"][speed]["vote"]
                if vote in (1, -1):
                    flips[speed] += last_vote.get((record["coin"], speed)) == -vote
                    last_vote[record["coin"], speed] = vote
        for speed in ("fast", "medium", "slow"):
            votes = [None if r["speeds"] is None else r["speeds"][speed]["vote"] for r in days]
            assert row["speeds"][speed] == {
                "up": share(votes.count(1), len(days)),
                "down": share(votes.count(-1), len(days)),
                "warming": share(sum(vote not in (1, -1) for vote in votes), len(days)),
                "flips": flips[speed],
            }, (row["year"], speed)
        readings = [r for r in days if r["speeds"] is not None]
        assert row["no_reading"] == share(len(days) - len(readings), len(days))
        assert row["confirmed_downtrend"] == share(
            sum(r["downtrend"]["confirmed"] is True for r in readings), len(days)
        )
        assert row["short_positive"] == share(sum(D(r["S"]) > 0 for r in readings), len(days))
        with localcontext(CONTEXT):
            levels = {"0": D(0), "1/3": D(1) / 3, "2/3": D(2) / 3, "1": D(1)}
        assert row["long_fraction"] == {
            label: share(sum(D(r["L"]) == level for r in readings), len(days))
            for label, level in levels.items()
        }
        targets = sum(r["target"] is not None and D(r["target"]) != 0 for r in days)
        with localcontext(CONTEXT):
            mean = str(D(targets) / D(row["decisions"]))
        assert row["mean_coins_with_target"] == mean
    assert sum(row["speeds"]["fast"]["flips"] for row in entry["signals"]) > 0
    hold = entry_of(diagnosis, "hold_universe")
    assert [row["coin_days"] for row in hold["signals"]] == [0, 0]
    assert all(row["speeds"]["fast"]["up"] is None for row in hold["signals"])


# ---- the market regime ---------------------------------------------------------------------


def hourly_closes(daily: Sequence[Decimal]) -> list[Decimal]:
    """24 hourly closes per day, each day's last one its daily close (a straight line between
    the days' closes)."""
    closes: list[Decimal] = []
    previous = daily[0]
    with localcontext(CONTEXT):
        for close in daily:
            step = (close - previous) / 24
            closes += [(previous + step * hour).quantize(D("0.00000001")) for hour in range(1, 25)]
            previous = close
    return closes


def test_market_regime_of_a_known_path(tmp_path):
    """A steady uptrend's months are above SMA200 with a positive return, a low volatility and
    no SMA20 crossing; a sawtooth (a daily close 4% above, then 4% below, a flat level) crosses
    SMA20 nearly every day. The universe's median is BTCUSDT's own return (its only coin). And
    each month uses only bars of that month and before: a world that ends a month earlier gives
    the same figures for every month it has."""
    days = hours_in("2023-01", "2023-10") // 24
    with localcontext(CONTEXT):
        up = [D(100) * D("1.003") ** day for day in range(days)]
    world = btc_world(hourly_closes(up), "2023-01", "2023-10", "2023-09")
    regime = v4_diagnose.market_regime(Market.load(write_world(tmp_path / "up", world)))
    assert [month["month"] for month in regime] == ["2023-09", "2023-10"]
    for month in regime:
        assert month["btc_vs_sma200"] == "above"
        assert D(month["btc_close_over_sma200"]) > 0
        assert D(month["btc_return"]) > 0
        assert month["btc_sma20_crossings"] == 0
        assert D(month["btc_volatility_30d"]) < D("0.05")
        assert (month["universe_coins"], month["universe_coins_with_return"]) == (1, 1)
        assert month["universe_median_return"] == month["btc_return"]
    with localcontext(CONTEXT):
        # The month's close over the previous month's, from the daily bars.
        expected = D(up[-1]).quantize(D("0.00000001")) / D(up[-32]).quantize(D("0.00000001")) - 1
    assert regime[-1]["btc_return"] == str(expected)

    saw = [D(104) if day % 2 else D(96) for day in range(days)]
    sawtooth = btc_world(hourly_closes(saw), "2023-01", "2023-10", "2023-08")
    full = v4_diagnose.market_regime(Market.load(write_world(tmp_path / "saw", sawtooth)))
    assert [month["month"] for month in full] == ["2023-08", "2023-09", "2023-10"]
    for month in full:
        assert month["btc_sma20_crossings"] >= 25, month["month"]
        assert D(month["btc_volatility_30d"]) > 1
    cut = hours_in("2023-01", "2023-09")
    shorter = btc_world(hourly_closes(saw)[:cut], "2023-01", "2023-09", "2023-08")
    early = v4_diagnose.market_regime(Market.load(write_world(tmp_path / "saw-9", shorter)))
    assert early == full[:2]


def test_the_diagnosis_holds_the_regime_of_its_packs(diagnosis, world_dir):
    """The diagnosis' regime is ``market_regime`` of the packs it was given, one row per month
    of the window; SMA200 is null until BTCUSDT has 200 daily bars."""
    regime = v4_diagnose.market_regime(Market.load(world_dir))
    assert diagnosis.document["market_regime"] == regime
    assert [month["month"] for month in regime] == months_between(FIRST, LAST)
    assert [month["btc_vs_sma200"] for month in regime] == [None, None, "above", "above"]
    assert [month["universe_coins"] for month in regime] == [4, 4, 4, 2]


# ---- Review Focus 2: streaming --------------------------------------------------------------


class Tracked(dict):  # type: ignore[type-arg]
    """A record dict that a weak reference can follow."""


def test_diagnose_streams_the_records(diagnosis, world_dir, cells_dir, tmp_path, monkeypatch):
    """Review Focus 2, by a spy: the diagnosis' own pass over each cell's records reads them
    through ``read_records`` once, to the end (so the receipt's counts and final hash are
    checked), and holds at most the record in hand and the one before it, never the file."""
    calls: list[dict[str, int | bool]] = []
    original = v4_diagnose.read_records

    def spy(path: Path, receipt: Receipt) -> Iterator[tuple[str, dict[str, Any]]]:
        state: dict[str, int | bool] = {"yielded": 0, "alive": 0, "exhausted": False}
        calls.append(state)
        held: list[weakref.ref[Tracked]] = []
        for kind, record in original(path, receipt):
            tracked = Tracked(record)
            del record
            held.append(weakref.ref(tracked))
            yield kind, tracked
            del tracked
            state["yielded"] = int(state["yielded"]) + 1
            alive = sum(ref() is not None for ref in held)
            state["alive"] = max(int(state["alive"]), alive)
            held = [ref for ref in held if ref() is not None]
        state["exhausted"] = True

    monkeypatch.setattr(v4_diagnose, "read_records", spy)
    code, _, stderr = run_main(v4_diagnose, diagnose_argv(world_dir, cells_dir, tmp_path / "o"))
    assert (code, stderr) == (0, "")
    counts = sorted(
        read_receipt(cell_folder(cells_dir, arm) / run.RECEIPT_FILE).record_count
        for arm in ARMS_RUN
    )
    assert sorted(int(call["yielded"]) for call in calls) == counts
    assert all(call["exhausted"] is True for call in calls)
    assert max(int(call["alive"]) for call in calls) <= 1
    written = json.loads((tmp_path / "o" / "diagnosis.json").read_text(encoding="ascii"))
    assert written == diagnosis.document


def synthetic_records(out: Path, hours: int) -> Receipt:
    """A large records file by hand: ``hours`` hourly records from 2021-01-01 with a slowly
    rising open mark, then a complete outcome."""
    first = month_start("2021-01")
    with RecordWriter(out / run.RECORDS_FILE) as writer:
        for index in range(hours):
            equity = D(10000 + index) / 4
            writer.append(
                "hourly",
                {
                    "open_ms": first + index * HOUR,
                    "open_equity": equity,
                    "complete": True,
                    "equity": equity,
                    "gross_notional": D(0),
                    "gross": D(0),
                    "margin_ratio": None,
                    "equity_residual": D(0),
                },
            )
        writer.append(
            "outcome",
            {
                "outcome": "complete",
                "reason": None,
                "stop_ms": None,
                "hours": hours,
                "final_equity": D(10000 + hours) / 4,
                "cell": run.cell_record(CellSpec("v4_main", CAPITAL, COSTS)),
                "window": {"start_ms": first, "end_ms": first + (hours - 1) * HOUR},
                "data": None,
            },
        )
        receipt = writer.close()
    return receipt


def test_diagnose_streams_the_records_in_bounded_memory(tmp_path):
    """Review Focus 2, measured: the pass over a records file ten times as long (25,000 hours,
    almost three years, about 9 MB) peaks at about the same traced memory as one of 2,500 hours
    (about 0.4 MB each when this was written), and far below the file's size; a list of the
    25,000 records alone would take about 23 MB."""
    peaks: dict[int, int] = {}
    for hours in (2500, 25000):
        folder = tmp_path / str(hours)
        folder.mkdir()
        receipt = synthetic_records(folder, hours)
        gc.collect()
        tracemalloc.start()
        try:
            figures = v4_diagnose.cell_figures(folder / run.RECORDS_FILE, receipt)
            peaks[hours] = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert figures["record_count"] == hours + 1
    size = (tmp_path / "25000" / run.RECORDS_FILE).stat().st_size
    assert size > 8_000_000
    assert peaks[25000] < peaks[2500] + 300_000, peaks
    assert peaks[25000] < size // 10, (peaks, size)


# ---- refusals --------------------------------------------------------------------------------


def tamper_summary(folder: Path) -> None:
    summary = json.loads((folder / SUMMARY_FILE).read_bytes())
    summary["years"][0]["return"] = "0.5"
    (folder / SUMMARY_FILE).write_bytes(_canonical(summary))


def tamper_layout(folder: Path) -> None:
    summary = json.loads((folder / SUMMARY_FILE).read_bytes())
    (folder / SUMMARY_FILE).write_text(json.dumps(summary, indent=1), encoding="ascii")


def tamper_records(folder: Path) -> None:
    raw = bytearray((folder / run.RECORDS_FILE).read_bytes())
    raw[200] = ord("7") if raw[200] != ord("7") else ord("8")
    (folder / run.RECORDS_FILE).write_bytes(bytes(raw))


def tamper_receipt(folder: Path) -> None:
    (folder / run.RECEIPT_FILE).write_text("{}", encoding="ascii")


def tamper_timing(folder: Path) -> None:
    write_timing(folder, "v4_main-1000-1x")


def drop_records(folder: Path) -> None:
    (folder / run.RECORDS_FILE).unlink()


@pytest.mark.parametrize(
    "tamper",
    [tamper_summary, tamper_layout, tamper_records, tamper_receipt, tamper_timing, drop_records],
    ids=["summary-field", "summary-not-canonical", "records", "receipt", "timing", "no-records"],
)
def test_diagnose_refuses_a_cell_that_fails_verification(world_dir, cells_dir, tmp_path, tamper):
    """A cell whose summary does not verify against its records, whose records or receipt were
    changed, whose summary is not canonical JSON, whose ``timing.json`` is of another cell, or
    with no records, is refused: exit 1, nothing written, and one line on standard error naming
    the step and the exception's type, never its text."""
    cells = tmp_path / "cells"
    shutil.copytree(cell_folder(cells_dir, "v4_main"), cell_folder(cells, "v4_main"))
    tamper(cell_folder(cells, "v4_main"))
    out = tmp_path / "out"
    code, stdout, stderr = run_main(v4_diagnose, diagnose_argv(world_dir, cells, out))
    assert code == 1
    assert not out.exists() or not any(out.iterdir())
    (line,) = stderr.splitlines()
    assert re.fullmatch(r"v4_diagnose: .*v4-cell-v4_main-10000-1x.*: [A-Za-z]+Error", line), line
    assert re.search(r"[0-9]\.[0-9]", stdout + stderr) is None


def test_diagnose_refuses_cells_of_other_packs(cells_dir, tmp_path):
    """The regime comes from the packs given, so a cell replayed on other packs is refused."""
    other = write_world(
        tmp_path / "other", btc_world(["100"] * hours_in(FIRST, LAST), FIRST, LAST, FIRST)
    )
    code, _, stderr = run_main(v4_diagnose, diagnose_argv(other, cells_dir, tmp_path / "out"))
    assert code == 1 and not (tmp_path / "out").exists()
    assert "other packs" in stderr and stderr.count("\n") == 1


def test_diagnose_refuses_data_past_2024_12(cells_dir, tmp_path, monkeypatch):
    """The reserved window (v4-d03): a data directory whose ``end_month`` is 2025-01 is refused
    by ``v4_cells_guard``'s own rule before any pack is read; nothing is written."""
    data = write_world(tmp_path / "late", tiny_2025_world())

    def no_load(cls: type, folder: Path) -> Market:
        raise AssertionError("Market.load ran on a data run past 2024-12")

    monkeypatch.setattr(v4_diagnose.Market, "load", classmethod(no_load))
    code, stdout, stderr = run_main(v4_diagnose, diagnose_argv(data, cells_dir, tmp_path / "out"))
    assert code == 1 and stdout == "" and not (tmp_path / "out").exists()
    assert "2025-01 is after the latest month 2024-12" in stderr


def test_diagnose_refuses_an_out_folder_that_holds_a_diagnosis(diagnosis, world_dir, cells_dir):
    """Both files are created exclusively: a second run into the same folder is refused and the
    files stay as they were."""
    before = {
        name: (diagnosis.out / name).read_bytes() for name in ("diagnosis.json", "diagnosis.md")
    }
    code, stdout, stderr = run_main(v4_diagnose, diagnose_argv(world_dir, cells_dir, diagnosis.out))
    assert code == 1 and stdout == ""
    assert "already holds" in stderr
    assert {name: (diagnosis.out / name).read_bytes() for name in before} == before


def test_a_failure_cell_is_listed_without_figures(tmp_path, monkeypatch):
    """A cell whose replay raised (outcome ``engine_error``) verifies and is listed with its
    outcome, record count and timing, and null figures; the page says it has none."""
    hours = hours_in("2024-01", "2024-01")
    flat = CoinSpec("BTCUSDT", Series(month_start("2024-01"), ("100",) * hours))
    world = World("2024-01", (flat,), every_month("2024-01", "2024-01", ("BTCUSDT",)))
    data = write_world(tmp_path / "flat", world)
    original = hold._HoldCell._fills

    def fills_then_fail(self: Any, h: int) -> None:
        if h >= month_start("2024-01") + 2 * HOUR:
            raise RuntimeError("injected failure")
        original(self, h)

    monkeypatch.setattr(hold._HoldCell, "_fills", fills_then_fail)
    argv = ["run", "--data", str(data), "--arm", "hold_universe", "--capital", str(CAPITAL)]
    code, _, stderr = run_main(v4_cell, [*argv, "--costs", str(COSTS), "--out", str(tmp_path)])
    assert (code, stderr) == (0, "")
    spec = CellSpec("hold_universe", CAPITAL, COSTS)
    cells = tmp_path / "cells"
    cells.mkdir()
    (tmp_path / spec.cell_id).rename(cells / f"v4-cell-{spec.cell_id}")
    out = tmp_path / "diagnosis"
    code, stdout, stderr = run_main(v4_diagnose, diagnose_argv(data, cells, out))
    assert (code, stderr) == (0, "")
    count = read_receipt(cells / f"v4-cell-{spec.cell_id}" / run.RECEIPT_FILE).record_count
    assert f"v4_diagnose: {spec.cell_id}: outcome engine_error, {count} records, 0 years" in stdout
    (entry,) = json.loads((out / "diagnosis.json").read_text(encoding="ascii"))["cells"]
    assert entry["outcome"] == "engine_error" and entry["record_count"] == count
    names = ("years", "months", "sides", "exit_reasons", "coins", "signals")
    assert all(entry[name] is None for name in names)
    text = (out / "diagnosis.md").read_text(encoding="utf-8")
    assert "A failure summary: the cell has no figures." in text
    assert "injected failure" not in text + stdout


# ---- the output -------------------------------------------------------------------------------


def test_output_prints_no_prices(diagnosis, cells_dir, records):
    """Standard output carries the guard's line (end month and pin), one line per cell (its id,
    outcome, record, year and month counts) and a last line of counts, and nothing else: no
    price, equity or return, no decimal number at all. Standard error is empty."""
    assert diagnosis.code == 0 and diagnosis.stderr == ""
    lines = diagnosis.stdout.splitlines()
    assert lines[0].startswith("v4_cells_guard: data end_month 2024-02, config_sha256 ")
    expected = []
    for arm in ARMS_RUN:
        spec = CellSpec(arm, CAPITAL, COSTS)
        expected.append(
            f"v4_diagnose: {spec.cell_id}: outcome complete, {len(records[arm])} records, "
            "2 years, 4 months"
        )
    assert lines[1:3] == expected
    assert lines[3:] == [
        "v4_diagnose: 2 cells from 3 folders, 4 regime months; wrote diagnosis.json and "
        "diagnosis.md"
    ]
    assert re.search(r"[0-9]\.[0-9]", diagnosis.stdout) is None
    for arm in ARMS_RUN:
        assert summary_of(cells_dir, arm)["final_equity"] not in diagnosis.stdout


def test_diagnosis_json_holds_exact_strings_and_the_timing(diagnosis, world_dir, cells_dir):
    """``diagnosis.json``: its format, the packs' pins and window, the timing section (copied
    from ``timing.json``, null for a cell without one), the regime and the cells in run order;
    every number of money or ratio is a string (no float anywhere)."""
    document = diagnosis.document
    assert document["format"] == "v4-diagnosis-1"
    market = Market.load(world_dir)
    assert document["data"] == run.data_record(market.pins)
    assert document["window"] == run.window_record(market)
    assert [cell["cell"]["id"] for cell in document["cells"]] == [
        CellSpec(arm, CAPITAL, COSTS).cell_id for arm in ARMS_RUN
    ]
    main_bytes = (cell_folder(cells_dir, "v4_main") / run.RECORDS_FILE).stat().st_size
    assert document["timing"] == [
        {
            "cell": "v4_main-10000-1x",
            "wall_seconds": "5025.37",
            "peak_rss_mb": "2103.8",
            "records_bytes": main_bytes,
        },
        {
            "cell": "hold_universe-10000-1x",
            "wall_seconds": None,
            "peak_rss_mb": None,
            "records_bytes": None,
        },
    ]

    def no_floats(value: object) -> None:
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for item in value.values():
                no_floats(item)
        elif isinstance(value, list):
            for item in value:
                no_floats(item)

    no_floats(json.loads((diagnosis.out / "diagnosis.json").read_bytes(), parse_float=float))
    for arm in ARMS_RUN:
        entry = entry_of(diagnosis, arm)
        summary = summary_of(cells_dir, arm)
        assert entry["cell"] == summary["cell"]
        assert (entry["outcome"], entry["reason"], entry["stop_ms"]) == ("complete", None, None)
        assert (
            entry["record_count"]
            == read_receipt(cell_folder(cells_dir, arm) / run.RECEIPT_FILE).record_count
        )
        assert entry["receipt_sha256"] == summary["receipt_sha256"]


def test_markdown_has_the_regime_then_each_cell_years_months_and_breakdowns(diagnosis):
    """``diagnosis.md``: the timing and the market regime first, shared by every cell, then one
    section per cell, in order: the per-year tables, the per-month tables of every year, then
    the breakdowns by side, exit reason and coin, and the signals."""
    text = diagnosis.markdown
    assert text.startswith("# V4 diagnosis\n")
    order = [text.index("## Timing"), text.index("## Market regime")]
    for arm in ARMS_RUN:
        head = text.index(f"## Cell {CellSpec(arm, CAPITAL, COSTS).cell_id}")
        section = text[head:]
        marks = [
            section.index("### Years"),
            section.index("### Months of 2023"),
            section.index("### Months of 2024"),
            section.index("### By side"),
            section.index("### By exit reason"),
            section.index("### By coin"),
            section.index("### Signals"),
        ]
        assert marks == sorted(marks), arm
        order.append(head)
    assert order == sorted(order)
    assert "| 2023-11 |" in text and "| 2024 |" in text
    assert "<script" not in text
