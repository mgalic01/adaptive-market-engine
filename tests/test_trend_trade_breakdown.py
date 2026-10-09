from decimal import Decimal as D
from decimal import localcontext

import pytest

from crypto_grid_bot.trend.account import FuturesAccount, Position
from crypto_grid_bot.trend.lifecycles import Lifecycle, LifecycleLedger
from crypto_grid_bot.trend.orders import OrderIntent


def test_actual_closed_and_censored_accounts_group_costs_and_short_profit():
    from crypto_grid_bot.trend.trade_breakdown import trade_breakdown

    account, ledger = FuturesAccount(), LifecycleLedger()
    for symbol, quantity in (("BTCUSDT", D(2)), ("ETHUSDT", D(-1))):
        fill = account.fill(symbol, OrderIntent(quantity, False), D(100), 1000)
        ledger.fill(fill, Position(), account.positions[symbol])
    ledger.fund(
        account.fund(
            2000, {"BTCUSDT": D(".01"), "ETHUSDT": D(".02")}, {"BTCUSDT": D(100), "ETHUSDT": D(100)}
        )
    )
    before = account.positions["BTCUSDT"]
    fill = account.fill("BTCUSDT", OrderIntent(D(-2), True), D(110), 3000)
    ledger.fill(fill, before, account.positions["BTCUSDT"], {"signal_zero"})
    ledger.censor(4000, account.positions, {"ETHUSDT": D(90)}, "end_of_run")
    report = trade_breakdown(ledger.completed)
    assert report.total.count == 2
    assert report.total.censored_count == 1
    assert report.total.funding_paid == 2
    assert report.total.funding_received == 2
    assert report.total.net == sum((life.net for life in ledger.completed), D(0))
    assert report.by_coin["BTCUSDT"] == report.by_side["long"]
    assert report.by_coin["ETHUSDT"] == report.by_coin_side[("ETHUSDT", "short")]
    assert report.by_side["short"].unrealized > 0
    assert report.by_side["short"].realized == 0
    with pytest.raises(TypeError):
        report.by_coin["OTHER"] = report.total


def test_zero_and_empty_results_and_decimal_context_do_not_change_aggregation():
    from crypto_grid_bot.trend.trade_breakdown import trade_breakdown

    assert trade_breakdown([]).total.count == 0
    life = Lifecycle("BTCUSDT", "long", 0, end_ms=1, exit_reason="sizing")
    result = trade_breakdown([life])
    assert result.total.count == 1
    assert result.total.net == 0
    life.realized = D("123456789.123456789")
    life.fees = D(".000000001")
    expected = trade_breakdown([life])
    with localcontext() as context:
        context.prec = 3
        assert trade_breakdown([life]) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"end_ms": None},
        {"side": "flat"},
        {"fees": D("NaN")},
        {"funding_received": D(-1)},
        {"end_ms": -1},
    ],
)
def test_bad_or_unfinished_evidence_is_rejected(change):
    from crypto_grid_bot.trend.trade_breakdown import trade_breakdown

    life = Lifecycle("BTCUSDT", "long", 0, end_ms=1, exit_reason="sizing")
    for name, value in change.items():
        setattr(life, name, value)
    with pytest.raises(ValueError):
        trade_breakdown([life])
