"""Frozen V3 baselines on the common-hourly schedule; synthetic inputs, never market data."""

import math
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.baseline_v3 import (
    LONG_RULES,
    SELECTOR,
    V3Inputs,
    replay_v3_baseline,
    v3_capital,
    window_picks,
)
from crypto_grid_bot.trend import replay as v3_replay
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.replay import replay_window

HOUR = 3_600_000
DAY = 24 * HOUR
PIN = "b" * 64
SYMBOLS = ("BTCUSDT", "ETHUSDT")
BASE = {"BTCUSDT": 7000.0, "ETHUSDT": 150.0}


def ms(year, month, day):
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


START, END = ms(2020, 5, 1), ms(2020, 5, 4)


def _daily(symbol):
    rows, stamp, index = [], ms(2019, 1, 1), 0
    while stamp < END:
        price = BASE[symbol] * (1 + 0.002 * index) * (1 + 0.03 * math.sin(index / 3.0))
        open_, close = D(str(round(price, 4))), D(str(round(price * 1.004, 4)))
        high = (max(open_, close) * D("1.01")).quantize(D(".0001"))
        low = (min(open_, close) * D(".99")).quantize(D(".0001"))
        rows.append(Kline(stamp, open_, high, low, close, D(1), D(1), D(0)))
        stamp, index = stamp + DAY, index + 1
    return rows


def _hourly(symbol):
    rows, stamp, index = [], START, 0
    while stamp < END:
        price = BASE[symbol] * 2.0 * (1 + 0.01 * math.sin(index / 2.0)) * (1 + 0.0004 * index)
        open_, close = D(str(round(price, 4))), D(str(round(price * 1.002, 4)))
        high = (max(open_, close) * D("1.005")).quantize(D(".0001"))
        low = (min(open_, close) * D(".995")).quantize(D(".0001"))
        rows.append(Kline(stamp, open_, high, low, close, D(1), D(1), D(0)))
        stamp, index = stamp + HOUR, index + 1
    return rows


def inputs(funding_offset=3):
    filters = OrderFilters(
        D(".001"), D(100000), D(".001"), D(5), D(".001"), D(100000), D(".001"), D(".001")
    )
    funding = {}
    for slot in range(START, END, 8 * HOUR):
        funding.setdefault(slot, {})["BTCUSDT"] = D(".0001")  # exactly on the hour
        funding.setdefault(slot + funding_offset, {})["ETHUSDT"] = D(".0001")  # just after
    return V3Inputs(
        DailyDecisions({s: _daily(s) for s in SYMBOLS}, {s: "2020-01" for s in SYMBOLS}),
        {s: filters for s in SYMBOLS},
        {s: _hourly(s) for s in SYMBOLS},
        funding,
    )


def run(arm="unchanged_v3_r2_long_only", **changes):
    options = dict(
        start_ms=START,
        end_ms=END,
        initial=D(10000),
        cost_multiple=1,
        source_refs=("synthetic:v3",),
        adapter_pin=PIN,
    )
    options.update(changes)
    return replay_v3_baseline(arm, inputs(), **options)


@pytest.mark.parametrize("arm", sorted(LONG_RULES))
def test_each_long_rule_gives_a_complete_comparison_report(arm):
    evidence = run(arm)
    assert evidence.status is None
    report = evidence.report
    # A rule that never trades on this synthetic data has zero drawdown, an
    # indeterminate return/drawdown by rule; nothing else may be missing.
    idle = {
        "metric_unavailable:return_drawdown:zero_drawdown",
        "metric_unavailable:sharpe:zero_variance",
    }
    issues = [i for i in report.issues if i != "contribution_equity_residual"]
    assert set(issues) <= idle, issues
    assert not issues or report.max_drawdown == 0
    assert evidence.accounting_explained and evidence.wallet_quantity_exact
    assert abs(evidence.accounting_residual) <= D("1e-18")
    # Every UTC hour is a boundary; only hour-stamped marks enter the comparison.
    boundaries = report.policy_evidence.boundaries
    assert [b.timestamp_ms for b in boundaries] == list(range(START, END + HOUR, HOUR))
    assert all(p.timestamp_ms % HOUR == 0 for p in report.equity_points)
    assert boundaries[0].role == "opening" and boundaries[-1].role == "terminal"
    assert report.equity_points[0].equity == D(10000)


