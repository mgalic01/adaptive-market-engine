"""The committed full-range-2017-2024 and full-range-2019-2024 manifests, rebuilt from Bob's
digest (long-window data plan, Task 9, "The manifest PR").

IBM Bob fetched both windows on a GitHub Actions machine (run 37605943947, report
docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md, PR #198) and printed a compact
digest and three SHA-256 hashes. ``config/datasets/full-range-2017-2024.digest.txt`` is that
digest, byte for byte; ``scripts/fetch_full_range.py``'s ``rebuild`` turns it, the committed
specs and the committed exchange filters into the two manifest files. These tests pin the
files to Bob's hashes, rebuild them from the digest, and check what the plan says they hold.

Nothing here touches the network: the fixture below makes every connection raise, and no
test calls a fetch entry point. Nothing is dated after 2024-12, and no market data is read.
"""

from __future__ import annotations

import copy
import hashlib
import json
import socket
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import (
    DatasetSpec,
    archive_path,
    funding_archive_path,
    is_funding,
    load_manifest,
    load_spec,
    local_path,
    verify_dataset,
)
from crypto_grid_bot.backtest.jobs import manifest_path
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "config" / "datasets"
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_full_range  # noqa: E402

SCORED, REPORTED = "full-range-2017-2024", "full-range-2019-2024"
DIGEST_FILE = DATASETS / f"{SCORED}.digest.txt"
# What Bob's run 37605943947 printed (its report, "Results", "Hashes").
DIGEST_SHA256 = "d10331a68985b3daa678debbc666d55fe04f13bc5be5fbf15f2e337e879b89ef"
MANIFEST_SHA256 = {
    SCORED: "069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e",
    REPORTED: "40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc",
}
CREATED_AT = {SCORED: "2026-10-07T10:31:33+00:00", REPORTED: "2026-10-07T10:38:31+00:00"}
FIRST_FUNDING_MONTH, LAST_MONTH = "2020-01", "2024-12"

