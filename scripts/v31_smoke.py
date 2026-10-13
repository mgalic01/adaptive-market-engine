"""Synthetic V3.1 worlds for the driver's offline smoke mode: labelled synthetic, never
market data.

``build_world`` lays out, under one directory, every input a registered run reads besides
the code:

- a tiny git repository whose head commits the synthetic legacy dataset's spec and
  manifest and a byte copy of the frozen bot config at their pinned paths (a minute cell
  reads them at the repo head), the arm menu (a copy of the committed one), an FX record,
  two filter snapshot stand-ins and the prepare config;
- the legacy dataset's hash-checked archives, stored by the frozen ``fetch_dataset`` from
  in-memory archives (``Archives``), laid out as ``backtest`` reads them.

``window_coins`` and ``v3_fields`` give the W1 and W0 coin inputs and the V3 input pack's
fields, and ``register`` writes the run-manifest and the registration (all 42 arms, all
216 cells) from a prepare document, as Task 11 copies the real one. The shapes follow the
driver tests' own fixtures (``tests/combined_market_fixtures.py``, the run-cell, baseline
and aggregate tests), with exact decimal arithmetic for every price. ``stand_ins``
replaces the two frozen computations that cannot run on a few synthetic days, as those
tests do: V3's walk-forward, whose calendar is fixed to 2020-2024, and the frozen mask job,
which needs whole months of minutes. Nothing here touches the network.

A rehearsal (``v31_driver.py rehearsal-world``, the workflow's ``rehearsal`` mode) builds
the same world with every module of the checkout's package (``source_modules``) and the
rehearsal marker (``REHEARSAL_MARKER``, ``rehearsal_marker``) committed at its code pin.
The marker is what lets the driver run the stand-ins on a world (``--mode rehearsal``) and
what every registered run refuses; the repository itself never holds it.

A world that runs the registered gates also carries a synthetic V3.1 trial in its trial
register (family ``spec-v3.1``, which the driver's trial gate reads), laid out as
``trial_register.check_ready`` requires of a real one: ``register_trial`` commits its spec
and then its registration event before the world's code pin, and ``complete_trial`` adds
the completion binding the code pin, the registration and the run-manifest, for the
registration commit.
"""

import hashlib
import io
import json
import shutil
import uuid
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from trial_register import append_event, code_digest

from crypto_grid_bot.backtest.dataset import (
    archive_path,
    fetch_dataset,
    funding_archive_path,
    load_spec,
    write_manifest,
)
from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.jobs import SymbolMask, manifest_path
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.driver import run_baselines
from crypto_grid_bot.combined.driver.flow_schedule import build_flow_schedule
from crypto_grid_bot.combined.driver.packs import CoinInputs
from crypto_grid_bot.combined.driver.registration import (
    CAPITAL_IDS,
    COMPONENT_ARMS,
    COST_MULTIPLES,
    HOLD_ARM,
    MENU_PATH,
    PREPARE_SCHEMA,
    REGISTRATION_SCHEMA,
    V1_VARIANTS,
    V3_ARMS,
    DriverRegistration,
    PrepareConfig,
    load_prepare_config,
    load_registration,
    registered_arms,
    run_manifest,
    write_run_manifest,
)
from crypto_grid_bot.combined.driver.run_baselines import (
    MINUTE_CONFIG_PATH,
    MINUTE_MANIFEST_PATH,
    MINUTE_PAIRS,
    MINUTE_SPEC_PATH,
)
from crypto_grid_bot.combined.driver.run_cell import _git, head_commit
from crypto_grid_bot.combined.driver.v3_pack import V3PackFields
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.experiment import SCENARIOS
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import replay_window

