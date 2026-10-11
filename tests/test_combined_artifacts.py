"""Saved evidence is exclusive, structurally checked and tamper evident."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_combined_evidence import event

from crypto_grid_bot.combined.artifacts import read_bundle, write_bundle
from crypto_grid_bot.combined.evidence import Evidence


def journal():
    result = Evidence()
    result.record(event())
    result.record(
        replace(
            event("qualified", event_id="e2", time=2), accepted=False, reasons=("missing_quote",)
        )
    )
    return result


def test_round_trip_preserves_original_journal_metadata_and_html(tmp_path):
    evidence = journal()
    metadata = {
        "synthetic": True,
        "failed": True,
        "equity": "99.00000000000000000001",
        "nested": [None, 1, {"source_refs": ["fixture"]}],
    }
    receipt = write_bundle(tmp_path, "synthetic-1", evidence, metadata, "<h1>Evidence</h1>")
    bundle = read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)
    assert bundle.events == evidence.events
    assert json.loads(bundle.metadata_json) == metadata
    assert bundle.source_refs == ("sha256:fixture",)
    assert bundle.report_html == "<h1>Evidence</h1>"
    assert receipt.event_count == 2
    assert (receipt.directory / "decisions.jsonl").read_text() == evidence.json_lines()
    assert bundle.receipt == receipt


def test_empty_evidence_is_retained_without_invented_sources(tmp_path):
    receipt = write_bundle(tmp_path, "empty", Evidence(), {})
    bundle = read_bundle(receipt.directory)
    assert bundle.events == () and bundle.source_refs == () and bundle.report_html is None


def test_same_invocation_never_overwrites(tmp_path):
    receipt = write_bundle(tmp_path, "once", journal(), {})
    original = {p.name: p.read_bytes() for p in receipt.directory.iterdir()}
    with pytest.raises(FileExistsError):
        write_bundle(tmp_path, "once", Evidence(), {})
    assert original == {p.name: p.read_bytes() for p in receipt.directory.iterdir()}


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/b", "a\\b", ".", "CON", "x.", "a:b"])
def test_invocation_path_is_single_portable_component(tmp_path, name):
    with pytest.raises(ValueError):
        write_bundle(tmp_path, name, journal(), {})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [1.2, float("nan"), Decimal("1"), {1: "x"}, ("tuple",)])
def test_metadata_requires_exact_json_types_before_creating_directory(tmp_path, value):
    with pytest.raises(ValueError):
        write_bundle(tmp_path, "invalid", journal(), {"value": value})
    assert list(tmp_path.iterdir()) == []


def test_cyclic_metadata_rejected(tmp_path):
    metadata = {}
    metadata["self"] = metadata
    with pytest.raises(ValueError):
        write_bundle(tmp_path, "cycle", journal(), metadata)


def rehash(directory, filename):
    path = directory / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["files"][filename] = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
    path.write_text(json.dumps(receipt))


@pytest.mark.parametrize("filename", ["decisions.jsonl", "metadata.json", "report.html"])
def test_modified_artifact_is_rejected(tmp_path, filename):
    receipt = write_bundle(tmp_path, "tamper", journal(), {}, "report")
    with (receipt.directory / filename).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="hash"):
        read_bundle(receipt.directory)


def test_external_receipt_pin_detects_rewritten_receipt(tmp_path):
    receipt = write_bundle(tmp_path, "pin", journal(), {})
    (receipt.directory / "metadata.json").write_text("{} ")
    rehash(receipt.directory, "metadata.json")
    with pytest.raises(ValueError, match="receipt"):
        read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)


@pytest.mark.parametrize("mutation", ["clock", "schema", "duplicate", "phase", "accepted_type"])
def test_valid_hashes_do_not_bypass_event_validation(tmp_path, mutation):
    receipt = write_bundle(tmp_path, "schema", journal(), {})
    path = receipt.directory / "decisions.jsonl"
    rows = [json.loads(row) for row in path.read_text().splitlines()]
    if mutation == "clock":
        rows[1]["event"]["timestamp_ms"] = 0
    elif mutation == "schema":
        rows[1]["event"]["schema"] = "future"
    elif mutation == "duplicate":
        rows[1] = rows[0]
    elif mutation == "phase":
        rows[1]["event"]["phase"] = "filled"
    else:
        rows[1]["event"]["accepted"] = 1
    previous = "0" * 64
    for row in rows:
        row["previous_hash"] = previous
        payload = {k: v for k, v in row.items() if k != "hash"}
        row["hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        previous = row["hash"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    rehash(receipt.directory, path.name)
    manifest_path = receipt.directory / "receipt.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["final_chain_hash"] = previous
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


def test_unknown_files_and_manifest_paths_rejected(tmp_path):
    receipt = write_bundle(tmp_path, "extra", journal(), {})
    (receipt.directory / "extra.txt").write_text("unexpected")
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)
    (receipt.directory / "extra.txt").unlink()
    path = receipt.directory / "receipt.json"
    data = json.loads(path.read_text())
    data["files"]["../outside"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


def test_duplicate_json_keys_rejected_even_after_rehash(tmp_path):
    receipt = write_bundle(tmp_path, "dupe", journal(), {})
    (receipt.directory / "metadata.json").write_text('{"same":1,"same":2}')
    rehash(receipt.directory, "metadata.json")
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


def test_write_failure_retains_completed_evidence_and_blocks_retry(tmp_path, monkeypatch):
    original = Path.open

    def interrupted(path, *args, **kwargs):
        if path.name == "metadata.json" and args and args[0] == "xb":
            raise OSError("synthetic disk failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted)
    with pytest.raises(OSError, match="synthetic disk failure"):
        write_bundle(tmp_path, "failed", journal(), {})
    assert (tmp_path / "failed" / "decisions.jsonl").read_text() == journal().json_lines()
    with pytest.raises(ValueError):
        read_bundle(tmp_path / "failed")
    with pytest.raises(FileExistsError):
        write_bundle(tmp_path, "failed", journal(), {})


def test_symlink_paths_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit symlink creation")
    with pytest.raises(ValueError):
        write_bundle(link, "escape", journal(), {})
    receipt = write_bundle(tmp_path, "links", journal(), {})
    target = receipt.directory / "metadata.json"
    target.unlink()
    target.symlink_to(outside / "metadata.json")
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


@pytest.mark.parametrize(
    "field,value",
    [("event_count", 3), ("source_refs", ["invented"]), ("final_chain_hash", "0" * 64)],
)
def test_receipt_summary_must_match_actual_events(tmp_path, field, value):
    receipt = write_bundle(tmp_path, "summary", journal(), {})
    path = receipt.directory / "receipt.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


@pytest.mark.parametrize("corruption", ["link", "truncated", "blank"])
def test_journal_internal_integrity_survives_outer_file_rehash(tmp_path, corruption):
    receipt = write_bundle(tmp_path, "internal", journal(), {})
    path = receipt.directory / "decisions.jsonl"
    raw = path.read_text()
    if corruption == "link":
        rows = [json.loads(row) for row in raw.splitlines()]
        rows[1]["previous_hash"] = "0" * 64
        raw = "".join(json.dumps(row) + "\n" for row in rows)
    elif corruption == "truncated":
        raw = raw[:-1]
    else:
        raw += "\n"
    path.write_text(raw)
    rehash(receipt.directory, path.name)
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


def test_windows_junction_ancestor_rejected(tmp_path):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows junction test")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True
    )
    try:
        assert link.is_junction()
        with pytest.raises(ValueError, match="junction"):
            write_bundle(link, "attempt", journal(), {})
        receipt = write_bundle(outside, "safe", journal(), {})
        with pytest.raises(ValueError, match="junction"):
            read_bundle(link / receipt.directory.name)
        assert not (outside / "attempt").exists()
    finally:
        link.rmdir()


def test_dotdot_directory_paths_are_rejected_without_normalizing_away_links(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    parent = child / ".."
    with pytest.raises(ValueError, match="traversal"):
        write_bundle(parent, "attempt", journal(), {})
    receipt = write_bundle(tmp_path, "safe_path", journal(), {})
    with pytest.raises(ValueError, match="traversal"):
        read_bundle(child / ".." / receipt.directory.name)
