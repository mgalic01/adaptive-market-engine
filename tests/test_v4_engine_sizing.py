"""V4 engine task 4: volatility sizing from the full-strength book, the caps and the band.

Sizing tests feed seeded ``DailyReturn`` series straight to ``size_book``. The exact checks
(sigma, the covariance, the volatility target) are recomputed here in ``Fraction``s, from the
inputs only. The one oracle is V3's ``trend.sizing``, which a test may call only on pre-2025
bars: with every |s| = 1 the full-strength book is V3's raw book, so ``size_book`` must equal
``size_portfolio`` exactly. Every input is synthetic; no network, no real data.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction
from typing import Any

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.sizing import DailyReturn
from crypto_grid_bot.trend.sizing import daily_returns as v3_daily_returns
from crypto_grid_bot.trend.sizing import size_portfolio as v3_size_portfolio
from crypto_grid_bot.v4.engine.arms import (
    BAND_ABSOLUTE,
    BAND_RELATIVE,
    COIN_CAP,
    COVARIANCE_DAYS,
    MIN_COMMON_DAYS,
    SIGMA_RETURNS,
    TOTAL_CAP,
)
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal
from crypto_grid_bot.v4.engine.sizing import (
    CoinSizing,
    SizingResult,
    band_trades,
    daily_returns,
    size_book,
)

D = Decimal
F = Fraction
DAY = 86_400_000
START = month_bounds_ms("2021-01")[0]
ONE = D(1)
TARGET = D("0.40")
# Caps that never bind, for the tests that look at the volatility scale alone.
LOOSE: dict[str, Decimal] = {"coin_cap": D(1000), "total_cap": D(100000)}


def at(day: int) -> int:
    return START + day * DAY


def noise(seed: int, count: int, bps: int) -> list[Decimal]:
    """Seeded returns of up to ``bps`` basis points either way, four decimals."""
    rng = random.Random(seed)
    return [D(rng.randint(-bps, bps)) / 10000 for _ in range(count)]


def series(
    values: list[Decimal], first_day: int = 0, missing: frozenset[int] | set[int] = frozenset()
) -> tuple[DailyReturn, ...]:
    """One return per value on consecutive days from ``first_day``, minus the missing days."""
    return tuple(
        DailyReturn(at(first_day + i), value)
        for i, value in enumerate(values)
        if first_day + i not in missing
    )


def bar(day: int, close: Any) -> Kline:
    value = D(str(close))
    return Kline(at(day), value, value, value, value, D(1), value, D("0.5"))


# --- daily_returns (Ruling R4) -------------------------------------------------------------


def test_returns_never_bridge_a_missing_day():
    bars = [bar(0, 100), bar(1, 110), bar(3, 110), bar(4, 99)]
    expected = (DailyReturn(at(1), D("0.1")), DailyReturn(at(4), D("-0.1")))
    assert daily_returns(bars) == expected
    assert daily_returns(bars) == v3_daily_returns(bars)
    assert daily_returns([]) == ()
    assert daily_returns([bar(0, 100)]) == ()
    # The day-3 bar has no day-2 neighbour, so it yields nothing, and the day-4 return is
    # measured from the day-3 close.
    assert all(row.day_ms != at(3) for row in daily_returns(bars))


def test_returns_do_not_depend_on_the_ambient_decimal_context():
    bars = [bar(0, 100), bar(1, 110), bar(2, "103.33333333")]
    expected = daily_returns(bars)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert daily_returns(bars) == expected
    # Under the one engine context, the quotient is rounded to 60 digits.
    with localcontext(CONTEXT):
        assert expected[1].value == D("103.33333333") / D(110) - 1


def test_returns_are_not_limited_to_the_development_window():
    first = int(datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000)
    bars = [
        Kline(first + i * DAY, D(close), D(close), D(close), D(close), D(1), D(1), D(1))
        for i, close in enumerate((100, 101))
    ]
    assert daily_returns(bars) == (DailyReturn(first + DAY, D("0.01")),)


@pytest.mark.parametrize(
    "bars",
    [
        [bar(0, 0)],
        [bar(0, -1)],
        [bar(0, "NaN")],
        [bar(0, "Infinity")],
        [bar(0, "0.0000000000000000001")],  # 19 decimals
        [bar(0, "1e19")],
        [bar(0, 100), bar(0, 101)],
        [bar(1, 100), bar(0, 101)],
        [Kline(START + 1, D(1), D(1), D(1), D(1), D(1), D(1), D(1))],
        [Kline(-DAY, D(1), D(1), D(1), D(1), D(1), D(1), D(1))],
        [Kline(at(0), D(1), D(1), D(1), 1.5, D(1), D(1), D(1))],  # type: ignore[arg-type]
    ],
    ids=[
        "zero",
        "negative",
        "nan",
        "infinity",
        "too-many-decimals",
        "too-large",
        "duplicate-day",
        "reversed",
        "not-midnight",
        "negative-time",
        "float-close",
    ],
)
def test_returns_reject_invalid_bars(bars):
    with pytest.raises(ValueError):
        daily_returns(bars)


# --- the book's inputs ---------------------------------------------------------------------


def two_coin_inputs() -> tuple[dict[str, Decimal], dict[str, tuple[DailyReturn, ...]]]:
    return (
        {"AA": ONE, "BB": ONE},
        {"AA": series(noise(1, 100, 300)), "BB": series(noise(2, 100, 300))},
    )


def test_short_history_or_zero_sigma_gets_zero():
    day = at(99)
    result = size_book(
        {"AA": ONE, "SHORT": ONE, "FLAT": ONE, "GONE": ONE, "EDGE": ONE},
        {
            "AA": series(noise(1, 100, 300)),
            # Returns on days 41..99: 59 of them, one short of the 60 sigma needs.
            "SHORT": series(noise(2, 59, 300), first_day=41),
            "FLAT": series([D("0.01")] * 100),  # a constant return has no spread
            # GONE has no returns at all.
            # Returns on days 40..99: exactly 60, so sigma exists.
            "EDGE": series(noise(4, 60, 300), first_day=40),
        },
        day,
        vol_target=TARGET,
        **LOOSE,
    )
    for name in ("SHORT", "GONE"):
        coin = result.coins[name]
        assert coin.sigma is None
        assert (coin.raw, coin.full, coin.scaled) == (0, 0, 0)
        assert (coin.after_coin_cap, coin.after_total_cap, result.weights[name]) == (0, 0, 0)
    flat = result.coins["FLAT"]
    assert flat.sigma == 0
    assert (flat.raw, flat.full, result.weights["FLAT"]) == (0, 0, 0)
    for name in ("AA", "EDGE"):
        coin = result.coins[name]
        assert coin.sigma is not None and coin.sigma > 0
        with localcontext(CONTEXT):
            assert coin.full == coin.raw == ONE / coin.sigma
        assert result.weights[name] != 0
    # The coins without a usable sigma are left out of the book, not of the record.
    assert set(result.weights) == set(result.coins) == {"AA", "SHORT", "FLAT", "GONE", "EDGE"}
    # Only AA and EDGE are active, and both have all 60 days of the window.
    assert result.common_days == 60


def test_sigma_is_the_annualised_sample_deviation_of_the_last_60_returns():
    values = [D("0.01") if day % 2 else D("-0.01") for day in range(60)]
    result = size_book({"AA": ONE}, {"AA": series(values)}, at(59), vol_target=TARGET, **LOOSE)
    sigma = result.coins["AA"].sigma
    assert sigma is not None
    # mean 0, so the variance is 60 x 0.0001 / 59, and 365 days make a year.
    expected = (60 * 0.0001 / 59 * 365) ** 0.5
    assert float(sigma) == pytest.approx(expected, rel=1e-12)
    assert abs(F(sigma) ** 2 - exact_sigma_squared(values)) < F(1, 10**50)


def test_sigma_reads_only_the_last_60_returns_at_or_before_the_day():
    base = noise(3, 100, 300)
    day = at(99)

    def book(rows: tuple[DailyReturn, ...]) -> SizingResult:
        return size_book({"AA": ONE}, {"AA": rows}, day, vol_target=TARGET, **LOOSE)

    reference = book(series(base))
    older = [D("0.05")] * 30 + base[30:]  # days 0..29 are outside the last 60 (days 40..99)
    assert book(series(older)) == reference
    # Returns after the day are never read, whatever they are.
    later = series(base + noise(9, 31, 900))
    assert len(later) == 131 and book(later) == reference
    # A return inside the window does matter.
    changed = list(base)
    changed[70] = D("0.04")
    assert book(series(changed)).coins["AA"].sigma != reference.coins["AA"].sigma


def test_fewer_than_40_common_days_flattens_the_book():
    day = at(99)
    aa = series(noise(1, 100, 300))

    def book(missing: int, bb_signal: Decimal = -ONE) -> SizingResult:
        # BB misses the first `missing` days of the window (days 40..99) and nothing before.
        gaps = set(range(40, 40 + missing))
        rows = {"AA": aa, "BB": series(noise(2, 100, 300), missing=gaps)}
        return size_book({"AA": ONE, "BB": bb_signal}, rows, day, vol_target=TARGET, **LOOSE)

    flat = book(21)  # 39 common days
    assert flat.common_days == 39
    assert flat.flat_reason == "insufficient_common_days"
    assert flat.scale is None
    assert all(weight == 0 for weight in flat.weights.values())
    assert all(
        (c.scaled, c.after_coin_cap, c.after_total_cap) == (0, 0, 0) for c in flat.coins.values()
    )
    # The record still shows what the coins would have been.
    assert flat.coins["AA"].sigma is not None
    assert flat.coins["AA"].raw > 0 and flat.coins["BB"].raw < 0
    assert flat.coins["BB"].full == flat.coins["BB"].raw  # |s| = 1

    sized = book(20)  # 40 common days: enough
    assert sized.common_days == MIN_COMMON_DAYS == 40
    assert sized.flat_reason is None and sized.scale is not None
    assert sized.weights["AA"] > 0 > sized.weights["BB"]

    # A coin with no signal is not in the book, so its gaps cost nothing.
    quiet = book(21, bb_signal=D(0))
    assert quiet.common_days == 60 and quiet.flat_reason is None
    assert quiet.weights["BB"] == 0 and quiet.weights["AA"] != 0


def test_a_book_with_nothing_to_hold_is_flat():
    signals, rows = two_coin_inputs()
    result = size_book(dict.fromkeys(signals, D(0)), rows, at(99), vol_target=TARGET)
    assert result.flat_reason == "no_nonzero_raw_weights"
    assert result.scale is None and result.common_days == 0
    assert all(weight == 0 for weight in result.weights.values())
    # Sigma is measured whether or not the coin is held.
    assert all(coin.sigma is not None and coin.full == 0 for coin in result.coins.values())
    # Nothing sized for a coin whose sigma is missing.
    only = size_book({"AA": ONE}, {"AA": series(noise(1, 59, 300))}, at(58), vol_target=TARGET)
    assert only.flat_reason == "no_nonzero_raw_weights" and only.weights == {"AA": 0}


def test_a_book_with_no_portfolio_volatility_is_flat():
    # Two coins with the same returns, one long and one short: the full-strength book is
    # perfectly hedged, so full' Sigma full is exactly 0.
    rows = series(noise(5, 100, 300))
    result = size_book({"AA": ONE, "BB": -ONE}, {"AA": rows, "BB": rows}, at(99), vol_target=TARGET)
    assert result.flat_reason == "zero_portfolio_volatility"
    assert result.scale is None and result.common_days == 60
    assert all(weight == 0 for weight in result.weights.values())
    assert result.coins["AA"].raw > 0 > result.coins["BB"].raw


def test_a_negative_portfolio_variance_is_refused():
    # BB moves twice as much as AA, and is held short at half AA's weight: on paper a perfect
    # hedge with variance 0. At 60 digits the rounded product comes out just below 0. The
    # engine refuses it, as V3 does on the same data.
    values = noise(2, 100, 300)
    rows = {"AA": series(values), "BB": series([2 * value for value in values])}
    signals = {"AA": ONE, "BB": -ONE}
    with pytest.raises(ValueError, match="negative portfolio variance"):
        size_book(signals, rows, at(99), vol_target=TARGET)
    with pytest.raises(ValueError, match="negative portfolio variance"):
        v3_size_portfolio(signals, rows, at(99), multiple=2)


# --- the scale and the caps ----------------------------------------------------------------


def exact_sigma_squared(values: list[Decimal]) -> Fraction:
    last = [F(value) for value in values[-SIGMA_RETURNS:]]
    mean = sum(last) / SIGMA_RETURNS
    return sum((value - mean) ** 2 for value in last) / (SIGMA_RETURNS - 1) * 365


def exact_covariance(a: dict[int, Decimal], b: dict[int, Decimal], days: list[int]) -> Fraction:
    mean_a = sum(F(a[day]) for day in days) / len(days)
    mean_b = sum(F(b[day]) for day in days) / len(days)
    total = sum((F(a[day]) - mean_a) * (F(b[day]) - mean_b) for day in days)
    return total / (len(days) - 1) * 365


def correlated_book() -> dict[str, tuple[DailyReturn, ...]]:
    """Five coins that share a market factor, one of them with a gap inside the window."""
    market = noise(7, 120, 200)
    rows: dict[str, tuple[DailyReturn, ...]] = {}
    for name, (seed, beta, bps, gaps) in {
        "AA": (11, D("1.0"), 150, set()),
        "BB": (12, D("0.6"), 250, {70}),
        "CC": (13, D("1.4"), 100, set()),
        "DD": (14, D("0.9"), 300, set()),
        "EE": (15, D("1.1"), 120, set()),
    }.items():
        own = noise(seed, 120, bps)
        values = [beta * m + n for m, n in zip(market, own, strict=True)]
        rows[name] = series(values, missing=gaps)
    return rows


@pytest.mark.parametrize("vol_target", [D("0.25"), D("0.40"), D("0.60")])
def test_full_strength_book_hits_the_vol_target_before_caps(vol_target):
    rows = correlated_book()
    day_index = 119
    # Mixed strengths and sides. EE has no signal, so it is not in the full-strength book.
    signals = {
        "AA": ONE,
        "BB": -ONE,
        "CC": D(1) / D(3),
        "DD": D("-0.5"),
        "EE": D(0),
    }
    result = size_book(signals, rows, at(day_index), vol_target=vol_target, **LOOSE)
    assert result.flat_reason is None and result.scale is not None

    window = range(day_index - COVARIANCE_DAYS + 1, day_index + 1)
    by_day = {name: {(r.day_ms - START) // DAY: r.value for r in rows[name]} for name in rows}
    active = [name for name in signals if signals[name] != 0]
    days = [d for d in window if all(d in by_day[name] for name in active)]
    assert len(days) == 59 == result.common_days  # BB has no return on day 70

    # sigma is the exact annualised deviation of the last 60 returns.
    for name in signals:
        values = [r.value for r in rows[name] if (r.day_ms - START) // DAY <= day_index]
        sigma = result.coins[name].sigma
        assert sigma is not None
        assert abs(F(sigma) ** 2 / exact_sigma_squared(values) - 1) < F(1, 10**50)

    # full is sign(s) / sigma, and 0 for a coin without a signal.
    with localcontext(CONTEXT):
        for name in active:
            sign = ONE if signals[name] > 0 else -ONE
            assert result.coins[name].full == sign * (ONE / result.coins[name].sigma)
            assert result.coins[name].raw == signals[name] * (ONE / result.coins[name].sigma)
    assert result.coins["EE"].full == 0 and result.coins["EE"].raw == 0

    # The full-strength book c x full runs at exactly the volatility target.
    scale = F(result.scale)
    variance = sum(
        scale
        * F(result.coins[a].full)
        * scale
        * F(result.coins[b].full)
        * exact_covariance(by_day[a], by_day[b], days)
        for a in active
        for b in active
    )
    assert abs(variance / F(vol_target) ** 2 - 1) < F(1, 10**40)

    # Each weight is c x raw, and with no cap in the way nothing else touches it.
    for name in signals:
        coin = result.coins[name]
        with localcontext(CONTEXT):
            assert coin.scaled == coin.raw * result.scale
        assert coin.after_coin_cap == coin.after_total_cap == coin.scaled
        assert result.weights[name] == coin.scaled
    assert result.weights["AA"] > 0 > result.weights["BB"]
    assert result.weights["CC"] > 0 > result.weights["DD"]
    assert result.weights["EE"] == 0


def test_agreement_sets_the_size():
    rows = correlated_book()
    day = at(119)
    with localcontext(CONTEXT):
        third = D(1) / D(3)  # L = 1/3: one speed up. A 60-digit quotient, not an exact third.
    book = {"AA": ONE, "BB": third}
    full_book = {"AA": ONE, "BB": ONE}
    result = size_book(book, rows, day, vol_target=TARGET, **LOOSE)
    reference = size_book(full_book, rows, day, vol_target=TARGET, **LOOSE)
    assert result.flat_reason is None

    # The scale comes from the full-strength book, so BB's weaker signal does not change it.
    assert result.scale == reference.scale
    assert result.coins["BB"].full == reference.coins["BB"].full
    assert result.weights["AA"] == reference.weights["AA"]

    # BB holds a third of its full-strength position (not an exact third: see the ruling).
    full_weight = reference.weights["BB"]
    assert full_weight > 0
    assert abs(F(result.weights["BB"]) / (F(full_weight) / 3) - 1) < F(1, 10**50)
    # In the engine's own order: (s x (1 / sigma)) x c.
    sigma = result.coins["BB"].sigma
    assert sigma is not None and result.scale is not None
    with localcontext(CONTEXT):
        assert result.weights["BB"] == (third * (ONE / sigma)) * result.scale

    # A short is sized the same way: a quarter, a half or all of its full-strength weight
    # (the fast-rally halving and the confirmed downtrend), under one scale.
    short_reference = size_book({"AA": ONE, "BB": -ONE}, rows, day, vol_target=TARGET, **LOOSE)
    for strength in (D("0.25"), D("0.5"), D(1)):
        mixed = size_book({"AA": ONE, "BB": -strength}, rows, day, vol_target=TARGET, **LOOSE)
        assert mixed.scale == short_reference.scale
        assert mixed.coins["BB"].full == short_reference.coins["BB"].full < 0
        expected = F(short_reference.weights["BB"]) * F(strength)
        assert abs(F(mixed.weights["BB"]) / expected - 1) < F(1, 10**50)


def test_coin_cap_then_total_cap():
    # AA is calm, so c x raw is far over the coin cap; the other four sit just under it. The
    # coin cap holds AA at 0.30, which pushes the book over the total cap, so every weight is
    # then scaled down together. Scaling by the total cap first and clamping after would give
    # other numbers: that is the order this test pins.
    quiet = noise(21, 100, 20)
    loud = {
        name: noise(seed, 100, 600)
        for name, seed in (("BB", 22), ("CC", 23), ("DD", 24), ("EE", 25))
    }
    rows = {"AA": series(quiet)} | {name: series(values) for name, values in loud.items()}
    signals = {"AA": -ONE, "BB": ONE, "CC": -ONE, "DD": ONE, "EE": ONE}
    coin_cap, total_cap = D("0.30"), D("1.0")
    day = at(99)

    result = size_book(
        signals, rows, day, vol_target=TARGET, coin_cap=coin_cap, total_cap=total_cap
    )
    assert result.flat_reason is None
    scaled = {name: F(result.coins[name].scaled) for name in signals}
    cap = F(coin_cap)

    # Preconditions: the coin cap binds on AA only, then the total cap binds on the rest.
    assert scaled["AA"] < -cap
    assert all(abs(scaled[name]) < cap for name in signals if name != "AA")
    clamped = {name: max(-cap, min(cap, value)) for name, value in scaled.items()}
    gross = sum(abs(value) for value in clamped.values())
    assert gross > F(total_cap)

    # Step 3, coin cap: AA is held at exactly -0.30, the others untouched.
    assert result.coins["AA"].after_coin_cap == -coin_cap
    for name in signals:
        assert F(result.coins[name].after_coin_cap) == clamped[name]
    # Step 3, total cap: every weight scaled by total / gross, the book at exactly the cap.
    factor = F(total_cap) / gross
    for name in signals:
        coin = result.coins[name]
        assert abs(F(coin.after_total_cap) - clamped[name] * factor) < F(1, 10**50)
        assert result.weights[name] == coin.after_total_cap
        assert coin.after_total_cap * coin.after_coin_cap >= 0  # the sides never flip
    book_gross = sum(abs(F(w)) for w in result.weights.values())
    assert abs(book_gross - F(total_cap)) < F(1, 10**50)
    # The other order (total cap on the raw scaled weights, then the coin cap) differs.
    shrink = F(total_cap) / sum(abs(value) for value in scaled.values())
    total_first = {name: max(-cap, min(cap, value * shrink)) for name, value in scaled.items()}
    assert all(F(result.weights[name]) != total_first[name] for name in signals)

    # With room under the total cap, only the coin cap acts, and the weights stay as clamped.
    roomy = size_book(signals, rows, day, vol_target=TARGET, coin_cap=coin_cap, total_cap=D(10))
    assert roomy.scale == result.scale
    for name in signals:
        assert F(roomy.weights[name]) == clamped[name]
        assert roomy.coins[name].after_total_cap == roomy.coins[name].after_coin_cap


def test_default_caps_are_the_spec_caps():
    assert D("0.30") == COIN_CAP
    assert D("2.7") == TOTAL_CAP
    # One calm coin: the volatility scale puts it well over 30%, so the coin cap holds it.
    calm = size_book({"AA": ONE}, {"AA": series(noise(1, 100, 100))}, at(99), vol_target=TARGET)
    assert calm.coins["AA"].scaled > COIN_CAP
    assert calm.weights["AA"] == COIN_CAP
    short = size_book({"AA": -ONE}, {"AA": series(noise(1, 100, 100))}, at(99), vol_target=TARGET)
    assert short.weights["AA"] == -COIN_CAP

    # Ten calm, independent coins, each over the coin cap: 10 x 0.30 = 3.0 > 2.7, so the whole
    # book is scaled to 2.7 and each coin ends at 0.27.
    names = [f"C{i}" for i in range(10)]
    rows = {name: series(noise(30 + i, 100, 300)) for i, name in enumerate(names)}
    signals = {name: ONE if i % 2 else -ONE for i, name in enumerate(names)}
    result = size_book(signals, rows, at(99), vol_target=TARGET)
    assert all(abs(result.coins[name].scaled) > COIN_CAP for name in names)
    assert all(abs(result.coins[name].after_coin_cap) == COIN_CAP for name in names)
    assert abs(sum(abs(F(w)) for w in result.weights.values()) - F(TOTAL_CAP)) < F(1, 10**50)
    assert all(abs(abs(F(result.weights[name])) - F("0.27")) < F(1, 10**50) for name in names)
    assert all((result.weights[name] > 0) == (signals[name] > 0) for name in names)


# --- the result types and the inputs -------------------------------------------------------


def test_results_are_immutable():
    signals, rows = two_coin_inputs()
    result = size_book(signals, rows, at(99), vol_target=TARGET)
    assert isinstance(result, SizingResult)
    assert isinstance(result.coins["AA"], CoinSizing)
    with pytest.raises(FrozenInstanceError):
        result.scale = D(1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.coins["AA"].raw = D(1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.weights["AA"] = D(1)  # type: ignore[index]
    with pytest.raises(TypeError):
        result.coins["AA"] = result.coins["AA"]  # type: ignore[index]


def test_sizing_does_not_depend_on_the_ambient_decimal_context():
    signals, rows = two_coin_inputs()
    expected = size_book(signals, rows, at(99), vol_target=TARGET)
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        assert size_book(signals, rows, at(99), vol_target=TARGET) == expected


def test_a_coin_without_returns_or_outside_the_signals_is_ignored():
    rows = {"AA": series(noise(1, 100, 300)), "OTHER": series(noise(2, 100, 300))}
    alone = size_book({"AA": ONE}, {"AA": rows["AA"]}, at(99), vol_target=TARGET)
    assert size_book({"AA": ONE}, rows, at(99), vol_target=TARGET) == alone
    assert set(alone.weights) == {"AA"}


@pytest.mark.parametrize(
    "signals",
    [
        {"AA": D("1.01")},
        {"AA": D("-1.0001")},
        {"AA": D("NaN")},
        {"AA": D("Infinity")},
        {"AA": 0.5},
        {"AA": 1},
    ],
    ids=["above", "below", "nan", "infinity", "float", "int"],
)
def test_signals_must_be_finite_decimals_within_one(signals):
    _, rows = two_coin_inputs()
    with pytest.raises(ValueError):
        size_book(signals, rows, at(99), vol_target=TARGET)


@pytest.mark.parametrize(
    "bad",
    [
        (DailyReturn(at(5), D("0.01")), DailyReturn(at(5), D("0.02"))),  # a day twice
        (DailyReturn(at(5), D("0.01")), DailyReturn(at(4), D("0.02"))),  # out of order
        (DailyReturn(START + 1, D("0.01")),),  # not at midnight
        (DailyReturn(at(5), D("-1")),),  # a total loss is not a simple return here
        (DailyReturn(at(5), D("NaN")),),
        (DailyReturn(at(5), D("1e37")),),
    ],
    ids=["duplicate", "unordered", "not-midnight", "minus-one", "nan", "huge"],
)
def test_returns_must_be_ordered_aligned_and_valid(bad):
    good = series(noise(1, 100, 300))
    # Wrong anywhere, even after the decision day: the whole series is validated.
    with pytest.raises(ValueError):
        size_book({"AA": ONE}, {"AA": bad}, at(99), vol_target=TARGET)
    with pytest.raises(ValueError):
        size_book(
            {"AA": ONE}, {"AA": good + (DailyReturn(at(99), D("0.01")),)}, at(99), vol_target=TARGET
        )
    with pytest.raises(ValueError):
        size_book({"AA": ONE}, {"AA": good + bad}, at(99), vol_target=TARGET)


@pytest.mark.parametrize("day_ms", [START + 1, -DAY, 99.0, True, "2021-01-01"])
def test_the_decision_day_must_be_a_utc_day(day_ms):
    signals, rows = two_coin_inputs()
    with pytest.raises(ValueError):
        size_book(signals, rows, day_ms, vol_target=TARGET)


@pytest.mark.parametrize(
    "limits",
    [
        {"vol_target": D(0)},
        {"vol_target": D(-1)},
        {"vol_target": 0.4},
        {"vol_target": D("NaN")},
        {"coin_cap": D(0)},
        {"coin_cap": D("Infinity")},
        {"total_cap": D(-2)},
        {"total_cap": 2.7},
    ],
)
def test_the_target_and_the_caps_must_be_positive_finite_decimals(limits):
    signals, rows = two_coin_inputs()
    arguments: dict[str, Any] = {"vol_target": TARGET} | limits
    with pytest.raises(ValueError):
        size_book(signals, rows, at(99), **arguments)


# --- the oracle: V3's size_portfolio -------------------------------------------------------


def walk_bars(
    seed: int, first_day: int, last_day: int, missing: frozenset[int] = frozenset()
) -> list[Kline]:
    """A seeded random walk of daily closes from 100; the price still moves on missing days."""
    rng = random.Random(seed)
    close = D(100)
    bars = []
    for day in range(first_day, last_day + 1):
        step = D(10000 + rng.randint(-300, 300)) / 10000
        close = max(D(1), (close * step).quantize(D("0.0001")))
        if day not in missing:
            bars.append(bar(day, close))
    return bars


def oracle_world() -> dict[str, list[Kline]]:
    """Ten coins, all pre-2025: C3 misses day 100, C7 is young and C9 stops at day 69."""
    world = {f"C{i}": walk_bars(i, 0, 129) for i in range(10)}
    world["C3"] = walk_bars(3, 0, 129, missing=frozenset({100}))
    world["C7"] = walk_bars(7, 60, 129)
    world["C9"] = walk_bars(9, 0, 69)
    return world


def signal_patterns(names: list[str], seed: int) -> list[dict[str, Decimal]]:
    rng = random.Random(seed)
    sides = {name: D(rng.choice((-1, 1))) for name in names}
    # C7 has a short history and C9 goes quiet, so a book without them is the plain case.
    plain = {name: (D(0) if name in ("C7", "C9") else sides[name]) for name in names}
    return [
        dict.fromkeys(names, D(1)),
        dict.fromkeys(names, D(0)),
        sides,
        plain,
        {name: D(rng.choice((-1, 0, 1))) for name in names},
    ]


def test_returns_match_v3_on_pre_2025_bars():
    for name, bars in oracle_world().items():
        assert daily_returns(bars) == v3_daily_returns(bars), name


@pytest.mark.parametrize("multiple", [1, 2, 3])
def test_matches_v3_size_portfolio_when_every_signal_is_full(multiple):
    """With |s| = 1 or 0 the full-strength book is V3's raw book, so every number agrees."""
    world = oracle_world()
    names = sorted(world)
    v3_rows = {name: v3_daily_returns(bars) for name, bars in world.items()}
    v4_rows = {name: daily_returns(bars) for name, bars in world.items()}
    vol_target = D("0.20") * multiple
    coin_cap = D("0.10") * multiple
    total_cap = D("0.80") * multiple
    seen: set[str] = set()
    for day in (75, 90, 100, 101, 129):
        for signals in signal_patterns(names, seed=day):
            expected = v3_size_portfolio(signals, v3_rows, at(day), multiple=multiple)
            result = size_book(
                signals,
                v4_rows,
                at(day),
                vol_target=vol_target,
                coin_cap=coin_cap,
                total_cap=total_cap,
            )
            context = f"day {day}, multiple {multiple}, signals {signals}"
            assert dict(result.weights) == expected.weights, context
            assert result.flat_reason == expected.flat_reason, context
            assert result.common_days == len(expected.common_days), context
            for name in names:
                coin = result.coins[name]
                assert coin.sigma == expected.volatility[name], context
                assert coin.raw == expected.raw_weights[name], context
                assert coin.full == coin.raw, context
                if expected.scaled_weights[name] is not None:
                    assert coin.scaled == expected.scaled_weights[name], context
            if expected.flat_reason is not None:
                seen.add(expected.flat_reason)
                assert result.scale is None
                continue
            seen.add("sized")
            with localcontext(CONTEXT):
                assert result.scale == vol_target / expected.estimated_volatility, context
            capped = [n for n in names if abs(result.coins[n].scaled) > coin_cap]
            assert capped == [n for n in names if "coin" in expected.binding_caps[n]], context
            gross = sum(abs(result.coins[n].after_coin_cap) for n in names)
            if gross > total_cap:
                seen.add("total cap")
                assert all("gross" in expected.binding_caps[n] for n in names if result.weights[n])
            if capped:
                seen.add("coin cap")
    # The cases must actually have exercised every branch of the oracle.
    assert seen >= {
        "sized",
        "coin cap",
        "total cap",
        "insufficient_common_days",
        "no_nonzero_raw_weights",
    }


