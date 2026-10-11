"""Outcomes carry exactly their report's figures, so acceptance can match them."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
from test_combined_baseline_hold import hold

from crypto_grid_bot.combined.experiment import RunIdentity, _report_valid
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.combined.outcomes import baseline_outcome, strategy_outcome
from crypto_grid_bot.combined.replay_records import strategy_report
from crypto_grid_bot.combined.strategy_replay import replay_strategy


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
    assert _report_valid(row)
