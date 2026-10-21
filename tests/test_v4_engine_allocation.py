"""V4 engine task 8: the spot-first allocation, the cash clip and the venue-unit conversion.

Every expected number is computed by hand from the spec's formulas (account and execution,
"Longs on spot first, coin by coin"; safety, "Margin cushion"), and the comment beside it names
the formula. With the equity E, the room is R = 0.98 x E - S_K - D - F_K / 3 and the spot
capacity s_max = max(0, min(G_L, 1.5 x (R - (G_L + G_S) / 3))). No pack, no network and no
clock is involved; the one test that books fills uses the V4 ledger on synthetic prices.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

import pytest

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.execution import VenueRules, floor_quantity
from crypto_grid_bot.v4.engine.allocation import (
    CoinState,
    LegTargets,
    allocate,
    clip_increases,
    to_venue_quantity,
)
from crypto_grid_bot.v4.engine.ledger import Fill, Ledger, Venue
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_fraction
from crypto_grid_bot.v4.engine.orders import fee, fill_price, plan_leg

D = Decimal
HOUR_MS = 3_600_000

NORMAL = {"spot": cost_profile(1, "spot"), "futures": cost_profile(1, "futures")}
# A fee of 0.1% and no slippage on both venues: the hand-computed clip numbers come out round.
FLAT = Costs(D("0.001"), D(0), D("0.002"))
FLAT_COSTS = {"spot": FLAT, "futures": FLAT}


def coin(
    name: str,
    target: str,
    *,
    spot: str = "0",
    dust: str = "0",
    futures: str = "0",
    eligible: bool = True,
    keeps: bool = False,
    exiting: Sequence[Venue] = (),
) -> CoinState:
    return CoinState(
        name, D(target), D(spot), D(dust), D(futures), eligible, keeps, frozenset(exiting)
    )


def split(equity: str, *coins: CoinState) -> dict[str, tuple[Decimal, Decimal]]:
    """The allocation as {coin: (spot, futures)}."""
    result = allocate(D(equity), coins)
    return {name: (legs.spot, legs.futures) for name, legs in result.items()}


def cut_to(admitted: Decimal, exact: Fraction) -> bool:
    """Whether ``admitted`` is ``exact`` truncated toward zero to about 60 significant digits."""
    return to_fraction(admitted) <= exact and exact - to_fraction(admitted) < Fraction(1, 10**50)


# --- the allocation -------------------------------------------------------------------------


def test_room_formula_counts_fixed_holdings_dust_and_futures_margin() -> None:
    # Equity 10000. KEEPA and KEEPB keep their legs: S_K = 1000 + 500 = 1500 (KEEPA's 50 of dust
    # excluded) and F_K = |-600| = 600. D = 50 (KEEPA) + 100 (BTC) = 150, every coin's dust.
    # R = 0.98 x 10000 - S_K - D - F_K / 3 = 9800 - 1500 - 150 - 200 = 7950.
    # BTC: target 8800, dust 100, so the residual is 8700 = G_E; G_N = G_S = 0 and G_L = 8700.
    # s_max = min(8700, 1.5 x (7950 - 8700 / 3)) = 1.5 x 5050 = 7575.
    # s_max >= G_N = 0, so BTC takes 7575 on spot and 8700 - 7575 = 1125 on futures.
    result = split(
        "10000",
        coin("KEEPA", "0", spot="1000", dust="50", futures="-600", keeps=True),
        coin("KEEPB", "0", spot="500", keeps=True),
        coin("BTC", "8800", dust="100"),
    )
    assert result == {
        "KEEPA": (D(1000), D(-600)),  # kept as held
        "KEEPB": (D(500), D(0)),
        "BTC": (D(7575), D(1125)),
    }
    # The room is used in full: spot 7575 + S_K 1500 + D 150 + futures margin
    # (1125 + F_K 600) / 3 = 575 is 9800, which is 0.98 x equity.
    assert D(7575) + 1500 + 150 + (D(1125) + 600) / 3 == D(9800)


def test_spot_only_coins_fill_spot_first_then_eligible_coins_share_the_rest() -> None:
    # Equity 10000, no fixed holdings and no dust, so R = 9800.
    # N (spot-only): ADA 1500 + DOT 900, G_N = 2400. E: BTC 6000 + ETH 3000, G_E = 9000.
    # XRP is a short of 300: G_S = 300. G_L = 11400.
    # s_max = min(11400, 1.5 x (9800 - (11400 + 300) / 3)) = 1.5 x (9800 - 3900) = 8850.
    # s_max >= G_N, so the N coins are fully on spot and the E coins share 8850 - 2400 = 6450 of
    # spot pro rata: BTC 6450 x 6000 / 9000 = 4300 and ETH 6450 x 3000 / 9000 = 2150. The rest of
    # each is on futures: BTC 1700 and ETH 850.
    book = (
        coin("ADA", "1500", eligible=False),
        coin("BTC", "6000"),
        coin("DOT", "900", eligible=False),
        coin("ETH", "3000"),
        coin("XRP", "-300"),
    )
    result = split("10000", *book)
    assert result == {
        "ADA": (D(1500), D(0)),
        "BTC": (D(4300), D(1700)),
        "DOT": (D(900), D(0)),
        "ETH": (D(2150), D(850)),
        "XRP": (D(0), D(-300)),
    }
    assert list(result) == ["ADA", "BTC", "DOT", "ETH", "XRP"]  # the input order
    # Spot 2400 + 6450 and futures margin (1700 + 850 + 300) / 3 = 950 make up the room 9800.
    assert D(2400) + 6450 + D(1700 + 850 + 300) / 3 == D(9800)

    # With room to spare (equity 100000, R = 98000) s_max = min(11400, 1.5 x (98000 - 3900))
    # = G_L = 11400: every long is fully on spot and nothing is on futures but the short.
    assert split("100000", *book) == {
        "ADA": (D(1500), D(0)),
        "BTC": (D(6000), D(0)),
        "DOT": (D(900), D(0)),
        "ETH": (D(3000), D(0)),
        "XRP": (D(0), D(-300)),
    }


def test_when_spot_capacity_is_short_eligible_coins_go_to_futures_and_spot_only_scale() -> None:
    # Equity 10000, R = 9800. N: ADA 6000 + DOT 3000, G_N = 9000. E: BTC 4500 + ETH 3000,
    # G_E = 7500. XRP is a short of 300, G_S = 300. G_L = 16500.
    # s_max = min(16500, 1.5 x (9800 - (16500 + 300) / 3)) = 1.5 x (9800 - 5600) = 6300 < G_N.
    # So the E coins are fully on futures, and the N coins scale by one common factor
    # k = max(0, 9800 - (7500 + 300) / 3) / 9000 = 7200 / 9000 = 0.8 (never above 1 here).
    # ADA 6000 x 0.8 = 4800 and DOT 3000 x 0.8 = 2400. The 1800 of spot the scaling frees is not
    # given to anyone.
    result = split(
        "10000",
        coin("ADA", "6000", eligible=False),
        coin("BTC", "4500"),
        coin("DOT", "3000", eligible=False),
        coin("ETH", "3000"),
        coin("XRP", "-300"),
    )
    assert result == {
        "ADA": (D(4800), D(0)),
        "BTC": (D(0), D(4500)),
        "DOT": (D(2400), D(0)),
        "ETH": (D(0), D(3000)),
        "XRP": (D(0), D(-300)),
    }
    # Spot 7200 plus futures margin (7500 + 300) / 3 = 2600 is the room 9800.
    assert D(7200) + D(7500 + 300) / 3 == D(9800)


def test_the_two_branches_meet_where_spot_capacity_equals_the_spot_only_target() -> None:
    # Equity 10000, R = 9800; ADA (spot-only) 7800 and BTC 6000. G_L = 13800 and
    # s_max = min(13800, 1.5 x (9800 - 13800 / 3)) = 1.5 x 5200 = 7800 = G_N exactly.
    # s_max >= G_N: ADA 7800 on spot, BTC gets 7800 - 7800 = 0 of spot and 6000 on futures.
    # (The other branch gives k = (9800 - 6000 / 3) / 7800 = 1, the same answer.)
    assert split("10000", coin("ADA", "7800", eligible=False), coin("BTC", "6000")) == {
        "ADA": (D(7800), D(0)),
        "BTC": (D(0), D(6000)),
    }


def test_targets_are_net_of_dust_and_a_short_beside_dust_shorts_more() -> None:
    # Equity 5000, so 0.98 x equity = 4900. D = 200 (BTC) + 300 (ADA) + 150 (XRP) = 650 and
    # R = 4900 - 650 = 4250.
    # BTC target 4400 less its 200 of dust is a residual of 4200 = G_E. The caller adds the 200
    # back when it plans the spot leg.
    # ADA is spot-only with target 100 and dust 300: residual -200, treated as 0, so it holds its
    # dust and nothing else; it does not enter G_S.
    # XRP target -1050 beside 150 of dust: residual -1200, so it shorts 1200, 150 more than its
    # target; G_S = 1200 (the dust is long, the short must offset it).
    # s_max = min(4200, 1.5 x (4250 - (4200 + 1200) / 3)) = 1.5 x 2450 = 3675.
    # BTC: spot 3675, futures 4200 - 3675 = 525.
    result = split(
        "5000",
        coin("ADA", "100", dust="300", eligible=False),
        coin("BTC", "4400", dust="200"),
        coin("XRP", "-1050", dust="150"),
    )
    assert result == {
        "ADA": (D(0), D(0)),
        "BTC": (D(3675), D(525)),
        "XRP": (D(0), D(-1200)),
    }
    # Spot 3675 + D 650 + futures margin (525 + 1200) / 3 = 575 is the room 4900.
    assert D(3675) + 650 + D(525 + 1200) / 3 == D(4900)


def test_exiting_legs_count_as_zero() -> None:
    # Equity 6000, so 0.98 x equity = 5880. Four coins keep their legs:
    # ADA holds 2000 of spot that a mandatory exit closes: it counts 0 (result 0 on spot);
    # DOT holds spot 600 and a short of 900 whose exit closes: S_K counts 600, F_K counts 0;
    # LINK holds a long of 1500 on futures: F_K counts 1500;
    # SOL holds 100 of spot and 200 of futures and both legs exit: both count 0.
    # S_K = 600, F_K = 1500, D = 0: R = 5880 - 600 - 1500 / 3 = 4780.
    # BTC target 6000 (G_E = 6000): s_max = min(6000, 1.5 x (4780 - 6000 / 3)) = 1.5 x 2780 = 4170.
    # BTC: spot 4170, futures 1830. (Counting the exiting legs as held would give
    # R = 5880 - 2600 - 2400 / 3 = 2480 and s_max = 720.)
    result = split(
        "6000",
        coin("ADA", "0", spot="2000", keeps=True, exiting=["spot"]),
        coin("BTC", "6000"),
        coin("DOT", "0", spot="600", futures="-900", keeps=True, exiting=["futures"]),
        coin("LINK", "0", futures="1500", keeps=True),
        coin("SOL", "0", spot="100", futures="200", keeps=True, exiting=["spot", "futures"]),
    )
    assert result == {
        "ADA": (D(0), D(0)),
        "BTC": (D(4170), D(1830)),
        "DOT": (D(600), D(0)),
        "LINK": (D(0), D(1500)),
        "SOL": (D(0), D(0)),
    }
    assert D(4170) + 600 + D(1830 + 1500) / 3 == D(5880)


def test_exiting_legs_of_a_trading_coin_do_not_change_its_split() -> None:
    # A trading coin's legs are re-targeted by the split; the exiting leg fills in the same
    # batch's reductions, so the flag only matters for the coins that keep their legs.
    plain = split("10000", coin("BTC", "6000", spot="500", futures="100"))
    flagged = split(
        "10000", coin("BTC", "6000", spot="500", futures="100", exiting=["spot", "futures"])
    )
    assert flagged == plain == {"BTC": (D(6000), D(0))}


def test_no_trading_coins_means_no_division_by_zero() -> None:
    assert dict(allocate(D(10000), [])) == {}
    # Only coins that keep their legs: every G is 0 and they come back as held.
    held = split(
        "10000",
        coin("ADA", "0", spot="400", dust="5", keeps=True, eligible=False),
        coin("BTC", "0", spot="600", futures="-900", keeps=True),
    )
    assert held == {"ADA": (D(400), D(0)), "BTC": (D(600), D(-900))}


def test_when_every_residual_is_not_positive_nothing_is_long() -> None:
    # G_E = G_N = 0 (the E-share denominator is 0, and there is no E coin to divide it among).
    # XRP shorts 700; DOT's -50 residual (spot-only) becomes 0; LINK's target 0 beside 20 of dust
    # is a short of 20; ADA (spot-only) at 0 stays at 0.
    result = split(
        "10000",
        coin("ADA", "0", eligible=False),
        coin("DOT", "-50", eligible=False),
        coin("LINK", "0", dust="20"),
        coin("XRP", "-700"),
    )
    assert result == {
        "ADA": (D(0), D(0)),
        "DOT": (D(0), D(0)),
        "LINK": (D(0), D(-20)),
        "XRP": (D(0), D(-700)),
    }


def test_negative_room_puts_eligible_coins_on_futures_and_zeroes_the_spot_only_coins() -> None:
    # Equity 1000 and a coin that keeps 2000 of spot: R = 980 - 2000 = -1020 < 0.
    # s_max = max(0, min(G_L, 1.5 x (-1020 - ...))) = 0 < G_N, so BTC is fully on futures and
    # k = max(0, -1020 - 100 / 3) / G_N = 0: ADA gets nothing. XRP shorts as usual.
    result = split(
        "1000",
        coin("ADA", "300", eligible=False),
        coin("BTC", "100"),
        coin("KEEP", "0", spot="2000", keeps=True),
        coin("XRP", "-100"),
    )
    assert result == {
        "ADA": (D(0), D(0)),
        "BTC": (D(0), D(100)),
        "KEEP": (D(2000), D(0)),
        "XRP": (D(0), D(-100)),
    }


def test_when_eligible_futures_do_not_fit_in_the_room_the_cash_clip_is_what_bounds_them() -> None:
    # Equity 10000: KEEP holds 7994 of spot, so the wallet has 2006 of cash. R = 9800 - 7994 =
    # 1806. ADA is spot-only (3000) and BTC, ETH, SOL are eligible (3000 each, G_E = 9000).
    # G_L = 12000 and s_max = max(0, min(12000, 1.5 x (1806 - 4000))) = 0 < G_N = 3000.
    # k = max(0, 1806 - 9000 / 3) / 3000 = 0, so ADA is cut to nothing, and the E coins are
    # fully on futures: 9000 of notional that needs 3000 of margin against a room of 1806.
    # The allocation does not scale the E coins (nothing is redistributed); the clip does.
    result = split(
        "10000",
        coin("ADA", "3000", eligible=False),
        coin("BTC", "3000"),
        coin("ETH", "3000"),
        coin("KEEP", "0", spot="7994", keeps=True),
        coin("SOL", "3000"),
    )
    assert result["ADA"] == (D(0), D(0))
    assert [result[name] for name in ("BTC", "ETH", "SOL")] == [(D(0), D(3000))] * 3

    # Free cash is 2006 (both terms, no futures open yet). With no slippage and a fee of 0.1%, a
    # futures increase of 3000 needs 3000 / 3 + 3 = 1003. BTC takes 1003 (term 1 is then
    # 2003 - 1000 = 1003, term 2 is 2003 - 120 = 1883) and ETH the other 1003; SOL is cut to 0.
    admitted = clip_increases(
        [("BTC", "futures", D(3000)), ("ETH", "futures", D(3000)), ("SOL", "futures", D(3000))],
        cash=D(2006),
        open_initial_margin=D(0),
        backing=D(2006),
        maintenance=D(0),
        costs=FLAT_COSTS,
    )
    assert admitted == (
        ("BTC", "futures", D(3000)),
        ("ETH", "futures", D(3000)),
        ("SOL", "futures", D(0)),
    )


def test_random_books_keep_each_coin_within_its_target_and_the_room() -> None:
    rng = random.Random(8)
    names = [f"C{i:02d}" for i in range(12)]
    for _ in range(300):
        equity = D(rng.randint(1000, 20000))
        book = []
        for name in names[: rng.randint(1, 12)]:
            exiting: list[Venue] = []
            if rng.random() < 0.2:
                exiting.append("spot")
            if rng.random() < 0.2:
                exiting.append("futures")
            book.append(
                coin(
                    name,
                    str(rng.randint(-1500, 3000)),
                    spot=str(rng.randint(0, 800)),
                    dust=str(rng.choice((0, 0, 0, 3, 40))),
                    futures=str(rng.randint(-800, 800)),
                    eligible=rng.random() < 0.6,
                    keeps=rng.random() < 0.3,
                    exiting=exiting,
                )
            )
        result = allocate(equity, book)
        assert list(result) == [state.coin for state in book]
        with localcontext(CONTEXT):
            check_book(equity, book, result)


def check_book(equity: Decimal, book: list[CoinState], result: Mapping[str, LegTargets]) -> None:
    """The spec's definitions, read off the inputs, against what ``allocate`` returned."""
    spot_kept = futures_kept = dust = g_e = g_n = g_s = used = D(0)
    for s in book:
        dust += s.dust_notional
        legs = result[s.coin]
        assert legs.spot >= 0
        if s.keeps_legs:  # kept as held, an exiting leg as 0
            held_spot = D(0) if "spot" in s.exiting_legs else s.spot_notional
            held_futures = D(0) if "futures" in s.exiting_legs else s.futures_notional
            assert (legs.spot, legs.futures) == (held_spot, held_futures)
            spot_kept += held_spot
            futures_kept += abs(held_futures)
            continue
        residual = s.target_notional - s.dust_notional
        if not s.eligible:
            assert legs.futures == 0
            assert 0 <= legs.spot <= max(residual, D(0))
            g_n += max(residual, D(0))
        elif residual > 0:
            assert legs.spot + legs.futures == residual
            assert 0 <= legs.spot <= residual
            g_e += residual
        else:
            assert legs.spot == 0
            assert legs.futures == residual
            g_s += -residual
        used += legs.spot + abs(legs.futures) / 3
    room = D("0.98") * equity - spot_kept - dust - futures_kept / 3
    # Whenever the eligible longs and the shorts fit on futures at all, the whole plan fits.
    if (g_e + g_s) / 3 <= room:
        assert used <= room + D("1e-40")


