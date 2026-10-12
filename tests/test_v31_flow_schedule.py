"""The grid's minute flow gate precomputed as two bits per window hour (synthetic data)."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest

from crypto_grid_bot.combined.driver.flow_schedule import FlowSchedule, build_flow_schedule
from crypto_grid_bot.combined.routing import MinuteFlowGate
from crypto_grid_bot.combined.strategy_replay import replay_strategy

HOUR = fx.HOUR
DAY = fx.DAY
MINUTE = 60_000
RESERVED = 1_735_689_600_000
START, END = fx.START, fx.START + 3 * DAY


def at(hour: int, minute: int = 0) -> int:
    return fx.START + hour * HOUR + minute * MINUTE


def stepped(*steps):
    """Minutes from the fixture's first one (hour -1) to the end of a three-day window,
    whose taker-buy share steps at each ``((hour, minute), share)``."""
    edges = [at(*when) for when, _ in steps] + [END]
    return tuple(
        bar
        for (_, share), start, stop in zip(steps, edges[:-1], edges[1:], strict=True)
        for bar in fx.minutes(start, stop, share)
    )


HEALTHY = stepped(((-1, 0), ".6"))
FIXTURES = {
    "healthy": HEALTHY,
    "blocked_then_recovered": stepped(((-1, 0), ".6"), ((2, 0), ".3"), ((30, 0), ".6")),
    # The reviewer's probe: the share falls at 25:05; at .1 the gate blocks at 25:12, at
    # .42 it never drops below .40 and the open gate stays open.
    "collapse_at_25_05": stepped(((-1, 0), ".6"), ((25, 5), ".1")),
    "dip_at_25_05": stepped(((-1, 0), ".6"), ((25, 5), ".42")),
    # The h+59 edge: a fall at 25:48 first blocks at 25:59, one at 25:49 at 26:00.
    "first_block_at_25_59": stepped(((-1, 0), ".6"), ((25, 48), ".3")),
    "first_block_at_26_00": stepped(((-1, 0), ".6"), ((25, 49), ".3")),
    # A gap across the 41:00 boundary blocks from 40:51 until the gate reopens at 41:20.
    "gap_across_41_00": tuple(b for b in HEALTHY if not at(40, 50) <= b.open_ms < at(41, 5)),
    "invalid_minute": tuple(
        replace(b, taker_buy_base=D(11)) if b.open_ms == at(12, 30) else b for b in HEALTHY
    ),
    # Without the look-back the gate reads nothing until 0:15, then opens.
    "starts_at_the_window": tuple(b for b in HEALTHY if b.open_ms >= START),
    "first_read_minute_only": fx.minutes(at(0, -15), at(0, -14)),
    "last_minute_only": fx.minutes(at(72, -1), at(72)),
    "before_the_read_range_only": fx.minutes(at(-1), at(0, -15)),
    "none": (),
}


def replay_gate_pattern(minutes, start, end):
    """The flags the replay's own calls read from ``MinuteFlowGate``, per window hour.

    The frame of hour h feeds minute h, then reads ``allowed``; the interval of bar h
    reads ``allowed``, then feeds the bar's other minutes, and withholds the bar's
    resting buys if the gate was blocked at its opening or after any of them.
    """
    gate = MinuteFlowGate({bar.open_ms: bar for bar in minutes}, start)
    opened, withheld = [], []
    for hour in range(start, end, HOUR):
        gate.advance(hour)  # frame(hour)
        opened.append(gate.allowed)
        was_open = gate.allowed  # interval(hour)
        withheld.append(gate.advance(hour + HOUR - MINUTE) or not was_open)
    return opened, withheld


def packed(flags):
    """One bit per flag, least significant bit first within each byte."""
    return bytes(
        sum(1 << bit for bit, flag in enumerate(flags[byte : byte + 8]) if flag)
        for byte in range(0, len(flags), 8)
    )


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_schedule_bits_are_the_gate_states_the_replay_read(name):
    minutes = FIXTURES[name]
    opened, withheld = replay_gate_pattern(minutes, START, END)
    schedule = build_flow_schedule("BTCUSDT", iter(minutes), START, END)
    assert (schedule.symbol, schedule.start_ms, schedule.end_ms) == ("BTCUSDT", START, END)
    assert schedule.open_allowed == packed(opened)
    assert schedule.withheld == packed(withheld)
    hours = range(START, END, HOUR)
    assert [schedule.allowed_at(hour) for hour in hours] == opened
    assert [schedule.withheld_at(hour) for hour in hours] == withheld
    assert schedule.present is any(at(0, -15) <= bar.open_ms < END for bar in minutes)


def test_the_probe_fixtures_reach_the_flags_they_probe():
    def flags(name, hour):
        schedule = build_flow_schedule("BTCUSDT", FIXTURES[name], START, END)
        return schedule.allowed_at(at(hour)), schedule.withheld_at(at(hour))

    assert flags("collapse_at_25_05", 25) == (True, True)
    assert flags("dip_at_25_05", 25) == (True, False)
    assert flags("first_block_at_25_59", 25) == (True, True)
    assert flags("first_block_at_26_00", 25) == (True, False)
    assert flags("first_block_at_26_00", 26) == (False, True)
    assert flags("gap_across_41_00", 40) == (True, True)
    assert flags("gap_across_41_00", 41) == (False, True)
    assert flags("gap_across_41_00", 42) == (True, False)
    assert flags("starts_at_the_window", 0) == (False, True)
    assert flags("starts_at_the_window", 1) == (True, False)
    assert flags("none", 0) == flags("last_minute_only", 71) == (False, True)


def test_schedule_bits_match_gate_states():
    # A three-hour window. The share is .6 from the first minute read; it falls to .3 at
    # 1:48, so eleven .3 minutes of fifteen (.38 < .40) first block at 1:59, bar 1's last
    # minute; back to .6 at 2:20, eight .6 minutes of fifteen (.46 >= .45) reopen at 2:28.
    minutes = (
        *fx.minutes(at(0, -15), at(1, 48), ".6"),
        *fx.minutes(at(1, 48), at(2, 20), ".3"),
        *fx.minutes(at(2, 20), at(3), ".6"),
    )
    schedule = build_flow_schedule("BTCUSDT", minutes, START, at(3))
    # Bar 0 opens allowed and stays so; bar 1 opens allowed and blocks at its last
    # minute; bar 2 opens blocked: allowed 1, 1, 0 and withheld 0, 1, 1, LSB first.
    assert schedule == FlowSchedule("BTCUSDT", START, at(3), bytes([0b011]), bytes([0b110]), True)


def test_schedule_streams_months_in_order_and_refuses_out_of_order():
    minutes = FIXTURES["blocked_then_recovered"]
    cuts = [minutes[0].open_ms, START + DAY, START + 2 * DAY, END]
    months = [
        tuple(bar for bar in minutes if low <= bar.open_ms < high)
        for low, high in zip(cuts[:-1], cuts[1:], strict=True)
    ]
    read = []

    def archives(*order):
        """Each month's minutes, read once from a generator as an archive is streamed."""
        for month in order:
            read.append(month)
            yield from month

    streamed = build_flow_schedule("BTCUSDT", archives(*months), START, END)
    assert streamed == build_flow_schedule("BTCUSDT", minutes, START, END)
    assert read == months  # each month read once, in order
    swapped = archives(months[0], months[2], months[1])
    with pytest.raises(ValueError, match="minute bars in ascending order required"):
        build_flow_schedule("BTCUSDT", swapped, START, END)
    repeated = archives(months[0], months[0][-1:], months[1], months[2])
    with pytest.raises(ValueError, match="unique aligned minute bars required"):
        build_flow_schedule("BTCUSDT", repeated, START, END)
    shifted = replace(months[1][5], open_ms=months[1][5].open_ms + 1)
    misaligned = archives(months[0], (*months[1][:5], shifted, *months[1][6:]), months[2])
    with pytest.raises(ValueError, match="unique aligned minute bars required"):
        build_flow_schedule("BTCUSDT", misaligned, START, END)
    with pytest.raises(ValueError, match="minute klines required"):
        build_flow_schedule("BTCUSDT", archives(months[0], ("not a kline",)), START, END)