# The 108 archives that #156's fetch (manifest at commit 25e7136, whose strict reader gave
# them the status `unparsed`) could not read: 82 1h and 26 1m, 2018-07 to 2023-03, the first
# of them the sixth file `required()` lists. Task 7's fallback reads each with the repairing
# reader, and Bob's fetch recorded all 108 as `ok`, none `unreadable`, with the statistics
# below (from the digest's rows; checked against them by hand). Seventeen read as a
# complete month, which the digest writes as `full`: the digest never marks a repaired
# archive, so the 108 are known by name from #156's manifest and not from the digest.
# Columns: file, status, rows, expected_rows, missing_rows, gaps, first_open_ms,
# last_open_ms, timestamp_units.
TASK_7_FALLBACK = """
BTCUSDT-1m-2019-06.zip ok 43139 43200 61 1 1559347200000 1561939140000 ms
BTCUSDT-1m-2020-02.zip ok 41346 41760 414 2 1580515200000 1583020740000 ms
BTCUSDT-1m-2020-03.zip ok 44512 44640 128 1 1583020800000 1585699140000 ms
BTCUSDT-1m-2020-12.zip ok 44350 44640 290 2 1606780800000 1609459140000 ms
BTCUSDT-1m-2021-02.zip ok 40241 40320 79 1 1612137600000 1614556740000 ms
BTCUSDT-1m-2021-04.zip ok 42766 43200 434 2 1617235200000 1619827140000 ms
BTCUSDT-1m-2021-08.zip ok 44370 44640 270 1 1627776000000 1630454340000 ms
BTCUSDT-1m-2021-12.zip ok 44640 44640 0 0 1638316800000 1640995140000 ms
BTCUSDT-1m-2023-03.zip ok 44560 44640 80 1 1677628800000 1680307140000 ms
ETHUSDT-1m-2019-06.zip ok 43139 43200 61 1 1559347200000 1561939140000 ms
ETHUSDT-1m-2020-02.zip ok 41346 41760 414 2 1580515200000 1583020740000 ms
ETHUSDT-1m-2020-03.zip ok 44512 44640 128 1 1583020800000 1585699140000 ms
ETHUSDT-1m-2020-12.zip ok 44349 44640 291 2 1606780800000 1609459140000 ms
ETHUSDT-1m-2021-02.zip ok 40241 40320 79 1 1612137600000 1614556740000 ms
ETHUSDT-1m-2021-04.zip ok 42766 43200 434 2 1617235200000 1619827140000 ms
ETHUSDT-1m-2021-08.zip ok 44370 44640 270 1 1627776000000 1630454340000 ms
ETHUSDT-1m-2021-12.zip ok 44640 44640 0 0 1638316800000 1640995140000 ms
ETHUSDT-1m-2023-03.zip ok 44560 44640 80 1 1677628800000 1680307140000 ms
XRPUSDT-1m-2019-06.zip ok 43139 43200 61 1 1559347200000 1561939140000 ms
XRPUSDT-1m-2020-02.zip ok 41346 41760 414 2 1580515200000 1583020740000 ms
XRPUSDT-1m-2020-03.zip ok 44512 44640 128 1 1583020800000 1585699140000 ms
XRPUSDT-1m-2020-12.zip ok 44349 44640 291 2 1606780800000 1609459140000 ms
XRPUSDT-1m-2021-02.zip ok 40241 40320 79 1 1612137600000 1614556740000 ms
XRPUSDT-1m-2021-04.zip ok 42767 43200 433 2 1617235200000 1619827140000 ms
XRPUSDT-1m-2021-08.zip ok 44370 44640 270 1 1627776000000 1630454340000 ms
XRPUSDT-1m-2023-03.zip ok 44560 44640 80 1 1677628800000 1680307140000 ms
BNBUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
BNBUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
BNBUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
BNBUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
BNBUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
BNBUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
BNBUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
BNBUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
BNBUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
BNBUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
BTCUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
BTCUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
BTCUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
BTCUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
BTCUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
BTCUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
BTCUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
BTCUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
BTCUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
BTCUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
DOGEUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
DOGEUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
DOGEUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
DOGEUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
DOGEUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
DOGEUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
DOGEUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
DOGEUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
ETHUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
ETHUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
ETHUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
ETHUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
ETHUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
ETHUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
ETHUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
ETHUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
ETHUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
ETHUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
LINKUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
LINKUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
LINKUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
LINKUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
LINKUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
LINKUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
LINKUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
LINKUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
LINKUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
LTCUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
LTCUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
LTCUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
LTCUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
LTCUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
LTCUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
LTCUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
LTCUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
LTCUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
LTCUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
SOLUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
SOLUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
SOLUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
SOLUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
SOLUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
SOLUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
TRXUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
TRXUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
TRXUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
TRXUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
TRXUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
TRXUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
TRXUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
TRXUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
TRXUSDT-1h-2021-12.zip ok 744 744 0 0 1638316800000 1640991600000 ms
TRXUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
XRPUSDT-1h-2018-07.zip ok 737 744 7 1 1530403200000 1533078000000 ms
XRPUSDT-1h-2019-06.zip ok 720 720 0 0 1559347200000 1561935600000 ms
XRPUSDT-1h-2020-02.zip ok 690 696 6 2 1580515200000 1583017200000 ms
XRPUSDT-1h-2020-03.zip ok 743 744 1 1 1583020800000 1585695600000 ms
XRPUSDT-1h-2020-12.zip ok 740 744 4 2 1606780800000 1609455600000 ms
XRPUSDT-1h-2021-02.zip ok 671 672 1 1 1612137600000 1614553200000 ms
XRPUSDT-1h-2021-04.zip ok 715 720 5 2 1617235200000 1619823600000 ms
XRPUSDT-1h-2021-08.zip ok 740 744 4 1 1627776000000 1630450800000 ms
XRPUSDT-1h-2023-03.zip ok 743 744 1 1 1677628800000 1680303600000 ms
"""


