"""Walk-forward orchestration with synthetic flat data, no market sources."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend import orchestration as orchestration
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import ReplayResult


def test_invalid_outcome_without_account_evidence_is_rejected():
    with pytest.raises(ValueError, match="account evidence"):
        orchestration.reconcile_replay(ReplayResult(None, "unavailable_exclusion_close", ()))


def missing_close_result():
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.replay import replay_window

    t, day, hour = 1577836800000, 86400000, 3600000
    start = t + 89 * day

    def bar(stamp, price):
        p = D(price)
        return Kline(stamp, p, p, p, p, D(1), p, D(".5"))

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    book = DailyDecisions(
        {"BTCUSDT": [bar(t + i * day, 100 + i * 2 + i % 3) for i in range(90)]},
        {"BTCUSDT": "2020-01"},
        {"BTCUSDT": frozenset({"2020-04"})},
    )
    result = replay_window(
        book,
        {"BTCUSDT": rules},
        {"BTCUSDT": [bar(start + i * hour, 100) for i in range(24)]},
        {},
        start,
        start + 3 * day,
        {start: "R1"},
    )
    return result


def test_missing_close_terminal_is_reconciled_before_invalid_classification():
    result = missing_close_result()
    checked = orchestration.reconcile_replay(result)
    assert checked.reason == "unavailable_exclusion_close"
    assert abs(checked.trade_reconciliation_residual) <= D("1e-18")
    result.runner.lifecycles.completed[0].fees += 1
    with pytest.raises(ValueError, match="reconcile"):
        orchestration.reconcile_replay(result)


def test_cancelled_replay_already_has_persisted_start_identity(monkeypatch):
    records = []

    def cancelled(*args, **kwargs):
        assert len(records) == 1
        assert records[0].state == "started"
        assert records[0].run_id
        assert records[0].pick_schedule == ((args[4], args[6][args[4]]),)
        raise KeyboardInterrupt()

    monkeypatch.setattr(orchestration, "replay_window", cancelled)
    with pytest.raises(KeyboardInterrupt):
        orchestration.run_walk_forward(
            DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2023-04"}),
            {},
            {},
            {},
            record=records.append,
        )


def test_cancelled_sensitivity_start_retains_entire_pick_schedule(monkeypatch):
    records = []
    start, day = 1609459200000, 86400000
    picks = {start: "R1", start + day: None}

    def cancelled(*args, **kwargs):
        assert records[0].pick_schedule == tuple(sorted(picks.items()))
        raise KeyboardInterrupt()

    monkeypatch.setattr(orchestration, "replay_window", cancelled)
    with pytest.raises(KeyboardInterrupt):
        orchestration.replay_sensitivities(
            DailyDecisions({}, {}), {}, {}, {}, picks, start + 2 * day, record=records.append
        )


def test_invalid_run_lifecycle_corruption_is_engine_failure(monkeypatch):
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    r = TrendRunner({"BTCUSDT": rules})
    t = 1609459200000
    r.account.fill("BTCUSDT", OrderIntent(D(10), False), D(100), t)
    r.step(t, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {})
    r.step(
        t + 3600000, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {t + 3600000: {"BTCUSDT": D(100)}}
    )
    assert r.stopped == "liquidation"
    r.lifecycles.completed[0].fees += D(1)
    monkeypatch.setattr(
        orchestration, "replay_window", lambda *a, **k: ReplayResult(r, "liquidation", ())
    )
    records = []
    with pytest.raises(ValueError, match="reconcile"):
        orchestration.replay_sensitivities(
            DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"}),
            {},
            {},
            {},
            {t: "R1"},
            t + 86400000,
            record=records.append,
        )
    assert len(records) == 2
    assert "reconcile" in records[-1].error


def test_sensitivity_menu_uses_identical_picks_and_records_invalid_outcomes(monkeypatch):
    calls, records = [], []

    def run(*args, **kwargs):
        calls.append((dict(args[6]), kwargs))
        return missing_close_result()

    monkeypatch.setattr(orchestration, "replay_window", run)
    picks = {1609459200000: "R1", 1617235200000: "R2L"}
    results = orchestration.replay_sensitivities(
        DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"}),
        {},
        {},
        {},
        picks,
        1640995200000,
        record=records.append,
    )
    assert list(results) == [(1, 1), (3, 1), (1, 2), (2, 2), (3, 2)]
    assert all(p == picks for p, _ in calls)
    assert [(k["multiple"], k["cost_multiple"]) for _, k in calls] == list(results)
    assert len({r.run_id for r in records}) == 5
    assert [(r.multiple, r.cost_multiple) for r in records if r.state == "finished"] == list(
        results
    )
    assert all(
        r.result.reason == "unavailable_exclusion_close" for r in records if r.state == "finished"
    )


def test_sensitivity_engine_error_aborts_remaining_scenarios(monkeypatch):
    records = []

    def broken(*args, **kwargs):
        raise ArithmeticError("bad ledger")

    monkeypatch.setattr(orchestration, "replay_window", broken)
    with pytest.raises(ArithmeticError, match="bad ledger"):
        orchestration.replay_sensitivities(
            DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"}),
            {},
            {},
            {},
            {1609459200000: "R1"},
            1640995200000,
            record=records.append,
        )
    assert len(records) == 2
    assert records[-1].error == "ArithmeticError: bad ledger"


def test_sensitivities_create_five_independent_accounts_on_synthetic_day():
    from crypto_grid_bot.trend.filters import OrderFilters

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    records = []
    result = orchestration.replay_sensitivities(
        DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"}),
        {"BTCUSDT": rules},
        {"BTCUSDT": []},
        {},
        {1609459200000: None},
        1609545600000,
        record=records.append,
    )
    assert len({id(row.runner.account) for row in result.values()}) == 5
    assert all(row.runner.stopped == "completed" for row in result.values())
    assert all(row.runner.account.wallet == 10000 for row in result.values())


def test_all_invalid_candidates_are_recorded_and_choose_flat(monkeypatch):
    records = []
    calls = []

    def invalid(*args, **kwargs):
        calls.append(args[6])
        return missing_close_result()

    monkeypatch.setattr(orchestration, "replay_window", invalid)
    result = orchestration.run_walk_forward(
        DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2023-04"}),
        {},
        {},
        {},
        record=records.append,
    )
    assert len(records) == 26
    assert all(row.sharpe is None for row in result.training)
    assert all(row.invalid_reason == "unavailable_exclusion_close" for row in result.training)
    assert set(result.picks.values()) == {None}
    assert calls[-1] == result.picks
    assert records[-2].state == "started"
    assert (
        records[-2].pick_schedule
        == records[-1].pick_schedule
        == tuple(sorted(result.picks.items()))
    )


def test_engine_error_is_recorded_and_aborts_instead_of_selecting_another_rule(monkeypatch):
    records = []

    def broken(*args, **kwargs):
        raise ArithmeticError("audit failed")

    monkeypatch.setattr(orchestration, "replay_window", broken)
    with pytest.raises(ArithmeticError, match="audit failed"):
        orchestration.run_walk_forward(
            DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2023-04"}),
            {},
            {},
            {},
            record=records.append,
        )
    assert len(records) == 2
    assert records[-1].rule == "R1"
    assert records[-1].error == "ArithmeticError: audit failed"


def test_failed_evidence_recording_stops_after_first_attempt(monkeypatch):
    calls = []

    def invalid(*args, **kwargs):
        calls.append(args)
        return missing_close_result()

    def cannot_save(attempt):
        raise OSError("disk full")

    monkeypatch.setattr(orchestration, "replay_window", invalid)
    with pytest.raises(OSError, match="disk full"):
        orchestration.run_walk_forward(
            DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2023-04"}),
            {},
            {},
            {},
            record=cannot_save,
        )
    assert len(calls) == 0


def test_frozen_training_menu_then_one_continuous_oos_account():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.orchestration import run_walk_forward

    filters = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    book = DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2023-04"})
    records = []

    def record(attempt):
        if attempt.state == "started":
            return
        assert attempt.error is None
        assert attempt.result.runner.account.initial == 10000
        assert attempt.result.runner.stopped == "completed"
        records.append((attempt.run_id, attempt.phase, attempt.rule))

    result = run_walk_forward(book, {"BTCUSDT": filters}, {"BTCUSDT": []}, {}, record=record)
    assert len(result.training) == 12
    assert [row.rule for row in result.training] == [
        f"R{i}{suffix}" for suffix in ("", "L") for i in range(1, 7)
    ]
    assert len(result.picks) == 1
    assert set(result.picks.values()) == {"R1"}
    assert len(records) == 13
    assert len({row[0] for row in records}) == 13
    assert records[-1][1] == "out_of_sample"
    assert result.out_of_sample.runner.account.wallet == 10000