CHECKOUT = Path(__file__).resolve().parents[1]  # the menu and the frozen bot config
HOUR = 3_600_000
DAY = 24 * HOUR
MINUTE = 60_000
HISTORY_DAYS = 100
START = 1_600_000_000_000 // DAY * DAY + HISTORY_DAYS * DAY  # 2020-12-22 00:00 UTC
FIRST = START - HISTORY_DAYS * DAY  # every coin's first hourly bar, 2020-09-13
WINDOWS = {"w1": (START + 3 * DAY, START + 6 * DAY), "w0": (START, START + 3 * DAY)}
W1_START, W1_END = WINDOWS["w1"]
GAP = W1_START + 30 * HOUR  # BTC has no spot bar here, so W1 has one derived skipped hour
SYMBOLS = ("BTCUSDT", "ETHUSDT")
NOV_2020 = 1_604_188_800_000  # 2020-11-01 00:00 UTC
MAY_2020 = 1_588_291_200_000  # 2020-05-01 00:00 UTC
RULES = VenueRules(Decimal(".001"), Decimal(0), Decimal(1000), Decimal(5), Decimal(".01"))
FILTERS = OrderFilters(
    *(
        Decimal(value)
        for value in ("0.001", "100000", "0.001", "5", "0.001", "100000", "0.001", "0")
    )
)
# What the stand-in walk-forward returns: a pick long before W1, the one in force at its
# start, a change inside it and one after it.
PICKS: dict[int, str | None] = {
    W1_START - 40 * DAY: "R1",
    W1_START - DAY: "R2L",
    W1_START + DAY: "R3L",
    W1_END + DAY: None,
}
FX_RECORD = "config/v3_1_fx_record.json"
SNAPSHOTS = {"spot": "config/smoke/spot.json", "futures": "config/smoke/futures.json"}
# A rehearsal world commits this file at its code pin: the one mark that lets the driver
# run the stand-ins (``--mode rehearsal``), and that every registered run refuses. The
# repository itself never holds it.
REHEARSAL_MARKER = "config/v3_1_rehearsal.json"
REHEARSAL_SCHEMA = "v3.1-rehearsal-1"
SOURCE_PACKAGE = "src/crypto_grid_bot"  # copied into a rehearsal world for its adapter pins
# The synthetic V3.1 trial (``register_trial``, ``complete_trial``): its family is the one
# the driver's trial gate reads (``v31_driver.V31_FAMILY``).
TRIAL_REGISTER = "docs/trials/register.jsonl"
TRIAL_FAMILY = "spec-v3.1"
TRIAL_ID = "v3-1-synthetic"
TRIAL_SPEC = "docs/v3_1_synthetic_spec.md"
TRIAL_SPEC_TEXT = (
    b"A synthetic V3.1 trial (labelled synthetic, never market data): the smoke world's 42 "
    b"arms and 216 cells, registered for a rehearsal or a test.\n"
)
# trial_register.check_ready's code inventory, which a completion's code_paths must list.
_CODE_PREFIXES = ("src/", "scripts/")
_CODE_FILES = frozenset({"pyproject.toml", "requirements-dev.lock", "requirements.txt"})
_RECORDED_AT = "2024-12-31T00:00:00Z"  # the synthetic trial events' recorded_at
_FIXED_NOW = datetime(2024, 12, 31, tzinfo=UTC)  # the synthetic manifest's created_at
_ABBREVIATIONS = {"open_low_high_close": "olhc", "open_high_low_close": "ohlc", "native": "native"}
_ADAPTER_PINS = {"v31": "5" * 64, "hold": "6" * 64, "v3": "7" * 64, "minute": "8" * 64}
_MINUTE_OFFSETS = (0, 30, 59)  # the minutes of each synthetic legacy hour
# A full-range-shaped spec: the frozen traded pairs, BTCUSDT as the proxy, the five-member
# breadth basket the frozen vote needs, daily history from 2020-05 and the frozen pricing.
LEGACY_SPEC = """name = "v31-smoke-minutes"
purpose = "synthetic V3.1 smoke dataset (labelled synthetic, never market data)"
traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT"]
daily_warmup_start = "2020-05"
warmup_start = "2020-11"
start = "2020-12"
end = "2020-12"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""


# --- prices, minutes and funding --------------------------------------------------------


def uptrend(i: int) -> Decimal:
    return Decimal(100) * Decimal("1.0006") ** i


def downtrend(i: int) -> Decimal:
    return Decimal(400) * Decimal("0.9994") ** i


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def hourly(
    path: Callable[[int], Decimal], hours: int, *, start: int = FIRST, wick: str = "0.01"
) -> tuple[Kline, ...]:
    """Bars whose open and close follow ``path(i)``, with symmetric wicks of ``wick``."""
    up, down = 1 + Decimal(wick), 1 - Decimal(wick)
    rows = []
    with localcontext(Context()):
        for i in range(hours):
            open_, close = path(i), path(i + 1)
            rows.append(
                Kline(
                    start + i * HOUR,
                    _cents(open_),
                    _cents(max(open_, close) * up),
                    _cents(min(open_, close) * down),
                    _cents(close),
                    Decimal(10),
                    Decimal(1000),
                    Decimal(5),
                )
            )
    return tuple(rows)


def minutes(start: int, end: int) -> tuple[Kline, ...]:
    """Flat minutes, 60% of their volume taker-bought: the flow gate allows them."""
    return tuple(
        Kline(t, *(Decimal(100),) * 4, Decimal(10), Decimal(1000), Decimal(6))
        for t in range(start, end, MINUTE)
    )


def funding(start: int, end: int, rate: str = "0.0001") -> tuple[FundingRecord, ...]:
    """Eight-hourly settlements from the slot at or before ``start`` to past ``end``."""
    first = start // (8 * HOUR) * (8 * HOUR)
    return tuple(FundingRecord(t, 8, Decimal(rate)) for t in range(first, end + 8 * HOUR, 8 * HOUR))


def coin(symbol: str, path: Callable[[int], Decimal], start: int, end: int) -> CoinInputs:
    """A coin with futures, its history from ``FIRST`` and a flow schedule from minutes."""
    hours = (end - FIRST) // HOUR
    spot = hourly(path, hours)
    flow = build_flow_schedule(symbol, minutes(start - 15 * MINUTE, end), start, end)
    return CoinInputs(
        symbol,
        FIRST,
        spot,
        hourly(path, hours),
        daily_bars(spot),
        funding(FIRST, end),
        RULES,
        RULES,
        flow,
        (),
        True,
    )


def window_coins(window_id: str) -> list[CoinInputs]:
    """The window's two coins; in W1, BTC lacks its spot bar at ``GAP``."""
    start, end = WINDOWS[window_id]
    btc = coin("BTCUSDT", uptrend, start, end)
    if window_id == "w1":
        spot = tuple(bar for bar in btc.spot_hourly if bar.open_ms != GAP)
        btc = replace(btc, spot_hourly=spot, daily=daily_bars(spot))
    return [btc, coin("ETHUSDT", downtrend, start, end)]