def refuse_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("a test of the committed manifests tried to reach the network")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here can reach any host: the fetch code's connection and archive call, the
    exchange client and the socket layer raise."""
    for name in ("https_connection", "PublicClient", "exchange_filters", "archive_get"):
        monkeypatch.setattr(dataset, name, refuse_network)
    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    monkeypatch.setattr(socket, "getaddrinfo", refuse_network)


def lf_bytes(path: Path) -> bytes:
    """A committed data file's bytes with LF line endings: .gitattributes keeps them LF
    in a working tree, and this keeps the tests independent of that rule (the acceptance
    scorer's ``text_digests`` does the same for a Windows checkout)."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_file(name: str) -> Path:
    return DATASETS / f"{name}.manifest.json"


def read_manifest(name: str) -> dict[str, Any]:
    return load_manifest(manifest_file(name))


def spec_of(name: str) -> DatasetSpec:
    return load_spec(DATASETS / f"{name}.toml")


def klines_of(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest["files"] if not is_funding(entry)]


def funding_of(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest["files"] if is_funding(entry)]


def identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (entry["symbol"], entry["interval"], entry["month"])


def month_range(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:])
    months: list[str] = []
    while f"{year:04d}-{month:02d}" <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def is_full(entry: dict[str, Any]) -> bool:
    """A kline entry that holds every bar of its month, once, in milliseconds."""
    return (
        entry["status"] == "ok"
        and entry["rows"] == entry["expected_rows"]
        and entry["missing_rows"] == 0
        and entry["gaps"] == 0
        and entry["timestamp_units"] == ["ms"]
    )


def rebuilt() -> tuple[dict[str, Any], dict[str, Any]]:
    digest = lf_bytes(DIGEST_FILE).decode("utf-8")
    filters = fetch_full_range.committed_filters(fetch_full_range.FILTERS)
    return fetch_full_range.rebuild(digest, spec_of(SCORED), spec_of(REPORTED), filters)


def written(manifest: dict[str, Any]) -> bytes:
    """A manifest as ``dataset.write_manifest`` writes it."""
    return (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()


# The network is blocked ---------------------------------------------------------------------


def test_the_network_is_blocked_in_this_module() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("data.binance.vision", 443))
    with pytest.raises(AssertionError, match="network"):
        dataset.archive_get("/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip")


# Bob's digest, and the files rebuilt from it ------------------------------------------------


def test_the_digest_is_bobs_digest() -> None:
    data = lf_bytes(DIGEST_FILE)
    assert sha256_of(data) == DIGEST_SHA256
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    lines = data.decode("utf-8").splitlines()
    assert lines[0] == (
        "digest of full-range-2017-2024 and full-range-2019-2024, format v1 "
        "(scripts/fetch_full_range.py)"
    )
    # The header names both manifests with their time, their file count and their hash.
    assert lines[1] == (
        f"manifest {SCORED} created_at {CREATED_AT[SCORED]} files 1224 sha256 "
        f"{MANIFEST_SHA256[SCORED]}"
    )
    assert lines[2] == (
        f"manifest {REPORTED} created_at {CREATED_AT[REPORTED]} files 1140 sha256 "
        f"{MANIFEST_SHA256[REPORTED]}"
    )
    # One row per scored-manifest file: 1,164 klines and 60 funding archives.
    assert len(lines) == 3 + 1224


@pytest.mark.parametrize("name", [SCORED, REPORTED])
def test_each_manifest_is_the_file_bobs_run_wrote(name: str) -> None:
    data = lf_bytes(manifest_file(name))
    assert sha256_of(data) == MANIFEST_SHA256[name]
    assert data.endswith(b"}\n")
    manifest = json.loads(data)
    assert manifest["created_at"] == CREATED_AT[name]
    assert manifest["dataset"] == name
    assert manifest["schema"] == dataset.MANIFEST_SCHEMA
    assert manifest["source"] == "https://data.binance.vision"


