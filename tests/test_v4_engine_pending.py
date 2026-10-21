"""V4 engine task 5: pending daily decisions, mandatory exit legs and replacement spot buys.

The book is driven by hand with synthetic hours; no price, no pack and no network is involved.
V3's ``trend.pending.PendingDecisions`` is the differential oracle, called here only on pre-2025
hours: for decisions and fills V4's book must agree with it.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.pending import PendingDecisions as V3PendingDecisions
from crypto_grid_bot.v4.engine.pending import Decided, Exit, Pending, PendingBook, Venue

D = Decimal
HOUR = 3_600_000
DAY = 24 * HOUR
T = month_bounds_ms("2021-01")[0]


def always(_coin: str) -> bool:
    return True


def never(_coin: str) -> bool:
    return False


def only(*coins: str) -> Callable[[str], bool]:
    return lambda coin: coin in coins


def every_bar(_coin: str, _venue: Venue) -> bool:
    return True


def coins_of(orders: tuple[Pending, ...]) -> list[str]:
    return [order.coin for order in orders]


# ---------------------------------------------------------------------------------------
# Daily decisions: the 00:00 replacement rule, the no-bar rule and deferral
# ---------------------------------------------------------------------------------------


def test_midnight_decision_replaces_a_deferred_order() -> None:
    book = PendingBook()
    first = book.decide(T, {"BTC": D(".1")})
    assert first == Decided(cancelled=(), cancelled_replacements=())
    # The coin has no usable hour all day: the order stays pending.
    for hour in range(24):
        assert book.due(T + hour * HOUR, never) == ()
    # At the next midnight the old order would fill, but the new decision replaces it first.
    second = book.decide(T + DAY, {"BTC": D("-.2")})
    assert second.cancelled == (Pending("BTC", T, D(".1")),)
    assert book.due(T + DAY, always) == ()
    assert book.due(T + DAY + HOUR, always) == (Pending("BTC", T + DAY, D("-.2")),)
    assert book.due(T + DAY + 2 * HOUR, always) == ()


def test_no_bar_day_keeps_the_pending_order() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    for hour in range(24):
        assert book.due(T + hour * HOUR, never) == ()
    # A no-bar day: BTC is absent from the day's targets, so its old order is kept...
    result = book.decide(T + DAY, {"ETH": D(".3")})
    assert result.cancelled == ()
    # ...and may still fill at 00:00 of that very day, as in V3.
    assert book.due(T + DAY, only("BTC")) == (Pending("BTC", T, D(".1")),)
    assert book.due(T + DAY + HOUR, always) == (Pending("ETH", T + DAY, D(".3")),)


def test_a_day_with_no_targets_at_all_cancels_nothing() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1"), "ETH": D("-.1")})
    assert book.decide(T + DAY, {}) == Decided((), ())
    assert coins_of(book.due(T + DAY, always)) == ["BTC", "ETH"]


def test_each_coin_waits_for_its_own_first_ready_hour() -> None:
    book = PendingBook()
    book.decide(T, {"ETH": D(".2"), "BTC": D(0)})
    assert coins_of(book.due(T + HOUR, only("ETH"))) == ["ETH"]
    assert coins_of(book.due(T + 2 * HOUR, only("BTC"))) == ["BTC"]
    assert book.due(T + 3 * HOUR, always) == ()


def test_orders_that_are_ready_together_come_back_in_coin_order() -> None:
    book = PendingBook()
    book.decide(T, {"SOL": D(".1"), "BTC": D(".1"), "ETH": D(".1")})
    assert coins_of(book.due(T + HOUR, always)) == ["BTC", "ETH", "SOL"]


def test_a_new_decision_cannot_fill_in_its_own_hour() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    assert book.due(T, always) == ()
    assert coins_of(book.due(T + HOUR, always)) == ["BTC"]
    # The same holds at a later midnight, when the coin has no older order.
    book.decide(T + DAY, {"BTC": D(".2")})
    assert book.due(T + DAY, always) == ()
    assert book.due(T + DAY + HOUR, always) == (Pending("BTC", T + DAY, D(".2")),)


def test_ready_is_asked_only_for_orders_that_are_old_enough() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    asked: list[str] = []

    def spy(coin: str) -> bool:
        asked.append(coin)
        return True

    assert book.due(T, spy) == ()
    assert asked == []
    assert coins_of(book.due(T + HOUR, spy)) == ["BTC"]
    assert asked == ["BTC"]


def test_a_zero_target_is_an_order_too() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(0)})
    assert book.due(T + HOUR, always) == (Pending("BTC", T, D(0)),)


@pytest.mark.parametrize("seed", range(8))
def test_agrees_with_v3_on_random_decisions_and_masked_hours(seed: int) -> None:
    rng = random.Random(seed)
    coins = ["AAA", "BTC", "ETH", "SOL", "XRP"]
    oracle = V3PendingDecisions()
    book = PendingBook()
    for hour in range(8 * 24):
        hour_ms = T + hour * HOUR
        targets: dict[str, Decimal] = {}
        if hour % 24 == 0:
            targets = {c: D(rng.randint(-100, 100)) / 100 for c in coins if rng.random() < 0.7}
        usable = {c for c in coins if rng.random() < 0.3}
        dispatch = oracle.advance(hour_ms, targets, usable)
        if hour % 24 == 0:
            decided = book.decide(hour_ms, targets)
            assert [(s, p.decision_ms, p.weight) for s, p in dispatch.cancelled] == [
                (o.coin, o.decision_ms, o.target) for o in decided.cancelled
            ]
        fills = book.due(hour_ms, lambda coin, usable=usable: coin in usable)
        assert [(s, p.decision_ms, p.weight) for s, p in dispatch.ready] == [
            (o.coin, o.decision_ms, o.target) for o in fills
        ]


# ---------------------------------------------------------------------------------------
# Refused calls change nothing
# ---------------------------------------------------------------------------------------

BAD_TARGET_SETS: list[Any] = [
    {"BTC": D("NaN")},
    {"BTC": D("sNaN")},
    {"BTC": D("Infinity")},
    {"BTC": D("-Infinity")},
    {"BTC": D("1.0000001")},
    {"BTC": D("-1.0000001")},
    {"BTC": 0.1},
    {"BTC": 0},
    {"BTC": "0.1"},
    {"BTC": True},
    {"BTC": None},
    {"btc": D(".1")},
    {"B": D(".1")},
    {"X" * 31: D(".1")},
    {"BTC-USDT": D(".1")},
    {"BTC ": D(".1")},
    {1: D(".1")},
    {None: D(".1")},
    # A bad entry after good ones must not leave the good ones half applied.
    {"AAA": D(".5"), "BTC": D("NaN")},
    {"AAA": D(".5"), "BTC": D(".1"), "ETH": D("2")},
    {"AAA": D(".5"), "bad": D(".1")},
    {"AAA": D(".5"), 1: D(".1")},
    {1: D(".1"), "AAA": D(".5")},
    [("AAA", D(".5"))],
    None,
]


@pytest.mark.parametrize("targets", BAD_TARGET_SETS)
def test_bad_decision_batch_does_not_cancel_or_advance(targets: Any) -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1"), "ETH": D(".2")})
    book.schedule_replacement("AAA", T + HOUR)
    with pytest.raises(ValueError):
        book.decide(T + DAY, targets)
    # Nothing was cancelled, replaced or advanced: the old orders and the replacement are
    # intact, and the same midnight still takes a good decision.
    assert book.due(T + HOUR, only("BTC")) == (Pending("BTC", T, D(".1")),)
    assert book.due_replacements(T + HOUR, always) == ("AAA",)
    good = book.decide(T + DAY, {"ETH": D(".4")})
    assert good.cancelled == (Pending("ETH", T, D(".2")),)


def test_bad_decision_batch_keeps_the_replacement_pending() -> None:
    book = PendingBook()
    book.schedule_replacement("AAA", T + HOUR)
    with pytest.raises(ValueError):
        book.decide(T + DAY, {"AAA": D(".5"), "BTC": D("NaN")})
    assert book.due_replacements(T + HOUR, always) == ("AAA",)


@pytest.mark.parametrize(
    "hour", [T + HOUR, T + 1, T + 12 * HOUR, T - DAY - 1, -DAY, 1.0 * (T + DAY), True, None, "x"]
)
def test_a_decision_is_midnight_only(hour: Any) -> None:
    book = PendingBook()
    with pytest.raises(ValueError):
        book.decide(hour, {})
    with pytest.raises(ValueError):
        book.decide(hour, {"BTC": D(0)})


def test_duplicate_hour_and_nonmidnight_decisions_are_rejected() -> None:
    book = PendingBook()
    book.decide(T, {})
    with pytest.raises(ValueError):
        book.decide(T, {})
    with pytest.raises(ValueError):
        book.decide(T + HOUR, {"BTC": D(0)})
    with pytest.raises(ValueError):
        book.decide(T + HOUR, {})


def test_decisions_must_move_forward() -> None:
    book = PendingBook()
    book.decide(T + DAY, {"BTC": D(".1")})
    with pytest.raises(ValueError):
        book.decide(T, {"BTC": D(".2")})
    with pytest.raises(ValueError):
        book.decide(T + DAY, {"BTC": D(".2")})
    assert book.due(T + DAY + HOUR, always) == (Pending("BTC", T + DAY, D(".1")),)


def test_a_decision_comes_before_the_fills_of_its_hour() -> None:
    book = PendingBook()
    book.decide(T, {})
    assert book.due(T + DAY, always) == ()
    with pytest.raises(ValueError, match="before"):
        book.decide(T + DAY, {"BTC": D(0)})
    book.decide(T + 2 * DAY, {"BTC": D(0)})  # the next midnight is fine


# ---------------------------------------------------------------------------------------
# The hour clocks
# ---------------------------------------------------------------------------------------


def test_due_hours_must_increase() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    assert book.due(T + HOUR, never) == ()
    with pytest.raises(ValueError):
        book.due(T + HOUR, always)
    with pytest.raises(ValueError):
        book.due(T, always)
    # A refused call changed nothing.
    assert coins_of(book.due(T + 2 * HOUR, always)) == ["BTC"]


@pytest.mark.parametrize("hour", [T + 1, T + 90 * 60 * 1000, -HOUR, 1.0 * (T + HOUR), True, None])
def test_due_hours_must_be_aligned_ints(hour: Any) -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    with pytest.raises(ValueError):
        book.due(hour, always)
    with pytest.raises(ValueError):
        book.due_exits(hour, every_bar)
    with pytest.raises(ValueError):
        book.due_replacements(hour, always)
    assert coins_of(book.due(T + HOUR, always)) == ["BTC"]


def test_the_three_due_methods_keep_their_own_clocks() -> None:
    book = PendingBook()
    book.decide(T, {})
    assert book.due(T + HOUR, always) == ()
    assert book.due_exits(T + HOUR, every_bar) == ()
    assert book.due_replacements(T + HOUR, always) == ()
    for refuse in (
        lambda: book.due(T + HOUR, always),
        lambda: book.due_exits(T + HOUR, every_bar),
        lambda: book.due_replacements(T + HOUR, always),
    ):
        with pytest.raises(ValueError):
            refuse()


def test_a_due_hour_cannot_precede_the_latest_decision() -> None:
    book = PendingBook()
    book.decide(T + DAY, {"BTC": D(".1")})
    for refuse in (
        lambda: book.due(T + 23 * HOUR, always),
        lambda: book.due_exits(T + 23 * HOUR, every_bar),
        lambda: book.due_replacements(T + 23 * HOUR, always),
    ):
        with pytest.raises(ValueError):
            refuse()
    assert book.due(T + DAY, always) == ()  # the decision's own hour is fine


def test_a_failing_ready_callback_changes_nothing() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1"), "ETH": D(".2")})

    def broken(coin: str) -> bool:
        if coin == "ETH":
            raise RuntimeError("no data")
        return True

    with pytest.raises(RuntimeError):
        book.due(T + HOUR, broken)
    # BTC was not consumed and the hour is still open for a retry.
    assert coins_of(book.due(T + HOUR, always)) == ["BTC", "ETH"]


@pytest.mark.parametrize("answer", [1, 0, None, "yes", D(1)])
def test_ready_must_answer_with_a_bool(answer: Any) -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    with pytest.raises(ValueError, match="bool"):
        book.due(T + HOUR, lambda _coin: answer)
    assert coins_of(book.due(T + HOUR, always)) == ["BTC"]


# ---------------------------------------------------------------------------------------
# Mandatory exits: one leg per venue, each on its own venue's first bar
# ---------------------------------------------------------------------------------------


def test_mandatory_exit_legs_close_independently_per_venue() -> None:
    book = PendingBook()
    spot = Exit("BTC", "spot", "universe exit", T + HOUR)
    futures = Exit("BTC", "futures", "universe exit", T + HOUR)
    book.schedule_exit(spot)
    book.schedule_exit(futures)
    bars = {("BTC", "spot"): False, ("BTC", "futures"): False}

    def has_bar(coin: str, venue: str) -> bool:
        return bars[(coin, venue)]

    assert book.due_exits(T, every_bar) == ()  # the fill hour is the decision hour + 1h
    assert book.due_exits(T + HOUR, has_bar) == ()  # neither venue has a bar
    bars[("BTC", "spot")] = True
    assert book.due_exits(T + 2 * HOUR, has_bar) == (spot,)  # spot goes alone
    assert book.due_exits(T + 3 * HOUR, has_bar) == ()  # futures still has no bar
    bars[("BTC", "futures")] = True
    assert book.due_exits(T + 4 * HOUR, has_bar) == (futures,)
    assert book.due_exits(T + 5 * HOUR, every_bar) == ()  # each leg went once


def test_a_funding_month_exit_is_one_futures_leg() -> None:
    book = PendingBook()
    leg = Exit("ETH", "futures", "funding-month exit", T + HOUR)
    book.schedule_exit(leg)
    asked: list[tuple[str, str]] = []

    def has_bar(coin: str, venue: str) -> bool:
        asked.append((coin, venue))
        return True

    assert book.due_exits(T + HOUR, has_bar) == (leg,)
    assert asked == [("ETH", "futures")]


def test_exits_wait_for_after_ms_and_ask_for_a_bar_only_then() -> None:
    book = PendingBook()
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + 3 * HOUR))
    asked: list[tuple[str, str]] = []

    def has_bar(coin: str, venue: str) -> bool:
        asked.append((coin, venue))
        return True

    assert book.due_exits(T + HOUR, has_bar) == ()
    assert book.due_exits(T + 2 * HOUR, has_bar) == ()
    assert asked == []
    assert [e.coin for e in book.due_exits(T + 3 * HOUR, has_bar)] == ["BTC"]


def test_due_exits_come_back_in_coin_then_venue_order() -> None:
    book = PendingBook()
    for coin, venue in [("SOL", "spot"), ("BTC", "spot"), ("BTC", "futures"), ("ETH", "futures")]:
        book.schedule_exit(Exit(coin, venue, "universe exit", T + HOUR))
    due = book.due_exits(T + HOUR, every_bar)
    assert [(e.coin, e.venue) for e in due] == [
        ("BTC", "futures"),
        ("BTC", "spot"),
        ("ETH", "futures"),
        ("SOL", "spot"),
    ]


def test_two_exits_for_one_leg_are_refused() -> None:
    book = PendingBook()
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + HOUR))
    with pytest.raises(ValueError, match="BTC"):
        book.schedule_exit(Exit("BTC", "spot", "funding-month exit", T + 5 * HOUR))
    # Another venue of the same coin, and the same venue of another coin, are other legs.
    book.schedule_exit(Exit("BTC", "futures", "universe exit", T + HOUR))
    book.schedule_exit(Exit("ETH", "spot", "universe exit", T + HOUR))
    assert len(book.due_exits(T + HOUR, every_bar)) == 3
    # Once a leg went, it may be scheduled again (a later month's exit).
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + 2 * HOUR))


def test_a_failing_has_bar_callback_changes_nothing() -> None:
    book = PendingBook()
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + HOUR))
    book.schedule_exit(Exit("ETH", "spot", "universe exit", T + HOUR))

    def broken(coin: str, _venue: str) -> bool:
        if coin == "ETH":
            raise RuntimeError("no data")
        return True

    with pytest.raises(RuntimeError):
        book.due_exits(T + HOUR, broken)
    assert [e.coin for e in book.due_exits(T + HOUR, every_bar)] == ["BTC", "ETH"]


def test_has_bar_must_answer_with_a_bool() -> None:
    book = PendingBook()
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + HOUR))
    with pytest.raises(ValueError, match="bool"):
        book.due_exits(T + HOUR, lambda _coin, _venue: 1)  # type: ignore[arg-type, return-value]
    assert len(book.due_exits(T + HOUR, every_bar)) == 1


def test_an_exit_for_an_hour_already_passed_is_refused() -> None:
    book = PendingBook()
    assert book.due_exits(T + 2 * HOUR, every_bar) == ()
    with pytest.raises(ValueError, match="passed"):
        book.schedule_exit(Exit("BTC", "spot", "universe exit", T + 2 * HOUR))
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + 3 * HOUR))
    assert len(book.due_exits(T + 3 * HOUR, every_bar)) == 1


def test_only_an_exit_object_can_be_scheduled() -> None:
    book = PendingBook()
    with pytest.raises(ValueError, match="Exit"):
        book.schedule_exit(("BTC", "spot", "universe exit", T + HOUR))  # type: ignore[arg-type]


def test_exit_and_pending_records_check_their_fields() -> None:
    with pytest.raises(ValueError):
        Exit("btc", "spot", "universe exit", T)
    with pytest.raises(ValueError):
        Exit("BTC", "margin", "universe exit", T)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Exit("BTC", "spot", "", T)
    with pytest.raises(ValueError):
        Exit("BTC", "spot", "universe exit", T + 1)
    with pytest.raises(ValueError):
        Exit("BTC", "spot", "universe exit", True)
    with pytest.raises(ValueError):
        Pending("BTC", T + 1, D(".1"))
    with pytest.raises(ValueError):
        Pending("BTC", T, D("NaN"))
    with pytest.raises(ValueError):
        Pending("BTC", T, D("1.5"))
    with pytest.raises(ValueError):
        Pending("BTC", T, 0.5)  # type: ignore[arg-type]
    leg = Exit("BTC", "spot", "universe exit", T)
    with pytest.raises(FrozenInstanceError):
        leg.coin = "ETH"  # type: ignore[misc]
    order = Pending("BTC", T, D(".1"))
    with pytest.raises(FrozenInstanceError):
        order.target = D(".2")  # type: ignore[misc]


# ---------------------------------------------------------------------------------------
# Replacement spot buys after a funding-month futures close
# ---------------------------------------------------------------------------------------


def test_replacement_buy_waits_for_the_futures_close_and_a_newer_target_cancels_it() -> None:
    book = PendingBook()
    book.decide(T, {})
    # The futures close filled at T + 1h: the replacement is due from that hour on.
    book.schedule_replacement("BTC", T + HOUR)
    no_spot = only()
    assert book.due_replacements(T + HOUR, no_spot) == ()
    assert book.due_replacements(T + 2 * HOUR, no_spot) == ()
    # The next midnight gives BTC a newer target: the replacement is cancelled, and only the
    # new decision's order fills, at 01:00.
    result = book.decide(T + DAY, {"BTC": D(".1")})
    assert result.cancelled_replacements == ("BTC",)
    assert result.cancelled == ()
    assert book.due_replacements(T + DAY, always) == ()
    assert book.due(T + DAY, always) == ()
    assert book.due(T + DAY + HOUR, always) == (Pending("BTC", T + DAY, D(".1")),)
    assert book.due_replacements(T + DAY + HOUR, always) == ()


def test_the_replacement_may_be_placed_in_the_hour_of_the_close() -> None:
    book = PendingBook()
    book.decide(T, {})
    book.schedule_replacement("BTC", T + HOUR)
    assert book.due_replacements(T + HOUR, only("BTC")) == ("BTC",)
    assert book.due_replacements(T + 2 * HOUR, always) == ()  # it was placed once


def test_the_replacement_waits_for_the_first_hour_with_a_spot_bar() -> None:
    book = PendingBook()
    book.schedule_replacement("BTC", T + 5 * HOUR)
    asked: list[str] = []

    def has_spot_bar(coin: str) -> bool:
        asked.append(coin)
        return len(asked) >= 2

    assert book.due_replacements(T + 4 * HOUR, has_spot_bar) == ()  # before the close
    assert asked == []
    assert book.due_replacements(T + 5 * HOUR, has_spot_bar) == ()
    assert book.due_replacements(T + 6 * HOUR, has_spot_bar) == ("BTC",)


def test_replacements_come_back_in_coin_order_and_each_coin_has_its_own_hour() -> None:
    book = PendingBook()
    book.schedule_replacement("SOL", T + HOUR)
    book.schedule_replacement("BTC", T + HOUR)
    book.schedule_replacement("ETH", T + 3 * HOUR)
    assert book.due_replacements(T + HOUR, only("SOL", "BTC")) == ("BTC", "SOL")
    assert book.due_replacements(T + 2 * HOUR, always) == ()
    assert book.due_replacements(T + 3 * HOUR, always) == ("ETH",)


def test_a_no_bar_midnight_keeps_the_replacement_pending() -> None:
    book = PendingBook()
    book.decide(T, {})
    book.schedule_replacement("BTC", T + HOUR)
    assert book.due_replacements(T + HOUR, never) == ()
    # BTC has no daily bar, so the next midnight gives it no target (ETH does).
    result = book.decide(T + DAY, {"ETH": D(".1")})
    assert result.cancelled_replacements == ()
    # The replacement fills as placed, at that midnight if spot has a bar.
    assert book.due_replacements(T + DAY, only("BTC")) == ("BTC",)


def test_a_midnight_with_no_targets_keeps_the_replacement_pending() -> None:
    book = PendingBook()
    book.schedule_replacement("BTC", T - DAY + HOUR)
    assert book.decide(T, {}) == Decided((), ())
    assert book.due_replacements(T, only("BTC")) == ("BTC",)


def test_a_replacement_and_a_cancelled_order_are_both_reported_by_one_decision() -> None:
    book = PendingBook()
    book.decide(T, {"ETH": D(".2")})
    book.schedule_replacement("BTC", T + HOUR)
    book.schedule_replacement("SOL", T + HOUR)
    result = book.decide(T + DAY, {"SOL": D(".1"), "ETH": D(".3"), "BTC": D(0)})
    assert result.cancelled == (Pending("ETH", T, D(".2")),)
    assert result.cancelled_replacements == ("BTC", "SOL")


def test_the_replacement_of_a_close_in_a_decision_hour_is_superseded_by_that_decision() -> None:
    book = PendingBook()
    # A synthetic funding-month close fills at the month's first midnight, after the day's
    # decision was made at the start of the hour. BTC got a target, ETH did not.
    book.decide(T, {"BTC": D(".1")})
    assert book.schedule_replacement("BTC", T) is False
    assert book.schedule_replacement("ETH", T) is True
    assert book.due_replacements(T, always) == ("ETH",)
    # Only the new decision's order fills, at 01:00.
    assert book.due(T + HOUR, always) == (Pending("BTC", T, D(".1")),)
    assert book.due_replacements(T + HOUR, always) == ()


def test_a_decision_before_the_close_does_not_supersede_a_later_replacement() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    # The close fills an hour after the decision hour: the decision was not made in that hour.
    assert book.schedule_replacement("BTC", T + HOUR) is True
    assert book.due_replacements(T + HOUR, always) == ("BTC",)


def test_a_replacement_for_an_hour_already_passed_is_refused() -> None:
    book = PendingBook()
    assert book.due_replacements(T + HOUR, always) == ()
    with pytest.raises(ValueError, match="passed"):
        book.schedule_replacement("BTC", T + HOUR)
    assert book.schedule_replacement("BTC", T + 2 * HOUR) is True
    assert book.due_replacements(T + 2 * HOUR, always) == ("BTC",)


def test_two_replacements_for_one_coin_are_refused() -> None:
    book = PendingBook()
    assert book.schedule_replacement("BTC", T + HOUR) is True
    with pytest.raises(ValueError, match="BTC"):
        book.schedule_replacement("BTC", T + 2 * HOUR)
    assert book.due_replacements(T + HOUR, always) == ("BTC",)
    assert book.schedule_replacement("BTC", T + 2 * HOUR) is True  # a later close


@pytest.mark.parametrize("coin", ["btc", "B", "X" * 31, "", "BTC-USDT", 1, None])
def test_replacement_and_cancel_check_the_symbol(coin: Any) -> None:
    book = PendingBook()
    with pytest.raises(ValueError):
        book.schedule_replacement(coin, T + HOUR)
    with pytest.raises(ValueError):
        book.cancel(coin)


@pytest.mark.parametrize("after", [T + 1, -HOUR, 1.0 * (T + HOUR), True, None])
def test_replacement_checks_its_hour(after: Any) -> None:
    book = PendingBook()
    with pytest.raises(ValueError):
        book.schedule_replacement("BTC", after)


def test_a_failing_spot_bar_callback_changes_nothing() -> None:
    book = PendingBook()
    book.schedule_replacement("BTC", T + HOUR)
    book.schedule_replacement("ETH", T + HOUR)

    def broken(coin: str) -> bool:
        if coin == "ETH":
            raise RuntimeError("no data")
        return True

    with pytest.raises(RuntimeError):
        book.due_replacements(T + HOUR, broken)
    assert book.due_replacements(T + HOUR, always) == ("BTC", "ETH")


# ---------------------------------------------------------------------------------------
# cancel: a universe exit, a funding-month exit or a dead-market close
# ---------------------------------------------------------------------------------------


def test_cancel_removes_the_order_and_the_replacement_and_returns_the_order() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1"), "ETH": D(".2")})
    book.schedule_replacement("BTC", T + HOUR)
    assert book.cancel("BTC") == Pending("BTC", T, D(".1"))
    assert coins_of(book.due(T + HOUR, always)) == ["ETH"]  # BTC's order is gone
    assert book.due_replacements(T + HOUR, always) == ()  # so is its replacement


def test_cancel_removes_a_replacement_that_has_no_order() -> None:
    book = PendingBook()
    book.schedule_replacement("BTC", T + HOUR)
    assert book.cancel("BTC") is None
    assert book.due_replacements(T + HOUR, always) == ()


def test_cancel_without_anything_pending_is_none() -> None:
    assert PendingBook().cancel("BTC") is None


def test_cancel_leaves_scheduled_exits_and_other_coins_alone() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1"), "ETH": D(".2")})
    book.schedule_exit(Exit("BTC", "spot", "universe exit", T + HOUR))
    book.schedule_replacement("ETH", T + HOUR)
    book.cancel("BTC")
    assert [e.coin for e in book.due_exits(T + HOUR, every_bar)] == ["BTC"]
    assert book.due_replacements(T + HOUR, always) == ("ETH",)
    assert coins_of(book.due(T + HOUR, always)) == ["ETH"]


def test_the_book_answers_whether_an_exit_or_a_replacement_is_pending() -> None:
    """The two read-only queries the hour loop uses instead of mirroring the book: an exit leg
    is scheduled until ``due_exits`` returns it, and a replacement is pending until it is
    placed, cancelled or superseded. Asking changes nothing."""
    book = PendingBook()
    assert not book.exit_scheduled("BTC", "spot") and not book.replacement_pending("BTC")
    book.schedule_exit(Exit("BTC", "futures", "funding-month exit", T + HOUR))
    assert book.exit_scheduled("BTC", "futures") and not book.exit_scheduled("BTC", "spot")
    assert not book.exit_scheduled("ETH", "futures")
    book.schedule_replacement("ETH", T + HOUR)
    book.schedule_replacement("SOL", T + HOUR)
    assert book.replacement_pending("ETH") and not book.replacement_pending("BTC")
    assert book.exit_scheduled("BTC", "futures")  # asking twice changes nothing
    assert [e.coin for e in book.due_exits(T + HOUR, every_bar)] == ["BTC"]
    assert not book.exit_scheduled("BTC", "futures")  # returned, so no longer scheduled
    book.cancel("ETH")
    assert not book.replacement_pending("ETH") and book.replacement_pending("SOL")
    book.decide(T + DAY, {"SOL": D(".1")})  # a newer target supersedes the replacement
    assert not book.replacement_pending("SOL")
    book.schedule_replacement("XRP", T + DAY + HOUR)
    assert book.due_replacements(T + DAY + HOUR, always) == ("XRP",)
    assert not book.replacement_pending("XRP")  # placed


@pytest.mark.parametrize(("coin", "venue"), [("btc", "spot"), ("BTC", "margin"), (1, "spot")])
def test_the_queries_check_the_coin_and_the_venue(coin: Any, venue: Any) -> None:
    book = PendingBook()
    with pytest.raises(ValueError):
        book.exit_scheduled(coin, venue)
    if venue == "spot":
        with pytest.raises(ValueError):
            book.replacement_pending(coin)


def test_a_coin_can_be_decided_again_after_a_cancel() -> None:
    book = PendingBook()
    book.decide(T, {"BTC": D(".1")})
    assert book.cancel("BTC") is not None
    result = book.decide(T + DAY, {"BTC": D(".3")})
    assert result.cancelled == ()  # nothing was left to replace
    assert book.due(T + DAY + HOUR, always) == (Pending("BTC", T + DAY, D(".3")),)
