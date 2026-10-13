"""The owner-approved size limits: every value pinned, and each one shown to bind.

Spec docs/superpowers/specs/2026-10-10-v3-1-design.md, Package D. The expected numbers
here are written from the spec, not read back from the constants, so changing any one
limit in ``risk.py`` fails this module. The behavioural cases use zero fees and slippage
unless they say otherwise, which keeps every bound an exact number a reader can check.
"""

import re
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path

import pytest
from test_combined_risk import intent, view

from crypto_grid_bot.combined import risk
from crypto_grid_bot.combined.risk import Exposure, PortfolioRisk

SYMBOLS = (
    "ETHUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "LTCUSDT",
    "AVAXUSDT",
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ASSET_RISK_LIMIT", Fraction("0.005")),  # initial risk per asset 0.5% of equity
        ("AGGREGATE_RISK_LIMIT", Fraction("0.03")),  # open + reserved stop risk <= 3%
        ("ASSET_NOTIONAL_LIMIT", Fraction("0.2")),  # asset notional <= 20% of equity
        ("GROSS_LIMIT", Fraction("1.6")),  # portfolio gross <= 1.6x
        ("GROUP_GROSS_LIMIT", Fraction("0.8")),  # correlated group gross <= 80% of equity
    ],
)
def test_each_owner_approved_limit_keeps_its_exact_spec_value(name, expected):
    value = getattr(risk, name)
    assert type(value) is Fraction
    assert value == expected


def free(**changes):
    """A spot candidate priced 100 with its stop at 99 (a unit risks 1) and no costs."""
    base = {"stop": D(99), "fee_rate": D(0), "slippage_rate": D(0), "min_notional": D(0)}
    return intent(**base | changes)


def held(symbol, notional, stop_risk, group="unknown"):
    return Exposure(symbol, "spot_trend", D(notional), D(stop_risk), group)


def test_asset_risk_limit_sizes_one_asset_to_half_a_percent_of_equity():
    # Equity 10000: 0.5% is 50, and a unit risks 50 with the stop at 50.
    answer = PortfolioRisk().reserve(free(stop=D(50)), view())
    assert answer.accepted
    assert (answer.quantity, answer.risk) == (D(1), D(50))
    beyond = PortfolioRisk().reserve(free(stop=D(50), requested_quantity=D("1.001")), view())
    assert (beyond.quantity, beyond.risk) == (D(1), D(50))
    # The extended-entry multiplier scales the same limit.
    half = PortfolioRisk().reserve(free(stop=D(50), risk_multiplier=D("0.5")), view())
    assert (half.quantity, half.risk) == (D("0.5"), D(25))


def test_asset_notional_limit_sizes_one_asset_to_a_fifth_of_equity():
    answer = PortfolioRisk().reserve(free(), view())
    assert answer.accepted
    assert (answer.quantity, answer.notional) == (D(20), D(2000))
    beyond = PortfolioRisk().reserve(free(requested_quantity=D("20.001")), view())
    assert (beyond.quantity, beyond.notional) == (D(20), D(2000))


def test_aggregate_risk_limit_refuses_at_three_percent_and_admits_the_headroom_below_it():
    # Six assets at 0.5% each are exactly 3% of 10000.
    full = tuple(held(symbol, 100, 50) for symbol in SYMBOLS[:6])
    refused = PortfolioRisk().reserve(free(), view(exposures=full))
    assert (refused.accepted, refused.reason) == (False, "portfolio_capacity")
    # One unit of stop risk below the limit leaves room for exactly one unit.
    inside = (replace(full[0], stop_risk=D(49)), *full[1:])
    answer = PortfolioRisk().reserve(free(), view(exposures=inside))
    assert (answer.quantity, answer.risk) == (D(1), D(1))


def test_gross_limit_refuses_at_one_point_six_times_equity_and_admits_the_headroom_below_it():
    # Eight assets at 20% each are 160% of equity; separate groups keep the group cap quiet.
    groups = tuple((symbol, symbol) for symbol in SYMBOLS)
    full = tuple(held(symbol, 2000, 0, symbol) for symbol in SYMBOLS)
    refused = PortfolioRisk().reserve(free(), view(exposures=full, correlation_groups=groups))
    assert (refused.accepted, refused.reason) == (False, "portfolio_capacity")
    inside = (replace(full[0], notional=D(1900)), *full[1:])
    answer = PortfolioRisk().reserve(free(), view(exposures=inside, correlation_groups=groups))
    assert (answer.quantity, answer.notional) == (D(1), D(100))


