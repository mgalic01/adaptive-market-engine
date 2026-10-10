"""Verify the preserved holding receipt without external market data."""

import json
from pathlib import Path

from crypto_grid_bot.trend.evidence_journal import EvidenceJournal
from crypto_grid_bot.trend.evidence_writer import verify_artifact


def test_retained_holding_failure_receipt_resolves_and_verifies():
    root = (
        Path(__file__).resolve().parents[1]
        / "docs/backtests/v3-20261010-failed-invocation/attempts"
    )
    assert EvidenceJournal(root).pending() == ()
    run_id = "ee8e4da9b2f44b458a9bf340dc628b4c-hold-cost1"
    start = json.loads((root / f"{run_id}.started.json").read_bytes())
    finish = json.loads((root / f"{run_id}.finished.json").read_bytes())
    assert start["run_id"] == finish["run_id"] == run_id
    assert (
        finish["payload"]["error"]
        == "SpotReplayExecutionError: ValueError: positive value required"
    )
    verify_artifact(root, finish["payload"]["evidence"])
