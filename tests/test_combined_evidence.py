"""Evidence preserves causal decisions and cannot silently rewrite an event."""

import json
from dataclasses import replace

import pytest

from crypto_grid_bot.combined.evidence import DecisionEvent, Evidence


def event(phase="detected", *, event_id="e1", time=1, accepted=True):
    return DecisionEvent(
        event_id,
        "opportunity-1",
        time,
        "BTCUSDT",
        phase,
        accepted,
        (),
        (("source", "sha256:fixture"),),
    )


def test_duplicate_is_idempotent_but_conflicting_reuse_is_error():
    journal = Evidence()
    e = event()
    journal.record(e)
    journal.record(e)
    assert len(journal.events) == 1
    with pytest.raises(ValueError, match="conflicting"):
        journal.record(replace(e, timestamp_ms=2))
    assert journal.events == (e,)


def test_funnel_cannot_skip_risk_or_size_gates():
    journal = Evidence()
    journal.record(event())
    with pytest.raises(ValueError, match="phase"):
        journal.record(event("filled", event_id="e2"))
    assert len(journal.events) == 1


def test_rejected_qualification_retains_independent_reasons_and_is_terminal():
    journal = Evidence()
    journal.record(event())
    journal.record(
        replace(
            event("qualified", event_id="e2"),
            accepted=False,
            reasons=("daily_conflict", "funding_unavailable"),
        )
    )
    with pytest.raises(ValueError, match="terminal"):
        journal.record(event("risk_approved", event_id="e3"))
    decoded = [json.loads(row) for row in journal.json_lines().splitlines()]
    assert decoded[-1]["event"]["reasons"] == ["daily_conflict", "funding_unavailable"]
    assert decoded[-1]["previous_hash"] == decoded[0]["hash"]
    assert decoded[-1]["event"]["schema"] == "combined-v1"


def test_successful_funnel_and_partial_fill_records():
    journal = Evidence()
    phases = [
        "detected",
        "qualified",
        "risk_approved",
        "executable_size",
        "submitted",
        "filled",
        "filled",
    ]
    for i, phase in enumerate(phases):
        journal.record(event(phase, event_id=f"e{i}", time=i))
    assert len(journal.events) == 7
    assert journal.json_lines() == journal.json_lines()


def test_event_cannot_move_backwards_in_time_or_change_symbol():
    journal = Evidence()
    journal.record(event(time=5))
    with pytest.raises(ValueError, match="time"):
        journal.record(event("qualified", event_id="e2", time=4))
    with pytest.raises(ValueError, match="symbol"):
        journal.record(replace(event("qualified", event_id="e2", time=5), symbol="ETHUSDT"))


def test_refusal_requires_reason_and_metadata_has_unique_keys():
    with pytest.raises(ValueError):
        event(accepted=False)
    with pytest.raises(ValueError):
        replace(event(), details=(("x", "1"), ("x", "2")))
