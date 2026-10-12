"""One deterministic input pack per V3.1 test window, and the window's skipped hours.

A pack holds what every run job of a window replays, per coin: the spot hourly history
and the futures hourly bars, the daily bars (V3's day rule), the funding records, the
venue rules and the flow schedule. It is built from decoded months (``driver.decode``),
minute bars streamed once into the flow schedule (``driver.flow_schedule``) and venue
rules (``driver.venues``), and written as gzip JSON whose bytes depend only on the pack,
so its SHA-256 can be pinned. The skipped hours are derived from the same inputs, and
``check_window`` refuses a window that breaks the registration checklist.

Pure: nothing here touches the network, and nothing at or after the reserved boundary
enters a pack.
"""

import gzip
import hashlib
import io
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.baseline_records import refuse_sealed
from crypto_grid_bot.combined.driver.decode import DecodedV31Month
from crypto_grid_bot.combined.driver.flow_schedule import FlowSchedule, build_flow_schedule
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.strategy_replay import _funding, _schedule_gaps
from crypto_grid_bot.market_data.parsing import symbol_name

HOUR = 3_600_000
DAY = 24 * HOUR
_MINUTE = 60_000
_LOOK_BACK = 15 * _MINUTE  # the flow gate's first read minute, before the window start
_HISTORY = 365 * DAY  # the longest spot history a pack holds (Ruling P7)
_RESERVED = 1_735_689_600_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_FORMAT = "v3.1-input-pack/1"
_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HEX = re.compile(r"(?:[0-9a-f]{2})*")
_WINDOW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_KLINE_DECIMALS = tuple(f.name for f in fields(Kline) if f.name != "open_ms")
_RULES = tuple(f.name for f in fields(VenueRules))
_FLOW_KEYS = frozenset({"symbol", "start_ms", "end_ms", "open_allowed", "withheld", "present"})
_COIN_KEYS = frozenset(
    {
        "symbol",
        "history_start_ms",
        "spot_hourly",
        "futures_hourly",
        "daily",
        "funding",
        "spot_rules",
        "futures_rules",
        "flow",
        "opening_minute_gaps",
        "final_minute",
    }
)
_PACK_KEYS = frozenset(
    {"format", "window_id", "start_ms", "end_ms", "coins", "skipped_hours", "sources"}
)


@dataclass(frozen=True, slots=True)
class CoinInputs:
    """One coin's registered inputs for one window (Ruling P7).

    ``spot_hourly`` covers ``[history_start_ms, end)`` and ``daily`` is
    ``daily_bars(spot_hourly)``. ``futures_hourly`` and ``funding`` start on the first
    day of the month before the window's, so ``funding`` holds the latest record
    published before it; a coin without futures in the window has neither, and no
    ``futures_rules``. ``opening_minute_gaps`` are the window hours whose opening minute
    has no bar and ``final_minute`` whether the window's last minute has one, both noted
    while the minutes streamed into ``flow``.
    """

    symbol: str
    history_start_ms: int
    spot_hourly: tuple[Kline, ...]
    futures_hourly: tuple[Kline, ...]
    daily: tuple[Kline, ...]
    funding: tuple[FundingRecord, ...]
    spot_rules: VenueRules
    futures_rules: VenueRules | None
    flow: FlowSchedule
    opening_minute_gaps: tuple[int, ...]
    final_minute: bool


@dataclass(frozen=True, slots=True)
class WindowPack:
    """Every input of one window's runs: ``coins`` sorted by symbol, the derived skipped
    hours, and ``sources``, the data manifests as (name, SHA-256) sorted by name."""

    window_id: str
    start_ms: int
    end_ms: int
    coins: tuple[CoinInputs, ...]
    skipped_hours: tuple[int, ...]
    sources: tuple[tuple[str, str], ...]


