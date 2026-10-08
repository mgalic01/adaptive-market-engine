"""Output-only entry diagnostics, with synthetic quotes and no market data."""

import json
from decimal import Decimal as D

from test_mode_switch_runner import Run, at, frame, grid

from crypto_grid_bot.domain import RiskAction
from crypto_grid_bot.strategy.mode_selector import Mode


def test_selected_entry_records_fill_and_context():
    run = Run()
    report = run.step(frame(at(1, 10)))
    entry = report["uptrend_entry"]
    assert entry["selected"] is True
    assert entry["outcome"] == "filled"
    assert entry["blockers"] == []
    assert entry["filled_quantity"] == D("0.599")
    assert entry["stop"] == D(97)


def test_selected_entry_records_invalid_stop_without_buying():
    run = Run()
    report = run.step(frame(at(1, 10), ask="96"))
    assert report["uptrend_entry"]["outcome"] == "blocked"
    assert "invalid_stop" in report["uptrend_entry"]["blockers"]
    assert not report["fills"]


def test_depth_wait_and_continuation_are_not_extra_selections():
    run = Run()
    first = run.step(frame(at(1, 10), ask_size="0"))
    second = run.step(frame(at(1, 10, 1)))
    assert first["uptrend_entry"]["outcome"] == "depth"
    assert first["uptrend_entry"]["selected"] is True
    assert second["uptrend_entry"]["outcome"] == "filled"
    assert second["uptrend_entry"]["selected"] is False


def test_budget_end_is_reported_separately_from_selection():
    run = Run()
    run.step(frame(at(1, 10)))
    report = run.step(frame(at(1, 10, 1)))
    assert report["uptrend_entry"]["outcome"] == "budget"
    assert report["uptrend_entry"]["selected"] is False


def test_collector_separates_selections_from_continuations_and_copies_records():
    from crypto_grid_bot.backtest.attribution import EntryAttribution

    run = Run()
    collector = EntryAttribution()
    reports = [
        run.step(frame(at(1, 10), ask_size="0")),
        run.step(frame(at(1, 10, 1))),
        run.step(frame(at(1, 10, 2))),
    ]
    for report in reports:
        collector.record(report)
    collector.record({})  # legacy output, or an unrelated frame
    reports[0]["uptrend_entry"]["blockers"].append("mutated")
    result = collector.report()
    assert result["selected"] == 1
    assert result["selected_outcomes"] == {"depth": 1}
    assert result["continuation_outcomes"] == {"budget": 1, "filled": 1}
    assert result["records"][0]["blockers"] == []
    assert result["records"][0]["filled_quantity"] == "0"
    assert json.loads(json.dumps(result)) == result


def test_replay_exports_entry_records():
    from test_mode_switch_replay import rising_run

    _, _, _, row, steps = rising_run()
    records = [s.report["uptrend_entry"] for s in steps if "uptrend_entry" in s.report]
    assert row["modes"]["entries"]["selected"] == sum(r["selected"] for r in records)
    assert row["modes"]["entries"]["selected"] > 0


def test_independent_risk_recovery_and_inventory_blockers_are_preserved():
    run = Run()
    grid(run, buy=False)
    run.forced = [RiskAction.REDUCE]
    report = run.step(frame(at(1, 10)))
    assert report["uptrend_entry"]["blockers"] == ["risk_action", "risk_recovery", "not_flat"]


def test_recovery_completed_on_selection_frame_does_not_report_a_block():
    run = Run()
    run.account.risk_recovery = True
    run.account.risk_recovery_count = run.sim.policy.recovery_frames - 1
    report = run.step(frame(at(1, 10)))
    assert report["uptrend_entry"]["blockers"] == []
    assert report["uptrend_entry"]["outcome"] == "filled"


def test_entry_records_include_execution_limits():
    run = Run()
    report = run.step(frame(at(1, 10)))
    entry = report["uptrend_entry"]
    assert entry["cash_left"] == D(60)
    assert entry["risk_left"] == D(4)
    assert entry["minimum_notional"] == D(5)
    assert entry["daily_rsi"] == D(60)


def test_partial_fills_and_repeated_waits_keep_one_selected_opportunity():
    from crypto_grid_bot.backtest.attribution import EntryAttribution

    run = Run()
    collector = EntryAttribution()
    for minute, depth in enumerate(("0", "0", "1", "1", "100", "100")):
        collector.record(run.step(frame(at(1, 10, minute), ask_size=depth)))
    result = collector.report()
    assert result["selected"] == 1
    assert result["selected_outcomes"] == {"depth": 1}
    assert result["continuation_outcomes"] == {"budget": 1, "depth": 1, "filled": 3}
    assert run.account.uptrend.quantity == D("0.599")


def test_selected_minimum_budget_refusal_has_no_fill():
    run = Run()
    run.account.cash = D(1)
    run.account.day_start = run.account.risk_high = run.account.measure_high = D(1)
    run.account.last_equity = D(1)
    report = run.step(frame(at(1, 10)))
    assert report["uptrend_entry"]["outcome"] == "budget"
    assert report["uptrend_entry"]["selected"] is True
    assert report["uptrend_entry"]["filled_quantity"] == 0
    assert run.account.uptrend is None


def test_reporting_flatness_cannot_clear_fragments_behind_a_risk_refusal():
    run = Run()
    run.account.flow_fragments = {D(101): D("0.01")}
    run.account.inventory = D("0.01")
    run.account.flow_block = False
    report = {"fills": []}
    run.sim._uptrend_step(
        run.account, frame(at(1, 10)), RiskAction.REDUCE, report, decided=Mode.UPTREND
    )
    # The original risk gate short-circuits before _flat, which would clear these.
    assert run.account.flow_fragments == {D(101): D("0.01")}
    assert report["uptrend_entry"]["blockers"] == ["risk_action"]
