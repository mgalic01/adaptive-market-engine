"""V4 step 4b task 1: the synthetic rehearsal and timing worlds (``crypto_grid_bot.v4.synthetic``)
and the CLI that writes them (``scripts/v4_rehearsal.py``).

One module-scoped fixture writes the rehearsal world once through the CLI (``world --scale
rehearsal``): five years of hourly bars for four coins and V3's input pack, about 300,000 rows, and
the world's repository built from this checkout (``world.tar``, gated in
``tests/test_v4_rehearsal_force.py``). The
timing world is never written at its real size here (owner rule: no heavy work on the owner's PC;
at its defaults it holds about 7 million rows): its plan is checked at the defaults, which builds no
price, and a scaled-down world of the same shape is written and loaded.

The network is blocked for every test (the autouse fixture, and the module fixture blocks it for
its own run). Only synthetic worlds in pytest's temporary folders are read.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import socket
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.driver.v3_pack import read_v3_pack
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.v4 import synthetic
from crypto_grid_bot.v4.engine import run
from crypto_grid_bot.v4.engine.arms import MAIN_LOOKBACKS
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.signals import CoinSignals
from crypto_grid_bot.v4.engine.v3_as_built import (
    PICKS_FILE,
    V3_END_MS,
    V3_START_MS,
    read_v3_picks,
)
from crypto_grid_bot.v4.synthetic import (
    CONFIG_SHA256,
    DAY,
    HOUR,
    REHEARSAL_PICKS,
    CoinSpec,
    Series,
    World,
    every_month,
    month_start,
    path,
    read_data_json,
    rehearsal_v3_fields,
    rehearsal_world,
    timing_rows,
    timing_world,
    write_world,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_rehearsal  # noqa: E402
from v4_rehearsal import DATA_DIR, V3_DIR, WORLD_FILE, WORLD_FORMAT, WORLD_TAR  # noqa: E402
from v4_v3_pack import EXPECTED_PACK_SHA256, PACK_FILE  # noqa: E402

REAL_ROWS = 7_003_893  # the hourly rows of step 2's real pack (docs/RUN_ARCHIVE.md)
SCALED = {"coins": 12, "first": "2023-01", "window_first": "2023-03", "last": "2023-06"}


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


_SOCKET_CALLS = [
    (socket, "getaddrinfo"),
    (socket, "create_connection"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
]


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in _SOCKET_CALLS:
        monkeypatch.setattr(owner, name, _refuse)


def run_cli(argv: Sequence[str]) -> tuple[int, str, str]:
    """``v4_rehearsal.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = v4_rehearsal.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# ---- the worlds ---------------------------------------------------------------------------------


class Rehearsal:
    """The rehearsal world, written once through the CLI."""

    def __init__(self, root: Path, stdout: str) -> None:
        self.root = root
        self.stdout = stdout

    @property
    def data(self) -> Path:
        return self.root / DATA_DIR

    @property
    def pack(self) -> Path:
        return self.root / V3_DIR / PACK_FILE


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory) -> Rehearsal:
    root = tmp_path_factory.mktemp("rehearsal") / "world"
    with pytest.MonkeyPatch.context() as patch:
        # The autouse block is per test; this module-wide run blocks the network itself.
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        code, stdout, stderr = run_cli(["world", "--scale", "rehearsal", "--out", str(root)])
    assert (code, stderr) == (0, "")
    return Rehearsal(root, stdout)


@pytest.fixture(scope="module")
def market(rehearsal) -> Market:
    return Market.load(rehearsal.data)


def small_world() -> World:
    """Three months of one coin: a world a test writes in a moment."""
    btc = CoinSpec("BTCUSDT", Series(month_start("2025-01"), path("100", (24 * 90, "0.0002"))))
    return World("2025-03", (btc,), every_month("2025-01", "2025-03", ("BTCUSDT",)))


def document_of(root: Path, **changes: object) -> dict[str, object]:
    """The world file of ``root`` with ``changes`` applied."""
    return v4_rehearsal.read_world(root) | changes


def write_document(folder: Path, document: object) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / WORLD_FILE).write_bytes(_canonical(document))


# ---- the rehearsal world ------------------------------------------------------------------------


