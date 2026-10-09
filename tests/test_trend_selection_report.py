from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.orchestration import TrainingScore
from crypto_grid_bot.trend.walk_forward import RULES

FIRST = {"BTCUSDT": "2023-04", "ETHUSDT": "2024-11"}
STAMP = month_bounds_ms("2024-10")[0]


def scores():
    return tuple(TrainingScore(f"run-{r}", "2024-10", r, D(1), None) for r in RULES)


def test_selection_recomputes_ties_and_reports_monthly_cohort_counts():
    from crypto_grid_bot.trend.selection_report import selection_report

    result = selection_report(scores(), {STAMP: "R1"}, FIRST, {"BTCUSDT": frozenset({"2024-12"})})
    assert result.long_only_quarters == 0
    assert result.quarters[0].monthly_coin_counts == (
        ("2024-10", 1),
        ("2024-11", 2),
        ("2024-12", 1),
    )
    assert result.quarters[0].training == scores()


def test_all_invalid_is_flat_and_long_only_frequency_is_explicit():
    from crypto_grid_bot.trend.selection_report import selection_report

    invalid = tuple(replace(s, sharpe=None, invalid_reason="liquidation") for s in scores())
    assert selection_report(invalid, {STAMP: None}, FIRST).flat_quarters == 1
    selected = tuple(replace(s, sharpe=D(2) if s.rule == "R2L" else D(1)) for s in scores())
    result = selection_report(selected, {STAMP: "R2L"}, FIRST)
    assert result.long_only_quarters == 1
    assert result.long_only_share == 1


@pytest.mark.parametrize(
    "damage",
    ["missing", "duplicate", "run_id", "false_pick", "engine", "nan", "invalid_score", "extra"],
)
def test_inconsistent_selection_evidence_is_rejected(damage):
    from crypto_grid_bot.trend.selection_report import selection_report

    rows, picks = list(scores()), {STAMP: "R1"}
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    elif damage == "run_id":
        rows[1] = replace(rows[1], run_id=rows[0].run_id)
    elif damage == "false_pick":
        picks[STAMP] = "R2"
    elif damage == "engine":
        rows[0] = replace(rows[0], sharpe=None, invalid_reason="engine_failure")
    elif damage == "nan":
        rows[0] = replace(rows[0], sharpe=D("NaN"))
    elif damage == "invalid_score":
        rows[0] = replace(rows[0], invalid_reason="liquidation")
    else:
        rows.append(replace(rows[0], run_id="extra", test_month="2024-07"))
    with pytest.raises(ValueError):
        selection_report(rows, picks, FIRST)
