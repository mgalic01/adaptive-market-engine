"""Spot evidence is exact, immutable and separate from an acceptance verdict."""

import json
from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.spot_benchmark import SpotRunner


def test_spot_artifact_retains_account_fills_audits_and_samples(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import verify_artifact, write_spot_replay

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = SpotRunner({"BTCUSDT": rules})
    for hour in range(3):
        runner.step(
            1609459200000 + hour * 3600000,
            {"BTCUSDT": (D(100), D(100), D(100))},
            {"BTCUSDT": D(".1")} if hour == 0 else {},
        )
    runner.finish({"BTCUSDT": D(100)})
    metadata = write_spot_replay(tmp_path, "spot", runner)
    verify_artifact(tmp_path, metadata)
    artifact = tmp_path / metadata["path"]
    raw = artifact.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    kinds = {row["kind"] for row in rows}
    assert {
        "spot_account",
        "spot_fill",
        "spot_audit",
        "spot_rebalance",
        "equity",
        "sample",
    } <= kinds
    account = next(row["value"] for row in rows if row["kind"] == "spot_account")
    assert D(account["cash"]) == runner.account.cash
    assert D(account["holdings"]["BTCUSDT"]) == runner.account.holdings["BTCUSDT"]
    assert account["stopped"] == "completed"
    fill = next(row["value"] for row in rows if row["kind"] == "spot_fill")
    assert D(fill["fee"]) == runner.account.fills[0].fee
    with pytest.raises(FileExistsError):
        write_spot_replay(tmp_path, "spot", runner)
    assert artifact.read_bytes() == raw


def test_spot_artifact_does_not_upgrade_partial_account_to_completed(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import write_spot_replay

    runner = SpotRunner({})
    runner.step(1609459200000, {})
    runner.stopped = "engine_failure"
    metadata = write_spot_replay(tmp_path, "failed", runner)
    rows = [json.loads(line) for line in (tmp_path / metadata["path"]).read_text().splitlines()]
    account = next(row["value"] for row in rows if row["kind"] == "spot_account")
    assert account["stopped"] == "engine_failure"
    assert not any(row["kind"] == "equity" and row["value"]["kind"] == "terminal" for row in rows)


def test_actual_spot_replay_retains_daily_decision_in_artifact(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import write_spot_replay
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, replay_spot_benchmark

    start = 1609459200000
    runner = replay_spot_benchmark(HoldDecisions({}, {}), {}, {}, start, start + 86400000)
    metadata = write_spot_replay(tmp_path, "decision", runner)
    rows = [json.loads(line) for line in (tmp_path / metadata["path"]).read_text().splitlines()]
    decisions = [row["value"] for row in rows if row["kind"] == "spot_decision"]
    assert len(decisions) == 1
    assert decisions[0]["timestamp_ms"] == start
    assert decisions[0]["decision"]["targets"] == {}
    assert decisions[0]["decision"]["sizing"]["flat_reason"] == "no_nonzero_raw_weights"


def test_recorded_spot_failure_retains_partial_runner_and_started_identity(tmp_path, monkeypatch):
    from crypto_grid_bot.trend.evidence_writer import replay_spot_recorded
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotReplayExecutionError

    start = 1609459200000
    original = SpotRunner.step

    def broken(self, hour, *args, **kwargs):
        assert (tmp_path / "partial.started.json").exists()
        if hour == start + 3600000:
            raise ArithmeticError("late synthetic failure")
        return original(self, hour, *args, **kwargs)

    monkeypatch.setattr(SpotRunner, "step", broken)
    with pytest.raises(SpotReplayExecutionError, match="late synthetic failure"):
        replay_spot_recorded(
            tmp_path, "partial", HoldDecisions({}, {}), {}, {}, start, start + 86400000
        )
    finish = json.loads((tmp_path / "partial.finished.json").read_text())["payload"]
    assert "late synthetic failure" in finish["error"]
    assert finish["phase"] == "spot_hold"
    rows = [
        json.loads(line)
        for line in (tmp_path / finish["evidence"]["path"]).read_text().splitlines()
    ]
    account = next(row["value"] for row in rows if row["kind"] == "spot_account")
    assert account["stopped"] == "engine_failure"
    assert not any(row["kind"] == "equity" and row["value"]["kind"] == "terminal" for row in rows)


def test_recorded_spot_success_links_immutable_artifact(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, replay_spot_recorded
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions

    start = 1609459200000
    runner = replay_spot_recorded(
        tmp_path, "ok", HoldDecisions({}, {}), {}, {}, start, start + 86400000
    )
    assert runner.stopped == "completed"
    finish = json.loads((tmp_path / "ok.finished.json").read_text())["payload"]
    assert finish["error"] is None
    assert finish["evidence"]["path"] == "ok.evidence.jsonl"
    assert AttemptRecorder(tmp_path).journal.pending() == ()


def test_recorded_spot_preflight_failure_is_error_without_fabricated_account(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import replay_spot_recorded
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions

    start = 1609459200000
    with pytest.raises(ValueError, match="cost multiple"):
        replay_spot_recorded(
            tmp_path, "bad", HoldDecisions({}, {}), {}, {}, start, start + 86400000, cost_multiple=3
        )
    finish = json.loads((tmp_path / "bad.finished.json").read_text())["payload"]
    assert finish["evidence"] is None
    assert "invalid cost multiple" in finish["error"]


@pytest.mark.parametrize("failure", ["interrupt", "publication"])
def test_recorded_spot_interruption_and_publication_failure_remain_pending(
    tmp_path, monkeypatch, failure
):
    from crypto_grid_bot.trend import evidence_writer as writer
    from crypto_grid_bot.trend import spot_benchmark as spot
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    def broken(*args, **kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt()
        raise OSError("synthetic disk full")

    if failure == "interrupt":
        monkeypatch.setattr(spot, "replay_spot_benchmark", broken)
    else:
        monkeypatch.setattr(writer, "write_spot_replay", broken)
    start = 1609459200000
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else OSError):
        writer.replay_spot_recorded(
            tmp_path, "pending", spot.HoldDecisions({}, {}), {}, {}, start, start + 86400000
        )
    assert EvidenceJournal(tmp_path).pending() == ("pending",)
    assert not (tmp_path / "pending.finished.json").exists()