def test_rehearsal_world_window_and_pins(rehearsal, market):
    assert market.window_start_ms == month_start("2020-09")
    assert market.window_end_ms == month_start("2025-04") - HOUR
    header = read_data_json(rehearsal.data)
    assert header["config_sha256"] == CONFIG_SHA256
    world = v4_rehearsal.read_world(rehearsal.root)
    assert world["data"] == run.data_record(market.pins)
    assert world["scale"] == "rehearsal"
    assert world["format"] == WORLD_FORMAT
    registration = world["registration_sha256"]  # world.tar's registration (task 7)
    assert isinstance(registration, str)
    v3_pin = world["v3_pack_sha256"]
    assert isinstance(v3_pin, str)
    assert v3_pin != EXPECTED_PACK_SHA256  # a synthetic pack, never V3.1's
    pins = run.data_record(market.pins)
    assert pins is not None
    assert rehearsal.stdout == (
        f"v4_rehearsal world: scale rehearsal, {header['coin_packs']} coins, "
        f"{header['hourly_rows']} hourly rows, daily sha256 {pins['daily_sha256']}, "
        f"index sha256 {pins['index_sha256']}, v3 pack sha256 {v3_pin}, "
        f"registration sha256 {registration}\n"
    )
    assert header["coin_packs"] == 4
    assert sorted(item.name for item in rehearsal.root.iterdir()) == sorted(
        [DATA_DIR, V3_DIR, WORLD_FILE, WORLD_TAR]  # no staging folder is left behind
    )
    raw = (rehearsal.root / WORLD_FILE).read_bytes()
    assert raw == _canonical(json.loads(raw))
    assert re.search(r"[0-9]+\.[0-9]", rehearsal.stdout) is None  # counts and pins, no price


def test_rehearsal_world_coins_perpetuals_and_delisting(market):
    assert market.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    perpetual = {symbol: market.coin(symbol).perpetual is not None for symbol in market.symbols}
    assert perpetual == {"BTCUSDT": True, "ETHUSDT": True, "SOLUSDT": True, "XRPUSDT": False}
    xrp = market.coin("XRPUSDT").spot
    assert xrp.first_open_ms == month_start("2020-01")
    assert xrp.opens()[-1] == month_start("2023-07") - HOUR  # 2023-06-30 23:00: a dead market
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        spot = market.coin(symbol).spot
        assert (spot.first_open_ms, spot.opens()[-1]) == (
            month_start("2020-01"),
            month_start("2025-04") - HOUR,
        )
    assert market.universe("2020-08") == ()  # the window opens with 2020-09
    assert market.universe("2020-09") == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert market.universe("2023-06") == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert market.universe("2023-07") == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert market.universe("2025-03") == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert market.universe("2025-04") == ()


def test_rehearsal_world_btc_vote_takes_both_signs(market):
    """BTC's slow vote (close against its 200-day SMA) is +1 on a long run of the window's days
    and -1 on another: ``v4_btc200_shorts`` and ``hold_btc_trend`` both trade."""
    signals = CoinSignals(MAIN_LOOKBACKS)
    slow = {bar.open_ms: signals.update(bar).slow for bar in market.daily("BTCUSDT")}
    in_window = [vote for day, vote in slow.items() if day >= market.window_start_ms]
    assert in_window.count(1) >= 90
    assert in_window.count(-1) >= 90


def test_rehearsal_world_is_exactly_reproducible():
    first, second = rehearsal_world(), rehearsal_world()
    for one, other in zip(first.coins, second.coins, strict=True):
        assert one.symbol == other.symbol
        assert one.spot.closes == other.spot.closes
    assert first.universes == second.universes


def test_rehearsal_v3_fields_are_bounded_and_sealed():
    fields = rehearsal_v3_fields()
    assert tuple(sorted(fields.first_months)) == ("BTCUSDT", "ETHUSDT")
    assert set(fields.first_months.values()) == {"2020-10"}
    for symbol, bars in fields.futures_hourly.items():
        assert bars[0].open_ms == month_start("2020-10")
        assert bars[-1].open_ms == V3_END_MS - HOUR
        assert all(
            later.open_ms - earlier.open_ms == HOUR
            for earlier, later in zip(bars, bars[1:], strict=False)
        )
        assert Decimal(20) < min(bar.low for bar in bars)
        assert max(bar.high for bar in bars) < Decimal(2000)
        daily = fields.spot_bars[symbol]
        assert (daily[0].open_ms, daily[-1].open_ms) == (month_start("2020-10"), V3_END_MS - DAY)
    assert max(fields.funding) < V3_END_MS
    assert REHEARSAL_PICKS == {
        V3_START_MS - 40 * DAY: "R1",
        V3_START_MS - DAY: "R2L",
        V3_START_MS + 365 * DAY: "R3L",
        V3_END_MS - DAY: None,
    }


