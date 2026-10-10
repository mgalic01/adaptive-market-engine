from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.decisions import DailyDecision
from crypto_grid_bot.trend.runner import EquityState
from crypto_grid_bot.trend.sizing import SizingResult


def test_worst_episode_preserves_same_hour_order_and_first_tied_trough():
    from crypto_grid_bot.trend.risk_diagnostics import worst_drawdown

    path = [
        EquityState(t, kind, D(e), D(0), D(0))
        for t, kind, e in (
            (0, "open", 100),
            (1, "favourable", 120),
            (1, "adverse", 90),
            (2, "open", 120),
            (3, "adverse", 90),
        )
    ]
    result = worst_drawdown(path)
    assert result.fraction == D(".25")
    assert (result.peak_index, result.trough_index) == (1, 2)
    assert result.peak_ms == result.trough_ms == 1
    assert (result.peak_kind, result.trough_kind) == ("favourable", "adverse")
    assert worst_drawdown(path[:1]) is None


def test_drawdown_rejects_missing_or_unordered_path():
    from crypto_grid_bot.trend.risk_diagnostics import worst_drawdown

    with pytest.raises(ValueError):
        worst_drawdown([])
    with pytest.raises(ValueError):
        worst_drawdown([EquityState(t, "open", D(100), D(100), D(0)) for t in (2, 1)])


def test_realized_volatility_uses_sample_deviation_and_frozen_annualization():
    from crypto_grid_bot.trend.risk_diagnostics import realized_volatility

    assert realized_volatility([]) is None
    assert realized_volatility([D(1)]) is None
    assert realized_volatility([D(1), D(1)]) == 0
    value = realized_volatility([D("-.1"), D(".1")])
    assert abs(value * value - D("7.3")) < D("1e-25")


def decision(caps):
    sizing = SizingResult(
        {"BTCUSDT": D(0)}, {}, {}, (), D(0), "flat", binding_caps={"BTCUSDT": frozenset(caps)}
    )
    return DailyDecision({"BTCUSDT": D(0)}, {}, {}, sizing)


def test_cap_share_counts_flat_days_and_each_day_once():
    from crypto_grid_bot.trend.risk_diagnostics import cap_diagnostics

    result = cap_diagnostics([(0, decision({"coin", "gross"})), (86400000, decision(set()))])
    assert result.decision_days == 2
    assert result.bound_days == 1
    assert result.bound_share == D(".5")
    assert cap_diagnostics([]).bound_share is None


@pytest.mark.parametrize(
    "days",
    [
        [(0, DailyDecision({}, {}, {}, None))],
        [(0, decision(set())), (2 * 86400000, decision(set()))],
        [(0, decision({"unknown"}))],
    ],
)
def test_cap_share_refuses_missing_or_unknown_evidence(days):
    from crypto_grid_bot.trend.risk_diagnostics import cap_diagnostics

    with pytest.raises(ValueError):
        cap_diagnostics(days)


def test_missing_daily_bar_keeps_sizing_universe_even_without_executable_target():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.risk_diagnostics import cap_diagnostics

    stamp = 1609459200000
    book = DailyDecisions({"BTCUSDT": []}, {"BTCUSDT": "2020-01"})
    value = book.at(stamp, "R1")
    assert value.targets == {}
    assert value.sizing.binding_caps == {"BTCUSDT": frozenset()}
    assert cap_diagnostics([(stamp, value)]).bound_share == 0
