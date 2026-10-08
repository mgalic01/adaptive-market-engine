"""Actual replay callbacks publish linked exact evidence after persisted starts."""

import hashlib
import json

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.orchestration import Attempt, replay_sensitivities


def test_callback_publishes_verified_artifacts_for_real_synthetic_replays(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    recorder = AttemptRecorder(tmp_path)
    t = 1609459200000
    outcomes = replay_sensitivities(
        DailyDecisions({}, {}), {}, {}, {}, {t: None}, t + 86400000, record=recorder
    )
    assert len(outcomes) == 5
    assert recorder.journal.pending() == ()
    for path in tmp_path.glob("*.finished.json"):
        doc = json.loads(path.read_text())["payload"]
        evidence = doc["evidence"]
        raw = (tmp_path / evidence["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == evidence["sha256"]
        rows = [json.loads(line) for line in raw.splitlines()]
        assert len(rows) == evidence["records"]
        assert len(raw) == evidence["bytes"]
        kinds = {row["kind"] for row in rows}
        assert {"outcome", "account", "hour", "audit", "equity", "sample"} <= kinds
        assert rows[0]["value"]["trade_reconciliation_residual"] == "0"


def test_finish_metadata_cannot_change_started_identity(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    with pytest.raises(ValueError, match="identity"):
        record(Attempt("one", "training", "R2", 0, 1, None, "failed"))
    assert record.journal.pending() == ("one",)


def test_error_without_replay_preserves_failed_attempt(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    record(Attempt("one", "training", "R1", 0, 1, None, "ArithmeticError: failed"))
    doc = json.loads((tmp_path / "one.finished.json").read_text())["payload"]
    assert doc["error"] == "ArithmeticError: failed"
    assert doc["evidence"] is None


def test_trade_and_funding_evidence_is_exact_and_tampering_is_detected(tmp_path):
    from decimal import Decimal as D

    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, verify_artifact
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.orchestration import reconcile_replay
    from crypto_grid_bot.trend.replay import ReplayResult
    from crypto_grid_bot.trend.runner import TrendRunner

    t = 1609459200000
    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = TrendRunner({"BTCUSDT": rules}, multiple=1)
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(t, bars, {"BTCUSDT": D(".1")}, {})
    runner.step(t + 3600000, bars, {}, {t + 3600000: {"BTCUSDT": D(".001")}})
    runner.finish({"BTCUSDT": D(100)})
    result = reconcile_replay(ReplayResult(runner, None, ()))
    record = AttemptRecorder(tmp_path)
    record(
        Attempt("trade", "training", "R1", t, t + 7200000, None, None, multiple=1, state="started")
    )
    record(Attempt("trade", "training", "R1", t, t + 7200000, result, None, multiple=1))
    metadata = json.loads((tmp_path / "trade.finished.json").read_text())["payload"]["evidence"]
    verify_artifact(tmp_path, metadata)
    raw = (tmp_path / metadata["path"]).read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert [row["value"]["quantity"] for row in rows if row["kind"] == "fill"] == ["10"]
    assert len([row for row in rows if row["kind"] == "funding"]) == 1
    (tmp_path / metadata["path"]).write_bytes(raw.replace(b"100", b"101", 1))
    with pytest.raises(ValueError, match="digest"):
        verify_artifact(tmp_path, metadata)
