"""V4 data step: the static exclusions, the stable-price rule and the monthly top 10.

Bars are small synthetic series, one per day, built in memory; the selection is pure, so there
is no network and no file beyond the committed config. The network is blocked for every test
in this file (the autouse fixture below), as in ``test_v4_data_listing.py``. Most tests select
at 2019-09-01 00:00 UTC (``SEL``); a symbol whose history starts at ``FIRST`` has 274 daily
bars before it.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from crypto_grid_bot.v4.data.bars import DailyBar
from crypto_grid_bot.v4.data.config import DataConfig, load_data_config, months
from crypto_grid_bot.v4.data.universe import (
    HOURLY_RANK_DEPTH,
    MonthlyUniverse,
    select_universe,
    stable_price,
    static_exclusion,
)

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
DAY = 24 * HOUR
FIRST = date(2018, 12, 1)
LAST = date(2019, 8, 31)
SEL = date(2019, 9, 1)

Value = str | Callable[[date], str]


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket; each attempt is counted."""
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        attempts.append("socket")
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return attempts


@pytest.fixture
def spec() -> DataConfig:
    """The committed config with the spec's values; the window is set by each test."""
    return load_data_config(ROOT / "config" / "v4_data.json")


@pytest.fixture
def config(spec: DataConfig) -> DataConfig:
    """Months 2019-01 to 2019-09: a symbol from ``FIRST`` is selectable from 2019-07."""
    return replace(spec, start_day="2019-01-01", end_month="2019-09")


def ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1000


def at(day: date, hours: int = 0) -> int:
    return ms(day) + hours * HOUR


def _value(value: Value, day: date) -> Decimal:
    return Decimal(value(day) if callable(value) else value)


def series(
    first: date,
    last: date,
    volume: Value = "100",
    close: Value = "100",
    *,
    gaps: Collection[date] = (),
) -> list[DailyBar]:
    """One daily bar for each day from ``first`` to ``last`` inclusive, except the ``gaps``."""
    bars = []
    day = first
    while day <= last:
        if day not in gaps:
            price = _value(close, day)
            bars.append(DailyBar(ms(day), price, price, price, price, _value(volume, day)))
        day += timedelta(days=1)
    return bars


def pick(result: Sequence[MonthlyUniverse], month: str) -> MonthlyUniverse:
    (found,) = (u for u in result if u.month == month)
    return found


def names(universe: MonthlyUniverse) -> list[str]:
    return [symbol for symbol, _, _ in universe.ranked]


def days_back(count: int) -> date:
    """The day ``count`` days before the selection."""
    return SEL - timedelta(days=count)


# --- static exclusions -----------------------------------------------------------------------

BASES = frozenset({"BTC", "ETH", "JUP", "USDC", "WBTC", "UP", "SYRUP", "BTCUP", "ETHBEAR"})


def test_static_exclusions_follow_the_spec_and_ruling_r1(spec):
    assert static_exclusion("BTCUPUSDT", BASES, spec) == "leveraged"
    assert static_exclusion("ETHBEARUSDT", BASES, spec) == "leveraged"
    assert static_exclusion("JUPUSDT", BASES, spec) is None
    assert static_exclusion("USDCUSDT", BASES, spec) == "stablecoin"
    assert static_exclusion("WBTCUSDT", BASES, spec) == "wrapped"
    assert static_exclusion("BTCUSDT", BASES, spec) is None


@pytest.mark.parametrize("suffix", ["UP", "DOWN", "BULL", "BEAR"])
def test_every_leveraged_suffix_counts_when_the_stem_is_a_listed_base(spec, suffix):
    assert static_exclusion(f"ETH{suffix}USDT", frozenset({"ETH", f"ETH{suffix}"}), spec) == (
        "leveraged"
    )


def test_a_base_that_merely_ends_in_a_suffix_with_an_unknown_stem_is_a_real_coin(spec):
    # R1: BTCUP is leveraged only because BTC is itself a base; without BTC it is not.
    assert static_exclusion("BTCUPUSDT", frozenset({"BTCUP", "ETH"}), spec) is None
    # SYRUP's stem would be SYR and JUP's J, neither a base; SETUP's SET is not either.
    assert static_exclusion("SYRUPUSDT", BASES, spec) is None
    assert static_exclusion("JUPUSDT", BASES, spec) is None
    assert static_exclusion("SETUPUSDT", BASES, spec) is None


