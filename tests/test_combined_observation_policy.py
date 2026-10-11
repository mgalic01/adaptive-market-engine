"""Synthetic settlement identities; no historical strategy execution."""

from dataclasses import replace

import pytest

from crypto_grid_bot.combined.observation_policy import (
    POLICY_ID,
    Boundary,
    PolicyEvidence,
    validate_boundaries,
)


def evidence():
    return PolicyEvidence(
        POLICY_ID,
        "adapter-sha256",
        (
            Boundary(0, "opening", ("initial",), "initial", "cash", ("source",)),
            Boundary(10, "settled", ("funding", "exit", "entry"), "entry", "held", ("source",)),
            Boundary(20, "terminal", ("close", "flat"), "flat", "end", ("source",)),
        ),
    )


def observations():
    return (
        (0, "initial"),
        (10, "funding"),
        (10, "exit"),
        (10, "entry"),
        (20, "close"),
        (20, "flat"),
    )


def test_boundary_policy_requires_all_ordered_marks_and_selects_final_settlement():
    result = validate_boundaries(evidence(), observations())
    assert result[10].selected_equity_id == "entry"
    assert result[0].role == "opening"
    assert result[20].role == "terminal"


@pytest.mark.parametrize(
    "change",
    [
        {"selected_equity_id": "funding"},
        {"observation_ids": ("exit", "funding", "entry")},
        {"observation_ids": ("funding", "entry")},
        {"source_refs": ()},
        {"capital_id": ""},
        {"role": "terminal"},
    ],
)
def test_incomplete_or_favorable_boundary_is_rejected(change):
    original = evidence()
    bad = replace(original.boundaries[1], **change)
    with pytest.raises(ValueError):
        validate_boundaries(
            replace(original, boundaries=(original.boundaries[0], bad, original.boundaries[2])),
            observations(),
        )


def test_unknown_policy_and_missing_adapter_are_rejected():
    for value in (replace(evidence(), policy_id="unknown"), replace(evidence(), adapter_pin="")):
        with pytest.raises(ValueError):
            validate_boundaries(value, observations())


def test_uncovered_same_time_observation_cannot_be_dropped():
    with pytest.raises(ValueError):
        validate_boundaries(evidence(), observations() + ((20, "late"),))


def policy_report(*, omit_interior=False, terminal_role="terminal", policy_id=POLICY_ID):
    from decimal import Decimal as D

    from crypto_grid_bot.combined.report import (
        CapitalObservation,
        Contribution,
        EquityPoint,
        UtilizationInterval,
        analyze,
    )

    day = 86_400_000
    points = tuple(
        EquityPoint(t, D(v), name, ("source",))
        for t, v, name in (
            (0, 100, "initial"),
            (0, 99, "cost"),
            (day, 110, "funding"),
            (day, 90, "exit"),
            (day, 107, "entry"),
            (2 * day, 108, "close"),
            (2 * day, 106, "flat"),
        )
    )
    policy = PolicyEvidence(
        POLICY_ID,
        "adapter-pin",
        (
            Boundary(0, "opening", ("initial", "cost"), "initial", "cash", ("source",)),
            Boundary(day, "settled", ("funding", "exit", "entry"), "entry", "held", ("source",)),
            Boundary(2 * day, "terminal", ("close", "flat"), "flat", "end", ("source",)),
        ),
    )
    capitals = tuple(
        CapitalObservation(p.timestamp_ms, p.equity, D(0), D(0), name, role, p.id, ("source",))
        for p, name, role in (
            (points[1], "cash", "opening"),
            (points[4], "held", "settled"),
            (points[-1], "end", "terminal"),
        )
    )
    intervals = tuple(
        UtilizationInterval(t, t + day, D(0), D(0), p.equity, name, ("source",), cap)
        for t, p, name, cap in ((0, points[1], "u0", "cash"), (day, points[4], "u1", "held"))
    )
    contribution = Contribution(
        "trade",
        "spot_trend",
        "BTCUSDT",
        "long",
        "up",
        D(7),
        D(1),
        D(0),
        D(100),
        "close",
        0,
        "closed",
        2 * day,
        source_refs=("source",),
    )
    daily = (points[0], points[4], points[-1])
    if omit_interior:
        policy = replace(policy, boundaries=(policy.boundaries[0], policy.boundaries[-1]))
        points = tuple(point for point in points if point.id not in ("funding", "exit"))
    policy = replace(policy, policy_id=policy_id)
    capitals = (*capitals[:-1], replace(capitals[-1], phase_id=terminal_role))
    report = analyze(
        D(100),
        points,
        (contribution,),
        (),
        (),
        ("source",),
        metrics_start_ms=0,
        daily_samples=daily,
        utilization=intervals,
        capital_observations=capitals,
        policy_evidence=policy,
    )
    assert report.policy_evidence == policy
    return report


def test_report_uses_approved_settlement_and_keeps_intermediate_drawdown():
    report = policy_report()
    assert report.complete, report.issues
    assert report.max_drawdown is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"omit_interior": True},
        {"terminal_role": "opening"},
        {"policy_id": "invalid"},
    ],
)
def test_invalid_sampling_is_incomplete_but_does_not_erase_drawdown(kwargs):
    report = policy_report(**kwargs)
    assert not report.complete
    assert report.max_drawdown is not None
    if not kwargs.get("omit_interior"):
        assert report.max_drawdown > 0.18
