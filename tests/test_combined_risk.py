"""Shared pending reservations must count before another strategy can submit."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.combined.risk import Exposure, Intent, PortfolioRisk, PortfolioView


def intent(key="one", symbol="BTCUSDT", **changes):
    return replace(
        Intent(
            key,
            symbol,
            "spot_trend",
            "spot",
            1,
            D(100),
            D(98),
            D(100),
            D("0.001"),
            D("0.0005"),
            D("0.001"),
            D(0),
            D(1000),
            D(5),
            "unknown",
        ),
        **changes,
    )


def view(**changes):
    return replace(PortfolioView(D(10000), D(10000), (), D(1)), **changes)


def test_extended_entry_halves_stop_risk_before_recovery_scaling():
    answer = PortfolioRisk().reserve(intent(risk_multiplier=D("0.5")), view())
    assert answer.accepted and answer.risk <= 25
    recovered = PortfolioRisk().reserve(
        intent(risk_multiplier=D("0.5")), view(risk_fraction=D("0.25"))
    )
    assert recovered.risk <= D("6.25")
    with pytest.raises(ValueError):
        PortfolioRisk().reserve(intent(risk_multiplier=D(2)), view())


def test_asset_cap_and_fee_reserve_limit_size():
    answer = PortfolioRisk().reserve(intent(), view())
    assert answer.quantity == D("19.990")
    assert answer.cash == D("2004.93704999")
    assert answer.risk == D("45.91704999")
    assert answer.accepted


def test_pending_owner_prevents_spot_futures_duplicate():
    book = PortfolioRisk()
    book.reserve(intent(), view())
    other = book.reserve(intent("two", venue="futures", owner="futures_trend"), view())
    assert not other.accepted
    assert other.reason == "asset_owned"


def test_pending_cash_cannot_be_spent_twice():
    book = PortfolioRisk()
    first = book.reserve(intent(), view(free_cash=D(100)))
    second = book.reserve(intent("two", "ETHUSDT"), view(free_cash=D(100)))
    assert first.cash <= 100
    assert not second.accepted
    assert first.cash + second.cash <= 100


def test_unknown_correlation_groups_all_assets_together():
    book = PortfolioRisk()
    answers = [
        book.reserve(intent(str(i), symbol, slippage_rate=D(0)), view())
        for i, symbol in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"))
    ]
    assert sum(a.notional for a in answers) <= 8000
    assert not answers[-1].accepted
    assert answers[-1].reason == "portfolio_capacity"


def test_recovery_quarters_even_asset_capped_size():
    answer = PortfolioRisk().reserve(intent(slippage_rate=D(0)), view(risk_fraction=D("0.25")))
    assert answer.quantity == 5
    assert answer.notional == 500


def test_minimum_notional_never_rounded_up_to_spend_more_risk():
    answer = PortfolioRisk().reserve(
        intent(min_notional=D(25)), view(equity=D(100), free_cash=D(100))
    )
    assert not answer.accepted
    assert answer.reason == "below_minimum"


def test_futures_short_funding_and_margin_admission():
    candidate = intent(
        venue="futures",
        owner="futures_trend",
        side=-1,
        stop=D(102),
        funding_rate=D("-0.01"),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    refused = PortfolioRisk().reserve(candidate, view())
    assert refused.reason == "adverse_funding"
    accepted = PortfolioRisk().reserve(replace(candidate, funding_rate=D("0.0001")), view())
    assert accepted.accepted
    assert accepted.cash == D("1006.06002")


@pytest.mark.parametrize(
    "changes",
    [
        dict(funding_rate=None),
        dict(funding_age_ms=-1),
        dict(funding_age_ms=28_800_001),
        dict(funding_interval_ms=14_400_000),
    ],
)
def test_futures_unknown_or_unsupported_funding_refused(changes):
    candidate = intent(
        venue="futures",
        owner="futures_trend",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    assert (
        PortfolioRisk().reserve(replace(candidate, **changes), view()).reason
        == "funding_unavailable"
    )


def test_funding_ablation_keeps_margin_safeguard():
    candidate = intent(
        venue="futures",
        owner="futures_trend",
        funding_rate=D("0.1"),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
        funding_admission=False,
        maintenance_rate=D("0.2"),
    )
    assert PortfolioRisk().reserve(candidate, view()).reason == "margin_buffer"


def test_existing_dust_still_owns_asset_and_consumes_risk():
    held = Exposure("BTCUSDT", "spot_grid", D("0.01"), D("0.001"), "unknown")
    assert PortfolioRisk().reserve(intent(), view(exposures=(held,))).reason == "asset_owned"


def test_release_requires_acknowledgement_and_id_reuse_cannot_double_submit():
    book = PortfolioRisk()
    first = book.reserve(intent(), view())
    assert book.reserve(intent(), view()) == first
    with pytest.raises(ValueError):
        book.release("one", acknowledged=False)
    assert book.reserve(intent("two"), view()).reason == "asset_owned"
    book.release("one", acknowledged=True)
    assert book.reserve(intent(), view()) == first
    assert book.reserve(intent("three"), view()).accepted


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D(-1)])
def test_invalid_capital_is_rejected_without_mutation(bad):
    book = PortfolioRisk()
    with pytest.raises(ValueError):
        book.reserve(intent(), view(equity=bad))
    assert book.reserve(intent(), view()).accepted


def test_zero_risk_fraction_blocks_increase():
    assert PortfolioRisk().reserve(intent(), view(risk_fraction=D(0))).reason == "risk_halted"


def test_strategy_cannot_invent_a_correlation_group_to_bypass_shared_cap():
    with pytest.raises(ValueError, match="correlation"):
        PortfolioRisk().reserve(intent(correlation_group="made-up"), view())


def test_partial_fill_ack_releases_only_remaining_fraction():
    book = PortfolioRisk()
    first = book.reserve(intent(slippage_rate=D(0)), view())
    with pytest.raises(ValueError):
        book.acknowledge_remaining("one", D(10), acknowledged=False)
    book.acknowledge_remaining("one", D(10), acknowledged=True)
    assert book.reservations[0].cash == first.cash / 2
    assert book.reservations[0].risk == first.risk / 2
    with pytest.raises(ValueError):
        book.acknowledge_remaining("one", D(11), acknowledged=True)
    assert book.reserve(intent("two"), view()).reason == "asset_owned"


def test_two_concurrent_strategies_cannot_reserve_same_cash():
    from concurrent.futures import ThreadPoolExecutor

    book = PortfolioRisk()
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(
            pool.map(
                lambda candidate: book.reserve(candidate, view(free_cash=D(100))),
                [intent(), intent("two", "ETHUSDT")],
            )
        )
    assert sum(a.cash for a in answers) <= 100
    assert sum(a.accepted for a in answers) == 1


@pytest.mark.parametrize("slippage", [D(0), D("0.01")])
def test_short_stop_execution_costs_stay_within_asset_risk(slippage):
    candidate = intent(
        venue="futures",
        owner="futures_trend",
        side=-1,
        stop=D(150),
        fee_rate=D("0.01"),
        slippage_rate=slippage,
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    answer = PortfolioRisk().reserve(candidate, view())
    entry = D(100) * (1 - slippage)
    exit_price = D(150) * (1 + slippage)
    actual_risk = answer.quantity * (exit_price - entry + (entry + exit_price) * D("0.01"))
    assert answer.accepted
    assert actual_risk <= D(50)
    assert answer.risk >= actual_risk


@pytest.mark.parametrize("venue", ["spot", "futures"])
def test_cash_keeps_entry_and_stop_exit_fees_reserved(venue):
    candidate = intent(
        venue=venue,
        owner="spot_trend" if venue == "spot" else "futures_trend",
        stop=D(99),
        fee_rate=D("0.01"),
        slippage_rate=D(0),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    account = view(free_cash=D(1010))
    answer = PortfolioRisk().reserve(candidate, account)
    principal = D(100) if venue == "spot" else D(50)
    required = answer.quantity * (principal + D(1) + D("0.99"))
    assert answer.accepted
    assert answer.cash >= required
    assert required <= account.free_cash


def test_expected_buy_execution_notional_respects_asset_cap():
    answer = PortfolioRisk().reserve(intent(), view())
    assert answer.accepted
    execution_notional = answer.quantity * D("100.05")
    assert execution_notional <= D(2000)
    assert answer.notional >= execution_notional


def test_short_minimum_notional_uses_adverse_sell_execution_price():
    candidate = intent(
        venue="futures",
        owner="futures_trend",
        side=-1,
        stop=D(102),
        requested_quantity=D(1),
        min_notional=D(100),
        slippage_rate=D("0.01"),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    answer = PortfolioRisk().reserve(candidate, view())
    assert not answer.accepted
    assert answer.reason == "below_minimum"
