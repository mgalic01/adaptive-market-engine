"""Frozen V3 baselines on the common-hourly schedule; synthetic inputs, never market data."""

import math
import threading
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.baseline_v3 import (
    LONG_RULES,
    SELECTOR,
    V3Inputs,
    replay_v3_baseline,
    selector_picks,
    v3_capital,
    window_picks,
)
from crypto_grid_bot.combined.common_series import FROZEN_REF
from crypto_grid_bot.combined.report import utc_text
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.trend import replay as v3_replay
from crypto_grid_bot.trend import runner as v3_runner
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
RESERVED = 1_735_689_600_000  # 2025-01-01T00:00Z


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
    assert "present_day_saved_exchange_filters_on_historical_data" in evidence.report.disclosures
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
    label = f"owner_small:EUR:100:usdt_per_eur=1.085:fx_pin={PIN}"
    small = run(initial=D("108.5"), capital_label=label)
    assert small.report.equity_points[0].equity == D("108.5")
    assert "v3_capital_adapter_sets_only_starting_capital" in small.disclosures
    assert small.report.disclosures == small.disclosures
    assert small.report.capital_label == label
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


@pytest.mark.parametrize("stop", ["no_tradable_position", "leverage_not_restored"])
def test_a_native_v3_stop_is_a_finished_result_frozen_to_the_window_end(monkeypatch, stop):
    # Simulate the frozen engine reporting its own stop at 06:00 on day two; the runner's
    # own bookkeeping (lifecycle censoring, audit, stopped reason) runs unchanged.
    original = v3_runner.execute_hour
    stop_hour = START + 30 * HOUR

    def stopping(account, hour_ms, *args, **kwargs):
        result = original(account, hour_ms, *args, **kwargs)
        return replace(result, reason=stop) if hour_ms == stop_hour else result

    monkeypatch.setattr(v3_runner, "execute_hour", stopping)
    evidence = run()
    assert evidence.status == stop and evidence.liquidations == 0
    assert evidence.accounting_explained and evidence.wallet_quantity_exact
    assert evidence.report.disclosures == evidence.disclosures
    # The stop is stated once, with the span its frozen marks cover.
    assert [d for d in evidence.disclosures if stop in d] == [
        f"frozen_after_native_stop:{stop}: hours={(END - stop_hour) // HOUR} "
        f"first={utc_text(stop_hour + HOUR)} last={utc_text(END)}"
    ]
    report = evidence.report
    assert not [i for i in report.issues if i != "contribution_equity_residual"], report.issues
    last = evidence.native[-1]
    assert stop_hour <= last.timestamp_ms < stop_hour + HOUR
    frozen = [p for p in report.equity_points if p.timestamp_ms > last.timestamp_ms]
    assert [p.timestamp_ms for p in frozen] == list(range(stop_hour + HOUR, END + HOUR, HOUR))
    assert all(p.equity == last.equity and FROZEN_REF + stop in p.source_refs for p in frozen)
    assert report.final_equity == last.equity


def test_an_engine_failure_is_not_a_native_stop(monkeypatch):
    original = v3_runner.execute_hour

    def failing(account, hour_ms, *args, **kwargs):
        if hour_ms == START + 30 * HOUR:
            raise ValueError("synthetic engine failure")
        return original(account, hour_ms, *args, **kwargs)

    monkeypatch.setattr(v3_runner, "execute_hour", failing)
    evidence = run()
    assert evidence.status == "engine_failure"
    assert not evidence.report.complete
    refs = [ref for point in evidence.report.equity_points for ref in point.source_refs]
    assert not any(ref.startswith(FROZEN_REF) for ref in refs)


def test_a_trading_rule_gives_a_fully_complete_comparison_report():
    complete = [arm for arm in sorted(LONG_RULES) if run(arm).report.max_drawdown]
    assert complete
    report = run(complete[0]).report
    assert not [i for i in report.issues if i != "contribution_equity_residual"], report.issues


