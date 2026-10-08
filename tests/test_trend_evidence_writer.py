"""Actual replay callbacks publish linked exact evidence after persisted starts."""

import hashlib
import json

import pytest

from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.orchestration import Attempt, replay_sensitivities


@pytest.mark.parametrize("orphan", [False, True])
def test_explicit_recovery_retains_evidence_but_never_adopts_success(tmp_path, orphan):
    from crypto_grid_bot.trend.evidence_writer import (
        AttemptRecorder,
        recover_interrupted,
        write_replay,
    )
    from crypto_grid_bot.trend.replay import ReplayResult
    from crypto_grid_bot.trend.runner import TrendRunner

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    start = (tmp_path / "one.started.json").read_bytes()
    artifact = tmp_path / "one.evidence.jsonl"
    before = None
    if orphan:
        runner = TrendRunner({})
        runner.step(1609459200000, {}, {}, {})
        runner.finish({})
        write_replay(tmp_path, "one", ReplayResult(runner, None, ()))
        before = artifact.read_bytes()
    recover_interrupted(tmp_path, "one", reason="process terminated before finish publication")
    payload = json.loads((tmp_path / "one.finished.json").read_text())["payload"]
    assert payload["error"].startswith("InterruptedAttempt: outcome unconfirmed;")
    assert "process terminated" in payload["error"]
    assert (payload["evidence"] is not None) == orphan
    assert (tmp_path / "one.started.json").read_bytes() == start
    if orphan:
        assert artifact.read_bytes() == before
    assert AttemptRecorder(tmp_path).journal.pending() == ()
    with pytest.raises(ValueError, match="unfinished"):
        recover_interrupted(tmp_path, "one", reason="second recovery")


def test_explicit_recovery_refuses_malformed_orphan_and_empty_reason(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, recover_interrupted

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    with pytest.raises(ValueError, match="reason"):
        recover_interrupted(tmp_path, "one", reason=" ")
    (tmp_path / "one.evidence.jsonl").write_bytes(b'{"schema":1')
    with pytest.raises(ValueError, match="row"):
        recover_interrupted(tmp_path, "one", reason="interrupted")
    assert record.journal.pending() == ("one",)
    assert not (tmp_path / "one.finished.json").exists()


def test_reopen_rejects_artifact_arriving_after_no_evidence_recovery(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, recover_interrupted

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    recover_interrupted(tmp_path, "one", reason="worker confirmed stopped")
    (tmp_path / "one.evidence.jsonl").write_text('{"schema":1,"kind":"outcome","value":{}}\n')
    with pytest.raises(ValueError, match="unreferenced.*evidence"):
        AttemptRecorder(tmp_path)


def test_engine_failure_persists_partial_hour_evidence(tmp_path, monkeypatch):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder
    from crypto_grid_bot.trend.runner import TrendRunner

    t = 1609459200000
    original = TrendRunner.step

    def broken(self, stamp, *args, **kwargs):
        if stamp == t + 3600000:
            raise ArithmeticError("synthetic late failure")
        return original(self, stamp, *args, **kwargs)

    monkeypatch.setattr(TrendRunner, "step", broken)
    with pytest.raises(Exception, match="synthetic late failure"):
        replay_sensitivities(
            DailyDecisions({}, {}),
            {},
            {},
            {},
            {t: None},
            t + 86400000,
            record=AttemptRecorder(tmp_path),
        )
    finishes = list(tmp_path.glob("*.finished.json"))
    assert len(finishes) == 1
    payload = json.loads(finishes[0].read_text())["payload"]
    assert "synthetic late failure" in payload["error"]
    assert payload["evidence"] is not None
    rows = [
        json.loads(line)
        for line in (tmp_path / payload["evidence"]["path"]).read_text().splitlines()
    ]
    assert len([row for row in rows if row["kind"] == "hour"]) == 1
    account = next(row["value"] for row in rows if row["kind"] == "account")
    assert account["stopped"] == "engine_failure"


def test_reopening_pending_attempt_refuses_new_dispatch(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    with pytest.raises(ValueError, match="unfinished.*one"):
        AttemptRecorder(tmp_path)


@pytest.mark.parametrize("damage", ["missing", "truncated", "identity", "wrong_path"])
def test_reopening_validates_finished_evidence(tmp_path, damage):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    t = 1609459200000
    replay_sensitivities(DailyDecisions({}, {}), {}, {}, {}, {t: None}, t + 86400000, record=record)
    AttemptRecorder(tmp_path)  # Intact evidence can be reopened.
    finished = next(tmp_path.glob("*.finished.json"))
    doc = json.loads(finished.read_text())
    artifact = tmp_path / doc["payload"]["evidence"]["path"]
    if damage == "missing":
        artifact.unlink()
    elif damage == "truncated":
        artifact.write_bytes(artifact.read_bytes()[:-1])
    elif damage == "identity":
        doc["payload"]["multiple"] = 99
        finished.write_text(json.dumps(doc))
    else:
        other = next(p for p in tmp_path.glob("*.finished.json") if p != finished)
        doc["payload"]["evidence"] = json.loads(other.read_text())["payload"]["evidence"]
        finished.write_text(json.dumps(doc))
    with pytest.raises((ValueError, FileNotFoundError)):
        AttemptRecorder(tmp_path)


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
        assert doc["pick_schedule"] == [[t, None]]
        evidence = doc["evidence"]
        raw = (tmp_path / evidence["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == evidence["sha256"]
        rows = [json.loads(line) for line in raw.splitlines()]
        assert len(rows) == evidence["records"]
        assert len(raw) == evidence["bytes"]
        kinds = {row["kind"] for row in rows}
        assert {"outcome", "decision", "account", "hour", "audit", "equity", "sample"} <= kinds
        assert rows[0]["value"]["trade_reconciliation_residual"] == "0"


def test_finish_metadata_cannot_change_started_identity(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    record(Attempt("one", "training", "R1", 0, 1, None, None, state="started"))
    with pytest.raises(ValueError, match="identity"):
        record(Attempt("one", "training", "R2", 0, 1, None, "failed"))
    assert record.journal.pending() == ("one",)


def test_finish_cannot_change_started_pick_schedule(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    record = AttemptRecorder(tmp_path)
    record(
        Attempt(
            "one",
            "sensitivity",
            None,
            0,
            1,
            None,
            None,
            state="started",
            pick_schedule=((0, "R1"),),
        )
    )
    with pytest.raises(ValueError, match="identity"):
        record(
            Attempt("one", "sensitivity", None, 0, 1, None, "failed", pick_schedule=((0, "R2"),))
        )
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