# --- the cash clip --------------------------------------------------------------------------


def test_cash_clip_never_takes_the_margin_ratio_below_4() -> None:
    # The spec's rule, literally. Free cash is min(term 1, term 2) with term 1 = cash - open
    # initial margin and term 2 = backing - 4 x maintenance. Normal costs: spot fee 0.001 and
    # slippage 0.0005; futures fee 0.0005 and slippage 0.0005.
    # A spot buy of n (notional at the unslipped open) needs n x 1.0005 x 1.001 = 1.0015005 n.
    # A futures increase needs n / 3 plus its fee on its own slipped notional: a long (a buy) at
    # n x 1.0005, a short (a sell) at n x 0.9995. Per unit of n that is
    # 1/3 + 0.0005 x 1.0005 = 1/3 + 0.00050025 for a long and 1/3 + 0.00049975 for a short.
    spot_rate = Fraction("1.0015005")
    long_rate = Fraction(1, 3) + Fraction("0.00050025")
    short_rate = Fraction(1, 3) + Fraction("0.00049975")

    # Spot buy, the cushion is the smaller term. 30000 of futures are open (initial margin 10000,
    # maintenance 300 so 4 x maintenance = 1200). Cash 12000, backing 2500 (the longs are 9500
    # down). Term 1 = 12000 - 10000 = 2000 and term 2 = 2500 - 1200 = 1300, so the buy is cut to
    # 1300 / 1.0015005 = 1298.05..: backing falls to 1200 = 4 x maintenance, a ratio of exactly 4.
    (spot,) = clip_increases(
        [("ADA", "spot", D(5000))], D(12000), D(10000), D(2500), D(300), NORMAL
    )
    assert spot[:2] == ("ADA", "spot") and cut_to(spot[2], Fraction(1300) / spot_rate)
    assert 2500 - to_fraction(spot[2]) * spot_rate >= 4 * 300  # ratio >= 4 after the buy
    assert 12000 - to_fraction(spot[2]) * spot_rate >= 10000

    # Futures long, the cash term is the smaller. No position yet, cash = backing = 5000, so free
    # cash is 5000 and n = 5000 / 0.33383358333.. = 14977.52.. Afterwards cash - margin is 0 and
    # the ratio is (5000 - 0.00100025 n) / (0.01 n) = 33.3.. >= 4.
    (cash_bound,) = clip_increases(
        [("BTC", "futures", D(20000))], D(5000), D(0), D(5000), D(0), NORMAL
    )
    assert cash_bound[:2] == ("BTC", "futures")
    assert cut_to(cash_bound[2], Fraction(5000) / long_rate)
    n = to_fraction(cash_bound[2])
    assert (5000 - n * Fraction("0.00100025")) / (Fraction("0.01") * n) >= 4

    # Futures long, the cushion is the smaller term: cash 20000, initial margin 10000 and
    # maintenance 300 (30000 open), backing 2000 (the longs are 18000 down). Term 1 = 10000 and
    # term 2 = 2000 - 1200 = 800, so free cash is 800 and the increase is cut to
    # 800 / 0.33383358333.. = 2396.4.. Its fee, slippage loss and added maintenance take
    # 0.04100025 n = 98.2.. of the 800 of term 2, so the ratio stays above 4.
    (cushion_bound,) = clip_increases(
        [("BTC", "futures", D(25000))], D(20000), D(10000), D(2000), D(300), NORMAL
    )
    assert cut_to(cushion_bound[2], Fraction(800) / long_rate)
    n = to_fraction(cushion_bound[2])
    backing = 2000 - n * Fraction("0.00100025")
    assert backing / (300 + Fraction("0.01") * n) > 4  # a ratio above 4 ...
    assert n / 3 + n * Fraction("0.00050025") <= 800  # ... and the need fits in free cash

    # A short increase is a negative notional; its fee is charged on the sell price n x 0.9995,
    # so the same free cash pays for a little more of it. Admitted amounts keep the sign.
    (short,) = clip_increases([("BTC", "futures", D(-20000))], D(5000), D(0), D(5000), D(0), NORMAL)
    assert short[2] < 0 and cut_to(short[2].copy_abs(), Fraction(5000) / short_rate)
    assert short[2].copy_abs() > cash_bound[2]
    n = to_fraction(short[2].copy_abs())
    assert (5000 - n * Fraction("0.00099975")) / (Fraction("0.01") * n) >= 4

    # An increase small enough is admitted as asked, the very same Decimal (a short too).
    asked, asked_short = D("100.5"), D("-100.5")
    ((_, _, whole), (_, _, whole_short)) = clip_increases(
        [("ADA", "spot", asked), ("ADA", "futures", asked_short)],
        D(12000),
        D(0),
        D(12000),
        D(0),
        NORMAL,
    )
    assert whole is asked and whole_short is asked_short

    # Below a ratio of 4 (backing 1100 against maintenance 300) nothing is made, spot or futures,
    # however much cash there is: term 2 = 1100 - 1200 = -100.
    below = clip_increases(
        [("ADA", "spot", D(100)), ("ADA", "futures", D(100)), ("ADA", "futures", D(-100))],
        D(50000),
        D(10000),
        D(1100),
        D(300),
        NORMAL,
    )
    assert below == (("ADA", "spot", D(0)), ("ADA", "futures", D(0)), ("ADA", "futures", D(0)))
    # Likewise when the wallet is below the initial margin (term 1 = 9000 - 10000 < 0).
    short_of_margin = clip_increases(
        [("ADA", "spot", D(100))], D(9000), D(10000), D(9000), D(0), NORMAL
    )
    assert short_of_margin == (("ADA", "spot", D(0)),)