@pytest.mark.parametrize("suffix", ["UP", "DOWN", "BULL", "BEAR"])
def test_a_base_that_is_exactly_a_suffix_word_is_leveraged_with_no_stem_listed(spec, suffix):
    # Ruling P19: BULLUSDT and BEARUSDT are the BTC members of the BULL/BEAR token family; no
    # real coin has such a base, so the empty stem needs no listed base.
    assert static_exclusion(f"{suffix}USDT", frozenset({suffix}), spec) == "leveraged"
    assert static_exclusion(f"{suffix}USDT", frozenset({suffix, "ETH", "JUP"}), spec) == (
        "leveraged"
    )
    # The ruling does not widen to bases that only end in a suffix, or to its first letters.
    assert static_exclusion("JUPUSDT", frozenset({suffix, "JUP", "SYRUP"}), spec) is None
    assert static_exclusion("SYRUPUSDT", frozenset({suffix, "JUP", "SYRUP"}), spec) is None


@pytest.mark.parametrize(
    "base",
    [
        *("USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD"),
        *("USDD", "UST", "EUR", "GBP", "AUD", "TRY", "BRL"),
    ],
)
def test_the_listed_stablecoins_and_fiat_tokens_are_excluded(spec, base):
    assert static_exclusion(f"{base}USDT", frozenset({base}), spec) == "stablecoin"


@pytest.mark.parametrize("base", ["WBTC", "WBETH", "BETH", "STETH"])
def test_the_listed_wrapped_and_staked_bases_are_excluded(spec, base):
    assert static_exclusion(f"{base}USDT", frozenset({base}), spec) == "wrapped"


@pytest.mark.parametrize("symbol", ["BTCEUR", "USDT", "BTC", "", "btcusdt"])
def test_static_exclusion_takes_a_usdt_symbol(spec, symbol):
    with pytest.raises(ValueError, match="USDT"):
        static_exclusion(symbol, BASES, spec)


# --- the stable-price rule -------------------------------------------------------------------


def window(close: Value, *, gaps: Collection[date] = ()) -> list[DailyBar]:
    """Every day of the 90 before the selection."""
    return series(days_back(90), days_back(1), close=close, gaps=gaps)


def test_stable_price_rule_needs_90_percent_of_90_days_within_2_percent(spec):
    def closes(near: int) -> Callable[[date], str]:
        return lambda day: "1.00" if (day - days_back(90)).days < near else "1.50"

    assert stable_price(window(closes(90)), ms(SEL), spec)
    assert stable_price(window(closes(81)), ms(SEL), spec)
    assert not stable_price(window(closes(80)), ms(SEL), spec)
    assert not stable_price(window(closes(0)), ms(SEL), spec)


def test_a_day_without_a_bar_is_not_within_the_band(spec):
    # 81 in-band days and 9 missing days are stable; 80 and 10 are not (ruling P2).
    missing = [days_back(n) for n in range(1, 10)]
    assert stable_price(window("1.00", gaps=missing), ms(SEL), spec)
    assert not stable_price(window("1.00", gaps=[*missing, days_back(10)]), ms(SEL), spec)


def test_a_history_shorter_than_81_days_is_not_stable(spec):
    assert not stable_price(series(days_back(80), days_back(1), close="1.00"), ms(SEL), spec)
    assert stable_price(series(days_back(81), days_back(1), close="1.00"), ms(SEL), spec)
    assert not stable_price([], ms(SEL), spec)


@pytest.mark.parametrize(
    ("close", "stable"),
    [
        ("1", True),
        ("1.02", True),
        ("0.98", True),
        ("1.0201", False),
        ("0.9799", False),
        ("1.50", False),
    ],
)
def test_the_band_is_two_percent_around_one_and_inclusive(spec, close, stable):
    assert stable_price(window(close), ms(SEL), spec) is stable