@pytest.fixture
def frozen_calls(monkeypatch):
    """Every call into frozen V3 replay or training; a refusal must come before the first."""
    calls = []

    def spy(name):
        real = getattr(baseline_v3, name)

        def call(*args, **kwargs):
            calls.append(name)
            return real(*args, **kwargs)

        return call

    for name in ("replay_window", "run_walk_forward"):
        monkeypatch.setattr(baseline_v3, name, spy(name))
    return calls


def sealed_inputs(kind):
    """The synthetic inputs plus one record at the reserved boundary."""
    data = inputs()
    bar = Kline(RESERVED, D(1), D(1), D(1), D(1), D(1), D(1), D(0))
    if kind == "hourly":
        return replace(data, hourly={**data.hourly, "BTCUSDT": [*data.hourly["BTCUSDT"], bar]})
    return replace(data, funding={**data.funding, RESERVED + 3: {"BTCUSDT": D(".0001")}})


@pytest.mark.parametrize("kind", ["hourly", "funding"])
def test_a_sealed_record_is_refused_before_any_frozen_v3_code_runs(frozen_calls, kind):
    bad = sealed_inputs(kind)
    options = dict(
        start_ms=START,
        end_ms=END,
        initial=D(10000),
        cost_multiple=1,
        source_refs=("synthetic:v3",),
        adapter_pin=PIN,
    )
    for arm in ("unchanged_v3_r2_long_only", SELECTOR):  # the selector has no pick: still refused
        with pytest.raises(ValueError, match="reserved boundary"):
            replay_v3_baseline(arm, bad, **options)
    with pytest.raises(ValueError, match="reserved boundary"):
        selector_picks(bad, record=lambda attempt: None)  # the training data too
    assert frozen_calls == []


def test_the_frozen_daily_decisions_cannot_be_built_with_a_sealed_daily_bar():
    daily = {s: _daily(s) for s in SYMBOLS}
    daily["BTCUSDT"].append(Kline(RESERVED, D(1), D(1), D(1), D(1), D(1), D(1), D(0)))
    with pytest.raises(DataError, match="reserved window"):
        DailyDecisions(daily, {s: "2020-01" for s in SYMBOLS})


def fake_walk_forward(seen):
    """Stands in for the frozen training; notes the starting capital its runners get."""

    def walk(decisions, filters, hourly, funding, *, record):
        seen.append(vars(v3_replay)["TrendRunner"](filters).account.initial)
        return SimpleNamespace(picks={START: "R2L"}, out_of_sample="oos")

    return walk


def test_selector_training_waits_for_a_small_capital_run_and_trains_at_10000(monkeypatch):
    seen = []
    monkeypatch.setattr(baseline_v3, "run_walk_forward", fake_walk_forward(seen))
    data, outcome = inputs(), {}
    held, release = threading.Event(), threading.Event()

    def small_capital_run():
        with v3_capital(D(100)):
            held.set()
            release.wait(10)

    def train():
        outcome["result"] = selector_picks(data, record=lambda attempt: None)

    holder = threading.Thread(target=small_capital_run, daemon=True)
    trainer = threading.Thread(target=train, daemon=True)
    holder.start()
    assert held.wait(10)
    try:
        trainer.start()
        trainer.join(0.3)
        assert trainer.is_alive() and seen == []  # waiting behind the small-capital run
    finally:
        release.set()
    holder.join(10)
    trainer.join(10)
    assert not trainer.is_alive() and not holder.is_alive()
    assert seen == [D(10000)]
    assert outcome["result"] == ({START: "R2L"}, "oos")


def test_training_inside_a_capital_run_is_refused_not_left_to_deadlock(monkeypatch):
    seen = []
    monkeypatch.setattr(baseline_v3, "run_walk_forward", fake_walk_forward(seen))
    original = vars(v3_replay)["TrendRunner"]
    with v3_capital(D(100)):
        with pytest.raises(RuntimeError, match="inside another"):
            selector_picks(inputs(), record=lambda attempt: None)
        with pytest.raises(RuntimeError, match="inside another"), v3_capital(D(50)):
            pass
    assert seen == [] and vars(v3_replay)["TrendRunner"] is original
    selector_picks(inputs(), record=lambda attempt: None)  # the lock was released
    assert seen == [D(10000)]
