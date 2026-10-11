import json
from dataclasses import asdict, replace
from decimal import Decimal as D

import pytest
from test_combined_engine import QUOTES, RULES, candidate
from test_combined_risk import intent

from crypto_grid_bot.combined.account import FillEvent, FundingEvent
from crypto_grid_bot.combined.artifacts import read_bundle, write_bundle
from crypto_grid_bot.combined.engine import PortfolioEngine
from crypto_grid_bot.combined.evidence import Evidence
from crypto_grid_bot.combined.replay_events import SettledBatch, replay_events


def batch(key="a", time=1, **changes):
    return replace(
        SettledBatch(
            key, time, tuple(QUOTES.items()), tuple(RULES.items()), source_refs=("fixture",)
        ),
        **changes,
    )


def test_replay_retains_prefix_and_does_not_count_duplicates():
    result = replay_events(PortfolioEngine(D(10000)), (batch(), batch(), batch("b", 2)))
    assert len(result.snapshots) == 2
    assert result.duplicate_ids == ("a",)
    assert result.failure is None


def test_invalid_suffix_preserves_prefix_and_stops_without_retry():
    first = replay_events(PortfolioEngine(D(10000)), (batch(),))
    result = replay_events(
        PortfolioEngine(D(10000)),
        (batch(), batch("bad", 1735689600000), batch("remaining", 1735689600001)),
    )
    assert result.snapshots == first.snapshots
    assert result.failure.batch_id == "bad"
    assert result.unprocessed_ids == ("remaining",)


def test_conflicting_duplicate_and_backwards_event_stop():
    for bad in (batch("a", 2), batch("b", 0)):
        result = replay_events(PortfolioEngine(D(10000)), (batch(), bad))
        assert result.failure is not None and len(result.snapshots) == 1
        assert result.failure.source_refs == ()


def test_failed_settlement_preserves_booked_funding_and_integrity_failure(tmp_path):
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28800000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0))
    first = batch(increases=((order.intent_id, fill),))
    bad = batch(
        "bad",
        2,
        funding=(FundingEvent("funding", 2, "BTCUSDT", D(-2)),),
        increases=(("unknown", replace(fill, event_id="invalid", timestamp_ms=2)),),
        source_refs=("synthetic:funding-ledger:2", "synthetic:execution:invalid"),
    )
    result = replay_events(engine, (first, bad, batch("remaining", 3)))
    assert result.failure is not None
    assert result.failure.terminal_snapshot.account.equity == 9998
    assert "execution_integrity_failure" in result.failure.terminal_snapshot.reasons
    assert result.unprocessed_ids == ("remaining",)
    assert len(result.snapshots) == 1
    assert result.failure.source_refs == bad.source_refs
    metadata = json.loads(json.dumps(asdict(result), default=str))
    receipt = write_bundle(tmp_path, "failed-replay", Evidence(), metadata)
    saved = json.loads(read_bundle(receipt.directory).metadata_json)
    assert saved["failure"]["source_refs"] == list(bad.source_refs)
    assert saved["failure"]["batch_id"] == "bad"
    assert saved["failure"]["terminal_snapshot"]["account"]["equity"] == "9998"
    assert saved["snapshots"][0]["source_refs"] == ["fixture"]


def test_missing_sources_and_duplicate_quote_names_stop_at_reached_batch():
    for bad in (batch("bad", 2, source_refs=()), batch("bad", 2, quotes=tuple(QUOTES.items()) * 2)):
        result = replay_events(PortfolioEngine(D(10000)), (batch(), bad))
        assert len(result.snapshots) == 1 and result.failure is not None
        assert result.failure.terminal_snapshot is None
        assert result.failure.terminal_unavailable_reason


def test_funding_before_reduction_retains_exact_final_wallet():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28800000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0))
    result = replay_events(
        engine,
        (
            batch(increases=((order.intent_id, fill),)),
            batch(
                "exit",
                2,
                funding=(FundingEvent("funding", 2, "BTCUSDT", D(-2)),),
                reductions=(replace(fill, event_id="close", timestamp_ms=2, side=-1),),
            ),
        ),
    )
    assert result.failure is None
    assert result.snapshots[-1].snapshot.account.equity == 9998
    assert result.snapshots[-1].snapshot.account.positions == ()


