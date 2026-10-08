"""Lifecycle attribution from actual synthetic account events."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.account import FuturesAccount, Position
from crypto_grid_bot.trend.orders import OrderIntent

T = 1609459200000


def test_closed_lifecycle_accounts_for_fees_and_exit_priority():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    opened = a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    ledger.fill(opened, Position(), a.positions["BTCUSDT"])
    before = a.positions["BTCUSDT"]
    closed = a.fill("BTCUSDT", OrderIntent(D(-2), True), D(110), T + 1000)
    ledger.fill(closed, before, a.positions["BTCUSDT"], {"flip", "excluded_month"})
    life = ledger.completed[0]
    assert life.exit_reason == "excluded_month"
    assert life.realized == closed.realized
    assert life.fees == opened.fee + closed.fee
    assert life.net == closed.realized - opened.fee - closed.fee
    assert life.given_back == 0
    assert life.duration_ms == 1000


def test_censor_preserves_unrealized_and_does_not_add_fills():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    fill = a.fill("BTCUSDT", OrderIntent(D(-2), False), D(100), T)
    ledger.fill(fill, Position(), a.positions["BTCUSDT"])
    ledger.observe("BTCUSDT", a.positions["BTCUSDT"], D(90))
    ledger.censor(T + 1000, a.positions, {"BTCUSDT": D(95)}, "end_of_run")
    life = ledger.completed[0]
    assert life.censored
    assert life.unrealized == D("9.9000")
    assert life.given_back == 10
    assert len(life.fills) == 1


def test_partial_close_and_funding_stay_in_one_lifecycle():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    opened = a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    ledger.fill(opened, Position(), a.positions["BTCUSDT"])
    ledger.fund(a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)}))
    before = a.positions["BTCUSDT"]
    reduced = a.fill("BTCUSDT", OrderIntent(D(-1), True), D(110), T + 1000)
    ledger.fill(reduced, before, a.positions["BTCUSDT"])
    assert not ledger.completed
    ledger.censor(T + 2000, a.positions, {"BTCUSDT": D(105)}, "end_of_run")
    life = ledger.completed[0]
    assert life.funding_paid == 2
    assert life.realized == reduced.realized
    assert len(life.fills) == 2
    assert life.given_back >= 0


def test_censor_validation_is_atomic_across_coins():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fill = a.fill(symbol, OrderIntent(D(1), False), D(100), T)
        ledger.fill(fill, Position(), a.positions[symbol])
    with pytest.raises(ValueError):
        ledger.censor(T + 1000, a.positions, {"BTCUSDT": D(100)}, "end_of_run")
    assert not ledger.completed
    assert all(life.end_ms is None for life in ledger.active.values())


def test_increase_preserves_pre_fill_excursion_and_flip_starts_new_life():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    for quantity, price, reducing, reasons in [
        (1, 100, False, set()),
        (9, 120, False, set()),
        (-10, 110, True, {"flip"}),
        (-2, 110, False, set()),
    ]:
        before = a.positions.get("BTCUSDT", Position())
        fill = a.fill("BTCUSDT", OrderIntent(D(quantity), reducing), D(price), T)
        ledger.fill(fill, before, a.positions["BTCUSDT"], reasons)
    closed = ledger.completed[0]
    assert closed.favourable == D("20.0100")
    assert closed.exit_reason == "flip"
    assert closed.side == "long"
    assert len(closed.fills) == 3
    assert ledger.active["BTCUSDT"].side == "short"
    assert len(ledger.active["BTCUSDT"].fills) == 1


def test_inconsistent_fill_positions_are_rejected_before_entry():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    fill = a.fill("BTCUSDT", OrderIntent(D(1), False), D(100), T)
    with pytest.raises(ValueError, match="quantity"):
        ledger.fill(fill, Position(), Position(D(2), fill.price))
    assert not ledger.active


def test_invalid_funding_group_does_not_partially_charge_lifecycles():
    from crypto_grid_bot.trend.account import FundingEvent, FundingPayment
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    fill = a.fill("BTCUSDT", OrderIntent(D(1), False), D(100), T)
    ledger.fill(fill, Position(), a.positions["BTCUSDT"])
    event = FundingEvent(
        T,
        (
            FundingPayment("BTCUSDT", D(1), D(100), D(".01"), D(1)),
            FundingPayment("ETHUSDT", D(1), D(100), D(".01"), D(1)),
        ),
    )
    with pytest.raises(ValueError):
        ledger.fund(event)
    assert ledger.active["BTCUSDT"].funding_paid == 0


def test_duplicate_funding_event_is_not_counted_twice():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    fill = a.fill("BTCUSDT", OrderIntent(D(1), False), D(100), T)
    ledger.fill(fill, Position(), a.positions["BTCUSDT"])
    event = a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})
    ledger.fund(event)
    with pytest.raises(ValueError):
        ledger.fund(event)
    assert ledger.active["BTCUSDT"].funding_paid == 1


def test_account_journal_preserves_same_time_fill_funding_reduction_order():
    from crypto_grid_bot.trend.account import FillEvent, FundingEvent

    a = FuturesAccount()
    a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})
    a.fill("BTCUSDT", OrderIntent(D(-1), True), D(100), T)
    assert [type(event) for event in a.events] == [FillEvent, FundingEvent, FillEvent]
    assert a.events[0].before.quantity == 0
    assert a.events[0].after.quantity == 2
    assert a.events[2].before.quantity == 2
    assert a.events[2].after.quantity == 1


def test_incremental_journal_consumption_preserves_ties_without_double_counting():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    ledger.consume(a.events, {})
    a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})
    a.fill("BTCUSDT", OrderIntent(D(-2), True), D(110), T)
    ledger.consume(a.events, {2: {"signal_zero"}})
    ledger.consume(a.events, {})
    assert len(ledger.completed) == 1
    assert ledger.completed[0].funding_paid == 2
    assert len(ledger.completed[0].fills) == 2
    assert ledger.completed[0].exit_reason == "signal_zero"


def test_journal_without_close_reason_fails_before_consuming_batch():
    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    a.fill("BTCUSDT", OrderIntent(D(1), False), D(100), T)
    a.fill("BTCUSDT", OrderIntent(D(-1), True), D(110), T)
    with pytest.raises(ValueError, match="reason"):
        ledger.consume(a.events, {})
    assert not ledger.active
    assert not ledger.completed


def test_trade_totals_reconcile_with_account_for_closed_and_censored_positions():
    from decimal import localcontext

    from crypto_grid_bot.trend.lifecycles import LifecycleLedger

    a, ledger = FuturesAccount(), LifecycleLedger()
    a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    a.fill("ETHUSDT", OrderIntent(D(-3), False), D(100), T)
    a.fund(T, {"BTCUSDT": D(".01"), "ETHUSDT": D(".01")}, {"BTCUSDT": D(100), "ETHUSDT": D(100)})
    a.fill("BTCUSDT", OrderIntent(D(-2), True), D(110), T + 1000)
    ledger.consume(a.events, {3: {"signal_zero"}})
    prices = {"ETHUSDT": D(95)}
    ledger.censor(T + 2000, a.positions, prices, "end_of_run")
    with localcontext() as context:
        context.prec = 60
        assert sum(life.net for life in ledger.completed) == a.mark(prices).equity - a.initial
    assert len(ledger.completed) == 2
    assert sum(life.funding_paid for life in ledger.completed) == 2
    assert sum(life.funding_received for life in ledger.completed) == 3
