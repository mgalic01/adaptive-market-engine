from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotRunner, replay_spot_benchmark

T, HOUR, DAY = 1609459200000, 3600000, 86400000


def accounts(*, manual_hold=False):
    book = DailyDecisions({}, {})
    main = replay_window(book, {}, {}, {}, T, T + 2 * DAY, {T: None})
    smaller = replay_window(book, {}, {}, {}, T, T + 2 * DAY, {T: None}, multiple=1)
    hold = SpotRunner({})
    for i in range(48):
        hold.step(T + i * HOUR, {})
    hold.finish({})
    if not manual_hold:
        hold = replay_spot_benchmark(HoldDecisions({}, {}), {}, {}, T, T + 2 * DAY)
    return main, smaller, hold


def test_flat_actual_accounts_fail_all_frozen_checks_including_strict_a5():
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    result = evaluate_accounts(*accounts(), spot_bars={}, first_months={})
    assert [row.name for row in result] == ["A1", "A2", "A3", "A4", "A5"]
    assert not any(row.passed for row in result)
    assert result[-1].strict
    assert result[-1].observed == result[-1].threshold == 0


@pytest.mark.parametrize(
    "values,expected",
    [
        (("1", "1.3", ".5", ".08", "1", "0"), (True,) * 5),
        ((".999", "1.299", ".499", ".079", "0", "0"), (False,) * 5),
        (("1", "Infinity", "Infinity", ".08", "1", "1"), (True, True, True, True, False)),
    ],
)
def test_exact_frozen_thresholds(values, expected):
    from crypto_grid_bot.trend.acceptance import _score

    assert tuple(row.passed for row in _score(*map(D, values))) == expected


@pytest.mark.parametrize("field", ["size", "cost", "picks", "missing", "invalid"])
def test_account_evidence_must_match_frozen_comparison(field):
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    main, smaller, hold = accounts()
    if field == "size":
        main.runner.multiple = 1
    elif field == "cost":
        main.runner.account.cost_multiple = 2
    elif field == "picks":
        smaller = replace(
            smaller, daily_decisions=tuple((t, "R1", d) for t, _, d in smaller.daily_decisions)
        )
    elif field == "missing":
        smaller = replace(smaller, daily_decisions=smaller.daily_decisions[:-1])
    else:
        main = replace(main, reason="liquidation")
    with pytest.raises(ValueError):
        evaluate_accounts(main, smaller, hold, spot_bars={}, first_months={})


def test_arbitrary_cash_spot_runner_is_not_frozen_benchmark_evidence():
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    main, smaller, hold = accounts(manual_hold=True)
    assert hold.daily_decisions == []
    with pytest.raises(ValueError, match="benchmark"):
        evaluate_accounts(main, smaller, hold, spot_bars={}, first_months={})


def test_real_hold_source_is_accepted_and_changed_signals_or_calendar_are_rejected():
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.trend.acceptance import evaluate_accounts
    from crypto_grid_bot.trend.filters import OrderFilters

    def bar(stamp, price):
        return Kline(stamp, price, price, price, price, D(1), price, D(".5"))

    daily = {"BTCUSDT": [bar(T - (64 - i) * DAY, D(100 + i % 3)) for i in range(64)]}
    first = {"BTCUSDT": "2020-01"}
    filters = {"BTCUSDT": OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))}
    hourly = {"BTCUSDT": [bar(T + i * HOUR, D(100)) for i in range(48)]}
    source = DailyDecisions(daily, first)
    main = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, {T: None})
    smaller = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, {T: None}, multiple=1)
    hold = replay_spot_benchmark(HoldDecisions(daily, first), filters, hourly, T, T + 2 * DAY)
    assert any(fill.quantity for fill in hold.account.fills)
    cash_only = SpotRunner(filters)
    for i in range(48):
        cash_only.step(T + i * HOUR, {"BTCUSDT": (D(100), D(100), D(100))})
    cash_only.finish({"BTCUSDT": D(100)})
    cash_only.daily_decisions = list(hold.daily_decisions)
    with pytest.raises(ValueError, match="submitted"):
        evaluate_accounts(main, smaller, cash_only, spot_bars=daily, first_months=first)
    assert evaluate_accounts(main, smaller, hold, spot_bars=daily, first_months=first)[-1].passed
    with pytest.raises(ValueError, match="benchmark"):
        evaluate_accounts(
            main,
            smaller,
            hold,
            spot_bars=daily,
            first_months=first,
            spot_exclusions={"BTCUSDT": frozenset({"2021-01"})},
        )
    stamp, decision = hold.daily_decisions[0]
    hold.daily_decisions[0] = (stamp, replace(decision, signals={"BTCUSDT": D(0)}))
    with pytest.raises(ValueError, match="benchmark"):
        evaluate_accounts(main, smaller, hold, spot_bars=daily, first_months=first)