def minute_months(start_ms: int, end_ms: int) -> tuple[str, ...]:
    """The months of minute bars a window's flow schedule reads, oldest first: those
    covering ``[start - 15 min, end)``. ``build_coin_inputs`` refuses any other minute."""
    _window(start_ms, end_ms)
    return _months(start_ms - _LOOK_BACK, end_ms)


def build_coin_inputs(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    spot_months: Iterable[DecodedV31Month],
    futures_months: Iterable[DecodedV31Month],
    funding_months: Iterable[DecodedV31Month],
    minutes: Iterable[Kline],
    spot_rules: VenueRules,
    futures_rules: VenueRules | None,
) -> CoinInputs:
    """One coin's inputs for the window ``[start_ms, end_ms)`` (Ruling P7).

    The spot history starts 365 days before the window, or on the first day after the
    coin's latest excluded spot month before it if that is later. Futures bars and
    funding start on the first day of the month before the window's. Every month of each
    range must be supplied, decoded; months outside the ranges are not read. An excluded
    spot month in the range refuses the window, as does an excluded futures month inside
    it; one before the window is dropped. Excluded funding months are kept, every record
    with its own interval. A coin without futures in the window passes no futures or
    funding months and ``futures_rules=None``.

    ``minutes`` is streamed once into the flow schedule, under a fresh default decimal
    context, and must hold only the months ``minute_months`` names.
    """
    symbol_name(symbol)
    _window(start_ms, end_ms)
    if not isinstance(spot_rules, VenueRules):
        raise ValueError(f"{symbol}: spot venue rules required")
    spot = _supplied(symbol, "spot", spot_months)
    futures = _supplied(symbol, "futures", futures_months)
    funding = _supplied(symbol, "funding", funding_months)
    history_start = _history_start(spot, start_ms)
    spot_hourly = _bars(symbol, "spot", spot, history_start, start_ms, end_ms)
    futures_hourly: tuple[Kline, ...] = ()
    records: tuple[FundingRecord, ...] = ()
    if futures_rules is None:
        if futures or funding:
            raise ValueError(f"{symbol}: futures or funding months without futures rules")
    elif not isinstance(futures_rules, VenueRules):
        raise ValueError(f"{symbol}: futures venue rules or None required")
    else:
        first = _month_start(_month_start(start_ms) - 1)
        futures_hourly = _bars(symbol, "futures", futures, first, start_ms, end_ms)
        records = _records(symbol, funding, first, end_ms)
    watch = _MinuteWatch(symbol, start_ms, end_ms)
    with localcontext(Context()):
        flow = build_flow_schedule(symbol, watch.stream(minutes), start_ms, end_ms)
        daily = daily_bars(spot_hourly)
    return CoinInputs(
        symbol,
        history_start,
        spot_hourly,
        futures_hourly,
        daily,
        records,
        spot_rules,
        futures_rules,
        flow,
        watch.gaps(),
        watch.final,
    )


def build_window_pack(
    window_id: str,
    start_ms: int,
    end_ms: int,
    coins: Iterable[CoinInputs],
    sources: Iterable[tuple[str, str]],
) -> WindowPack:
    """The window's pack: coins sorted by symbol, sources by name and the skipped hours
    derived. ``check_window`` refuses it if it breaks the registration checklist."""
    if not isinstance(window_id, str) or _WINDOW_ID.fullmatch(window_id) is None:
        raise ValueError(f"window id {window_id!r}: 1-64 letters, digits, '.', '_' or '-'")
    _window(start_ms, end_ms)
    listed = tuple(coins)
    if not listed or any(not isinstance(coin, CoinInputs) for coin in listed):
        raise ValueError(f"{window_id}: coin inputs required")
    ordered = tuple(sorted(listed, key=lambda coin: coin.symbol))
    symbols = [coin.symbol for coin in ordered]
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{window_id}: duplicate coin inputs")
    skipped = derive_skipped_hours(start_ms, end_ms, ordered)
    pack = WindowPack(window_id, start_ms, end_ms, ordered, skipped, _sources(sources))
    check_window(pack)
    return pack


