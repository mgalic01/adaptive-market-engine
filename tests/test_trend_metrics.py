"""Hand-computed evaluation examples, not strategy performance claims."""

from decimal import Decimal as D

import pytest


def test_profit_factor_zero_and_infinite_boundaries():
    from crypto_grid_bot.trend.metrics import profit_factor

    assert profit_factor([D(2), D(-1), D(0)]) == 2
    assert profit_factor([D(1), D(0)]) == D("Infinity")
    assert profit_factor([D(0)]) == 0
    assert profit_factor([D(-1)]) == 0


def test_sharpe_uses_sample_deviation_and_zero_variance_rule():
    from crypto_grid_bot.trend.metrics import sharpe

    assert sharpe([D(".1"), D("-.1")]) == 0
    assert sharpe([D(".1"), D(".1")]) == 0
    assert sharpe([D(".1")]) == 0
    assert D("40.52") < sharpe([D(".1"), D(".2")]) < D("40.53")


def test_drawdown_tracks_true_peak_and_allows_negative_terminal_equity():
    from crypto_grid_bot.trend.metrics import maximum_drawdown

    assert maximum_drawdown([D(100), D(120), D(90), D(110)]) == D(".25")
    assert maximum_drawdown([D(100), D(-10)]) == D("1.1")


def test_nonfinite_metrics_are_rejected():
    from crypto_grid_bot.trend.metrics import profit_factor

    with pytest.raises(ValueError):
        profit_factor([D("NaN")])