def test_cash_clip_order_is_alphabetical_spot_before_futures() -> None:
    # No slippage, fee 0.1% on both venues. Cash = backing = 2004, nothing open.
    # ADA spot 1000: needs 1000 x 1.001 = 1001 of free cash 2004: admitted 1000. Cash and
    # backing are now 1003.
    # ADA futures 3000: needs 3000 / 3 + 3 = 1003 of free cash 1003: admitted 3000. Cash is now
    # 1000, initial margin 1000, backing 1000, maintenance 30: term 1 = 0 and term 2 = 880.
    # BTC spot and BTC futures then find term 1 empty: 0, kept in the result so the caller can
    # record each cut.
    ordered = [
        ("ADA", "spot", D(1000)),
        ("ADA", "futures", D(3000)),
        ("BTC", "spot", D(1000)),
        ("BTC", "futures", D(3000)),
    ]
    admitted = clip_increases(ordered, D(2004), D(0), D(2004), D(0), FLAT_COSTS)
    assert admitted == (
        ("ADA", "spot", D(1000)),
        ("ADA", "futures", D(3000)),
        ("BTC", "spot", D(0)),
        ("BTC", "futures", D(0)),
    )

    # Taken in the order given: the same increases with BTC first go to BTC. BTC futures 3000
    # consumes 1003 (cash 2001, margin 1000, term 1 = 1001); BTC spot 1000 consumes 1001 and
    # empties term 1; then ADA gets nothing.
    reversed_order = list(reversed(ordered))
    assert clip_increases(reversed_order, D(2004), D(0), D(2004), D(0), FLAT_COSTS) == (
        ("BTC", "futures", D(3000)),
        ("BTC", "spot", D(1000)),
        ("ADA", "futures", D(0)),
        ("ADA", "spot", D(0)),
    )

    # Within one coin the spot leg goes first. Cash = backing = 2004.002, asks of 3000 on each.
    # Spot first: 2004.002 / 1.001 = 2002 on spot (term 1 left at 0), then 0 on futures.
    # Futures first: 3000 on futures (1003 of term 1), then the spot buy gets
    # (2004.002 - 1003) / 1.001 = 1000.0019.. of the 3000 asked.
    cash = D("2004.002")
    spot_first = clip_increases(
        [("ADA", "spot", D(3000)), ("ADA", "futures", D(3000))], cash, D(0), cash, D(0), FLAT_COSTS
    )
    assert spot_first[0][:2] == ("ADA", "spot") and spot_first[0][2] == D(2002)
    assert spot_first[1] == ("ADA", "futures", D(0))
    futures_first = clip_increases(
        [("ADA", "futures", D(3000)), ("ADA", "spot", D(3000))], cash, D(0), cash, D(0), FLAT_COSTS
    )
    assert futures_first[0] == ("ADA", "futures", D(3000))
    assert futures_first[1][:2] == ("ADA", "spot")
    assert cut_to(futures_first[1][2], (Fraction("2004.002") - 1003) / Fraction("1.001"))