def test_the_digest_rebuilds_both_manifests_byte_for_byte() -> None:
    first, second = rebuilt()
    for manifest in (first, second):
        name = manifest["dataset"]
        assert written(manifest) == lf_bytes(manifest_file(name))
        assert sha256_of(written(manifest)) == MANIFEST_SHA256[name]
    # And the other way: the digest's text is what the script prints for these manifests.
    digest = fetch_full_range.digest_text(first, second, MANIFEST_SHA256)
    assert digest.encode() == lf_bytes(DIGEST_FILE)


def test_the_manifests_carry_the_committed_exchange_filters_of_the_stage_1_window() -> None:
    """Bob's fetch copied the filters (and their ``fetched_at``) from the committed
    long-bull-bear-2022 manifest, so that no request went to data-api.binance.vision."""
    committed = load_manifest(DATASETS / "long-bull-bear-2022.manifest.json")["instruments"]
    for name in (SCORED, REPORTED):
        instruments = read_manifest(name)["instruments"]
        assert sorted(instruments) == ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
        assert instruments == {symbol: committed[symbol] for symbol in instruments}


def test_the_manifests_sit_beside_their_specs() -> None:
    for name in (SCORED, REPORTED):
        assert manifest_path(DATASETS / f"{name}.toml") == manifest_file(name)
        assert manifest_file(name).is_file()


def test_no_entry_is_after_the_development_window() -> None:
    """The reserved window starts in 2025: nothing of it is listed, named or requested."""
    for name in (SCORED, REPORTED):
        files = read_manifest(name)["files"]
        assert max(entry["month"] for entry in files) == LAST_MONTH
        assert not [e for e in files if fetch_full_range.RESERVED_NAME.search(e["url"])]


# Section 4's windows ------------------------------------------------------------------------


def test_full_range_2017_2024_lists_1164_klines_and_60_funding_archives() -> None:
    manifest, spec = read_manifest(SCORED), spec_of(SCORED)
    klines, funding = klines_of(manifest), funding_of(manifest)
    assert len(klines) == 1164
    assert len(funding) == 60
    assert len(manifest["files"]) == 1224
    # The klines are the spec's required() files, once each, in its order, and then the
    # funding entries.
    assert [identity(entry) for entry in klines] == spec.required()
    assert manifest["files"] == klines + funding
    assert Counter((e["interval"], e["status"]) for e in klines) == {
        ("1m", "ok"): 216,
        ("1h", "ok"): 665,
        ("1h", "missing"): 46,
        ("1d", "ok"): 237,
    }
    # BTCUSDT's funding archives for every evaluation month from 2020-01, all ok.
    assert [(e["symbol"], e["month"]) for e in funding] == [
        ("BTCUSDT", month) for month in month_range(FIRST_FUNDING_MONTH, LAST_MONTH)
    ]
    assert len(funding) == 60
    for entry in funding:
        assert entry["kind"] == dataset.FUNDING_KIND
        assert entry["status"] == "ok"
        assert entry["records"] > 0
        assert entry["bytes"] > 0
        assert entry["url"] == (
            "https://data.binance.vision" + funding_archive_path("BTCUSDT", entry["month"])
        )
    for entry in klines:
        assert entry["url"] == (
            "https://data.binance.vision"
            + archive_path(entry["symbol"], entry["interval"], entry["month"])
        )


def test_full_range_2019_2024_holds_exactly_its_required_files_as_the_scored_entries() -> None:
    scored, reported = read_manifest(SCORED), read_manifest(REPORTED)
    spec = spec_of(REPORTED)
    klines = klines_of(reported)
    assert len(klines) == len(spec.required()) == 1080
    assert [identity(entry) for entry in klines] == spec.required()
    scored_by_file = {identity(entry): entry for entry in klines_of(scored)}
    # Every entry is the 2017-2024 entry for the same file, field for field.
    for entry in klines:
        assert entry == scored_by_file[identity(entry)]
    # Plus the 60 funding entries, the same ones.
    assert funding_of(reported) == funding_of(scored)
    assert len(funding_of(reported)) == 60
    assert reported["files"] == klines + funding_of(reported)
    assert len(reported["files"]) == 1140
    # Its files are a strict subset of the scored window's: 1m from 2019-07, 1h from 2019-01
    # and 1d from 2018-07, so 84 of the scored window's 1,164 are not in it.
    assert set(scored_by_file) > {identity(entry) for entry in klines}
    assert len(scored_by_file) - len(klines) == 84
    assert Counter(entry["status"] for entry in klines) == {"ok": 1055, "missing": 25}
    assert reported["instruments"] == scored["instruments"]


