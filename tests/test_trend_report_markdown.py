from dataclasses import replace
from decimal import Decimal as D

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.trend.run_report import build_futures_report


def report():
    start, day = 1609459200000, 86400000
    return build_futures_report(
        replay_window(DailyDecisions({}, {}), {}, {}, {}, start, start + 2 * day, {start: None})
    )


def test_readable_report_includes_units_months_and_scope():
    from crypto_grid_bot.trend.report_markdown import report_markdown

    text = report_markdown(report())
    assert "Account status: completed" in text
    assert "Experiment verdict: not evaluated" in text
    assert "2021-01" in text
    assert "USDT" in text
    assert "Sharpe" in text
    assert "No lifecycles" in text
    assert "Not reachable" in text
    assert "Signed reconciliation residual: `0` USDT" in text


def test_invalid_report_never_displays_completed_metrics_or_hides_reason():
    from crypto_grid_bot.trend.report_markdown import report_markdown

    value = replace(
        report(), reason="liquidation", performance=None, monthly=None, realized_volatility=None
    )
    text = report_markdown(value)
    assert "Account status: invalid (liquidation)" in text
    assert "Completed-run metrics unavailable" in text
    assert "Monthly results unavailable" in text
    assert "Sharpe | 0" not in text


def test_infinity_and_exact_tiny_residual_are_not_lost_to_display_rounding():
    from crypto_grid_bot.trend.report_markdown import report_markdown

    value = report()
    value = replace(
        value,
        performance=replace(value.performance, calmar=D("Infinity")),
        reconciliation_residual=D("5e-57"),
    )
    text = report_markdown(value)
    assert "Calmar | +Infinity" in text
    assert "`5E-57` USDT" in text


def test_coin_table_escapes_text_and_drawdown_keeps_same_hour_indices():
    from crypto_grid_bot.trend.report_markdown import report_markdown
    from crypto_grid_bot.trend.risk_diagnostics import DrawdownEpisode

    value = report()
    trades = replace(value.trades, by_coin_side={("BTC|<x>\n", "long"): value.trades.total})
    episode = DrawdownEpisode(D(".25"), 1609459200000, 1609459200000, 1, 2, "favourable", "adverse")
    text = report_markdown(replace(value, trades=trades, worst_drawdown=episode))
    assert "BTC&#124;&lt;x&gt; " in text
    assert "Worst drawdown: 25%" in text
    assert "favourable, index 1" in text
    assert "adverse, index 2" in text
