"""Saved evidence is exclusive, structurally checked and tamper evident."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_combined_evidence import event

from crypto_grid_bot.combined.artifacts import (
    BundleRecords,
    RunRecord,
    SymbolGaps,
    read_bundle,
    write_bundle,
)
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


RECORD_FILES = (
    "run.jsonl",
    "symbol_gaps.jsonl",
    "assessments.jsonl",
    "intents.jsonl",
    "decision_records.jsonl",
    "lifecycles.jsonl",
    "recoveries.jsonl",
)


def evidence_records():
    """One record of every kind, all from synthetic inputs, with their funnel journal."""
    from test_combined_routing import market

    from crypto_grid_bot.combined.decisions import Costs, DecisionCoordinator, VenueInputs
    from crypto_grid_bot.combined.engine import PortfolioEngine, Quote
    from crypto_grid_bot.combined.evidence import IntentRecord
    from crypto_grid_bot.combined.execution import VenueRules
    from crypto_grid_bot.combined.report import Contribution, RecoveryEpisode
    from crypto_grid_bot.combined.routing import RoutingContext

    assessment = replace(market(), atr=Decimal(2), extension=Decimal(1))
    now = assessment.decision_ms
    rules = VenueRules(Decimal(".001"), Decimal(0), Decimal(1000), Decimal(5), Decimal(".01"))
    spot = VenueInputs(
        rules,
        Costs(Decimal(".001"), Decimal(".0005"), Decimal(".004")),
        quote=Quote(Decimal(100), now),
    )
    run = RunRecord(("sha256:fixture",))
    journal = Evidence()
    coordinator = DecisionCoordinator(PortfolioEngine(Decimal(10000)), journal)
    result = coordinator.decide(
        "one", assessment, RoutingContext(), {}, spot, None, run.source_refs
    )
    # Records cite the run's sources once, by its digest, then their own references.
    refs = (run.ref,)
    records = BundleRecords(
        run,
        (SymbolGaps("BTCUSDT", now, (), (), (), (), ()),),
        (replace(assessment, source_refs=(*refs, *assessment.source_refs)),),
        (IntentRecord("one", assessment.assessment_id, now, result.intent, refs),),
        (replace(result.record, source_refs=refs),),
        (
            Contribution(
                "lifecycle:BTCUSDT:fill",
                "spot_trend",
                "BTCUSDT",
                "long",
                "up/up/pullback",
                Decimal("1.5"),
                Decimal("0.1"),
                Decimal(0),
                Decimal(200),
                "stop",
                now,
                "closed",
                now + 3_600_000,
                None,
                None,
                (*refs, "fill:entry"),
            ),
        ),
        (RecoveryEpisode(now, None, Decimal(10000), None, "recovery:obs", refs, "obs", None),),
    )
    return journal, records


def test_every_evidence_record_kind_round_trips_as_a_versioned_file(tmp_path):
    journal, records = evidence_records()
    receipt = write_bundle(tmp_path, "records", journal, {}, records=records)
    bundle = read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)
    assert bundle.records == records and bundle.events == journal.events
    assert {name for name, _ in receipt.file_hashes} >= set(RECORD_FILES)
    for name in RECORD_FILES:
        rows = [json.loads(row) for row in (receipt.directory / name).read_text().splitlines()]
        assert len(rows) == 1 and set(rows[0]) == {"schema", "record"}
        assert rows[0]["schema"] == "combined-v1"
    saved = json.loads((receipt.directory / "decision_records.jsonl").read_text())["record"]
    assert saved["spot_fee_rate"] == "0.001" and saved["executable_quantity"] is not None
    # A bundle without records reads back as such, not as an empty record set.
    plain = write_bundle(tmp_path, "plain", journal, {})
    assert read_bundle(plain.directory).records is None


def test_each_recovery_record_kind_round_trips_with_what_ended_it(tmp_path):
    from test_combined_replay_records import SEQUENCE, trace_of

    from crypto_grid_bot.combined.replay_records import recovery_episodes

    journal, records = evidence_records()
    refs = records.recoveries[0].source_refs
    rows = tuple(replace(row, source_refs=refs) for row in recovery_episodes(trace_of(*SEQUENCE)))
    saved = replace(records, recoveries=rows)
    receipt = write_bundle(tmp_path, "recoveries", journal, {}, records=saved)
    bundle = read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)
    assert bundle.records == saved
    lines = (receipt.directory / "recoveries.jsonl").read_text().splitlines()
    kept = [json.loads(line)["record"] for line in lines]
    assert [(row["kind"], row["end_reason"]) for row in kept] == [
        ("liquidation", "liquidated"),
        ("cooldown", "restarted"),
        ("episode", "episode_stop"),
        ("cooldown", "restarted"),
        ("episode", "normal_restored"),
    ]


def rewrite_record(directory, name, change):
    path = directory / name
    rows = [json.loads(row) for row in path.read_text().splitlines()]
    change(rows[0])
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    rehash(directory, name)


@pytest.mark.parametrize(
    "name,change",
    [
        ("assessments.jsonl", lambda row: row.update(schema="combined-v2")),
        ("assessments.jsonl", lambda row: row["record"].update(close=114.4)),
        ("assessments.jsonl", lambda row: row["record"].update(daily="sideways")),
        ("assessments.jsonl", lambda row: row["record"].update(hourly_gaps=[[0, 3_600_000]])),
        ("run.jsonl", lambda row: row["record"].update(source_refs=["sha256:other"])),
        ("run.jsonl", lambda row: row["record"].update(issues=[""])),
        ("symbol_gaps.jsonl", lambda row: row["record"].update(symbol="ETHUSDT")),
        ("intents.jsonl", lambda row: row["record"].update(extra="field")),
        ("intents.jsonl", lambda row: row["record"].update(assessment_id="assessment:other")),
        ("decision_records.jsonl", lambda row: row["record"].update(accepted=1)),
        ("decision_records.jsonl", lambda row: row["record"].update(spot_fee_rate="NaN")),
        ("decision_records.jsonl", lambda row: row["record"].update(opportunity_id="unknown")),
        ("lifecycles.jsonl", lambda row: row["record"].update(gross_pnl="1e2")),
        ("recoveries.jsonl", lambda row: row["record"].pop("end_ms")),
        ("recoveries.jsonl", lambda row: row["record"].pop("kind")),
        ("recoveries.jsonl", lambda row: row["record"].update(kind="pause")),
        ("recoveries.jsonl", lambda row: row["record"].update(end_reason=3)),
    ],
)
def test_valid_hashes_do_not_bypass_record_validation(tmp_path, name, change):
    journal, records = evidence_records()
    receipt = write_bundle(tmp_path, "records", journal, {}, records=records)
    rewrite_record(receipt.directory, name, change)
    with pytest.raises(ValueError):
        read_bundle(receipt.directory)


def test_exactly_one_run_record_is_required(tmp_path):
    journal, records = evidence_records()
    receipt = write_bundle(tmp_path, "runs", journal, {}, records=records)
    path = receipt.directory / "run.jsonl"
    path.write_bytes(path.read_bytes() * 2)
    rehash(receipt.directory, "run.jsonl")
    with pytest.raises(ValueError, match="run record"):
        read_bundle(receipt.directory)


def test_a_partial_record_set_is_rejected(tmp_path):
    journal, records = evidence_records()
    receipt = write_bundle(tmp_path, "partial", journal, {}, records=records)
    (receipt.directory / "recoveries.jsonl").unlink()
    path = receipt.directory / "receipt.json"
    data = json.loads(path.read_text())
    del data["files"]["recoveries.jsonl"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="record"):
        read_bundle(receipt.directory)


def test_records_must_reference_their_assessment_and_funnel_before_writing(tmp_path):
    journal, records = evidence_records()
    with pytest.raises(ValueError):
        write_bundle(tmp_path, "dangling", journal, {}, records=replace(records, assessments=()))
    with pytest.raises(ValueError):
        write_bundle(tmp_path, "unjournaled", Evidence(), {}, records=records)
    duplicated = replace(records, lifecycles=records.lifecycles * 2)
    with pytest.raises(ValueError):
        write_bundle(tmp_path, "duplicate", journal, {}, records=duplicated)
    # The run's sources are cited by digest, never repeated in a record.
    repeated = replace(
        records,
        recoveries=(replace(records.recoveries[0], source_refs=records.run.source_refs),),
    )
    with pytest.raises(ValueError, match="digest"):
        write_bundle(tmp_path, "repeated", journal, {}, records=repeated)
    # An assessment's gaps live in its symbol's gap table.
    gapped = replace(records.assessments[0], daily_gaps=((0, 86_400_000),))
    with pytest.raises(ValueError, match="gap table"):
        write_bundle(
            tmp_path, "gapped", journal, {}, records=replace(records, assessments=(gapped,))
        )
    assert list(tmp_path.iterdir()) == []
