"""V4 engine task 10: per coin and side trade lifecycles across the spot and futures venues.

Each scenario drives a real ``Ledger`` beside ``Lifecycles`` the way the hour loop will: book a
batch of fills, pass the batch with each fill's realised P&L and the legs afterwards, and pass the
hourly open mark of the combined position. Every number is worked out by hand in the comments. No
pack and no network is involved.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from crypto_grid_bot.v4.engine.ledger import Fill, Ledger, Venue
from crypto_grid_bot.v4.engine.lifecycle import EXIT_REASONS, Lifecycle, Lifecycles

D = Decimal
HOUR = 3_600_000
T = 1_735_689_600_000  # 2025-01-01 00:00 UTC: synthetic, any date is allowed
BTC = "BTCUSDT"
ETH = "ETHUSDT"
SHIB = "SHIBUSDT"
SHIB_PERP = "1000SHIBUSDT"

# venue, side, quantity, price, fee
Spec = tuple[Venue, int, str, str, str]


class Desk:
    """One coin's ledger beside a shared ``Lifecycles``."""

    def __init__(
        self, lifecycles: Lifecycles, coin: str = BTC, perpetual: str | None = None
    ) -> None:
        self.lifecycles = lifecycles
        self.coin = coin
        self.perpetual = perpetual or coin
        self.ledger = Ledger(D(1_000_000))

    def symbol(self, venue: Venue) -> str:
        return self.coin if venue == "spot" else self.perpetual

    def batch(
        self,
        at: int,
        specs: Sequence[Spec],
        spot_price: str,
        futures_price: str | None = None,
        *,
        reason: str = "signal",
        dust: bool = False,
    ) -> Lifecycle | None:
        fills: list[tuple[Fill, Decimal]] = []
        for venue, side, quantity, price, fee in specs:
            f = Fill(at, venue, self.symbol(venue), side, D(quantity), D(price), D(fee), reason)
            fills.append((f, self.ledger.fill(f)))
        spot_qty = self.ledger.quantity("spot", self.coin)
        futures_qty = self.ledger.quantity("futures", self.perpetual)
        notional = spot_qty * D(spot_price) + futures_qty * D(futures_price or spot_price)
        return self.lifecycles.after_batch(
            at, self.coin, notional, spot_qty, futures_qty, dust, fills, reason
        )

    def unrealised(self, spot_price: str, futures_price: str | None = None) -> Decimal:
        return self.ledger.unrealised("spot", self.coin, D(spot_price)) + self.ledger.unrealised(
            "futures", self.perpetual, D(futures_price or spot_price)
        )

    def mark(
        self, at: int, spot_price: str, futures_price: str | None = None, *, counts: bool = True
    ) -> None:
        self.lifecycles.mark(
            at, self.coin, self.unrealised(spot_price, futures_price), counts=counts
        )


def venue_view(lifecycle: Lifecycle, venue: Venue) -> dict[str, Decimal]:
    return dict(lifecycle.venues[venue])


def ended_of(result: Lifecycle | None) -> Lifecycle:
    assert result is not None
    return result


# ---------------------------------------------------------------------------------------
# The brief's five scenarios
# ---------------------------------------------------------------------------------------


def test_full_spot_to_futures_move_stays_one_lifecycle() -> None:
    life = Lifecycles()
    desk = Desk(life)
    # h0: buy 2 spot at 100, fee 0.2.
    assert desk.batch(T, [("spot", 1, "2", "100", "0.2")], "100") is None
    # h1 open mark at 110: 2 x (110 - 100) = 20, nothing realised yet, so 20.
    desk.mark(T + HOUR, "110")
    # h2: the whole long moves to futures in one batch. Sell 2 spot at 112 (realised 24) and buy
    # 2 contracts at 112. Between those two fills the coin is flat; after them it is long.
    moved = desk.batch(
        T + 2 * HOUR,
        [("spot", -1, "2", "112", "0.224"), ("futures", 1, "2", "112", "0.112")],
        "112",
    )
    assert moved is None
    # h3 open mark at 115: futures 2 x (115 - 112) = 6, so 24 realised + 6 = 30.
    desk.mark(T + 3 * HOUR, "115")
    # h4: sell the 2 contracts at 114: realised 2 x (114 - 112) = 4. Both legs are flat.
    ended = ended_of(desk.batch(T + 4 * HOUR, [("futures", -1, "2", "114", "0.114")], "114"))
    assert ended == Lifecycle(
        coin=BTC,
        side="long",
        entry_ms=T,
        exit_ms=T + 4 * HOUR,
        exit_reason="signal",
        gross_pnl=D(28),
        fees=D("0.650"),
        funding=D(0),
        best_unrealised=D(30),
        given_back=D(2),
        holding_hours=4,
        censored=False,
        venues={
            "spot": {
                "bought_quantity": D(2),
                "sold_quantity": D(2),
                "fees": D("0.424"),
                "realised_pnl": D(24),
            },
            "futures": {
                "bought_quantity": D(2),
                "sold_quantity": D(2),
                "fees": D("0.226"),
                "realised_pnl": D(4),
                "funding": D(0),
            },
        },
        unrealised=D(0),
    )