def test_cash_clip_updates_every_term_before_the_next_increase() -> None:
    # A futures increase raises the initial margin and the maintenance, which the later spot buy
    # must see. No slippage, fee 0.1%. Cash = backing = 1500, nothing open.
    # BTC futures 3000 needs 1000 + 3 = 1003 of free cash 1500 and is admitted. Then cash is 1497
    # (its fee), initial margin 1000, backing 1497 and maintenance 30: term 1 = 497 and term 2 =
    # 1497 - 4 x 30 = 1377. ETH spot 1000 needs 1001 against free cash 497: admitted
    # 497 / 1.001 = 496.5..
    admitted = clip_increases(
        [("BTC", "futures", D(3000)), ("ETH", "spot", D(1000))],
        D(1500),
        D(0),
        D(1500),
        D(0),
        FLAT_COSTS,
    )
    assert admitted[0] == ("BTC", "futures", D(3000))
    assert admitted[1][:2] == ("ETH", "spot")
    assert cut_to(admitted[1][2], Fraction(497) / Fraction("1.001"))

    # The maintenance and the backing it adds up to are carried too. 3000 of futures are open
    # (initial margin 1000, maintenance 30), cash 3000 and backing 1300 (a loss of 1700), so
    # term 1 = 2000 and term 2 = 1300 - 4 x 30 = 1180, so free cash is 1180. Normal costs. BTC
    # futures 600 needs 600 / 3 + 600 x 0.00050025 = 200.30015 and is admitted. Its fee comes off
    # cash and its fee plus its slippage loss at the open, 600 x 0.0005 = 0.3, off backing; it
    # adds 200 of initial margin and 6 of maintenance: cash 2999.69985, initial margin 1200,
    # backing 1299.39985 and maintenance 36 give term 1 = 1799.69985 and term 2 = 1299.39985 -
    # 144 = 1155.39985. The ETH spot buy of 2000 is then bound by free cash 1155.39985 (term 2):
    # 1155.39985 / 1.0015005 = 1153.67.. (term 1 alone would allow 1797.0).
    admitted = clip_increases(
        [("BTC", "futures", D(600)), ("ETH", "spot", D(2000))],
        D(3000),
        D(1000),
        D(1300),
        D(30),
        NORMAL,
    )
    assert admitted[0] == ("BTC", "futures", D(600))
    assert admitted[1][:2] == ("ETH", "spot")
    assert cut_to(admitted[1][2], Fraction("1155.39985") / Fraction("1.0015005"))


