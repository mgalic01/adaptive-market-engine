"""Publish supplied diagnostics, not a verdict, dispatch permission or attestation.

Validated RegisteredDocuments and an exclusively owned evidence directory are
caller prerequisites. Metadata linkage cannot establish report derivation or
complete historical attempt coverage. Runtime rechecks remain upstream. Completion
is a hash-pinned receipt, never the presence of report files. Interrupted writes
are retained and cannot be resumed here. Cleanup can fail after receipt publication:
inspect and verify that receipt; never infer absence, delete evidence or retry.
No security or power-loss guarantee.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trial_register import RegisteredDocuments

from crypto_grid_bot.trend.evidence_journal import LIMIT, _object
from crypto_grid_bot.trend.evidence_writer import AttemptRecorder
from crypto_grid_bot.trend.experiment_report import (
    REQUIRED,
    ExperimentReport,
    experiment_json,
    experiment_markdown,
)

REPORT_LIMIT = 64 * 1024 * 1024
RECEIPT_LIMIT = 32 * 1024 * 1024
STATUS = "diagnostics_published_uncertified"


@dataclass(frozen=True, slots=True)
class PublishedReport:
    directory: Path
    receipt_sha256: str


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pin(value: str, size: int = 64) -> None:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{size}}}", value) is None:
        raise ValueError("invalid publication identity digest")


def _identities(documents: RegisteredDocuments) -> dict[str, str]:
    names = (
        "trial_id",
        "revision",
        "registration_id",
        "completion_id",
        "code_commit",
        "code_sha256",
        "spec_sha256",
        "manifest_path",
        "manifest_sha256",
        "config_path",
        "config_sha256",
    )
    values = {name: getattr(documents, name) for name in names}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ValueError("missing publication registration identity")
    for name in ("revision", "code_commit"):
        _pin(values[name], 40)
    for name in ("code_sha256", "spec_sha256", "manifest_sha256", "config_sha256"):
        _pin(values[name])
    for raw, digest, limit in (
        (documents.manifest, documents.manifest_sha256, RECEIPT_LIMIT),
        (documents.config, documents.config_sha256, 1024 * 1024),
    ):
        if not isinstance(raw, bytes) or len(raw) > limit or _digest(raw) != digest:
            raise ValueError("supplied registered document hash or size mismatch")
    return values


def _regular(path: Path) -> None:
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError(f"publication requires regular file: {path.name}")


def _read(path: Path, limit: int) -> bytes:
    _regular(path)
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"publication file exceeds size limit: {path.name}")
    return raw


def _root(directory: Path) -> Path:
    if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
        raise ValueError("existing regular evidence directory required")
    return directory.resolve()


def _attempts(root: Path) -> list[dict[str, Any]]:
    # Guard the paths before the existing journal/artifact reader opens them.
    for path in (*root.glob("*.json"), *root.glob("*.evidence.jsonl")):
        _regular(path)
    recorder = AttemptRecorder(root)  # verifies framing, identities, artifacts and pending starts
    rows = []
    referenced = set()
    for path in sorted(root.glob("*.started.json")):
        run_id = path.name[:-13]
        start = _read(path, LIMIT)
        finish = _read(root / f"{run_id}.finished.json", LIMIT)
        payload = recorder.journal._read(run_id, "finished")["payload"]
        error = payload["error"]
        if error is not None and (not isinstance(error, str) or not error):
            raise ValueError("invalid attempt error metadata")
        evidence = payload["evidence"]
        if evidence is not None:
            referenced.add(evidence["path"])
        rows.append(
            {
                "run_id": run_id,
                "started_sha256": _digest(start),
                "finished_sha256": _digest(finish),
                "error": error,
                "evidence": evidence,
            }
        )
    if not rows:
        raise ValueError("publication requires observed attempt evidence")
    if {p.name for p in root.glob("*.evidence.jsonl")} != referenced:
        raise ValueError("unreferenced published attempt evidence")
    return rows


def _json(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _write(path: Path, raw: bytes) -> None:
    # Partial files remain on any failure; the containing report directory is never reused.
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def _metadata(raw: bytes) -> dict[str, Any]:
    return {"sha256": _digest(raw), "bytes": len(raw)}


def publish_experiment_report(
    directory: Path, report: ExperimentReport, documents: RegisteredDocuments
) -> PublishedReport:
    """Persist supplied uncertified diagnostics once; never execute or retry a run."""
    root = _root(directory)
    identities = _identities(documents)
    prerequisites = REQUIRED if report.full_size_hold is None else REQUIRED[:-1]
    if report.verdict is not None or report.required_before_verdict != prerequisites:
        raise ValueError("publication must retain uncertified verdict and all report prerequisites")
    outputs = {
        "experiment.json": experiment_json(report).encode(),
        "experiment.md": experiment_markdown(report).encode(),
    }
    if any(len(raw) > REPORT_LIMIT for raw in outputs.values()):
        raise ValueError("serialized report exceeds size limit")
    attempts = _attempts(root)
    receipt = _json(
        {
            "schema": 1,
            "status": STATUS,
            "identities": identities,
            "required_before_verdict": list(prerequisites),
            "attempts": attempts,
            "files": {name: _metadata(raw) for name, raw in outputs.items()},
        }
    )
    if len(receipt) > RECEIPT_LIMIT:
        raise ValueError("publication receipt exceeds size limit")
    destination = root / "report"
    destination.mkdir(exist_ok=False)
    for name, raw in outputs.items():
        _write(destination / name, raw)
    if _attempts(root) != attempts or any(
        _read(destination / name, REPORT_LIMIT) != raw for name, raw in outputs.items()
    ):
        raise ValueError("evidence or report changed during publication")
    temporary = destination / ".publication.tmp"
    _write(temporary, receipt)
    # The only completion marker is atomic and cannot overwrite an existing receipt.
    os.link(temporary, destination / "publication.json")
    temporary.unlink()
    return verify_published_report(root, _digest(receipt), documents)


def verify_published_report(
    directory: Path, receipt_sha256: str, documents: RegisteredDocuments
) -> PublishedReport:
    """Verify with a separately retained receipt pin; not a historical verdict."""
    root = _root(directory)
    _pin(receipt_sha256)
    destination = root / "report"
    if destination.is_symlink() or destination.is_junction() or not destination.is_dir():
        raise ValueError("missing or redirected report directory")
    raw = _read(destination / "publication.json", RECEIPT_LIMIT)
    if _digest(raw) != receipt_sha256:
        raise ValueError("publication receipt hash mismatch")
    receipt = json.loads(raw, object_pairs_hook=_object)
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {"schema", "status", "identities", "required_before_verdict", "attempts", "files"}
        or type(receipt["schema"]) is not int
        or receipt["schema"] != 1
        or receipt["status"] != STATUS
        or receipt["identities"] != _identities(documents)
        or not isinstance(receipt["files"], dict)
        or set(receipt["files"]) != {"experiment.json", "experiment.md"}
    ):
        raise ValueError("invalid publication receipt or registered identity mismatch")
    contents = {}
    for name, pin in receipt["files"].items():
        contents[name] = _read(destination / name, REPORT_LIMIT)
        if pin != _metadata(contents[name]):
            raise ValueError("publication report hash or size mismatch")
    report = json.loads(contents["experiment.json"], object_pairs_hook=_object)
    prerequisites = list(REQUIRED if report.get("full_size_hold") is None else REQUIRED[:-1])
    if (
        report.get("verdict", "missing") is not None
        or report.get("required_before_verdict") != prerequisites
        or receipt["required_before_verdict"] != prerequisites
        or receipt["attempts"] != _attempts(root)
    ):
        raise ValueError("publication prerequisites or observed attempt evidence mismatch")
    return PublishedReport(destination, receipt_sha256)
