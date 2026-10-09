"""Synthetic publication only: no replay, market files or network."""

import hashlib
import json
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from trial_register import RegisteredDocuments  # noqa: E402

from crypto_grid_bot.trend.cost_diagnostics import MinimumAccountSize  # noqa: E402
from crypto_grid_bot.trend.evidence_journal import EvidenceJournal  # noqa: E402
from crypto_grid_bot.trend.evidence_writer import _write_rows  # noqa: E402
from crypto_grid_bot.trend.experiment_report import (  # noqa: E402
    ExperimentReport,
    experiment_json,
    experiment_markdown,
)
from crypto_grid_bot.trend.selection_report import SelectionReport  # noqa: E402


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "evidence"
    journal = EvidenceJournal(root)
    identity = {"phase": "synthetic"}
    journal.record("one", "started", identity)
    evidence = _write_rows(root, "one", iter([("outcome", {"reason": "synthetic-invalid"})]))
    journal.record("one", "finished", {**identity, "error": None, "evidence": evidence})
    journal.record("failed", "started", identity)
    journal.record("failed", "finished", {**identity, "error": "SyntheticError", "evidence": None})
    raw = b"{}\n"
    docs = RegisteredDocuments(
        "v3",
        "1" * 40,
        "registered",
        "completed",
        "2" * 40,
        "3" * 64,
        "4" * 64,
        "config/manifest.json",
        hashlib.sha256(raw).hexdigest(),
        raw,
        "config/run.json",
        hashlib.sha256(raw).hexdigest(),
        raw,
    )
    # Deliberately incomplete synthetic accounts: publisher must not certify them.
    report = ExperimentReport(
        1,
        2,
        SelectionReport((), 0, 0, Decimal(0)),
        {},
        {},
        {},
        (),
        (),
        {},
        MinimumAccountSize(Decimal(100), "BTCUSDT", 1, Decimal(1), Decimal(1), "synthetic"),
    )
    return root, report, docs


def test_publish_and_verify_exact_serializers_and_observed_failures(prepared):
    from v3_report_publication import publish_experiment_report, verify_published_report

    root, report, docs = prepared
    result = publish_experiment_report(root, report, docs)
    assert (root / "report/experiment.json").read_bytes() == experiment_json(report).encode()
    assert (root / "report/experiment.md").read_bytes() == experiment_markdown(report).encode()
    receipt = json.loads((root / "report/publication.json").read_bytes())
    assert receipt["status"] == "diagnostics_published_uncertified"
    assert receipt["identities"]["trial_id"] == "v3"
    assert receipt["identities"]["code_sha256"] == "3" * 64
    assert [row["run_id"] for row in receipt["attempts"]] == ["failed", "one"]
    assert receipt["attempts"][0]["error"] == "SyntheticError"
    assert EvidenceJournal(root).pending() == ()
    assert verify_published_report(root, result.receipt_sha256, docs) == result
    assert json.loads((root / "report/experiment.json").read_bytes())["verdict"] is None


@pytest.mark.parametrize("damage", ["pending", "artifact", "orphan", "identity", "empty"])
def test_bad_evidence_rejected_before_report_directory(prepared, damage):
    from v3_report_publication import publish_experiment_report

    root, report, docs = prepared
    if damage == "pending":
        EvidenceJournal(root).record("pending", "started", {})
    elif damage == "artifact":
        (root / "one.evidence.jsonl").write_bytes(b"tamper")
    elif damage == "orphan":
        _write_rows(root, "orphan", iter([("outcome", None)]))
    elif damage == "identity":
        path = root / "one.finished.json"
        value = json.loads(path.read_bytes())
        value["payload"]["phase"] = "changed"
        path.write_text(json.dumps(value))
    else:
        for path in root.iterdir():
            path.unlink()
    with pytest.raises(ValueError):
        publish_experiment_report(root, report, docs)
    assert not (root / "report").exists()


@pytest.mark.parametrize("damage", ["verdict", "prerequisites", "document", "commit"])
def test_invalid_supplied_metadata_before_writes(prepared, damage):
    from v3_report_publication import publish_experiment_report

    root, report, docs = prepared
    if damage == "verdict":
        report = replace(report, verdict="PASS")
    elif damage == "prerequisites":
        report = replace(report, required_before_verdict=())
    elif damage == "document":
        docs = replace(docs, manifest=b"changed")
    else:
        docs = replace(docs, revision="main")
    with pytest.raises(ValueError):
        publish_experiment_report(root, report, docs)
    assert not (root / "report").exists()


