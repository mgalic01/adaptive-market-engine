"""Exclusive offline evidence bundles; hashes prove integrity, not source authenticity.

No retry, execution, registration or network access. A failed write leaves its directory
and completed/partial files intact; absence of a valid final receipt means incomplete.
Retain the returned receipt digest separately to detect wholesale bundle replacement.
Filesystem permissions remain the caller's responsibility: this is not WORM storage or
protection against a hostile process concurrently replacing filesystem ancestors.

A bundle may also carry the versioned evidence records (assessment, intent/protection,
decision admission/refusal, lifecycle, recovery), one JSON line per record, each line
``{"record": ..., "schema": "combined-v1"}``: either all five files or none.
"""

import hashlib
import json
import os
import re
import types
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import cache
from pathlib import Path
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

from crypto_grid_bot.combined.evidence import DecisionEvent, DecisionRecord, Evidence, IntentRecord
from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.combined.report import Contribution, RecoveryEpisode

_SCHEMA = "combined-artifacts-v1"
_RECORD_SCHEMA = "combined-v1"
_ZERO = "0" * 64
_REQUIRED = {"decisions.jsonl", "metadata.json"}
# BundleRecords field -> file and record type, in field order.
_RECORD_FILES: dict[str, tuple[str, type]] = {
    "assessments": ("assessments.jsonl", Assessment),
    "intents": ("intents.jsonl", IntentRecord),
    "decisions": ("decision_records.jsonl", DecisionRecord),
    "lifecycles": ("lifecycles.jsonl", Contribution),
    "recoveries": ("recoveries.jsonl", RecoveryEpisode),
}
_ALLOWED = _REQUIRED | {"report.html"} | {name for name, _ in _RECORD_FILES.values()}
_EVENT_KEYS = {
    "event_id",
    "opportunity_id",
    "timestamp_ms",
    "symbol",
    "phase",
    "accepted",
    "reasons",
    "details",
    "source_refs",
    "schema",
}


@dataclass(frozen=True, slots=True)
class BundleReceipt:
    directory: Path
    receipt_sha256: str
    file_hashes: tuple[tuple[str, str], ...]
    event_count: int
    final_chain_hash: str