def v3_fields() -> V3PackFields:
    """The V3 input pack's fields for both coins, joining in 2020-10, to W1's end."""
    hours = (W1_END - FIRST) // HOUR
    paths = {"BTCUSDT": uptrend, "ETHUSDT": downtrend}
    spot = {symbol: hourly(path, hours) for symbol, path in paths.items()}
    rates = {r.calc_time_ms: dict.fromkeys(SYMBOLS, r.rate) for r in funding(FIRST, W1_END)}
    return V3PackFields(
        first_months=dict.fromkeys(SYMBOLS, "2020-10"),
        spot_bars={symbol: daily_bars(bars) for symbol, bars in spot.items()},
        spot_exclusions=dict.fromkeys(SYMBOLS, frozenset()),
        futures_exclusions=dict.fromkeys(SYMBOLS, frozenset()),
        futures_filters=dict.fromkeys(SYMBOLS, FILTERS),
        futures_hourly={s: hourly(path, hours, wick="0.02") for s, path in paths.items()},
        funding=rates,
    )


# --- archives ---------------------------------------------------------------------------


def month_of(stamp: int) -> str:
    return datetime.fromtimestamp(stamp / 1000, UTC).strftime("%Y-%m")


def kline_csv(klines: Iterable[Kline], step: int, *, header: bool = False) -> str:
    """Binance's monthly kline CSV of ``klines`` (a futures archive starts with a header)."""
    rows = [
        f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},{k.open_ms + step - 1},"
        f"{k.quote_volume},10,{k.taker_buy_base},{k.taker_buy_base * k.close},0"
        for k in klines
    ]
    if header:
        rows.insert(
            0,
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
            "taker_buy_volume,taker_buy_quote_volume,ignore",
        )
    return "\n".join(rows) + "\n"