def test_schedule_refuses_a_sealed_minute():
    start, end = RESERVED - 3 * DAY, RESERVED - 2 * DAY
    minutes = fx.minutes(start - 15 * MINUTE, end)
    assert build_flow_schedule("BTCUSDT", minutes, start, end).present
    # Even after the window's end: data from the reserved boundary on is never skipped.
    sealed = (*minutes, *fx.minutes(RESERVED, RESERVED + MINUTE))
    with pytest.raises(ValueError, match="reserved"):
        build_flow_schedule("BTCUSDT", sealed, start, end)
    with pytest.raises(ValueError, match="reserved"):
        build_flow_schedule("BTCUSDT", minutes, start, RESERVED + HOUR)


@pytest.mark.parametrize(
    ("start", "end"), [(START + 1, END), (START, END + MINUTE), (END, START), (START, START)]
)
def test_schedule_refuses_a_window_that_is_not_whole_hours(start, end):
    with pytest.raises(ValueError, match="window"):
        build_flow_schedule("BTCUSDT", HEALTHY, start, end)


def test_schedule_is_read_only_at_its_own_window_hours():
    schedule = build_flow_schedule("BTCUSDT", HEALTHY, START, END)
    for stamp in (START - HOUR, END, START + MINUTE):
        with pytest.raises(ValueError, match="flow schedule"):
            schedule.allowed_at(stamp)
        with pytest.raises(ValueError, match="flow schedule"):
            schedule.withheld_at(stamp)


GRID_ARMS = [
    "spot_grid",
    "combined",
    "combined_without_continuation",
    "combined_without_full_short_qualification",
    "combined_without_discretionary_trailing",
    "combined_without_funding_admission",
    "combined_without_recovery",
]


def replayed_market(fixture):
    """A ranging market fed the fixture's minutes; the gap fixture also misses spot bar
    25, in which the first grid buy fills when the flow stays healthy."""
    market = replace(fx.market("BTCUSDT", fx.ranging, 3, futures=True), minutes=FIXTURES[fixture])
    if fixture != "gap_across_41_00":
        return market
    spot = tuple(bar for bar in market.spot.hourly if bar.open_ms != at(25))
    return replace(market, spot=replace(market.spot, hourly=spot), daily=fx.daily(spot))


@pytest.mark.parametrize(
    "fixture", ["gap_across_41_00", "collapse_at_25_05", "first_block_at_25_59", "none"]
)
@pytest.mark.parametrize("arm", GRID_ARMS)
def test_schedule_from_fixture_minutes_reproduces_the_minute_trace(arm, fixture):
    run = fx.run(arm, 3)
    fed_minutes = replayed_market(fixture)
    schedule = build_flow_schedule("BTCUSDT", iter(fed_minutes.minutes), START, END)
    fed_schedule = replace(fed_minutes, minutes=(), flow=schedule)
    expected = replay_strategy(run, (fed_minutes,))
    assert expected.failure is None
    assert replay_strategy(run, (fed_schedule,)) == expected
    # Each fixture reaches the replay: a basket's buys are withheld, or the coin is missing.
    if fixture == "none":
        assert expected.missing_grid_inputs == ("BTCUSDT",)
    else:
        assert expected.missing_grid_inputs == () and expected.withheld_buys
