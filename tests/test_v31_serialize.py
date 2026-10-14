"""Exact JSON for V3.1 cell outcomes and reports: what a run job writes, aggregation reads.

The outcome and report come from a tiny synthetic replay (``combined_market_fixtures``),
never market data, so every nested type the codec meets is a real one.
"""

import json
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction

import combined_market_fixtures as fx
import pytest

from crypto_grid_bot.combined.driver.serialize import (
    decode_outcome,
    decode_report,
    encode_outcome,
    encode_report,
)
from crypto_grid_bot.combined.experiment import RunIdentity
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.combined.outcomes import strategy_outcome
from crypto_grid_bot.combined.replay_records import strategy_report
from crypto_grid_bot.combined.strategy_replay import replay_strategy

PIN = "5" * 64
DAYS = 2


@pytest.fixture(scope="module")
def replayed():
    """One combined replay over two synthetic coins, its report and two outcomes: a
    research identity and a small one (the codec judges no capital)."""
    markets = (
        fx.market("BTCUSDT", fx.uptrend, DAYS, futures=True, flow=True),
        fx.market("ETHUSDT", fx.downtrend, DAYS, futures=True, flow=True),
    )
    trace = replay_strategy(fx.run("combined", DAYS), markets)
    skipped = (fx.START + 5 * fx.HOUR,)
    report = strategy_report(
        trace, adapter_pin=PIN, skipped_hours=skipped, capital_label="research_10000_usdt"
    )
    identity = RunIdentity(
        arm="combined",
        window="w1",
        capital="research",
        cost_multiple=1,
        data_pin="1" * 64,
        cost_profile_pin="2" * 64,
        start_ms=fx.START,
        end_ms=fx.START + DAYS * fx.DAY,
        code_pin="4" * 40,
        config_pin="3" * 64,
        observation_policy=POLICY_ID,
        adapter_pin=PIN,
        scenario="open_low_high_close",
    )
    owner = replace(identity, capital="small")
    return (
        report,
        strategy_outcome(trace, report, identity, attempt_id="attempt-1"),
        strategy_outcome(trace, report, owner, attempt_id="attempt-2"),
    )


def canonical(text: str) -> str:
    return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def test_outcome_and_report_round_trip_exactly(replayed):
    report, research, owner = replayed
    # Not a stub: the replay traded, and the report carries every kind of nested value.
    assert report.contributions and report.equity_points and report.policy_evidence
    assert report.skipped_hours and report.disclosures and report.drawdown_episodes
    assert isinstance(report.max_gross_leverage, Fraction)
    assert research.report_evidence is not None

    for outcome in (research, owner):
        text = encode_outcome(outcome)
        assert text == canonical(text)  # sorted keys, no spaces, ASCII
        decoded = decode_outcome(text)
        assert decoded == outcome
        assert decoded.report_evidence == outcome.report_evidence
        assert encode_outcome(decoded) == text
        # No capital converts a currency (owner decision, 2026-10-14): no FX pin is written.
        assert '"fx_pin"' not in text
    assert decode_outcome(encode_outcome(owner)).identity.capital == "small"
    # An identity still holding the replaced FX pin is not this codec's: refused.
    with_fx = json.loads(encode_outcome(owner))
    with_fx["outcome"]["identity"]["fx_pin"] = None
    with pytest.raises(ValueError, match="unexpected fields: fx_pin"):
        decode_outcome(canonical(json.dumps(with_fx)))

    text = encode_report(report)
    assert text == canonical(text)
    decoded = decode_report(text)
    assert decoded == report and encode_report(decoded) == text
    # Tuples stay tuples, Decimals keep their exact digits, the Fraction stays exact.
    assert isinstance(decoded.equity_points, tuple)
    assert isinstance(decoded.equity_points[0].source_refs, tuple)
    assert isinstance(decoded.exit_reason_counts, tuple)
    assert decoded.max_gross_leverage == report.max_gross_leverage
    assert [str(p.equity) for p in decoded.equity_points] == [
        str(p.equity) for p in report.equity_points
    ]
    # Money is written as strings, never as JSON numbers.
    assert '"initial_equity":"10000"' in text
    leverage = report.max_gross_leverage
    assert f'"max_gross_leverage":"{leverage.numerator}/{leverage.denominator}"' in text


def test_encoding_is_deterministic(replayed):
    report, research, _ = replayed
    assert encode_outcome(research) == encode_outcome(replace(research))
    assert encode_report(report) == encode_report(decode_report(encode_report(report)))


def test_an_outcome_without_report_values_carries_nan_in_its_three_fields(replayed):
    _, research, _ = replayed
    nan = D("NaN")
    failed = replace(
        research,
        final_equity=nan,
        max_drawdown=nan,
        accounting_residual=nan,
        failed=True,
        complete=False,
    )
    text = encode_outcome(failed)
    assert '"final_equity":"NaN"' in text and '"accounting_residual":"NaN"' in text
    decoded = decode_outcome(text)
    assert decoded.final_equity.is_qnan() and decoded.max_drawdown.is_qnan()
    assert decoded.accounting_residual.is_qnan()
    assert encode_outcome(decoded) == text  # NaN != NaN, so compare the exact text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda o: replace(o, liquidations=True), "integer"),
        (lambda o: replace(o, disclosures=list(o.disclosures)), "tuple"),
        (lambda o: replace(o, initial_equity=10000.0), "Decimal"),
        (lambda o: replace(o, initial_equity=D("NaN")), "finite"),
        (lambda o: replace(o, final_equity=D("Infinity")), "finite"),
        (lambda o: replace(o, final_equity=D("sNaN")), "finite"),
        (lambda o: replace(o, attempt_id=None), "string"),
    ],
)
def test_encode_refuses_values_the_json_cannot_hold_exactly(replayed, change, message):
    _, research, _ = replayed
    with pytest.raises(ValueError, match=message):
        encode_outcome(change(research))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"liquidations":0', '"liquidations":0.0', "JSON float"),
        ('"liquidations":0', '"liquidations":NaN', "JSON float"),
        ('"liquidations":0', '"liquidations":0,"liquidations":0', "duplicate JSON key"),
        ('"liquidations":0', '"liquidations":false', "integer"),
        ('"liquidations":0', '"extra":1,"liquidations":0', "fields"),
        ('"initial_equity":"10000",', "", "fields"),
        ('"initial_equity":"10000"', '"initial_equity":10000', "Decimal"),
        ('"initial_equity":"10000"', '"initial_equity":"1_0000"', "Decimal"),
        ('"initial_equity":"10000"', '"initial_equity":"NaN"', "finite"),
        ('"schema":"v3.1-outcome-1"', '"schema":"v3.1-outcome-0"', "schema"),
    ],
)
def test_decode_refuses_anything_but_the_exact_encoding(replayed, old, new, message):
    _, research, _ = replayed
    text = encode_outcome(research)
    assert old in text
    with pytest.raises(ValueError, match=message):
        decode_outcome(text.replace(old, new, 1))


def test_decode_refuses_non_canonical_text_and_the_other_document(replayed):
    report, research, _ = replayed
    text = encode_outcome(research)
    with pytest.raises(ValueError, match="canonical"):
        decode_outcome(json.dumps(json.loads(text), indent=1, sort_keys=True))
    with pytest.raises(ValueError, match="canonical"):
        decode_outcome(text + "\n")
    with pytest.raises(ValueError, match="schema"):
        decode_report(text)
    with pytest.raises(ValueError, match="schema"):
        decode_outcome(encode_report(report))
    with pytest.raises(ValueError, match="text"):
        decode_outcome(text.encode("ascii"))