# ---- the world command --------------------------------------------------------------------------


def test_world_refuses_an_existing_folder(tmp_path):
    out = tmp_path / "taken"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    code, stdout, stderr = run_cli(["world", "--scale", "rehearsal", "--out", str(out)])
    assert code == 1
    assert stdout == ""
    assert stderr == "v4_rehearsal world: refused: the output folder already exists\n"
    assert sorted(item.name for item in out.iterdir()) == ["keep.txt"]


def test_world_leaves_nothing_after_a_failure(tmp_path, monkeypatch):
    def broken(fields: object, target: object) -> str:
        raise RuntimeError("secret detail 4242.5")

    # A three-month world and no V3 fields keep this fast; what is tested is the clean-up of a
    # folder that already holds the data pack when the V3 pack cannot be written.
    monkeypatch.setattr(v4_rehearsal, "rehearsal_world", small_world)
    monkeypatch.setattr(v4_rehearsal, "rehearsal_v3_fields", lambda: None)
    monkeypatch.setattr(v4_rehearsal, "write_v3_pack", broken)
    out = tmp_path / "world"
    code, stdout, stderr = run_cli(["world", "--scale", "rehearsal", "--out", str(out)])
    assert code == 1
    assert stdout == ""
    assert not out.exists()
    assert tmp_path.exists()
    assert stderr == (
        "v4_rehearsal world: writing the world failed; the folder is removed: RuntimeError\n"
    )  # the type of the exception, never its text


def test_world_leaves_nothing_when_the_repository_fails(tmp_path, monkeypatch):
    def broken(root: object, checkout: object, manifest: object) -> tuple[Path, str]:
        raise RuntimeError("secret detail 4242.5")

    def pack(fields: object, target: Path) -> str:
        target.write_bytes(b"a stand-in pack")
        return "c" * 64

    # As above, a three-month world and a stand-in V3 pack keep this fast: what is tested is the
    # clean-up of a folder that holds the data and the pack when its repository cannot be built.
    monkeypatch.setattr(v4_rehearsal, "rehearsal_world", small_world)
    monkeypatch.setattr(v4_rehearsal, "rehearsal_v3_fields", lambda: None)
    monkeypatch.setattr(v4_rehearsal, "write_v3_pack", pack)
    monkeypatch.setattr(v4_rehearsal, "build_rehearsal_repo", broken)
    out = tmp_path / "world"
    code, stdout, stderr = run_cli(["world", "--scale", "rehearsal", "--out", str(out)])
    assert (code, stdout) == (1, "")
    assert not out.exists()
    assert stderr == (
        "v4_rehearsal world: writing the world failed; the folder is removed: RuntimeError\n"
    )


def test_world_at_the_timing_scale_writes_no_v3_pack(tmp_path, monkeypatch):
    """The timing scale through the command, with the preset scaled down (the real one holds about
    7 million rows): a data pack and a world file whose V3 pin is null."""
    monkeypatch.setattr(v4_rehearsal, "timing_world", lambda: timing_world(**SCALED))
    out = tmp_path / "timing"
    code, stdout, stderr = run_cli(["world", "--scale", "timing", "--out", str(out)])
    assert (code, stderr) == (0, "")
    assert sorted(item.name for item in out.iterdir()) == sorted([DATA_DIR, WORLD_FILE])
    world = v4_rehearsal.read_world(out)
    assert (world["scale"], world["v3_pack_sha256"]) == ("timing", None)
    assert world["data"] == run.data_record(Market.load(out / DATA_DIR).pins)
    rows = read_data_json(out / DATA_DIR)["hourly_rows"]
    assert stdout.startswith(f"v4_rehearsal world: scale timing, 12 coins, {rows} hourly rows, ")
    assert stdout.endswith(", v3 pack sha256 none, registration sha256 none\n")
    assert world["registration_sha256"] is None  # no repository: a timing run is not gated