def book_fill(
    ledger: Ledger,
    clock: int,
    venue: Venue,
    symbol: str,
    side: int,
    quantity: Decimal,
    open_price: Decimal,
) -> None:
    costs = NORMAL[venue]
    price = fill_price(open_price, side, costs)
    ledger.fill(Fill(clock, venue, symbol, side, quantity, price, fee(quantity, price, costs), "t"))


def initial_margin(ledger: Ledger, opens: dict[str, Decimal]) -> Decimal:
    """Ruling R2: the futures notional at the open, divided by 3."""
    with localcontext(CONTEXT):
        notional = sum(
            (
                abs(q) * opens[symbol]
                for (venue, symbol), q in ledger.positions().items()
                if venue == "futures"
            ),
            D(0),
        )
        return notional / 3


NAMES = ("AAAUSDT", "BBBUSDT", "CCCUSDT")


def random_account(
    rng: random.Random,
) -> tuple[Ledger, dict[str, Decimal], dict[str, int], dict[tuple[Venue, str], Decimal]]:
    """A ledger holding random futures (long or short) and spot, the fill hour's opens, each
    coin's futures side and the prices that mark it.

    Half the accounts are a crash: every position is marked against its holder and the cash is
    set so that backing - 4 x maintenance is a few USDT, while cash - initial margin is large.
    There the cushion, not the cash, is what limits a futures increase."""
    entries = {name: D(rng.choice((10, 20, 50, 100, 200))) for name in NAMES}
    sides = {name: rng.choice((1, -1)) for name in NAMES}
    crash = rng.random() < 0.5
    factors = ("0.5", "0.8", "0.95", "1", "1.05", "1.3")
    opens = {
        name: entries[name]
        * D(("0.5" if sides[name] > 0 else "1.5") if crash else rng.choice(factors))
        for name in NAMES
    }
    plan: list[tuple[Venue, str, int, Decimal]] = []
    for name in NAMES:
        if rng.random() < 0.8:
            quantity = D(rng.randint(1, 400)) / 10
            plan.append(("futures", name, sides[name], quantity * (10 if crash else 1)))
        if rng.random() < 0.5:
            plan.append(("spot", name, 1, D(rng.randint(1, 300)) / 10))
    prices: dict[tuple[Venue, str], Decimal] = {}
    for name in NAMES:
        prices[("futures", name)] = opens[name]
        prices[("spot", name)] = opens[name]

    def build(initial_cash: Decimal) -> Ledger:
        ledger = Ledger(initial_cash)
        for index, (venue, name, side, quantity) in enumerate(plan):
            book_fill(ledger, index * HOUR_MS, venue, name, side, quantity, entries[name])
        return ledger

    if not crash:
        return build(D(rng.randint(3000, 30000))), opens, sides, prices
    scratch = build(D(10**7)).mark(prices)
    outflow = D(10**7) - scratch.cash  # spot purchases and fees
    slack = D(rng.choice((0, 5, 50, 500)))
    needed = -scratch.futures_upnl + 4 * scratch.maintenance + slack
    return build(outflow + needed), opens, sides, prices


