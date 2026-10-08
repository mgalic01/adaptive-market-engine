"""Predeclared exclusions override daily targets, never price-derived forecasts."""

from datetime import UTC, datetime
from decimal import Decimal as D


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def test_calendar_forces_last_day_and_entire_excluded_month_only():
    from crypto_grid_bot.trend.exclusions import ExclusionCalendar

    c = ExclusionCalendar({"BTCUSDT": frozenset({"2021-02"})})
    assert c.zero_symbols(stamp("2021-01-30")) == frozenset()
    assert c.zero_symbols(stamp("2021-01-31")) == frozenset({"BTCUSDT"})
    assert c.zero_symbols(stamp("2021-02-28")) == frozenset({"BTCUSDT"})
    assert c.zero_symbols(stamp("2021-03-01")) == frozenset()


def test_runner_forced_close_cancels_pending_entry_and_waits_for_unmasked_hour():
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    r = TrendRunner({"BTCUSDT": rules}, excluded_months={"BTCUSDT": frozenset({"2021-02"})})
    start, hour = stamp("2021-01-30"), 3600000
    bar = {"BTCUSDT": (D(100), D(100), D(100))}
    r.account.fill("BTCUSDT", OrderIntent(D(5), False), D(100), start)
    r.step(start, bar, {"BTCUSDT": D(".1")}, {})
    for i in range(1, 27):
        r.step(start + i * hour, {}, {}, {})
    cancellation = r.hours[24][1].cancelled
    assert cancellation[0][1].weight == D(".1")
    r.step(start + 27 * hour, bar, {}, {})
    assert r.account.positions["BTCUSDT"].quantity == 0
    assert r.lifecycles.completed[0].exit_reason == "excluded_month"
    assert r.lifecycles.completed[0].end_ms == start + 27 * hour
