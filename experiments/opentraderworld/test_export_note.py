"""Checks for the disposable, one-artifact OTW feasibility probe."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "otw_probe", Path(__file__).with_name("export_note.py")
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def sample():
    return {
        "dataset": "SYNTHETIC <script>alert(1)</script>",
        "valid": False,
        "failures": ["SYNTHETIC accounting failure"],
        "excluded_pairs": {"SOLUSDT": ["SYNTHETIC exclusion"]},
        "code_commit": "a" * 40,
        "fees": {"maker": "0", "taker": "0.0009"},
        "results": [
            {
                "symbol": "BTCUSDT",
                "strategy": "SYNTHETIC benchmark D",
                "path_mode": "high_first",
                "return_pct": "-1.234567890123456789",
                "max_drawdown_pct": "12.5",
                "buy_and_hold_return_pct": "-3",
                "active_max_drawdown_pct": "13",
                "accounting_problems": ["mismatch"],
                "final_exit_blocked": "incomplete",
                "hourly_equity": [[0, "100", "100"]],
            }
        ],
    }


def test_note_preserves_failures_exclusions_precision_and_benchmark_identity():
    note = probe.note_text(sample())
    for text in (
        "INVALID",
        "SYNTHETIC exclusion",
        "mismatch",
        "incomplete",
        "-1.234567890123456789",
        "SYNTHETIC benchmark D",
    ):
        assert text in note
    assert "hourly_equity" not in note
    assert "does not mean" in note
    assert "ROW OVERVIEW" in note
    assert "Strategy return: -1.234567890123456789%" in note


def test_editor_payload_is_literal_text_and_preview_escapes_html():
    note = probe.note_text(sample())
    payload = probe.editor_payload(note)
    assert payload["content"]["content"][0]["content"][0] == {"type": "text", "text": note}
    preview = probe.preview_html(note)
    assert "<script>" not in preview
    assert "&lt;script&gt;" in preview


def test_changed_source_fails_before_creating_output(tmp_path):
    source = tmp_path / "results.json"
    source.write_text(json.dumps(sample()), encoding="utf-8")
    out = tmp_path / "bundle"
    with pytest.raises(ValueError, match="SHA-256"):
        probe.export(source, out)
    assert not out.exists()


def test_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "results.json"
    raw = json.dumps(sample()).encode()
    source.write_bytes(raw)
    monkeypatch.setattr(probe, "EXPECTED_SHA256", hashlib.sha256(raw).hexdigest())
    out = tmp_path / "bundle"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        probe.export(source, out)
    assert sentinel.read_text() == "keep"


def test_bundle_keeps_exact_source_and_hashes_every_view(tmp_path, monkeypatch):
    source = tmp_path / "results.json"
    raw = json.dumps(sample()).encode()
    source.write_bytes(raw)
    monkeypatch.setattr(probe, "EXPECTED_SHA256", hashlib.sha256(raw).hexdigest())
    out = tmp_path / "bundle"
    probe.export(source, out)
    assert (out / "results.json").read_bytes() == raw
    manifest = json.loads((out / "bundle.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert manifest["source_sha256"] == hashlib.sha256(raw).hexdigest()