# --- the band ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "current", "trades"),
    [
        # A sign change trades, however small.
        ("0.20", "-0.05", True),
        ("-0.20", "0.05", True),
        ("0.0001", "-0.0001", True),
        # A zero current with a nonzero target counts as a sign change.
        ("0.01", "0", True),
        ("-0.01", "0", True),
        ("0.0001", "0", True),
        # A zero target with a position open trades, even a tiny one.
        ("0", "0.5", True),
        ("0", "-0.5", True),
        ("0", "0.0001", True),
        # Nothing held and nothing wanted is no trade.
        ("0", "0", False),
        # Inside the band: within 25% of the target.
        ("0.20", "0.20", False),
        ("0.20", "0.16", False),
        ("0.20", "0.24", False),
        ("-0.20", "-0.16", False),
        ("-0.20", "-0.24", False),
        # Exactly on the edge does not trade; a hair past it does.
        ("0.20", "0.15", False),
        ("0.20", "0.25", False),
        ("0.20", "0.1499", True),
        ("0.20", "0.2501", True),
        ("-0.20", "-0.15", False),
        ("-0.20", "-0.1499", True),
        # The band is 25% of the target, not of the current position.
        ("0.10", "0.125", False),
        ("0.10", "0.13", True),
        ("0.10", "0.075", False),
        ("0.10", "0.07", True),
        # The 0.01 floor applies when 25% of the target is smaller.
        ("0.02", "0.03", False),
        ("0.02", "0.01", False),
        ("0.02", "0.0301", True),
        ("0.02", "0.0099", True),
        ("0.04", "0.05", False),  # 25% of 0.04 is exactly the floor
        ("0.04", "0.0501", True),
        ("0.05", "0.0625", False),  # 25% of 0.05 is above the floor
        ("0.05", "0.0626", True),
        ("-0.02", "-0.03", False),
        ("-0.02", "-0.0301", True),
    ],
)
def test_band_cases(target, current, trades):
    assert band_trades(D(target), D(current)) is trades


def test_band_edge_is_exact_at_any_precision():
    # 25% of a 70-digit target is more digits than the engine context keeps; the edge is still
    # exactly the edge.
    target = D("0." + "3" * 70)
    edge = to_decimal(F(target) * F(5, 4))
    assert band_trades(target, edge) is False
    assert band_trades(target, to_decimal(F(edge) + F(1, 10**75))) is True
    below = to_decimal(F(target) * F(3, 4))
    assert band_trades(target, below) is False
    assert band_trades(target, to_decimal(F(below) - F(1, 10**75))) is True
    assert D("0.25") == BAND_RELATIVE
    assert D("0.01") == BAND_ABSOLUTE


@pytest.mark.parametrize(
    ("target", "current"),
    [(0.2, D("0.1")), (D("0.2"), 0.1), (D("NaN"), D(0)), (D(0), D("Infinity")), (1, D(0))],
)
def test_band_needs_finite_decimals(target, current):
    with pytest.raises(ValueError):
        band_trades(target, current)
