from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from test_combined_routing import market

from crypto_grid_bot.combined.components import component_plan, grid_target
from crypto_grid_bot.combined.routing import RoutingContext, qualify
from crypto_grid_bot.strategy.perception import TrendState

D = Decimal
HOUR = 3_600_000


def candidate(owner: str = "spot_trend", side: int = 1):
    assessment = replace(market(), atr=D(2), extension=D(1))
    if owner == "spot_grid":
        assessment = replace(assessment, daily=TrendState.RANGE, four_hour=TrendState.RANGE)
    elif side < 0:
        assessment = replace(assessment, daily=TrendState.DOWN, four_hour=TrendState.DOWN)
    context = RoutingContext(
        spot_executable=True, flow_allowed=True, spot_trend=owner != "futures_trend"
    )
    return assessment, qualify(assessment, context)


@pytest.mark.parametrize(
    "owner,side,stop,venue",
    [
        ("spot_trend", 1, "96", "spot"),
        ("futures_trend", 1, "96", "futures"),
        ("futures_trend", -1, "104", "futures"),
    ],
)
def test_trend_stop_uses_current_quote_and_two_atr(
    owner: str, side: int, stop: str, venue: str
) -> None:
    assessment, qualification = candidate(owner, side)
    plan = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(".001"))
    assert plan is not None
    assert (plan.owner, plan.venue, plan.side, plan.stop) == (owner, venue, side, D(stop))
    assert plan.reference_price == 100
    assert plan.levels[0].price == 100
    assert plan.levels[0].risk_weight == 1
    assert plan.spacing is None


def test_grid_geometry_and_equal_risk_weights_include_complete_cost() -> None:
    assessment, qualification = candidate("spot_grid")
    plan = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(".01"))
    assert plan is not None
    assert plan.spacing == 2
    assert tuple(level.price for level in plan.levels) == (D(98), D(96), D(94))
    assert plan.stop == 90
    assert sum(level.risk_weight for level in plan.levels) == 1
    # Stop distances plus conservative1 quote unit round-trip cost:9,7,5.
    assert tuple(level.risk_weight for level in plan.levels) == (
        Fraction(35, 143),
        Fraction(45, 143),
        Fraction(63, 143),
    )
    assert grid_target(plan, D("93.5")) == D("95.5")


def test_grid_atr_floor_and_fractional_risk_multiplier_are_preserved() -> None:
    assessment, qualification = candidate("spot_grid")
    plan = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(0))
    assert plan is not None and plan.spacing == 1 and plan.stop == 93
    assessment, qualification = candidate()
    qualification = replace(qualification, risk_multiplier=D(".5"))
    plan = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(".001"))
    assert plan is not None and plan.risk_multiplier == D(".5")


@pytest.mark.parametrize(
    "change",
    [
        "denied",
        "assessment",
        "reasons",
        "quote",
        "nan",
        "atr",
        "future",
        "stale",
        "cost",
        "badside",
        "spotshort",
        "multiplier",
        "nonpositive-stop",
    ],
)
def test_invalid_or_unqualified_proposal_has_no_executable_plan(change: str) -> None:
    assessment, qualification = candidate()
    price, timestamp, cost = D(100), assessment.decision_ms, D(".001")
    if change == "denied":
        qualification = replace(qualification, allowed=False)
    elif change == "assessment":
        assessment = replace(assessment, available=False)
    elif change == "reasons":
        qualification = replace(qualification, reasons=("blocked",))
    elif change == "quote":
        price = None
    elif change == "nan":
        price = D("NaN")
    elif change == "atr":
        assessment = replace(assessment, atr=D(0))
    elif change == "future":
        timestamp += 1
    elif change == "stale":
        timestamp -= HOUR + 1
    elif change == "cost":
        cost = D(-1)
    elif change == "badside":
        qualification = replace(qualification, side=True)
    elif change == "spotshort":
        qualification = replace(qualification, side=-1)
    elif change == "multiplier":
        qualification = replace(qualification, risk_multiplier=D("NaN"))
    else:
        price = D(3)
    assert component_plan(assessment, qualification, price, timestamp, cost) is None


@pytest.mark.parametrize(
    "field,value", [("symbol", "ETHUSDT"), ("decision_ms", 1), ("schema", "other")]
)
def test_qualification_identity_must_match_assessment(field: str, value: object) -> None:
    assessment, qualification = candidate()
    with pytest.raises(ValueError):
        component_plan(
            assessment,
            replace(qualification, **{field: value}),
            D(100),
            assessment.decision_ms,
            D(0),
        )


def test_grid_rejects_nonpositive_levels_or_stop() -> None:
    assessment, qualification = candidate("spot_grid")
    assert component_plan(assessment, qualification, D(6), assessment.decision_ms, D(0)) is None


def test_quote_age_boundary_and_caller_precision_do_not_change_plan() -> None:
    assessment, qualification = candidate("spot_grid")
    expected = component_plan(
        assessment, qualification, D("100.123"), assessment.decision_ms - HOUR, D(".001")
    )
    with localcontext() as context:
        context.prec = 2
        actual = component_plan(
            assessment, qualification, D("100.123"), assessment.decision_ms - HOUR, D(".001")
        )
    assert actual == expected
    assert actual is not None and actual.reference_price == D("100.123")


def test_target_requires_grid_and_actual_positive_fill() -> None:
    assessment, qualification = candidate()
    trend = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(0))
    assert trend is not None
    with pytest.raises(ValueError):
        grid_target(trend, D(100))
    assessment, qualification = candidate("spot_grid")
    grid = component_plan(assessment, qualification, D(100), assessment.decision_ms, D(0))
    assert grid is not None
    with pytest.raises(ValueError):
        grid_target(grid, D("NaN"))


def test_boolean_qualification_timestamp_cannot_match_integer_assessment() -> None:
    assessment, qualification = candidate()
    assessment = replace(assessment, decision_ms=1)
    qualification = replace(qualification, decision_ms=True)
    assert component_plan(assessment, qualification, D(100), 1, D(0)) is None


def test_forged_allowed_short_in_bull_context_is_still_unusable() -> None:
    assessment, qualification = candidate()
    qualification = replace(qualification, owner="futures_trend", side=-1)
    assert component_plan(assessment, qualification, D(100), assessment.decision_ms, D(0)) is None