def derive_skipped_hours(
    start_ms: int, end_ms: int, coins: Iterable[CoinInputs]
) -> tuple[int, ...]:
    """The window's skipped hours, ascending: every hour some coin has no spot bar at,
    no futures bar at (a coin with futures) or no opening minute at, restricted to
    ``start < h < end - 1h``. ``check_window`` refuses a gap at the first or last hour."""
    hours: set[int] = set()
    for coin in coins:
        hours.update(_gaps(coin, start_ms, end_ms))
    return tuple(sorted(hour for hour in hours if start_ms < hour < end_ms - HOUR))


def check_window(pack: WindowPack) -> None:
    """Refuse, with a ``ValueError`` naming the coin and the hour, slot or month, a
    window that breaks the registration checklist:

    - its first or last hour would need skipping;
    - a coin's minutes lack the final in-window minute (``end - 1 min``);
    - a spot month from the coin's history start to the end misses more than 17% of its
      hours, V3's exclusion rule (a month the pack holds in part is judged on the hours
      it holds);
    - a coin with futures has no valid funding record usable at the start, funding the
      replay refuses, or a settlement missing inside the window by the replay's rule.

    Inputs built for another window, and skipped hours other than the derived ones, are
    refused too.
    """
    if not isinstance(pack, WindowPack):
        raise ValueError("window pack required")
    start, end = pack.start_ms, pack.end_ms
    for coin in pack.coins:
        flow = coin.flow
        if (flow.symbol, flow.start_ms, flow.end_ms) != (coin.symbol, start, end):
            raise ValueError(f"{coin.symbol}: inputs built for another window")
        gaps = _gaps(coin, start, end)
        for hour, which in ((start, "first"), (end - HOUR, "last")):
            if hour in gaps:
                raise ValueError(
                    f"{coin.symbol}: the {which} window hour {hour} would need skipping "
                    f"({', '.join(gaps[hour])})"
                )
        if not coin.final_minute:
            raise ValueError(
                f"{coin.symbol}: no minute bar at {end - _MINUTE}, the final in-window minute"
            )
        _check_spot_months(coin, end)
        if coin.futures_rules is not None:
            _check_funding(coin, start, end)
    if pack.skipped_hours != derive_skipped_hours(start, end, pack.coins):
        raise ValueError(f"{pack.window_id}: the skipped hours differ from the derived ones")


def write_pack(pack: WindowPack, path: str | Path) -> str:
    """Write ``pack`` to a new file at ``path`` and return the file's SHA-256 (hex).

    The file is gzip JSON whose bytes depend only on the pack: sorted keys, fixed
    separators, ASCII, Decimals as their ``str()``, flow bitsets as hex, and a gzip header
    with mtime 0 and no file name. An existing file is refused, never replaced.
    """
    if not isinstance(pack, WindowPack):
        raise ValueError("window pack required")
    with localcontext(Context()):  # str() reads the context's exponent letter case
        document = _pack_document(pack)
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as archive:
        archive.write(text.encode("ascii"))
    content = buffer.getvalue()
    with open(path, "xb") as handle:
        handle.write(content)
    return hashlib.sha256(content).hexdigest()


def read_pack(path: str | Path, expected_sha256: str) -> WindowPack:
    """The pack at ``path``, rebuilt equal to the one written; the file's SHA-256 must
    equal ``expected_sha256``, checked before any byte is parsed. A duplicate JSON key,
    a non-integer number or a field out of place is refused."""
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("the expected pack sha256 must be 64 lowercase hex digits")
    content = Path(path).read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{path}: pack sha256 {actual} differs from the pinned {expected_sha256}")
    document = json.loads(
        gzip.decompress(content),
        object_pairs_hook=_unique_keys,
        parse_float=_not_an_integer,
        parse_constant=_not_an_integer,
    )
    with localcontext(Context()):
        return _pack_from(document)


