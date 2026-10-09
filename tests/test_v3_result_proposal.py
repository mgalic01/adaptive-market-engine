"""Read-only proposal tests with fabricated metadata, never replay or market data."""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_trial_register import candidate, completion, encode  # noqa: E402
from trial_register import RegisteredDocuments, validate_append  # noqa: E402

from crypto_grid_bot.trend.evidence_journal import EvidenceJournal  # noqa: E402
from crypto_grid_bot.trend.evidence_writer import _write_rows  # noqa: E402


@pytest.fixture
def context(tmp_path):
    first, done = candidate(), completion()
    raw = b"{}\n"
    digest = hashlib.sha256(raw).hexdigest()
    done["payload"]["manifest"]["sha256"] = digest
    done["payload"]["config"]["sha256"] = digest
    docs = RegisteredDocuments(
        "v3",
        "1" * 40,
        "registered",
        "completed",
        "c" * 40,
        "d" * 64,
        "b" * 64,
        "config/manifest.json",
        digest,
        raw,
        "config/run.json",
        digest,
        raw,
    )
    root = tmp_path / "evidence"
    root.mkdir()
    register = encode(first, done)
    register_path = tmp_path / "register.jsonl"
    register_path.write_bytes(register)
    return root, register, docs


def add(
    root,
    run_id="run-1",
    phase="training",
    kind="outcome",
    outcome=None,
    error=None,
    pending=False,
    artifact=True,
):
    identity = {"phase": phase, "start_ms": 1, "end_ms_exclusive": 2}
    journal = EvidenceJournal(root)
    journal.record(run_id, "started", identity)
    key = "stopped" if kind == "spot_account" else "reason"
    evidence = _write_rows(root, run_id, iter([(kind, {key: outcome})])) if artifact else None
    if not pending:
        journal.record(run_id, "finished", {**identity, "error": error, "evidence": evidence})


def build(context, **kwargs):
    from v3_result_proposal import build_result_proposal

    root, register, docs = context
    return build_result_proposal(
        register,
        docs,
        root,
        index_path="docs/trials/proposed/attempt-index.json",
        evidence_source="retained synthetic evidence",
        recorded_at="2026-10-09T18:00:00Z",
        agent="Codex synthetic",
        pending_dispositions=kwargs.pop("pending_dispositions", {}),
        **kwargs,
    )


def event(proposal):
    return json.loads(proposal.events.splitlines()[0])


