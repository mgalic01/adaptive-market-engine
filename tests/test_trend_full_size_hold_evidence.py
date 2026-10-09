import json
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.filters import OrderFilters

START = month_bounds_ms("2024-10")[0]
HOUR = 3600000


def invoke(tmp_path, rows=None, end=None):
    from crypto_grid_bot.trend.full_size_hold_evidence import replay_full_size_hold_recorded

    limits = OrderFilters(*map(D, (".001", "100000", ".001", "5", ".001", "100000", ".001", "1")))
    return replay_full_size_hold_recorded(
        tmp_path,
        "hold",
        {"BTCUSDT": rows or []},
        {"BTCUSDT": "2023-01"},
        {"BTCUSDT": limits},
        START,
        end or START + 3 * HOUR,
    )


def test_unavailable_is_recorded_without_becoming_valid_or_strategy_failure(tmp_path):
    from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, verify_artifact

    result = invoke(tmp_path)
    finish = json.loads((tmp_path / "hold.finished.json").read_text())["payload"]
    assert finish["error"] is None
    assert finish["phase"] == "full_size_hold"
    verify_artifact(tmp_path, finish["evidence"])
    rows = [
        json.loads(line) for line in (tmp_path / "hold.evidence.jsonl").read_text().splitlines()
    ]
    outcome = next(row["value"] for row in rows if row["kind"] == "full_size_hold")
    assert outcome["reason"] == result.reason == "unavailable_first_purchase"
    assert outcome["missing_symbols"] == ["BTCUSDT"]
    assert outcome["cash"] == "10000"
    assert AttemptRecorder(tmp_path).journal.pending() == ()
    original = (tmp_path / "hold.evidence.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        invoke(tmp_path)
    assert (tmp_path / "hold.evidence.jsonl").read_bytes() == original


def test_late_error_preserves_partial_fills_without_terminal_sample(tmp_path):
    from crypto_grid_bot.trend.full_size_hold import FullSizeHoldExecutionError

    good = Kline(START + HOUR, *([D(100)] * 7))
    bad = Kline(START + 2 * HOUR, D(100), D(90), D(80), D(85), D(1), D(1), D(1))
    with pytest.raises(FullSizeHoldExecutionError):
        invoke(tmp_path, [good, bad])
    finish = json.loads((tmp_path / "hold.finished.json").read_text())["payload"]
    assert "invalid full-size hold bar" in finish["error"]
    rows = [
        json.loads(line) for line in (tmp_path / "hold.evidence.jsonl").read_text().splitlines()
    ]
    assert any(row["kind"] == "spot_fill" for row in rows)
    assert not any(row["kind"] == "equity" and row["value"]["kind"] == "terminal" for row in rows)


def test_invalid_preflight_is_recorded_without_invented_account(tmp_path):
    with pytest.raises(ValueError):
        invoke(tmp_path, end=START - HOUR)
    finish = json.loads((tmp_path / "hold.finished.json").read_text())["payload"]
    assert finish["evidence"] is None
    assert finish["error"]


@pytest.mark.parametrize("interrupt", [True, False])
def test_interruption_or_disk_failure_keeps_started_attempt_pending(
    tmp_path, monkeypatch, interrupt
):
    from crypto_grid_bot.trend import full_size_hold_evidence as writer
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    def broken(*args, **kwargs):
        if interrupt:
            raise KeyboardInterrupt()
        raise OSError("disk full")

    monkeypatch.setattr(
        writer, "replay_full_size_hold" if interrupt else "write_full_size_hold", broken
    )
    with pytest.raises(KeyboardInterrupt if interrupt else OSError):
        invoke(tmp_path)
    assert EvidenceJournal(tmp_path).pending() == ("hold",)
    assert not (tmp_path / "hold.finished.json").exists()