# The pre-listing months ---------------------------------------------------------------------


def covered_by_an_exclusion(spec: DatasetSpec, entry: dict[str, Any]) -> bool:
    """The whole month lies inside one of the spec's documented basket absences."""
    start, end = month_bounds_ms(entry["month"])
    return any(
        x.symbol == entry["symbol"] and x.start_ms <= start and end <= x.end_ms
        for x in spec.basket_exclusions
    )


def test_the_46_missing_archives_of_the_scored_window_are_the_pre_listing_months() -> None:
    manifest, spec = read_manifest(SCORED), spec_of(SCORED)
    missing = [e for e in klines_of(manifest) if e["status"] == "missing"]
    # The 1h archives before each listing: SOLUSDT's first candle is 2020-08-11T06:00Z,
    # DOGEUSDT's 2019-07-05T12:00Z and LINKUSDT's 2019-01-16T10:00Z.
    expected = (
        {("SOLUSDT", "1h", m) for m in month_range("2018-06", "2020-07")}
        | {("DOGEUSDT", "1h", m) for m in month_range("2018-06", "2019-06")}
        | {("LINKUSDT", "1h", m) for m in month_range("2018-06", "2018-12")}
    )
    assert len(expected) == 26 + 13 + 7 == 46
    assert len(missing) == 46
    assert {identity(entry) for entry in missing} == expected
    for entry in missing:
        # A missing archive's entry has a name, a status and its URL, and no checksum, size
        # or statistics.
        assert sorted(entry) == ["interval", "month", "status", "symbol", "url"]
        assert covered_by_an_exclusion(spec, entry)


def test_the_25_missing_archives_of_the_reported_window_are_the_pre_listing_months() -> None:
    manifest, spec = read_manifest(REPORTED), spec_of(REPORTED)
    missing = [e for e in klines_of(manifest) if e["status"] == "missing"]
    expected = {("SOLUSDT", "1h", m) for m in month_range("2019-01", "2020-07")} | {
        ("DOGEUSDT", "1h", m) for m in month_range("2019-01", "2019-06")
    }
    assert len(expected) == 19 + 6 == 25
    assert {identity(entry) for entry in missing} == expected
    # LINKUSDT's first archive, 2019-01, exists: it lists from 2019-01-16.
    assert ("LINKUSDT", "1h", "2019-01") not in expected
    for entry in missing:
        assert covered_by_an_exclusion(spec, entry)


# Task 7's fallback --------------------------------------------------------------------------


class Pinned(NamedTuple):
    name: str
    status: str
    rows: int
    expected_rows: int
    missing_rows: int
    gaps: int
    first_open_ms: int
    last_open_ms: int
    timestamp_units: tuple[str, ...]


def fallback_rows() -> list[Pinned]:
    rows = []
    for line in TASK_7_FALLBACK.strip().splitlines():
        name, status, *numbers, units = line.split(" ")
        rows.append(Pinned(name, status, *(int(n) for n in numbers), tuple(units.split(","))))
    return rows


def month_of(name: str) -> str:
    """'BTCUSDT-1m-2019-06.zip' is the archive of 2019-06."""
    return "-".join(name.removesuffix(".zip").split("-")[2:])


