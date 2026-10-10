"""Frozen monthly boundaries and hosting economics, with synthetic samples."""

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

DAY = 86400000
HOUR = 3600000


def stamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()) * 1000


def series(start, end, boundaries):
    rows = []
    equity = D(10000)
    for time in range(stamp(start), stamp(end), DAY):
        equity = boundaries.get(time, equity)
        rows.append((time, equity))
    rows.append((stamp(end), boundaries.get(stamp(end), equity)))
    return rows


def test_months_share_boundary_and_terminal_midnight_does_not_add_a_month():
    from crypto_grid_bot.trend.monthly import monthly_diagnostics

    samples = series(
        "2020-01-01T01:00",
        "2020-03-01T00:00",
        {stamp("2020-02-01T01:00"): D(12000), stamp("2020-03-01T00:00"): D(15600)},
    )
    result = monthly_diagnostics(samples)
    assert [row.month for row in result.months] == ["2020-01", "2020-02"]
    assert [row.return_fraction for row in result.months] == [D(".2"), D(".3")]
    assert result.months[0].end_ms == result.months[1].start_ms
    assert result.mean_return == D(".25")
    assert result.months_at_least_20_percent == 2
    assert result.months_at_least_30_percent == 1
    assert result.hosting_capital_eur_proxy == D(20)


def test_partial_first_and_last_month_keep_real_endpoints():
    from crypto_grid_bot.trend.monthly import monthly_diagnostics

    samples = series(
        "2020-01-20T01:00",
        "2020-02-03T00:00",
        {stamp("2020-02-01T01:00"): D(9000), stamp("2020-02-03T00:00"): D(9900)},
    )
    result = monthly_diagnostics(samples)
    assert result.months[0].start_ms == samples[0][0]
    assert result.months[-1].end_ms == samples[-1][0]
    assert [row.return_fraction for row in result.months] == [D("-.1"), D(".1")]
    assert result.mean_return == 0
    assert result.hosting_capital_eur_proxy is None


@pytest.mark.parametrize("terminal", [D(0), D(-1), D(9900)])
def test_loss_or_nonpositive_terminal_has_no_reachable_hosting_capital(terminal):
    from crypto_grid_bot.trend.monthly import monthly_diagnostics

    samples = [(stamp("2020-01-01T01:00"), D(10000)), (stamp("2020-01-02T00:00"), terminal)]
    result = monthly_diagnostics(samples)
    assert result.hosting_capital_eur_proxy is None
    assert result.months_at_least_20_percent == 0


@pytest.mark.parametrize("bad", ["gap", "wrong_hour", "late_terminal", "nonpositive", "nan"])
def test_rejects_malformed_daily_or_terminal_samples(bad):
    from crypto_grid_bot.trend.monthly import monthly_diagnostics

    start = stamp("2020-01-01T01:00")
    samples = [(start, D(10000)), (start + DAY, D(10100)), (start + 2 * DAY - HOUR, D(10200))]
    if bad == "gap":
        samples.pop(1)
    elif bad == "wrong_hour":
        samples[0] = (start - HOUR, D(10000))
    elif bad == "late_terminal":
        samples[-1] = (start + 3 * DAY, D(10200))
    elif bad == "nonpositive":
        samples[1] = (start + DAY, D(0))
    else:
        samples[-1] = (samples[-1][0], D("NaN"))
    with pytest.raises(ValueError):
        monthly_diagnostics(samples)
