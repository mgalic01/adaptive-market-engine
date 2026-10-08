"""Immutable attempt records survive reopen without inventing completion."""

from decimal import Decimal

import pytest


def test_started_identity_survives_reopen_and_finish(tmp_path):
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    journal = EvidenceJournal(tmp_path)
    journal.record("trial-1", "started", {"cash": Decimal("0.000000000000000001")})
    assert EvidenceJournal(tmp_path).pending() == ("trial-1",)
    journal.record("trial-1", "finished", {"outcome": "invalid"})
    assert EvidenceJournal(tmp_path).pending() == ()
    assert "1E-18" in (tmp_path / "trial-1.started.json").read_text()


def test_refuses_overwrite_and_finish_without_start(tmp_path):
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    j = EvidenceJournal(tmp_path)
    with pytest.raises(ValueError, match="start"):
        j.record("missing", "finished", {})
    j.record("one", "started", {"a": 1})
    before = (tmp_path / "one.started.json").read_bytes()
    with pytest.raises(FileExistsError):
        j.record("one", "started", {"a": 2})
    assert (tmp_path / "one.started.json").read_bytes() == before


@pytest.mark.parametrize("value", [1.2, Decimal("NaN")])
def test_bad_numeric_evidence_does_not_publish_a_record(tmp_path, value):
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    j = EvidenceJournal(tmp_path)
    with pytest.raises(ValueError):
        j.record("one", "started", {"value": value})
    assert list(tmp_path.iterdir()) == []


def test_unsafe_id_and_corrupt_record_are_rejected(tmp_path):
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    j = EvidenceJournal(tmp_path)
    with pytest.raises(ValueError):
        j.record("../escape", "started", {})
    (tmp_path / "one.started.json").write_text("{")
    with pytest.raises(ValueError):
        j.pending()


def test_failed_finish_publication_keeps_attempt_pending(tmp_path, monkeypatch):
    import os

    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    j = EvidenceJournal(tmp_path)
    j.record("one", "started", {})

    def fail(*args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError):
        j.record("one", "finished", {})
    assert j.pending() == ("one",)
    assert len(list(tmp_path.iterdir())) == 1


def test_duplicate_json_keys_are_not_recovered_as_valid(tmp_path):
    from crypto_grid_bot.trend.evidence_journal import EvidenceJournal

    j = EvidenceJournal(tmp_path)
    (tmp_path / "one.started.json").write_text(
        '{"schema":1,"run_id":"wrong","run_id":"one","state":"started","payload":{}}'
    )
    with pytest.raises(ValueError, match="duplicate"):
        j.pending()