def test_admitted_increases_keep_the_ledgers_cash_and_cushion_terms_non_negative() -> None:
    # The literal rule's admission against the real ledger. Random accounts hold futures and
    # spot; random increases (futures ones signed, a short being negative) are clipped, floored
    # to a step like the caller does, and booked at their slipped fill price with their fee.
    # After every fill, cash - initial margin and backing - 4 x maintenance must both be >= 0,
    # and after every futures increase the margin ratio must be >= 4.
    rng = random.Random(20261020)
    rules = VenueRules(D("0.1"), D("0.1"), D(100000), D(5), D("0.01"))
    tolerance = D("1e-40")  # the initial margin / 3 is a 60-digit Decimal
    blocked = cut = filled = shorts = cushion_smaller = 0
    for _ in range(300):
        ledger, opens, sides, prices = random_account(rng)
        clock = 1000 * HOUR_MS
        mark = ledger.mark(prices)
        margin = initial_margin(ledger, opens)
        starts_clear = mark.cash - margin >= 0 and mark.backing - 4 * mark.maintenance >= 0

        asks: list[tuple[str, Venue, Decimal]] = []
        for name in NAMES:
            asks.append((name, "spot", D(rng.choice((0, rng.randint(0, 20000))))))
            asks.append((name, "futures", sides[name] * D(rng.randint(0, 40000))))
        admitted = clip_increases(asks, mark.cash, margin, mark.backing, mark.maintenance, NORMAL)
        assert [(a, v) for a, v, _ in admitted] == [(a, v) for a, v, _ in asks]
        for (name, venue, amount), (_, _, wanted) in zip(admitted, asks, strict=True):
            size, asked = amount.copy_abs(), wanted.copy_abs()
            assert 0 <= size <= asked
            assert amount == 0 or (amount < 0) == (wanted < 0)  # the sign is kept
            if not starts_clear:
                assert amount == 0
                continue
            cut += size < asked
            quantity = floor_quantity(to_venue_quantity(size, opens[name]), rules)
            if quantity < rules.min_qty:
                continue
            before = ledger.mark(prices)
            term_one = before.cash - initial_margin(ledger, opens)
            term_two = before.backing - 4 * before.maintenance
            cushion_smaller += venue == "futures" and size < asked and term_two < term_one
            side = 1 if venue == "spot" else sides[name]
            shorts += side < 0
            book_fill(ledger, clock, venue, name, side, quantity, opens[name])
            clock += HOUR_MS
            filled += 1
            now = ledger.mark(prices)
            assert now.cash - initial_margin(ledger, opens) >= -tolerance
            assert now.backing - 4 * now.maintenance >= -tolerance
            if venue == "futures":
                assert now.ratio is not None and now.ratio >= 4 - tolerance
        blocked += not starts_clear
    # The run does reach the cases it is there for.
    assert filled > 300 and cut > 100 and blocked > 0 and shorts > 50 and cushion_smaller > 10