def test_task_7s_fallback_is_pinned_for_each_of_the_108_unparsed_archives() -> None:
    pinned = fallback_rows()
    spec, manifest = spec_of(SCORED), read_manifest(SCORED)
    by_name = {fetch_full_range.file_name(entry): entry for entry in manifest["files"]}
    names = [row.name for row in pinned]
    assert len(names) == len(set(names)) == 108
    assert sum("-1h-" in name for name in names) == 82
    assert sum("-1m-" in name for name in names) == 26
    assert (min(map(month_of, names)), max(map(month_of, names))) == ("2018-07", "2023-03")
    # In required()'s order, the first of them the sixth file it lists.
    order = [fetch_full_range.kline_file(*file) for file in spec.required()]
    assert names == sorted(names, key=order.index)
    assert order.index(names[0]) == 5
    assert names[0] == "BTCUSDT-1m-2019-06.zip"
    complete_reads = 0
    for row in pinned:
        entry = by_name[row.name]
        assert entry["status"] == row.status == "ok"  # none is `unreadable`
        assert "reason" not in entry
        assert entry["rows"] == row.rows
        assert entry["expected_rows"] == row.expected_rows
        assert entry["missing_rows"] == row.missing_rows == row.expected_rows - row.rows
        assert entry["gaps"] == row.gaps
        assert entry["first_open_ms"] == row.first_open_ms
        assert entry["last_open_ms"] == row.last_open_ms
        assert tuple(entry["timestamp_units"]) == row.timestamp_units == ("ms",)
        complete_reads += is_full(entry)
    # Seventeen of the repaired reads are complete months, which the digest writes `full`.
    assert complete_reads == 17


def test_the_digest_marks_no_repaired_archive_and_no_unreadable_one() -> None:
    """The plan describes the 108 as the digest's repaired or unreadable rows. It has none
    of either: no row is `unreadable`, and a repaired archive is a plain `ok` row. Its rows
    that are not `full` are 212 (161 1h and 51 1m), of which 91 are among the 108; the other
    121 were `ok` in #156's manifest too, strict reads of months with real gaps."""
    klines = klines_of(read_manifest(SCORED))
    assert not [e for e in klines if e["status"] not in ("ok", "missing")]
    not_full = [e for e in klines if e["status"] == "ok" and not is_full(e)]
    assert len(not_full) == 212
    assert sum(e["interval"] == "1h" for e in not_full) == 161
    assert sum(e["interval"] == "1m" for e in not_full) == 51
    assert all(e["interval"] != "1d" for e in not_full)
    pinned = {row.name for row in fallback_rows()}
    among = [e for e in not_full if fetch_full_range.file_name(e) in pinned]
    assert len(among) == 91
    assert len(not_full) - len(among) == 121


# What the loaders and verify accept ---------------------------------------------------------


@pytest.mark.parametrize("name", [SCORED, REPORTED])
def test_load_manifest_and_verify_accept_the_manifest(name: str, tmp_path: Path) -> None:
    path, spec = manifest_file(name), spec_of(name)
    manifest = load_manifest(path)
    assert manifest == json.loads(path.read_text(encoding="utf-8"))
    # verify_dataset validates the manifest, its dataset, its coverage of the spec's files
    # and the funding entries before it opens a local archive, and this checkout has none:
    # the first error is the first archive's absence, so every manifest check has passed.
    first = next(e for e in manifest["files"] if e["status"] != "missing")
    path_of_first = local_path(tmp_path, first["symbol"], first["interval"], first["month"])
    with pytest.raises(DataError, match="missing local archive") as raised:
        verify_dataset(spec, manifest, tmp_path)
    assert str(path_of_first) in str(raised.value)
    assert identity(first) == spec.required()[0]


def test_verify_refuses_a_manifest_that_does_not_cover_its_spec() -> None:
    """The check above would be vacuous if verify_dataset accepted anything."""
    scored, spec = read_manifest(SCORED), spec_of(SCORED)
    short = copy.deepcopy(scored)
    short["files"].pop(100)
    with pytest.raises(DataError, match="do not match the dataset spec"):
        verify_dataset(spec, short, Path("nowhere"))
    with pytest.raises(DataError, match="different dataset"):
        verify_dataset(spec, read_manifest(REPORTED), Path("nowhere"))
    # The scored manifest under the reported window's name holds files that spec does not.
    with pytest.raises(DataError, match="do not match the dataset spec"):
        verify_dataset(spec_of(REPORTED), {**scored, "dataset": REPORTED}, Path("nowhere"))
