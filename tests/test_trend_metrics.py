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
