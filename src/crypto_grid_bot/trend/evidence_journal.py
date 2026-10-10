"""Local immutable attempt metadata; not a historical dispatcher.

Single-writer ownership is required. File contents are fsynced before atomic
hard-link publication; filesystems without hard links fail rather than overwrite.
This handles process interruption, not every filesystem/power-loss scenario.
"""

import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

LIMIT = 4 * 1024 * 1024


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate journal key")
        result[key] = value
    return result


def _identity(run_id: str, state: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id) or run_id.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("invalid run identity")
    if state not in ("started", "finished"):
        raise ValueError("invalid journal state")


def _json_value(value: Any) -> Any:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    if type(value) in (list, tuple):
        return [_json_value(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise ValueError("unsupported or nonfinite journal value")


class EvidenceJournal:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _read(self, run_id: str, state: str) -> dict[str, Any]:
        _identity(run_id, state)
        with (self.directory / f"{run_id}.{state}.json").open("rb") as source:
            data = source.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("journal record exceeds metadata size limit")
        doc = json.loads(data, object_pairs_hook=_object)
        if (
            not isinstance(doc, dict)
            or set(doc) != {"schema", "run_id", "state", "payload"}
            or type(doc["schema"]) is not int
            or doc["schema"] != 1
            or doc["run_id"] != run_id
            or doc["state"] != state
            or type(doc["payload"]) is not dict
        ):
            raise ValueError("invalid journal record")
        _json_value(doc)
        return doc

    def record(self, run_id: str, state: str, payload: dict[str, Any]) -> None:
        _identity(run_id, state)
        if type(payload) is not dict:
            raise ValueError("journal payload must be an object")
        if state == "finished":
            if not (self.directory / f"{run_id}.started.json").exists():
                raise ValueError("finished record requires a start")
            self._read(run_id, "started")
        document = {"schema": 1, "run_id": run_id, "state": state, "payload": _json_value(payload)}
        data = (
            json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
        if len(data) > LIMIT:
            raise ValueError("journal record exceeds metadata size limit")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.directory, prefix=".journal-", delete=False
            ) as f:
                temporary = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # Atomic create-if-absent; a duplicate can never replace evidence.
            os.link(temporary, self.directory / f"{run_id}.{state}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def pending(self) -> tuple[str, ...]:
        starts = set()
        finishes = set()
        for path in self.directory.glob("*.json"):
            if path.name.endswith(".started.json"):
                run_id, state = path.name[:-13], "started"
                starts.add(run_id)
            elif path.name.endswith(".finished.json"):
                run_id, state = path.name[:-14], "finished"
                finishes.add(run_id)
            else:
                raise ValueError("unrecognized journal record")
            self._read(run_id, state)
        if not finishes <= starts:
            raise ValueError("finished record without start")
        return tuple(sorted(starts - finishes))