def test_sign_change_ends_one_and_opens_the_other() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0.1")], "100")
    desk.mark(T + HOUR, "105")  # unrealised 5
    # h2: sell the spot (realised 4, fee 0.104) and open a short of 1 contract at 104. After the
    # batch the net notional is -104: strictly opposite to the long.
    long = ended_of(
        desk.batch(
            T + 2 * HOUR,
            [("spot", -1, "1", "104", "0.104"), ("futures", -1, "1", "104", "0.052")],
            "104",
        )
    )
    assert (long.coin, long.side, long.entry_ms, long.exit_ms) == (BTC, "long", T, T + 2 * HOUR)
    assert long.exit_reason == "signal"
    assert (long.gross_pnl, long.best_unrealised, long.given_back) == (D(4), D(5), D(1))
    assert long.holding_hours == 2 and not long.censored and long.unrealised == 0
    # The short-opening fill and its fee belong to the new lifecycle, not to the one that ended.
    assert long.fees == D("0.204")
    assert venue_view(long, "spot") == {
        "bought_quantity": D(1),
        "sold_quantity": D(1),
        "fees": D("0.204"),
        "realised_pnl": D(4),
    }
    assert venue_view(long, "futures") == {
        "bought_quantity": D(0),
        "sold_quantity": D(0),
        "fees": D(0),
        "realised_pnl": D(0),
        "funding": D(0),
    }
    # The short is open: it takes a mark and funding, and closes as its own record.
    desk.mark(T + 3 * HOUR, "100")  # short 1 from 104: unrealised 4
    life.funding(BTC, D("0.5"))
    short = ended_of(desk.batch(T + 4 * HOUR, [("futures", 1, "1", "101", "0.0505")], "101"))
    assert (short.side, short.entry_ms, short.exit_ms) == ("short", T + 2 * HOUR, T + 4 * HOUR)
    assert (short.gross_pnl, short.fees, short.funding) == (D(3), D("0.1025"), D("0.5"))
    assert (short.best_unrealised, short.given_back, short.holding_hours) == (D(4), D(1), 2)
    assert venue_view(short, "futures") == {
        "bought_quantity": D(1),
        "sold_quantity": D(1),
        "fees": D("0.1025"),
        "realised_pnl": D(3),
        "funding": D("0.5"),
    }
    assert venue_view(short, "spot")["fees"] == 0


def test_dust_keeps_the_lifecycle_open_until_sold() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0.1")], "100")
    # h1: sell 0.9996 at 110 (realised 9.996, fee 0.109956). 0.0004 is left, unsellable dust.
    left = desk.batch(T + HOUR, [("spot", -1, "0.9996", "110", "0.109956")], "110", dust=True)
    assert left is None
    desk.mark(T + 2 * HOUR, "90")  # dust 0.0004 x (90 - 100) = -0.004: 9.996 - 0.004 = 9.992
    desk.mark(T + 3 * HOUR, "100")  # dust unrealised 0: 9.996
    # h5: the dust is finally sold at 95: realised 0.0004 x (95 - 100) = -0.002.
    ended = ended_of(desk.batch(T + 5 * HOUR, [("spot", -1, "0.0004", "95", "0.000038")], "95"))
    assert ended.entry_ms == T and ended.exit_ms == T + 5 * HOUR and ended.holding_hours == 5
    assert ended.gross_pnl == D("9.994")
    assert ended.fees == D("0.209994")  # the dust sale's fee is inside the lifecycle
    assert ended.best_unrealised == D("9.996")
    assert ended.given_back == D("0.002")
    assert not ended.censored


def test_best_unrealised_and_given_back_on_open_marks() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "2", "100", "0")], "100")
    desk.mark(T + HOUR, "105")  # 0 realised + 10
    desk.mark(T + 2 * HOUR, "115")  # 0 + 30
    # h3: sell 1 at 125: realised 25. The lifecycle stays open.
    assert desk.batch(T + 3 * HOUR, [("spot", -1, "1", "125", "0")], "125") is None
    desk.mark(T + 4 * HOUR, "120")  # 25 realised + 1 x 20 = 45, the best
    desk.mark(T + 5 * HOUR, "110")  # 25 + 10 = 35
    ended = ended_of(desk.batch(T + 6 * HOUR, [("spot", -1, "1", "108", "0")], "108"))
    assert ended.gross_pnl == D(33)  # 25 + 8
    assert ended.best_unrealised == D(45)
    assert ended.given_back == D(12)  # 45 - 33


