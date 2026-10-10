from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.correlation import correlation_groups

D = Decimal
DAY = 86_400_000
X = [D(v) / 100 for v in (1, -1, 1, -1)] * 15
Z = [D(v) / 100 for v in (1, 1, -1, -1)] * 15


def bars(returns: list[Decimal], offset: int = 0) -> list[Kline]:
    with localcontext() as context:
        context.prec = 2000
        price = D(100)
        result = [Kline(offset, price, price, price, price, D(1), D(1), D(".5"))]
        for i, change in enumerate(returns, 1):
            price *= 1 + change
            result.append(Kline(offset + i * DAY, price, price, price, price, D(1), D(1), D(".5")))
        return result


def mixed(a: str, b: str) -> list[Decimal]:
    return [D(a) * x + D(b) * z for x, z in zip(X, Z, strict=True)]


def test_exact_threshold_and_negative_correlation_join_but_orthogonal_stays_separate() -> None:
    source = {"AA": bars(X), "BB": bars(mixed(".8", ".6")), "CC": bars([-x for x in X])}
    assert correlation_groups(source, 61 * DAY) == (("AA", "AA"), ("BB", "AA"), ("CC", "AA"))
    assert correlation_groups({"AA": bars(X), "BB": bars(Z)}, 61 * DAY) == (
        ("AA", "AA"),
        ("BB", "BB"),
    )
    assert correlation_groups({"AA": bars(X), "BB": bars(mixed(".799", ".601"))}, 61 * DAY) == (
        ("AA", "AA"),
        ("BB", "BB"),
    )


def test_connected_components_are_transitive_and_input_order_independent() -> None:
    source = {"CC": bars(mixed(".28", ".96")), "AA": bars(X), "BB": bars(mixed(".8", ".6"))}
    expected = (("AA", "AA"), ("BB", "AA"), ("CC", "AA"))
    assert correlation_groups(source, 61 * DAY) == expected
    assert correlation_groups(dict(reversed(list(source.items()))), 61 * DAY) == expected


@pytest.mark.parametrize(
    "bad", ["missing", "constant", "nan", "duplicate", "unordered", "ohlc", "stale"]
)
def test_unknown_relation_conservatively_connects_affected_assets(bad: str) -> None:
    data = bars(X)
    if bad == "missing":
        data = data[2:]
    elif bad == "constant":
        data = bars([D(0)] * 60)
    elif bad == "nan":
        data[10] = replace(data[10], close=D("NaN"))
    elif bad == "duplicate":
        data.insert(5, data[5])
    elif bad == "unordered":
        data[5], data[6] = data[6], data[5]
    elif bad == "ohlc":
        data[5] = replace(data[5], low=data[5].high + 1)
    else:
        data = data[:-1]
    source = {"AA": bars(X), "BB": data, "CC": bars(Z)}
    assert correlation_groups(source, 61 * DAY) == (("AA", "AA"), ("BB", "AA"), ("CC", "AA"))


def test_future_suffix_and_current_incomplete_bar_do_not_change_snapshot() -> None:
    source = {"AA": bars(X), "BB": bars(Z)}
    expected = correlation_groups(source, 61 * DAY)
    future = replace(source["AA"][-1], open_ms=61 * DAY, close=D("sNaN"))
    source["AA"] = source["AA"] + [future, replace(future, open_ms=62 * DAY)]
    assert correlation_groups(source, 61 * DAY) == expected
    assert correlation_groups(source, 61 * DAY + 100) == expected


def test_latest_sixty_common_returns_override_older_different_relationship() -> None:
    source = {"AA": bars(X + X), "BB": bars(X + Z)}
    assert correlation_groups(source, 121 * DAY) == (("AA", "AA"), ("BB", "BB"))


def test_returns_use_matching_dates_not_array_offsets_or_multiday_changes() -> None:
    aa = bars(X + X)
    bb = bars(Z + Z)
    del bb[20]
    assert correlation_groups({"AA": aa, "BB": bb}, 121 * DAY) == (("AA", "AA"), ("BB", "BB"))
    assert correlation_groups({"AA": aa[:61], "BB": bars(Z, DAY)}, 62 * DAY) == (
        ("AA", "AA"),
        ("BB", "AA"),
    )


@pytest.mark.parametrize("decision", [-1, True, 1.5, 1_735_689_600_000])
def test_invalid_or_reserved_decision_time_is_rejected(decision: int) -> None:
    with pytest.raises(ValueError):
        correlation_groups({}, decision)


def test_empty_singleton_and_callers_decimal_context() -> None:
    assert correlation_groups({}, 0) == ()
    assert correlation_groups({"AA": []}, DAY) == (("AA", "AA"),)
    source = {"AA": bars(X), "BB": bars(mixed(".8", ".6"))}
    with localcontext() as context:
        context.prec = 2
        assert correlation_groups(source, 61 * DAY) == (("AA", "AA"), ("BB", "AA"))