def _window(start_ms: int, end_ms: int) -> None:
    if (
        type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms % DAY
        or end_ms % DAY
        or not 0 <= start_ms < end_ms <= _RESERVED
    ):
        raise ValueError("a pre-reserved window of whole UTC days required")


def _month_of(stamp: int) -> str:
    return (_EPOCH + timedelta(milliseconds=stamp)).strftime("%Y-%m")


def _month_start(stamp: int) -> int:
    """The first millisecond of the month holding ``stamp``."""
    return month_bounds_ms(_month_of(stamp))[0]


def _months(first: int, end: int) -> tuple[str, ...]:
    """The calendar months overlapping ``[first, end)``, oldest first."""
    months: list[str] = []
    while first < end:
        month = _month_of(first)
        months.append(month)
        first = month_bounds_ms(month)[1]
    return tuple(months)


def _supplied(
    symbol: str, kind: str, months: Iterable[DecodedV31Month]
) -> dict[str, DecodedV31Month]:
    """``months`` by month: each this coin's, of ``kind``, eligible or excluded, before
    the reserved boundary, holding only its own month's data, and supplied once."""
    by_month: dict[str, DecodedV31Month] = {}
    for month in months:
        if not isinstance(month, DecodedV31Month) or (month.kind, month.symbol) != (kind, symbol):
            raise ValueError(f"{symbol}: decoded {kind} months of this coin required")
        label = f"{symbol} {kind} {month.month}"
        if not isinstance(month.month, str) or _MONTH.fullmatch(month.month) is None:
            raise ValueError(f"{label}: month must be YYYY-MM")
        if month.status not in ("eligible", "excluded"):
            raise ValueError(f"{label}: an eligible or excluded month required")
        if month.month in by_month:
            raise ValueError(f"{label}: month supplied twice")
        first, end = month_bounds_ms(month.month)
        rows = month.funding if kind == "funding" else month.hourly
        other = month.hourly if kind == "funding" else month.funding
        kept = FundingRecord if kind == "funding" else Kline
        if other or any(not isinstance(row, kept) for row in rows):
            raise ValueError(f"{label}: {kind} data required")
        stamps = [
            row.calc_time_ms if isinstance(row, FundingRecord) else row.open_ms for row in rows
        ]
        refuse_sealed([first, *stamps], label)
        if any(not first <= stamp < end for stamp in stamps):
            raise ValueError(f"{label}: data outside its month")
        if kind != "funding" and (
            any(stamp % HOUR for stamp in stamps) or len(set(stamps)) != len(stamps)
        ):
            raise ValueError(f"{label}: unique hourly bars required")
        by_month[month.month] = month
    return by_month


def _history_start(spot: dict[str, DecodedV31Month], start: int) -> int:
    """365 days before ``start``, or the first day after the latest excluded spot month
    before it if that is later (Ruling P7)."""
    after = [
        end
        for month, decoded in spot.items()
        if decoded.status == "excluded" and (end := month_bounds_ms(month)[1]) <= start
    ]
    return max([start - _HISTORY, *after])


def _required(
    symbol: str, kind: str, supplied: dict[str, DecodedV31Month], first: int, end: int
) -> list[DecodedV31Month]:
    """The months covering ``[first, end)``, oldest first; every one must be supplied."""
    months = _months(first, end)
    absent = [month for month in months if month not in supplied]
    if absent:
        more = f" (and {len(absent) - 1} more)" if len(absent) > 1 else ""
        raise ValueError(f"{symbol} {kind} {absent[0]}: month not supplied{more}")
    return [supplied[month] for month in months]