def test_world_refuses_a_scale_that_is_not_synthetic(tmp_path, capsys):
    """Only the two synthetic scales exist: no real or registered world is written here."""
    out = tmp_path / "registered"
    with pytest.raises(SystemExit) as stopped:
        v4_rehearsal.main(["world", "--scale", "registered", "--out", str(out)])
    assert stopped.value.code == 2
    assert not out.exists()
    capsys.readouterr()


# ---- the timing world ---------------------------------------------------------------------------


def test_timing_world_shape_scaled_down(tmp_path):
    world = timing_world(**SCALED)
    coins = list(world.coins)
    assert len(coins) == len(world.coins) == 12
    assert [coin.symbol for coin in coins[:3]] == ["BTCUSDT", "S01USDT", "S02USDT"]
    assert coins[-1].symbol == "S11USDT"
    assert world.end_month == "2023-06"
    assert sorted(world.universes) == ["2023-03", "2023-04", "2023-05", "2023-06"]
    for month, selected in world.universes.items():
        assert len(selected) == len(set(selected)) == 10, month
        assert selected[0] == "BTCUSDT"
    perpetuals = [coin for coin in coins if coin.perpetual is not None]
    assert coins[0].perpetual is not None
    assert len(perpetuals) >= 9  # three coins in four
    assert sum(coin.perpetual.multiplier == 1000 for coin in perpetuals if coin.perpetual) == 4
    # One coin in eight stops trading before the world ends: a delisting.
    ends = {coin.symbol: coin.spot.end_ms for coin in coins}
    assert [symbol for symbol, end in ends.items() if end < month_start("2023-07")] == ["S08USDT"]

    data_dir = write_world(tmp_path, world)  # a few months of 12 coins: not the real size
    header = read_data_json(data_dir)
    assert header["coin_packs"] == 12
    assert header["perpetuals"] == len(perpetuals)
    assert header["multiplier_perpetuals"] == 4
    assert header["hourly_rows"] == timing_rows(**SCALED)  # the plan counts what is written
    loaded = Market.load(data_dir)
    assert loaded.window_start_ms == month_start("2023-03")
    assert loaded.window_end_ms == month_start("2023-07") - HOUR
    assert loaded.universe("2023-04") == world.universes["2023-04"]


def test_timing_world_iteration_never_hides_an_index_error(monkeypatch):
    """An ``IndexError`` raised while a coin is built propagates out of the world's coins:
    ``Sequence``'s default iteration, which stops at the first ``IndexError``, would end the world
    there and silently drop every coin after it (shown below), so ``write_world`` would write a
    short timing world."""
    world = timing_world(**SCALED)
    real = synthetic._timing_coin
    built: list[str] = []

    def failing(item):
        if len(built) == 3:
            raise IndexError("a bug inside the coin's builder")
        built.append(item.symbol)
        return real(item)

    monkeypatch.setattr(synthetic, "_timing_coin", failing)
    with pytest.raises(IndexError, match="builder"):
        list(world.coins)
    assert built == ["BTCUSDT", "S01USDT", "S02USDT"]
    # What the default iteration would have done: three coins of twelve, and no error.
    built.clear()
    assert len(list(Sequence.__iter__(world.coins))) == 3 < len(world.coins) == 12
    # Unharmed, every coin comes out, in order, as indexing gives them.
    monkeypatch.setattr(synthetic, "_timing_coin", real)
    coins = list(world.coins)
    assert [coin.symbol for coin in coins] == [world.coins[i].symbol for i in range(12)]


def test_timing_world_at_its_defaults_is_the_real_packs_size_without_building_it():
    """The defaults are the real pack's size (7.0 million rows). Only the plan is looked at: no
    price is built, and nothing is written."""
    world = timing_world()
    assert len(world.coins) == 80
    assert world.end_month == "2026-09"
    months = sorted(world.universes)
    assert (months[0], months[-1], len(months)) == ("2018-04", "2026-09", 102)
    assert all(len(selected) == 10 for selected in world.universes.values())
    assert world.universes["2018-04"][0] == "BTCUSDT"
    assert abs(timing_rows() - REAL_ROWS) < 0.03 * REAL_ROWS


@pytest.mark.parametrize(
    "arguments",
    [
        {"coins": 1},
        {"first": "2018-04"},  # not before window_first
        {"window_first": "2026-10"},  # after last
        {"first": "2017-8"},  # not a month
    ],
)
def test_timing_world_refuses_bad_arguments(arguments):
    with pytest.raises(ValueError):
        timing_world(**arguments)