# --- the venue's units ----------------------------------------------------------------------


def test_a_multiplier_perpetual_is_sized_in_contracts_from_notional() -> None:
    # 1000SHIBUSDT: one contract is 1000 coins, so it trades at 1000 x the coin's price.
    # The coin is at 0.000012, the contract at 0.012. A futures notional of 1000 USDT is
    # 1000 / 0.012 = 83333.33.. contracts, truncated (never rounded up) to 60 digits.
    coin_price = D("0.000012")
    multiplier = 1000
    contract_price = coin_price * multiplier
    assert contract_price == D("0.012")

    contracts = to_venue_quantity(D(1000), contract_price)
    assert contracts == D("83333." + "3" * 55)  # 5 + 55 = 60 significant digits
    assert to_fraction(contracts) < Fraction(1000) / to_fraction(contract_price)  # not up

    # Sizing by the coin's price instead would order 1000 times too many contracts.
    by_coin_price = to_venue_quantity(D(1000), coin_price)
    assert by_coin_price == D("83333333." + "3" * 52)
    assert by_coin_price // contracts == multiplier

    # A whole number of contracts: the floor to the step never exceeds the true quotient, and
    # the leg plan on the contract price orders 83333 contracts, worth 999.996 USDT.
    rules = VenueRules(D(1), D(1), D(10_000_000), D(5), D("0.000001"))
    assert floor_quantity(contracts, rules) == D(83333)
    plan = plan_leg("futures", D(0), contracts, contract_price, rules)
    assert [(o.side, o.quantity) for o in plan.orders] == [(1, D(83333))]
    assert D(83333) * contract_price == D("999.996")

    # A short sizes to a negative quantity, truncated toward zero.
    assert to_venue_quantity(D(-1000), contract_price) == contracts.copy_negate()
    # An exact quotient stays exact, and 0 stays 0.
    assert to_venue_quantity(D(600), contract_price) == D(50000)
    assert to_venue_quantity(D(0), contract_price) == 0


def test_the_truncation_never_rounds_up() -> None:
    rng = random.Random(3)
    for _ in range(200):
        notional = D(rng.randint(1, 10**9)) / D(rng.choice((1, 10, 1000)))
        price = D(rng.randint(1, 10**7)) / D(rng.choice((1000, 10**6, 10**8)))
        result = to_venue_quantity(notional, price)
        exact = to_fraction(notional) / to_fraction(price)
        assert 0 < to_fraction(result) <= exact
        assert len(result.as_tuple().digits) <= 60
        assert exact - to_fraction(result) < exact * Fraction(1, 10**59)