@dataclass(frozen=True, slots=True)
class BundleRecords:
    """Versioned evidence records beside the funnel journal; never a strategy input."""

    assessments: tuple[Assessment, ...] = ()
    intents: tuple[IntentRecord, ...] = ()
    decisions: tuple[DecisionRecord, ...] = ()
    lifecycles: tuple[Contribution, ...] = ()
    recoveries: tuple[RecoveryEpisode, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifiedBundle:
    receipt: BundleReceipt
    events: tuple[DecisionEvent, ...]
    metadata_json: str
    source_refs: tuple[str, ...]
    report_html: str | None
    records: BundleRecords | None = None


def _json_value(value: object, depth: int = 0) -> None:
    # Exact types prevent lossy float/Decimal coercion and arbitrary custom serialization.
    if depth > 50:
        raise ValueError("metadata nesting/cycle exceeds limit")
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            _json_value(item, depth + 1)
        return
    raise ValueError("only exact JSON dict/list/string/integer/boolean/null values allowed")


def _canonical(value: object) -> bytes:
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse(raw: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        _json_value(value)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON evidence") from exc
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return cast(dict[str, object], value)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("invalid SHA256 hash")
    return value


def _safe_path(path: Path) -> Path:
    # Reject links and Windows junctions anywhere, including links remaining inside root.
    if ".." in path.parts:
        raise ValueError("path traversal forbidden")
    absolute = Path(os.path.abspath(path))
    for part in (absolute, *absolute.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("symlink or junction evidence path forbidden")
    return absolute


def _name(invocation_id: str) -> None:
    if not isinstance(invocation_id, str) or not re.fullmatch(
        "[A-Za-z0-9][A-Za-z0-9_-]{0,127}", invocation_id
    ):
        raise ValueError("invocation ID must be a portable single path component")
    if invocation_id.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        "(COM|LPT)[0-9]", invocation_id.upper()
    ):
        raise ValueError("reserved invocation ID")


def _events(raw: bytes) -> tuple[tuple[DecisionEvent, ...], str]:
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete JSONL final line")
    evidence = Evidence()
    previous = _ZERO
    seen: set[str] = set()
    for line in raw.splitlines():
        row = _parse(line)
        if set(row) != {"event", "previous_hash", "hash"}:
            raise ValueError("invalid journal row schema")
        payload = {"event": row["event"], "previous_hash": row["previous_hash"]}
        if row["previous_hash"] != previous or _hash(row["hash"]) != _digest(_canonical(payload)):
            raise ValueError("decision hash chain mismatch")
        data = row["event"]
        if not isinstance(data, dict) or set(data) != _EVENT_KEYS:
            raise ValueError("invalid event schema")
        if any(
            type(data[key]) is not str
            for key in ("event_id", "opportunity_id", "symbol", "phase", "schema")
        ):
            raise ValueError("invalid event string type")
        for key in ("reasons", "source_refs"):
            if type(data[key]) is not list or any(type(v) is not str for v in data[key]):
                raise ValueError("invalid event string list")
        details = data["details"]
        if type(details) is not list or any(
            type(pair) is not list or len(pair) != 2 or any(type(v) is not str for v in pair)
            for pair in details
        ):
            raise ValueError("invalid event details")
        event = DecisionEvent(
            data["event_id"],
            data["opportunity_id"],
            data["timestamp_ms"],
            data["symbol"],
            data["phase"],
            data["accepted"],
            tuple(data["reasons"]),
            tuple(tuple(pair) for pair in details),
            tuple(data["source_refs"]),
            data["schema"],
        )
        if event.event_id in seen:
            raise ValueError("duplicate event ID in saved journal")
        seen.add(event.event_id)
        evidence.record(event)
        previous = cast(str, row["hash"])
    return evidence.events, previous


def _encode(value: object, hint: object) -> object:
    """A record value as exact JSON: Decimals as their string, enums as their value."""
    origin = get_origin(hint)
    if origin in (types.UnionType, Union):
        (kind,) = (arg for arg in get_args(hint) if arg is not type(None))
        return None if value is None else _encode(value, kind)
    if origin is tuple:
        args = get_args(hint)
        if not isinstance(value, tuple):
            raise ValueError("immutable record tuple required")
        kinds = (args[0],) * len(value) if args[1:] == (Ellipsis,) else args
        if len(kinds) != len(value):
            raise ValueError("record tuple length mismatch")
        return [_encode(item, kind) for item, kind in zip(value, kinds, strict=True)]
    if is_dataclass(hint):
        return _record_json(value)
    if isinstance(hint, type) and issubclass(hint, Enum):
        if not isinstance(value, hint):
            raise ValueError("record enum value required")
        return value.value
    if hint is Decimal:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("finite record Decimal required")
        return str(value)
    if type(value) is not hint or hint not in (str, int, bool):
        raise ValueError("exact record string, integer or Boolean required")
    return value


def _decode(value: object, hint: object) -> object:
    """The exact inverse of ``_encode``; anything else is refused."""
    origin = get_origin(hint)
    if origin in (types.UnionType, Union):
        (kind,) = (arg for arg in get_args(hint) if arg is not type(None))
        return None if value is None else _decode(value, kind)
    if origin is tuple:
        args = get_args(hint)
        if type(value) is not list:
            raise ValueError("record list required")
        kinds = (args[0],) * len(value) if args[1:] == (Ellipsis,) else args
        if len(kinds) != len(value):
            raise ValueError("record list length mismatch")
        return tuple(_decode(item, kind) for item, kind in zip(value, kinds, strict=True))
    if is_dataclass(hint) and isinstance(hint, type):
        return _record(value, hint)
    if isinstance(hint, type) and issubclass(hint, Enum):
        try:
            return hint(value)
        except ValueError as exc:
            raise ValueError("unknown record enum value") from exc
    if hint is Decimal:
        if type(value) is not str:
            raise ValueError("record Decimal must be string encoded")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid record Decimal") from exc
        if not number.is_finite() or str(number) != value:
            raise ValueError("finite canonical record Decimal required")
        return number
    if type(value) is not hint or hint not in (str, int, bool):
        raise ValueError("exact record string, integer or Boolean required")
    return value


@cache
def _schema(kind: type) -> tuple[tuple[str, object], ...]:
    """Each field of a record type with its type, in declaration order."""
    hints = get_type_hints(kind)
    return tuple((f.name, hints[f.name]) for f in fields(kind))


def _record_json(record: object) -> dict[str, object]:
    if not is_dataclass(record) or isinstance(record, type):
        raise ValueError("dataclass record required")
    return {name: _encode(getattr(record, name), hint) for name, hint in _schema(type(record))}


def _record(data: object, kind: type) -> object:
    schema = _schema(kind)
    if type(data) is not dict or data.keys() != {name for name, _ in schema}:
        raise ValueError("invalid record schema")
    return kind(**{name: _decode(data[name], hint) for name, hint in schema})


def _record_id(record: object) -> object:
    if isinstance(record, Assessment):
        return record.assessment_id
    if isinstance(record, IntentRecord | DecisionRecord):
        return record.record_id
    return getattr(record, "id", None)


def _check_records(records: BundleRecords, events: tuple[DecisionEvent, ...]) -> None:
    """Exact types, unique stable IDs, and references to saved assessments and funnels."""
    for field, (_, kind) in _RECORD_FILES.items():
        rows = getattr(records, field)
        if not isinstance(rows, tuple) or any(type(row) is not kind for row in rows):
            raise ValueError(f"immutable {field} records required")
        ids = [_record_id(row) for row in rows]
        if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"unique stable {field} record IDs required")
    assessments = {row.assessment_id for row in records.assessments}
    opportunities = {event.opportunity_id for event in events if event.phase == "detected"}
    linked: tuple[IntentRecord | DecisionRecord, ...] = (*records.intents, *records.decisions)
    for row in linked:
        if row.assessment_id not in assessments or row.opportunity_id not in opportunities:
            raise ValueError("record references an unsaved assessment or funnel")


def _record_lines(rows: tuple[object, ...]) -> bytes:
    return b"".join(
        _canonical({"record": _record_json(row), "schema": _RECORD_SCHEMA}) + b"\n" for row in rows
    )


def _read_records(raw: bytes, kind: type) -> tuple[object, ...]:
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete record JSONL final line")
    rows = []
    for line in raw.splitlines():
        row = _parse(line)
        if set(row) != {"record", "schema"} or row["schema"] != _RECORD_SCHEMA:
            raise ValueError("invalid record line schema")
        rows.append(_record(row["record"], kind))
    return tuple(rows)


def _sources(events: tuple[DecisionEvent, ...]) -> tuple[str, ...]:
    return tuple(sorted({ref for event in events for ref in event.source_refs}))


def _write(path: Path, raw: bytes) -> None:
    _safe_path(path)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_bundle(
    parent_dir: Path,
    invocation_id: str,
    evidence: Evidence,
    metadata: dict[str, object],
    report_html: str | None = None,
    *,
    records: BundleRecords | None = None,
) -> BundleReceipt:
    """Persist a new invocation once. Financial Decimal metadata must be string encoded.

    Inputs are validated before directory creation. File errors propagate with no cleanup,
    preserving partial evidence. The parent directory must already exist. Report HTML is
    retained byte-for-byte, never rendered, sanitized or treated as trusted executable code.
    ``records``, when given, are written as all five record files, empty ones included.
    """
    _name(invocation_id)
    if type(metadata) is not dict:
        raise ValueError("metadata must be a JSON object")
    metadata_raw = _canonical(metadata)
    if report_html is not None and type(report_html) is not str:
        raise ValueError("report HTML must be a string")
    journal = evidence.json_lines().encode("utf-8")
    events, final_hash = _events(journal)
    files = {"decisions.jsonl": journal, "metadata.json": metadata_raw}
    if report_html is not None:
        files["report.html"] = report_html.encode("utf-8")
    if records is not None:
        if not isinstance(records, BundleRecords):
            raise ValueError("bundle records required")
        _check_records(records, events)
        for field, (name, _) in _RECORD_FILES.items():
            files[name] = _record_lines(getattr(records, field))
    parent = _safe_path(parent_dir)
    if not parent.is_dir():
        raise ValueError("existing parent directory required")
    directory = parent / invocation_id
    directory.mkdir(exist_ok=False)
    hashes = {name: _digest(raw) for name, raw in files.items()}
    for name, raw in files.items():
        _write(directory / name, raw)
    manifest = {
        "schema": _SCHEMA,
        "invocation_id": invocation_id,
        "files": hashes,
        "event_count": len(events),
        "final_chain_hash": final_hash,
        "source_refs": list(_sources(events)),
    }
    raw_receipt = _canonical(manifest)
    _write(directory / "receipt.json", raw_receipt)
    return BundleReceipt(
        directory, _digest(raw_receipt), tuple(sorted(hashes.items())), len(events), final_hash
    )


def read_bundle(directory: Path, *, expected_receipt_sha256: str | None = None) -> VerifiedBundle:
    """Verify all saved hashes and event invariants; never follow source references.

    A valid receipt establishes structural completeness only, not experiment success,
    source authenticity, authorization, or physical write-once storage.
    """
    directory = _safe_path(directory)
    if not directory.is_dir():
        raise ValueError("bundle directory missing")
    entries = {path.name: _safe_path(path) for path in directory.iterdir()}
    if "receipt.json" not in entries or any(not path.is_file() for path in entries.values()):
        raise ValueError("incomplete bundle receipt or non-file entry")
    raw_receipt = entries["receipt.json"].read_bytes()
    receipt_hash = _digest(raw_receipt)
    if expected_receipt_sha256 is not None and receipt_hash != _hash(expected_receipt_sha256):
        raise ValueError("external receipt hash mismatch")
    manifest = _parse(raw_receipt)
    if (
        set(manifest)
        != {"schema", "invocation_id", "files", "event_count", "final_chain_hash", "source_refs"}
        or manifest["schema"] != _SCHEMA
    ):
        raise ValueError("invalid receipt schema")
    if manifest["invocation_id"] != directory.name:
        raise ValueError("invocation identity mismatch")
    _name(directory.name)
    hashes = manifest["files"]
    if not isinstance(hashes, dict) or not _REQUIRED <= hashes.keys() <= _ALLOWED:
        raise ValueError("invalid artifact file paths")
    saved = {name for name, _ in _RECORD_FILES.values()} & hashes.keys()
    if saved and len(saved) != len(_RECORD_FILES):
        raise ValueError("partial evidence record set")
    if set(entries) != set(hashes) | {"receipt.json"}:
        raise ValueError("missing or unexpected bundle file")
    files: dict[str, bytes] = {}
    for name, digest in hashes.items():
        raw = entries[name].read_bytes()
        if _digest(raw) != _hash(digest):
            raise ValueError("artifact hash mismatch")
        files[name] = raw
    events, final_hash = _events(files["decisions.jsonl"])
    if (
        type(manifest["event_count"]) is not int
        or manifest["event_count"] != len(events)
        or manifest["final_chain_hash"] != final_hash
    ):
        raise ValueError("event count or final chain hash mismatch")
    sources = _sources(events)
    if manifest["source_refs"] != list(sources):
        raise ValueError("source reference inventory mismatch")
    metadata = _parse(files["metadata.json"])
    try:
        report = files["report.html"].decode("utf-8") if "report.html" in files else None
    except UnicodeError as exc:
        raise ValueError("invalid report UTF-8") from exc
    records = None
    if saved:
        # Each record's exact type is checked below, not assumed from the file name.
        records = BundleRecords(
            **cast(
                dict[str, Any],
                {
                    field: _read_records(files[name], kind)
                    for field, (name, kind) in _RECORD_FILES.items()
                },
            )
        )
        _check_records(records, events)
    receipt = BundleReceipt(
        directory,
        receipt_hash,
        tuple(sorted((name, _hash(value)) for name, value in hashes.items())),
        len(events),
        final_hash,
    )
    return VerifiedBundle(receipt, events, _canonical(metadata).decode(), sources, report, records)