def test_only_the_90_days_before_the_selection_count(spec):
    def far(day: date) -> str:
        return "1.00" if day in near else "1.50"

    # 80 in-band days inside the window, so not stable ...
    near = {days_back(n) for n in range(10, 90)}
    assert len(near) == 80
    assert not stable_price(window(far), ms(SEL), spec)
    # ... in-band bars on the selection day itself and 91 days back are outside the window ...
    before_window = series(days_back(91), days_back(91), close="1.00")
    selection_day = series(SEL, SEL, close="1.00")
    assert not stable_price([*before_window, *window(far), *selection_day], ms(SEL), spec)
    # ... while the window's first day, 90 days back, is the 81st.
    near.add(days_back(90))
    assert stable_price(window(far), ms(SEL), spec)


# --- the ranking -----------------------------------------------------------------------------


def test_ranking_uses_the_30_day_mean_over_days_with_bars_and_needs_200_bars(config):
    window_start = days_back(30)  # 2019-08-02: the 30 UTC days before the selection
    daily = {
        # Steady: 100 a day on all 30 days of the window.
        "AAAUSDT": series(FIRST, LAST),
        # Huge volume up to and including the day before the window, 50 inside it.
        "BBBUSDT": series(
            FIRST, LAST, volume=lambda d: "50" if d >= window_start else "1000000000"
        ),
        # Bars on only 10 of the 30 days, at 300: the mean is 300, not 100.
        "CCCUSDT": series(
            FIRST,
            LAST,
            volume="300",
            gaps={window_start + timedelta(days=n) for n in range(20)},
        ),
        # 199 bars before the selection: one short of the minimum, whatever its volume.
        "DDDUSDT": series(days_back(199), LAST, volume="999999"),
        # 200 bars: enough.
        "EEEUSDT": series(days_back(200), LAST, volume="75"),
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.ranked == (
        ("CCCUSDT", Decimal(300), 10),
        ("AAAUSDT", Decimal(100), 30),
        ("EEEUSDT", Decimal(75), 30),
        ("BBBUSDT", Decimal(50), 30),
    )
    assert sep.excluded == (("DDDUSDT", "history"),)
    assert sep.selected == ("CCCUSDT", "AAAUSDT", "EEEUSDT", "BBBUSDT")


def test_the_200_bar_boundary(config):
    daily = {
        "BTCUSDT": series(days_back(199), LAST),
        "ETHUSDT": series(days_back(200), LAST),
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.selected == ("ETHUSDT",)
    assert sep.excluded == (("BTCUSDT", "history"),)


def test_the_mean_is_a_decimal_division_independent_of_the_ambient_context(config):
    # 200 older bars for the history, then exactly three in the window, of volume 1, 0 and 0.
    bars = [
        *series(days_back(230), days_back(31)),
        *series(days_back(3), days_back(1), volume=lambda d: "1" if d == days_back(3) else "0"),
    ]
    expected = Decimal("0.3333333333333333333333333333333333333333")
    sep = pick(select_universe({"AAAUSDT": bars}, config), "2019-09")
    assert sep.ranked == (("AAAUSDT", expected, 3),)
    with localcontext() as context:
        context.prec = 5
        again = pick(select_universe({"AAAUSDT": bars}, config), "2019-09")
    assert again.ranked == sep.ranked


def test_relisted_symbol_counts_only_days_with_bars(config):
    daily = {
        # 306 bars in 2018-03..12, a gap of 233 days, then 10 bars of volume 200. Zero-filled
        # days would make the mean 200 x 10 / 30; it is 200.
        "RELISTUSDT": series(date(2018, 3, 1), date(2018, 12, 31))
        + series(days_back(10), LAST, volume="200"),
        # 100 bars, a gap of about 600 days, 62 bars: 162 bars in all, though 730 days pass
        # between the first bar and the selection. A calendar count would let it through.
        "THINUSDT": series(date(2017, 9, 1), date(2017, 12, 9), volume="1000000")
        + series(days_back(62), LAST, volume="1000000"),
        "STEADYUSDT": series(FIRST, LAST),
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.ranked == (
        ("RELISTUSDT", Decimal(200), 10),
        ("STEADYUSDT", Decimal(100), 30),
    )
    assert sep.excluded == (("THINUSDT", "history"),)


def test_ties_break_alphabetically_and_only_the_top_10_are_selected(config):
    distinct = {f"S{n:02d}USDT": str(1000 - 10 * n) for n in range(1, 10)}
    daily = {symbol: series(FIRST, LAST, volume=volume) for symbol, volume in distinct.items()}
    daily["TIEZUSDT"] = series(FIRST, LAST, volume="500")
    # Three bars of 500 in the window have the same mean as thirty: still a tie, by value.
    gaps = {days_back(n) for n in range(4, 31)}
    daily["TIEAUSDT"] = series(FIRST, LAST, volume="500", gaps=gaps)
    daily["LOWUSDT"] = series(FIRST, LAST, volume="10")
    sep = pick(select_universe(daily, config), "2019-09")
    assert len(sep.ranked) == 12
    assert names(sep)[9:] == ["TIEAUSDT", "TIEZUSDT", "LOWUSDT"]
    assert sep.ranked[9][1] == sep.ranked[10][1] == Decimal(500)
    assert sep.ranked[9][2] == 3 and sep.ranked[10][2] == 30
    assert sep.selected == (*distinct, "TIEAUSDT")
    assert len(sep.selected) == 10


def test_first_selection_is_the_first_month_any_symbol_has_200_bars(spec):
    # BTC trades from 2017-08-17: 227 daily bars before 2018-04-01, 196 before 2018-03-01.
    config = replace(spec, end_month="2018-06")
    daily = {"BTCUSDT": series(date(2017, 8, 17), date(2018, 6, 30))}
    result = select_universe(daily, config)
    assert [u.month for u in result] == ["2018-04", "2018-05", "2018-06"]
    assert all(u.selected == ("BTCUSDT",) for u in result)
    first = result[0]
    assert first.entered == ("BTCUSDT",) and first.left == ()
    assert (date(2018, 4, 1) - date(2017, 8, 17)).days == 227
    assert (date(2018, 3, 1) - date(2017, 8, 17)).days == 196


def test_months_before_the_first_selection_are_omitted_and_none_follows_the_end_month(spec):
    daily = {"BTCUSDT": series(date(2017, 8, 17), date(2018, 12, 31))}
    result = select_universe(daily, replace(spec, end_month="2018-09"))
    assert [u.month for u in result] == list(months("2018-04", "2018-09"))
    # No symbol ever reaches 200 bars inside the window: nothing is selected, nothing returned.
    assert select_universe(daily, replace(spec, end_month="2018-03")) == ()
    assert select_universe({}, spec) == ()


def test_entered_and_left_are_relative_to_the_previous_month(config):
    top2 = replace(config, top_n=2)

    def b(day: date) -> str:  # strong until July, weak after
        return "200" if day <= date(2019, 7, 31) else "10"

    def c(day: date) -> str:  # weak until July, strong after
        return "50" if day <= date(2019, 7, 31) else "300"

    daily = {
        "AAAUSDT": series(FIRST, LAST),  # steady at 100
        "BBBUSDT": series(FIRST, LAST, volume=b),
        "CCCUSDT": series(FIRST, LAST, volume=c),
    }
    result = select_universe(daily, top2)
    assert [(u.month, u.selected, u.entered, u.left) for u in result] == [
        ("2019-07", ("BBBUSDT", "AAAUSDT"), ("BBBUSDT", "AAAUSDT"), ()),
        ("2019-08", ("BBBUSDT", "AAAUSDT"), (), ()),
        ("2019-09", ("CCCUSDT", "AAAUSDT"), ("CCCUSDT",), ("BBBUSDT",)),
    ]


def test_a_month_where_every_candidate_is_excluded_is_kept_and_empty(spec):
    config = replace(spec, start_day="2019-01-01", end_month="2019-12")
    # Trading to 2019-08-31, silent until mid-November, and back for the last ten days of it.
    daily = {
        "AAAUSDT": series(FIRST, LAST) + series(date(2019, 11, 21), date(2019, 11, 30)),
        "USDCUSDT": series(FIRST, LAST),
    }
    result = select_universe(daily, config)
    by_month = {u.month: u for u in result}
    assert [u.month for u in result] == list(months("2019-07", "2019-12"))
    october = by_month["2019-10"]
    assert october.selected == () and october.ranked == ()
    assert october.excluded == (("AAAUSDT", "dead_market"), ("USDCUSDT", "stablecoin"))
    assert october.entered == () and october.left == ("AAAUSDT",)
    november = by_month["2019-11"]
    assert november.selected == () and november.entered == () and november.left == ()
    december = by_month["2019-12"]
    assert december.selected == ("AAAUSDT",) and december.entered == ("AAAUSDT",)
    assert december.ranked == (("AAAUSDT", Decimal(100), 10),)


# --- eligibility -----------------------------------------------------------------------------


def test_no_bar_in_the_7_days_before_selection_is_not_eligible(config):
    daily = {
        "ALIVEUSDT": series(FIRST, LAST),
        "SEVENUSDT": series(FIRST, days_back(7)),  # last bar opened 7 days before 00:00
        "EIGHTUSDT": series(FIRST, days_back(8)),  # last bar opened 8 days before 00:00
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert names(sep) == ["ALIVEUSDT", "SEVENUSDT"]
    assert sep.excluded == (("EIGHTUSDT", "dead_market"),)
    assert sep.selected == ("ALIVEUSDT", "SEVENUSDT")


def test_fewer_than_10_eligible_selects_all_of_them(config):
    daily = {
        "AAAUSDT": series(FIRST, LAST, volume="30"),
        "BBBUSDT": series(FIRST, LAST, volume="20"),
        "CCCUSDT": series(FIRST, LAST, volume="10"),
        "NEWUSDT": series(days_back(30), LAST, volume="999"),
    }
    result = select_universe(daily, config)
    assert result[0].month == "2019-07"
    sep = pick(result, "2019-09")
    assert sep.selected == ("AAAUSDT", "BBBUSDT", "CCCUSDT")
    assert names(sep) == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert sep.excluded == (("NEWUSDT", "history"),)


def test_the_configured_top_n_is_the_size_of_the_selection(config):
    daily = {f"S{n:02d}USDT": series(FIRST, LAST, volume=str(100 - n)) for n in range(1, 8)}
    sep = pick(select_universe(daily, replace(config, top_n=3)), "2019-09")
    assert sep.selected == ("S01USDT", "S02USDT", "S03USDT")
    assert len(sep.ranked) == 7


def test_excluded_carries_the_first_applicable_reason_in_symbol_order(config):
    daily = {
        "BTCUSDT": series(FIRST, LAST),
        # Static reasons come first, whatever else is wrong with the symbol.
        "USDCUSDT": series(days_back(20), days_back(10)),
        "BTCUPUSDT": series(FIRST, LAST),
        "WBTCUSDT": series(FIRST, LAST),
        # A pegged price comes before too little history and before a dead market.
        "PEGUSDT": series(days_back(100), days_back(10), close="1.00"),
        # Too little history comes before a dead market.
        "GONEUSDT": series(days_back(80), days_back(20)),
        "NEWUSDT": series(days_back(50), LAST),
        "OLDUSDT": series(FIRST, days_back(20)),
        # Not trading yet at the selection: neither a candidate nor excluded.
        "LATEUSDT": series(SEL, SEL + timedelta(days=300)),
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.excluded == (
        ("BTCUPUSDT", "leveraged"),
        ("GONEUSDT", "history"),
        ("NEWUSDT", "history"),
        ("OLDUSDT", "dead_market"),
        ("PEGUSDT", "stable_price"),
        ("USDCUSDT", "stablecoin"),
        ("WBTCUSDT", "wrapped"),
    )
    assert sep.selected == ("BTCUSDT",)


def test_suffix_word_bases_are_excluded_and_coins_that_only_end_in_one_are_ranked(config):
    daily = {
        symbol: series(FIRST, LAST)
        for symbol in (
            *("BTCUSDT", "UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"),
            *("JUPUSDT", "SYRUPUSDT", "BTCUPUSDT", "BTCBEARUSDT"),
        )
    }
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.excluded == (
        ("BEARUSDT", "leveraged"),
        ("BTCBEARUSDT", "leveraged"),
        ("BTCUPUSDT", "leveraged"),
        ("BULLUSDT", "leveraged"),
        ("DOWNUSDT", "leveraged"),
        ("UPUSDT", "leveraged"),
    )
    assert sorted(names(sep)) == ["BTCUSDT", "JUPUSDT", "SYRUPUSDT"]


def test_a_static_reason_wins_over_the_stable_price_rule(config, spec):
    pegged = series(FIRST, LAST, close="1.00")
    assert len(pegged) >= 200 and stable_price(pegged, ms(SEL), spec)
    daily = {"USDCUSDT": pegged, "BTCUSDT": series(FIRST, LAST)}
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.excluded == (("USDCUSDT", "stablecoin"),)
    assert sep.selected == ("BTCUSDT",)


def test_the_stable_price_rule_is_judged_afresh_at_each_selection(spec):
    config = replace(spec, start_day="2019-01-01", end_month="2019-12")
    end = date(2019, 12, 31)
    daily = {
        # Pegged until the end of August, free afterwards.
        "PEGTHENFREEUSDT": series(
            FIRST, end, close=lambda d: "1.00" if d <= LAST else "100", volume="50"
        ),
        # Free until the end of August, pegged afterwards: not judged on prices it has not had.
        "FREETHENPEGUSDT": series(
            FIRST, end, close=lambda d: "100" if d <= LAST else "1.00", volume="50"
        ),
        "BTCUSDT": series(FIRST, end, volume="500"),
    }
    result = {u.month: u for u in select_universe(daily, config)}
    assert result["2019-09"].excluded == (("PEGTHENFREEUSDT", "stable_price"),)
    assert names(result["2019-09"]) == ["BTCUSDT", "FREETHENPEGUSDT"]
    assert result["2019-12"].excluded == (("FREETHENPEGUSDT", "stable_price"),)
    assert names(result["2019-12"]) == ["BTCUSDT", "PEGTHENFREEUSDT"]


def test_a_selection_uses_only_bars_before_the_month(config):
    daily = {
        "AAAUSDT": series(FIRST, LAST),
        "BBBUSDT": series(FIRST, LAST, volume="50"),
    }
    later = {
        "AAAUSDT": daily["AAAUSDT"],
        "BBBUSDT": daily["BBBUSDT"] + series(SEL, SEL + timedelta(days=5), volume="1000000"),
        "NEWUSDT": series(SEL, SEL + timedelta(days=300), volume="1000000"),
    }
    assert pick(select_universe(later, config), "2019-09") == pick(
        select_universe(daily, config), "2019-09"
    )


def test_the_result_is_ordered_by_month_and_deterministic(config):
    daily = {f"S{n:02d}USDT": series(FIRST, LAST, volume=str(n)) for n in range(1, 6)}
    result = select_universe(daily, config)
    assert [u.month for u in result] == sorted(u.month for u in result)
    assert result == select_universe(dict(reversed(daily.items())), config)


def test_a_monthly_universe_is_frozen(config):
    universe = pick(select_universe({"AAAUSDT": series(FIRST, LAST)}, config), "2019-09")
    with pytest.raises(FrozenInstanceError):
        universe.month = "2019-10"  # type: ignore[misc]


# --- the hourly check ------------------------------------------------------------------------

SEL_MS = ms(SEL)


def ranked_symbols(count: int) -> dict[str, list[DailyBar]]:
    """``count`` symbols C01.. whose volumes fall with the number, so C01 ranks first."""
    return {
        f"C{n:02d}USDT": series(FIRST, LAST, volume=str(10_000 - n)) for n in range(1, count + 1)
    }


def usable_for(symbols: Collection[str]) -> dict[str, list[int]]:
    """Every symbol has an hour open an hour before the selection."""
    return {symbol: [SEL_MS - HOUR] for symbol in symbols}


def test_a_candidate_without_recent_hourly_bars_is_skipped_and_the_next_takes_its_place(config):
    daily = ranked_symbols(12)
    usable = usable_for(daily)
    usable["C03USDT"] = [SEL_MS - 169 * HOUR]  # one hour too old: skipped
    usable["C04USDT"] = [SEL_MS - 168 * HOUR]  # exactly 168 hours back: inside the window
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert sep.selected == (
        "C01USDT",
        "C02USDT",
        "C04USDT",
        "C05USDT",
        "C06USDT",
        "C07USDT",
        "C08USDT",
        "C09USDT",
        "C10USDT",
        "C11USDT",
    )
    assert sep.excluded == (("C03USDT", "no_recent_hourly"),)
    # The ranking is the full ranking: the skipped one and the unconsidered rank 12 stay in it.
    assert len(sep.ranked) == 12 and sep.ranked[2][0] == "C03USDT"


@pytest.mark.parametrize(
    ("hours", "kept"),
    [
        ([SEL_MS - 168 * HOUR], True),  # the window's first instant is inside
        ([SEL_MS - 168 * HOUR - 1], False),  # one millisecond before it
        ([SEL_MS - HOUR], True),
        ([SEL_MS - 1], True),
        ([SEL_MS], False),  # the selection's own hour is not before the selection
        ([SEL_MS + HOUR, SEL_MS + 2 * HOUR], False),
        ([SEL_MS - 400 * HOUR, SEL_MS - 300 * HOUR], False),
        ([SEL_MS - 400 * HOUR, SEL_MS - 5 * HOUR, SEL_MS + HOUR], True),
        ([], False),
    ],
)
def test_the_168_hour_window_is_closed_at_the_start_and_open_at_the_selection(config, hours, kept):
    # BBB, always usable, keeps the month non-empty; AAA ranks first and carries the hours.
    daily = {"AAAUSDT": series(FIRST, LAST, volume="200"), "BBBUSDT": series(FIRST, LAST)}
    usable = {"AAAUSDT": hours, "BBBUSDT": [SEL_MS - HOUR]}
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    if kept:
        assert sep.selected == ("AAAUSDT", "BBBUSDT") and sep.excluded == ()
    else:
        assert sep.selected == ("BBBUSDT",)
        assert sep.excluded == (("AAAUSDT", "no_recent_hourly"),)
    assert names(sep) == ["AAAUSDT", "BBBUSDT"]


def test_a_symbol_missing_from_usable_hours_has_none(config):
    daily = ranked_symbols(3)
    usable = usable_for(["C01USDT", "C03USDT"])
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert sep.selected == ("C01USDT", "C03USDT")
    assert sep.excluded == (("C02USDT", "no_recent_hourly"),)
    assert select_universe(daily, config, usable_hours={}) == ()


def test_the_hourly_skip_stops_at_rank_20(config):
    assert HOURLY_RANK_DEPTH == 20
    daily = ranked_symbols(25)
    unusable = {2, 4, 6, 8, 10, 12, 14, 15, 16, 17, 18, 19}  # 12 of the top 20
    usable = usable_for(s for n, s in enumerate(daily, start=1) if n not in unusable)
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert sep.selected == tuple(f"C{n:02d}USDT" for n in (1, 3, 5, 7, 9, 11, 13, 20))
    assert sep.excluded == tuple((f"C{n:02d}USDT", "no_recent_hourly") for n in sorted(unusable))
    # Ranks 21 to 25 are usable but never considered: not selected, not recorded as skipped.
    assert len(sep.ranked) == 25
    assert not {f"C{n:02d}USDT" for n in range(21, 26)} & {
        *sep.selected,
        *(symbol for symbol, _ in sep.excluded),
    }


def test_the_hourly_skip_stops_as_soon_as_ten_are_selected(config):
    daily = ranked_symbols(25)
    usable = usable_for(daily)
    usable["C02USDT"] = []
    usable["C15USDT"] = []  # past the tenth selected: never looked at
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert len(sep.selected) == 10 and sep.selected[-1] == "C11USDT"
    assert sep.excluded == (("C02USDT", "no_recent_hourly"),)


def test_without_usable_hours_there_is_no_hourly_check(config):
    daily = ranked_symbols(12)
    sep = pick(select_universe(daily, config), "2019-09")
    assert sep.selected == tuple(f"C{n:02d}USDT" for n in range(1, 11))
    assert sep.excluded == ()
    assert len(sep.ranked) == 12
    # The same data with an hourly check that fails everyone selects nobody.
    assert select_universe(daily, config, usable_hours={}) == ()


def test_the_hourly_check_does_not_change_the_ranking(config):
    daily = ranked_symbols(12)
    usable = usable_for(daily)
    usable["C01USDT"] = []
    plain = pick(select_universe(daily, config), "2019-09")
    checked = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert checked.ranked == plain.ranked
    assert "C01USDT" not in checked.selected and checked.selected[0] == "C02USDT"


def test_excluded_mixes_every_reason_in_symbol_order(config):
    daily = ranked_symbols(3)
    daily["AAAUSDT"] = series(days_back(5), LAST)  # too little history
    daily["USDCUSDT"] = series(FIRST, LAST)
    usable = usable_for(["C01USDT", "C03USDT"])
    sep = pick(select_universe(daily, config, usable_hours=usable), "2019-09")
    assert sep.excluded == (
        ("AAAUSDT", "history"),
        ("C02USDT", "no_recent_hourly"),
        ("USDCUSDT", "stablecoin"),
    )


# --- bad input -------------------------------------------------------------------------------


def test_daily_bars_must_be_strictly_increasing(config):
    bars = series(FIRST, LAST)
    with pytest.raises(ValueError, match="AAAUSDT.*strictly increasing"):
        select_universe({"AAAUSDT": [*bars, bars[-1]]}, config)
    with pytest.raises(ValueError, match="AAAUSDT.*strictly increasing"):
        select_universe({"AAAUSDT": [bars[1], bars[0], *bars[2:]]}, config)


def test_usable_hours_must_be_strictly_increasing(config):
    daily = {"AAAUSDT": series(FIRST, LAST)}
    with pytest.raises(ValueError, match="AAAUSDT.*strictly increasing"):
        select_universe(daily, config, usable_hours={"AAAUSDT": [SEL_MS - HOUR, SEL_MS - 2 * HOUR]})


def test_every_symbol_must_be_a_usdt_symbol(config):
    with pytest.raises(ValueError, match="BTCEUR"):
        select_universe({"BTCEUR": series(FIRST, LAST)}, config)


def test_the_volume_window_must_cover_the_dead_market_window(config):
    # With a 6-day volume window a symbol alive 7 days ago could have no observation.
    with pytest.raises(ValueError, match="volume_days"):
        select_universe({"AAAUSDT": series(FIRST, LAST)}, replace(config, volume_days=6))
    select_universe({"AAAUSDT": series(FIRST, LAST)}, replace(config, volume_days=7))


def test_top_n_beyond_the_hourly_depth_is_refused_only_with_an_hourly_check(config):
    wide = replace(config, top_n=HOURLY_RANK_DEPTH + 1)
    daily = {"AAAUSDT": series(FIRST, LAST)}
    assert pick(select_universe(daily, wide), "2019-09").selected == ("AAAUSDT",)
    with pytest.raises(ValueError, match="top_n"):
        select_universe(daily, wide, usable_hours={"AAAUSDT": [SEL_MS - HOUR]})


def test_select_universe_does_not_change_its_inputs(config):
    daily: Mapping[str, Sequence[DailyBar]] = {"AAAUSDT": series(FIRST, LAST)}
    before = {symbol: list(bars) for symbol, bars in daily.items()}
    usable = {"AAAUSDT": [SEL_MS - HOUR]}
    select_universe(daily, config, usable_hours=usable)
    assert {symbol: list(bars) for symbol, bars in daily.items()} == before
    assert usable == {"AAAUSDT": [SEL_MS - HOUR]}