def funding_csv(records: Iterable[FundingRecord]) -> str:
    rows = "".join(f"{r.calc_time_ms},{r.interval_hours},{r.rate}\n" for r in records)
    return "calc_time,funding_interval_hours,last_funding_rate\n" + rows


def zipped(member: str, text: str) -> bytes:
    """One deterministic zip archive holding ``member``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(member, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, text)
    return buffer.getvalue()


class Archives:
    """Monthly archives by their data.binance.vision path, each with Binance's
    ``.CHECKSUM`` beside it: ``fetch_dataset``'s fetcher (a call) and a driver transport
    (``archive``). ``requested`` lists every path asked for."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requested: list[str] = []

    def put(self, path: str, member: str, text: str) -> str:
        body = zipped(member, text)
        self.objects[path] = body
        name = path.rsplit("/", 1)[1]
        self.objects[path + ".CHECKSUM"] = f"{hashlib.sha256(body).hexdigest()}  {name}".encode()
        return path

    def spot_klines(self, symbol: str, interval: str, step: int, klines: Sequence[Kline]) -> None:
        """Each month of ``klines`` as the spot archive of ``symbol`` at ``interval``."""
        for month, rows in _by_month(klines).items():
            path = archive_path(symbol, interval, month)
            self.put(path, f"{symbol}-{interval}-{month}.csv", kline_csv(rows, step))

    def funding(self, symbol: str, records: Sequence[FundingRecord]) -> list[str]:
        """Each month of ``records`` as the funding archive of ``symbol``; the months."""
        months = _by_month(records)
        for month, rows in months.items():
            path = funding_archive_path(symbol, month)
            self.put(path, f"{symbol}-fundingRate-{month}.csv", funding_csv(rows))
        return list(months)

    def __call__(self, path: str) -> bytes | None:
        self.requested.append(path)
        return self.objects.get(path)

    def archive(self, path: str) -> bytes | None:
        return self(path)


def _by_month(rows: Iterable[Any]) -> dict[str, list[Any]]:
    months: dict[str, list[Any]] = {}
    for row in rows:
        stamp = row.calc_time_ms if isinstance(row, FundingRecord) else row.open_ms
        months.setdefault(month_of(stamp), []).append(row)
    return months


def _legacy_price(hour: int) -> Decimal:
    """A daily triangle wave between 0.94 and 1.06, exact, at hour ``hour`` of Nov 2020."""
    return 1 + (6 - abs((hour + 8) % 24 - 12)) * Decimal("0.01")


def _legacy_bar(open_ms: int, open_: Decimal, close: Decimal, wick: str) -> Kline:
    high, low = max(open_, close) * (1 + Decimal(wick)), min(open_, close) * (1 - Decimal(wick))
    volume = Decimal(10**6)
    return Kline(open_ms, open_, high, low, close, volume, volume * close, volume / 2)