def _bars(
    symbol: str,
    kind: str,
    supplied: dict[str, DecodedV31Month],
    first: int,
    start: int,
    end: int,
) -> tuple[Kline, ...]:
    """The bars of ``[first, end)``, ascending. An excluded spot month refuses the
    window; an excluded futures month is dropped before the window, refused inside it."""
    rows: list[Kline] = []
    for month in _required(symbol, kind, supplied, first, end):
        if month.status == "excluded":
            if kind == "futures" and month_bounds_ms(month.month)[1] <= start:
                continue
            where = "inside the window" if kind == "futures" else "in the window or its history"
            raise ValueError(f"{symbol} {kind} {month.month}: an excluded month {where}")
        rows.extend(bar for bar in month.hourly if first <= bar.open_ms < end)
    return tuple(sorted(rows, key=lambda bar: bar.open_ms))


def _records(
    symbol: str, supplied: dict[str, DecodedV31Month], first: int, end: int
) -> tuple[FundingRecord, ...]:
    """Every funding record of ``[first, end)``, excluded months included, ascending."""
    records = sorted(
        (
            record
            for month in _required(symbol, "funding", supplied, first, end)
            for record in month.funding
            if record.calc_time_ms < end
        ),
        key=lambda record: record.calc_time_ms,
    )
    times = [record.calc_time_ms for record in records]
    if len(set(times)) != len(times):
        raise ValueError(f"{symbol}: duplicate funding record")
    return tuple(records)


class _MinuteWatch:
    """Notes, as the minutes stream past, which window hours have their opening minute
    and whether the final minute came; it holds no bar. A minute outside the window's
    minute months, or at or after the reserved boundary, is refused."""

    def __init__(self, symbol: str, start: int, end: int) -> None:
        self.symbol, self.start, self.end = symbol, start, end
        self.first = _month_start(start - _LOOK_BACK)
        self.last = month_bounds_ms(_month_of(end - 1))[1]
        self.opened: set[int] = set()
        self.final = False

    def stream(self, minutes: Iterable[Kline]) -> Iterator[Kline]:
        for bar in minutes:
            if isinstance(bar, Kline) and type(bar.open_ms) is int:
                stamp = bar.open_ms
                refuse_sealed((stamp,), f"{self.symbol} minutes")
                if not self.first <= stamp < self.last:
                    raise ValueError(
                        f"{self.symbol}: minute {stamp} is outside the window's minute months"
                    )
                if self.start <= stamp < self.end and stamp % HOUR == 0:
                    self.opened.add(stamp)
                self.final = self.final or stamp == self.end - _MINUTE
            yield bar  # anything else is the flow schedule's to refuse

    def gaps(self) -> tuple[int, ...]:
        return tuple(h for h in range(self.start, self.end, HOUR) if h not in self.opened)


def _gaps(coin: CoinInputs, start: int, end: int) -> dict[int, list[str]]:
    """Each window hour the coin has a gap at, with what it lacks there."""
    venues = [("spot", coin.spot_hourly)]
    if coin.futures_rules is not None:
        venues.append(("futures", coin.futures_hourly))
    gaps: dict[int, list[str]] = {}
    for venue, bars in venues:
        present = {bar.open_ms for bar in bars if start <= bar.open_ms < end}
        for hour in range(start, end, HOUR):
            if hour not in present:
                gaps.setdefault(hour, []).append(f"no {venue} bar")
    for hour in coin.opening_minute_gaps:
        gaps.setdefault(hour, []).append("no opening minute")
    return gaps


def _check_spot_months(coin: CoinInputs, end: int) -> None:
    """V3's exclusion rule on every spot month from the history start to ``end``."""
    present = {bar.open_ms for bar in coin.spot_hourly}
    for month in _months(coin.history_start_ms, end):
        first, stop = month_bounds_ms(month)
        hours = range(max(first, coin.history_start_ms), min(stop, end), HOUR)
        missing = sum(1 for hour in hours if hour not in present)
        if missing * 100 > len(hours) * 17:
            raise ValueError(
                f"{coin.symbol} spot {month}: {missing} of {len(hours)} hours missing, over 17%"
            )


