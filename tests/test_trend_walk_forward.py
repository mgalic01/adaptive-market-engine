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
