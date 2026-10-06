"""Uptrend sizing for spec v2 (§5): the entry limits, the stop arithmetic and the market buy.

Prices, sizes and limits are constructed to hit each bound; nothing here is backtest evidence.
The market buy is the least of three bounds (depth, cash, risk) and refuses in one of two ways,
which the entry reads differently: "budget" ends it, "depth" waits for the next quote.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from crypto_grid_bot.backtest import trend_benchmark
from crypto_grid_bot.simulation import execution
from crypto_grid_bot.simulation.models import ZERO, Account, LimitOrder, MarketRules, Quote
from crypto_grid_bot.simulation.uptrend import (
    ATR_MULTIPLE,
    CAPITAL_CAP,
    RISK_FRACTION,
    UptrendPosition,
    entry_limits,
    initial_stop,
    stop_distance,
    trailed_stop,
)


def test_entry_limits_and_stop_distance():
    assert entry_limits(D(100), D(100)) == (D(60), D(4))  # 0.60 x 100 and 0.04 x 100
    assert stop_distance(D(100), D(90)) == D("0.1")
    assert stop_distance(D(100), D(100)) == D(0)  # s <= 0: no entry


def test_trailed_stop_never_moves_down():
    assert trailed_stop(D(95), D(100), D(2)) == D(95)  # 100-6 = 94 < 95
    assert trailed_stop(D(95), D(110), D(2)) == D(104)


RULES = MarketRules(
    symbol="BTCUSDT",
    tick_size=D("0.01"),
    quantity_step=D("0.001"),
    minimum_notional=D("5"),
    fee_rate=D("0"),
    slippage_rate=D("0"),
    participation=D("0.10"),
    taker_fee_rate=D("0.0009"),
)
T0 = "2024-01-01T00:00:00+00:00"


def quote(ask_size, ask=D("100")):
    return Quote("e1", "BTCUSDT", T0, T0, ask - D("0.01"), ask, D(5), ask_size)


def buy(ask_size, *, cash, risk, stop, ask=D("100")):
    account = Account.start(D(100))
    q = quote(ask_size, ask)
    return execution.market_buy(account, q, RULES, cash_left=cash, risk_left=risk, stop=stop)


def test_buy_price_matches_trend_benchmark():
    rules = replace(RULES, slippage_rate=D("0.00033"))  # 100.033 rounds up to 100.04
    assert execution.buy_price(quote(D(5)), rules) == trend_benchmark.buy_price(quote(D(5)), rules)


def test_buy_price_rounds_up_to_the_tick_and_adds_none_when_exact():
    rules = replace(RULES, slippage_rate=D("0.001"))
    assert execution.buy_price(quote(D(5), D("100")), rules) == D("100.10")  # exactly 100.100
    assert execution.buy_price(quote(D(5), D("100.01")), rules) == D("100.12")  # 100.11001 up
    with localcontext() as context:
        context.prec = 3  # the price is computed at the simulator's precision, not this one
        assert execution.buy_price(quote(D(5), D("100.01")), rules) == D("100.12")


def test_market_buy_bounds():
    # The price is 100 and the all-in unit cost 100.09. Risk 100 at stop 50 allows 2.
    # Depth: 2 x 0.10 = 0.2 is below the cash bound's 40 / 100.09 -> 0.399.
    result = buy(D(2), cash=D(40), risk=D(100), stop=D(50))
    assert (result.fill.price, result.fill.quantity, result.fill.fee) == (
        D(100),
        D("0.2"),
        D("0.018"),
    )
    # Cash: 5 x 0.10 = 0.5 is above 0.399.
    result = buy(D(5), cash=D(40), risk=D(100), stop=D(50))
    assert (result.fill.quantity, result.fill.fee) == (D("0.399"), D("0.03591"))
    # Risk: 2 left at stop 90 allows 2 / 10 = 0.2, below the cash bound's 0.399.
    assert buy(D(5), cash=D(40), risk=D(2), stop=D(90)).fill.quantity == D("0.2")


def test_market_buy_refusals_tell_depth_from_budget():
    # Budget: 4 / 100.09 -> 0.039, and 0.039 x 100 = 3.9 < 5, so the entry ends.
    result = buy(D(5), cash=D(4), risk=D(100), stop=D(50))
    assert (result.fill, result.refusal) == (None, "budget")
    # Depth: 0.4 x 0.10 = 0.04, and 0.04 x 100 = 4 < 5, with budget to spare: it waits.
    result = buy(D("0.4"), cash=D(40), risk=D(100), stop=D(50))
    assert (result.fill, result.refusal) == (None, "depth")


def test_market_buy_is_bounded_by_spendable_cash():
    # The cash cap allows 40, but the account can spend only 10: 10 / 100.09 -> 0.099.
    account = Account.start(D(10))
    result = execution.market_buy(
        account, quote(D(5)), RULES, cash_left=D(40), risk_left=D(100), stop=D(50)
    )
    assert result.fill.quantity == D("0.099") and account.cash >= 0


def test_a_later_buy_at_a_higher_price_buys_less():
    # Stop 90 with 2 of the risk allowance left: at 120 that allows 2 / 30 -> 0.066.
    assert buy(D(50), cash=D(40), risk=D(2), stop=D(90), ask=D(120)).fill.quantity == D("0.066")


def test_market_buy_never_risks_more_than_its_allowance():
    # 1E-55 below 0.4 x (100 - 90): the quotient rounds up to 0.4 at precision 50,
    # and 0.4 would risk 4, so the guard lowers it to 0.399.
    with localcontext() as context:
        context.prec = 80
        risk = D(4) - D("1E-55")
    assert buy(D(5), cash=D(60), risk=risk, stop=D(90)).fill.quantity == D("0.399")


def test_market_buy_never_spends_more_than_its_cash():
    # 1E-55 below 0.4 x 100.09: the quotient rounds up to 0.4 at precision 50,
    # and 0.4 would cost 40.036, so the guard lowers it to 0.399.
    with localcontext() as context:
        context.prec = 80
        cash = D("40.036") - D("1E-55")
    assert buy(D(5), cash=cash, risk=D(100), stop=D(50)).fill.quantity == D("0.399")


def test_the_spec_constants():
    assert (D("0.04"), D("0.60"), D(3)) == (RISK_FRACTION, CAPITAL_CAP, ATR_MULTIPLE)


def test_initial_stop_is_three_atr_below_the_close():
    assert initial_stop(D(100), D(2)) == D(94)  # 100 - 3 x 2
    assert initial_stop(D("100.5"), D("1.25")) == D("96.75")


def test_a_shrinking_atr_raises_the_trailed_stop_without_a_new_high():
    # Highest close 110: the ATR falling from 2 to 1 lifts the stop from 104 to 107.
    assert trailed_stop(D(104), D(110), D(1)) == D(107)


def test_stop_distance_is_negative_when_the_price_is_below_the_stop():
    assert stop_distance(D(90), D(100)) < 0


def test_the_market_buy_settles_on_the_account_at_the_taker_fee():
    account = Account.start(D(100))
    result = execution.market_buy(
        account, quote(D(2)), RULES, cash_left=D(40), risk_left=D(100), stop=D(50)
    )
    fill = result.fill
    assert result.refusal == ""
    assert (fill.order_id, fill.side, fill.remaining) == ("uptrend/buy/e1", "buy", ZERO)
    assert account.inventory == D("0.2")
    assert account.cash == D(100) - D("0.2") * D(100) - D("0.018")
    assert (account.fees, account.fill_count, account.orders) == (D("0.018"), 1, {})


def test_a_refused_buy_leaves_the_account_untouched():
    for ask_size, cash in ((D(5), D(4)), (D("0.4"), D(40))):  # budget, then depth
        account = Account.start(D(100))
        before = copy.deepcopy(account)
        result = execution.market_buy(
            account, quote(ask_size), RULES, cash_left=cash, risk_left=D(100), stop=D(50)
        )
        assert result.fill is None and account == before


def test_budget_wins_when_both_the_budget_and_the_depth_are_short():
    # Depth 0.04 x 100 = 4 and cash 4 / 100.09 -> 0.039 are both below 5: the entry ends.
    result = buy(D("0.4"), cash=D(4), risk=D(100), stop=D(50))
    assert (result.fill, result.refusal) == (None, "budget")


def test_an_exhausted_risk_allowance_ends_the_entry():
    assert buy(D(5), cash=D(40), risk=D(0), stop=D(90)).refusal == "budget"
    # A limit overspent, even by a last digit, reads as nothing left, never as a negative buy.
    for overspent in (D("-1E-40"), D(-5)):
        assert buy(D(5), cash=overspent, risk=D(100), stop=D(50)).refusal == "budget"
        assert buy(D(5), cash=D(40), risk=overspent, stop=D(90)).refusal == "budget"


def test_the_buy_is_bounded_by_cash_the_account_has_reserved_elsewhere():
    # A resting buy of 8 x 10 reserves 80 of the 100: 20 is spendable, 20 / 100.09 -> 0.199.
    account = Account.start(D(100))
    execution.place(account, LimitOrder("rest", "buy", D(10), D(8), D(8)), RULES)
    result = execution.market_buy(
        account, quote(D(5)), RULES, cash_left=D(60), risk_left=D(100), stop=D(50)
    )
    assert result.fill.quantity == D("0.199") and account.available_quote(RULES) >= 0


def test_a_buy_at_or_below_its_stop_is_a_caller_error():
    for stop in (D(100), D(101)):
        with pytest.raises(ValueError, match="priced above its stop"):
            buy(D(5), cash=D(40), risk=D(100), stop=stop)


def test_a_fill_never_exceeds_either_limit_over_a_sweep():
    filled = 0
    for cash in (D("5.01"), D("17.3"), D("40.036"), D("99.99")):
        for risk in (D("0.05"), D("0.31"), D(2), D("3.999")):
            for stop in (D(90), D("97.5")):
                result = buy(D(500), cash=cash, risk=risk, stop=stop)
                if result.fill is None:
                    continue
                filled += 1
                paid = result.fill.price * result.fill.quantity + result.fill.fee
                assert paid <= cash
                assert result.fill.quantity * (result.fill.price - stop) <= risk
    assert filled > 0


def test_the_buy_does_not_depend_on_the_ambient_precision():
    # A price and a cost of many digits: at an ambient precision of 6 they would round.
    rules = replace(RULES, tick_size=D("0.00001"), quantity_step=D("0.00001"))
    wide = Quote("e1", "BTCUSDT", T0, T0, D("12345.67890"), D("12345.67891"), D(5), D(100))

    def run():
        account = Account.start(D(100000))
        result = execution.market_buy(
            account, wide, rules, cash_left=D(1000), risk_left=D(100), stop=D(12000)
        )
        return result, account

    expected = run()
    with localcontext() as context:
        context.prec = 6
        assert run() == expected


def test_the_entry_limits_do_not_depend_on_the_ambient_precision():
    with localcontext() as context:
        context.prec = 6
        limits = entry_limits(D("123456.789012"), D("98765.4321"))
    assert limits == (D("74074.0734072"), D("3950.617284"))


def test_the_entry_limits_never_round_up():
    # 0.04 x (1 + 1.5E-50) is 0.04 + 6E-52: 0.6 of a unit in the last place at precision 50,
    # which round-half-even would round up to 0.04 + 1E-51, a limit above 4% of equity.
    with localcontext() as context:
        context.prec = 80
        equity = D(1) + D("1.5E-50")
    assert entry_limits(D(100), equity)[1] == D("0.04")


def test_a_position_starts_entering_with_nothing_bought():
    position = UptrendPosition(
        cash_cap=D(60),
        risk_allowance=D(4),
        stop=D(94),
        highest_close=D(100),
        stop_day_ms=0,
        entered_at=T0,
    )
    assert (position.spent, position.risk_used, position.quantity) == (ZERO, ZERO, ZERO)
    assert (position.exit_reason, position.phase) == ("", "entering")
    position.phase = "holding"  # mutable: the engine moves it through its phases
    assert position.phase == "holding"


def test_a_position_is_built_by_keyword_so_no_field_is_mistaken_for_another():
    with pytest.raises(TypeError):
        UptrendPosition(D(60), D(4), D(94), D(100), 0, T0)  # type: ignore[misc]
