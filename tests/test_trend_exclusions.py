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


def test_close_preflight_uses_first_unmasked_hour_and_reports_missing_close():
    import pytest

    from crypto_grid_bot.trend.exclusions import ExclusionCalendar, UnavailableClose

    c = ExclusionCalendar({"BTCUSDT": frozenset({"2021-02"})})
    start, end = stamp("2021-01-01"), stamp("2021-03-01")
    last = stamp("2021-01-31")
    plan = c.check_close_availability(
        start, end, {"BTCUSDT": frozenset({last, last + 3 * 3600000})}
    )
    assert plan[0].decision_ms == last
    assert plan[0].fill_ms == last + 3 * 3600000
    assert plan[0].excluded_month == "2021-02"
    with pytest.raises(UnavailableClose) as failure:
        c.check_close_availability(start, end, {"BTCUSDT": frozenset({last})})
    assert failure.value.requirements[0].fill_ms is None


def test_fresh_run_inside_exclusion_and_consecutive_exclusions_need_no_new_close():
    from crypto_grid_bot.trend.exclusions import ExclusionCalendar

    c = ExclusionCalendar({"BTCUSDT": frozenset({"2021-02", "2021-03"})})
    assert (
        c.check_close_availability(
            stamp("2021-02-01"), stamp("2021-04-01"), {"BTCUSDT": frozenset()}
        )
        == ()
    )


def test_close_preflight_rejects_missing_inventory_and_non_daily_run_bounds():
    import pytest

    from crypto_grid_bot.trend.exclusions import ExclusionCalendar

    c = ExclusionCalendar({"BTCUSDT": frozenset({"2021-02"})})
    with pytest.raises(ValueError, match="inventory"):
        c.check_close_availability(stamp("2021-01-01"), stamp("2021-03-01"), {})
    with pytest.raises(ValueError):
        c.check_close_availability(
            stamp("2021-01-01") + 1, stamp("2021-03-01"), {"BTCUSDT": frozenset()}
        )


def test_malformed_inventory_is_data_error_not_unavailable_close():
    import pytest

    from crypto_grid_bot.trend.exclusions import ExclusionCalendar, UnavailableClose

    c = ExclusionCalendar({"BTCUSDT": frozenset({"2021-02"})})
    for bad in (True, -3600000, stamp("2021-01-31") + 1, stamp("2025-01-01")):
        with pytest.raises(ValueError, match="inventory") as failure:
            c.check_close_availability(
                stamp("2021-01-01"), stamp("2021-03-01"), {"BTCUSDT": frozenset({bad})}
            )
        assert not isinstance(failure.value, UnavailableClose)
