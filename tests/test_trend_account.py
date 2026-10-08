"""Synthetic futures ledger examples, no market access."""

from decimal import ROUND_DOWN, localcontext
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.orders import OrderIntent

T = 1577836800000


def account(**kwargs):
    from crypto_grid_bot.trend.account import FuturesAccount

    return FuturesAccount(**kwargs)


def fill(a, quantity, price, reduce=False, symbol="BTCUSDT", timestamp=T):
    return a.fill(symbol, OrderIntent(D(quantity), reduce), D(price), timestamp)


def test_futures_open_moves_only_fee_and_mark_includes_slippage():
    a = account()
    record = fill(a, "2", "100")
    assert record.price == D("100.0500")
    assert record.fee == D(".10005000")
    assert a.wallet == D("9999.89995000")
    assert a.positions["BTCUSDT"].quantity == 2
    mark = a.mark({"BTCUSDT": D(100)})
    assert mark.unrealized == D("-.1000")
    assert mark.equity == D("9999.79995000")
    assert mark.gross_notional == 200


def test_weighted_entry_partial_close_and_short_realized_sign():
    a = account()
    fill(a, "2", "100")
    fill(a, "2", "200")
    assert a.positions["BTCUSDT"].average_entry == D("150.075")
    close = fill(a, "-1", "180", True)
    assert close.realized == D("29.835")
    assert a.positions["BTCUSDT"].average_entry == D("150.075")
    assert a.positions["BTCUSDT"].quantity == 3
    b = account()
    fill(b, "-2", "100")
    close = fill(b, "1", "80", True)
    assert close.realized == D("19.91")
    assert b.positions["BTCUSDT"].quantity == -1


def test_double_cost_stress_and_close_then_reopen():
    a = account(cost_multiple=2)
    first = fill(a, "1", "100")
    assert first.price == D("100.1")
    assert first.fee == D(".1001")
    fill(a, "-1", "110", True)
    fill(a, "-1", "110")
    assert a.positions["BTCUSDT"].average_entry == D("109.89")


@pytest.mark.parametrize(
    "quantity,reduce", [("-2", True), ("1", True), ("-1", False), ("0", False), ("NaN", False)]
)
def test_invalid_fill_is_atomic(quantity, reduce):
    a = account()
    fill(a, "1", "100")
    before = (a.wallet, dict(a.positions), tuple(a.fills))
    with pytest.raises(ValueError):
        fill(a, quantity, "100", reduce)
    assert (a.wallet, a.positions, tuple(a.fills)) == before


def test_funding_group_long_short_and_negative_rate():
    a = account()
    fill(a, "2", "100")
    fill(a, "-3", "100", symbol="ETHUSDT")
    before = a.wallet
    event = a.fund(
        T, {"BTCUSDT": D(".01"), "ETHUSDT": D(".01")}, {"BTCUSDT": D(100), "ETHUSDT": D(100)}
    )
    assert [row.payment for row in event.payments] == [D(2), D(-3)]
    assert a.wallet == before + 1
    a.fund(T + 1, {"BTCUSDT": D("-.01")}, {"BTCUSDT": D(100)})
    assert a.wallet == before + 3


def test_invalid_funding_group_does_not_partially_charge():
    a = account()
    fill(a, "1", "100")
    fill(a, "1", "100", symbol="ETHUSDT")
    before = a.wallet
    with pytest.raises(ValueError):
        a.fund(T, {"BTCUSDT": D(".1"), "ETHUSDT": D("NaN")}, {"BTCUSDT": D(100), "ETHUSDT": D(100)})
    assert a.wallet == before
    assert not a.funding


def test_liquidation_at_equality_is_terminal_without_fill():
    a = account(initial=D("11.00025"))
    fill(a, "10", "100")
    before = (a.wallet, tuple(a.fills))
    mark = a.check_liquidation({"BTCUSDT": D(100)}, T)
    assert mark.equity == 10
    assert mark.margin_ratio == D(".01")
    assert a.liquidation is not None
    assert (a.wallet, tuple(a.fills)) == before
    assert a.positions["BTCUSDT"].quantity == 10
    with pytest.raises(ValueError, match="terminal"):
        fill(a, "-10", "100", True)
    with pytest.raises(ValueError, match="terminal"):
        a.fund(T + 1, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})


def test_flat_book_has_no_margin_ratio_or_liquidation():
    a = account()
    mark = a.check_liquidation({}, T)
    assert mark.margin_ratio is None
    assert mark.gross_notional == 0
    assert a.liquidation is None


def test_ledger_audit_reports_frozen_precision_conflict_without_hiding_it():
    a = account()
    fill(a, "1", "1")
    fill(a, "6", "2")
    fill(a, "-7", "2", True)
    audit = a.audit({})
    assert audit.wallet_residual == 0
    assert audit.quantity_residuals == {"BTCUSDT": D(0)}
    assert audit.equity_residual == D("-1e-59")
    assert not audit.exact


