"""Deterministic V3.1 input packs and their mechanically derived skipped hours.

Synthetic data only: hand-built decoded months, funding records and minute bars. No
archive is read and nothing touches the network.
"""

import gzip
import hashlib
import io
import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import Inexact, localcontext

import pytest

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.driver import packs
from crypto_grid_bot.combined.driver.decode import DecodedV31Month
from crypto_grid_bot.combined.driver.flow_schedule import build_flow_schedule
from crypto_grid_bot.combined.driver.packs import (
    build_coin_inputs,
    build_window_pack,
    check_window,
    derive_skipped_hours,
    minute_months,
    read_pack,
    skipped_hour_sources,
    write_pack,
)
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.strategy_replay import (
    ReplayRun,
    SymbolMarket,
    VenueMarket,
    replay_strategy,
)

HOUR = 3_600_000
DAY = 24 * HOUR
MINUTE = 60_000
RESERVED = 1_735_689_600_000
START = 1_625_097_600_000  # 2021-07-01 00:00 UTC
END = START + 3 * DAY
SPOT_RULES = VenueRules(D("0.001"), D("0"), D("1000"), D("5"), D("0.01"))
# Trailing zeros, as a saved snapshot gives them; a pack keeps each value's str().
FUTURES_RULES = VenueRules(D("0.0010"), D("0.001"), D("500"), D("5.0"), D("0.010"))
SOURCES = (
    ("v3-20261009/inventory.manifest.json", "a" * 64),
    ("v3-1-minute-bars.manifest.json", "b" * 64),
)
COINS = {"BTCUSDT": True, "ETHUSDT": True, "ADAUSDT": False}  # symbol: has futures


def month_start(month: str) -> int:
    return int(datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC).timestamp()) * 1000