# ---- read_world ---------------------------------------------------------------------------------


def data_record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "config_sha256": CONFIG_SHA256,
        "end_month": "2025-03",
        "daily_sha256": "a" * 64,
        "index_sha256": "b" * 64,
    }
    return record | changes


def good_document(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "format": WORLD_FORMAT,
        "scale": "rehearsal",
        "data": data_record(),
        "v3_pack_sha256": "c" * 64,
        "registration_sha256": None,
    }
    return document | changes


@pytest.mark.parametrize(
    "document",
    [
        good_document(),
        good_document(registration_sha256="d" * 64),  # task 7 fills it for the rehearsal scale
        good_document(v3_pack_sha256=None),
        good_document(scale="timing", v3_pack_sha256=None),
    ],
)
def test_read_world_accepts_what_world_writes(tmp_path, document):
    write_document(tmp_path, document)
    assert v4_rehearsal.read_world(tmp_path) == document


@pytest.mark.parametrize(
    "document",
    [
        good_document(format="v4-rehearsal-world-0"),
        good_document(scale="registered"),
        good_document(v3_pack_sha256="C" * 64),
        good_document(v3_pack_sha256="c" * 63),
        good_document(registration_sha256="d" * 65),
        good_document(registration_sha256=5),
        good_document(scale="timing"),  # a timing world has no V3 pack
        good_document(data={"config_sha256": CONFIG_SHA256}),
        good_document(data=data_record(end_month="2025-13")),
        good_document(data=data_record(daily_sha256="x")),
        good_document(data=data_record(config_sha256="")),
        good_document(data=data_record(extra="1")),
        {key: value for key, value in good_document().items() if key != "registration_sha256"},
        good_document() | {"unexpected": None},
        [],
    ],
)
def test_read_world_refuses_a_wrongly_shaped_file(tmp_path, document):
    write_document(tmp_path, document)
    with pytest.raises(ValueError):
        v4_rehearsal.read_world(tmp_path)