@pytest.mark.parametrize("failure", ["markdown", "fsync", "receipt_link", "drift"])
def test_failure_retains_partial_publication_without_receipt_or_retry(
    prepared, monkeypatch, failure
):
    import v3_report_publication as module

    root, report, docs = prepared
    original = module.os.fsync
    calls = []

    def fsync(fd):
        calls.append(fd)
        if failure == "fsync":
            raise OSError("synthetic fsync failure")
        original(fd)
        if failure == "drift" and len(calls) == 1:
            EvidenceJournal(root).record("new", "started", {})

    monkeypatch.setattr(module.os, "fsync", fsync)
    if failure == "receipt_link":
        monkeypatch.setattr(module.os, "link", lambda *args: (_ for _ in ()).throw(OSError("link")))
    if failure == "markdown":
        original_open = Path.open

        def opening(path, *args, **kwargs):
            if path.name == "experiment.md" and args == ("xb",):
                raise OSError("write")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", opening)
    with pytest.raises((ValueError, OSError)):
        module.publish_experiment_report(root, report, docs)
    assert (root / "report").is_dir()
    assert not (root / "report/publication.json").exists()
    with pytest.raises((ValueError, FileExistsError)):
        module.publish_experiment_report(root, report, docs)


@pytest.mark.parametrize(
    "target", ["experiment.json", "experiment.md", "publication.json", "attempt"]
)
def test_reader_rejects_tampered_publication(prepared, target):
    from v3_report_publication import publish_experiment_report, verify_published_report

    root, report, docs = prepared
    result = publish_experiment_report(root, report, docs)
    path = root / "one.finished.json" if target == "attempt" else root / "report" / target
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        verify_published_report(root, result.receipt_sha256, docs)


def test_existing_report_is_never_overwritten(prepared):
    from v3_report_publication import publish_experiment_report

    root, report, docs = prepared
    publish_experiment_report(root, report, docs)
    before = {p.name: p.read_bytes() for p in (root / "report").iterdir()}
    with pytest.raises(FileExistsError):
        publish_experiment_report(root, report, docs)
    assert {p.name: p.read_bytes() for p in (root / "report").iterdir()} == before


def test_reader_requires_matching_registered_identities(prepared):
    from v3_report_publication import publish_experiment_report, verify_published_report

    root, report, docs = prepared
    result = publish_experiment_report(root, report, docs)
    with pytest.raises(ValueError, match="identity"):
        verify_published_report(root, result.receipt_sha256, replace(docs, trial_id="other"))


def test_reader_rejects_incomplete_publication(prepared):
    from v3_report_publication import verify_published_report

    root, _, docs = prepared
    (root / "report").mkdir()
    (root / "report/experiment.json").write_text("{}")
    with pytest.raises(ValueError):
        verify_published_report(root, "a" * 64, docs)


def test_serializer_failure_has_no_publication_side_effect(prepared):
    from v3_report_publication import publish_experiment_report

    root, report, docs = prepared
    bad = replace(report, intervals={"bad": (float("nan"), 0)})
    with pytest.raises(ValueError):
        publish_experiment_report(root, bad, docs)
    assert not (root / "report").exists()


@pytest.mark.parametrize("nth", [2, 3])
def test_later_fsync_failure_never_publishes_receipt(prepared, monkeypatch, nth):
    import v3_report_publication as module

    root, report, docs = prepared
    original = module.os.fsync
    count = 0

    def fail(fd):
        nonlocal count
        count += 1
        if count == nth:
            raise OSError("synthetic flush failure")
        original(fd)

    monkeypatch.setattr(module.os, "fsync", fail)
    with pytest.raises(OSError):
        module.publish_experiment_report(root, report, docs)
    assert not (root / "report/publication.json").exists()
    assert (root / "report/experiment.json").is_file()


def test_report_symlink_is_never_followed(prepared):
    from v3_report_publication import publish_experiment_report, verify_published_report

    root, report, docs = prepared
    result = publish_experiment_report(root, report, docs)
    target = root / "report/experiment.md"
    outside = root.parent / "elsewhere.md"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="regular"):
        verify_published_report(root, result.receipt_sha256, docs)
