"""Frozen V3 signals on synthetic daily bars; no market data."""

from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms

DAY = 86_400_000
START = month_bounds_ms("2020-01")[0]


def bar(day, close):
    value = Decimal(close)
    return Kline(START + day * DAY, value, value, value, value, Decimal(1), value, Decimal("0.5"))


def test_sma_and_ema_warmup_and_exact_seed():
    from crypto_grid_bot.trend.signals import signal_series

    points = signal_series([bar(i, i + 1) for i in range(55)])
    assert points[48].rule("R1") == 0
    assert points[49].sma50 == Decimal("25.5")
    assert points[49].rule("R1") == 1
    assert points[53].rule("R2") == 0
    assert points[54].ema21 == 45
    assert points[54].ema55 == 28
    assert points[54].rule("R2") == 1


def test_seeded_ema_updates_after_shock_and_ignores_caller_context():
    from crypto_grid_bot.trend.signals import signal_series

    bars = [bar(i, i + 1) for i in range(55)] + [bar(55, 155)]
    expected = signal_series(bars)
    assert expected[-1].ema21 == 55
    assert expected[-1].ema55 == Decimal(
        "32.5357142857142857142857142857142857142857142857142857142857"
    )
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        assert signal_series(bars) == expected


def test_constant_price_ties_are_flat_for_sma_and_ema():
    from crypto_grid_bot.trend.signals import signal_series

    point = signal_series([bar(i, 10) for i in range(60)])[-1]
    assert point.rule("R1") == point.rule("R2") == 0
    with pytest.raises(ValueError):
        point.rule("R7")


def test_bad_daily_bar_is_rejected_before_mutating_state():
    from dataclasses import replace

    from crypto_grid_bot.trend.signals import SignalState

    state = SignalState()
    state.update(bar(0, 10))
    for invalid in (
        bar(0, 11),
        bar(-1, 11),
        replace(bar(1, 11), high=Decimal(1)),
        replace(bar(1, 11), open_ms=START + DAY + 1),
        bar(1, "NaN"),
        bar(1, "1e19"),
        bar(1, "0.0000000000000000001"),
    ):
        with pytest.raises(ValueError):
            state.update(invalid)
    assert state.update(bar(1, 11)).day_ms == START + DAY


def test_donchian_strict_breakout_reversal_and_gap_continuity():
    from crypto_grid_bot.trend.signals import signal_series

    points = signal_series([bar(i, 10) for i in range(55)] + [bar(55, 11), bar(70, 10), bar(71, 9)])
    assert points[54].rule("R3") == 0
    assert [point.rule("R3") for point in points[-3:]] == [1, 1, -1]


@pytest.mark.parametrize("old,breakout,exit_close,held", [(1, 11, 5, 1), (20, 9, 15, -1)])
def test_donchian_twenty_bar_exit_without_fifty_five_bar_reversal(old, breakout, exit_close, held):
    from crypto_grid_bot.trend.signals import signal_series

    points = signal_series(
        [bar(i, old if i < 35 else 10) for i in range(55)]
        + [bar(55, breakout), bar(56, exit_close)]
    )
    assert points[-2].rule("R3") == held
    assert points[-1].rule("R3") == 0


def test_momentum_uses_calendar_date_with_seven_day_tolerance():
    from crypto_grid_bot.trend.signals import signal_series

    points = signal_series([bar(0, 10), bar(364, 11), bar(365, 11), bar(372, 9), bar(373, 20)])
    assert [point.rule("R4") for point in points] == [0, 0, 1, -1, 0]


def ranged_bar(day, close, high, low):
    from dataclasses import replace

    return replace(bar(day, close), high=Decimal(high), low=Decimal(low))


def test_supertrend_seed_wilder_update_and_two_strict_flips():
    from crypto_grid_bot.trend.signals import signal_series

    bars = [ranged_bar(i, 10, 11, 9) for i in range(11)]
    points = signal_series(bars + [ranged_bar(20, 3, 4, 2), ranged_bar(21, 12, 13, 11)])
    assert points[9].rule("R5") == 0
    assert (points[10].atr10, points[10].upper, points[10].lower, points[10].rule("R5")) == (
        2,
        16,
        4,
        1,
    )
    assert (points[11].atr10, points[11].upper, points[11].lower, points[11].rule("R5")) == (
        Decimal("2.6"),
        Decimal("10.8"),
        4,
        -1,
    )
    assert (points[12].atr10, points[12].upper, points[12].lower, points[12].rule("R5")) == (
        Decimal("3.34"),
        Decimal("10.8"),
        Decimal("1.98"),
        1,
    )
    contiguous = signal_series(bars + [ranged_bar(11, 3, 4, 2), ranged_bar(12, 12, 13, 11)])
    assert points[-1].directional == contiguous[-1].directional
    assert points[-1].atr10 == contiguous[-1].atr10


def test_supertrend_seed_down_and_equality_does_not_flip():
    from crypto_grid_bot.trend.signals import signal_series

    down = signal_series([ranged_bar(i, 9, 11, 9) for i in range(11)])[-1]
    assert down.rule("R5") == -1
    tied = signal_series([ranged_bar(i, 10, 11, 9) for i in range(11)] + [bar(11, 4)])[-1]
    assert tied.lower == 4
    assert tied.rule("R5") == 1


def test_blend_counts_warming_rules_and_long_only_clips_after_averaging():
    from crypto_grid_bot.trend.signals import signal_series

    warm = signal_series([bar(i, 10) for i in range(11)])[-1]
    assert warm.rule("R6") == Decimal("0.2")
    point = signal_series([bar(i, i + 1) for i in range(55)] + [bar(55, "0.5")])[-1]
    assert point.rule("R6") == Decimal("-0.4")
    assert point.rule("R6L") == 0
    assert point.rule("R2L") == 1
    assert sum(point.rule(f"R{i}L") for i in range(1, 6)) > 0


def test_series_is_prefix_stable_and_all_recursive_state_survives_gap():
    from crypto_grid_bot.trend.signals import signal_series

    bars = [bar(i, 10 + i % 13) for i in range(80)]
    full = signal_series(bars)
    assert signal_series(bars[:60]) == full[:60]
    gapped = signal_series([bar(i if i < 60 else i + 10, 10 + i % 13) for i in range(80)])
    assert full[-1].directional == gapped[-1].directional
    assert full[-1].ema21 == gapped[-1].ema21
    assert full[-1].ema55 == gapped[-1].ema55
    assert full[-1].atr10 == gapped[-1].atr10
    assert full[-1].upper == gapped[-1].upper
    assert full[-1].lower == gapped[-1].lower


def test_reserved_daily_date_is_rejected_and_all_twelve_rule_names_exist():
    from dataclasses import replace

    from crypto_grid_bot.trend.signals import RULES, SignalState

    state = SignalState()
    with pytest.raises(ValueError):
        state.update(replace(bar(0, 10), open_ms=month_bounds_ms("2025-01")[0]))
    point = state.update(bar(0, 10))
    assert len(RULES) == 12
    assert all(point.rule(name) == 0 for name in RULES)