def month_end(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    return month_start(f"{year + number // 12}-{number % 12 + 1:02d}")


def months(first: str, last: str) -> list[str]:
    result, month = [], first
    while month <= last:
        result.append(month)
        moved = datetime.fromtimestamp(month_end(month) // 1000, UTC)
        month = moved.strftime("%Y-%m")
    return result


def bar(open_ms: int) -> Kline:
    price = D(100 + open_ms // HOUR % 7)
    return Kline(open_ms, price, price + 1, price - 1, price, D("10.5"), D("1050.25"), D("5.125"))


def kline_month(kind, symbol, month, *, status="eligible", skip=()):
    hours = range(month_start(month), month_end(month), HOUR)
    return DecodedV31Month(
        kind,
        symbol,
        month,
        status,
        hourly=tuple(bar(t) for t in hours if t not in skip),
        missing_hours=frozenset(t for t in hours if t in skip),
    )


def funding_records(month, *, drop=()):
    return tuple(
        FundingRecord(t, 8, D("0.0001"))
        for t in range(month_start(month), month_end(month), 8 * HOUR)
        if t not in drop
    )


def funding_month(symbol, month, *, status="eligible", records=None, drop=()):
    if records is None:
        records = funding_records(month, drop=drop)
    return DecodedV31Month("funding", symbol, month, status, funding=records)


def minute_stream(start=START, end=END, *, skip=(), volume="10", taker="6"):
    """Minutes from the gate's first read minute to the window's end, as a stream."""
    for t in range(start - 15 * MINUTE, end, MINUTE):
        if t not in skip:
            yield Kline(t, D(100), D(100), D(100), D(100), D(volume), D(1000), D(taker))


def coin_args(symbol, *, start=START, end=END, spot_skip=(), futures_skip=(), minute_skip=(), **kw):
    """``build_coin_inputs`` arguments for the fixture window: the coin's 2021-06 spot
    month is excluded, so its history starts at the window."""
    futures = COINS[symbol]
    args = {
        "start_ms": start,
        "end_ms": end,
        "spot_months": (
            kline_month("spot", symbol, "2021-06", status="excluded"),
            kline_month("spot", symbol, "2021-07", skip=spot_skip),
        ),
        "futures_months": tuple(
            kline_month("futures", symbol, month, skip=futures_skip)
            for month in ("2021-06", "2021-07")
        )
        if futures
        else (),
        "funding_months": tuple(funding_month(symbol, m) for m in ("2021-06", "2021-07"))
        if futures
        else (),
        "minutes": minute_stream(start, end, skip=minute_skip),
        "spot_rules": SPOT_RULES,
        "futures_rules": FUTURES_RULES if futures else None,
    }
    args.update(kw)
    return args


def coin(symbol, **options):
    return build_coin_inputs(symbol, **coin_args(symbol, **options))


def pack(**options):
    """The fixture window's pack; each keyword maps a symbol to its ``coin_args`` options."""
    coins = [coin(symbol, **options.get(symbol, {})) for symbol in COINS]
    return build_window_pack("w-test", START, END, coins, SOURCES)


def eth_funding_with_odd_records():
    """ETH's funding with an invalid interval long before the window and a negative rate
    written with trailing zeros: both must survive the round trip as they are."""
    june = list(funding_records("2021-06"))
    june[3] = FundingRecord(june[3].calc_time_ms, None, D("0.0001"))
    june[-1] = FundingRecord(june[-1].calc_time_ms, 8, D("-0.00012500"))
    return (
        funding_month("ETHUSDT", "2021-06", records=tuple(june)),
        funding_month("ETHUSDT", "2021-07"),
    )


def test_pack_round_trips_and_is_byte_identical_on_rebuild(tmp_path):
    options = {"ETHUSDT": {"funding_months": eth_funding_with_odd_records()}}
    first, second = pack(**options), pack(**options)
    assert first == second

    digest = write_pack(first, tmp_path / "first.json.gz")
    again = write_pack(second, tmp_path / "second.json.gz")
    content = (tmp_path / "first.json.gz").read_bytes()
    assert content == (tmp_path / "second.json.gz").read_bytes()  # one zlib build
    # The pin is the canonical JSON's hash, whatever compressed it (Ruling P11).
    assert digest == again == hashlib.sha256(gzip.decompress(content)).hexdigest()
    # gzip header: deflate, no flags (so no file name), mtime 0.
    assert content[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00"

    read = read_pack(tmp_path / "first.json.gz", digest)
    assert read == first
    assert [c.symbol for c in read.coins] == ["ADAUSDT", "BTCUSDT", "ETHUSDT"]
    assert read.sources == tuple(sorted(SOURCES))
    eth = read.coins[2]
    assert str(eth.futures_rules.step) == "0.0010" and str(eth.futures_rules.tick) == "0.010"
    funding = {record.calc_time_ms: record for record in eth.funding}
    assert funding[month_start("2021-06") + DAY].interval_hours is None
    assert str(funding[START - 8 * HOUR].rate) == "-0.00012500"
    assert eth.flow == first.coins[2].flow and eth.flow.present
    assert read.coins[0].futures_rules is None and read.coins[0].funding == ()
    # Futures and funding start on the first day of the month before the window's.
    assert eth.futures_hourly[0].open_ms == eth.funding[0].calc_time_ms == month_start("2021-06")
    assert eth.spot_hourly[0].open_ms == eth.history_start_ms == START
    assert eth.daily == daily_bars(eth.spot_hourly) and len(eth.daily) == 3


def test_skipped_hours_are_the_union_of_all_sources():
    result = pack(
        BTCUSDT={
            "spot_skip": (START + 5 * HOUR,),
            "minute_skip": (START + 30 * HOUR + 30 * MINUTE,),  # not an opening minute
        },
        ETHUSDT={"futures_skip": (START + 5 * HOUR, START + 10 * HOUR)},
        ADAUSDT={"minute_skip": (START + 20 * HOUR,)},  # the opening minute of 20:00
    )
    expected = (START + 5 * HOUR, START + 10 * HOUR, START + 20 * HOUR)
    assert result.skipped_hours == expected
    assert derive_skipped_hours(START, END, result.coins) == expected
    with pytest.raises(ValueError, match="skipped hours"):
        check_window(replace(result, skipped_hours=expected[:2]))


def test_a_missing_final_minute_refuses_the_window():
    with pytest.raises(ValueError, match=f"ETHUSDT: .*{END - MINUTE}"):
        pack(ETHUSDT={"minute_skip": (END - MINUTE,)})


@pytest.mark.parametrize(
    ("symbol", "option", "hour"),
    [
        ("BTCUSDT", "spot_skip", START),
        ("ETHUSDT", "futures_skip", END - HOUR),
        ("ADAUSDT", "minute_skip", START),
        ("ADAUSDT", "minute_skip", END - HOUR),
    ],
)
def test_first_or_last_hour_gap_refuses_the_window(symbol, option, hour):
    gapped = coin(symbol, **{option: (hour,)})
    coins = [gapped, *(coin(other) for other in COINS if other != symbol)]
    assert derive_skipped_hours(START, END, coins) == ()  # never a skipped hour itself
    with pytest.raises(ValueError, match=f"{symbol}: .*window hour {hour}"):
        build_window_pack("w-test", START, END, coins, SOURCES)


def test_an_excluded_spot_month_refuses_the_window():
    spot = (
        kline_month("spot", "BTCUSDT", "2021-06", status="excluded"),
        kline_month("spot", "BTCUSDT", "2021-07", status="excluded"),
    )
    with pytest.raises(ValueError, match="BTCUSDT spot 2021-07: .*excluded"):
        coin("BTCUSDT", spot_months=spot)


def gzipped(content: bytes, level: int) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=level) as f:
        f.write(content)
    return buffer.getvalue()


def test_read_pack_refuses_a_wrong_hash(tmp_path):
    path = tmp_path / "w.json.gz"
    digest = write_pack(pack(), path)
    wrong = ("1" if digest[0] == "0" else "0") + digest[1:]
    with pytest.raises(ValueError, match=f"sha256 {digest} differs from the pinned {wrong}"):
        read_pack(path, wrong)
    junk = tmp_path / "junk.json.gz"
    junk.write_bytes(b"not a pack")
    with pytest.raises(ValueError, match="gzip"):
        read_pack(junk, digest)


def test_tampered_content_is_refused_before_it_is_parsed(tmp_path):
    path = tmp_path / "w.json.gz"
    digest = write_pack(pack(), path)
    content = gzip.decompress(path.read_bytes())
    # Valid JSON with one value changed, and bytes that are not JSON at all: both are
    # refused by the hash, so neither reaches the parser.
    for index, tampered in enumerate((content.replace(b'"w-test"', b'"w-tesT"'), b"{not json")):
        assert tampered != content
        other = tmp_path / f"tampered-{index}.json.gz"
        other.write_bytes(gzipped(tampered, 9))
        refusal = f"{re.escape(str(other))}: pack sha256 .* the pinned {digest}"
        with pytest.raises(ValueError, match=refusal):
            read_pack(other, digest)


def test_other_gzip_bytes_of_the_same_content_read_as_the_same_pack(tmp_path):
    built = pack()
    path = tmp_path / "w.json.gz"
    digest = write_pack(built, path)
    recompressed = gzipped(gzip.decompress(path.read_bytes()), 1)
    assert recompressed != path.read_bytes()  # as another zlib build's bytes would be
    other = tmp_path / "level-1.json.gz"
    other.write_bytes(recompressed)
    assert read_pack(other, digest) == built


def test_read_pack_refuses_content_over_the_size_cap(tmp_path, monkeypatch):
    built = pack()
    path = tmp_path / "w.json.gz"
    digest = write_pack(built, path)
    size = len(gzip.decompress(path.read_bytes()))
    assert packs.MAX_CONTENT_BYTES == 2 * 1024**3
    monkeypatch.setattr(packs, "MAX_CONTENT_BYTES", size)
    assert read_pack(path, digest) == built
    monkeypatch.setattr(packs, "MAX_CONTENT_BYTES", size - 1)
    with pytest.raises(ValueError, match=f"more than {size - 1} bytes"):
        read_pack(path, digest)


def test_history_starts_365_days_back_or_after_the_latest_excluded_spot_month():
    spot = tuple(kline_month("spot", "BTCUSDT", m) for m in months("2020-05", "2021-07"))
    btc = coin("BTCUSDT", spot_months=spot)
    assert month_start("2020-07") == START - 365 * DAY
    assert btc.history_start_ms == btc.spot_hourly[0].open_ms == month_start("2020-07")
    assert btc.spot_hourly[-1].open_ms == END - HOUR
    assert btc.daily == daily_bars(btc.spot_hourly) and len(btc.daily) == 368

    excluded = tuple(
        replace(m, status="excluded") if m.month in ("2020-06", "2020-09", "2020-11") else m
        for m in spot
    )
    btc = coin("BTCUSDT", spot_months=excluded)
    assert btc.history_start_ms == btc.spot_hourly[0].open_ms == month_start("2020-12")


def test_a_partial_first_month_is_judged_on_the_hours_the_pack_holds():
    start, end = START + 2 * DAY, START + 5 * DAY
    history = start - 365 * DAY  # 2020-07-03: 696 of the month's 744 hours are held
    assert history == month_start("2020-07") + 2 * DAY
    held = range(history + 7 * DAY, history + 12 * DAY, HOUR)  # 120 hours

    def spot(skip):
        return tuple(
            kline_month("spot", "BTCUSDT", m, skip=skip) for m in months("2020-07", "2021-07")
        )

    btc = coin("BTCUSDT", start=start, end=end, spot_months=spot(tuple(held)[:118]))
    assert btc.history_start_ms == btc.spot_hourly[0].open_ms == history
    build_window_pack("w-test", start, end, [btc], SOURCES)  # 118 of 696: under 17%
    # 120 of 744 would be under 17% too, but the pack holds only 696 of the month's hours.
    btc = coin("BTCUSDT", start=start, end=end, spot_months=spot(tuple(held)))
    with pytest.raises(ValueError, match="BTCUSDT spot 2020-07: 120 of 696 hours"):
        build_window_pack("w-test", start, end, [btc], SOURCES)


def test_a_spot_month_missing_over_17_percent_refuses_the_window():
    twelve = tuple(START + h * HOUR for h in range(30, 42))  # 12 of the window's 72 hours
    assert pack(BTCUSDT={"spot_skip": twelve}).skipped_hours == twelve
    with pytest.raises(ValueError, match="BTCUSDT spot 2021-07: 13 of 72 hours"):
        pack(BTCUSDT={"spot_skip": (*twelve, START + 42 * HOUR)})


@pytest.mark.parametrize(
    ("key", "month"),
    [
        ("spot_months", "2021-07"),
        ("futures_months", "2021-06"),
        ("futures_months", "2021-07"),
        ("funding_months", "2021-06"),
    ],
)
def test_a_month_not_supplied_refuses_the_window(key, month):
    args = coin_args("BTCUSDT")
    args[key] = tuple(m for m in args[key] if m.month != month)
    kind = key.removesuffix("_months")
    with pytest.raises(ValueError, match=f"BTCUSDT {kind} {month}: .*not supplied"):
        build_coin_inputs("BTCUSDT", **args)


def test_an_excluded_futures_month_is_dropped_before_the_window_and_refused_inside():
    june, july = (kline_month("futures", "BTCUSDT", m) for m in ("2021-06", "2021-07"))
    btc = coin("BTCUSDT", futures_months=(replace(june, status="excluded"), july))
    assert btc.futures_hourly == tuple(b for b in july.hourly if b.open_ms < END)
    with pytest.raises(ValueError, match="BTCUSDT futures 2021-07: .*excluded"):
        coin("BTCUSDT", futures_months=(june, replace(july, status="excluded")))


def test_excluded_funding_months_are_kept_with_their_own_intervals():
    # The cadence changes from 8h to 4h a day into the window, in an excluded month.
    july = tuple(FundingRecord(START + k * 8 * HOUR, 8, D("0.0001")) for k in range(3)) + tuple(
        FundingRecord(t, 4, D("0.0002")) for t in range(START + DAY, month_end("2021-07"), 4 * HOUR)
    )
    june = funding_month("BTCUSDT", "2021-06", status="excluded")
    btc = coin(
        "BTCUSDT",
        funding_months=(june, funding_month("BTCUSDT", "2021-07", status="excluded", records=july)),
    )
    assert btc.funding == june.funding + tuple(r for r in july if r.calc_time_ms < END)
    build_window_pack("w-test", START, END, [btc], SOURCES)


@pytest.mark.parametrize("latest", ["none", "invalid"])
def test_a_futures_coin_needs_a_valid_funding_record_usable_at_the_start(latest):
    june = funding_records("2021-06")
    if latest == "none":
        june = ()  # 2021-07-01 00:00 itself is usable only a minute later
    else:
        june = (*june[:-1], FundingRecord(june[-1].calc_time_ms, None, D("0.0001")))
    btc = coin(
        "BTCUSDT",
        funding_months=(
            funding_month("BTCUSDT", "2021-06", records=june),
            funding_month("BTCUSDT", "2021-07"),
        ),
    )
    with pytest.raises(ValueError, match="BTCUSDT: no valid funding record usable at the window"):
        build_window_pack("w-test", START, END, [btc], SOURCES)


def test_a_missing_funding_settlement_inside_the_window_refuses_it():
    slot = START + 16 * HOUR
    btc = coin(
        "BTCUSDT",
        funding_months=(
            funding_month("BTCUSDT", "2021-06"),
            funding_month("BTCUSDT", "2021-07", drop=(slot,)),
        ),
    )
    with pytest.raises(ValueError, match=f"BTCUSDT: .*funding settlement.*{slot}"):
        build_window_pack("w-test", START, END, [btc], SOURCES)


def test_a_coin_without_futures_needs_no_futures_inputs():
    ada = coin("ADAUSDT")
    assert (ada.futures_hourly, ada.funding, ada.futures_rules) == ((), (), None)
    with pytest.raises(ValueError, match="ADAUSDT: .*without futures rules"):
        coin("ADAUSDT", funding_months=(funding_month("ADAUSDT", "2021-06"),))


def test_nothing_at_or_after_2025_enters_a_pack():
    with pytest.raises(ValueError, match="reserved"):
        coin("BTCUSDT", end=RESERVED + DAY)
    with pytest.raises(ValueError, match="reserved"):
        build_window_pack("w-test", START, RESERVED + DAY, [coin("BTCUSDT")], SOURCES)
    sealed = DecodedV31Month("spot", "BTCUSDT", "2025-01", "eligible")
    args = coin_args("BTCUSDT")
    with pytest.raises(ValueError, match="BTCUSDT spot 2025-01: .*reserved"):
        build_coin_inputs("BTCUSDT", **{**args, "spot_months": (*args["spot_months"], sealed)})

    def into_2025():
        yield from minute_stream()
        yield Kline(RESERVED, D(1), D(1), D(1), D(1), D(1), D(1), D(1))

    with pytest.raises(ValueError, match="reserved"):
        coin("BTCUSDT", minutes=into_2025())


def test_minutes_outside_the_window_minute_months_are_refused():
    assert minute_months(START, END) == ("2021-06", "2021-07")
    assert minute_months(START + DAY, END) == ("2021-07",)
    w1 = minute_months(START, RESERVED)
    assert (w1[0], w1[-1], len(w1)) == ("2021-06", "2024-12", 43)
    early = Kline(month_start("2021-05"), D(1), D(1), D(1), D(1), D(1), D(1), D(1))
    with pytest.raises(ValueError, match="BTCUSDT: minute .*outside"):
        coin("BTCUSDT", minutes=(early, *minute_stream()))
    late = replace(early, open_ms=month_start("2021-08"))
    with pytest.raises(ValueError, match="BTCUSDT: minute .*outside"):
        coin("BTCUSDT", minutes=(*minute_stream(), late))


def test_the_flow_schedule_is_built_in_a_fresh_decimal_context():
    # A share of 2/3 is inexact: a caller's context that traps it must not reach the gate.
    expected = coin("BTCUSDT", minutes=minute_stream(volume="3", taker="2"))
    with localcontext() as context:
        context.traps[Inexact] = True
        with pytest.raises(Inexact):
            build_flow_schedule("BTCUSDT", minute_stream(volume="3", taker="2"), START, END)
        assert coin("BTCUSDT", minutes=minute_stream(volume="3", taker="2")) == expected
    assert expected.flow.allowed_at(START + HOUR)


def test_write_pack_refuses_an_existing_file(tmp_path):
    path = tmp_path / "w.json.gz"
    path.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        write_pack(pack(), path)
    assert path.read_bytes() == b"keep"


def test_build_window_pack_refuses_a_coin_of_another_window_and_bad_sources():
    btc = coin("BTCUSDT")
    with pytest.raises(ValueError, match="BTCUSDT: .*another window"):
        build_window_pack("w-test", START, END, [coin("BTCUSDT", start=START + DAY)], SOURCES)
    with pytest.raises(ValueError, match="duplicate"):
        build_window_pack("w-test", START, END, [btc, btc], SOURCES)
    with pytest.raises(ValueError, match="source"):
        build_window_pack("w-test", START, END, [btc], (*SOURCES, SOURCES[0]))
    with pytest.raises(ValueError, match="source"):
        build_window_pack("w-test", START, END, [btc], (("m.json", "A" * 64),))


def test_gzip_payload_is_canonical_json(tmp_path):
    path = tmp_path / "w.json.gz"
    write_pack(pack(), path)
    text = gzip.decompress(path.read_bytes()).decode("ascii")
    assert ": " not in text and ", " not in text  # fixed separators
    assert '"step":"0.0010"' in text  # Decimals as their str()


def test_the_replay_accepts_a_packs_inputs_with_pre_window_futures_and_funding():
    def market(c):
        futures = None
        if c.futures_rules is not None:
            futures = VenueMarket(c.futures_hourly, c.futures_rules, cost_profile(1, "futures"))
        spot = VenueMarket(c.spot_hourly, c.spot_rules, cost_profile(1, "spot"))
        return SymbolMarket(c.symbol, spot, c.daily, futures, c.funding, flow=c.flow)

    coins = pack().coins
    with_futures = tuple(market(c) for c in coins if c.futures_rules is not None)
    assert all(m.futures.hourly[0].open_ms < START for m in with_futures)
    assert all(m.funding[0].calc_time_ms < START for m in with_futures)
    for arm, markets in (("combined", with_futures), ("spot_grid", tuple(map(market, coins)))):
        run = ReplayRun(arm, "open_low_high_close", D(10000), START, END, ("pack:synthetic",))
        trace = replay_strategy(run, markets)
        assert trace.missing_grid_inputs == () and trace.data_gaps == ()


# --- labelled extra missing-hour sources (Rulings P16, P17) ----------------------------

EXTRA = {
    "minute_mask:BTCUSDT": (START + 7 * HOUR, START + 5 * HOUR, START + 7 * HOUR),
    "quote_test:XRPUSDT": (START + 9 * HOUR,),
    "minute_mask:ETHUSDT": (),
}


def test_extra_missing_hour_sources_join_the_skipped_hours(tmp_path):
    base = pack(BTCUSDT={"spot_skip": (START + 5 * HOUR,)})
    joined = build_window_pack("w-test", START, END, base.coins, SOURCES, extra_missing_hours=EXTRA)
    # The union of the derived gaps and every labelled source, each hour once.
    assert joined.skipped_hours == (START + 5 * HOUR, START + 7 * HOUR, START + 9 * HOUR)
    # Each source is kept, sorted by label, its hours sorted and unique; an empty one too.
    assert joined.extra_missing_hours == (
        ("minute_mask:BTCUSDT", (START + 5 * HOUR, START + 7 * HOUR)),
        ("minute_mask:ETHUSDT", ()),
        ("quote_test:XRPUSDT", (START + 9 * HOUR,)),
    )
    assert derive_skipped_hours(START, END, base.coins, joined.extra_missing_hours) == (
        joined.skipped_hours
    )
    # Disclosed per source: the coins' own gaps and the extra sources, by label.
    assert skipped_hour_sources(joined) == (
        ("BTCUSDT: no spot bar", (START + 5 * HOUR,)),
        ("minute_mask:BTCUSDT", (START + 5 * HOUR, START + 7 * HOUR)),
        ("minute_mask:ETHUSDT", ()),
        ("quote_test:XRPUSDT", (START + 9 * HOUR,)),
    )
    # The sources travel with the pack and are pinned with it.
    pin = write_pack(joined, tmp_path / "joined.json.gz")
    assert read_pack(tmp_path / "joined.json.gz", pin) == joined
    assert pin != write_pack(base, tmp_path / "base.json.gz")
    # A pack whose skipped hours drop a source's hour, or that lost its sources, is refused.
    with pytest.raises(ValueError, match="skipped hours"):
        check_window(replace(joined, skipped_hours=base.skipped_hours))
    with pytest.raises(ValueError, match="skipped hours"):
        check_window(replace(joined, extra_missing_hours=()))


def test_a_pack_without_extra_sources_is_unchanged(tmp_path):
    base = pack(BTCUSDT={"spot_skip": (START + 5 * HOUR,)})
    again = build_window_pack("w-test", START, END, base.coins, SOURCES, extra_missing_hours={})
    assert again == base and base.extra_missing_hours == ()
    assert skipped_hour_sources(base) == (("BTCUSDT: no spot bar", (START + 5 * HOUR,)),)
    write_pack(base, tmp_path / "base.json.gz")
    text = gzip.decompress((tmp_path / "base.json.gz").read_bytes()).decode("ascii")
    assert "extra_missing_hours" not in text  # the document, so the pin, is as before


@pytest.mark.parametrize("hour", [START, END - HOUR])
def test_an_extra_source_at_the_first_or_last_hour_refuses_the_window(hour):
    coins = pack().coins
    with pytest.raises(ValueError, match=f"minute_mask:XRPUSDT: .*window hour {hour}"):
        build_window_pack(
            "w-test",
            START,
            END,
            coins,
            SOURCES,
            extra_missing_hours={"minute_mask:XRPUSDT": (hour,)},
        )


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"minute_mask:BTCUSDT": (START - HOUR,)}, "inside the window"),
        ({"minute_mask:BTCUSDT": (END,)}, "inside the window"),
        ({"minute_mask:BTCUSDT": (START + 5 * HOUR + MINUTE,)}, "whole hours"),
        ({"minute_mask:BTCUSDT": (float(START + 5 * HOUR),)}, "whole hours"),
        ({" ": (START + 5 * HOUR,)}, "label"),
        ((("a", (START + 5 * HOUR,)), ("a", ())), "label"),
    ],
)
def test_malformed_extra_sources_are_refused(extra, message):
    with pytest.raises(ValueError, match=message):
        build_window_pack("w-test", START, END, pack().coins, SOURCES, extra_missing_hours=extra)