def test_duplicate_after_later_batch_does_not_rewind_or_create_sample():
    result = replay_events(PortfolioEngine(D(10000)), (batch(), batch("b", 2), batch()))
    assert result.failure is None
    assert [row.snapshot.timestamp_ms for row in result.snapshots] == [1, 2]


def test_reserved_input_never_touches_engine():
    engine = PortfolioEngine(D(10000))
    result = replay_events(engine, (batch("reserved", 1735689600000),))
    assert result.failure and result.failure.terminal_snapshot is None
    assert replay_events(engine, (batch(),)).failure is None


def test_malformed_reached_batches_preserve_prefix_and_safe_suffix_identities():
    for malformed in (None, batch("bad", 2, batch_id=[])):
        result = replay_events(
            PortfolioEngine(D(10000)), (batch(), malformed, None, batch("later", 3))
        )
        assert len(result.snapshots) == 1
        assert result.failure is not None
        assert result.failure.batch_id == "<unavailable:1>"
        assert result.unprocessed_ids == ("<unavailable:2>", "later")


def test_malformed_suffix_does_not_affect_earlier_failure_evidence():
    result = replay_events(PortfolioEngine(D(10000)), (batch(), batch("bad", 1735689600000), None))
    assert len(result.snapshots) == 1
    assert result.failure.batch_id == "bad"
    assert result.unprocessed_ids == ("<unavailable:2>",)


def test_malformed_quote_symbol_preserves_valid_prefix():
    result = replay_events(
        PortfolioEngine(D(10000)),
        (batch(), batch("bad", 2, quotes=((None, next(iter(QUOTES.values()))),))),
    )
    assert len(result.snapshots) == 1 and result.failure is not None


def test_valid_funding_before_malformed_funding_preserves_wallet_and_failure():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28800000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0))
    result = replay_events(
        engine,
        (
            batch(increases=((order.intent_id, fill),)),
            batch(
                "bad",
                2,
                funding=(
                    FundingEvent("valid", 2, "BTCUSDT", D(-2)),
                    FundingEvent("invalid", 2, None, D(-2)),
                ),
            ),
        ),
    )
    assert len(result.snapshots) == 1
    assert result.failure.terminal_snapshot.account.equity == 9998
    assert "execution_integrity_failure" in result.failure.terminal_snapshot.reasons


@pytest.mark.parametrize("refs", [(), ("",), ["unvalidated"], "unvalidated", (None,)])
def test_invalid_failure_sources_are_not_promoted(refs):
    result = replay_events(PortfolioEngine(D(10000)), (batch("bad", source_refs=refs),))
    assert result.failure is not None
    assert result.failure.source_refs == ()
    assert result.failure.terminal_snapshot is None


def test_other_validation_failure_does_not_promote_unchecked_sources():
    result = replay_events(
        PortfolioEngine(D(10000)),
        (batch("bad", quotes=tuple(QUOTES.items()) * 2, source_refs=("unchecked",)),),
    )
    assert result.failure.source_refs == ()


def test_attempted_failure_retains_sources_when_terminal_observation_unavailable():
    class BrokenTerminalEngine(PortfolioEngine):
        unavailable = False

        def settle(self, *args, **kwargs):
            try:
                return super().settle(*args, **kwargs)
            finally:
                self.unavailable = True

        def observe(self, *args, **kwargs):
            if self.unavailable:
                raise ValueError("synthetic terminal observation unavailable")
            return super().observe(*args, **kwargs)

    engine = BrokenTerminalEngine(D(10000))
    fill = FillEvent("unknown", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    failed = batch(increases=(("unknown", fill),), source_refs=("synthetic:failed-event",))
    result = replay_events(engine, (failed,))
    assert result.failure.source_refs == failed.source_refs
    assert result.failure.terminal_snapshot is None
    assert (
        result.failure.terminal_unavailable_reason == "synthetic terminal observation unavailable"
    )


def test_engineering_failure_snapshot_and_failure_keep_same_batch_sources():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("adverse", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(150), D(0))
    failed = batch(increases=((order.intent_id, fill),), source_refs=("synthetic:adverse-fill",))
    result = replay_events(engine, (failed,))
    assert len(result.snapshots) == 1
    assert result.failure.source_refs == result.snapshots[0].source_refs == failed.source_refs
    assert result.failure.reason == "settled snapshot reports engineering failure"
