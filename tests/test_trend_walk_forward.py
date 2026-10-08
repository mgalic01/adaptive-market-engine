"""Frozen selection order on synthetic scores, without strategy runs."""

from decimal import Decimal as D

import pytest


def test_selection_uses_frozen_tie_order_not_mapping_order():
    from crypto_grid_bot.trend.walk_forward import RULES, choose_rule

    scores = {rule: D(1) for rule in reversed(RULES)}
    assert choose_rule(scores) == "R1"
    scores["R1"] = None
    assert choose_rule(scores) == "R2"
    scores["R6L"] = D(2)
    assert choose_rule(scores) == "R6L"


def test_all_invalid_is_flat_and_negative_scores_still_choose_best():
    from crypto_grid_bot.trend.walk_forward import RULES, choose_rule

    assert choose_rule(dict.fromkeys(RULES)) is None
    scores = dict.fromkeys(RULES, D(-2))
    scores["R3"] = D(-1)
    assert choose_rule(scores) == "R3"


def test_missing_or_nonfinite_scores_fail_as_engine_errors():
    from crypto_grid_bot.trend.walk_forward import RULES, choose_rule

    with pytest.raises(ValueError):
        choose_rule({"R1": D(1)})
    scores = dict.fromkeys(RULES, D(0))
    scores["R2"] = D("NaN")
    with pytest.raises(ValueError):
        choose_rule(scores)


@pytest.mark.parametrize(
    "first,expected,count", [("2019-10", "2021-04", 15), ("2020-01", "2021-07", 14)]
)
def test_calendar_windows_match_frozen_examples(first, expected, count):
    from crypto_grid_bot.trend.walk_forward import windows

    result = windows(first)
    assert len(result) == count
    assert result[0].test_start == expected
    assert result[0].train_start == first
    assert result[-1].test_end_exclusive == "2025-01"


def test_nonquarter_start_rounds_test_forward_and_keeps_exact_training_length():
    from crypto_grid_bot.trend.walk_forward import windows

    first = windows("2020-02")[0]
    assert first.test_start == "2021-10"
    assert first.train_start == "2020-04"
    assert first.train_end_exclusive == first.test_start


def test_reserved_or_too_late_start_is_rejected():
    from crypto_grid_bot.trend.walk_forward import windows

    for first in ("2025-01", "2024-01", "2020-13"):
        with pytest.raises(ValueError):
            windows(first)