def test_account_operations_ignore_ambient_context():
    def run():
        a = account()
        fill(a, "2", "100")
        fill(a, "1", "123")
        a.fund(T, {"BTCUSDT": D(".001")}, {"BTCUSDT": D(120)})
        return a.wallet, a.mark({"BTCUSDT": D(120)})

    expected = run()
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert run() == expected


def test_constructor_validation_ignores_ambient_inexact_trap():
    from decimal import Inexact

    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        a = account(initial=D("10000.12345"))
        assert a.wallet == D("10000.12345")


def test_funding_order_independence_and_duplicate_group_refusal():
    def run(reverse=False):
        a = account()
        fill(a, "2", "100")
        fill(a, "-3", "100", symbol="ETHUSDT")
        pairs = [("BTCUSDT", D(".01")), ("ETHUSDT", D(".01"))]
        a.fund(
            T, dict(reversed(pairs) if reverse else pairs), {"BTCUSDT": D(100), "ETHUSDT": D(100)}
        )
        return a

    a, b = run(), run(True)
    assert a.funding == b.funding
    assert a.wallet == b.wallet
    before = (a.wallet, a.funding)
    with pytest.raises(ValueError, match="complete group"):
        a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})
    assert (a.wallet, a.funding) == before


def test_nonchronological_and_reserved_events_leave_account_unchanged():
    a = account()
    fill(a, "1", "100", timestamp=T + 1000)
    before = (a.wallet, a.fills)
    with pytest.raises(ValueError):
        fill(a, "1", "100", timestamp=T)
    with pytest.raises(ValueError):
        fill(a, "1", "100", timestamp=1735689600000)
    assert (a.wallet, a.fills) == before


def test_missing_marks_fail_and_price_gap_can_liquidate():
    a = account()
    fill(a, "200", "100")
    with pytest.raises(ValueError, match="missing"):
        a.mark({})
    assert a.check_liquidation({"BTCUSDT": D(100)}, T).margin_ratio > D(".01")
    a.check_liquidation({"BTCUSDT": D(50)}, T + 3600000)
    assert a.liquidation is not None
    assert a.liquidation.mark.prices == {"BTCUSDT": D(50)}
    assert len(a.fills) == 1


def test_above_liquidation_boundary_and_simple_audit_are_exact():
    a = account(initial=D("11.00025001"))
    fill(a, "10", "100")
    a.check_liquidation({"BTCUSDT": D(100)}, T)
    assert a.liquidation is None
    assert a.audit({"BTCUSDT": D(100)}).exact


def test_wallet_audit_detects_corrupted_totals():
    a = account()
    fill(a, "1", "100")
    a._fees += D(1)  # Deliberate state corruption to exercise independent reconstruction.
    assert a.audit({"BTCUSDT": D(100)}).wallet_residual == -1


def test_quantity_audit_detects_lost_position():
    a = account()
    fill(a, "1", "100")
    del a._positions["BTCUSDT"]
    result = a.audit({"BTCUSDT": D(100)})
    assert result.quantity_residuals == {"BTCUSDT": D(-1)}
    assert not result.exact


def test_liquidation_prices_cannot_be_mutated():
    a = account()
    fill(a, "200", "100")
    prices = {"BTCUSDT": D(50)}
    mark = a.check_liquidation(prices, T)
    prices["BTCUSDT"] = D(99)
    with pytest.raises(TypeError):
        mark.prices["BTCUSDT"] = D(99)
    assert a.liquidation.mark.prices == {"BTCUSDT": D(50)}


def test_empty_funding_group_does_not_advance_clocks():
    a = account()
    fill(a, "1", "100")
    before = (a.wallet, a.funding, a._clock, a._funding_clock)
    with pytest.raises(ValueError, match="empty"):
        a.fund(T + 1000, {}, {})
    assert (a.wallet, a.funding, a._clock, a._funding_clock) == before
    event = a.fund(T, {"BTCUSDT": D(".01")}, {"BTCUSDT": D(100)})
    assert event.payments[0].payment == D(1)


@pytest.mark.parametrize(
    "residual,accepted",
    [
        ("0", True),
        ("-1e-59", True),
        ("1e-18", True),
        ("-1e-18", True),
        ("1.0000000000000000001e-18", False),
        ("-1.0000000000000000001e-18", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_equity_audit_tolerance_is_bounded_and_preserves_residual(residual, accepted):
    from crypto_grid_bot.trend.account import AccountingAudit

    audit = AccountingAudit(D(0), {"BTCUSDT": D(0)}, D(residual))
    assert audit.accepted is accepted
    assert str(audit.equity_residual) == str(D(residual))


def test_audit_tolerance_never_relaxes_wallet_or_quantity():
    from crypto_grid_bot.trend.account import AccountingAudit

    assert not AccountingAudit(D("1e-59"), {}, D(0)).accepted
    assert not AccountingAudit(D(0), {"BTCUSDT": D("1e-59")}, D(0)).accepted