def test_given_back_when_every_mark_is_a_loss() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "90")  # -10
    desk.mark(T + 2 * HOUR, "95")  # -5, the best of the marks
    desk.mark(T + 3 * HOUR, "80")  # -20
    ended = ended_of(desk.batch(T + 4 * HOUR, [("spot", -1, "1", "82", "0")], "82"))
    assert ended.gross_pnl == D(-18)
    assert ended.best_unrealised == D(-5)  # the maximum of the marks, not floored at 0
    assert ended.given_back == D(13)  # -5 - (-18)


def test_an_exit_above_every_open_mark_gives_nothing_back() -> None:
    # The best is the maximum over the open marks and the final gross P&L, so an exit that beats
    # every mark is the best itself: nothing is given back, never a negative amount.
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "110")  # the only open mark: 10
    ended = ended_of(desk.batch(T + 2 * HOUR, [("spot", -1, "1", "125", "0")], "125"))
    assert ended.gross_pnl == D(25)
    assert ended.best_unrealised == D(25)  # the final gross, above the mark's 10
    assert ended.given_back == D(0)


def test_a_window_end_close_above_every_hourly_open_mark_gives_nothing_back() -> None:
    # The window end, as the hour loop does it: the hourly open marks count, then the close sells
    # the whole long at the last hour's close, above every one of them.
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "2", "100", "0.2")], "100")
    desk.mark(T + HOUR, "105")  # 10
    desk.mark(T + 2 * HOUR, "110")  # 20, the best open mark
    ended = ended_of(
        desk.batch(T + 2 * HOUR, [("spot", -1, "2", "125", "0.25")], "125", reason="window end")
    )
    assert (ended.exit_reason, ended.censored) == ("window end", False)
    assert ended.gross_pnl == D(50)  # 2 x (125 - 100)
    assert (ended.best_unrealised, ended.given_back) == (D(50), D(0))


def test_a_censored_lifecycle_never_gives_back_a_negative_amount() -> None:
    # Window end with dust: the close leaves 0.0004 unsellable, and the mark at the close, taken
    # after the closing fills, does not count toward the best. The censored gross P&L, above the
    # only open mark, is the best itself.
    life = Lifecycles()
    dusty = Desk(life)
    dusty.batch(T, [("spot", 1, "1", "100", "0")], "100")
    dusty.mark(T + HOUR, "105")  # 5
    left = dusty.batch(
        T + HOUR, [("spot", -1, "0.9996", "130", "0")], "130", reason="window end", dust=True
    )
    assert left is None
    dusty.mark(T + HOUR, "130", counts=False)  # the dust at the close: 0.0004 x 30 = 0.012
    (censored,) = life.censor(T + HOUR, "window end")
    assert censored.exit_reason == "window end (dust)"
    assert censored.gross_pnl == D("30.000")  # 0.9996 x 30 = 29.988 realised + 0.012
    assert (censored.best_unrealised, censored.given_back) == (D("30.000"), D(0))
    # A stop whose mark is above every open mark: the same, since the stop's mark is the end.
    life = Lifecycles()
    stopped = Desk(life)
    stopped.batch(T, [("futures", -1, "1", "100", "0")], "100")
    stopped.mark(T + HOUR, "98")  # 2
    stopped.mark(T + 2 * HOUR, "99")  # 1
    stopped.mark(T + 2 * HOUR, "90", counts=False)  # the stop's mark: 10
    (stop,) = life.censor(T + 2 * HOUR, "liquidation")
    assert (stop.unrealised, stop.gross_pnl) == (D(10), D(10))
    assert (stop.best_unrealised, stop.given_back) == (D(10), D(0))


def test_a_mark_that_does_not_count_feeds_censor_but_not_the_best() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "110", counts=False)  # 10, not counted
    desk.mark(T + 2 * HOUR, "105")  # 5, the best that counts
    ended = ended_of(desk.batch(T + 3 * HOUR, [("spot", -1, "1", "104", "0")], "104"))
    assert (ended.gross_pnl, ended.best_unrealised, ended.given_back) == (D(4), D(5), D(1))
    # It is still the value censor uses.
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "103")  # 3
    desk.mark(T + HOUR, "101", counts=False)  # 1
    (censored,) = life.censor(T + HOUR, "limit_unrestorable")
    assert (censored.unrealised, censored.best_unrealised, censored.given_back) == (
        D(1),
        D(3),
        D(2),
    )


def test_a_lifecycle_closed_in_its_opening_hour_has_no_mark_and_gives_nothing_back() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0.1")], "100")  # the daily fill
    ended = ended_of(  # a cut in the same hour closes it: no open mark ever saw it
        desk.batch(T, [("spot", -1, "1", "103", "0.103")], "103", reason="ceiling cut")
    )
    assert ended.exit_reason == "ceiling cut"
    assert ended.entry_ms == ended.exit_ms == T and ended.holding_hours == 0
    assert ended.gross_pnl == D(3)
    assert (ended.best_unrealised, ended.given_back) == (D(3), D(0))


