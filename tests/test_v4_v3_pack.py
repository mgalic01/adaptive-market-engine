"""V4's V3 input pack, built on GitHub: ``scripts/v4_v3_pack.py``.

The ``v3_as_built`` arm needs V3's own inputs. The script rebuilds the pack V3.1's registered
prepare built (``config/v3_1_run_manifest.json`` ``v3_pack_sha256``): it fetches the archives
V3's inventory manifest lists as present, each verified against its pinned SHA-256, lays them
out as V3's loader reads them, builds the pack with ``v31_v3_pack.build_v3_pack`` and exits 0
only if the pack's pin is V3.1's.

The network is blocked for every test in this file (the autouse fixture below, as in
``tests/test_v4_diagnose.py``) and the host is a fake that serves bytes from a dict. A test
never reaches data.binance.vision. The pack builder is replaced by a spy except where a test
reads the committed files: V3's frozen loader decodes all 1914 archives, which belongs to the
GitHub job, not to the owner's PC.
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_v3_pack  # noqa: E402
from fetch_v3_data import archive_path  # noqa: E402

MANIFEST_PATH = "config/datasets/v3-20261009/inventory.manifest.json"
MANIFEST_SHA256 = "78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a"
V31_PACK_SHA256 = "8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee"
PACK_FILE = "v3-input.pack.json.gz"
FIRST_MONTHS = {"BTCUSDT": "2020-01", "ETHUSDT": "2020-02"}
OTHER_PIN = "0123456789abcdef" * 4


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


def test_the_network_is_blocked_here():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("data.binance.vision", 443)
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("data.binance.vision", 443))


# ---- a three-entry world --------------------------------------------------------------------


class FakeTransport:
    """The archive host: bytes by path, and the paths asked for."""

    def __init__(self, archives: dict[str, bytes]) -> None:
        self.archives = archives
        self.requests: list[str] = []

    def archive(self, path: str) -> bytes | None:
        self.requests.append(path)
        return self.archives.get(path)


@dataclass
class Builder:
    """Stands in for ``build_v3_pack``: records the call and the collection it was given,
    writes a pack file, and returns ``pin`` (or raises ``error`` after writing it)."""

    pin: str = V31_PACK_SHA256
    error: Exception | None = None
    calls: list[tuple[Path, str, dict[str, str], Path]] = field(default_factory=list)
    layout: dict[str, bytes] = field(default_factory=dict)

    def __call__(
        self, inventory_root: Path, manifest_sha256: str, first_months: Any, path: Path
    ) -> str:
        self.calls.append((inventory_root, manifest_sha256, dict(first_months), path))
        self.layout = {
            file.relative_to(inventory_root).as_posix(): file.read_bytes()
            for file in sorted(inventory_root.rglob("*"))
            if file.is_file()
        }
        path.write_bytes(b"a pack, or half of one")
        if self.error is not None:
            raise self.error
        return self.pin


@dataclass
class World:
    repo: Path
    manifest: bytes
    manifest_sha256: str
    archives: dict[str, bytes]  # the present entries' archives, by path
    missing_path: str
    snapshots: dict[str, bytes]


def entry(kind: str, month: str, content: bytes | None, status: str) -> dict[str, object]:
    # archive_path refuses a month from 2025 on, so the month is swapped into a 2020-01 path.
    path = archive_path(kind, "BTCUSDT", "2020-01").replace("2020-01", month)
    return {
        "kind": kind,
        "symbol": "BTCUSDT",
        "month": month,
        "path": path,
        "local_path": "archives" + path,
        "sha256": None if content is None else hashlib.sha256(content).hexdigest(),
        "status": status,
    }


def make_world(tmp_path: Path, months: tuple[str, str, str] = ("2020-01",) * 3) -> World:
    """A repository holding a three-entry inventory manifest (spot and futures present,
    funding missing), its two snapshots and V3's calendar, in the committed layout."""
    spot, futures = b"spot archive bytes", b"futures archive bytes"
    entries = [
        entry("spot", months[0], spot, "eligible"),
        entry("futures", months[1], futures, "excluded"),
        entry("funding", months[2], None, "missing"),
    ]
    snapshots = {"spot": b'{"fake": "spot filters"}', "futures": b'{"fake": "futures filters"}'}
    document = {
        "entries": entries,
        "snapshots": {
            market: {
                "path": f"snapshots/{market}.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
            for market, raw in snapshots.items()
        },
    }
    manifest = json.dumps(document, sort_keys=True).encode()
    repo = tmp_path / "repo"
    collection = repo / "config" / "datasets" / "v3-20261009"
    (collection / "snapshots").mkdir(parents=True)
    (collection / "inventory.manifest.json").write_bytes(manifest)
    for market, raw in snapshots.items():
        (collection / "snapshots" / f"{market}.json").write_bytes(raw)
    config = {"experiment": "v3", "first_months": FIRST_MONTHS, "schema_version": 1}
    (repo / "config" / "v3-development-run.json").write_text(json.dumps(config), encoding="utf-8")
    return World(
        repo,
        manifest,
        hashlib.sha256(manifest).hexdigest(),
        {str(entries[0]["path"]): spot, str(entries[1]["path"]): futures},
        str(entries[2]["path"]),
        snapshots,
    )


def run(
    tmp_path: Path,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    *,
    builder: Builder | None = None,
    archives: dict[str, bytes] | None = None,
    pinned: str | None = None,
) -> tuple[int, FakeTransport, Builder]:
    """``v4_v3_pack.main`` over ``world`` with the manifest pin of the world (or ``pinned``),
    the fake host and the spy builder."""
    builder = Builder() if builder is None else builder
    transport = FakeTransport(world.archives if archives is None else archives)
    monkeypatch.setattr(v4_v3_pack, "MANIFEST_SHA256", pinned or world.manifest_sha256)
    monkeypatch.setattr(v4_v3_pack, "build_v3_pack", builder)
    argv = [
        "--repo",
        str(world.repo),
        "--work",
        str(tmp_path / "work"),
        "--out",
        str(tmp_path / "out"),
    ]
    return v4_v3_pack.main(argv, transport=transport), transport, builder


def files_under(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*") if path.is_file()) if folder.exists() else []


# ---- the job -----------------------------------------------------------------------------------


def test_v3_pack_fetches_every_present_entry_and_skips_the_missing_ones(
    tmp_path, monkeypatch, capsys
):
    world = make_world(tmp_path)
    code, transport, builder = run(tmp_path, world, monkeypatch)
    captured = capsys.readouterr()

    assert code == 0, captured.err
    # Exactly the two present archives were requested; the missing month never was.
    assert sorted(transport.requests) == sorted(world.archives)
    assert world.missing_path not in transport.requests
    # The builder got V3's collection layout under work/inventory: the manifest's pinned bytes,
    # both snapshots and the verified archives under archives/<path>, and nothing else.
    (root, manifest_sha256, first_months, pack), *rest = builder.calls
    assert rest == []
    assert root == tmp_path / "work" / "inventory"
    assert manifest_sha256 == world.manifest_sha256
    assert first_months == FIRST_MONTHS
    assert pack == tmp_path / "out" / PACK_FILE
    expected = {
        "inventory.manifest.json": world.manifest,
        "snapshots/spot.json": world.snapshots["spot"],
        "snapshots/futures.json": world.snapshots["futures"],
    }
    expected.update({"archives" + path: content for path, content in world.archives.items()})
    assert builder.layout == expected
    # The pack is there, and stdout is the archive count, the bytes and the pin: nothing else.
    assert pack.read_bytes() == b"a pack, or half of one"
    total = sum(len(content) for content in world.archives.values())
    lines = captured.out.splitlines()
    assert len(lines) == 2, lines
    assert "2 archives" in lines[0] and f"{total} bytes" in lines[0]
    assert V31_PACK_SHA256 in lines[1]


def test_v3_pack_refuses_an_archive_whose_sha256_changed(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    changed = dict(world.archives)
    victim = sorted(changed)[0]
    changed[victim] = changed[victim] + b" changed on the host"
    code, transport, builder = run(tmp_path, world, monkeypatch, archives=changed)
    captured = capsys.readouterr()

    assert code == 1
    assert "do not match the pinned sha256" in captured.err
    # Nothing was built, and the changed bytes were not kept.
    assert builder.calls == []
    assert files_under(tmp_path / "out") == []
    assert not (tmp_path / "work" / "inventory" / "archives" / victim.lstrip("/")).exists()
    assert captured.out == ""


def test_v3_pack_refuses_a_pack_whose_pin_is_not_v3_1s(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    code, _, builder = run(tmp_path, world, monkeypatch, builder=Builder(pin=OTHER_PIN))
    captured = capsys.readouterr()

    assert code == 1
    assert len(builder.calls) == 1  # it was built, and then refused
    assert files_under(tmp_path / "out") == []  # no file left
    assert OTHER_PIN in captured.err and V31_PACK_SHA256 in captured.err
    assert OTHER_PIN not in captured.out and V31_PACK_SHA256 not in captured.out


@pytest.mark.parametrize("error", [ValueError("the loader refused"), OSError("disk")])
def test_v3_pack_removes_what_a_failing_build_left(tmp_path, monkeypatch, capsys, error):
    world = make_world(tmp_path)
    code, _, builder = run(tmp_path, world, monkeypatch, builder=Builder(error=error))
    captured = capsys.readouterr()

    assert code == 1
    assert len(builder.calls) == 1
    assert files_under(tmp_path / "out") == []
    assert str(error) in captured.err


def test_v3_pack_refuses_a_manifest_that_is_not_the_pinned_one(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    # The pin is the committed manifest's, not the fake world's.
    code, transport, builder = run(tmp_path, world, monkeypatch, pinned=MANIFEST_SHA256)
    captured = capsys.readouterr()

    assert code == 1
    assert "manifest" in captured.err and MANIFEST_SHA256 in captured.err
    assert transport.requests == []  # nothing was requested
    assert builder.calls == []
    assert not (tmp_path / "work").exists() and not (tmp_path / "out").exists()
    assert captured.out == ""


def test_v3_pack_refuses_a_manifest_whose_snapshot_is_not_the_one_it_records(
    tmp_path, monkeypatch, capsys
):
    world = make_world(tmp_path)
    snapshot = world.repo / "config/datasets/v3-20261009/snapshots/spot.json"
    snapshot.write_bytes(b'{"fake": "other spot filters"}')
    code, transport, builder = run(tmp_path, world, monkeypatch)

    assert code == 1
    assert "spot" in capsys.readouterr().err
    assert transport.requests == [] and builder.calls == []


def test_v3_pack_refuses_a_month_from_the_reserved_window(tmp_path, monkeypatch, capsys):
    # Owner decision v4-d03: nothing from 2025-01 on is requested before the registered run,
    # even when a manifest pinned at that very hash lists it.
    world = make_world(tmp_path, months=("2020-01", "2025-01", "2020-01"))
    code, transport, builder = run(tmp_path, world, monkeypatch)

    assert code == 1
    assert "2025" in capsys.readouterr().err
    assert transport.requests == [] and builder.calls == []


def test_v3_pack_refuses_a_pack_that_is_already_there_and_leaves_it(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / PACK_FILE).write_bytes(b"an earlier pack")
    code, transport, builder = run(tmp_path, world, monkeypatch)

    assert code == 1
    assert PACK_FILE in capsys.readouterr().err
    assert (tmp_path / "out" / PACK_FILE).read_bytes() == b"an earlier pack"
    assert transport.requests == [] and builder.calls == []


def test_v3_pack_refuses_a_calendar_that_is_not_v3s(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    config = {"experiment": "v3", "first_months": FIRST_MONTHS, "schema_version": 2}
    (world.repo / "config" / "v3-development-run.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    code, transport, builder = run(tmp_path, world, monkeypatch)

    assert code == 1
    assert "v3-development-run.json" in capsys.readouterr().err
    assert transport.requests == [] and builder.calls == []


def test_v3_pack_uses_v3s_own_transport_by_default(tmp_path, monkeypatch, capsys):
    world = make_world(tmp_path)
    made: list[FakeTransport] = []

    def factory() -> FakeTransport:
        made.append(FakeTransport(world.archives))
        return made[-1]

    monkeypatch.setattr(v4_v3_pack, "MANIFEST_SHA256", world.manifest_sha256)
    monkeypatch.setattr(v4_v3_pack, "build_v3_pack", Builder())
    monkeypatch.setattr(v4_v3_pack, "V3Transport", factory)
    argv = ["--repo", str(world.repo), "--work", str(tmp_path / "w"), "--out", str(tmp_path / "o")]

    assert v4_v3_pack.main(argv) == 0
    assert len(made) == 1 and sorted(made[0].requests) == sorted(world.archives)


def test_v3_pack_needs_a_work_and_an_out_folder():
    with pytest.raises(SystemExit) as raised:
        v4_v3_pack.main(["--work", "w"])
    assert raised.value.code == 2


# ---- the pins are the committed ones -----------------------------------------------------------


def test_the_pins_are_the_committed_ones():
    """The script's two pins are the committed manifest's and V3.1's registered pack pin, the
    snapshots are the ones the run manifest pins, and the manifest lists no month from 2025."""
    assert v4_v3_pack.MANIFEST_SHA256 == MANIFEST_SHA256
    assert v4_v3_pack.EXPECTED_PACK_SHA256 == V31_PACK_SHA256
    raw = (ROOT / MANIFEST_PATH).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256
    run_manifest = json.loads((ROOT / "config" / "v3_1_run_manifest.json").read_text("utf-8"))
    assert run_manifest["v3_pack_sha256"] == V31_PACK_SHA256
    for relative, pin in run_manifest["filter_snapshots"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == pin
    document = json.loads(raw)
    assert len(document["entries"]) == 2710
    present = [e for e in document["entries"] if e["status"] != "missing"]
    assert len(present) == 1914
    assert max(e["month"] for e in present) < "2025-01"
