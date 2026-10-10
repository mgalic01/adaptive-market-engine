from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.filters import OrderFilters

START = month_bounds_ms("2024-10")[0]
HOUR = 3600000


def bar(hour, price=100, close=None):
    value = D(price)
    closing = value if close is None else D(close)
    return Kline(
        START + hour * HOUR,
        value,
        max(value, closing),
        min(value, closing),
        closing,
        D(1),
        D(1),
        D(1),
    )


def filters(maximum="100000", minimum=".001"):
    return OrderFilters(*map(D, (".001", maximum, minimum, "5", ".001", maximum, minimum, "1")))


def run(rows, first=None, limits=None, end=5):
    from crypto_grid_bot.trend.full_size_hold import replay_full_size_hold

    return replay_full_size_hold(
        rows,
        first or dict.fromkeys(rows, "2023-01"),
        limits or {symbol: filters() for symbol in rows},
        START,
        START + end * HOUR,
    )


def test_delayed_coin_keeps_equal_fee_inclusive_budget_and_no_late_join():
    result = run(
        {"BTCUSDT": [bar(1), bar(3, 200)], "ETHUSDT": [bar(3, 50)], "SOLUSDT": [bar(1)]},
        {"BTCUSDT": "2023-01", "ETHUSDT": "2023-01", "SOLUSDT": "2024-11"},
    )
    assert result.reason is None
    assert result.scheduled_ms == START + HOUR
    assert result.purchase_times == {"BTCUSDT": START + HOUR, "ETHUSDT": START + 3 * HOUR}
    assert result.budgets == {"BTCUSDT": D(5000), "ETHUSDT": D(5000)}
    fills = result.account.fills
    assert len(fills) == 2 and all(fill.quantity > 0 for fill in fills)
    for fill in fills:
        assert D(4999) < fill.quantity * fill.price + fill.fee <= D(5000)
    assert result.account.audit().exact
    assert result.account.cash < 1
    assert result.equity_path[-1].kind == "terminal"
    assert result.equity_path[-1].equity == result.account.mark(
        {"BTCUSDT": D(200), "ETHUSDT": D(50)}
    )


def test_absent_purchase_is_unavailable_without_redistribution():
    result = run({"BTCUSDT": [bar(1)], "ETHUSDT": []})
    assert result.reason == "unavailable_first_purchase"
    assert result.missing_symbols == ("ETHUSDT",)
    assert len(result.account.fills) == 1
    assert result.account.cash >= 5000


def test_no_sales_and_gap_marks_carry_open_but_terminal_uses_close():
    result = run({"BTCUSDT": [bar(1, 100, 120)]})
    assert len(result.account.fills) == 1
    marks = {(p.timestamp_ms, p.kind): p.equity for p in result.equity_path}
    assert marks[START + 2 * HOUR, "open"] == result.account.mark({"BTCUSDT": D(100)})
    assert result.equity_path[-1].equity == result.account.mark({"BTCUSDT": D(120)})
    assert result.samples[0] == (START + HOUR, D(10000))
    assert result.samples[-1] == (START + 5 * HOUR, result.equity_path[-1].equity)
    assert result.max_drawdown > 0


def test_maximum_order_splitting_and_minimum_refusal_keep_account_auditable():
    split = run({"BTCUSDT": [bar(1)]}, limits={"BTCUSDT": filters(maximum="20")})
    assert len(split.account.fills) == 5
    assert all(fill.quantity <= 20 for fill in split.account.fills)
    refused = run({"BTCUSDT": [bar(1)]}, limits={"BTCUSDT": filters(minimum="200")})
    assert refused.reason is None
    assert refused.account.cash == 10000 and refused.account.fills[0].quantity == 0
    assert refused.account.audit().exact


@pytest.mark.parametrize("damage", ["duplicate", "unsorted", "reserved", "no_member"])
def test_invalid_inputs_fail_without_becoming_strategy_outcomes(damage):
    rows = {"BTCUSDT": [bar(1), bar(2)]}
    first = {"BTCUSDT": "2023-01"}
    if damage == "duplicate":
        rows["BTCUSDT"] *= 2
    elif damage == "unsorted":
        rows["BTCUSDT"].reverse()
    elif damage == "reserved":
        rows["BTCUSDT"] = [Kline(month_bounds_ms("2025-01")[0], *([D(100)] * 7))]
    else:
        first["BTCUSDT"] = "2024-11"
    with pytest.raises(ValueError):
        run(rows, first)


def test_no_purchase_at_exclusive_end_or_before_scheduled_hour():
    result = run({"BTCUSDT": [bar(0), bar(5)]})
    assert result.reason == "unavailable_first_purchase"
    assert result.account.cash == 10000
    assert result.account.fills == []


def test_sub_step_budget_records_refusal_without_retry():
    result = run({"BTCUSDT": [bar(1, "100000000"), bar(2, 1)]})
    assert result.reason is None
    assert len(result.account.fills) == 1
    assert result.account.fills[0].reason == "minimum_quantity"
    assert result.account.cash == 10000


def test_engine_failure_preserves_prior_purchase_evidence():
    from crypto_grid_bot.trend.full_size_hold import FullSizeHoldExecutionError

    invalid = Kline(START + 2 * HOUR, D(100), D(90), D(80), D(85), D(1), D(1), D(1))
    with pytest.raises(FullSizeHoldExecutionError) as error:
        run({"BTCUSDT": [bar(1), invalid]})
    result = error.value.result
    assert result.reason == "engine_failure"
    assert len(result.account.fills) == 1
    assert result.account.audit().exact
    assert result.equity_path[-1].timestamp_ms < START + 2 * HOUR