def _two_coins_at_hour_three() -> tuple[Lifecycles, Desk, Desk]:
    """BTC long on spot and ETH short on futures, both marked after BTC's partial sale."""
    life = Lifecycles()
    btc, eth = Desk(life, BTC), Desk(life, ETH)
    btc.batch(T, [("spot", 1, "1", "100", "0.1")], "100")
    eth.batch(T, [("futures", -1, "10", "50", "0.25")], "50")
    btc.mark(T + HOUR, "110")  # 10
    eth.mark(T + HOUR, "45")  # short 10 x (50 - 45) = 50
    # h2: BTC sells 0.4 at 112: realised 0.4 x 12 = 4.8, fee 0.0448.
    assert btc.batch(T + 2 * HOUR, [("spot", -1, "0.4", "112", "0.0448")], "112") is None
    btc.mark(T + 3 * HOUR, "120")  # 4.8 realised + 0.6 x 20 = 16.8
    eth.mark(T + 3 * HOUR, "60")  # short 10 x (50 - 60) = -100
    return life, btc, eth


def test_censoring_at_window_end_and_at_a_stop() -> None:
    # Window end: both lifecycles are censored at the last marks, unrealised included in gross.
    life, btc, eth = _two_coins_at_hour_three()
    btc.mark(T + 10 * HOUR, "108")  # 0.6 x 8 = 4.8
    eth.mark(T + 10 * HOUR, "40")  # 10 x (50 - 40) = 100
    first, second = life.censor(T + 10 * HOUR, "window end")
    assert (first.coin, first.side, first.censored, first.exit_reason) == (
        BTC,
        "long",
        True,
        "window end",
    )
    assert (first.entry_ms, first.exit_ms, first.holding_hours) == (T, T + 10 * HOUR, 10)
    assert first.unrealised == D("4.8")
    assert first.gross_pnl == D("9.6")  # 4.8 realised + 4.8 unrealised
    assert first.fees == D("0.1448")
    assert (first.best_unrealised, first.given_back) == (D("16.8"), D("7.2"))
    assert (second.coin, second.side, second.censored) == (ETH, "short", True)
    assert second.unrealised == D(100) and second.gross_pnl == D(100)
    assert (second.best_unrealised, second.given_back) == (D(100), D(0))
    assert venue_view(second, "futures")["sold_quantity"] == D(10)
    # Nothing is left open.
    assert life.censor(T + 10 * HOUR, "window end") == ()


@pytest.mark.parametrize("reason", ["liquidation", "limit_unrestorable"])
def test_a_stop_censors_every_lifecycle_with_the_stop_reason(reason: str) -> None:
    life, _, _ = _two_coins_at_hour_three()
    btc, eth = life.censor(T + 3 * HOUR, reason)
    assert (btc.censored, btc.exit_reason, btc.exit_ms, btc.holding_hours) == (
        True,
        reason,
        T + 3 * HOUR,
        3,
    )
    assert btc.unrealised == D(12) and btc.gross_pnl == D("16.8")  # the marks at hour 3
    assert (btc.best_unrealised, btc.given_back) == (D("16.8"), D(0))
    assert (eth.censored, eth.exit_reason) == (True, reason)
    assert eth.unrealised == D(-100) and eth.gross_pnl == D(-100)
    assert (eth.best_unrealised, eth.given_back) == (D(50), D(150))  # 50 - (-100)


def test_window_end_labels_only_a_lifecycle_left_with_dust() -> None:
    life = Lifecycles()
    btc, eth = Desk(life, BTC), Desk(life, ETH)
    btc.batch(T, [("spot", 1, "1", "100", "0.1")], "100")
    eth.batch(T, [("spot", 1, "1", "50", "0.05")], "50")
    btc.mark(T + 5 * HOUR, "105")
    eth.mark(T + 5 * HOUR, "55")
    # The window-end close sells BTC down to 0.0004 of unsellable dust. ETH is still held.
    left = btc.batch(
        T + 5 * HOUR,
        [("spot", -1, "0.9996", "105", "0.104958")],
        "105",
        reason="window end",
        dust=True,
    )
    assert left is None
    btc.mark(T + 5 * HOUR, "105")  # the dust at the close: 0.0004 x 5 = 0.002
    dusty, whole = life.censor(T + 5 * HOUR, "window end")
    assert (dusty.coin, dusty.exit_reason, dusty.censored) == (BTC, "window end (dust)", True)
    assert dusty.unrealised == D("0.002")
    assert dusty.gross_pnl == D("5.000")  # 0.9996 x 5 = 4.998 realised + 0.002
    assert dusty.fees == D("0.204958")
    assert (whole.coin, whole.exit_reason, whole.censored) == (ETH, "window end", True)


