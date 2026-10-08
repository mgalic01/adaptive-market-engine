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
