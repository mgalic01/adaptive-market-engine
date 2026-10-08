"""Offline trial-history validation. No dispatch or network operations.

Initial schema slice: retrospective records only. Candidate/completion/result event
support is deliberately rejected until its validation and readiness gates exist.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite number")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_events(events: list[dict[str, Any]]) -> None:
    """Validate retrospective records; errors identify the offending line."""
    seen: set[str] = set()
    fields = {
        "schema_version",
        "event_id",
        "trial_id",
        "event_type",
        "recorded_at",
        "agent",
        "family",
        "parent_trial_id",
        "sources",
        "payload",
    }
    for line, event in enumerate(events, 1):
        try:
            _finite(event)
            if not isinstance(event, dict) or set(event) != fields:
                raise ValueError("expected exactly the schema's common fields")
            if type(event["schema_version"]) is not int or event["schema_version"] != 1:
                raise ValueError("unsupported schema version")
            for field in ("event_id", "trial_id", "agent", "family", "recorded_at"):
                if not _text(event[field]):
                    raise ValueError(f"invalid {field}")
            if event["event_id"] in seen:
                raise ValueError("duplicate event ID")
            seen.add(event["event_id"])
            stamp = event["recorded_at"]
            if not stamp.endswith("Z") or "T" not in stamp:
                raise ValueError("recorded_at must be a UTC timestamp ending in Z")
            datetime.fromisoformat(stamp)
            parent = event["parent_trial_id"]
            if parent is not None and (not _text(parent) or parent == event["trial_id"]):
                raise ValueError("invalid parent trial ID")
            sources = event["sources"]
            if not isinstance(sources, list) or not sources or not all(map(_text, sources)):
                raise ValueError("nonempty source references required")
            if event["event_type"] != "retrospective":
                raise ValueError("event type not implemented; cannot authorize dispatch")
            payload = event["payload"]
            if not isinstance(payload, dict) or set(payload) != {
                "preregistered",
                "scope",
                "missing_fields",
                "outcome",
            }:
                raise ValueError("invalid retrospective payload")
            if payload["preregistered"] is not False:
                raise ValueError("retrospective records are not preregistered")
            if not _text(payload["scope"]) or not _text(payload["outcome"]):
                raise ValueError("scope and outcome references required")
            missing = payload["missing_fields"]
            if not isinstance(missing, list) or not all(map(_text, missing)):
                raise ValueError("missing_fields must explicitly list historical unknowns")
        except ValueError as exc:
            raise ValueError(f"line {line}: {exc}") from exc


def _parse(data: bytes) -> list[dict[str, Any]]:
    if data and not data.endswith(b"\n"):
        raise ValueError("line at EOF: record must end in newline")
    events: list[dict[str, Any]] = []
    for line, raw in enumerate(data.splitlines(), 1):
        try:
            event = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
            _finite(event)
            events.append(event)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"line {line}: {exc}") from exc
    validate_events(events)
    return events


def load_events(path: Path) -> list[dict[str, Any]]:
    return _parse(path.read_bytes())


def validate_append(base: bytes, candidate: bytes) -> None:
    """Reject history edits, even equivalent JSON reformatted into different bytes."""
    _parse(base)
    _parse(candidate)
    if not candidate.startswith(base):
        raise ValueError("historical bytes must remain an unchanged prefix")
