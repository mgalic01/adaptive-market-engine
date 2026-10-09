"""All twelve reported fixed-rule scenarios, with no market data."""

import pytest

from crypto_grid_bot.trend import orchestration as o
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.walk_forward import RULES

T, DAY = 1609459200000, 86400000


def test_twelve_rules_have_independent_accounts_and_persisted_fixed_schedules(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder

    records = []
    recorder = AttemptRecorder(tmp_path)

    def record(attempt):
        recorder(attempt)
        records.append(attempt)

    results = o.replay_fixed_rules(
        DailyDecisions({}, {}), {}, {}, {}, {T: "R2L"}, T + DAY, record=record
    )
    assert tuple(results) == RULES
    assert len({id(result.runner.account) for result in results.values()}) == 12
    assert len(records) == 24
    for rule, start, finish in zip(RULES, records[::2], records[1::2], strict=True):
        assert start.phase == finish.phase == "fixed_rule"
        assert start.rule == finish.rule == rule
        assert start.state == "started" and finish.state == "finished"
        assert start.pick_schedule == finish.pick_schedule == ((T, rule),)
        assert start.multiple == 2 and start.cost_multiple == 1
        assert start.run_id == finish.run_id
        assert finish.result.runner.stopped == "completed"

    assert len(list(tmp_path.glob("*.finished.json"))) == 12
    assert not AttemptRecorder(tmp_path).journal.pending()


def test_fixed_rule_interrupt_preserves_complete_schedule_before_execution(monkeypatch):
    records = []

    def interrupted(*args, **kwargs):
        assert len(records) == 1 and records[0].state == "started"
        assert records[0].pick_schedule == ((T, "R1"), (T + DAY, "R1"))
        raise KeyboardInterrupt()

    monkeypatch.setattr(o, "replay_window", interrupted)
    with pytest.raises(KeyboardInterrupt):
        o.replay_fixed_rules(
            DailyDecisions({}, {}),
            {},
            {},
            {},
            {T: "R3", T + DAY: None},
            T + 2 * DAY,
            record=records.append,
        )
    assert len(records) == 1


def test_fixed_rule_engine_failure_aborts_menu_and_records_failure(monkeypatch):
    records = []

    def broken(*args, **kwargs):
        raise ArithmeticError("bad account")

    monkeypatch.setattr(o, "replay_window", broken)
    with pytest.raises(ArithmeticError):
        o.replay_fixed_rules(
            DailyDecisions({}, {}), {}, {}, {}, {T: None}, T + DAY, record=records.append
        )
    assert len(records) == 2
    assert records[-1].error == "ArithmeticError: bad account"
    assert records[-1].rule == "R1"


@pytest.mark.parametrize("menu", [o.replay_fixed_rules, o.replay_sensitivities])
def test_both_menus_persist_partial_execution_failure(tmp_path, monkeypatch, menu):
    import json

    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder
    from crypto_grid_bot.trend.replay import ReplayExecutionError, ReplayResult
    from crypto_grid_bot.trend.runner import TrendRunner

    runner = TrendRunner({})
    runner.step(T, {}, {}, {})
    partial = ReplayResult(runner, "engine_failure", ())
    recorder, records = AttemptRecorder(tmp_path), []

    def record(attempt):
        recorder(attempt)
        records.append(attempt)

    def broken(*args, **kwargs):
        assert len(records) == 1 and records[0].state == "started"
        raise ReplayExecutionError(ArithmeticError("partial account failure"), partial)

    monkeypatch.setattr(o, "replay_window", broken)
    with pytest.raises(ReplayExecutionError):
        menu(DailyDecisions({}, {}), {}, {}, {}, {T: "R2"}, T + DAY, record=record)
    assert len(records) == 2
    assert records[-1].result is partial
    assert "partial account failure" in records[-1].error
    run_id = records[-1].run_id
    rows = [
        json.loads(line)
        for line in (tmp_path / f"{run_id}.evidence.jsonl").read_text().splitlines()
    ]
    assert any(row["kind"] == "hour" for row in rows)
    assert any(row["kind"] == "account" for row in rows)
    finish = json.loads((tmp_path / f"{run_id}.finished.json").read_text())
    assert finish["payload"]["evidence"] is not None
    assert "partial account failure" in finish["payload"]["error"]
    assert not AttemptRecorder(tmp_path).journal.pending()
