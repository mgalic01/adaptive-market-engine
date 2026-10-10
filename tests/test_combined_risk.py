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


def test_asset_cap_and_fee_reserve_limit_size():
    answer = PortfolioRisk().reserve(intent(), view())
    assert answer.quantity == 20
    assert answer.cash == D("2003.001")
    assert answer.risk == D("46.002")
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
        book.reserve(intent(str(i), symbol), view())
        for i, symbol in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"))
    ]
    assert sum(a.notional for a in answers) <= 8000
    assert not answers[-1].accepted
    assert answers[-1].reason == "portfolio_capacity"


def test_recovery_quarters_even_asset_capped_size():
    answer = PortfolioRisk().reserve(intent(), view(risk_fraction=D("0.25")))
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
    assert accepted.cash == D("1003.001")


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
    first = book.reserve(intent(), view())
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
