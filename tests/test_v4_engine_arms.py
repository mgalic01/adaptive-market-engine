"""V4 engine task 1: the 12 arms, the 48 cells, the cost profile and the exact number helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

import pytest

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.v4.engine import arms
from crypto_grid_bot.v4.engine.arms import (
    ARMS,
    DIAGNOSTIC_ARMS,
    ArmSpec,
    CellSpec,
    Lookbacks,
    all_cells,
)
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction

ARM_NAMES = (
    "v4_main",
    "v4_long_only",
    "v4_vol25",
    "v4_vol60",
    "v4_faster",
    "v4_slower",
    "v4_btc200_shorts",
    "v4_confirm3",
    "hold_universe",
    "hold_btc",
    "hold_btc_trend",
    "v3_as_built",
)


def _tuple(lookbacks: Lookbacks | None) -> tuple[int, ...]:
    assert lookbacks is not None
    return (
        lookbacks.fast,
        lookbacks.ema_fast,
        lookbacks.ema_slow,
        lookbacks.donchian_entry,
        lookbacks.donchian_exit,
        lookbacks.slow,
        lookbacks.trend_sma,
        lookbacks.trend_slope,
        lookbacks.trend_window,
    )


def test_arms_are_the_twelve_of_the_run_in_order() -> None:
    assert list(ARMS) == list(ARM_NAMES)
    assert len(ARMS) == 12 and len(all_cells()) == 48
    assert all(spec.name == name for name, spec in ARMS.items())
    assert [spec.family for spec in ARMS.values()] == ["v4"] * 8 + ["hold"] * 3 + ["v3"]


def test_the_diagnostic_arms_are_the_eight_of_step_3_in_the_runs_order() -> None:
    assert DIAGNOSTIC_ARMS == (
        "v4_main",
        "v4_long_only",
        "v4_vol25",
        "v4_vol60",
        "v4_faster",
        "v4_slower",
        "hold_universe",
        "hold_btc",
    )
    assert [name for name in ARMS if name in DIAGNOSTIC_ARMS] == list(DIAGNOSTIC_ARMS)


def test_the_new_trend_arms_are_the_main_arm_plus_one_rule() -> None:
    main = ARMS["v4_main"]
    assert (main.short_filter, main.confirm_readings) == (None, None)
    shorts, confirm = ARMS["v4_btc200_shorts"], ARMS["v4_confirm3"]
    assert shorts == replace(main, name="v4_btc200_shorts", short_filter="btc_sma200")
    assert confirm == replace(main, name="v4_confirm3", confirm_readings=3)
    assert (shorts.short_filter, shorts.confirm_readings) == ("btc_sma200", None)
    assert (confirm.short_filter, confirm.confirm_readings) == (None, 3)
    # No other arm carries either rule.
    for name, spec in ARMS.items():
        if name not in ("v4_btc200_shorts", "v4_confirm3"):
            assert (spec.short_filter, spec.confirm_readings) == (None, None), name


def test_btc_is_the_one_coin_of_both_btc_rules() -> None:
    """``BTC`` is hold_btc's and hold_btc_trend's coin and the coin of ``short_filter``'s vote,
    one name for both (step 4a's review)."""
    assert arms.BTC == "BTCUSDT"


def test_an_arm_spec_refuses_a_confirmation_on_a_long_only_arm() -> None:
    """Step 4a's review: the confirmation reads each reading's raw ``s`` and gives the arm its
    effective signal in place of ``s``, so on a long-only arm it would replace ``L`` with a
    signal that can be short. Such an arm is refused when it is made, whatever its name."""
    with pytest.raises(ValueError, match="confirm_readings"):
        replace(ARMS["v4_confirm3"], long_only=True)
    with pytest.raises(ValueError, match="confirm_readings"):
        replace(ARMS["v4_long_only"], name="v4_extra", confirm_readings=3)
    assert replace(ARMS["v4_long_only"], confirm_readings=None) == ARMS["v4_long_only"]


def test_an_arm_spec_refuses_a_short_filter_on_a_long_only_arm() -> None:
    """Step 4a's review: a long-only arm has no short for ``short_filter`` to allow or block, so
    an arm with both is refused when it is made."""
    with pytest.raises(ValueError, match="short_filter"):
        replace(ARMS["v4_btc200_shorts"], long_only=True)
    with pytest.raises(ValueError, match="short_filter"):
        replace(ARMS["v4_long_only"], short_filter="btc_sma200")


def test_hold_btc_trend_is_a_hold_arm() -> None:
    spec = ARMS["hold_btc_trend"]
    assert spec.family == "hold"
    assert spec.vol_target is None and spec.lookbacks is None
    assert (spec.long_only, spec.short_filter, spec.confirm_readings) == (False, None, None)


def test_v3_as_built_is_the_v3_family() -> None:
    spec = ARMS["v3_as_built"]
    assert spec.family == "v3"
    assert spec.vol_target is None and spec.lookbacks is None
    assert (spec.long_only, spec.short_filter, spec.confirm_readings) == (False, None, None)


def test_main_lookbacks_are_the_specs() -> None:
    assert _tuple(ARMS["v4_main"].lookbacks) == (20, 21, 55, 55, 20, 200, 50, 10, 20)


def test_arms_that_share_the_main_signal_use_the_main_lookbacks() -> None:
    main = ARMS["v4_main"].lookbacks
    for name in ("v4_long_only", "v4_vol25", "v4_vol60"):
        assert ARMS[name].lookbacks == main


def test_neighbour_lookbacks_are_the_specs_table() -> None:
    assert _tuple(ARMS["v4_faster"].lookbacks) == (15, 16, 41, 41, 15, 150, 38, 8, 15)
    assert _tuple(ARMS["v4_slower"].lookbacks) == (25, 26, 69, 69, 25, 250, 62, 12, 25)


def test_vol_targets_and_long_only_flags() -> None:
    targets = {
        "v4_main": Decimal("0.40"),
        "v4_long_only": Decimal("0.40"),
        "v4_vol25": Decimal("0.25"),
        "v4_vol60": Decimal("0.60"),
        "v4_faster": Decimal("0.40"),
        "v4_slower": Decimal("0.40"),
    }
    for name, target in targets.items():
        assert ARMS[name].vol_target == target
        assert ARMS[name].long_only is (name == "v4_long_only")
    for name in ("hold_universe", "hold_btc"):
        assert ARMS[name].vol_target is None
        assert ARMS[name].lookbacks is None
        assert ARMS[name].long_only is False


def test_arm_tables_are_read_only_and_their_records_frozen() -> None:
    with pytest.raises(TypeError):
        ARMS["v4_extra"] = ARMS["v4_main"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        ARMS["v4_main"].long_only = True  # type: ignore[misc]
    lookbacks = ARMS["v4_main"].lookbacks
    assert lookbacks is not None
    with pytest.raises(FrozenInstanceError):
        lookbacks.fast = 1  # type: ignore[misc]
    assert isinstance(ARMS["v4_main"], ArmSpec)


def test_cells_are_two_capitals_by_two_cost_levels() -> None:
    cells = all_cells()
    expected = [
        f"{arm}-{capital}-{multiple}x"
        for arm in ARM_NAMES
        for capital in (1000, 10000)
        for multiple in (1, 2)
    ]
    assert len(expected) == 48
    assert [cell.cell_id for cell in cells] == expected
    assert len(set(expected)) == 48
    assert cells[0].cell_id == "v4_main-1000-1x"
    assert cells[3].cell_id == "v4_main-10000-2x"
    assert cells[-1].cell_id == "v3_as_built-10000-2x"
    assert CellSpec("v4_main", 10000, 1).cell_id == "v4_main-10000-1x"
    assert CellSpec("hold_universe", 1000, 2) in cells


def test_cell_spec_is_frozen() -> None:
    cell = CellSpec("v4_main", 10000, 1)
    with pytest.raises(FrozenInstanceError):
        cell.capital = 1000  # type: ignore[misc]


@pytest.mark.parametrize(
    ("arm", "capital", "multiple"),
    [
        ("v5_main", 10000, 1),  # not an arm of the run
        ("", 10000, 1),
        ("V4_MAIN", 10000, 1),
        ("v4_main", 5000, 1),
        ("v4_main", 0, 1),
        ("v4_main", 10000, 0),
        ("v4_main", 10000, 3),
        ("v4_main", 10000.0, 1),
        ("v4_main", 10000, 1.0),
        ("v4_main", True, 1),  # a bool is an int to isinstance, and True == 1
        ("v4_main", 10000, True),
        (None, 10000, 1),
        (["v4_main"], 10000, 1),  # unhashable: still a ValueError, not a TypeError
    ],
)
def test_cell_spec_refuses_an_unknown_arm_capital_or_cost_multiple(
    arm: Any, capital: Any, multiple: Any
) -> None:
    with pytest.raises(ValueError):
        CellSpec(arm, capital, multiple)


def test_costs_are_the_v31_profile_and_double() -> None:
    normal = CellSpec("v4_main", 10000, 1)
    assert normal.costs("spot") == Costs(Decimal("0.001"), Decimal("0.0005"), Decimal("0.004"))
    assert normal.costs("futures") == Costs(Decimal("0.0005"), Decimal("0.0005"), Decimal("0.0025"))
    doubled = CellSpec("v4_main", 10000, 2)
    assert doubled.costs("spot") == Costs(Decimal("0.002"), Decimal("0.001"), Decimal("0.008"))
    assert doubled.costs("futures") == Costs(Decimal("0.001"), Decimal("0.001"), Decimal("0.005"))
    # The arm and the capital do not change the rates.
    assert CellSpec("hold_btc", 1000, 1).costs("spot") == normal.costs("spot")


def test_costs_refuse_an_unknown_venue() -> None:
    with pytest.raises(ValueError):
        CellSpec("v4_main", 10000, 1).costs("margin")  # type: ignore[arg-type]


def test_the_fixed_sizing_constants_are_the_plans() -> None:
    expected: dict[str, int | Decimal] = {
        "SIGMA_RETURNS": 60,
        "COVARIANCE_DAYS": 60,
        "MIN_COMMON_DAYS": 40,
        "COIN_CAP": Decimal("0.30"),
        "TOTAL_CAP": Decimal("2.7"),
        "BAND_RELATIVE": Decimal("0.25"),
        "BAND_ABSOLUTE": Decimal("0.01"),
        "CEILING": Decimal(3),
        "CEILING_TARGET": Decimal("2.7"),
        "CUSHION_FLOOR": 3,
        "CUSHION_TARGET": 4,
        "MAINTENANCE_RATE": Decimal("0.01"),
        "INITIAL_MARGIN_DIVISOR": 3,
        "COST_RESERVE": Decimal("0.02"),
        "DEAD_MARKET_HOURS": 168,
        "DEAD_MARKET_PENALTY": Decimal("0.10"),
        "HOLD_INVESTED": Decimal("0.99"),
    }
    for name, value in expected.items():
        actual = getattr(arms, name)
        assert actual == value, name
        assert type(actual) is type(value), name  # an int is not a Decimal here


def test_the_decimal_context_is_sixty_digits_half_even() -> None:
    assert CONTEXT.prec == 60
    assert CONTEXT.rounding == ROUND_HALF_EVEN


def test_to_fraction_is_exact() -> None:
    assert to_fraction(Decimal("0.1")) == Fraction(1, 10)  # not the float 0.1
    assert to_fraction(Decimal("-0.25")) == Fraction(-1, 4)
    assert to_fraction(Decimal("1E+3")) == Fraction(1000)
    assert to_fraction(Decimal("0")) == Fraction(0)
    digits = Decimal("1." + "0" * 70 + "1")  # more digits than the context keeps
    assert to_fraction(digits) == 1 + Fraction(1, 10**71)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 0.5, 1])