@pytest.mark.parametrize(
    "phase,kind,outcome,status",
    [
        ("training", "outcome", None, "success"),
        ("out_of_sample", "outcome", "liquidation", "invalid"),
        ("fixed_rule", "outcome", "no_tradable_position", "invalid"),
        ("sensitivity", "outcome", "leverage_not_restored", "invalid"),
        ("training", "outcome", "unavailable_exclusion_close", "invalid"),
        ("spot_hold", "spot_account", "completed", "success"),
        ("spot_hold", "spot_account", "unavailable_exclusion_close", "invalid"),
        ("full_size_hold", "full_size_hold", None, "success"),
        ("full_size_hold", "full_size_hold", "unavailable_first_purchase", "invalid"),
    ],
)
def test_known_outcomes_map_without_verdict(context, phase, kind, outcome, status):
    add(context[0], phase=phase, kind=kind, outcome=outcome)
    result = build(context)
    row = event(result)
    assert row["payload"]["status"] == status
    assert row["payload"]["reason"] == (None if status == "success" else outcome)
    assert row["payload"]["metrics"] == {}
    assert set(row["payload"]) == {
        "completion_id",
        "run_id",
        "status",
        "provenance",
        "report",
        "metrics",
        "reason",
    }
    validate_append(context[1], context[1] + result.events)
    index = json.loads(result.index)
    assert index["experiment_verdict"] is None
    assert (
        index["attempts"][0]["evidence"]["sha256"]
        == hashlib.sha256((context[0] / "run-1.evidence.jsonl").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("artifact", [False, True])
def test_recorded_error_wins_over_partial_outcome(context, artifact):
    add(context[0], error="EngineError: synthetic", artifact=artifact, outcome="liquidation")
    row = event(build(context))
    assert row["payload"]["status"] == "failed"
    assert row["payload"]["reason"] == "EngineError: synthetic"


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("artifact", [False, True])
def test_explicit_pending_claim_preserves_unconfirmed_artifact(context, status, artifact):
    from v3_result_proposal import PendingDisposition

    add(context[0], pending=True, artifact=artifact)
    disposition = PendingDisposition(status, "caller inspected stopped process", "review-note")
    result = build(context, pending_dispositions={"run-1": disposition})
    assert event(result)["payload"]["status"] == status
    row = json.loads(result.index)["attempts"][0]
    assert row["finish"] is None
    assert row["outcome_confirmed"] is False
    assert row["disposition"]["source"] == "review-note"
    assert not (context[0] / "run-1.finished.json").exists()


def test_pending_without_explicit_claim_blocks_even_with_complete_artifact(context):
    add(context[0], pending=True)
    with pytest.raises(ValueError, match="pending"):
        build(context)


@pytest.mark.parametrize(
    "phase,kind,outcome",
    [
        ("unknown", "outcome", None),
        ("training", "outcome", "unknown"),
        ("spot_hold", "spot_account", None),
        ("training", "outcome", 0),
        ("full_size_hold", "full_size_hold", "liquidation"),
        ("training", "spot_account", "completed"),
    ],
)
def test_unknown_phase_outcome_or_type_blocks(context, phase, kind, outcome):
    add(context[0], phase=phase, kind=kind, outcome=outcome)
    with pytest.raises(ValueError):
        build(context)


@pytest.mark.parametrize("damage", ["artifact", "identity", "duplicate-outcome", "orphan"])
def test_integrity_failures_preserve_every_input_byte(context, damage):
    root = context[0]
    add(root)
    if damage == "artifact":
        (root / "run-1.evidence.jsonl").write_bytes(b"changed")
    elif damage == "identity":
        path = root / "run-1.finished.json"
        doc = json.loads(path.read_bytes())
        doc["payload"]["phase"] = "sensitivity"
        path.write_text(json.dumps(doc))
    elif damage == "duplicate-outcome":
        path = root / "run-1.evidence.jsonl"
        raw = path.read_bytes() * 2
        path.write_bytes(raw)
        finish = root / "run-1.finished.json"
        doc = json.loads(finish.read_bytes())
        doc["payload"]["evidence"].update(
            sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), records=2
        )
        finish.write_text(json.dumps(doc))
    else:
        _write_rows(root, "orphan", iter([("outcome", {"reason": None})]))
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ValueError):
        build(context)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert (root.parent / "register.jsonl").read_bytes() == context[1]


def test_deterministic_order_ids_and_no_input_mutation(context):
    root = context[0]
    add(root, "z-run")
    add(root, "a-run", error="SyntheticError", artifact=False)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    first, second = build(context), build(context)
    assert first == second
    assert [json.loads(line)["payload"]["run_id"] for line in first.events.splitlines()] == [
        "a-run",
        "z-run",
    ]
    assert (
        event(first)["event_id"]
        == "v3-result-" + hashlib.sha256(b'["v3","completed","a-run"]').hexdigest()
    )
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert (root.parent / "register.jsonl").read_bytes() == context[1]
    assert hashlib.sha256(first.index).hexdigest() in event(first)["payload"]["provenance"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("trial_id", "other"),
        ("completion_id", "absent"),
        ("code_sha256", "e" * 64),
        ("manifest", b"changed"),
        ("revision", "main"),
    ],
)
def test_document_mismatch_blocks(context, field, value):
    root, register, docs = context
    add(root)
    with pytest.raises(ValueError):
        build((root, register, replace(docs, **{field: value})))