def test_a_tiny_quotient_keeps_at_most_100_decimals_so_the_order_helpers_take_it() -> None:
    # 60 significant digits of 1e-45 / 7 would need 104 decimal places; the quantity is cut at
    # 100 (still toward zero), which floor_quantity and plan_leg accept.
    tiny = to_venue_quantity(D("1e-45"), D(7))
    assert tiny.as_tuple().exponent == -100
    assert 0 < to_fraction(tiny) <= Fraction(1, 10**45) / 7
    rules = VenueRules(D("0.001"), D("0.001"), D(100), D(5), D("0.01"))
    assert floor_quantity(tiny, rules) == 0
    # A split can leave a tiny share with more digits than that (a 60-digit scale times a
    # residual); it is accepted as a target and converts to a bounded quantity.
    share = LegTargets(D("1e-118"), D("-1e-118"))
    assert to_venue_quantity(share.spot, D(7)).as_tuple().exponent == -100
    # The clip cuts an increase to the same bounded form.
    (leftover,) = clip_increases(
        [("ADA", "spot", D(5))], D("1e-45"), D(0), D("1e-45"), D(0), FLAT_COSTS
    )
    assert leftover[2].as_tuple().exponent == -100
    assert 0 < to_fraction(leftover[2]) <= Fraction(1, 10**45) / Fraction("1.001")


# --- refusals -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"coin": "btc"},
        {"coin": "B"},
        {"target_notional": 1.5},
        {"target_notional": D("NaN")},
        {"spot_notional": D(-1)},
        {"dust_notional": D(-1)},
        {"futures_notional": D("Infinity")},
        {"eligible": 1},
        {"keeps_legs": "yes"},
        {"exiting_legs": ["spot"]},
        {"exiting_legs": frozenset({"margin"})},
    ],
)
def test_a_coin_state_refuses_bad_input(changes: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "coin": "BTC",
        "target_notional": D(100),
        "spot_notional": D(0),
        "dust_notional": D(0),
        "futures_notional": D(0),
        "eligible": True,
        "keeps_legs": False,
        "exiting_legs": frozenset(),
    }
    with pytest.raises(ValueError):
        CoinState(**(fields | changes))


def test_allocate_and_leg_targets_refuse_bad_input() -> None:
    with pytest.raises(ValueError, match="twice"):
        allocate(D(1000), [coin("BTC", "10"), coin("BTC", "20")])
    with pytest.raises(ValueError, match="equity"):
        allocate(1000, [coin("BTC", "10")])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="CoinState"):
        allocate(D(1000), ["BTC"])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        LegTargets(D(-1), D(0))
    with pytest.raises(ValueError):
        LegTargets(D(0), 1.5)  # type: ignore[arg-type]
    legs = LegTargets(D(1), D(-2))
    with pytest.raises(FrozenInstanceError):
        legs.spot = D(2)  # type: ignore[misc]
    with pytest.raises(TypeError):
        allocate(D(1000), [coin("BTC", "10")])["BTC"] = legs  # type: ignore[index]


def test_the_clip_and_the_quantity_helper_refuse_bad_input() -> None:
    ok: dict[str, Any] = {
        "cash": D(1000),
        "open_initial_margin": D(0),
        "backing": D(1000),
        "maintenance": D(0),
        "costs": NORMAL,
    }

    def clip(increases: Sequence[Any], **changes: Any) -> Any:
        return clip_increases(increases, **(ok | changes))

    assert clip([]) == ()
    with pytest.raises(ValueError, match="venue"):
        clip([("ADA", "margin", D(1))])
    with pytest.raises(ValueError, match="notional"):
        clip([("ADA", "spot", D(-1))])
    with pytest.raises(ValueError, match="notional"):
        clip([("ADA", "spot", 1.5)])
    clip([("ADA", "futures", D(-1))])  # a short increase is a negative futures notional
    wild = Costs(D("0.0005"), D("0.3"), D("0.5"))  # a slippage above 1/3 - 0.04
    with pytest.raises(ValueError, match="slippage"):
        clip([("ADA", "futures", D(1))], costs={"spot": NORMAL["spot"], "futures": wild})
    with pytest.raises(ValueError, match="symbol"):
        clip([("ada", "spot", D(1))])
    with pytest.raises(ValueError, match="increase"):
        clip([("ADA", "spot")])
    with pytest.raises(ValueError, match="maintenance"):
        clip([("ADA", "spot", D(1))], maintenance=D(-1))
    with pytest.raises(ValueError, match="open_initial_margin"):
        clip([("ADA", "spot", D(1))], open_initial_margin=D(-1))
    with pytest.raises(ValueError, match="cash"):
        clip([("ADA", "spot", D(1))], cash=1000)
    with pytest.raises(ValueError, match="futures"):
        clip([("ADA", "futures", D(1))], costs={"spot": NORMAL["spot"]})
    odd = SimpleNamespace(fee_rate=1.5, slippage_rate=D(0))
    with pytest.raises(ValueError, match="fee_rate"):
        clip([("ADA", "spot", D(1))], costs={"spot": odd, "futures": NORMAL["futures"]})
    for bad_price in (D(0), D(-1), D("NaN"), 1.5):
        with pytest.raises(ValueError, match="price"):
            to_venue_quantity(D(100), bad_price)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="notional"):
        to_venue_quantity(D("Infinity"), D(1))
