from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.account import CombinedAccount, FillEvent, FundingEvent

D = Decimal


def test_wallet_conversion_ignores_restrictive_decimal_context() -> None:
    account = CombinedAccount(D(10000))
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        for signal in context.traps:
            context.traps[signal] = True
        result = account.apply(fill("context", fee="1"))
    assert result.free_cash == 9989
    assert result.equity == 9999
    assert result.reconciliation_residual == 0


def test_extreme_decimal_input_rejected_before_wallet_mutation() -> None:
    account = CombinedAccount(D(10000))
    before = account.snapshot()
    with pytest.raises(ValueError):
        account.apply(fill("extreme", price="1e5000"))
    assert account.snapshot() == before


def fill(
    event: str,
    symbol: str = "BTCUSDT",
    venue: str = "spot",
    side: int = 1,
    qty: str = "1",
    price: str = "10",
    fee: str = "0",
    time: int = 0,
    lot: str | None = None,
) -> FillEvent:
    return FillEvent(
        event,
        time,
        symbol,
        "spot_grid" if venue == "spot" else "futures_trend",
        venue,
        side,
        D(qty),
        D(price),
        D(fee),
        lot,
    )


def test_shared_cash_counts_collateral_once_and_marks_both_venues() -> None:
    account = CombinedAccount(D(100))
    account.apply(fill("spot", qty="4"))
    result = account.apply(fill("future", "ETHUSDT", "futures", qty="4"))
    assert result.free_cash == 40
    assert result.equity == 100
    result = account.snapshot({"BTCUSDT": D(12), "ETHUSDT": D(11)})
    assert result.equity == 112
    assert result.positions[1].collateral == 20
    assert result.positions[1].unrealized_pnl == 4
    assert result.reconciliation_residual == 0


def test_spot_fifo_partial_close_preserves_tiny_inventory_and_ownership() -> None:
    account = CombinedAccount(D(100))
    account.apply(fill("one", qty="2"))
    account.apply(fill("two", qty="1", price="20", time=1))
    result = account.apply(fill("sale", side=-1, qty="2.999", price="30", time=2))
    assert result.free_cash == D("149.97")
    assert result.realized_pnl == D("49.99")
    position = result.positions[0]
    assert position.quantity == D(".001")
    assert position.entry_cost == D(".02")
    assert len(position.lots) == 1
    with pytest.raises(ValueError):
        account.apply(fill("new-owner", venue="futures", time=3))
    assert account.snapshot() == result


def test_targeted_grid_lot_close_does_not_consume_fifo_neighbor() -> None:
    account = CombinedAccount(D(100))
    account.apply(fill("one", qty="2"))
    account.apply(fill("two", qty="1", price="20", time=1))
    result = account.apply(fill("close-two", side=-1, qty="1", price="25", lot="two", time=2))
    assert result.realized_pnl == 5
    assert result.positions[0].lots[0].lot_id == "one"
    assert result.positions[0].quantity == 2


@pytest.mark.parametrize(
    "side,exit_price,pnl", [(1, "15", "10"), (-1, "5", "10"), (-1, "15", "-10")]
)
def test_signed_futures_partial_close_releases_only_corresponding_collateral(
    side: int, exit_price: str, pnl: str
) -> None:
    account = CombinedAccount(D(100))
    account.apply(fill("open", venue="futures", side=side, qty="4", fee="1"))
    result = account.apply(
        fill("close", venue="futures", side=-side, qty="2", price=exit_price, fee=".5", time=1)
    )
    assert result.free_cash == D("88.5") + D(pnl)
    assert result.realized_pnl == D(pnl)
    assert result.positions[0].quantity == side * 2
    assert result.positions[0].collateral == 10
    assert result.fees == D("1.5")
    assert result.reconciliation_residual == 0