def test_a_stop_keeps_its_own_reason_for_a_lifecycle_left_with_dust() -> None:
    life = Lifecycles()
    btc = Desk(life)
    btc.batch(T, [("spot", 1, "1", "100", "0")], "100")
    btc.batch(T + HOUR, [("spot", -1, "0.9996", "110", "0")], "110", dust=True)
    btc.mark(T + HOUR, "110")
    (stopped,) = life.censor(T + HOUR, "liquidation")
    assert stopped.exit_reason == "liquidation"


# ---------------------------------------------------------------------------------------
# The controller's rulings
# ---------------------------------------------------------------------------------------


def test_a_net_zero_with_legs_not_flat_stays_open() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0.1")], "100")
    # h1: sell down to 0.0004 of dust (worth 0.04) and short 0.0004 contracts (worth 0.04): the
    # net notional is exactly 0 but both legs are held, so the lifecycle stays open.
    assert (
        desk.batch(
            T + HOUR,
            [("spot", -1, "0.9996", "100", "0.09996"), ("futures", -1, "0.0004", "100", "0.00002")],
            "100",
        )
        is None
    )
    desk.mark(T + 2 * HOUR, "100")
    # h3: the short is covered. Dust alone is left, long again: still the same lifecycle.
    assert (
        desk.batch(T + 3 * HOUR, [("futures", 1, "0.0004", "99", "0.00002")], "99", dust=True)
        is None
    )
    ended = ended_of(desk.batch(T + 4 * HOUR, [("spot", -1, "0.0004", "99", "0.00004")], "99"))
    assert (ended.side, ended.entry_ms, ended.exit_ms, ended.holding_hours) == (
        "long",
        T,
        T + 4 * HOUR,
        4,
    )
    assert ended.fees == D("0.1") + D("0.09996") + D("0.00002") + D("0.00002") + D("0.00004")
    assert venue_view(ended, "futures")["realised_pnl"] == D("0.0004")  # 0.0004 x (100 - 99)


def test_after_a_net_zero_the_lifecycle_ends_only_on_the_opposite_sign() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.batch(
        T + HOUR,
        [("spot", -1, "0.9996", "100", "0"), ("futures", -1, "0.0004", "100", "0")],
        "100",
    )  # net zero: still the long
    # h2: the short grows to 0.001 (worth 0.1) against 0.04 of dust: net -0.06, opposite to the
    # long, so the long ends here and a short begins.
    long = ended_of(desk.batch(T + 2 * HOUR, [("futures", -1, "0.0006", "100", "0")], "100"))
    assert (long.side, long.exit_ms) == ("long", T + 2 * HOUR)
    short = ended_of(
        desk.batch(
            T + 3 * HOUR,
            [("futures", 1, "0.001", "100", "0"), ("spot", -1, "0.0004", "100", "0")],
            "100",
        )
    )
    assert (short.side, short.entry_ms) == ("short", T + 2 * HOUR)


def test_both_legs_flat_ends_the_lifecycle_and_a_new_entry_starts_a_new_one() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("futures", -1, "2", "100", "0")], "100")
    first = ended_of(desk.batch(T + 7 * HOUR, [("futures", 1, "2", "98", "0")], "98"))
    assert (first.side, first.holding_hours, first.gross_pnl) == ("short", 7, D(4))
    desk.batch(T + 9 * HOUR, [("spot", 1, "1", "98", "0")], "98")
    second = ended_of(desk.batch(T + 12 * HOUR, [("spot", -1, "1", "99", "0")], "99"))
    assert (second.side, second.entry_ms, second.holding_hours) == ("long", T + 9 * HOUR, 3)


def test_dust_left_after_a_short_closes_becomes_its_own_long_lifecycle() -> None:
    # The letter of the ruling: the sign of the net notional is the side. A short that carried
    # dust ends when its futures leg closes, because the dust alone is long; the dust is then a
    # lifecycle of its own, which a later sale (or the window end) closes.
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    flip = ended_of(
        desk.batch(
            T + HOUR,
            [("spot", -1, "0.9996", "100", "0"), ("futures", -1, "1", "100", "0")],
            "100",
            dust=False,
        )
    )
    assert flip.side == "long"
    cover = ended_of(desk.batch(T + 2 * HOUR, [("futures", 1, "1", "90", "0")], "90", dust=True))
    assert (cover.side, cover.entry_ms, cover.gross_pnl) == ("short", T + HOUR, D(10))
    desk.mark(T + 3 * HOUR, "90")
    (dust,) = life.censor(T + 3 * HOUR, "window end")
    assert (dust.side, dust.entry_ms, dust.exit_reason) == (
        "long",
        T + 2 * HOUR,
        "window end (dust)",
    )


