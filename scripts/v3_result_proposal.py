"""Read-only result-event proposals, never canonical register mutation or dispatch.

Caller supplies previously validated committed documents and exclusively owns a
quiescent evidence directory. Matching metadata is not authenticated provenance.
Pending dispositions are caller-reviewed claims, not authorization or inferred
execution outcomes/timestamps. Success means a recorded run completed, not strategy
acceptance. Full-size hold unavailability never decides A5 or an experiment verdict.
Observed local attempts do not prove all-history coverage or report derivation.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from trial_register import RegisteredDocuments, _digest, _parse, _path, validate_append

from crypto_grid_bot.trend.evidence_journal import LIMIT, EvidenceJournal, _object
from crypto_grid_bot.trend.evidence_writer import _inspect_artifact, verify_artifact
from crypto_grid_bot.trend.orchestration import INVALID

LIMIT_PROPOSAL = 32 * 1024 * 1024
FUTURES_PHASES = frozenset({"training", "out_of_sample", "sensitivity", "fixed_rule"})


@dataclass(frozen=True, slots=True)
class PendingDisposition:
    status: Literal["failed", "cancelled"]
    reason: str
    source: str


@dataclass(frozen=True, slots=True)
class ResultProposal:
    index: bytes
    events: bytes


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty provenance text required")


def _read(path: Path) -> bytes:
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError(f"regular journal file required: {path.name}")
    with path.open("rb") as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("journal metadata exceeds size limit")
    return raw


def _registration(
    register: bytes, docs: RegisteredDocuments
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(register, bytes) or len(register) > LIMIT_PROPOSAL:
        raise ValueError("register exceeds proposal size limit")
    events = _parse(register)
    _digest(docs.revision, 40)
    matches = [e for e in events if e["event_id"] == docs.completion_id]
    if len(matches) != 1 or matches[0]["event_type"] != "completion":
        raise ValueError("matching completing registration required")
    done = matches[0]
    payload = done["payload"]
    if (
        done["trial_id"] != docs.trial_id
        or payload["registration_id"] != docs.registration_id
        or payload["code_commit"] != docs.code_commit
        or payload["code_sha256"] != docs.code_sha256
        or payload["manifest"] != {"path": docs.manifest_path, "sha256": docs.manifest_sha256}
        or payload["config"] != {"path": docs.config_path, "sha256": docs.config_sha256}
        or any(e["trial_id"] == docs.trial_id and e["event_type"] == "correction" for e in events)
    ):
        raise ValueError("registered document identities disagree or trial is corrected")
    registration = next(e for e in events if e["event_id"] == docs.registration_id)
    if registration["payload"]["spec"]["sha256"] != docs.spec_sha256:
        raise ValueError("registered spec digest mismatch")
    for raw, expected, limit in (
        (docs.manifest, docs.manifest_sha256, LIMIT_PROPOSAL),
        (docs.config, docs.config_sha256, 1024 * 1024),
    ):
        if not isinstance(raw, bytes) or len(raw) > limit or _hash(raw) != expected:
            raise ValueError("supplied registered document hash or size mismatch")
    identities = {
        name: getattr(docs, name)
        for name in (
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
    }
    return done, identities


def _outcome(root: Path, evidence: dict[str, Any], phase: str) -> tuple[str, str | None]:
    kind = (
        "outcome"
        if phase in FUTURES_PHASES
        else ("spot_account" if phase == "spot_hold" else "full_size_hold")
    )
    digest = hashlib.sha256()
    outcomes = []
    # Artifact framing/counts were verified already. Hash the classified read too.
    with (root / evidence["path"]).open("rb") as source:
        while raw := source.readline(LIMIT + 1):
            if len(raw) > LIMIT or not raw.endswith(b"\n"):
                raise ValueError("invalid outcome evidence row")
            digest.update(raw)
            row = json.loads(raw, object_pairs_hook=_object)
            if row.get("kind") == kind:
                outcomes.append(row.get("value"))
    if digest.hexdigest() != evidence["sha256"]:
        raise ValueError("evidence changed during outcome classification")
    key = "stopped" if phase == "spot_hold" else "reason"
    if len(outcomes) != 1 or not isinstance(outcomes[0], dict) or key not in outcomes[0]:
        raise ValueError("exactly one phase-specific recorded outcome required")
    reason = outcomes[0][key]
    if reason is not None and not isinstance(reason, str):
        raise ValueError("unsupported recorded outcome type")
    if phase == "spot_hold":
        if reason == "completed":
            return "success", None
        allowed: set[str] | frozenset[str] = {"unavailable_exclusion_close"}
    else:
        if reason is None:
            return "success", None
        allowed = INVALID if phase in FUTURES_PHASES else {"unavailable_first_purchase"}
    if reason not in allowed:
        raise ValueError("unsupported recorded outcome reason")
    return "invalid", reason


def _attempts(root: Path, dispositions: Mapping[str, PendingDisposition]) -> list[dict[str, Any]]:
    for path in (*root.glob("*.json"), *root.glob("*.evidence.jsonl")):
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("redirected or nonregular evidence input")
    journal = EvidenceJournal(root)  # Root must already exist; never creates an input directory.
    pending = set(journal.pending())
    if set(dispositions) != pending:
        raise ValueError("exact explicit dispositions required for pending starts")
    rows = []
    artifact_names = set()
    for start_path in sorted(root.glob("*.started.json")):
        run_id = start_path.name[:-13]
        start_raw = _read(start_path)
        identity = journal._read(run_id, "started")["payload"]
        phase = identity.get("phase")
        if not isinstance(phase, str) or phase not in FUTURES_PHASES | {
            "spot_hold",
            "full_size_hold",
        }:
            raise ValueError("unsupported attempt phase")
        name = f"{run_id}.evidence.jsonl"
        evidence = finish_pin = disposition = None
        status: str
        reason: str | None
        if run_id in pending:
            claim = dispositions[run_id]
            if not isinstance(claim, PendingDisposition) or claim.status not in {
                "failed",
                "cancelled",
            }:
                raise ValueError("pending disposition must claim failed or cancelled")
            _text(claim.reason)
            _text(claim.source)
            disposition = asdict(claim)
            status, reason = claim.status, claim.reason
            if (root / name).exists():
                evidence = _inspect_artifact(root, name)
            outcome_confirmed = False
        else:
            finish_path = root / f"{run_id}.finished.json"
            finish_pin = {"path": finish_path.name, "sha256": _hash(_read(finish_path))}
            finish = journal._read(run_id, "finished")["payload"]
            if set(finish) != set(identity) | {"error", "evidence"} or any(
                finish[key] != value for key, value in identity.items()
            ):
                raise ValueError("finished attempt identity differs from start")
            error, evidence = finish["error"], finish["evidence"]
            if error is not None:
                _text(error)
            if evidence is not None:
                if not isinstance(evidence, dict) or evidence.get("path") != name:
                    raise ValueError("evidence belongs to another attempt")
                verify_artifact(root, evidence)
            elif error is None or (root / name).exists():
                raise ValueError("finished attempt lacks referenced evidence or error")
            if error is not None:
                status, reason = "failed", error
            else:
                if evidence is None:
                    raise ValueError("finished attempt lacks outcome evidence")
                status, reason = _outcome(root, evidence, phase)
            outcome_confirmed = error is None
        if evidence is not None:
            artifact_names.add(name)
        rows.append(
            {
                "run_id": run_id,
                "identity": identity,
                "start": {"path": start_path.name, "sha256": _hash(start_raw)},
                "finish": finish_pin,
                "evidence": evidence,
                "status": status,
                "reason": reason,
                "disposition": disposition,
                "outcome_confirmed": outcome_confirmed,
            }
        )
    if not rows:
        raise ValueError("no observed started attempts")
    if {p.name for p in root.glob("*.evidence.jsonl")} != artifact_names:
        raise ValueError("orphan artifact without referenced start")
    return rows


def build_result_proposal(
    register_bytes: bytes,
    documents: RegisteredDocuments,
    evidence_directory: Path,
    *,
    index_path: str,
    evidence_source: str,
    recorded_at: str,
    agent: str,
    pending_dispositions: Mapping[str, PendingDisposition],
) -> ResultProposal:
    """Return proposal bytes only; callers separately review, persist and append.

    The supplied recorded_at is proposal-recording time, never inferred run time.
    evidence_source and pending disposition sources are provenance text only; they
    are not opened or treated as authenticated instructions or authorization.
    """
    _path(index_path)
    _text(evidence_source)
    _text(agent)
    done, identities = _registration(register_bytes, documents)
    root = Path(evidence_directory)
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError("existing regular evidence directory required")
    root = root.resolve()
    attempts = _attempts(root, pending_dispositions)
    index = (
        _encoded(
            {
                "schema": 1,
                "status": "result_event_proposal_uncertified",
                "experiment_verdict": None,
                "status_scope": "recorded_run_only",
                "identities": identities,
                "register_sha256": _hash(register_bytes),
                "evidence_source": evidence_source,
                "recorded_at": recorded_at,
                "agent": agent,
                "pending_dispositions_are_caller_claims": True,
                "attempts": attempts,
            }
        )
        + b"\n"
    )
    provenance = _encoded({"index_sha256": _hash(index), **identities}).decode()
    events = []
    for attempt in attempts:
        run_id = attempt["run_id"]
        event_id = "v3-result-" + _hash(
            _encoded([documents.trial_id, documents.completion_id, run_id])
        )
        events.append(
            {
                "schema_version": 1,
                "event_id": event_id,
                "trial_id": documents.trial_id,
                "event_type": "result",
                "recorded_at": recorded_at,
                "agent": agent,
                "family": done["family"],
                "parent_trial_id": done["parent_trial_id"],
                "sources": [index_path, evidence_source],
                "payload": {
                    "completion_id": documents.completion_id,
                    "run_id": run_id,
                    "status": attempt["status"],
                    "reason": attempt["reason"],
                    "metrics": {},
                    "provenance": provenance,
                    "report": f"{index_path}#run_id={run_id}",
                },
            }
        )
    encoded = b"".join(_encoded(event) + b"\n" for event in events)
    if max(len(index), len(encoded)) > LIMIT_PROPOSAL:
        raise ValueError("result proposal exceeds size limit")
    validate_append(register_bytes, register_bytes + encoded)
    if _attempts(root, pending_dispositions) != attempts:
        raise ValueError("attempt evidence changed during proposal construction")
    return ResultProposal(index, encoded)
