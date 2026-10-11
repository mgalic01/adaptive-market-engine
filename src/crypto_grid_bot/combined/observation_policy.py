"""Approved settlement sampling identities, not authentication or a replay engine.

Adapters attest the economic boundary and retain all intermediate equity marks.
This validator checks identity/order only; adapter conformance and its exact code
pin require external review. No timestamps are synthesized or moved here.
"""

from dataclasses import dataclass

POLICY_ID = "v3.1-owner-2026-10-11-settlement-v1"


@dataclass(frozen=True, slots=True)
class Boundary:
    timestamp_ms: int
    role: str
    observation_ids: tuple[str, ...]
    selected_equity_id: str
    capital_id: str
    source_refs: tuple[str, ...]
    interval_start_ms: int | None = None
    interval_end_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    policy_id: str
    adapter_pin: str
    boundaries: tuple[Boundary, ...]
    scenario: str | None = None


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_boundaries(
    evidence: PolicyEvidence, observations: tuple[tuple[int, str | None], ...]
) -> dict[int, Boundary]:
    """Require exact retained ordering at each declared settlement boundary.

    Opening is before costs; later daily/utilization samples follow all settlements.
    Unlisted timestamps remain observations but cannot resolve ambiguous sampling.
    Terminal is explicitly declared, never inferred from a native adapter timestamp.
    """
    if (
        not isinstance(evidence, PolicyEvidence)
        or evidence.policy_id != POLICY_ID
        or not _text(evidence.adapter_pin)
        or not isinstance(evidence.boundaries, tuple)
        or len(evidence.boundaries) < 2
        or not observations
    ):
        raise ValueError("approved policy and adapter identity required")
    groups: dict[int, list[str | None]] = {}
    seen: set[str] = set()
    previous = -1
    for timestamp, identity in observations:
        if (
            type(timestamp) is not int
            or timestamp < previous
            or not isinstance(identity, str)
            or not identity.strip()
        ):
            raise ValueError("ordered identified observations required")
        if identity in seen:
            raise ValueError("unique observation identities required")
        seen.add(identity)
        groups.setdefault(timestamp, []).append(identity)
        previous = timestamp
    result: dict[int, Boundary] = {}
    previous = -1
    for index, boundary in enumerate(evidence.boundaries):
        if not isinstance(boundary, Boundary):
            raise ValueError("boundary record required")
        role = (
            "opening"
            if index == 0
            else "terminal"
            if index == len(evidence.boundaries) - 1
            else "settled"
        )
        if (
            type(boundary.timestamp_ms) is not int
            or boundary.timestamp_ms <= previous
            or boundary.role != role
            or type(boundary.interval_start_ms) is not int
            or type(boundary.interval_end_ms) is not int
            or not 0 <= boundary.interval_start_ms < boundary.interval_end_ms < 1_735_689_600_000
            or boundary.interval_start_ms % 3_600_000
            or boundary.interval_end_ms - boundary.interval_start_ms != 3_600_000
            or boundary.timestamp_ms
            != (boundary.interval_end_ms if role == "terminal" else boundary.interval_start_ms)
            or not isinstance(boundary.observation_ids, tuple)
            or not boundary.observation_ids
            or tuple(groups.get(boundary.timestamp_ms, ())) != boundary.observation_ids
            or not _text(boundary.capital_id)
            or not isinstance(boundary.source_refs, tuple)
            or not boundary.source_refs
            or not all(_text(ref) for ref in boundary.source_refs)
        ):
            raise ValueError("complete ordered boundary evidence required")
        selected = boundary.observation_ids[0 if role == "opening" else -1]
        if boundary.selected_equity_id != selected:
            raise ValueError("boundary must select approved settlement state")
        result[boundary.timestamp_ms] = boundary
        previous = boundary.timestamp_ms
    if (
        evidence.boundaries[0].timestamp_ms != observations[0][0]
        or evidence.boundaries[-1].timestamp_ms != observations[-1][0]
    ):
        raise ValueError("opening and terminal must bound retained observations")
    return result
