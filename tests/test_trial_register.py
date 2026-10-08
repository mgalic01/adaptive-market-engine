"""Reject corrupt or rewritten experiment history rather than silently losing trials."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from trial_register import load_events, validate_append  # noqa: E402


def record(event_id="old"):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "trial_id": "v0",
        "event_type": "retrospective",
        "recorded_at": "2026-10-08T17:00:00Z",
        "agent": "Codex Desktop",
        "family": "grid",
        "parent_trial_id": None,
        "sources": ["docs/backtests/source.md"],
        "payload": {
            "preregistered": False,
            "scope": "recorded trials only",
            "missing_fields": ["exact trial count"],
            "outcome": "see source",
        },
    }


def encode(*events):
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def test_valid_history_and_append(tmp_path):
    old = encode(record())
    new = old + encode(record("next"))
    path = tmp_path / "register.jsonl"
    path.write_bytes(new)
    assert [e["event_id"] for e in load_events(path)] == ["old", "next"]
    validate_append(old, new)


@pytest.mark.parametrize(
    "data",
    [
        b"{}\n",
        b"\n",
        b"{",
        b"[]\n",
        b'{"event_id":"a","event_id":"b"}\n',
        encode(record()).replace(b"false", b"NaN"),
        encode(record()).replace(b"false", b"1e999"),
        encode(record()) + b"\n",
        encode(record()).rstrip(b"\n"),
    ],
)
def test_malformed_history_is_rejected(tmp_path, data):
    path = tmp_path / "register.jsonl"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="line"):
        load_events(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("recorded_at", "2026-10-08"),
        ("event_type", "unknown"),
        ("sources", []),
        ("event_id", " "),
        ("payload", {}),
    ],
)
def test_invalid_fields(tmp_path, field, value):
    event = record()
    event[field] = value
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(event))
    with pytest.raises(ValueError):
        load_events(path)


def test_retrospective_cannot_claim_preregistration(tmp_path):
    event = record()
    event["payload"]["preregistered"] = True
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(event))
    with pytest.raises(ValueError):
        load_events(path)


def test_duplicate_ids_rejected(tmp_path):
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(record(), record()))
    with pytest.raises(ValueError, match="line 2"):
        load_events(path)


@pytest.mark.parametrize(
    "replacement", [b"", encode(record("changed")), encode(record("next"), record())]
)
def test_history_cannot_be_deleted_reordered_or_rewritten(replacement):
    with pytest.raises(ValueError):
        validate_append(encode(record()), replacement)
