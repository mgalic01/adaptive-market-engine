"""The v4-data workflow's month guard (``scripts/v4_data_month_guard.py``) on fake trees.

The network is blocked for every test in this file (the autouse fixture below); the guard
only walks a folder and reads the data config.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_data_month_guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """The committed config with end_month 2024-03."""
    document = json.loads((ROOT / "config" / "v4_data.json").read_text(encoding="utf-8"))
    path = tmp_path / "v4_data.json"
    path.write_text(json.dumps(document | {"end_month": "2024-03"}), encoding="ascii")
    return path


def tree(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return root


def guard(config: Path, root: Path, capsys) -> tuple[int, str]:
    code = v4_data_month_guard.main(["--config", str(config), "--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


ARCHIVES = "fetched/cache/data/spot/monthly/klines/AAAUSDT/1h/"


def test_files_at_or_before_end_month_pass(tmp_path, config, capsys):
    root = tree(
        tmp_path / "v4",
        ARCHIVES + "AAAUSDT-1h-2024-03.zip",
        ARCHIVES + "AAAUSDT-1h-2023-12.zip",
        "fetched/manifests/manifest-spot_1h-0.json",
        "data/daily.pack.json.gz",
        "data/data.json",
        "2024-09/notes.txt",  # a folder's name is not a file's
    )
    code, output = guard(config, root, capsys)
    assert code == 0, output
    assert "6 files checked; none is named for a month after end_month 2024-03" in output


def test_a_file_named_for_a_month_after_end_month_fails(tmp_path, config, capsys):
    root = tree(
        tmp_path / "v4",
        ARCHIVES + "AAAUSDT-1h-2024-03.zip",
        ARCHIVES + "AAAUSDT-1h-2024-04.zip",
        "fetched/cache/data/futures/um/monthly/fundingRate/AAAUSDT/AAAUSDT-fundingRate-2025-01.zip",
    )
    code, output = guard(config, root, capsys)
    assert code == 1
    assert "AAAUSDT-1h-2024-04.zip" in output and "AAAUSDT-fundingRate-2025-01.zip" in output
    assert "AAAUSDT-1h-2024-03.zip" not in output
    assert "2 files are named for a month after end_month 2024-03" in output


def test_a_folder_that_cannot_be_listed_fails_closed(tmp_path, config, capsys, monkeypatch):
    root = tree(tmp_path / "v4", "data/data.json", "fetched/locked/AAAUSDT-1h-2024-09.zip")
    scandir = v4_data_month_guard.os.scandir

    def refuse_locked(path):
        if Path(path).name == "locked":
            raise PermissionError(13, "Permission denied", str(path))
        return scandir(path)

    # os.walk lists each folder with os.scandir; the locked one now cannot be listed.
    monkeypatch.setattr(v4_data_month_guard.os, "scandir", refuse_locked)
    code, output = guard(config, root, capsys)
    assert code == 1
    assert "could not check" in output and "Permission denied" in output


def test_a_missing_folder_or_a_refused_config_fails(tmp_path, config, capsys):
    assert guard(config, tmp_path / "absent", capsys)[0] == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="ascii")
    assert guard(bad, tree(tmp_path / "v4", "a.txt"), capsys)[0] == 1