def test_existing_result_cannot_be_silently_duplicated(context):
    root, register, docs = context
    add(root)
    result = build(context)
    with pytest.raises(ValueError, match="duplicate"):
        build((root, register + result.events, docs))


@pytest.mark.parametrize("path", ["../index.json", "C:/index.json", "/index.json", "a\\index.json"])
def test_unsafe_destination_rejected(context, path):
    from v3_result_proposal import build_result_proposal

    root, register, docs = context
    add(root)
    with pytest.raises(ValueError):
        build_result_proposal(
            register,
            docs,
            root,
            index_path=path,
            evidence_source="text",
            recorded_at="2026-10-09T18:00:00Z",
            agent="test",
            pending_dispositions={},
        )


@pytest.mark.parametrize(
    "claim",
    [
        ("success", "reason", "source"),
        ("failed", "", "source"),
        ("cancelled", "reason", ""),
    ],
)
def test_pending_disposition_cannot_claim_success_or_omit_diagnosis(context, claim):
    from v3_result_proposal import PendingDisposition

    add(context[0], pending=True)
    with pytest.raises(ValueError):
        build(context, pending_dispositions={"run-1": PendingDisposition(*claim)})


def test_extra_disposition_cannot_reclassify_finished_attempt(context):
    from v3_result_proposal import PendingDisposition

    add(context[0])
    with pytest.raises(ValueError, match="pending"):
        build(
            context,
            pending_dispositions={"run-1": PendingDisposition("cancelled", "claim", "note")},
        )


@pytest.mark.parametrize("error", [None, "", 3, True])
def test_no_artifact_requires_nonempty_recorded_error(context, error):
    add(context[0], artifact=False, error=error)
    with pytest.raises(ValueError):
        build(context)


def test_absent_input_directory_is_not_created(context):
    root, register, docs = context
    missing = root / "missing"
    with pytest.raises(ValueError):
        build((missing, register, docs))
    assert not missing.exists()


def test_no_attempts_cannot_be_exported_as_success(context):
    with pytest.raises(ValueError, match="no observed"):
        build(context)


def test_changed_input_during_export_blocks_return_and_preserves_change(context, monkeypatch):
    import v3_result_proposal as module

    add(context[0])
    original = module.validate_append
    path = context[0] / "run-1.finished.json"

    def mutate(base, candidate):
        original(base, candidate)
        path.write_bytes(path.read_bytes() + b" ")

    monkeypatch.setattr(module, "validate_append", mutate)
    with pytest.raises(ValueError, match="changed"):
        build(context)
    assert path.read_bytes().endswith(b" ")
    assert (context[0].parent / "register.jsonl").read_bytes() == context[1]


def test_read_error_does_not_mutate_input(context, monkeypatch):
    add(context[0])
    before = {p.name: p.read_bytes() for p in context[0].iterdir()}
    original = Path.open

    def denied(path, *args, **kwargs):
        if path.name == "run-1.finished.json":
            raise PermissionError("synthetic read denial")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        with pytest.raises(PermissionError):
            build(context)
    assert {p.name: p.read_bytes() for p in context[0].iterdir()} == before


def test_alternative_valid_registration_remains_explicitly_unverified(context):
    root, register, docs = context
    add(root)
    events = [json.loads(line) for line in register.splitlines()]
    for row in events:
        row["trial_id"] = "another-valid-trial"
    other_register = encode(*events)
    other_docs = replace(docs, trial_id="another-valid-trial")
    proposal = build((root, other_register, other_docs))
    index = json.loads(proposal.index)
    assert index["attempt_registration_binding"] == "caller_proposed_unverified"
    for raw in proposal.events.splitlines():
        row = json.loads(raw)
        assert row["trial_id"] == "another-valid-trial"
        provenance = json.loads(row["payload"]["provenance"])
        assert provenance["attempt_registration_binding"] == "caller_proposed_unverified"
    validate_append(other_register, other_register + proposal.events)
    assert (root.parent / "register.jsonl").read_bytes() == register
