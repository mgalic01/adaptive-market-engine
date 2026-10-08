"""Daily decision integration on synthetic spot history."""

from decimal import Decimal as D

from crypto_grid_bot.backtest.klines import Kline

DAY = 86400000
T = 1577836800000


def bars(count):
    result = []
    for i in range(count):
        p = D(100 + i * 2 + i % 3)
        result.append(Kline(T + i * DAY, p, p, p, p, D(1), p, D(".5")))
    return result


def test_sizing_receives_bounded_history_with_identical_sparse_results(monkeypatch):
    from crypto_grid_bot.trend import decisions as module
    from crypto_grid_bot.trend.sizing import daily_returns, size_portfolio

    rows = [row for i, row in enumerate(bars(300)) if i % 17 != 0]
    book = module.DailyDecisions({"BTCUSDT": rows}, {"BTCUSDT": "2020-01"})
    original = module.size_portfolio
    observed = []

    def bounded(signals, returns, day, **kwargs):
        observed.append(len(returns["BTCUSDT"]))
        return original(signals, returns, day, **kwargs)

    monkeypatch.setattr(module, "size_portfolio", bounded)
    result = book.at(T + 300 * DAY, "R1")
    full = size_portfolio(result.signals, {"BTCUSDT": daily_returns(rows)}, T + 299 * DAY)
    assert result.sizing == full
    assert observed == [60]


def test_decision_uses_closed_history_and_does_not_change_with_future_bars():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    a = DailyDecisions({"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"})
    b = DailyDecisions({"BTCUSDT": bars(90)}, {"BTCUSDT": "2020-01"})
    x, y = a.at(T + 65 * DAY, "R1"), b.at(T + 65 * DAY, "R1")
    assert x.targets == y.targets
    assert x.targets["BTCUSDT"] > 0
    assert x.signals["BTCUSDT"] == 1


def test_missing_bar_keeps_signal_but_issues_no_target():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    book = DailyDecisions({"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"})
    decision = book.at(T + 66 * DAY, "R1")
    assert decision.signals["BTCUSDT"] == 1
    assert decision.targets == {}


def test_missing_bar_records_pick_cause_without_issuing_target():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    book = DailyDecisions({"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"})
    decision = book.at(T + 66 * DAY, "R2", pick_changed=True)
    assert decision.targets == {}
    assert decision.exit_reasons.get("BTCUSDT") == frozenset({"pick_change"})


def test_missing_spot_boundary_retains_pick_cause_through_actual_close():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.runner import TrendRunner

    rows = [row for row in bars(67) if row.open_ms != T + 65 * DAY]
    book = DailyDecisions({"BTCUSDT": rows}, {"BTCUSDT": "2020-01"})
    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = TrendRunner({"BTCUSDT": rules})
    start = T + 65 * DAY
    price = {"BTCUSDT": (D(100), D(100), D(100))}
    for hour in range(50):
        stamp = start + hour * 3600000
        targets, reasons = {}, {}
        if hour % 24 == 0:
            decision = book.at(stamp, "R1" if hour == 0 else "R4", pick_changed=hour == 24)
            targets, reasons = decision.targets, decision.exit_reasons
            if hour == 24:
                assert not targets
        runner.step(stamp, price, targets, {}, exit_reasons=reasons)
    assert len(runner.lifecycles.completed) == 1
    assert runner.lifecycles.completed[0].exit_reason == "pick_change"


def test_ineligible_coins_are_absent_and_all_invalid_pick_targets_flat():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    book = DailyDecisions(
        {"BTCUSDT": bars(65), "ETHUSDT": bars(65)}, {"BTCUSDT": "2020-01", "ETHUSDT": "2020-05"}
    )
    decision = book.at(T + 66 * DAY, None, pick_changed=True)
    assert decision.targets == {"BTCUSDT": D(0)}
    assert decision.exit_reasons["BTCUSDT"] == frozenset({"pick_change"})


def test_daily_decision_flows_into_next_hour_runner_fill():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.runner import TrendRunner

    book = DailyDecisions({"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"})
    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = TrendRunner({"BTCUSDT": rules})
    time = T + 65 * DAY
    decision = book.at(time, "R1")
    price = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(time, price, decision.targets, {}, exit_reasons=decision.exit_reasons)
    assert not runner.account.fills
    runner.step(time + 3600000, price, {}, {})
    assert runner.account.positions["BTCUSDT"].quantity > 0
    assert runner.account.fills[0].timestamp_ms == time + 3600000


def test_exclusion_overrides_missing_signal_bar_before_month_start():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    book = DailyDecisions(
        {"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    decision = book.at(T + 90 * DAY, "R1")  # March 31; latest signal bar is in March's first week.
    assert decision.targets == {"BTCUSDT": D(0)}
    assert "excluded_month" in decision.exit_reasons["BTCUSDT"]
    assert decision.signals["BTCUSDT"] == 0
    assert "sizing" not in decision.exit_reasons["BTCUSDT"]


def test_all_invalid_quarter_keeps_pick_change_reason_after_first_day():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    book = DailyDecisions({"BTCUSDT": bars(65)}, {"BTCUSDT": "2020-01"})
    decision = book.at(T + 66 * DAY, None)
    assert decision.exit_reasons["BTCUSDT"] == frozenset({"pick_change"})
