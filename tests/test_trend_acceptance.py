from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.trend.spot_benchmark import SpotRunner

T, HOUR, DAY = 1609459200000, 3600000, 86400000


def accounts():
    book = DailyDecisions({}, {})
    main = replay_window(book, {}, {}, {}, T, T + 2 * DAY, {T: None})
    smaller = replay_window(book, {}, {}, {}, T, T + 2 * DAY, {T: None}, multiple=1)
    hold = SpotRunner({})
    for i in range(48):
        hold.step(T + i * HOUR, {})
    hold.finish({})
    return main, smaller, hold


def test_flat_actual_accounts_fail_all_frozen_checks_including_strict_a5():
    from crypto_grid_bot.trend.acceptance import evaluate_accounts

    result = evaluate_accounts(*accounts())
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
        evaluate_accounts(main, smaller, hold)
