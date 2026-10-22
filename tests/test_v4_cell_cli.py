"""V4 engine task 15: the one-cell CLI (``scripts/v4_cell.py``) end to end, on a synthetic world.

The module's world (``cli_world``) is small enough for all eight arms to run in well under two
minutes (owner rule: no heavy work on the owner's PC). The loop simulates only the window's hours,
three months from 2024-12-01 to 2025-02-28, so the summaries hold an equity at 2025-01-01 and both
the 2021-2024 and the 2025-end eras. History from 2024-02-01 feeds the signals through daily bars:
304 days before the window, more than every warm-up needs (SMA 250 for ``v4_slower``, 60 returns
and the covariance's 60 days). Four coins, each with one job, selected in this rank order:

* BTCUSDT falls (shorted on its perpetual) and is the crash at 3x: its close at 12:00 on
  2025-02-15 is four times the open, a short squeeze. At the next open the gross exposure of the
  two shorts is above 3 x equity while the margin ratio stays above 3, so the post-fill check
  cuts every tradable position by the ceiling factor k' and the cell carries on. hold_btc holds it.
* ETHUSDT rises (held on spot) and leaves the top 10: it is not selected in February, so the
  February decision gives it 0 and its spot sells at 01:00. Its spot hours 00:00 to 04:59 of
  2024-12-20 are masked, a masked day: those open marks are incomplete, and the decision closing
  that day has no bar for it (no target, the no-bar rule).
* SHIBUSDT falls and is shorted on its multiplier perpetual 1000SHIBUSDT, in contracts of 1000
  coins at 1000 x the spot price. Its January funding month is incomplete (``missing_slot``): the
  decision on 2024-12-31 bars the perpetual, the short closes at 01:00 that day as a funding-month
  exit, it has no futures in January and shorts again in February.
* LUNAUSDT rises (held on spot) and is delisted: its data stops at 2025-01-15 00:00, so 168 hours
  after its last bar the dead-market close sells it at its last close less 10%. Its returns stop
  too; it leaves the universe in February, before its missing returns could thin the covariance's
  common days below 40.

Each feature has a test that reads the records and checks that it happened, at the hour and price
the spec gives. The CLI's own behaviour has the rest: the exact one-line output, the refusals that
write nothing and return 1 (a bad pin, bad data, existing outputs, a failure before the summary),
argparse's exit code 2, and the failure summary of an engine error, which returns 0.

The network is blocked for every test (the autouse fixture, and the module fixture blocks it for
its own run). Only synthetic worlds in pytest's temporary folders are read.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import socket
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from v4_synthetic import (
    CONFIG_SHA256,
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
    read_data_json,
    repack,
    write_data_json,
    write_world,
)

from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.pack import coin_pack_file
from crypto_grid_bot.v4.engine import hold, run
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.records import Receipt, read_receipt, read_records
from crypto_grid_bot.v4.engine.safety import ceiling_factor, penalised_price
from crypto_grid_bot.v4.engine.summary import PAGE_FILE, SUMMARY_FILE, verify_summary

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cell  # noqa: E402

D = Decimal
F = Fraction
Rows = list[tuple[str, dict[str, Any]]]

CAPITAL = 10000
COSTS = 1
OUTPUT_FILES = ("records.jsonl", "receipt.json", SUMMARY_FILE, PAGE_FILE)

HISTORY, FIRST, LAST = "2024-02", "2024-12", "2025-02"
START = month_start(HISTORY)
WINDOW_START = month_start(FIRST)
JAN, FEB = month_start("2025-01"), month_start("2025-02")
WINDOW_HOURS = hours_in(FIRST, LAST)
LAST_HOUR = WINDOW_START + (WINDOW_HOURS - 1) * HOUR
HOURS = hours_in(HISTORY, LAST)
MASKED_DAY = WINDOW_START + 19 * DAY  # 2024-12-20: ETHUSDT's spot hours 00:00 to 04:59 masked
FUNDING_DECISION = JAN - DAY  # 00:00 on 2024-12-31, the decision before the incomplete month
CRASH = FEB + 14 * DAY + 12 * HOUR  # the bar of 12:00 on 2025-02-15 closes four times its open
DEAD = JAN + 14 * DAY  # LUNAUSDT's last bar opens at 23:00 on 2025-01-14
DEAD_CLOSE = DEAD + 168 * HOUR  # 168 hours after that bar: 00:00 on 2025-01-22

# SHIBUSDT's spot trades in whole coins, many of them at a time.
SHIB_SPOT = VenueRules(
    step=D("1"),
    min_qty=D("1"),
    max_qty=D("100000000000"),
    min_notional=D("5"),
    tick=D("0.000000000001"),
)


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


def cli_world() -> World:
    """The module's world (module docstring)."""
    before = (CRASH - START) // HOUR
    btc = CoinSpec(
        "BTCUSDT",
        Series(
            START,
            path(
                "90000",
                (before, "-0.0002"),
                (1, "3"),
                (HOURS - before - 1, "-0.0002"),
                noise="0.002",
                seed=1,
            ),
        ),
        perpetual=PerpetualSpec(),
    )
    eth = CoinSpec(
        "ETHUSDT",
        Series(
            START,
            path("2000", (HOURS, "0.0002"), noise="0.002", seed=2),
            masked=day_hours(MASKED_DAY, range(5)),
        ),
    )
    shib = CoinSpec(
        "SHIBUSDT",
        Series(START, path("0.00003", (HOURS, "-0.0002"), noise="0.002", seed=3, places=12)),
        perpetual=PerpetualSpec(multiplier=1000, months={"2025-01": "missing_slot"}),
        spot_rules=SHIB_SPOT,
    )
    luna = CoinSpec(
        "LUNAUSDT",
        Series(START, path("5", ((DEAD - START) // HOUR, "0.0002"), noise="0.002", seed=4)),
    )
    everyone = ("BTCUSDT", "ETHUSDT", "SHIBUSDT", "LUNAUSDT")
    universes = {"2024-12": everyone, "2025-01": everyone, "2025-02": ("BTCUSDT", "SHIBUSDT")}
    return World(LAST, (btc, eth, shib, luna), universes)


def tiny_world() -> World:
    """BTCUSDT flat at 100 with its perpetual, January 2025 only: a world that never trades, for
    the CLI's refusals and its failure summary."""
    hours = hours_in("2025-01", "2025-01")
    btc = CoinSpec("BTCUSDT", Series(JAN, ("100",) * hours), perpetual=PerpetualSpec())
    return World("2025-01", (btc,), every_month("2025-01", "2025-01", ("BTCUSDT",)))


# ---- running the CLI ----------------------------------------------------------------------


def run_cli(argv: Sequence[str]) -> tuple[int, str, str]:
    """``v4_cell.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = v4_cell.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def cell_argv(data: Path, out: Path, arm: str = "v4_main", capital: int = CAPITAL) -> list[str]:
    return [
        "run",
        "--data",
        str(data),
        "--arm",
        arm,
        "--capital",
        str(capital),
        "--costs",
        str(COSTS),
        "--out",
        str(out),
    ]


@dataclass
class CellRun:
    """One CLI run of a cell: its exit code and output, its folder, and its files read back."""

    code: int
    stdout: str
    stderr: str
    folder: Path
    summary: dict[str, Any]
    receipt: Receipt
    rows: Rows


def read_cell(code: int, stdout: str, stderr: str, folder: Path) -> CellRun:
    receipt = read_receipt(folder / "receipt.json")
    summary = json.loads((folder / SUMMARY_FILE).read_bytes())
    rows = list(read_records(folder / "records.jsonl", receipt))
    return CellRun(code, stdout, stderr, folder, summary, receipt, rows)


@pytest.fixture(scope="module")
def world_dir(tmp_path_factory) -> Path:
    return write_world(tmp_path_factory.mktemp("cli-world"), cli_world())


@pytest.fixture(scope="module")
def market(world_dir) -> Market:
    return Market.load(world_dir)


@pytest.fixture(scope="module")
def cells(world_dir, tmp_path_factory) -> dict[str, CellRun]:
    """Every arm of the world at one capital and cost level, each through the CLI into one
    shared ``out`` folder, run once for the tests that read them."""
    out = tmp_path_factory.mktemp("cli-cells") / "out"
    runs: dict[str, CellRun] = {}
    with pytest.MonkeyPatch.context() as patch:
        # The autouse block is per test; this module-wide run blocks the network itself.
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        for arm in ARMS:
            code, stdout, stderr = run_cli(cell_argv(world_dir, out, arm))
            folder = out / CellSpec(arm, CAPITAL, COSTS).cell_id
            runs[arm] = read_cell(code, stdout, stderr, folder)
    return runs


# ---- reading the records ------------------------------------------------------------------


def of_kind(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [record for name, record in rows if name == kind]


def events(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "event") if r["type"] == kind]


def fills(rows: Iterable[tuple[str, dict[str, Any]]], **match: object) -> list[dict[str, Any]]:
    """The fill records whose fields equal ``match``."""
    return [f for f in of_kind(rows, "fill") if all(f[k] == v for k, v in match.items())]


def held_before(rows: Rows, venue: str, symbol: str, before_ms: int) -> Fraction:
    """The leg's signed quantity once every fill stamped before ``before_ms`` is booked."""
    return sum(
        (
            f["side"] * F(D(f["quantity"]))
            for f in fills(rows, venue=venue, symbol=symbol)
            if f["timestamp_ms"] < before_ms
        ),
        F(0),
    )


def daily(rows: Rows, decision_ms: int, coin: str) -> dict[str, Any]:
    (found,) = [
        r
        for r in of_kind(rows, "daily_coin")
        if (r["decision_ms"], r["coin"]) == (decision_ms, coin)
    ]
    return found


def lifecycles(rows: Rows, coin: str) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "lifecycle") if r["coin"] == coin]


def monthly(rows: Rows, open_ms: int) -> dict[str, Any]:
    (found,) = [r for r in of_kind(rows, "monthly") if r["open_ms"] == open_ms]
    return found


def hourly(rows: Rows, open_ms: int) -> dict[str, Any]:
    (found,) = [r for r in of_kind(rows, "hourly") if r["open_ms"] == open_ms]
    return found


def spot_open(market: Market, coin: str, hour_ms: int) -> Decimal:
    bar = market.coin(coin).spot.bar(hour_ms)
    assert bar is not None
    return bar.open


# ---- every arm through the CLI ------------------------------------------------------------


def test_cli_runs_every_arm_on_the_synthetic_world(world_dir, cells):
    """Each of the eight arms, at one capital and cost level, writes its cell's four files in
    ``out/<cell id>/`` and exits 0; its summary verifies against its records and receipt
    (rebuilt here as well as by the CLI). Every cell of this world runs to the window's end: the
    ceiling cut restores its limit, and no arm is liquidated."""
    pins = read_data_json(world_dir)["packs"]
    data = {
        "config_sha256": CONFIG_SHA256,
        "end_month": LAST,
        "daily_sha256": pins["daily"]["sha256"],
        "index_sha256": pins["hourly_index"]["sha256"],
    }
    window = list(range(WINDOW_START, LAST_HOUR + HOUR, HOUR))
    assert set(cells) == set(ARMS) and len(cells) == 8
    for arm, cell in cells.items():
        spec = CellSpec(arm, CAPITAL, COSTS)
        assert (cell.code, cell.stderr) == (0, ""), arm
        assert cell.folder.name == spec.cell_id
        assert sorted(item.name for item in cell.folder.iterdir()) == sorted(OUTPUT_FILES)
        verify_summary(cell.summary, cell.folder / "records.jsonl", cell.receipt)
        summary = cell.summary
        assert summary["cell"] == {
            "id": spec.cell_id,
            "arm": arm,
            "capital": CAPITAL,
            "cost_multiple": COSTS,
        }
        assert summary["data"] == data
        assert (summary["outcome"], summary["reason"], summary["stop_ms"]) == (
            "complete",
            None,
            None,
        )
        assert [mark[0] for mark in summary["open_marks"]] == window
        marks = {ms: equity for ms, equity, _ in summary["open_marks"]}
        assert summary["equity_2025"] == marks[JAN]
        assert summary["final_after_close"] == summary["final_equity"]
        assert summary["liquidations"] == 0
        assert [era["start_ms"] for era in summary["eras"]] == [None, WINDOW_START, JAN]
        assert [year["year"] for year in summary["years"]] == [2024, 2025]
        page = (cell.folder / PAGE_FILE).read_text(encoding="utf-8")
        assert spec.cell_id in page and "<script" not in page
    # The arms do differ: the long-only arm never shorts, and the holds trade spot alone.
    for arm in ("v4_long_only", "hold_universe", "hold_btc"):
        assert not fills(cells[arm].rows, venue="futures"), arm
    assert fills(cells["v4_main"].rows, venue="futures")
    assert {f["coin"] for f in of_kind(cells["hold_btc"].rows, "fill")} == {"BTCUSDT"}


def test_cli_output_prints_no_prices(cells):
    """Standard output is one line per cell holding its id, outcome, record count, hours and the
    summary's SHA-256 (counts and pins only, owner rule: public logs), and nothing else: no
    price, no equity, no decimal number at all."""
    for arm, cell in cells.items():
        digest = hashlib.sha256((cell.folder / SUMMARY_FILE).read_bytes()).hexdigest()
        expected = (
            f"v4_cell run: {CellSpec(arm, CAPITAL, COSTS).cell_id}: outcome complete, "
            f"{cell.receipt.record_count} records, {WINDOW_HOURS} hours, summary sha256 {digest}\n"
        )
        assert cell.stdout == expected
        assert re.search(r"[0-9]\.[0-9]", cell.stdout) is None
        assert cell.summary["final_equity"] not in cell.stdout


# ---- the world's features, each checked in the records ------------------------------------


def test_the_world_delists_a_coin_and_its_dead_market_closes(market, cells):
    """LUNAUSDT's data stops at DEAD. With no bar in the 168 hours before DEAD_CLOSE, the first
    step of that hour closes its spot leg as one synthetic batch: at its last close less 10%, no
    slippage, the spot fee, reason ``delisting``, ending its lifecycle there. Every arm that holds
    it shows the same close (V4's longs and hold_universe)."""
    last_close = market.coin("LUNAUSDT").spot.last_close_before(DEAD)
    assert last_close is not None and market.coin("LUNAUSDT").spot.bar(DEAD) is None
    price = penalised_price(last_close, 1)
    fee_rate = F(CellSpec("v4_main", CAPITAL, COSTS).costs("spot").fee_rate)
    for arm in ("v4_main", "v4_long_only", "hold_universe"):
        rows = cells[arm].rows
        held = held_before(rows, "spot", "LUNAUSDT", DEAD_CLOSE)
        assert held > 0, arm
        (batch,) = events(rows, "synthetic_closes")
        assert batch["hour_ms"] == DEAD_CLOSE
        (leg,) = batch["legs"]
        assert (leg["coin"], leg["venue"], leg["reason"]) == ("LUNAUSDT", "spot", "delisting")
        assert D(leg["last_close"]) == last_close and D(leg["price"]) == price
        (fill,) = fills(rows, coin="LUNAUSDT", reason="delisting")
        assert (fill["hour_ms"], fill["venue"], fill["side"]) == (DEAD_CLOSE, "spot", -1)
        assert F(D(fill["quantity"])) == held
        assert D(fill["price"]) == D(fill["unslipped_price"]) == price
        assert F(D(fill["fee"])) == held * F(price) * fee_rate
        (ended,) = lifecycles(rows, "LUNAUSDT")
        assert (ended["exit_reason"], ended["exit_ms"]) == ("delisting", DEAD_CLOSE)
        assert not [f for f in fills(rows, coin="LUNAUSDT") if f["timestamp_ms"] > DEAD_CLOSE]


def test_the_world_crashes_a_short_book_through_the_3x_ceiling(market, cells):
    """BTCUSDT's close at CRASH is four times its open. The open mark of the next hour sees it:
    equity falls by more than half and the two shorts' gross exposure is above 3 x equity, while
    backing stays above 3 x maintenance (no margin cut). The post-fill check cuts every tradable
    position, both shorts, to ``held x k'`` with ``k' = ceiling_factor(...)`` at that open, each
    by a reduce-only buy with reason ``ceiling cut``. The limit is restored: the cell runs on."""
    rows = cells["v4_main"].rows
    after = CRASH + HOUR
    assert spot_open(market, "BTCUSDT", after) > 3 * spot_open(market, "BTCUSDT", CRASH)
    assert D(hourly(rows, after)["open_equity"]) < D(hourly(rows, CRASH)["open_equity"]) / 2
    assert not events(rows, "margin_cut")
    (cut,) = events(rows, "ceiling_cut")
    assert (cut["hour_ms"], cut["check"], cut["timestamp_ms"]) == (after, "post_fill", after)
    equity, untradable = D(cut["equity"]), D(cut["untradable_gross"])
    tradable = D(cut["tradable_gross"])
    assert untradable == 0 and cut["untradable"] == []
    assert F(tradable) > 3 * F(equity) > 0  # the breach
    factor = ceiling_factor(equity, untradable, tradable)
    assert factor is not None and 0 < factor < 1 and D(cut["factor"]) == factor
    booked = fills(rows, timestamp_ms=after, reason="ceiling cut")
    assert [(f["coin"], f["venue"], f["symbol"], f["side"]) for f in booked] == [
        ("BTCUSDT", "futures", "BTCUSDT", 1),
        ("SHIBUSDT", "futures", "1000SHIBUSDT", 1),
    ]
    for fill in booked:
        held = held_before(rows, "futures", fill["symbol"], after)
        assert held < 0  # a short, cut by part of it
        assert 0 < F(D(fill["quantity"])) < -held
    assert [(leg["coin"], leg["venue"]) for leg in cut["legs"]] == [
        ("BTCUSDT", "futures"),
        ("SHIBUSDT", "futures"),
    ]
    assert D(hourly(rows, after)["margin_ratio"]) > 3
    assert cells["v4_main"].summary["outcome"] == "complete"


def test_the_world_has_a_coin_leave_the_top_10(cells):
    """ETHUSDT is not selected in February. The February decision gives it 0 as a universe exit
    and cancels its order; its spot leg sells at 01:00 with reason ``universe exit``, ending its
    lifecycle, and it is never decided again. hold_universe sells it at its February rebalance."""
    rows = cells["v4_main"].rows
    record = monthly(rows, FEB)
    assert record["universe"] == ["BTCUSDT", "SHIBUSDT"]
    assert record["left"] == ["ETHUSDT", "LUNAUSDT"]
    view = daily(rows, FEB, "ETHUSDT")
    assert view["universe_exit"] and not view["in_universe"] and view["target"] == "0"
    scheduled = [e for e in events(rows, "exit_scheduled") if e["coin"] == "ETHUSDT"]
    assert [(e["venue"], e["reason"], e["after_ms"]) for e in scheduled] == [
        ("spot", "universe exit", FEB + HOUR)
    ]
    for arm in ("v4_main", "hold_universe"):
        rows = cells[arm].rows
        held = held_before(rows, "spot", "ETHUSDT", FEB + HOUR)
        assert held > 0, arm
        (fill,) = fills(rows, coin="ETHUSDT", reason="universe exit")
        assert (fill["hour_ms"], fill["side"], F(D(fill["quantity"]))) == (FEB + HOUR, -1, held)
        (ended,) = lifecycles(rows, "ETHUSDT")
        assert (ended["exit_reason"], ended["exit_ms"]) == ("universe exit", FEB + HOUR)
    decided = of_kind(cells["v4_main"].rows, "daily_coin")
    assert max(r["decision_ms"] for r in decided if r["coin"] == "ETHUSDT") == FEB


def test_the_world_trades_a_multiplier_perpetual_in_contracts(market, cells):
    """SHIBUSDT's perpetual is 1000SHIBUSDT: one contract is 1000 coins. Every futures fill of the
    coin carries the perpetual's symbol and is priced per contract, at 1000 x the spot price
    (the open, or the close at the window end); the monthly records name it with its multiplier."""
    rows = cells["v4_main"].rows
    booked = fills(rows, coin="SHIBUSDT", venue="futures")
    reasons = {f["reason"] for f in booked}
    assert {"signal", "funding-month exit", "ceiling cut", "window end"} <= reasons
    spot = market.coin("SHIBUSDT").spot
    for fill in booked:
        assert fill["symbol"] == "1000SHIBUSDT"
        bar = spot.bar(fill["hour_ms"])
        assert bar is not None
        price = bar.close if fill["reason"] == "window end" else bar.open
        assert D(fill["unslipped_price"]) == 1000 * price
    (entry,) = [p for p in monthly(rows, WINDOW_START)["perpetuals"] if p["coin"] == "SHIBUSDT"]
    assert (entry["perpetual"], entry["multiplier"]) == ("1000SHIBUSDT", 1000)
    # The hold arms buy the coin itself on spot, in coins.
    assert {f["symbol"] for f in fills(cells["hold_universe"].rows, coin="SHIBUSDT")} == {
        "SHIBUSDT"
    }


def test_the_world_masks_a_day_and_its_hours_are_incomplete(cells):
    """ETHUSDT's spot hours 00:00 to 04:59 of MASKED_DAY are masked: 19 usable hours, so no daily
    bar for the day. The decision that closes it finds no bar, keeps the reading of the day
    before and takes no target. An open mark is incomplete exactly when a held leg has no bar:
    the five masked hours while ETHUSDT is held, and LUNAUSDT's 168 dead hours. hold_btc holds
    neither, so every one of its marks is complete."""
    view = daily(cells["v4_main"].rows, MASKED_DAY + DAY, "ETHUSDT")
    assert view["no_bar"] is True and view["no_target"] == "no_bar"
    assert view["reading_day_ms"] == MASKED_DAY - DAY
    expected = set(day_hours(MASKED_DAY, range(5))) | set(range(DEAD, DEAD_CLOSE, HOUR))
    for arm, cell in cells.items():
        incomplete = {ms for ms, _, complete in cell.summary["open_marks"] if not complete}
        assert incomplete == (set() if arm == "hold_btc" else expected), arm


def test_the_world_has_an_incomplete_funding_month_and_its_exit(market, cells):
    """1000SHIBUSDT's January funding month is ``missing_slot``. At the decision on 2024-12-31 the
    perpetual is barred for the next month: SHIBUSDT's signal becomes max(s, 0) = 0, its order is
    cancelled and its short closes at 01:00 as a funding-month exit, a reduce-only buy of every
    contract held; a short needs no replacement buy. It holds no futures and pays no funding in
    January, and shorts again from February's first fill hour."""
    rows = cells["v4_main"].rows
    assert market.funding_month("SHIBUSDT", "2025-01") == "missing_slot"
    view = daily(rows, FUNDING_DECISION, "SHIBUSDT")
    assert view["funding_month_exit"] is True and view["eligible"] is False
    assert (view["next_month"], view["next_month_status"]) == ("2025-01", "missing_slot")
    assert view["target"] == "0" and D(view["s"]) < 0
    (cancelled,) = [e for e in events(rows, "order_cancelled") if e["coin"] == "SHIBUSDT"]
    assert (cancelled["hour_ms"], cancelled["reason"]) == (FUNDING_DECISION, "funding-month exit")
    exit_hour = FUNDING_DECISION + HOUR
    held = held_before(rows, "futures", "1000SHIBUSDT", exit_hour)
    assert held < 0
    (fill,) = fills(rows, coin="SHIBUSDT", reason="funding-month exit")
    assert (fill["hour_ms"], fill["symbol"], fill["side"]) == (exit_hour, "1000SHIBUSDT", 1)
    assert F(D(fill["quantity"])) == -held
    assert [e["hour_ms"] for e in events(rows, "replacement_not_needed")] == [exit_hour]
    ended = lifecycles(rows, "SHIBUSDT")[0]
    assert (ended["side"], ended["exit_reason"], ended["exit_ms"]) == (
        "short",
        "funding-month exit",
        exit_hour,
    )
    (entry,) = [p for p in monthly(rows, JAN)["perpetuals"] if p["coin"] == "SHIBUSDT"]
    assert entry["status"] == "missing_slot"
    assert not [f for f in fills(rows, symbol="1000SHIBUSDT") if JAN <= f["timestamp_ms"] < FEB]
    assert not [
        r for r in of_kind(rows, "funding") if r["coin"] == "SHIBUSDT" and JAN <= r["hour_ms"] < FEB
    ]
    (back,) = fills(rows, symbol="1000SHIBUSDT", timestamp_ms=FEB + HOUR)
    assert (back["side"], back["reason"]) == (-1, "signal")


# ---- the CLI's refusals and its failure summary -------------------------------------------


def _bad_pin(data: Path) -> None:
    document = read_data_json(data)
    document["packs"]["hourly_index"]["sha256"] = "0" * 64
    write_data_json(data, document)


def _bad_data(data: Path) -> None:
    """A validly pinned coin pack whose fourth spot bar has its low above the body."""

    def change(document: dict[str, Any]) -> None:
        document["spot"][3][3] = "100.5"

    repack(data, coin_pack_file("BTCUSDT"), change)


def _no_data(data: Path) -> None:
    (data / "data.json").unlink()


@pytest.mark.parametrize("spoil", [_bad_pin, _bad_data, _no_data], ids=["pin", "data", "missing"])
def test_cli_refuses_a_data_dir_with_a_bad_pin(spoil, tmp_path):
    """A data directory that does not load (a pin that does not match, a validly pinned pack the
    loader refuses, no ``data.json``) is not a cell outcome: nothing is written, not even the
    cell's folder, and the exit code is 1. The reason goes to standard error, with any decimal
    number in it hidden, so a bad bar's price never reaches a public log."""
    data = write_world(tmp_path / "world", tiny_world())
    spoil(data)
    out = tmp_path / "out"

    code, stdout, stderr = run_cli(cell_argv(data, out))

    assert (code, stdout) == (1, "")
    assert stderr.startswith("v4_cell run: v4_main-10000-1x: refused: ")
    assert not out.exists()
    assert re.search(r"[0-9]\.[0-9]", stderr) is None
    if spoil is _bad_pin:
        assert "sha256" in stderr
    if spoil is _bad_data:  # the loader names the bar's low, which is hidden
        assert "the low <number> is above the body" in stderr


@pytest.mark.parametrize("existing", OUTPUT_FILES)
def test_cli_refuses_a_cell_directory_that_already_holds_outputs(existing, tmp_path):
    """A cell's files are never replaced: a cell folder holding any of the four is refused before
    the market is read, with exit code 1, and is left exactly as it was."""
    data = write_world(tmp_path / "world", tiny_world())
    folder = tmp_path / "out" / "v4_main-10000-1x"
    folder.mkdir(parents=True)
    (folder / existing).write_bytes(b"kept")

    code, stdout, stderr = run_cli(cell_argv(data, tmp_path / "out"))

    assert (code, stdout) == (1, "")
    assert stderr.startswith("v4_cell run: v4_main-10000-1x: refused: ")
    assert [item.name for item in folder.iterdir()] == [existing]
    assert (folder / existing).read_bytes() == b"kept"


@pytest.mark.parametrize(
    ("change", "value"),
    [("--capital", "5000"), ("--costs", "3"), ("--arm", "v3_as_built"), ("--capital", "1e4")],
)
def test_cli_refuses_bad_arguments_with_argparse_exit_code(change, value, tmp_path):
    """A capital, cost multiple or arm outside the run's is argparse's error: exit code 2, and
    nothing is read or written."""
    argv = cell_argv(tmp_path / "missing", tmp_path / "out")
    argv[argv.index(change) + 1] = value
    with pytest.raises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()):
        v4_cell.main(argv)
    assert stopped.value.code == 2
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("arm", "owner"), [("v4_main", run._V4Cell), ("hold_universe", hold._HoldCell)]
)
def test_cli_writes_a_failure_summary_on_engine_error(arm, owner, monkeypatch, tmp_path):
    """An exception in the replay's loop is the outcome ``engine_error`` (ruling P5). The CLI
    writes its short failure summary and page, the summary verifies against the records, and the
    exit code is 0: a summary was written. The injected exception comes from the fill phase of
    the window's third hour."""
    data = write_world(tmp_path / "world", tiny_world())
    failing_at = JAN + 2 * HOUR
    original = owner._fills

    def fills_then_fail(self, h):
        if h >= failing_at:
            raise RuntimeError("injected failure")
        return original(self, h)

    monkeypatch.setattr(owner, "_fills", fills_then_fail)

    code, stdout, stderr = run_cli(cell_argv(data, tmp_path / "out", arm))

    spec = CellSpec(arm, CAPITAL, COSTS)
    cell = read_cell(code, stdout, stderr, tmp_path / "out" / spec.cell_id)
    assert (cell.code, cell.stderr) == (0, "")
    verify_summary(cell.summary, cell.folder / "records.jsonl", cell.receipt)
    pins = read_data_json(data)["packs"]
    assert cell.summary == {
        "format": "v4-summary-1",
        "cell": {"id": spec.cell_id, "arm": arm, "capital": CAPITAL, "cost_multiple": COSTS},
        "data": {
            "config_sha256": CONFIG_SHA256,
            "end_month": "2025-01",
            "daily_sha256": pins["daily"]["sha256"],
            "index_sha256": pins["hourly_index"]["sha256"],
        },
        "outcome": "engine_error",
        "type": "RuntimeError",
        "message": "injected failure",
        "hour_ms": failing_at,
    }
    assert sorted(item.name for item in cell.folder.iterdir()) == sorted(OUTPUT_FILES)
    digest = hashlib.sha256((cell.folder / SUMMARY_FILE).read_bytes()).hexdigest()
    assert stdout == (
        f"v4_cell run: {spec.cell_id}: outcome engine_error, {cell.receipt.record_count} records, "
        f"3 hours, summary sha256 {digest}\n"
    )


def test_cli_reports_a_failure_before_the_summary_without_its_message(monkeypatch, tmp_path):
    """An exception after the replay but before the summary is written leaves the replay's
    records and receipt but no summary: exit code 1, and standard error names the exception's
    type only, since its message may hold an equity."""
    data = write_world(tmp_path / "world", tiny_world())

    def broken(*args: object) -> Mapping[str, object]:
        raise ValueError("the first open mark, 10234.56, is not the capital")

    monkeypatch.setattr(v4_cell, "build_summary", broken)

    code, stdout, stderr = run_cli(cell_argv(data, tmp_path / "out"))

    folder = tmp_path / "out" / "v4_main-10000-1x"
    assert (code, stdout) == (1, "")
    assert "ValueError" in stderr and "10234" not in stderr
    assert sorted(item.name for item in folder.iterdir()) == ["receipt.json", "records.jsonl"]
