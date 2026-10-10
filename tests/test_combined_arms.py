"""The registered component menu maps to one fixed set of switches."""

from dataclasses import fields

import pytest

from crypto_grid_bot.combined.arms import arm_settings


def test_component_controls_and_baselines_are_not_silently_combined():
    spot = arm_settings("spot_trend")
    assert spot.routing.spot_trend and not spot.routing.futures_trend
    assert not spot.routing.spot_grid
    future = arm_settings("futures_trend_long_only")
    assert future.routing.futures_trend and future.routing.futures_long_only
    assert not future.routing.spot_trend and not future.routing.spot_grid
    grid = arm_settings("spot_grid")
    assert grid.routing.spot_grid and not grid.routing.spot_trend
    with pytest.raises(ValueError, match="baseline adapter"):
        arm_settings("unchanged_v3_selector")
    with pytest.raises(ValueError, match="unknown"):
        arm_settings("combined_without_accounting")


@pytest.mark.parametrize(
    "name,field",
    [
        ("combined_without_continuation", "continuation"),
        ("combined_without_full_short_qualification", "short_qualification"),
    ],
)
def test_routing_ablation_changes_exactly_one_switch(name, field):
    base, changed = arm_settings("combined"), arm_settings(name)
    differences = [
        f.name
        for f in fields(base.routing)
        if getattr(base.routing, f.name) != getattr(changed.routing, f.name)
    ]
    assert differences == [field]
    assert not getattr(changed.routing, field)


@pytest.mark.parametrize(
    "name,field",
    [
        ("combined_without_discretionary_trailing", "trailing"),
        ("combined_without_funding_admission", "funding_admission"),
        ("combined_without_recovery", "automatic_recovery"),
    ],
)
def test_protection_ablation_never_disables_mandatory_safeguards(name, field):
    base, changed = arm_settings("combined"), arm_settings(name)
    assert changed.routing == base.routing
    assert not getattr(changed, field)
    assert {f.name for f in fields(changed)} == {
        "routing",
        "trailing",
        "funding_admission",
        "automatic_recovery",
    }