@pytest.mark.parametrize(
    "reason",
    [
        r
        for r in EXIT_REASONS
        if r not in {"window end (dust)", "liquidation", "limit_unrestorable"}
    ],
)
def test_the_reason_of_the_batch_that_ends_a_lifecycle_is_its_exit_reason(reason: str) -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "2", "100", "0")], "100")
    # A batch that leaves the lifecycle open takes no exit reason.
    assert desk.batch(T + HOUR, [("spot", -1, "1", "100", "0")], "100", reason="margin cut") is None
    ended = ended_of(
        desk.batch(T + 2 * HOUR, [("spot", -1, "1", "100", "0")], "100", reason=reason)
    )
    assert ended.exit_reason == reason


def test_the_exit_reasons_are_exactly_the_briefs_list() -> None:
    assert EXIT_REASONS == (
        "signal",
        "universe exit",
        "funding-month exit",
        "margin cut",
        "ceiling cut",
        "delisting",
        "window end",
        "window end (dust)",
        "liquidation",
        "limit_unrestorable",
    )


def test_two_batches_in_one_hour_are_two_tests() -> None:
    # The daily fills and then a cut at the same open: the cut ends what the daily fills grew.
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    assert desk.batch(T + 5 * HOUR, [("spot", 1, "1", "100", "0")], "100") is None
    ended = ended_of(
        desk.batch(T + 5 * HOUR, [("spot", -1, "2", "100", "0")], "100", reason="ceiling cut")
    )
    assert (ended.exit_reason, ended.holding_hours) == ("ceiling cut", 5)


def test_funding_goes_under_the_futures_venue_and_is_keyed_by_the_coin() -> None:
    life = Lifecycles()
    desk = Desk(life, SHIB, SHIB_PERP)
    # 1,000,000 coins at 0.00001 (10 USDT) on spot, then the long moves to 1000 contracts of 1000
    # coins each, at the contract price 0.012 (12 USDT).
    desk.batch(T, [("spot", 1, "1000000", "0.00001", "0.01")], "0.00001")
    moved = desk.batch(
        T + HOUR,
        [("spot", -1, "1000000", "0.000012", "0.012"), ("futures", 1, "1000", "0.012", "0.006")],
        "0.000012",
        "0.012",
    )
    assert moved is None  # spot symbol SHIBUSDT and perpetual 1000SHIBUSDT are one coin
    life.funding(SHIB, D("-0.01"))
    life.funding(SHIB, D("0.004"))
    with pytest.raises(ValueError, match="no open lifecycle"):
        life.funding(SHIB_PERP, D(1))  # keyed by the coin, never the perpetual's symbol
    ended = ended_of(
        desk.batch(T + 2 * HOUR, [("futures", -1, "1000", "0.013", "0.0065")], "0.013")
    )
    assert ended.coin == SHIB
    assert ended.funding == D("-0.006")
    assert venue_view(ended, "futures")["funding"] == D("-0.006")
    assert venue_view(ended, "futures")["bought_quantity"] == D(1000)
    assert venue_view(ended, "spot")["bought_quantity"] == D(1000000)
    assert ended.gross_pnl == D(3)  # 2 on spot, 1 on futures


def test_the_venues_breakdown_adds_up_to_the_lifecycle() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "2", "100", "0.2"), ("futures", -1, "1", "100", "0.05")], "100")
    life.funding(BTC, D("0.25"))
    life.funding(BTC, D("-0.1"))
    ended = ended_of(
        desk.batch(
            T + 3 * HOUR,
            [("spot", -1, "2", "103", "0.206"), ("futures", 1, "1", "103", "0.0515")],
            "103",
        )
    )
    assert set(ended.venues) == {"spot", "futures"}
    assert set(ended.venues["spot"]) == {
        "bought_quantity",
        "sold_quantity",
        "fees",
        "realised_pnl",
    }
    assert set(ended.venues["futures"]) == {
        "bought_quantity",
        "sold_quantity",
        "fees",
        "realised_pnl",
        "funding",
    }
    assert all(isinstance(key, str) for venue in ended.venues.values() for key in venue)
    assert all(
        isinstance(value, Decimal) for venue in ended.venues.values() for value in venue.values()
    )
    spot, futures = venue_view(ended, "spot"), venue_view(ended, "futures")
    assert spot["realised_pnl"] + futures["realised_pnl"] == ended.gross_pnl == D(3)  # 6 - 3
    assert spot["fees"] + futures["fees"] == ended.fees == D("0.5075")
    assert futures["funding"] == ended.funding == D("0.15")


def test_a_lifecycle_record_is_immutable_and_its_unrealised_defaults_to_zero() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    ended = ended_of(desk.batch(T + HOUR, [("spot", -1, "1", "100", "0")], "100"))
    with pytest.raises(FrozenInstanceError):
        ended.gross_pnl = D(1)
    with pytest.raises(TypeError):
        ended.venues["spot"]["fees"] = D(1)
    with pytest.raises(TypeError):
        ended.venues["spot"] = {}
    # The brief's thirteen fields build a Lifecycle; only the added `unrealised` has a default.
    built = Lifecycle(
        BTC, "long", T, T + HOUR, "signal", D(0), D(0), D(0), D(0), D(0), 1, False, {}
    )
    assert built.unrealised == 0