def _check_funding(coin: CoinInputs, start: int, end: int) -> None:
    """The funding a futures coin's replay reads at the start and settles in the window."""
    usable = [record for record in coin.funding if record.usable_ms <= start]
    if not usable or not max(usable, key=lambda record: record.calc_time_ms).valid:
        raise ValueError(f"{coin.symbol}: no valid funding record usable at the window start")
    needed, _ = _funding(coin.funding, start, end, coin.symbol)
    missing, _ = _schedule_gaps(needed, start, end)
    if missing:
        raise ValueError(
            f"{coin.symbol}: {len(missing)} funding settlement slot(s) missing inside the "
            f"window, the first at {min(missing)}"
        )


def _text(value: Decimal) -> str:
    if not isinstance(value, Decimal):
        raise ValueError("pack values must be Decimals")
    return str(value)


def _kline_row(bar: Kline) -> list[object]:
    return [bar.open_ms, *(_text(getattr(bar, name)) for name in _KLINE_DECIMALS)]


def _rules_document(rules: VenueRules) -> dict[str, object]:
    return {name: _text(getattr(rules, name)) for name in _RULES}


def _pack_document(pack: WindowPack) -> dict[str, object]:
    return {
        "format": _FORMAT,
        "window_id": pack.window_id,
        "start_ms": pack.start_ms,
        "end_ms": pack.end_ms,
        "skipped_hours": list(pack.skipped_hours),
        "sources": [list(source) for source in pack.sources],
        "coins": [_coin_document(coin) for coin in pack.coins],
    }


def _coin_document(coin: CoinInputs) -> dict[str, object]:
    flow = coin.flow
    return {
        "symbol": coin.symbol,
        "history_start_ms": coin.history_start_ms,
        "spot_hourly": [_kline_row(bar) for bar in coin.spot_hourly],
        "futures_hourly": [_kline_row(bar) for bar in coin.futures_hourly],
        "daily": [_kline_row(bar) for bar in coin.daily],
        "funding": [[r.calc_time_ms, r.interval_hours, _text(r.rate)] for r in coin.funding],
        "spot_rules": _rules_document(coin.spot_rules),
        "futures_rules": None
        if coin.futures_rules is None
        else _rules_document(coin.futures_rules),
        "flow": {
            "symbol": flow.symbol,
            "start_ms": flow.start_ms,
            "end_ms": flow.end_ms,
            "open_allowed": flow.open_allowed.hex(),
            "withheld": flow.withheld.hex(),
            "present": flow.present,
        },
        "opening_minute_gaps": list(coin.opening_minute_gaps),
        "final_minute": coin.final_minute,
    }


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"pack: duplicate JSON key {key!r}")
        result[key] = value
    return result


def _not_an_integer(text: str) -> object:
    raise ValueError(f"pack: {text} is not an integer")


def _object(value: object, keys: frozenset[str], what: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"pack {what}: the fields {sorted(keys)} required")
    return value


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"pack {what}: a list required")
    return value


def _int(value: object, what: str) -> int:
    if type(value) is not int:
        raise ValueError(f"pack {what}: an integer required")
    return value


def _bool(value: object, what: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"pack {what}: true or false required")
    return value


def _str(value: object, what: str) -> str:
    if type(value) is not str:
        raise ValueError(f"pack {what}: a string required")
    return value


def _decimal(value: object, what: str) -> Decimal:
    try:
        return Decimal(_str(value, what))
    except InvalidOperation as exc:
        raise ValueError(f"pack {what}: a decimal string required") from exc


def _bytes(value: object, what: str) -> bytes:
    text = _str(value, what)
    if _HEX.fullmatch(text) is None:
        raise ValueError(f"pack {what}: lowercase hex required")
    return bytes.fromhex(text)


