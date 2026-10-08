"""Lifecycle attribution from actual synthetic account events."""

from decimal import Decimal as D

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