# ---------------------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------------------


def test_censoring_needs_a_mark_since_the_last_batch() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "110")
    desk.batch(T + 2 * HOUR, [("spot", -1, "0.5", "110", "0")], "110")  # the mark is now stale
    with pytest.raises(ValueError, match="mark"):
        life.censor(T + 2 * HOUR, "liquidation")
    desk.mark(T + 2 * HOUR, "108")  # 0.5 x 8 = 4 unrealised, 5 realised
    (stopped,) = life.censor(T + 2 * HOUR, "liquidation")  # the refused call changed nothing
    assert (stopped.unrealised, stopped.gross_pnl) == (D(4), D(9))


def test_a_batch_without_fills_keeps_the_mark_fresh() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "110")
    assert desk.batch(T + HOUR, [], "110") is None
    (stopped,) = life.censor(T + HOUR, "limit_unrestorable")
    assert stopped.unrealised == D(10)


def test_the_last_mark_wins_and_every_counting_mark_counts_toward_the_best() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "1", "100", "0")], "100")
    desk.mark(T + HOUR, "110")  # 10
    desk.mark(T + HOUR, "130")  # 30, a second mark in the same hour
    desk.mark(T + 2 * HOUR, "120")  # 20: this is the last
    (stopped,) = life.censor(T + 2 * HOUR, "liquidation")
    assert (stopped.unrealised, stopped.best_unrealised, stopped.given_back) == (
        D(20),
        D(30),
        D(10),
    )


# ---------------------------------------------------------------------------------------
# Refusals: every bad call raises ValueError and leaves the state as it was
# ---------------------------------------------------------------------------------------


def _fill(
    venue: Venue = "spot",
    side: int = -1,
    quantity: str = "2",
    symbol: str = BTC,
    at: int = T + 2 * HOUR,
) -> Fill:
    return Fill(at, venue, symbol, side, D(quantity), D(110), D(0), "signal")


def _good_sell() -> list[tuple[Fill, Decimal]]:
    return [(_fill(), D(20))]


AT = T + 2 * HOUR
_BATCH: dict[str, object] = {
    "hour_ms": AT,
    "coin": BTC,
    "signed_notional": D(0),
    "spot_qty": D(0),
    "futures_qty": D(0),
    "dust_only": False,
    "reason": "signal",
}

_BAD_BATCHES: dict[str, dict[str, object]] = {
    "unknown reason": {"reason": "stop"},
    "empty reason": {"reason": ""},
    "a stop reason is not a batch reason": {"reason": "liquidation"},
    "the dust label is derived": {"reason": "window end (dust)"},
    "bad coin": {"coin": "btcusdt"},
    "short coin": {"coin": "B"},
    "float notional": {"signed_notional": 0.0},
    "nan notional": {"signed_notional": D("NaN")},
    "negative spot": {"spot_qty": D(-1)},
    "float futures": {"futures_qty": 0.0},
    "int dust flag": {"dust_only": 1},
    "dust flag without a spot leg": {"dust_only": True},
    "negative hour": {"hour_ms": -1},
    "float hour": {"hour_ms": float(AT)},
    "bool hour": {"hour_ms": True},
    "hour before the last event": {"hour_ms": T},
    "flat legs with a notional": {"signed_notional": D(5)},
    "a long spot leg with a short notional": {
        "spot_qty": D(2),
        "signed_notional": D(-220),
        "fills": [],
    },
    "fills as a string": {"fills": "abc"},
    "fill that is not a pair": {"fills": [_fill()]},
    "a fill that is not a Fill": {"fills": [("sell", D(0))]},
    "a float realised P&L": {"fills": [(_fill(), 20.0)]},
    "a spot fill of another symbol": {"fills": [(_fill(symbol=ETH), D(20))]},
    "fills that do not reach the legs passed": {
        "spot_qty": D(1),
        "signed_notional": D(110),
        "fills": [],
    },
    "a spot sell above the held quantity": {"fills": [(_fill(quantity="3"), D(0))]},
}


@pytest.mark.parametrize("name", sorted(_BAD_BATCHES))
def test_a_bad_batch_is_refused_and_changes_nothing(name: str) -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("spot", 1, "2", "100", "0")], "100")
    desk.mark(T + HOUR, "115")
    arguments = {**_BATCH, "fills": _good_sell(), **_BAD_BATCHES[name]}
    with pytest.raises(ValueError):
        life.after_batch(**arguments)
    # The lifecycle is as it was: the real sale still closes it with the numbers of a clean run.
    ended = ended_of(desk.batch(AT, [("spot", -1, "2", "110", "0")], "110"))
    assert (ended.entry_ms, ended.exit_ms, ended.gross_pnl) == (T, AT, D(20))
    assert (ended.best_unrealised, ended.given_back, ended.fees) == (D(30), D(10), D(0))