def _kline_from(row: object, what: str) -> Kline:
    items = _list(row, what)
    if len(items) != 1 + len(_KLINE_DECIMALS):
        raise ValueError(f"pack {what}: {1 + len(_KLINE_DECIMALS)} kline fields required")
    return Kline(_int(items[0], what), *(_decimal(item, what) for item in items[1:]))


def _klines(value: object, what: str) -> tuple[Kline, ...]:
    return tuple(_kline_from(row, what) for row in _list(value, what))


def _record_from(row: object, what: str) -> FundingRecord:
    items = _list(row, what)
    if len(items) != 3:
        raise ValueError(f"pack {what}: calc time, interval and rate required")
    interval = None if items[1] is None else _int(items[1], what)
    return FundingRecord(_int(items[0], what), interval, _decimal(items[2], what))


def _funding_from(value: object, what: str) -> tuple[FundingRecord, ...]:
    return tuple(_record_from(row, what) for row in _list(value, what))


def _ints(value: object, what: str) -> tuple[int, ...]:
    return tuple(_int(item, what) for item in _list(value, what))


def _rules_from(value: object, what: str) -> VenueRules:
    document = _object(value, frozenset(_RULES), what)
    return VenueRules(*(_decimal(document[name], what) for name in _RULES))


def _flow_from(value: object, what: str) -> FlowSchedule:
    document = _object(value, _FLOW_KEYS, what)
    return FlowSchedule(
        _str(document["symbol"], what),
        _int(document["start_ms"], what),
        _int(document["end_ms"], what),
        _bytes(document["open_allowed"], what),
        _bytes(document["withheld"], what),
        _bool(document["present"], what),
    )


def _coin_from(value: object) -> CoinInputs:
    document = _object(value, _COIN_KEYS, "coin")
    symbol = _str(document["symbol"], "coin symbol")
    futures_rules = document["futures_rules"]
    return CoinInputs(
        symbol,
        _int(document["history_start_ms"], f"{symbol} history start"),
        _klines(document["spot_hourly"], f"{symbol} spot hourly"),
        _klines(document["futures_hourly"], f"{symbol} futures hourly"),
        _klines(document["daily"], f"{symbol} daily"),
        _funding_from(document["funding"], f"{symbol} funding"),
        _rules_from(document["spot_rules"], f"{symbol} spot rules"),
        None if futures_rules is None else _rules_from(futures_rules, f"{symbol} futures rules"),
        _flow_from(document["flow"], f"{symbol} flow"),
        _ints(document["opening_minute_gaps"], f"{symbol} opening minute gaps"),
        _bool(document["final_minute"], f"{symbol} final minute"),
    )


def _sources(sources: Iterable[object]) -> tuple[tuple[str, str], ...]:
    """The data manifests as (name, lowercase SHA-256) pairs, sorted, each named once."""
    pairs: list[tuple[str, str]] = []
    for source in sources:
        if (
            not isinstance(source, tuple | list)
            or len(source) != 2
            or type(source[0]) is not str
            or not source[0].strip()
            or type(source[1]) is not str
            or _SHA256.fullmatch(source[1]) is None
        ):
            raise ValueError(f"source {source!r}: a manifest name and its sha256 required")
        pairs.append((source[0], source[1]))
    names = [name for name, _ in pairs]
    if not pairs or len(set(names)) != len(names):
        raise ValueError("each source manifest named once required")
    return tuple(sorted(pairs))


def _pack_from(value: object) -> WindowPack:
    document = _object(value, _PACK_KEYS, "document")
    if document["format"] != _FORMAT:
        raise ValueError(f"pack: format {_FORMAT!r} required")
    return WindowPack(
        _str(document["window_id"], "window id"),
        _int(document["start_ms"], "start"),
        _int(document["end_ms"], "end"),
        tuple(_coin_from(coin) for coin in _list(document["coins"], "coins")),
        _ints(document["skipped_hours"], "skipped hours"),
        _sources(_list(document["sources"], "sources")),
    )