def test_funding_is_signed_actual_wallet_cash_and_duplicate_is_noop() -> None:
    account = CombinedAccount(D(100))
    account.apply(fill("open", venue="futures", side=-1, qty="2"))
    event = FundingEvent("fund", 1, "BTCUSDT", D("-3"))
    result = account.apply(event)
    assert result.free_cash == 87
    assert result.equity == 97
    assert result.funding == -3
    assert account.apply(event) == result
    result = account.apply(FundingEvent("credit", 2, "BTCUSDT", D("2")))
    assert result.free_cash == 89
    assert result.funding == -1
    assert account.apply(event) == result


def test_global_conflicting_event_id_and_invalid_events_do_not_mutate() -> None:
    account = CombinedAccount(D(100))
    event = fill("one")
    result = account.apply(event)
    assert account.apply(event) == result
    for bad in (
        replace(event, fee=D(1)),
        fill("overclose", side=-1, qty="2"),
        fill("nan", qty="NaN"),
        fill("negative-fee", fee="-1"),
        replace(fill("badside"), side=True),
        fill("wrong-lot", side=-1, lot="absent"),
        FundingEvent("one", 0, "BTCUSDT", D(0)),
    ):
        with pytest.raises(ValueError):
            account.apply(bad)
        assert account.snapshot() == result


def test_completed_overspend_books_negative_cash_and_latches_failure() -> None:
    account = CombinedAccount(D(10))
    result = account.apply(fill("overspend", qty="1", fee="2"))
    assert result.free_cash == -2
    assert result.equity == 8
    assert not result.integrity_ok and "negative_free_cash" in result.issues
    result = account.apply(fill("sell", side=-1, price="20", time=1))
    assert result.free_cash == 18 and not result.integrity_ok


def test_futures_loss_and_funding_can_exhaust_cash_without_rejecting_actual_events() -> None:
    account = CombinedAccount(D(10))
    account.apply(fill("open", venue="futures", qty="2"))
    result = account.apply(FundingEvent("fund", 1, "BTCUSDT", D(-1)))
    assert result.free_cash == -1 and result.equity == 9
    result = account.apply(fill("close", venue="futures", side=-1, qty="2", price="1", time=2))
    assert result.free_cash == -9 and result.equity == -9
    assert not result.positions


def test_explicit_marks_must_cover_positions_and_defaults_are_identified_fill_marks() -> None:
    account = CombinedAccount(D(100))
    result = account.apply(fill("open", time=5))
    assert result.positions[0].mark_source == "fill"
    assert result.positions[0].mark_timestamp_ms == 5
    for marks in ({}, {"BTCUSDT": D("NaN")}, {"BTCUSDT": D(0)}):
        with pytest.raises(ValueError):
            account.snapshot(marks)
    marked = account.snapshot({"BTCUSDT": D(20)})
    assert marked.equity == 110 and marked.positions[0].mark_source == "caller"
    assert account.snapshot() == result


def test_exact_decimals_do_not_depend_on_context_and_reconcile() -> None:
    account = CombinedAccount(D(100))
    with localcontext() as context:
        context.prec = 2
        account.apply(fill("open", qty=".123456789", price="13.123456789", fee=".000000001"))
        result = account.apply(
            fill("close", side=-1, qty=".023456789", price="19.123456789", time=1)
        )
    assert result.positions[0].quantity == D(".1")
    assert result.realized_pnl == D(".140740734")
    assert result.reconciliation_residual == 0


def test_backward_new_event_rejected_but_duplicate_old_event_allowed() -> None:
    account = CombinedAccount(D(100))
    event = fill("open", time=2)
    account.apply(event)
    result = account.apply(fill("more", time=3))
    assert account.apply(event) == result
    with pytest.raises(ValueError):
        account.apply(fill("backwards", time=1))
    assert account.snapshot() == result


def test_malformed_equal_duplicate_cannot_bypass_side_validation() -> None:
    account = CombinedAccount(D(100))
    event = fill("open")
    result = account.apply(event)
    with pytest.raises(ValueError):
        account.apply(replace(event, side=True))
    assert account.snapshot() == result
