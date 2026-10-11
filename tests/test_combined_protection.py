"""Conservative OHLC protection; no synthetic fills from missing observations."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.protection import initial_protection, manage_completed_bar


def bar(open="100", high="101", low="99", close="100"):
    return Kline(0, D(open), D(high), D(low), D(close), D(1), D(100), D("0.5"))


@pytest.mark.parametrize("side,stop", [(1, "98"), (-1, "102")])
def test_initial_stop_uses_two_completed_atr_and_frozen_state(side, stop):
    state = initial_protection(side, D(100), D(1))
    assert state.initial_stop == state.stop == D(stop)
    assert state.best == state.entry == D(100)
    assert not state.trail_active
    with pytest.raises(FrozenInstanceError):
        state.stop = D(99)


@pytest.mark.parametrize(
    "side,ohlc,target,price",
    [
        (1, bar("100", "107", "97", "106"), "106", "98"),
        (-1, bar("100", "103", "93", "94"), "94", "102"),
    ],
)
def test_existing_adverse_stop_wins_when_target_also_touched(side, ohlc, target, price):
    state = initial_protection(side, D(100), D(1))
    after, exit = manage_completed_bar(state, ohlc, target=D(target), atr=D(1), atr_fresh=True)
    assert after == state
    assert exit.reason == "stop" and exit.price == D(price)


@pytest.mark.parametrize(
    "side,ohlc,price",
    [
        (1, bar("95", "99", "94", "98"), "94.05"),
        (-1, bar("105", "106", "101", "102"), "106.05"),
    ],
)
def test_stop_gap_uses_worse_open_with_adverse_slippage(side, ohlc, price):
    state = initial_protection(side, D(100), D(1))
    _, exit = manage_completed_bar(state, ohlc, slippage=D("0.01"))
    assert exit.reason == "stop" and exit.price == D(price)


@pytest.mark.parametrize(
    "side,ohlc,target,price",
    [
        (1, bar("100", "103", "99", "102"), "102", "100.98"),
        (-1, bar("100", "101", "97", "98"), "98", "98.98"),
    ],
)
def test_target_fill_is_conservative_and_slipped_adversely(side, ohlc, target, price):
    state = initial_protection(side, D(100), D(1))
    _, exit = manage_completed_bar(state, ohlc, target=D(target), slippage=D("0.01"))
    assert exit.reason == "target" and exit.price == D(price)


@pytest.mark.parametrize(
    "side,ohlc,best,stop",
    [
        (1, bar("100", "104", "99", "103"), "104", "101"),
        (-1, bar("100", "101", "96", "97"), "96", "99"),
    ],
)
def test_trail_activates_at_exact_two_initial_r_only_after_old_stop_check(side, ohlc, best, stop):
    state = initial_protection(side, D(100), D(1))
    after, exit = manage_completed_bar(state, ohlc, atr=D(1), atr_fresh=True)
    assert exit is None  # low/high crossed NEW stop, but it did not exist intrabar
    assert after.trail_active and after.best == D(best) and after.stop == D(stop)
    assert after.initial_stop == state.initial_stop


@pytest.mark.parametrize(
    "side,ohlc",
    [
        (1, bar("100", "103.99", "99", "103")),
        (-1, bar("100", "101", "96.01", "97")),
    ],
)
def test_below_two_r_never_activates_trail(side, ohlc):
    state = initial_protection(side, D(100), D(1))
    after, exit = manage_completed_bar(state, ohlc, atr=D("0.1"), atr_fresh=True)
    assert exit is None and after.stop == state.stop and not after.trail_active


@pytest.mark.parametrize(
    "side,ohlc,price",
    [
        (1, bar("100", "106", "99", "102"), "100.98"),
        (-1, bar("100", "101", "94", "98"), "98.98"),
    ],
)
def test_new_trail_crossed_at_completion_exits_at_actual_close_not_retrospective_stop(
    side, ohlc, price
):
    state = initial_protection(side, D(100), D(1))
    after, exit = manage_completed_bar(state, ohlc, atr=D(1), atr_fresh=True, slippage=D("0.01"))
    assert after.trail_active
    assert exit.reason == "trailing_at_close" and exit.price == D(price)
    assert exit.price != after.stop


@pytest.mark.parametrize(
    "side,first,second",
    [
        (1, bar("100", "104", "99", "103"), bar("103", "105", "102", "104")),
        (-1, bar("100", "101", "96", "97"), bar("97", "98", "95", "96")),
    ],
)
def test_wider_later_atr_never_widens_stop_or_redefines_initial_r(side, first, second):
    state = initial_protection(side, D(100), D(1))
    state, _ = manage_completed_bar(state, first, atr=D(1), atr_fresh=True)
    after, exit = manage_completed_bar(state, second, atr=D(10), atr_fresh=True)
    assert exit is None and after.stop == state.stop and after.initial_stop == state.initial_stop


@pytest.mark.parametrize(
    "atr,fresh",
    [
        (None, True),
        (D("NaN"), True),
        (D("Infinity"), True),
        (D(0), True),
        (D(-1), True),
        (D(1), False),
        (1, True),
    ],
)
def test_unavailable_atr_does_not_tighten_but_cannot_suppress_old_stop(atr, fresh):
    state = initial_protection(1, D(100), D(1))
    after, exit = manage_completed_bar(
        state, bar("100", "106", "99", "105"), atr=atr, atr_fresh=fresh
    )
    assert exit is None and after.stop == D(98)
    _, exit = manage_completed_bar(state, bar("100", "106", "97", "105"), atr=atr, atr_fresh=fresh)
    assert exit.reason == "stop" and exit.price == D(98)


def test_missing_bar_keeps_protection_without_manufacturing_fill():
    state = initial_protection(1, D(100), D(1))
    after, exit = manage_completed_bar(state, None, atr=D(1), atr_fresh=True)
    assert after == state and exit is None
    # A later executable gap still honors the same old stop; external close
    # obligations have not been canceled or marked filled by the missing bar.
    _, exit = manage_completed_bar(after, bar("95", "96", "94", "95"))
    assert exit.price == D(95)


def test_trailing_ablation_disables_only_tightening_not_old_stop():
    state = initial_protection(1, D(100), D(1))
    after, exit = manage_completed_bar(
        state, bar("100", "110", "99", "105"), atr=D(1), atr_fresh=True, trailing=False
    )
    assert exit is None and after.stop == D(98) and not after.trail_active
    _, exit = manage_completed_bar(after, bar("100", "110", "97", "105"), trailing=False)
    assert exit.reason == "stop"


@pytest.mark.parametrize(
    "side,entry,atr",
    [
        (True, D(100), D(1)),
        (0, D(100), D(1)),
        (1, D("NaN"), D(1)),
        (1, D(100), None),
        (1, D(100), D(0)),
        (1, D(1), D(1)),
    ],
)
def test_invalid_initial_protection_rejected(side, entry, atr):
    with pytest.raises(ValueError):
        initial_protection(side, entry, atr)


def test_invalid_state_and_nonfinite_bar_rejected():
    state = initial_protection(1, D(100), D(1))
    with pytest.raises(ValueError):
        manage_completed_bar(replace(state, stop=D(97)), bar())
    with pytest.raises(ValueError):
        manage_completed_bar(state, replace(bar(), low=D("NaN")))


def test_decimal_context_does_not_round_protection_prices():
    with localcontext() as ctx:
        ctx.prec = 60
        expected = D("100.123456789123456789") - 2 * D("0.123456789123456789")
    with localcontext() as ctx:
        ctx.prec = 8
        state = initial_protection(1, D("100.123456789123456789"), D("0.123456789123456789"))
    assert state.stop == expected