def test_read_world_refuses_a_missing_or_non_canonical_file(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        v4_rehearsal.read_world(tmp_path)
    pretty = json.dumps(good_document(), indent=1, sort_keys=True).encode()
    (tmp_path / WORLD_FILE).write_bytes(pretty)
    with pytest.raises(ValueError, match="canonical"):
        v4_rehearsal.read_world(tmp_path)
    (tmp_path / WORLD_FILE).write_bytes(_canonical(good_document()) + b"\n")
    with pytest.raises(ValueError, match="canonical"):
        v4_rehearsal.read_world(tmp_path)
    duplicate = _canonical(good_document()).replace(
        b'"scale":"rehearsal"', b'"scale":"rehearsal","scale":"timing"'
    )
    (tmp_path / WORLD_FILE).write_bytes(duplicate)
    with pytest.raises(ValueError, match="duplicate"):
        v4_rehearsal.read_world(tmp_path)
    (tmp_path / WORLD_FILE).write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        v4_rehearsal.read_world(tmp_path)
    for number in (b"1.5", b"NaN"):  # a float or a non-finite number anywhere
        (tmp_path / WORLD_FILE).write_bytes(_canonical(good_document()).replace(b"null", number, 1))
        with pytest.raises(ValueError, match="non-finite"):
            v4_rehearsal.read_world(tmp_path)


# ---- the picks command --------------------------------------------------------------------------


def fake_world(tmp_path: Path, rehearsal: Rehearsal, **changes: object) -> Path:
    """A world folder with the rehearsal's V3 pack and its world file changed."""
    folder = tmp_path / "fake"
    (folder / V3_DIR).mkdir(parents=True)
    (folder / V3_DIR / PACK_FILE).write_bytes(rehearsal.pack.read_bytes())
    write_document(folder, document_of(rehearsal.root, **changes))
    return folder


def picks_argv(world: Path, out: Path) -> list[str]:
    return ["picks", "--world", str(world), "--out", str(out)]


def test_picks_refuses_v31s_pin_and_an_unnamed_pack(rehearsal, tmp_path):
    original = baseline_v3.run_walk_forward
    out = tmp_path / "picks"
    cases = [
        # V3.1's own pin is refused whatever the pack holds.
        (
            {"v3_pack_sha256": EXPECTED_PACK_SHA256},
            "refused: the world names V3.1's registered pack",
        ),
        # A pack that does not hash to the pin the world file names.
        ({"v3_pack_sha256": "0" * 64}, "refused: the V3 pack is not the one rehearsal.json names"),
        # No pack named at all, and a world that is not a rehearsal world.
        (
            {"v3_pack_sha256": None},
            "refused: rehearsal.json does not name a rehearsal world's V3 pack",
        ),
        (
            {"scale": "timing", "v3_pack_sha256": None},
            "refused: rehearsal.json does not name a rehearsal world's V3 pack",
        ),
    ]
    for index, (changes, line) in enumerate(cases):
        world = fake_world(tmp_path / str(index), rehearsal, **changes)
        code, stdout, stderr = run_cli(picks_argv(world, out))
        assert (code, stdout) == (1, "")
        assert stderr == f"v4_rehearsal picks: {line}\n"
        assert not (out / PICKS_FILE).exists()
        assert baseline_v3.run_walk_forward is original
    # A folder without a world file, and a world file that is not canonical.
    code, _, stderr = run_cli(picks_argv(tmp_path / "nothing", out))
    assert (code, stderr) == (1, "v4_rehearsal picks: reading rehearsal.json failed: ValueError\n")
    loose = fake_world(tmp_path / "loose", rehearsal)
    (loose / WORLD_FILE).write_bytes(json.dumps(document_of(rehearsal.root), indent=1).encode())
    code, _, stderr = run_cli(picks_argv(loose, out))
    assert (code, stderr) == (1, "v4_rehearsal picks: reading rehearsal.json failed: ValueError\n")
    assert not (out / PICKS_FILE).exists()


def test_picks_writes_the_stand_in_picks(rehearsal, tmp_path):
    original = baseline_v3.run_walk_forward
    out = tmp_path / "picks"
    code, stdout, stderr = run_cli(picks_argv(rehearsal.root, out))
    assert (code, stderr) == (0, "")
    raw = (out / PICKS_FILE).read_bytes()
    assert raw == _canonical(json.loads(raw))  # canonical JSON
    digest = hashlib.sha256(raw).hexdigest()
    assert stdout == f"v4_v3_cell picks: 4 picks, {PICKS_FILE} sha256 {digest}\n"
    assert read_v3_picks(out / PICKS_FILE, digest) == REHEARSAL_PICKS
    assert baseline_v3.run_walk_forward is original  # the original again afterwards


def test_picks_refuses_an_existing_picks_file_and_restores_the_original(rehearsal, tmp_path):
    original = baseline_v3.run_walk_forward
    out = tmp_path / "picks"
    out.mkdir()
    (out / PICKS_FILE).write_bytes(b"{}")
    code, stdout, stderr = run_cli(picks_argv(rehearsal.root, out))
    assert code == 1
    assert stdout == ""
    assert "already holds" in stderr
    assert (out / PICKS_FILE).read_bytes() == b"{}"
    assert baseline_v3.run_walk_forward is original


def test_the_stand_in_records_two_attempts_around_one_short_replay(rehearsal):
    inputs = read_v3_pack(rehearsal.pack, v4_rehearsal.read_world(rehearsal.root)["v3_pack_sha256"])
    attempts: list[Attempt] = []
    with v4_rehearsal.stand_in_walk_forward():
        picks, _ = baseline_v3.selector_picks(inputs, record=attempts.append)
    assert picks == REHEARSAL_PICKS
    started, finished = attempts
    assert (started.state, finished.state) == ("started", "finished")
    assert started.run_id == finished.run_id
    assert (started.phase, started.rule, started.result) == ("training", "R2L", None)
    assert finished.result is not None
    assert (finished.start_ms, finished.end_ms_exclusive) == (V3_START_MS - 2 * DAY, V3_START_MS)
    assert finished.pick_schedule == ((V3_START_MS - 2 * DAY, "R2L"),)


def test_the_stand_in_is_restored_after_a_failure():
    original = baseline_v3.run_walk_forward
    with pytest.raises(RuntimeError), v4_rehearsal.stand_in_walk_forward():
        assert baseline_v3.run_walk_forward is not original
        raise RuntimeError("inside the block")
    assert baseline_v3.run_walk_forward is original
