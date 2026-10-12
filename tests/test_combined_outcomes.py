"""Outcomes carry exactly their report's figures, so acceptance can match them."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest
from test_combined_baseline_hold import hold

from crypto_grid_bot.combined.baseline_records import (
    NATIVE_STOPS,
    BaselineEvidence,
    NativeMark,
    comparison_report,
)
from crypto_grid_bot.combined.experiment import RunIdentity, _report_valid
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.combined.outcomes import baseline_outcome, strategy_outcome
from crypto_grid_bot.combined.replay_records import strategy_report
from crypto_grid_bot.combined.report import Contribution
from crypto_grid_bot.combined.strategy_replay import replay_strategy

HOUR = 3_600_000


def identity(arm, scenario, pin, end_days=3):
    return RunIdentity(
        arm,
        "w1",
        "research",
        1,
        "a" * 64,
        "b" * 64,
        fx.START,
        fx.START + end_days * fx.DAY,
        "c" * 40,
        "d" * 64,
        None,
        POLICY_ID,
        pin,
        scenario,
    )


def test_a_complete_strategy_run_is_a_valid_acceptance_outcome():
    trace = replay_strategy(fx.run("spot_trend", 3), (fx.market("BTCUSDT", fx.uptrend, 3),))
    report = strategy_report(trace, adapter_pin="0" * 64)
    row = strategy_outcome(
        trace, report, identity("spot_trend", "open_low_high_close", "0" * 64), attempt_id="a-1"
    )
    assert row.complete and not row.failed and row.liquidations == 0
    assert row.wallet_quantity_exact is True
    assert (row.final_equity, row.max_drawdown, row.accounting_residual) == (
        report.final_equity,
        report.max_drawdown,
        report.reconciliation_residual,
    )
    assert _report_valid(row)


def test_a_failed_strategy_run_is_retained_as_failed_and_incomplete(monkeypatch):
    from crypto_grid_bot.combined import strategy_replay

    original = strategy_replay.replay_held_portfolio

    def failing(*args, **kwargs):
        return replace(original(*args, **kwargs), failure="portfolio_safety_failure")

    monkeypatch.setattr(strategy_replay, "replay_held_portfolio", failing)
    trace = replay_strategy(fx.run("spot_trend", 3), (fx.market("BTCUSDT", fx.uptrend, 3),))
    report = strategy_report(trace, adapter_pin="0" * 64)
    row = strategy_outcome(
        trace, report, identity("spot_trend", "open_low_high_close", "0" * 64), attempt_id="a-2"
    )
    assert row.failed and not row.complete
    assert not _report_valid(row)


def test_a_complete_baseline_cell_is_a_valid_acceptance_outcome():
    evidence = hold()
    row = baseline_outcome(
        evidence, identity("matched_spot_hold", "native", "c" * 64), attempt_id="h-1"
    )
    assert row.complete and not row.failed
    assert row.initial_equity == D(10000)
    assert row.native_stop is None
    assert _report_valid(row)


def stopped(status):
    """A V3 cell whose last native mark is its stop, 30 hours into a three-day window.

    As the V3 adapter builds it: a native stop is held frozen, any other stop is a
    producer issue.
    """
    native_stop = status if status in NATIVE_STOPS else None
    end = fx.START + 3 * fx.DAY
    marks = (
        NativeMark(fx.START, "open", D(10000), D(0), D(4000)),
        *(NativeMark(fx.START + h * HOUR, "open", D(9900), D(0), D(4000)) for h in range(1, 30)),
        NativeMark(fx.START + 30 * HOUR, "post_fill", D(9800), D(0), D(4000)),
    )
    lifecycle = Contribution(
        "life",
        "unchanged_v3",
        "BTC",
        "long",
        None,
        D(-200),
        D(0),
        D(0),
        D(1),
        None,
        fx.START,
        "open_marked",
        source_refs=("synthetic",),
    )
    report = comparison_report(
        "unchanged_v3_r2_long_only",
        marks,
        (lifecycle,),
        initial=D(10000),
        start_ms=fx.START,
        end_ms=end,
        source_refs=("synthetic",),
        adapter_pin="c" * 64,
        producer_issues=() if native_stop else (f"baseline_stop:{status}",),
        native_stop=native_stop,
    )
    liquidations = int(status == "liquidation")
    return BaselineEvidence(
        "unchanged_v3_r2_long_only",
        "v3-native",
        marks,
        report,
        status,
        liquidations,
        D(0),
        True,
        True,
        (),
    )


def test_a_liquidated_baseline_is_a_finished_result():
    row = baseline_outcome(
        stopped("liquidation"),
        identity("unchanged_v3_r2_long_only", "native", "c" * 64),
        attempt_id="v3-1",
    )
    assert row.complete and not row.failed
    assert row.native_stop == "liquidation" and row.liquidations == 1
    assert row.final_equity == D(9800)
    assert _report_valid(row)


# Owner, 2026-10-12: V3's no_tradable_position and leverage_not_restored come from masked
# or untradable coins, not a market event: incomplete, never a finished result.
@pytest.mark.parametrize(
    "status",
    [
        "no_tradable_position",
        "leverage_not_restored",
        "engine_failure",
        "unavailable_exclusion_close",
    ],
)
def test_other_baseline_stops_stay_failed_and_incomplete(status):
    row = baseline_outcome(
        stopped(status),
        identity("unchanged_v3_r2_long_only", "native", "c" * 64),
        attempt_id="v3-2",
    )
    assert row.failed and not row.complete
    assert row.native_stop is None
    assert not _report_valid(row)


def test_outcomes_carry_their_reports_disclosures_and_capital_label():
    trace = replay_strategy(fx.run("spot_trend", 3), (fx.market("BTCUSDT", fx.uptrend, 3),))
    report = strategy_report(trace, adapter_pin="0" * 64, capital_label="research_10000_usdt")
    row = strategy_outcome(
        trace, report, identity("spot_trend", "open_low_high_close", "0" * 64), attempt_id="a-3"
    )
    assert row.disclosures == report.disclosures and row.disclosures
    assert row.capital_label == "research_10000_usdt"
    assert _report_valid(row)  # the recomputed report keeps both
    evidence = hold(capital_label="research_10000_usdt")
    base = baseline_outcome(
        evidence, identity("matched_spot_hold", "native", "c" * 64), attempt_id="h-2"
    )
    assert base.disclosures == evidence.disclosures
    assert "hold_marks_at_hourly_opening_quotes" in base.disclosures
    assert base.capital_label == "research_10000_usdt"
    assert _report_valid(base)
