import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import replay_window

T, DAY = 1609459200000, 86400000


def completed():
    return replay_window(DailyDecisions({}, {}), {}, {}, {}, T, T + 2 * DAY, {T: None})


def test_assembled_report_uses_actual_replay_and_exact_json():
    from crypto_grid_bot.trend.run_report import build_futures_report, report_json

    report = build_futures_report(completed())
    assert report.reason is None
    assert report.performance.net_pnl == 0
    assert report.costs.fill_count == report.trades.total.count == 0
    assert report.caps.decision_days == 2
    assert report.exposure.observed_hours == 48
    assert report.monthly.mean_return == report.realized_volatility == 0
    assert report.target_volatility == D(".4")
    assert report.reconciliation_residual == 0
    assert report.worst_drawdown is None
    value = json.loads(report_json(report))
    assert value["performance"]["net_pnl"] == "0"
    assert value["trades"]["by_coin_side"] == []
    assert "verdict" not in value


def test_report_rejects_unknown_outcomes_and_missing_daily_evidence():
    from crypto_grid_bot.trend.run_report import build_futures_report

    result = completed()
    with pytest.raises(ValueError):
        build_futures_report(replace(result, reason="engine_failure"))
    with pytest.raises(ValueError, match="decision"):
        build_futures_report(replace(result, daily_decisions=result.daily_decisions[:-1]))


def test_report_json_retains_legitimate_infinity_but_refuses_nan():
    from crypto_grid_bot.trend.run_report import build_futures_report, report_json

    report = build_futures_report(completed())
    value = replace(report, performance=replace(report.performance, calmar=D("Infinity")))
    assert json.loads(report_json(value))["performance"]["calmar"] == "Infinity"
    with pytest.raises(ValueError):
        report_json(replace(report, realized_volatility=D("NaN")))


def test_liquidation_retains_diagnostics_without_completed_metrics_and_corruption_aborts():
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.replay import ReplayResult
    from crypto_grid_bot.trend.run_report import build_futures_report, report_json
    from crypto_grid_bot.trend.runner import TrendRunner

    filters = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = TrendRunner({"BTCUSDT": filters})
    runner.account.fill("BTCUSDT", OrderIntent(D(10), False), D(100), T)
    runner.step(T, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {})
    runner.step(
        T + 3600000, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {T + 3600000: {"BTCUSDT": D(100)}}
    )
    decision = DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"}).at(T, "R1")
    result = ReplayResult(runner, "liquidation", (), daily_decisions=((T, "R1", decision),))
    report = build_futures_report(result)
    assert report.reason == "liquidation"
    assert report.performance is report.monthly is report.realized_volatility is None
    assert report.trades.total.count == report.trades.total.censored_count == 1
    assert report.costs.funding_paid == 100000
    assert report.worst_drawdown.fraction > 1
    assert json.loads(report_json(report))["trades"]["by_coin_side"][1]["side"] == "short"
    runner.lifecycles.completed[0].fees += D(1)
    with pytest.raises(ValueError, match="reconcile"):
        build_futures_report(result)
