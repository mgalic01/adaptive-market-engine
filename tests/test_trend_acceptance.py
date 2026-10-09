from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotRunner, replay_spot_benchmark

T, HOUR, DAY = 1609459200000, 3600000, 86400000


@pytest.mark.parametrize("copied_multiple", [1, 2])
def test_nonzero_strategy_matches_expected_quarterly_pick(copied_multiple, monkeypatch):
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.trend.acceptance import evaluate_accounts
    from crypto_grid_bot.trend.filters import OrderFilters

    def bar(stamp, price):
        return Kline(stamp, price, price, price, price, D(1), price, D(".5"))

    daily = {"BTCUSDT": [bar(T + (i - 64) * DAY, D(100 + i)) for i in range(66)]}
    first = {"BTCUSDT": "2020-01"}
    filters = {"BTCUSDT": OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))}
    hourly = {"BTCUSDT": [bar(T + i * HOUR, D(164)) for i in range(48)]}
    source = DailyDecisions(daily, first)
    picks = {T: "R1"}
    main = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, picks)
    smaller = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, picks, multiple=1)
    hold = replay_spot_benchmark(HoldDecisions(daily, first), filters, hourly, T, T + 2 * DAY)
    assert main.runner.account.fills and smaller.runner.account.fills
    assert main.daily_decisions[0][2].signals["BTCUSDT"] == 1
    assert [rule for _, rule, _ in main.daily_decisions] == ["R1", "R1"]
    assert (
        len(
            evaluate_accounts(
                main, smaller, hold, spot_bars=daily, first_months=first, expected_picks=picks
            )
        )
        == 5
    )
    from crypto_grid_bot.trend import replay
    from crypto_grid_bot.trend.runner import TrendRunner

    def excluded_runner(*args, **kwargs):
        kwargs["excluded_months"] = {"BTCUSDT": frozenset({"2021-01"})}
        return TrendRunner(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(replay, "TrendRunner", excluded_runner)
        overridden = replay_window(
            source, filters, hourly, {}, T, T + 2 * DAY, picks, multiple=copied_multiple
        )
    assert not overridden.runner.account.fills
    assert overridden.daily_decisions == (main if copied_multiple == 2 else smaller).daily_decisions
    with pytest.raises(ValueError, match="exclusion calendar"):
        evaluate_accounts(
            overridden if copied_multiple == 2 else main,
            overridden if copied_multiple == 1 else smaller,
            hold,
            spot_bars=daily,
            first_months=first,
            expected_picks=picks,
        )
    cash = replay_window(
        source, filters, hourly, {}, T, T + 2 * DAY, {T: None}, multiple=copied_multiple
    )
    cash = replace(
        cash, daily_decisions=(main if copied_multiple == 2 else smaller).daily_decisions
    )
    with pytest.raises(ValueError, match="strategy submitted"):
        evaluate_accounts(
            cash if copied_multiple == 2 else main,
            cash if copied_multiple == 1 else smaller,
            hold,
            spot_bars=daily,
            first_months=first,
            expected_picks=picks,
        )
    stamp, rule, decision = smaller.daily_decisions[-1]
    altered = replace(
        smaller,
        daily_decisions=smaller.daily_decisions[:-1]
        + ((stamp, rule, replace(decision, signals={"BTCUSDT": D(0)})),),
    )
    with pytest.raises(ValueError, match="strategy decisions"):
        evaluate_accounts(
            main, altered, hold, spot_bars=daily, first_months=first, expected_picks=picks
        )


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


@pytest.mark.parametrize("expected", [{T: "R2"}, {T: None, T + DAY: "R2"}])
def test_wrong_or_nonquarterly_expected_schedule_is_rejected(expected):
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    with pytest.raises(ValueError, match="quarterly picks"):
        evaluate_accounts(*accounts(), spot_bars={}, first_months={}, expected_picks=expected)


def test_flat_actual_accounts_fail_all_frozen_checks_including_strict_a5():
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    result = evaluate_accounts(*accounts(), spot_bars={}, first_months={}, expected_picks={T: None})
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
        evaluate_accounts(
            main, smaller, hold, spot_bars={}, first_months={}, expected_picks={T: None}
        )


def test_arbitrary_cash_spot_runner_is_not_frozen_benchmark_evidence():
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    main, smaller, hold = accounts(manual_hold=True)
    assert hold.daily_decisions == []
    with pytest.raises(ValueError, match="benchmark"):
        evaluate_accounts(
            main, smaller, hold, spot_bars={}, first_months={}, expected_picks={T: None}
        )


@pytest.mark.parametrize("excluded", [False, True])
def test_real_hold_source_is_accepted_and_changed_signals_or_calendar_are_rejected(excluded):
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.trend.acceptance import evaluate_accounts
    from crypto_grid_bot.trend.filters import OrderFilters

    def bar(stamp, price):
        return Kline(stamp, price, price, price, price, D(1), price, D(".5"))

    daily = {"BTCUSDT": [bar(T - (64 - i) * DAY, D(100 + i % 3)) for i in range(64)]}
    first = {"BTCUSDT": "2020-01"}
    filters = {"BTCUSDT": OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))}
    hourly = {"BTCUSDT": [bar(T + i * HOUR, D(100)) for i in range(48)]}
    exclusions = {"BTCUSDT": frozenset({"2021-01"})} if excluded else {}
    source = DailyDecisions(daily, first, exclusions)
    main = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, {T: None})
    smaller = replay_window(source, filters, hourly, {}, T, T + 2 * DAY, {T: None}, multiple=1)
    hold = replay_spot_benchmark(
        HoldDecisions(daily, first, exclusions), filters, hourly, T, T + 2 * DAY
    )
    if excluded:
        assert (
            len(
                evaluate_accounts(
                    main,
                    smaller,
                    hold,
                    spot_bars=daily,
                    first_months=first,
                    expected_picks={T: None},
                    spot_exclusions=exclusions,
                )
            )
            == 5
        )
        return
    assert any(fill.quantity for fill in hold.account.fills)
    cash_only = SpotRunner(filters)
    for i in range(48):
        cash_only.step(T + i * HOUR, {"BTCUSDT": (D(100), D(100), D(100))})
    cash_only.finish({"BTCUSDT": D(100)})
    cash_only.daily_decisions = list(hold.daily_decisions)
    with pytest.raises(ValueError, match="submitted"):
        evaluate_accounts(
            main, smaller, cash_only, spot_bars=daily, first_months=first, expected_picks={T: None}
        )
    assert evaluate_accounts(
        main, smaller, hold, spot_bars=daily, first_months=first, expected_picks={T: None}
    )[-1].passed
    smaller.runner.filters["BTCUSDT"] = replace(filters["BTCUSDT"], min_notional=D(10))
    with pytest.raises(ValueError, match="filters"):
        evaluate_accounts(
            main, smaller, hold, spot_bars=daily, first_months=first, expected_picks={T: None}
        )
    smaller.runner.filters["BTCUSDT"] = filters["BTCUSDT"]
    with pytest.raises(ValueError, match="source"):
        evaluate_accounts(
            main,
            smaller,
            hold,
            spot_bars=daily,
            first_months=first,
            expected_picks={T: None},
            spot_exclusions={"BTCUSDT": frozenset({"2021-01"})},
        )
    stamp, decision = hold.daily_decisions[0]
    hold.daily_decisions[0] = (stamp, replace(decision, signals={"BTCUSDT": D(0)}))
    with pytest.raises(ValueError, match="benchmark"):
        evaluate_accounts(
            main, smaller, hold, spot_bars=daily, first_months=first, expected_picks={T: None}
        )
