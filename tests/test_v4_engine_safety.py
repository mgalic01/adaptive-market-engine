"""V4 engine task 9: the safety rules as pure helpers (spec "Safety").

Liquidation on the futures backing, adverse-extreme prices, the margin-cushion and 3x-ceiling
cut factors, dead markets (168 hours without a bar), the 10% penalised price and the
funding-month exit hour. Every expected number is worked by hand from the spec's formulas and
the comment beside it names the formula. The thresholds are exact: a few tests give a Mark whose
rounded 60-digit ratio says one thing and whose exact values say the other.

Most tests build a ``Mark`` or a ``Ledger`` by hand. The funding-exit tests use small in-memory
markets and one synthetic pack written under pytest's ``tmp_path``. No network and no real pack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Context, Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from v4_synthetic import (
    FUTURES_RULES,
    HOUR,
    SPOT_RULES,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    every_month,
    hours_in,
    month_start,
    path,
    write_world,
)

from crypto_grid_bot.v4.engine.arms import DEAD_MARKET_HOURS, DEAD_MARKET_PENALTY
from crypto_grid_bot.v4.engine.ledger import Fill, Ledger, Mark
from crypto_grid_bot.v4.engine.market import Coin, HourBar, Market, Perpetual, SeriesStore
from crypto_grid_bot.v4.engine.numbers import to_fraction
from crypto_grid_bot.v4.engine.safety import (
    DeadMarkets,
    adverse_prices,
    ceiling_breached,
    ceiling_factor,
    cushion_breached,
    cushion_factor,
    funding_exit_hour,
    liquidated,
    penalised_price,
)

D = Decimal
T0 = month_start("2025-01")
EXACT = Context(prec=200)  # for test arithmetic that must not round
MAINTENANCE_35 = D("1.2345678901234567890123456789012345")  # 35 digits: a 28-digit context rounds
THREE_TIMES_35 = D("3.7037036703703703670370370367037035")
LEG = ("spot", "XUSDT")


def make_mark(
    *, backing: str, maintenance: str, equity: str = "1000", gross_notional: str = "0"
) -> Mark:
    """A Mark with the four fields the safety checks read; the rest is filler. ``ratio`` is the
    60-digit-style quotient the ledger reports, so a test can show it is never compared."""
    b, m = D(backing), D(maintenance)
    return Mark(
        equity=D(equity),
        cash=b,
        spot_value=D(0),
        futures_upnl=D(0),
        backing=b,
        maintenance=m,
        ratio=None if m == 0 else b / m,
        gross_notional=D(gross_notional),
        gross=None,
    )


def with_backing(mark: Mark, delta: str) -> Mark:
    """``mark`` with its backing moved by ``delta`` exactly; the ratio is left as it was."""
    return Mark(
        equity=mark.equity,
        cash=mark.cash,
        spot_value=mark.spot_value,
        futures_upnl=mark.futures_upnl,
        backing=EXACT.add(mark.backing, D(delta)),
        maintenance=mark.maintenance,
        ratio=mark.ratio,
        gross_notional=mark.gross_notional,
        gross=mark.gross,
    )


def futures_ledger(cash: str, *legs: tuple[str, int, str, str]) -> Ledger:
    """A ledger with futures legs opened at fee 0: (symbol, side, quantity, price)."""
    ledger = Ledger(D(cash))
    for symbol, side, quantity, price in legs:
        ledger.fill(Fill(0, "futures", symbol, side, D(quantity), D(price), D(0), "open"))
    return ledger


def bar(open_ms: int, high: str, low: str, close: str = "100") -> HourBar:
    return HourBar(open_ms, D("100"), D(high), D(low), D(close))


def cut_to(value: Decimal, exact: Fraction) -> bool:
    """Whether ``value`` is ``exact`` cut toward zero to 60 significant digits."""
    return (
        len(value.as_tuple().digits) <= 60
        and abs(to_fraction(value)) <= abs(exact)
        and abs(exact) - abs(to_fraction(value)) < Fraction(1, 10**58)
    )


# --- liquidation ----------------------------------------------------------------------------


def test_liquidation_at_backing_at_or_below_maintenance():
    # One long of 100 contracts bought at 10 with 505 of cash (a futures fill moves cash by its
    # fee only). At the mark p: backing = 505 + 100 (p - 10) and maintenance = 0.01 x 100 p = p.
    ledger = futures_ledger("505", ("BTCUSDT", 1, "100", "10"))

    def at(price: str) -> Mark:
        return ledger.mark({("futures", "BTCUSDT"): D(price)})

    edge = at("5")  # backing = 505 - 500 = 5 = maintenance: liquidated (at or below)
    assert (edge.backing, edge.maintenance) == (D(5), D(5))
    assert liquidated(edge)
    assert liquidated(at("4.99"))  # backing 4 < maintenance 4.99
    assert not liquidated(at("5.01"))  # backing 6 > maintenance 5.01
    assert not liquidated(at("10"))


def test_liquidation_compares_the_exact_values_not_the_rounded_ratio():
    # Backing one part in 1e70 above maintenance: the 60-digit ratio is 1 exactly, which a ratio
    # test would call liquidated. The exact comparison says it is not; one part below is.
    equal = make_mark(backing="5", maintenance="5")
    barely_above = with_backing(equal, "1E-70")
    assert barely_above.ratio == D(1)
    assert not liquidated(barely_above)
    assert liquidated(equal)
    assert liquidated(with_backing(equal, "-1E-70"))


def test_a_flat_account_is_never_liquidated_even_with_negative_backing():
    # No futures leg: maintenance 0, so there is nothing to liquidate (spec "Futures margin").
    assert not liquidated(make_mark(backing="-50", maintenance="0"))
    assert not liquidated(make_mark(backing="0", maintenance="0"))


# --- the two breach tests -------------------------------------------------------------------


def test_cushion_breached_at_the_exact_edges_of_ratio_3():
    # The ratio is below 3 when backing < 3 x maintenance. The 35-digit values would be rounded
    # by a 28-digit context.
    assert to_fraction(THREE_TIMES_35) == 3 * to_fraction(MAINTENANCE_35)
    at_edge = make_mark(backing=str(THREE_TIMES_35), maintenance=str(MAINTENANCE_35))
    assert not cushion_breached(at_edge)  # a ratio of exactly 3 is not below 3
    assert cushion_breached(with_backing(at_edge, "-1E-34"))
    assert not cushion_breached(with_backing(at_edge, "1E-34"))
    # One part in 1e70 below 3 x maintenance: the rounded ratio reads 3 exactly, the exact
    # comparison still breaches.
    barely = with_backing(make_mark(backing="30", maintenance="10"), "-1E-70")
    assert barely.ratio == D(3)
    assert cushion_breached(barely)
    # Ratio 3.0001 and 2.9999 on round numbers.
    assert not cushion_breached(make_mark(backing="300.01", maintenance="100"))
    assert cushion_breached(make_mark(backing="299.99", maintenance="100"))


def test_cushion_is_not_breached_without_a_futures_position():
    assert not cushion_breached(make_mark(backing="-5", maintenance="0"))
    assert not cushion_breached(make_mark(backing="100", maintenance="0"))


def test_ceiling_breached_at_the_exact_edges_of_3x():
    # Gross exposure above 3 x equity breaches; exactly 3 x does not.
    def mark(equity: str, gross: str) -> Mark:
        return make_mark(backing="0", maintenance="0", equity=equity, gross_notional=gross)

    assert not ceiling_breached(mark("1000", "3000"))
    assert ceiling_breached(mark("1000", "3000.000000000000000000000000001"))
    assert not ceiling_breached(mark("1000", "2999.999999999999999999999999999"))
    # 35-digit values: 3 x equity exactly, then one unit of the last place above it.
    assert not ceiling_breached(mark(str(MAINTENANCE_35), str(THREE_TIMES_35)))
    above = EXACT.add(THREE_TIMES_35, D("1E-34"))
    assert ceiling_breached(mark(str(MAINTENANCE_35), str(above)))


def test_ceiling_with_equity_at_or_below_zero_counts_as_breached_when_anything_is_held():
    for equity in ("0", "-1", "-1000"):
        assert ceiling_breached(
            make_mark(backing="0", maintenance="0", equity=equity, gross_notional="0.00001")
        )
    # With no gross exposure there is nothing to cut, so no breach is reported.
    flat_negative = make_mark(backing="0", maintenance="0", equity="-5", gross_notional="0")
    flat_zero = make_mark(backing="0", maintenance="0", equity="0", gross_notional="0")
    assert not ceiling_breached(flat_negative)
    assert not ceiling_breached(flat_zero)


# --- adverse extremes -----------------------------------------------------------------------


def test_adverse_extremes_all_at_once_masked_legs_at_carried_marks():
    held = {
        ("spot", "BTCUSDT"): D("2"),  # a spot leg is a long: the low of the spot bar
        ("futures", "BTCUSDT"): D("3"),  # a long: the low of the perpetual's own bar
        ("futures", "ETHUSDT"): D("-4"),  # a short: the high
        ("futures", "SOLUSDT"): D("-1"),  # masked: its carried mark
        ("spot", "SOLUSDT"): D("5"),  # masked: its carried mark
    }
    bars = {
        ("spot", "BTCUSDT"): bar(T0, "110", "90"),
        ("futures", "BTCUSDT"): bar(T0, "112", "88"),
        ("futures", "ETHUSDT"): bar(T0, "125", "70"),
        ("futures", "SOLUSDT"): None,
        ("spot", "SOLUSDT"): None,
    }
    carried = {
        ("spot", "BTCUSDT"): D("101"),  # not used: the bar is there
        ("futures", "SOLUSDT"): D("33"),
        ("spot", "SOLUSDT"): D("34"),
        ("spot", "OTHERUSDT"): D("7"),  # not held: ignored
    }
    prices = adverse_prices(held, bars, carried)
    assert dict(prices) == {
        ("spot", "BTCUSDT"): D("90"),
        ("futures", "BTCUSDT"): D("88"),
        ("futures", "ETHUSDT"): D("125"),
        ("futures", "SOLUSDT"): D("33"),
        ("spot", "SOLUSDT"): D("34"),
    }
    with pytest.raises(TypeError):  # the result is read-only
        prices[("spot", "BTCUSDT")] = D(1)  # type: ignore[index]


def test_adverse_extremes_are_taken_at_once_so_two_legs_can_liquidate_together():
    # A long of 100 contracts at 100 and a short of 100 at 100, with 2000 of cash. At the long's
    # low a = 90 and the short's high b = 110: backing = 2000 + 100 (a - 100) - 100 (b - 100) = 0
    # and maintenance = 0.01 x 100 x (a + b) = 200, so the account is liquidated. Either leg
    # alone at its extreme (the other at 100) leaves backing 1000 over maintenance 190 or 210.
    ledger = futures_ledger("2000", ("AAAUSDT", 1, "100", "100"), ("BBBUSDT", -1, "100", "100"))
    held = ledger.positions()
    bars = {
        ("futures", "AAAUSDT"): bar(T0, "101", "90"),
        ("futures", "BBBUSDT"): bar(T0, "110", "99"),
    }
    together = ledger.mark(adverse_prices(held, bars, {}))
    assert (together.backing, together.maintenance) == (D(0), D(200))
    assert liquidated(together)
    only_long = ledger.mark({("futures", "AAAUSDT"): D(90), ("futures", "BBBUSDT"): D(100)})
    only_short = ledger.mark({("futures", "AAAUSDT"): D(100), ("futures", "BBBUSDT"): D(110)})
    assert (only_long.backing, only_long.maintenance) == (D(1000), D(190))
    assert (only_short.backing, only_short.maintenance) == (D(1000), D(210))
    assert not liquidated(only_long) and not liquidated(only_short)


def test_a_long_that_closes_well_is_liquidated_by_its_low_and_a_short_by_its_high():
    # Long 100 at 100 with 1000 cash: backing = 100 p - 9000, maintenance = p, liquidated for
    # p <= 90.9. Bar: low 80, close 95. At the close backing is 500 over 95; at the low it is
    # -1000 under 80.
    long = futures_ledger("1000", ("AAAUSDT", 1, "100", "100"))
    long_bar = {("futures", "AAAUSDT"): bar(T0, "101", "80", "95")}
    assert not liquidated(long.mark({("futures", "AAAUSDT"): D(95)}))
    assert liquidated(long.mark(adverse_prices(long.positions(), long_bar, {})))
    # Short 100 at 100: backing = 11000 - 100 p, liquidated for p >= 108.9. Bar: high 120.
    short = futures_ledger("1000", ("AAAUSDT", -1, "100", "100"))
    short_bar = {("futures", "AAAUSDT"): bar(T0, "120", "99", "102")}
    assert not liquidated(short.mark({("futures", "AAAUSDT"): D(102)}))
    assert liquidated(short.mark(adverse_prices(short.positions(), short_bar, {})))


def test_a_masked_held_leg_without_a_carried_mark_is_refused():
    held = {("futures", "BTCUSDT"): D("1")}
    with pytest.raises(ValueError, match="carried"):
        adverse_prices(held, {("futures", "BTCUSDT"): None}, {})
    with pytest.raises(ValueError, match="carried"):
        adverse_prices(held, {("futures", "BTCUSDT"): None}, {("spot", "BTCUSDT"): D(5)})


def test_adverse_prices_refuses_malformed_input():
    ok = {("futures", "BTCUSDT"): bar(T0, "110", "90")}
    held = {("futures", "BTCUSDT"): D("1")}
    masked = {("futures", "BTCUSDT"): None}
    assert adverse_prices(held, ok, {})[("futures", "BTCUSDT")] == D(90)
    assert adverse_prices({}, {}, {}) == {}
    with pytest.raises(ValueError, match="bars"):  # a held leg with no entry in bars at all
        adverse_prices(held, {}, {("futures", "BTCUSDT"): D(100)})
    with pytest.raises(ValueError, match="nonzero"):  # a leg of quantity 0 is not held
        adverse_prices({("futures", "BTCUSDT"): D(0)}, ok, {})
    spot_bar = {("spot", "BTCUSDT"): bar(T0, "1", "1")}
    with pytest.raises(ValueError, match="long only"):  # spot is long only
        adverse_prices({("spot", "BTCUSDT"): D(-1)}, spot_bar, {})
    with pytest.raises(ValueError, match="venue"):
        adverse_prices({("margin", "BTCUSDT"): D(1)}, {}, {})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="symbol"):
        adverse_prices({("spot", "btc"): D(1)}, {}, {})
    with pytest.raises(ValueError, match="positive"):  # a carried mark must be positive
        adverse_prices(held, masked, {("futures", "BTCUSDT"): D(0)})
    with pytest.raises(ValueError, match="Decimal"):  # and a Decimal
        adverse_prices(held, masked, {("futures", "BTCUSDT"): 5})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="Decimal"):  # a held quantity too
        adverse_prices({("futures", "BTCUSDT"): 1}, ok, {})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="HourBar"):  # a bar is a HourBar or None
        adverse_prices(held, {("futures", "BTCUSDT"): "bar"}, {})  # type: ignore[dict-item]


# --- the margin-cushion factor --------------------------------------------------------------


def test_cushion_factor_restores_ratio_4_before_fees():
    # All futures tradable: backing 250 on maintenance 100 (ratio 2.5). k = (250 / 4 - 0) / 100 =
    # 0.625. Cutting every position to 0.625 gives maintenance 62.5, and 250 / 62.5 = 4.
    k = cushion_factor(D(250), D(0), D(100))
    assert k == D("0.625")
    assert Fraction(250) / (Fraction(100) * to_fraction(k)) == 4
    # 20 of the maintenance cannot trade: k = (250 / 4 - 20) / 80 = 42.5 / 80 = 0.53125, and the
    # maintenance after the cut is 20 + 80 k = 62.5 again.
    k = cushion_factor(D(250), D(20), D(80))
    assert k == D("0.53125")
    assert Fraction(250) / (20 + Fraction(80) * to_fraction(k)) == 4


def test_cushion_factor_returns_a_k_at_or_below_zero_as_it_is():
    # backing 60, untradable 20, tradable 80: (15 - 20) / 80 = -0.0625: close every tradable leg.
    assert cushion_factor(D(60), D(20), D(80)) == D("-0.0625")
    assert cushion_factor(D(80), D(20), D(80)) == 0  # (20 - 20) / 80
    assert cushion_factor(D(-40), D(0), D(10)) == D(-1)  # underwater: (-10 - 0) / 10


def test_cushion_factor_cuts_toward_zero_never_up():
    # (8 / 4 - 0) / 3 = 2/3: sixty 6s, where rounding to nearest would end in a 7.
    k = cushion_factor(D(8), D(0), D(3))
    assert k == D("0." + "6" * 60)
    assert k is not None and cut_to(k, Fraction(2, 3))
    # The same value negative is cut toward zero as well (a k <= 0 closes everything anyway).
    assert cushion_factor(D(-8), D(0), D(3)) == D("-0." + "6" * 60)
    # A quotient needing more than 60 digits, from many-digit inputs, never exceeds the exact one.
    backing, untradable, tradable = D("1234.5678901234567890123"), D("0.7"), D("19.0000000007")
    k = cushion_factor(backing, untradable, tradable)
    assert k is not None
    exact = (to_fraction(backing) / 4 - to_fraction(untradable)) / to_fraction(tradable)
    assert cut_to(k, exact)


def test_cushion_with_no_tradable_futures_is_unrestorable():
    # A ratio below 3 with all the maintenance untradable: no k exists.
    stuck = make_mark(backing="250", maintenance="100")
    assert cushion_breached(stuck)
    assert cushion_factor(D(250), D(100), D(0)) is None
    assert cushion_factor(D(-5), D(0), D(0)) is None


def test_cushion_factor_refuses_malformed_input():
    with pytest.raises(ValueError, match="untradable"):
        cushion_factor(D(250), D(-1), D(80))
    with pytest.raises(ValueError, match="tradable"):
        cushion_factor(D(250), D(1), D(-80))
    with pytest.raises(ValueError, match="Decimal"):
        cushion_factor(250, D(1), D(80))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        cushion_factor(D("NaN"), D(1), D(80))
    with pytest.raises(ValueError, match="finite"):
        cushion_factor(D(250), D("Infinity"), D(80))


# --- the 3x ceiling factor ------------------------------------------------------------------


def test_ceiling_factor_cuts_to_2_7_and_counts_untradable_gross():
    # Equity 1000 with 500 of untradable gross and 2750 tradable (3250 in all, above 3000).
    # k' = (2.7 x 1000 - 500) / 2750 = 2200 / 2750 = 0.8, and 500 + 0.8 x 2750 = 2700.
    k = ceiling_factor(D(1000), D(500), D(2750))
    assert k == D("0.8")
    assert 500 + to_fraction(k) * 2750 == Fraction(27, 10) * 1000
    # Without the untradable gross the same tradable gross is cut less: 2700 / 2750.
    no_untradable = ceiling_factor(D(1000), D(0), D(2750))
    assert no_untradable is not None
    assert no_untradable > k
    assert cut_to(no_untradable, Fraction(2700, 2750))


def test_ceiling_factor_returns_a_k_at_or_below_zero_as_it_is():
    # The untradable gross alone is above 2.7 x equity: (270 - 300) / 500 = -0.06.
    assert ceiling_factor(D(100), D(300), D(500)) == D("-0.06")
    assert ceiling_factor(D(100), D(270), D(500)) == 0
    # Equity at or below zero: (2.7 x -10 - 0) / 100 = -0.27, close everything.
    assert ceiling_factor(D(-10), D(0), D(100)) == D("-0.27")
    assert ceiling_factor(D(0), D(0), D(100)) == 0


def test_ceiling_factor_with_nothing_tradable_is_none():
    assert ceiling_factor(D(1000), D(3500), D(0)) is None
    assert ceiling_factor(D(-5), D(0), D(0)) is None


def test_ceiling_factor_cuts_toward_zero_never_up():
    # (2.7 x 1000 - 100) / 3000 = 26/30 = 0.8666...: an 8, then fifty-nine 6s.
    k = ceiling_factor(D(1000), D(100), D(3000))
    assert k == D("0.8" + "6" * 59)
    assert k is not None and cut_to(k, Fraction(26, 30))
    equity, untradable, tradable = (
        D("1000.000000000000000000000000000001"),
        D("1.5"),
        D("2999.99999999999999"),
    )
    k = ceiling_factor(equity, untradable, tradable)
    assert k is not None
    exact = (Fraction(27, 10) * to_fraction(equity) - to_fraction(untradable)) / to_fraction(
        tradable
    )
    assert cut_to(k, exact)


def test_ceiling_factor_refuses_malformed_input():
    with pytest.raises(ValueError, match="untradable"):
        ceiling_factor(D(1000), D(-1), D(100))
    with pytest.raises(ValueError, match="tradable"):
        ceiling_factor(D(1000), D(1), D(-100))
    with pytest.raises(ValueError, match="Decimal"):
        ceiling_factor(1000, D(1), D(100))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        ceiling_factor(D("NaN"), D(1), D(100))


# --- dead markets ---------------------------------------------------------------------------


def test_dead_market_after_168_hours_per_venue():
    # The spot leg has its last bar in hour 10, the perpetual trades every hour. The window
    # [h - 168 h, h) holds no spot bar once h - 168 > 10, so the spot leg is first due at hour
    # 179 (hours 11 to 178 are the 168 empty hours). The perpetual leg is never due.
    assert DEAD_MARKET_HOURS == 168
    dead = DeadMarkets()
    due = {}
    for hour in range(300):
        now = T0 + hour * HOUR
        due[hour] = dead.due(now)  # asked before the hour is observed
        dead.observe(now, "spot", "XUSDT", hour <= 10)
        dead.observe(now, "futures", "XUSDT", True)
    assert [hour for hour, legs in due.items() if legs][0] == 179
    assert all(not legs for hour, legs in due.items() if hour < 179)
    assert all(legs == (("spot", "XUSDT"),) for hour, legs in due.items() if hour >= 179)


def test_a_perpetual_that_dies_while_spot_still_trades_is_handled_on_its_own():
    dead = DeadMarkets()
    due = {}
    for hour in range(300):
        now = T0 + hour * HOUR
        due[hour] = dead.due(now)
        dead.observe(now, "spot", "XUSDT", True)
        dead.observe(now, "futures", "XUSDT", hour <= 20)
    assert [hour for hour, legs in due.items() if legs][0] == 189
    assert due[299] == (("futures", "XUSDT"),)


def test_dead_market_exact_edge_167_168_and_169_hours_after_the_last_bar():
    # Last bar in hour 0. After 167 empty hours (1..167) the leg is not due at hour 168, whose
    # window [0, 168) still holds the bar. After 168 empty hours (1..168) it is due at hour 169.
    dead = DeadMarkets()
    dead.observe(T0, *LEG, True)
    for hour in range(1, 169):
        dead.observe(T0 + hour * HOUR, *LEG, False)
        if hour == 167:
            assert dead.due(T0 + 168 * HOUR) == ()
    assert dead.due(T0 + 169 * HOUR) == (LEG,)


def test_dead_market_close_does_not_wait_for_the_hour_to_have_a_bar():
    # Hour 169 itself has a bar, but the question comes before it is observed: the leg is due.
    dead = DeadMarkets()
    dead.observe(T0, "futures", "XUSDT", True)
    for hour in range(1, 169):
        dead.observe(T0 + hour * HOUR, "futures", "XUSDT", False)
    assert dead.due(T0 + 169 * HOUR) == (("futures", "XUSDT"),)
    # Once hour 169 is observed with its bar, asking about hour 169 would be a look-ahead.
    dead.observe(T0 + 169 * HOUR, "futures", "XUSDT", True)
    with pytest.raises(ValueError, match="already observed"):
        dead.due(T0 + 169 * HOUR)
    assert dead.due(T0 + 170 * HOUR) == ()  # and that bar restarted the 168 hours


def test_a_bar_restarts_the_168_hours():
    dead = DeadMarkets()
    dead.observe(T0, *LEG, True)
    for hour in range(1, 100):
        dead.observe(T0 + hour * HOUR, *LEG, False)
    dead.observe(T0 + 100 * HOUR, *LEG, True)
    for hour in range(101, 268):
        dead.observe(T0 + hour * HOUR, *LEG, False)
    assert dead.due(T0 + 268 * HOUR) == ()  # the window [100, 268) holds the bar of hour 100
    dead.observe(T0 + 268 * HOUR, *LEG, False)
    assert dead.due(T0 + 269 * HOUR) == (LEG,)


def test_a_leg_never_observed_is_never_due():
    dead = DeadMarkets()
    assert dead.due(T0 + 10_000 * HOUR) == ()
    dead.observe(T0, "spot", "AAAUSDT", True)
    assert dead.due(T0 + 10_000 * HOUR) == (("spot", "AAAUSDT"),)  # only the observed leg
    assert DeadMarkets().due(0) == ()


def test_a_leg_first_seen_without_a_bar_needs_168_observed_hours():
    # Nothing is known before the first observation, so 168 observed misses are needed: hours
    # 5 to 172 are 168 misses, and the leg is due at hour 173, not before.
    dead = DeadMarkets()
    for hour in range(5, 172):  # 167 misses, hours 5 to 171
        dead.observe(T0 + hour * HOUR, *LEG, False)
    assert dead.due(T0 + 172 * HOUR) == ()
    dead.observe(T0 + 172 * HOUR, *LEG, False)
    assert dead.due(T0 + 173 * HOUR) == (LEG,)


def test_forget_drops_a_closed_leg_and_a_reopened_leg_starts_afresh():
    dead = DeadMarkets()
    dead.observe(T0, *LEG, True)
    dead.observe(T0 + 200 * HOUR, *LEG, False)
    assert dead.due(T0 + 201 * HOUR) == (LEG,)
    dead.forget(*LEG)
    assert dead.due(T0 + 201 * HOUR) == ()
    dead.forget(*LEG)  # forgetting a leg that is not there changes nothing
    dead.observe(T0 + 500 * HOUR, *LEG, True)  # data resumed: its clock starts again
    assert dead.due(T0 + 501 * HOUR) == ()
    assert dead.due(T0 + 668 * HOUR) == ()
    assert dead.due(T0 + 669 * HOUR) == (LEG,)
    with pytest.raises(ValueError, match="venue"):
        dead.forget("margin", "XUSDT")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="symbol"):
        dead.forget("spot", "xusdt")


def test_due_lists_every_dead_leg_in_symbol_order_spot_before_futures():
    dead = DeadMarkets()
    for venue, symbol in (
        ("futures", "BBBUSDT"),
        ("spot", "BBBUSDT"),
        ("futures", "AAAUSDT"),
        ("spot", "AAAUSDT"),
        ("spot", "CCCUSDT"),
        ("spot", "LIVEUSDT"),
    ):
        dead.observe(T0, venue, symbol, True)  # type: ignore[arg-type]
    dead.observe(T0 + 169 * HOUR, "spot", "LIVEUSDT", True)  # a bar at hour 169: not dead
    assert dead.due(T0 + 170 * HOUR) == (
        ("spot", "AAAUSDT"),
        ("futures", "AAAUSDT"),
        ("spot", "BBBUSDT"),
        ("futures", "BBBUSDT"),
        ("spot", "CCCUSDT"),
    )


def test_observe_keeps_a_per_leg_hourly_clock_and_validates_its_input():
    dead = DeadMarkets()
    dead.observe(T0 + 5 * HOUR, *LEG, True)
    with pytest.raises(ValueError, match="after"):
        dead.observe(T0 + 5 * HOUR, *LEG, True)  # the same hour twice
    with pytest.raises(ValueError, match="after"):
        dead.observe(T0 + 4 * HOUR, *LEG, True)
    dead.observe(T0 + 4 * HOUR, "futures", "XUSDT", True)  # another leg has its own clock
    with pytest.raises(ValueError, match="hour"):
        dead.observe(T0 + 6 * HOUR + 1, *LEG, True)
    with pytest.raises(ValueError, match="non-negative"):
        dead.observe(-HOUR, "spot", "YUSDT", True)
    with pytest.raises(ValueError, match="venue"):
        dead.observe(T0 + 6 * HOUR, "margin", "XUSDT", True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="symbol"):
        dead.observe(T0 + 6 * HOUR, "spot", "xusdt", True)
    with pytest.raises(ValueError, match="has_bar"):
        dead.observe(T0 + 6 * HOUR, *LEG, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ms"):
        dead.observe(float(T0 + 6 * HOUR), *LEG, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="hour"):
        dead.due(T0 + 7 * HOUR + 5)
    with pytest.raises(ValueError, match="ms"):
        dead.due(True)  # type: ignore[arg-type]
    # The refused calls changed nothing.
    assert dead.due(T0 + 6 * HOUR) == ()
    assert dead.due(T0 + 173 * HOUR) == (("futures", "XUSDT"),)  # last bar at hour 4
    assert dead.due(T0 + 174 * HOUR) == (LEG, ("futures", "XUSDT"))  # and at hour 5


def test_dead_markets_agrees_with_the_stores_own_answer():
    # Driven hour by hour, the tracker says "due" exactly when the store's last bar before the
    # hour is more than 168 hours back: store.last_open_at_or_before(h - 1 ms) < h - 168 h. The
    # series has a 200-hour gap (hours 300-499), a short masked stretch (600-639) and a
    # 180-hour dead stretch (700-879); the first and last of these are dead markets.
    masked = set(range(300, 500)) | set(range(600, 640)) | set(range(700, 880))
    rows = [[T0 + hour * HOUR, "100", "100", "100", "100", "1", "100"] for hour in range(1000)]
    store = SeriesStore.from_rows(rows, masked=[T0 + hour * HOUR for hour in masked])
    dead = DeadMarkets()
    due_hours = []
    for hour in range(1, 1000):
        now = T0 + hour * HOUR
        last = store.last_open_at_or_before(now - 1)
        expected = last is not None and last < now - DEAD_MARKET_HOURS * HOUR
        assert (dead.due(now) == (("futures", "XUSDT"),)) == expected, hour
        if expected:
            due_hours.append(hour)
        dead.observe(now, "futures", "XUSDT", store.bar(now) is not None)
    # Dead from 299 + 169 = 468 until the bar returns at 500 (hour 500 itself is still due:
    # the question comes before it is observed), and from 699 + 169 = 868 to 880.
    assert due_hours == list(range(468, 501)) + list(range(868, 881))


# --- the penalised price --------------------------------------------------------------------


def test_penalised_price_is_10_percent_against_the_holder():
    assert D("0.10") == DEAD_MARKET_PENALTY
    assert penalised_price(D("100"), 1) == D("90")  # a long sells 10% below the last close
    assert penalised_price(D("100"), -1) == D("110")  # a short buys back 10% above it
    assert penalised_price(D("0.00012345"), 1) == D("0.000111105")
    assert penalised_price(D("0.00012345"), -1) == D("0.000135795")
    # Exact beyond the 28 and 60 digits of any Decimal context.
    close = D("123456789012345678901234567890.123456789012345678901234567890123456789")
    assert to_fraction(penalised_price(close, 1)) == to_fraction(close) * Fraction(9, 10)
    assert to_fraction(penalised_price(close, -1)) == to_fraction(close) * Fraction(11, 10)
    assert penalised_price(close, 1) < close < penalised_price(close, -1)


def test_penalised_price_refuses_malformed_input():
    for side in (0, 2, -2, True, 1.0):
        with pytest.raises(ValueError, match="side"):
            penalised_price(D(100), side)  # type: ignore[arg-type]
    for close in (D(0), D(-1), D("NaN"), D("Infinity")):
        with pytest.raises(ValueError):
            penalised_price(close, 1)
    with pytest.raises(ValueError, match="Decimal"):
        penalised_price(100, 1)  # type: ignore[arg-type]


# --- the funding-month exit hour ------------------------------------------------------------


def utc(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp()) * 1000


def in_memory_market(perpetual_opens: list[int] | None) -> Market:
    """BTCUSDT over a few hours of flat spot, and a perpetual with a bar at each of
    ``perpetual_opens`` (None: no perpetual). An hour not listed is masked or missing."""
    flat = [[T0 + hour * HOUR, "100", "100", "100", "100", "1", "100"] for hour in range(3)]
    spot = SeriesStore.from_rows(flat, masked=())
    perpetual = None
    if perpetual_opens is not None:
        rows = [[ms, "100", "100", "100", "100", "1", "100"] for ms in perpetual_opens]
        store = SeriesStore.from_rows(rows, masked=())
        perpetual = Perpetual("BTCUSDT", 1, store, (), {}, FUTURES_RULES)
    coin = Coin("BTCUSDT", spot, SPOT_RULES, perpetual)
    return Market(end_month="2026-06", universes={"2025-01": ("BTCUSDT",)}, coins=[coin])


def test_funding_exit_hour_is_01_00_of_the_previous_months_last_day_when_it_has_a_bar():
    # Month 2025-03: the decision is at 00:00 on 2025-02-28 and fills at 01:00 that day.
    target = utc(2025, 2, 28, 1)
    market = in_memory_market(
        [utc(2025, 2, 27, 23), utc(2025, 2, 28, 0), target, utc(2025, 2, 28, 2), utc(2025, 3, 1)]
    )
    assert funding_exit_hour(market, "BTCUSDT", "2025-03") == target


@pytest.mark.parametrize(
    ("month", "target"),
    [
        ("2025-03", utc(2025, 2, 28, 1)),
        ("2024-03", utc(2024, 2, 29, 1)),  # a leap February
        ("2026-01", utc(2025, 12, 31, 1)),  # across the year
        ("2025-05", utc(2025, 4, 30, 1)),
        ("2025-08", utc(2025, 7, 31, 1)),
    ],
)
def test_funding_exit_hour_target_for_each_month_length(month: str, target: int):
    assert funding_exit_hour(in_memory_market([target]), "BTCUSDT", month) == target


def test_funding_exit_hour_moves_to_the_next_unmasked_perpetual_hour():
    # 01:00, 02:00 and 03:00 have no bar; 04:00 is the next unmasked perpetual hour.
    market = in_memory_market(
        [utc(2025, 2, 28, 0), utc(2025, 2, 28, 4), utc(2025, 2, 28, 5), utc(2025, 3, 1)]
    )
    assert funding_exit_hour(market, "BTCUSDT", "2025-03") == utc(2025, 2, 28, 4)
    # The next bar can be the very last hour before the month.
    late = in_memory_market([utc(2025, 2, 28, 0), utc(2025, 2, 28, 23), utc(2025, 3, 1)])
    assert funding_exit_hour(late, "BTCUSDT", "2025-03") == utc(2025, 2, 28, 23)


def test_funding_exit_hour_falls_back_to_a_synthetic_midnight_close():
    # No perpetual bar from 01:00 on 2025-02-28 up to the end of the month: the leg closes
    # synthetically at 00:00 on 2025-03-01. A bar at 00:00 on 2025-03-01 itself does not count
    # (it is not "before the month starts"), nor does one before the fill hour.
    market = in_memory_market(
        [utc(2025, 2, 27, 0), utc(2025, 2, 28, 0), utc(2025, 3, 1), utc(2025, 3, 1, 1)]
    )
    assert funding_exit_hour(market, "BTCUSDT", "2025-03") == "synthetic"
    assert funding_exit_hour(in_memory_market([]), "BTCUSDT", "2025-03") == "synthetic"


def test_funding_exit_hour_refuses_a_coin_without_a_perpetual_and_bad_input():
    with pytest.raises(ValueError, match="perpetual"):
        funding_exit_hour(in_memory_market(None), "BTCUSDT", "2025-03")
    market = in_memory_market([utc(2025, 2, 28, 1)])
    with pytest.raises(ValueError, match="not a coin"):
        funding_exit_hour(market, "ETHUSDT", "2025-03")
    for month in ("2025-3", "2025-13", "202503", "2025-03-01", "", "March"):
        with pytest.raises(ValueError, match="YYYY-MM"):
            funding_exit_hour(market, "BTCUSDT", month)
    with pytest.raises(ValueError, match="YYYY-MM"):
        funding_exit_hour(market, "BTCUSDT", None)  # type: ignore[arg-type]


def test_funding_exit_hour_on_a_loaded_pack_with_masked_perpetual_hours(tmp_path: Path):
    hours = hours_in("2025-01", "2025-03")
    closes = path("100", (hours, "0.0001"), noise="0.001", seed=4)
    first_fill = month_start("2025-03") - 23 * HOUR  # 01:00 on 2025-02-28
    perpetual = PerpetualSpec(
        series=Series(month_start("2025-01"), closes, masked=(first_fill, first_fill + HOUR)),
        months={"2025-03": "missing_slot"},
    )
    coin = CoinSpec("BTCUSDT", Series(month_start("2025-01"), closes), perpetual=perpetual)
    world = World("2025-03", (coin,), every_month("2025-01", "2025-03", ("BTCUSDT",)))
    market = Market.load(write_world(tmp_path, world))
    assert market.funding_month("BTCUSDT", "2025-03") == "missing_slot"
    assert first_fill == utc(2025, 2, 28, 1)
    # 01:00 and 02:00 are masked, so the exit is at 03:00.
    assert funding_exit_hour(market, "BTCUSDT", "2025-03") == first_fill + 2 * HOUR