def test_group_gross_limit_refuses_at_eighty_percent_and_admits_the_headroom_below_it():
    # Four assets at 20% each are 80% of equity, all in the candidate's group.
    members = SYMBOLS[:4]
    groups = tuple((symbol, "crowd") for symbol in (*members, "BTCUSDT"))
    full = tuple(held(symbol, 2000, 0, "crowd") for symbol in members)
    candidate = free(correlation_group="crowd")
    refused = PortfolioRisk().reserve(candidate, view(exposures=full, correlation_groups=groups))
    assert (refused.accepted, refused.reason) == (False, "portfolio_capacity")
    inside = (replace(full[0], notional=D(1900)), *full[1:])
    answer = PortfolioRisk().reserve(candidate, view(exposures=inside, correlation_groups=groups))
    assert (answer.quantity, answer.notional) == (D(1), D(100))


def other_group(notional):
    """Five assets in a group the candidate is not in: ``notional`` each."""
    members = SYMBOLS[:5]
    groups = tuple((symbol, "other") for symbol in members)
    return view(
        exposures=tuple(held(symbol, notional, 1, "other") for symbol in members),
        correlation_groups=groups,
    )


# The candidate's own entry costs shrink equity, so every other holding's limit moves with
# them. A holding sitting exactly on a limit leaves no room for any new cost; one a hundredth
# inside it does. Default fees and slippage are on here.
HELD_LIMITS = {
    "asset_risk": lambda inside: view(exposures=(held("ETHUSDT", 100, "49.5" if inside else 50),)),
    "asset_notional": lambda inside: view(
        exposures=(held("ETHUSDT", 1980 if inside else 2000, 1),)
    ),
    "group_gross": lambda inside: other_group(1584 if inside else 1600),
}


@pytest.mark.parametrize("kind", sorted(HELD_LIMITS))
def test_holdings_on_a_limit_refuse_new_costs_and_holdings_just_inside_it_admit(kind):
    on_limit = PortfolioRisk().reserve(intent(), HELD_LIMITS[kind](False))
    assert (on_limit.accepted, on_limit.reason) == (False, "portfolio_capacity")
    assert PortfolioRisk().reserve(intent(), HELD_LIMITS[kind](True)).accepted


# Each limit as (numerator, denominator, decimal text): the spellings a copy would take.
LIMIT_FORMS = {
    "ASSET_RISK_LIMIT": (1, 200, "0.005"),
    "AGGREGATE_RISK_LIMIT": (3, 100, "0.03"),
    "ASSET_NOTIONAL_LIMIT": (1, 5, "0.2"),
    "GROSS_LIMIT": (8, 5, "1.6"),
    "GROUP_GROSS_LIMIT": (4, 5, "0.8"),
}
DEFINITIONS = re.compile(rf"^(?:{'|'.join(LIMIT_FORMS)}) = .*$", re.MULTILINE)


def bare_limit_literals(text):
    """Every spelling of an owner limit as a bare number: ``Fraction(1, 200)``,
    ``Decimal("0.005")`` or a division such as ``/ 200``."""
    found = []
    for name, (numerator, denominator, decimal) in LIMIT_FORMS.items():
        number = rf"0?{re.escape(decimal.removeprefix('0'))}" if decimal[0] == "0" else decimal
        patterns = [
            rf"Fraction\(\s*{numerator}\s*,\s*{denominator}\s*\)",
            rf"(?:Fraction|Decimal|D)\(\s*[\"']{number}[\"']\s*\)",
        ]
        if numerator == 1:
            patterns.append(rf"/\s*{denominator}(?![.\w])")
        found += [(name, m.group()) for pattern in patterns for m in re.finditer(pattern, text)]
    return found


@pytest.mark.parametrize("module", ["engine", "risk"])
def test_no_module_repeats_an_owner_limit_as_a_bare_number(module):
    # The engine's cut-backs once carried their own copies of these numbers. They import
    # the constants now; a copy that comes back would drift from the admission limits.
    source = (Path(risk.__file__).parent / f"{module}.py").read_text(encoding="utf-8")
    assert bare_limit_literals(DEFINITIONS.sub("", source)) == []


def test_the_scan_recognises_each_spelling_of_a_limit():
    assert bare_limit_literals("x = Fraction( 1,200 )") == [
        ("ASSET_RISK_LIMIT", "Fraction( 1,200 )")
    ]
    assert bare_limit_literals('Decimal(".03")') == [("AGGREGATE_RISK_LIMIT", 'Decimal(".03")')]
    assert bare_limit_literals("capital / 5") == [("ASSET_NOTIONAL_LIMIT", "/ 5")]
    assert bare_limit_literals("v * Fraction(8, 5)") == [("GROSS_LIMIT", "Fraction(8, 5)")]
    assert bare_limit_literals("capital * Fraction(4, 5)") == [
        ("GROUP_GROSS_LIMIT", "Fraction(4, 5)")
    ]
    assert bare_limit_literals('D("0.25") / 50 + Fraction(9, 10) + Fraction(3, 10)') == []