def test_sample_returns_and_cagr_use_exact_elapsed_time():
    from crypto_grid_bot.trend.metrics import cagr, sample_returns

    year_ms = 31557600000  # 365.25 days
    samples = [(0, D(100)), (year_ms // 2, D(110)), (year_ms, D(121))]
    assert sample_returns(samples) == (D(".1"), D(".1"))
    assert cagr(samples) == D(".21")
    assert cagr([(0, D(100)), (year_ms, D(-1))]) == -1


def test_calmar_boundaries():
    from crypto_grid_bot.trend.metrics import calmar

    assert calmar(D(".2"), D(".1")) == 2
    assert calmar(D(".2"), D(0)) == D("Infinity")
    assert calmar(D("-.2"), D(0)) == 0


def test_duplicate_sample_time_is_invalid():
    from crypto_grid_bot.trend.metrics import sample_returns

    with pytest.raises(ValueError):
        sample_returns([(0, D(100)), (0, D(101))])


def test_summary_keeps_trade_and_daily_profit_factors_separate():
    from crypto_grid_bot.trend.metrics import summarize

    result = summarize(
        [(0, D(100)), (86400000, D(110)), (172800000, D(105))],
        [D(100), D(120), D(105)],
        [D(20), D(-15), D(0)],
    )
    assert result.net_pnl == 5
    assert result.trade_count == 3
    assert result.wins == 1
    assert result.losses == 1
    assert result.daily_profit_factor == 2
    assert D("1.33") < result.trade_profit_factor < D("1.34")
    assert result.max_drawdown == D(".125")


def test_summary_requires_path_to_end_at_terminal_equity():
    from crypto_grid_bot.trend.metrics import summarize

    with pytest.raises(ValueError, match="terminal"):
        summarize([(0, D(100)), (86400000, D(105))], [D(100), D(99)], [])


def test_summary_rejects_missing_trade_results():
    from crypto_grid_bot.trend.metrics import summarize

    with pytest.raises(ValueError, match="reconcile"):
        summarize([(0, D(100)), (86400000, D(105))], [D(100), D(105)], [])


def test_finished_runner_to_summary_includes_censored_trade_costs():
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.metrics import summarize_runner
    from crypto_grid_bot.trend.runner import TrendRunner

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    r = TrendRunner({"BTCUSDT": rules}, multiple=1)
    start, hour = 1609459200000, 3600000
    bar = {"BTCUSDT": (D(100), D(99), D(101))}
    r.step(start, bar, {"BTCUSDT": D(".1")}, {})
    r.step(start + hour, bar, {}, {})
    with pytest.raises(ValueError, match="finished"):
        summarize_runner(r)
    r.finish({"BTCUSDT": D(100)})
    summary = summarize_runner(r)
    assert summary.net_pnl == D("-1.00025")
    assert summary.trade_count == 1
    assert summary.losses == 1
    assert summary.trade_profit_factor == 0


def test_summary_rejects_mismatched_initial_equity_even_when_trades_reconcile():
    from crypto_grid_bot.trend.metrics import summarize

    with pytest.raises(ValueError, match="initial"):
        summarize([(0, D(100)), (86400000, D(110))], [D(90), D(110)], [D(20)])


@pytest.mark.parametrize("bad_quantity", [False, True])
def test_runner_summary_accepts_equity_tolerance_without_calling_it_exact(bad_quantity):
    from crypto_grid_bot.trend.account import AccountingAudit
    from crypto_grid_bot.trend.metrics import summarize_runner
    from crypto_grid_bot.trend.runner import TrendRunner

    runner = TrendRunner({})
    runner.step(1609459200000, {}, {}, {})
    runner.step(1609462800000, {}, {}, {})
    runner.finish({})
    evidence = AccountingAudit(D(0), {}, D("-1e-59"))
    runner.audits.append(evidence)
    assert evidence.accepted and not evidence.exact
    assert summarize_runner(runner).net_pnl == 0
    assert runner.audits[-1].equity_residual == D("-1e-59")
    runner.audits.append(
        AccountingAudit(D(0), {"BTCUSDT": D("1e-59")}, D(0))
        if bad_quantity
        else AccountingAudit(D("1e-59"), {}, D(0))
    )
    with pytest.raises(ValueError, match="accounting"):
        summarize_runner(runner)


def test_real_round_trip_retains_accepted_trade_residual():
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.metrics import summarize_runner
    from crypto_grid_bot.trend.runner import TrendRunner

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = TrendRunner({"BTCUSDT": rules})
    start = 1609459200000
    for hour in range(50):
        price = D(1 if hour < 24 else 2)
        targets = (
            {"BTCUSDT": D(".1" if hour == 0 else ".2" if hour == 24 else "0")}
            if hour in (0, 24, 48)
            else {}
        )
        runner.step(
            start + hour * 3600000,
            {"BTCUSDT": (price, price, price)},
            targets,
            {},
            exit_reasons={"BTCUSDT": frozenset({"signal_zero" if hour == 48 else "sizing"})},
        )
    runner.finish({"BTCUSDT": D(2)})
    assert all(a.accepted for a in runner.audits)
    assert any(a.equity_residual == D("-5e-57") for a in runner.audits)
    assert len(runner.lifecycles.completed) == 1
    assert not runner.lifecycles.completed[0].censored
    from decimal import Context, localcontext

    with localcontext(Context(prec=60)):
        trade_total = sum((life.net for life in runner.lifecycles.completed), D(0))
        account_profit = runner.daily_samples[-1][1] - runner.daily_samples[0][1]
        assert trade_total - account_profit == D("5e-57")
    assert summarize_runner(runner).trade_reconciliation_residual == D("5e-57")


@pytest.mark.parametrize("residual", [D("1e-18"), D("-1e-18"), D(0)])
def test_trade_reconciliation_accepts_inclusive_bound_and_reports_residual(residual):
    from crypto_grid_bot.trend.metrics import summarize

    result = summarize([(0, D(100)), (86400000, D(100))], [D(100), D(100)], [residual])
    assert result.trade_reconciliation_residual == residual


@pytest.mark.parametrize(
    "residual", [D("1.00000000000000000001e-18"), D("-1.00000000000000000001e-18")]
)
def test_trade_reconciliation_rejects_outside_bound(residual):
    from crypto_grid_bot.trend.metrics import summarize

    with pytest.raises(ValueError, match="reconcile"):
        summarize([(0, D(100)), (86400000, D(100))], [D(100), D(100)], [residual])