def test_to_fraction_refuses_a_non_finite_or_non_decimal_value(bad: Any) -> None:
    with pytest.raises(ValueError):
        to_fraction(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(1, 2), Decimal("0.5")),
        (Fraction(3, 8), Decimal("0.375")),
        (Fraction(1, 20), Decimal("0.05")),
        (Fraction(7, 25), Decimal("0.28")),
        (Fraction(-7, 4), Decimal("-1.75")),
        (Fraction(1, 1000), Decimal("0.001")),
        (Fraction(50), Decimal("50")),
        (Fraction(0), Decimal("0")),
    ],
)
def test_to_decimal_is_exact_for_a_terminating_fraction(value: Fraction, expected: Decimal) -> None:
    result = to_decimal(value)
    assert result == expected
    assert str(result) == str(expected)  # the shortest form, no trailing zeros


def test_to_decimal_keeps_every_digit_beyond_the_context() -> None:
    value = Fraction(1, 2**100)  # 100 significant decimal digits, the context keeps 60
    result = to_decimal(value)
    assert to_fraction(result) == value
    assert len(result.as_tuple().digits) > CONTEXT.prec
    big = Fraction(3**50, 5**80)
    assert to_fraction(to_decimal(big)) == big


def test_to_decimal_round_trips_a_decimal() -> None:
    for text in ("0.0005", "123456789.123456789", "-0.000000001", "1E+5", "7"):
        original = Decimal(text)
        assert to_decimal(to_fraction(original)) == original


@pytest.mark.parametrize(
    "value",
    [Fraction(1, 3), Fraction(1, 6), Fraction(1, 7), Fraction(2, 15), Fraction(-5, 12)],
)
def test_to_decimal_refuses_a_non_terminating_fraction(value: Fraction) -> None:
    with pytest.raises(ValueError, match="terminat"):
        to_decimal(value)


@pytest.mark.parametrize("bad", [0.5, 1, Decimal("0.5"), "1/2", None])
def test_to_decimal_refuses_a_non_fraction(bad: Any) -> None:
    with pytest.raises(ValueError):
        to_decimal(bad)