def test_a_flat_coin_with_no_lifecycle_takes_an_empty_batch_and_refuses_fills_it_cannot_place() -> (
    None
):
    life = Lifecycles()
    assert life.after_batch(T, BTC, D(0), D(0), D(0), False, [], "signal") is None
    # A batch that opens and closes within itself would lose its fee: refused.
    buy, sell = _fill(side=1, at=T), _fill(side=-1, at=T)
    with pytest.raises(ValueError, match="flat"):
        life.after_batch(T, BTC, D(0), D(0), D(0), False, [(buy, D(0)), (sell, D(0))], "signal")
    # A net-zero opening from flat has no side.
    spot = _fill(side=1, quantity="1", at=T)
    short = _fill(venue="futures", side=-1, quantity="1", at=T)
    with pytest.raises(ValueError, match="side"):
        life.after_batch(T, BTC, D(0), D(1), D(-1), False, [(spot, D(0)), (short, D(0))], "signal")


def test_a_futures_fill_that_crosses_zero_is_refused_and_changes_nothing() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("futures", -1, "1", "100", "0")], "100")
    cross = Fill(T + HOUR, "futures", BTC, 1, D(2), D(100), D(0), "signal")
    with pytest.raises(ValueError, match="crosses zero"):
        life.after_batch(T + HOUR, BTC, D(100), D(0), D(1), False, [(cross, D(0))], "signal")
    ended = ended_of(desk.batch(T + HOUR, [("futures", 1, "1", "99", "0")], "99"))
    assert (ended.side, ended.gross_pnl) == ("short", D(1))


def test_a_perpetual_symbol_that_changes_for_one_coin_is_refused() -> None:
    life = Lifecycles()
    desk = Desk(life, SHIB, SHIB_PERP)
    desk.batch(T, [("futures", 1, "1000", "0.01", "0")], "0.00001", "0.01")
    other = Fill(T + HOUR, "futures", "10000SHIBUSDT", -1, D(1000), D("0.01"), D(0), "signal")
    with pytest.raises(ValueError, match="perpetual"):
        life.after_batch(T + HOUR, SHIB, D(0), D(0), D(0), False, [(other, D(0))], "signal")


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda life: life.mark(AT, BTC, 1.0), id="mark float"),
        pytest.param(lambda life: life.mark(AT, BTC, D("NaN")), id="mark nan"),
        pytest.param(lambda life: life.mark(AT, BTC, D("Infinity")), id="mark infinity"),
        pytest.param(lambda life: life.mark(AT, ETH, D(1)), id="mark without a lifecycle"),
        pytest.param(lambda life: life.mark(AT, "btc", D(1)), id="mark bad coin"),
        pytest.param(lambda life: life.mark(T, BTC, D(1)), id="mark backwards in time"),
        pytest.param(lambda life: life.mark(True, BTC, D(1)), id="mark bool hour"),
        pytest.param(lambda life: life.mark(AT, BTC, D(1), counts=1), id="mark int counts"),
        pytest.param(lambda life: life.funding(BTC, 1.0), id="funding float"),
        pytest.param(lambda life: life.funding(BTC, D("NaN")), id="funding nan"),
        pytest.param(lambda life: life.funding(BTC, D("Infinity")), id="funding infinity"),
        pytest.param(lambda life: life.funding(ETH, D(1)), id="funding without a lifecycle"),
        pytest.param(lambda life: life.funding("btc", D(1)), id="funding bad coin"),
        pytest.param(lambda life: life.censor(AT, "signal"), id="censor with an exit reason"),
        pytest.param(lambda life: life.censor(AT, "window end (dust)"), id="censor with the label"),
        pytest.param(lambda life: life.censor(AT, ""), id="censor empty reason"),
        pytest.param(lambda life: life.censor(T, "liquidation"), id="censor backwards in time"),
        pytest.param(lambda life: life.censor(-1, "liquidation"), id="censor negative hour"),
    ],
)
def test_bad_marks_funding_and_censoring_are_refused_and_change_nothing(
    bad: Callable[[Lifecycles], object],
) -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("futures", -1, "1", "100", "0.05")], "100")
    desk.mark(T + HOUR, "95")  # 5
    with pytest.raises(ValueError):
        bad(life)
    life.funding(BTC, D("0.5"))
    (stopped,) = life.censor(AT, "liquidation")
    assert (stopped.funding, stopped.unrealised, stopped.best_unrealised) == (D("0.5"), D(5), D(5))
    assert stopped.fees == D("0.05")


def test_funding_for_a_lifecycle_that_already_ended_is_refused() -> None:
    life = Lifecycles()
    desk = Desk(life)
    desk.batch(T, [("futures", -1, "1", "100", "0")], "100")
    desk.batch(T + HOUR, [("futures", 1, "1", "100", "0")], "100")
    with pytest.raises(ValueError, match="no open lifecycle"):
        life.funding(BTC, D(1))