def test_native_marks_keep_every_off_hour_mark_labelled():
    evidence = run()
    kinds = {mark.kind for mark in evidence.native}
    assert {"open", "post_fill", "favourable", "adverse", "terminal"} <= kinds
    off_hour = [m for m in evidence.native if m.timestamp_ms % HOUR]
    assert off_hour and all(m.kind in {"funding", "favourable", "adverse"} for m in off_hour)
    assert "v3_funding_after_fills_is_native_timing" in evidence.disclosures
    in_report = {p.id for p in evidence.report.equity_points}
    assert not any(":favourable" in identity or ":adverse" in identity for identity in in_report)


@pytest.mark.parametrize("cost", [1, 2])
def test_capital_adapter_is_exactly_the_frozen_run_at_10000(cost):
    data = inputs()
    plain = replay_window(
        data.decisions,
        data.filters,
        data.hourly,
        data.funding,
        START,
        END,
        {START: "R2L"},
        multiple=2,
        cost_multiple=cost,
    )
    with v3_capital(D(10000)):
        adapted = replay_window(
            data.decisions,
            data.filters,
            data.hourly,
            data.funding,
            START,
            END,
            {START: "R2L"},
            multiple=2,
            cost_multiple=cost,
        )
    assert adapted.runner.equity_path == plain.runner.equity_path
    assert adapted.runner.account.fills == plain.runner.account.fills


def test_capital_adapter_runs_small_capital_and_always_restores_the_runner():
    original = vars(v3_replay)["TrendRunner"]
    small = run(initial=D("108.5"))
    assert small.report.equity_points[0].equity == D("108.5")
    assert "v3_capital_adapter_sets_only_starting_capital" in small.disclosures
    assert vars(v3_replay)["TrendRunner"] is original
    with pytest.raises(RuntimeError), v3_capital(D(5)):
        raise RuntimeError("synthetic")
    assert vars(v3_replay)["TrendRunner"] is original
    with pytest.raises(ValueError), v3_capital(D(0)):
        pass


def test_doubled_cost_is_the_frozen_native_multiple():
    base, doubled = run(cost_multiple=1), run(cost_multiple=2)
    assert doubled.status is None
    assert doubled.report.fees > base.report.fees


def test_selector_replays_the_frozen_picks_in_force_over_the_window():
    picks = {START - 30 * DAY: "R2L", START + DAY: "R3L"}
    assert window_picks(picks, START, END) == {START: "R2L", START + DAY: "R3L"}
    assert window_picks(picks, START - 40 * DAY, END) is None
    evidence = run(SELECTOR, picks=picks)
    assert evidence.status is None
    assert "v3_selector_frozen_picks_on_registered_window" in evidence.disclosures
    early = run(SELECTOR, picks={START + DAY: "R2L"})
    assert early.status == "no_selector_pick" and not early.report.complete


def test_unknown_or_baseline_less_arms_are_refused():
    with pytest.raises(ValueError):
        run("combined")
    assert set(LONG_RULES) == {f"unchanged_v3_r{i}_long_only" for i in range(1, 7)}
    assert baseline_v3.V3_MULTIPLE == 2


def test_a_trading_rule_gives_a_fully_complete_comparison_report():
    complete = [arm for arm in sorted(LONG_RULES) if run(arm).report.max_drawdown]
    assert complete
    report = run(complete[0]).report
    assert not [i for i in report.issues if i != "contribution_equity_residual"], report.issues
