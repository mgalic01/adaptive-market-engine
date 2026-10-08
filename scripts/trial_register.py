"""Offline trial-history validation. No dispatch or network operations.

Schema validation alone is not a dispatch authorization. Committed-file pin
verification and runner integration are separate requirements.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
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
    prior: dict[str, dict[str, Any]] = {}
    stages: set[tuple[str, str]] = set()
    runs: set[str] = set()
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
            for field in ("event_id", "trial_id", "agent", "family", "recorded_at", "event_type"):
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
                _forward(event, prior, stages, runs)
                prior[event["event_id"]] = event
                continue
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
            prior[event["event_id"]] = event
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


def _fields(payload: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != names:
        raise ValueError("invalid payload fields")
    return payload


def _digest(value: Any, length: int) -> None:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is None:
        raise ValueError("invalid digest or commit")


def _path(value: Any) -> None:
    if not _text(value) or "\\" in value or ":" in value:
        raise ValueError("expected relative repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("expected canonical relative repository path")


def _pin(value: Any, commit: bool = False) -> None:
    fields = {"path", "sha256", "commit"} if commit else {"path", "sha256"}
    pin = _fields(value, fields)
    _path(pin["path"])
    _digest(pin["sha256"], 64)
    if commit:
        _digest(pin["commit"], 40)


def _reference(
    event: dict[str, Any], prior: dict[str, dict[str, Any]], identity: Any, kind: str
) -> None:
    if not _text(identity) or identity not in prior:
        raise ValueError("missing prior event reference")
    other = prior[identity]
    if other["trial_id"] != event["trial_id"] or other["event_type"] != kind:
        raise ValueError("reference belongs to wrong trial or stage")
    if other["family"] != event["family"] or other["parent_trial_id"] != event["parent_trial_id"]:
        raise ValueError("trial family or parent changed")


def _forward(
    event: dict[str, Any],
    prior: dict[str, dict[str, Any]],
    stages: set[tuple[str, str]],
    runs: set[str],
) -> None:
    kind = event["event_type"]
    stage = (event["trial_id"], kind)
    if kind in ("registration", "completion") and stage in stages:
        raise ValueError("duplicate trial stage")
    p = event["payload"]
    if kind == "registration":
        p = _fields(
            p,
            {
                "preregistered",
                "hypothesis",
                "spec",
                "candidates",
                "sizes",
                "fees",
                "folds",
                "mask",
                "seeds",
                "budget",
                "stopping",
                "selection",
                "data",
                "code",
            },
        )
        if p["preregistered"] is not True or p["data"] is not None or p["code"] is not None:
            raise ValueError("initial registration must disclose pending code and data")
        _pin(p["spec"], commit=True)
        for field in ("hypothesis", "fees", "folds", "mask", "budget", "stopping", "selection"):
            if not _text(p[field]):
                raise ValueError(f"missing {field}")
        candidates = p["candidates"]
        if (
            not isinstance(candidates, list)
            or not candidates
            or not all(map(_text, candidates))
            or len(set(candidates)) != len(candidates)
        ):
            raise ValueError("unique candidate descriptions required")
        sizes = p["sizes"]
        if (
            not isinstance(sizes, list)
            or not sizes
            or any(type(x) is not int or x <= 0 for x in sizes)
        ):
            raise ValueError("positive integer sizes required")
        if not isinstance(p["seeds"], list) or any(type(x) is not int for x in p["seeds"]):
            raise ValueError("seeds must be explicit integers")
        if any(e["trial_id"] == event["trial_id"] for e in prior.values()):
            raise ValueError("registration cannot reuse an existing historical trial ID")
    elif kind == "completion":
        p = _fields(
            p,
            {
                "registration_id",
                "code_commit",
                "code_sha256",
                "code_paths",
                "manifest",
                "config",
                "review",
            },
        )
        _reference(event, prior, p["registration_id"], "registration")
        _digest(p["code_commit"], 40)
        _digest(p["code_sha256"], 64)
        _pin(p["manifest"])
        _pin(p["config"])
        paths = p["code_paths"]
        if not isinstance(paths, list) or not paths:
            raise ValueError("code paths required")
        for path in paths:
            _path(path)
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate code paths")
        if not _text(p["review"]):
            raise ValueError("review provenance required")
    elif kind == "result":
        p = _fields(
            p, {"completion_id", "run_id", "status", "provenance", "report", "metrics", "reason"}
        )
        _reference(event, prior, p["completion_id"], "completion")
        for field in ("run_id", "status", "provenance", "report"):
            if not _text(p[field]):
                raise ValueError(f"missing {field}")
        if p["status"] not in ("success", "invalid", "failed", "cancelled"):
            raise ValueError("unknown result status")
        if not isinstance(p["metrics"], dict):
            raise ValueError("metrics must be an object")
        if p["status"] != "success" and not _text(p["reason"]):
            raise ValueError("unsuccessful attempt requires reason")
        if p["status"] == "success" and p["reason"] is not None:
            raise ValueError("successful result reason must be null")
        if p["run_id"] in runs:
            raise ValueError("duplicate run ID; append a correction instead")
        runs.add(p["run_id"])
    elif kind == "correction":
        p = _fields(p, {"target_id", "reason", "details"})
        target = p["target_id"]
        if not _text(target) or target not in prior:
            raise ValueError("correction target must already exist")
        if prior[target]["trial_id"] != event["trial_id"]:
            raise ValueError("correction target belongs to another trial")
        if not _text(p["reason"]) or not _text(p["details"]):
            raise ValueError("correction explanation required")
    else:
        raise ValueError("unsupported event type")
    stages.add(stage)


def code_digest(blobs: dict[str, bytes]) -> str:
    """SHA256 of sorted UTF-8 paths and Git blobs, each prefixed by 8-byte length."""
    import hashlib

    digest = hashlib.sha256()
    for path, blob in sorted(blobs.items()):
        for part in (path.encode("utf-8"), blob):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> bytes:
    import subprocess  # nosec B404

    # Fixed Git executable and separate arguments; no shell or repository hooks invoked.
    process = subprocess.run(  # nosec B603, B607
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,  # nosec B603, B607
    )
    if process.returncode:
        raise ValueError("Git object or ancestry check failed")
    return process.stdout


def check_ready(root: Path, trial_id: str, revision: str) -> dict[str, Any]:
    """Verify committed registration pins; caller still owns review/data-access gates."""
    import hashlib

    _digest(revision, 40)
    if _git(root, "cat-file", "-t", revision).strip() != b"commit":
        raise ValueError("revision must name a commit")
    events = _parse(_git(root, "show", f"{revision}:docs/trials/register.jsonl"))
    matches = [e for e in events if e["trial_id"] == trial_id and e["event_type"] == "completion"]
    if len(matches) != 1:
        raise ValueError("one committed completion required")
    done = matches[0]
    # Corrections are annotations, never silent replacement of authorization pins.
    if any(e["trial_id"] == trial_id and e["event_type"] == "correction" for e in events):
        raise ValueError("corrected trial requires a new registration before dispatch")
    payload = done["payload"]
    registration = next(e for e in events if e["event_id"] == payload["registration_id"])
    spec = registration["payload"]["spec"]
    for ancestor in (payload["code_commit"], spec["commit"]):
        _git(root, "merge-base", "--is-ancestor", ancestor, revision)
    for pin in (spec, payload["config"], payload["manifest"]):
        blob = _git(root, "show", f"{revision}:{pin['path']}")
        if hashlib.sha256(blob).hexdigest() != pin["sha256"]:
            raise ValueError("committed file does not match pin")
    if (
        hashlib.sha256(_git(root, "show", f"{spec['commit']}:{spec['path']}")).hexdigest()
        != spec["sha256"]
    ):
        raise ValueError("registered spec commit does not match pin")
    for commit in (payload["code_commit"], revision):
        tracked = _git(root, "ls-tree", "-r", "--name-only", "-z", commit).decode().split("\0")
        required = {
            p
            for p in tracked
            if p.startswith(("src/", "scripts/"))
            or p in {"pyproject.toml", "requirements-dev.lock", "requirements.txt"}
        }
        if set(payload["code_paths"]) != required:
            raise ValueError("code path inventory does not cover committed implementation")
        blobs = {path: _git(root, "show", f"{commit}:{path}") for path in payload["code_paths"]}
        if code_digest(blobs) != payload["code_sha256"]:
            raise ValueError("committed code does not match pin")
    return done


def append_event(path: Path, event: dict[str, Any]) -> None:
    """Validate before atomic replacement; fail closed on another writer's lock."""
    import os
    import tempfile

    lock = path.with_suffix(path.suffix + ".lock")
    try:
        handle = lock.open("xb")
    except FileExistsError as exc:
        raise ValueError("register writer lock exists; inspect before recovery") from exc
    temporary: str | None = None
    try:
        with handle:
            handle.write(str(os.getpid()).encode("ascii"))
        old = path.read_bytes() if path.exists() else b""
        addition = (json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        candidate = old + addition
        validate_append(old, candidate)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = output.name
            output.write(candidate)
            output.flush()
            os.fsync(output.fileno())
        # Detect an external editor which did not respect our writer lock.
        if (path.read_bytes() if path.exists() else b"") != old:
            raise ValueError("register changed during append")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--register", type=Path, default=Path("docs/trials/register.jsonl"))
    validate.add_argument("--base-ref", help="full base commit for append-only comparison")
    append = commands.add_parser("append")
    append.add_argument("--register", type=Path, default=Path("docs/trials/register.jsonl"))
    append.add_argument("--event", type=Path, required=True)
    ready = commands.add_parser("check-ready")
    ready.add_argument("--trial-id", required=True)
    ready.add_argument("--revision", required=True, help="full committed revision")
    ready.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.command == "check-ready":
            check_ready(args.root, args.trial_id, args.revision)
        elif args.command == "append":
            event = json.loads(args.event.read_text(encoding="utf-8"), object_pairs_hook=_object)
            append_event(args.register, event)
        else:
            load_events(args.register)
            if args.base_ref:
                _digest(args.base_ref, 40)
                root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
                relative = args.register.resolve().relative_to(root.resolve()).as_posix()
                _path(relative)
                present = _git(root, "ls-tree", "--name-only", args.base_ref, "--", relative)
                base = _git(root, "show", f"{args.base_ref}:{relative}") if present else b""
                validate_append(base, args.register.read_bytes())
        print("trial register: valid")
        return 0
    except (OSError, ValueError) as exc:
        print(f"trial register: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