def legacy_dataset(repo: Path, data_dir: Path) -> Path:
    """The synthetic legacy dataset: its spec at ``repo/MINUTE_SPEC_PATH``, the manifest the
    frozen fetch writes beside it (``MINUTE_MANIFEST_PATH``) and the hash-checked archives
    under ``data_dir``, as ``backtest`` reads them; returns the spec's path.

    Hourly bars from 2020-11-01 for the five basket members, rising daily bars from
    2020-05-01 for the pairs, BTCUSDT's funding for 2020-11 and 2020-12, and the pairs'
    minutes from a day before W1 to a day after it, each hour holding only the minutes
    ``_MINUTE_OFFSETS``: its opening minute and its last, so the replays stay short."""
    with localcontext(Context()):
        hours = (W1_END + 2 * DAY - NOV_2020) // HOUR
        bars = [
            _legacy_bar(NOV_2020 + i * HOUR, _legacy_price(i - 1), _legacy_price(i), "0.004")
            for i in range(hours)
        ]
        first_hour = (W1_START - DAY - NOV_2020) // HOUR
        flat = [
            _legacy_bar(NOV_2020 + h * HOUR + k * MINUTE, price, price, "0.0005")
            for h in range(first_hour, first_hour + (W1_END - W1_START) // HOUR + 48)
            for price in (_legacy_price(h - 1),)
            for k in _MINUTE_OFFSETS
        ]
        days = (W1_END + 2 * DAY - MAY_2020) // DAY
        daily = [
            _legacy_bar(
                MAY_2020 + i * DAY,
                Decimal("0.5") + Decimal(i) / 500,
                Decimal("0.5") + Decimal(i + 1) / 500,
                "0.01",
            )
            for i in range(days)
        ]
        archives = Archives()
        for pair in MINUTE_PAIRS:
            archives.spot_klines(pair, "1m", MINUTE, flat)
            archives.spot_klines(pair, "1d", DAY, daily)
        for symbol in ("BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT"):
            archives.spot_klines(symbol, "1h", HOUR, bars)
        # Every settlement of 2020-11 and 2020-12 (90 and 93), read by V1 g and cg.
        months = archives.funding("BTCUSDT", funding(NOV_2020, NOV_2020 + 61 * DAY - 8 * HOUR))
    spec_path = repo / MINUTE_SPEC_PATH
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_bytes(LEGACY_SPEC.encode("utf-8"))
    filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.0001"}
    filters |= {"quantity_step": "0.1", "min_notional": "5"}
    manifest = fetch_dataset(
        load_spec(spec_path),
        data_dir,
        fetcher=archives,
        instruments=lambda symbol: filters,
        now=lambda: _FIXED_NOW,
        previous={
            "files": [{"kind": "fundingRate", "symbol": "BTCUSDT", "month": m} for m in months]
        },
    )
    if any(entry["status"] != "ok" for entry in manifest["files"]):
        raise ValueError("the synthetic legacy dataset is incomplete")
    write_manifest(manifest_path(spec_path), manifest)
    return spec_path


# --- the repository, the prepare config and the registration ----------------------------


def init_repo(repo: Path) -> None:
    """A new git repository at ``repo`` with a local identity and LF bytes as written."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    for key, value in (
        ("user.name", "V3.1 smoke (synthetic)"),
        ("user.email", "smoke@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        _git(repo, "config", key, value)


def commit_all(repo: Path, message: str) -> str:
    """Commit every file under ``repo`` and return the new head."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return head_commit(repo)


def write_json(path: Path, document: object) -> str:
    """Write ``document`` as indented JSON with a trailing newline; return its SHA-256."""
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class World:
    """A smoke world: the repository and its head, the legacy dataset's directory and the
    prepare config the head commits."""

    root: Path
    repo: Path
    head: str
    legacy: Path
    prepare: PrepareConfig


def build_world(
    root: Path, *, extra_files: Mapping[str, bytes] | None = None, trial: bool = False
) -> World:
    """Lay out a smoke world under ``root`` (layout in the module docstring) and commit it.

    ``extra_files`` (repository path: bytes) are committed too, such as the modules the
    adapter pins read. The prepare config names both windows with their two coins, the
    legacy manifest by its SHA-256 and the two snapshot stand-ins. With ``trial``, the
    synthetic V3.1 trial's spec and registration event are committed first
    (``register_trial``), so the world's own commit, its code pin, sits on the registration
    as ``trial_register.check_ready`` requires."""
    repo, legacy = root / "repo", root / "legacy"
    init_repo(repo)
    if trial:
        register_trial(repo)
    for name, content in (extra_files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(content)
    spec_path = legacy_dataset(repo, legacy)
    shutil.copyfile(CHECKOUT / MINUTE_CONFIG_PATH, repo / MINUTE_CONFIG_PATH)
    (repo / MENU_PATH).write_bytes((CHECKOUT / MENU_PATH).read_bytes())
    write_json(repo / FX_RECORD, fx_record())
    snapshots = {
        market: {"path": path, "sha256": write_json(repo / path, {"synthetic": market})}
        for market, path in SNAPSHOTS.items()
    }
    legacy_sha = hashlib.sha256(manifest_path(spec_path).read_bytes()).hexdigest()
    write_json(
        repo / "config/v3_1_prepare.json",
        {
            "schema": PREPARE_SCHEMA,
            "windows": [
                {"id": wid, "start_ms": start, "end_ms": end, "symbols": list(SYMBOLS)}
                for wid, (start, end) in WINDOWS.items()
            ],
            "data_manifests": {MINUTE_MANIFEST_PATH: legacy_sha},
            "filter_snapshots": snapshots,
        },
    )
    head = commit_all(repo, "synthetic V3.1 smoke world")
    return World(root, repo, head, legacy, load_prepare_config(repo / "config/v3_1_prepare.json"))


def trial_event(
    event_type: str, payload: Mapping[str, Any], *, trial_id: str = TRIAL_ID
) -> dict[str, Any]:
    """One event of the synthetic V3.1 trial (or of another synthetic V3.1 trial,
    ``trial_id``), in the trial register's schema."""
    return {
        "schema_version": 1,
        "event_id": f"{trial_id}-{event_type}",
        "trial_id": trial_id,
        "event_type": event_type,
        "recorded_at": _RECORDED_AT,
        "agent": "V3.1 smoke (synthetic)",
        "family": TRIAL_FAMILY,
        "parent_trial_id": None,
        "sources": [TRIAL_SPEC],
        "payload": dict(payload),
    }


def register_trial(repo: Path) -> str:
    """Commit the synthetic V3.1 trial's spec into the new repository ``repo``, then its
    registration event naming that commit's spec; return the second commit. The world's
    code pin goes on top of it: ``check_ready`` requires the code commit's first parent to
    hold the registration."""
    (repo / TRIAL_SPEC).parent.mkdir(parents=True, exist_ok=True)
    (repo / TRIAL_SPEC).write_bytes(TRIAL_SPEC_TEXT)
    spec_commit = commit_all(repo, "the synthetic V3.1 trial's spec")
    spec = {
        "path": TRIAL_SPEC,
        "commit": spec_commit,
        "sha256": hashlib.sha256(TRIAL_SPEC_TEXT).hexdigest(),
    }
    payload = {
        "preregistered": True,
        "hypothesis": "synthetic: the driver's gates and job graph run end to end",
        "spec": spec,
        "candidates": ["synthetic: the registration's 42 arms"],
        "sizes": [1],
        "fees": "synthetic: the registered cost profiles",
        "folds": "synthetic: the world's two windows",
        "mask": "synthetic: the world's skipped hours",
        "seeds": [],
        "budget": "synthetic: the registration's 216 cells, each once",
        "stopping": "synthetic: every cell, once",
        "selection": "synthetic: none",
        "data": None,
        "code": None,
    }
    register = repo / TRIAL_REGISTER
    register.parent.mkdir(parents=True, exist_ok=True)
    append_event(register, trial_event("registration", payload))
    return commit_all(repo, "the synthetic V3.1 trial's registration")


def complete_trial(
    repo: Path,
    *,
    code_pin: str,
    config_sha256: str,
    manifest_sha256: str,
    registration: str = "config/v3_1_registration.json",
    manifest: str = "config/v3_1_run_manifest.json",
    trial_id: str = TRIAL_ID,
) -> None:
    """Write the trial register into ``repo``'s working tree, unstaged, as ``code_pin``
    commits it plus the synthetic trial's completion (``trial_id``'s, whose registration
    event ``code_pin`` commits), for the registration commit to commit. The completion
    binds ``code_pin`` (its code inventory and digest as ``check_ready`` computes them
    there), the registration file ``registration`` at ``config_sha256`` and the
    run-manifest ``manifest`` at ``manifest_sha256``."""
    register = repo / TRIAL_REGISTER
    register.write_bytes(_git(repo, "show", f"{code_pin}:{TRIAL_REGISTER}"))
    listed = _git(repo, "ls-tree", "-r", "--name-only", "-z", code_pin).decode("utf-8")
    paths = sorted(
        path
        for path in listed.split("\0")
        if path.startswith(_CODE_PREFIXES) or path in _CODE_FILES
    )
    blobs = {path: _git(repo, "show", f"{code_pin}:{path}") for path in paths}
    payload = {
        "registration_id": f"{trial_id}-registration",
        "code_commit": code_pin,
        "code_sha256": code_digest(blobs),
        "code_paths": paths,
        "manifest": {"path": manifest, "sha256": manifest_sha256},
        "config": {"path": registration, "sha256": config_sha256},
        "review": "synthetic: a rehearsal or test world, never reviewed",
    }
    append_event(register, trial_event("completion", payload, trial_id=trial_id))


def rehearsal_marker() -> bytes:
    """The rehearsal marker's bytes (canonical JSON): a world committing them at its code
    pin is synthetic, built in-job, and only a rehearsal runs the stand-ins on it."""
    document = {
        "schema": REHEARSAL_SCHEMA,
        "synthetic": True,
        "purpose": "a synthetic V3.1 rehearsal world (labelled synthetic, never market data); "
        "a registered run refuses any checkout holding this file",
        "stand_ins": list(STAND_INS),
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def source_modules() -> dict[str, bytes]:
    """Every module of the checkout's own package (``src/crypto_grid_bot/**/*.py``) by
    repository path: a rehearsal world commits them, so its adapter pins are read from
    real blobs at its code pin as a registered run's are."""
    package = CHECKOUT / SOURCE_PACKAGE
    return {
        path.relative_to(CHECKOUT).as_posix(): path.read_bytes()
        for path in sorted(package.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def fx_record() -> dict[str, str]:
    return {
        "schema": "v3.1-fx-record-1",
        "usd_per_eur": "1.0389",
        "reference_date": "2024-12-31",
        "source_url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
        "euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html",
        "retrieved_on": "2026-10-13",
    }


def arm_kind(arm: str) -> str:
    if arm in COMPONENT_ARMS:
        return "v31"
    if arm in V3_ARMS:
        return "v3"
    return "hold" if arm == HOLD_ARM else "minute"


def synthetic_adapter_pins(arms: Iterable[str]) -> dict[str, str]:
    """One synthetic adapter pin per arm kind, for a world whose head holds no modules."""
    return {arm: _ADAPTER_PINS[arm_kind(arm)] for arm in arms}


def cells_document(arms: Sequence[str]) -> list[dict[str, object]]:
    """The 216 cells ``registration.required_cells`` lists, as the registration file holds
    them: W1 by arm, scenario, cost and capital, then W0's ``combined`` cells."""

    def cells(window: str, arm: str, scenarios: Sequence[str]) -> Iterator[dict[str, object]]:
        for scenario in scenarios:
            for multiple in COST_MULTIPLES:
                for capital in CAPITAL_IDS:
                    yield {
                        "cell_id": f"{window}.{arm}.{_ABBREVIATIONS[scenario]}.c{multiple}."
                        f"{capital}",
                        "arm": arm,
                        "window": window,
                        "scenario": scenario,
                        "cost_multiple": multiple,
                        "capital_id": capital,
                        "kind": arm_kind(arm),
                        "reported_only": window == "w0",
                    }

    listed: list[dict[str, object]] = []
    for arm in arms:
        scenarios = SCENARIOS if arm in COMPONENT_ARMS else ("native",)
        listed.extend(cells("w1", arm, scenarios))
    listed.extend(cells("w0", "combined", SCENARIOS))
    return listed


def register(
    world: World,
    document: Mapping[str, Any],
    *,
    code_pin: str,
    adapter_pins: Mapping[str, str] | None = None,
    registration: str = "config/v3_1_registration.json",
    manifest: str = "config/v3_1_run_manifest.json",
) -> tuple[DriverRegistration, str]:
    """Write the run-manifest and the registration from the prepare ``document`` (its pack
    pins and each window's skipped hours) into the world's repository at ``manifest`` and
    ``registration``, unstaged, as Task 11 does for the real run; return the loaded
    registration and the registration file's SHA-256.

    The windows are the prepare config's: ``w1`` judged, ``w0`` reported. ``adapter_pins``
    defaults to ``synthetic_adapter_pins``; ``code_pin`` is the commit the registration
    names. A world with a trial (``build_world(trial=True)``) then completes it with these
    pins (``complete_trial``) before the registration commit."""
    repo = world.repo
    menu = json.loads((repo / MENU_PATH).read_bytes())["arms"]
    arms = registered_arms(menu, V1_VARIANTS)
    manifest_file = repo / manifest
    manifest_sha = write_run_manifest(
        run_manifest(
            world.prepare,
            window_packs=document["window_packs"],
            v3_pack=document["v3_pack_sha256"],
        ),
        manifest_file,
    )
    fx_sha = hashlib.sha256((repo / FX_RECORD).read_bytes()).hexdigest()
    skipped = document["skipped_hours"]
    windows = {window.id: window for window in world.prepare.windows}

    def window(wid: str) -> dict[str, object]:
        start, end = windows[wid].start_ms, windows[wid].end_ms
        return {"id": wid, "start_ms": start, "end_ms": end, "skipped_hours": skipped[wid]["hours"]}

    registered = {
        "schema": REGISTRATION_SCHEMA,
        "code_pin": code_pin,
        "prepare_sha256": world.prepare.sha256,
        "run_manifest_sha256": manifest_sha,
        "observation_policy": POLICY_ID,
        "scenarios": list(SCENARIOS),
        "v1_variants": list(V1_VARIANTS),
        "arms": list(arms),
        "adapter_pins": dict(adapter_pins or synthetic_adapter_pins(arms)),
        "cost_profiles": [{"multiple": m, "sha256": COST_PROFILE_PINS[m]} for m in COST_MULTIPLES],
        "capitals": [
            {"id": "research", "currency": "USDT", "amount": "10000", "initial_equity": "10000"},
            {
                "id": "owner_small",
                "currency": "EUR",
                "amount": "100",
                "initial_equity": "103.89",
                "fx_rate": "1.0389",
                "fx_record": {"path": FX_RECORD, "sha256": fx_sha},
            },
        ],
        "windows": [window("w1")],
        "reported_windows": [window("w0")],
        "cells": cells_document(arms),
    }
    path = repo / registration
    config_sha = write_json(path, registered)
    return load_registration(path, manifest_file, repo_root=repo), config_sha


# --- the stand-ins ----------------------------------------------------------------------


def _walk_forward(
    decisions: Any, filters: Any, hourly_bars: Any, rates: Any, *, record: Callable[..., None]
) -> SimpleNamespace:
    """Stands in for V3's frozen walk-forward (its calendar is fixed to 2020-2024): records
    a started and a finished training attempt around one short frozen replay, under a
    fresh run-id prefix as V3's own does, and returns ``PICKS``."""
    run_id = f"{uuid.uuid4().hex}-train-2020-12-R2L"
    start, end = W1_START - 2 * DAY, W1_START
    schedule = ((start, "R2L"),)
    record(
        Attempt(
            run_id,
            "training",
            "R2L",
            start,
            end,
            None,
            None,
            state="started",
            pick_schedule=schedule,
        )
    )
    result = replay_window(
        decisions,
        filters,
        hourly_bars,
        rates,
        start,
        end,
        dict(schedule),
        multiple=2,
        cost_multiple=1,
    )
    record(Attempt(run_id, "training", "R2L", start, end, result, None, pick_schedule=schedule))
    return SimpleNamespace(picks=dict(PICKS), out_of_sample=result)


def _unmasked(spec_path: Path, data_dir: Path, symbol: str) -> SymbolMask:
    """Stands in for the frozen ``mask_job``, as the frozen CLI's own tests do: a mask of
    None (the symbol reads clean). The real mask would mask nearly every hour of the
    evaluation month, since the synthetic dataset holds three minutes an hour."""
    return SymbolMask(symbol, None, ())


STAND_INS = (
    "V3's frozen walk-forward (its calendar is fixed to 2020-2024): a stand-in records two "
    "real training attempts around one short frozen replay and returns fixed picks",
    "the frozen mask job (it needs whole months of minutes): a stand-in gives every symbol "
    "a clean mask (None)",
)


@contextmanager
def stand_ins() -> Iterator[None]:
    """Replace V3's walk-forward and the frozen mask job while the block runs (the
    ``STAND_INS``); the originals are restored afterwards, whatever happens."""
    replaced = (
        (baseline_v3, "run_walk_forward", _walk_forward),
        (run_baselines, "mask_job", _unmasked),
    )
    saved = [(vars(module), name, vars(module)[name]) for module, name, _ in replaced]
    for module, name, stand_in in replaced:
        vars(module)[name] = stand_in
    try:
        yield
    finally:
        for namespace, name, original in saved:
            namespace[name] = original
