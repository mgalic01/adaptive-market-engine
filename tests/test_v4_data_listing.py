"""V4 data step: the archive listing, symbol discovery and per-kind month discovery.

The network is blocked for every test in this file (the autouse fixture below). Discovery runs
against a fake bucket that serves S3 ``ListBucketResult`` XML built from small fixtures and
records the listing URLs it is asked for; the one real transport, ``HttpTransport``, is only
used to prove that those URLs pass its allowlist (it then stops at the blocked socket).
"""

from __future__ import annotations

import socket
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from crypto_grid_bot.v4.data import archives, listing
from crypto_grid_bot.v4.data.archives import HttpTransport, archive_path
from crypto_grid_bot.v4.data.config import DataConfig, load_data_config
from crypto_grid_bot.v4.data.listing import (
    ListingPage,
    discover_months,
    discover_spot_usdt_symbols,
    list_all,
    parse_listing,
)

ROOT = Path(__file__).resolve().parents[1]
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = "http://s3.amazonaws.com/doc/2006-03-01/"
KLINES = "data/spot/monthly/klines/"
KINDS = ("spot_1d", "spot_1h", "futures_1h", "funding")


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
def config() -> DataConfig:
    return replace(load_data_config(ROOT / "config" / "v4_data.json"), end_month="2026-09")


def listing_xml(
    prefixes=(),
    keys=(),
    *,
    truncated: bool | None = False,
    next_marker: str | None = None,
    requested: str = "",
) -> bytes:
    """An S3 ListBucketResult page. ``truncated`` None leaves IsTruncated out."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<ListBucketResult xmlns="{NS}">',
        "<Name>data.binance.vision</Name>",
        f"<Prefix>{escape(requested)}</Prefix>",
        "<Marker></Marker>",
        "<Delimiter>/</Delimiter>",
    ]
    if truncated is not None:
        parts.append(f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>")
    if next_marker is not None:
        parts.append(f"<NextMarker>{escape(next_marker)}</NextMarker>")
    for key in keys:
        parts.append(
            f"<Contents><Key>{escape(key)}</Key><LastModified>2023-01-01T00:00:00.000Z</LastModified>"
            '<ETag>"abc"</ETag><Size>123</Size><StorageClass>STANDARD</StorageClass></Contents>'
        )
    for prefix in prefixes:
        parts.append(f"<CommonPrefixes><Prefix>{escape(prefix)}</Prefix></CommonPrefixes>")
    parts.append("</ListBucketResult>")
    return "".join(parts).encode("utf-8")


def url_of(prefix: str, marker: str | None = None) -> str:
    """The exact listing URL for ``prefix``, continued after ``marker`` if there is one."""
    url = f"{LISTING}?delimiter=/&prefix={prefix}"
    return url if marker is None else f"{url}&marker={marker}"


class FakeBucket:
    """Serves bytes from a dict of listing URL -> body, 404 (None) for the rest, and records
    the URLs it is asked for."""

    def __init__(self, pages=None):
        self.pages = dict(pages or {})
        self.requests: list[str] = []

    def get(self, url):
        self.requests.append(url)
        return self.pages.get(url)


def klines_bucket(*symbols: str) -> FakeBucket:
    """A bucket whose spot klines listing is one complete page of these symbols."""
    prefixes = [f"{KLINES}{symbol}/" for symbol in symbols]
    return FakeBucket({url_of(KLINES): listing_xml(prefixes=prefixes, requested=KLINES)})


def month_keys(kind: str, symbol: str, *months: str) -> list[str]:
    """The keys of these months' archives as the bucket lists them (no leading slash)."""
    return [archive_path(kind, symbol, month).lstrip("/") for month in months]


def months_bucket(kind: str, symbol: str, keys: list[str]) -> tuple[FakeBucket, str]:
    """A bucket whose listing of one symbol's kind is one complete page of ``keys``."""
    prefix = archive_path(kind, symbol, "2020-01").lstrip("/").rsplit("/", 1)[0] + "/"
    return FakeBucket({url_of(prefix): listing_xml(keys=keys, requested=prefix)}), prefix


# --- parse_listing ------------------------------------------------------------------------


def test_parse_listing_reads_prefixes_keys_and_marker():
    xml = listing_xml(
        prefixes=[f"{KLINES}BTCUSDT/", f"{KLINES}ETHUSDT/"],
        keys=[f"{KLINES}x/a.zip", f"{KLINES}x/b.zip.CHECKSUM"],
        truncated=True,
        next_marker=f"{KLINES}ETHUSDT/",
        requested=KLINES,
    )

    page = parse_listing(xml)

    assert page == ListingPage(
        prefixes=(f"{KLINES}BTCUSDT/", f"{KLINES}ETHUSDT/"),
        keys=(f"{KLINES}x/a.zip", f"{KLINES}x/b.zip.CHECKSUM"),
        next_marker=f"{KLINES}ETHUSDT/",
    )
    # The request's own <Prefix> element sits beside the entries and is not one of them.
    assert KLINES not in page.prefixes


def test_parse_listing_of_an_empty_listing_is_an_empty_page():
    assert parse_listing(listing_xml()) == ListingPage((), (), None)


def test_a_complete_page_has_no_marker():
    # IsTruncated false, or absent, ends the listing even if a NextMarker element is there.
    for truncated in (False, None):
        page = parse_listing(
            listing_xml(keys=["data/a"], truncated=truncated, next_marker="data/z")
        )
        assert page.next_marker is None
        assert page.keys == ("data/a",)


def test_a_truncated_page_without_a_next_marker_continues_after_its_last_entry():
    # With a delimiter, keys and prefixes share one sort order; the greatest of the two lists'
    # last entries is where the page stopped.
    keys_last = listing_xml(keys=["data/a", "data/m"], prefixes=["data/b/"], truncated=True)
    prefixes_last = listing_xml(keys=["data/a"], prefixes=["data/b/", "data/q/"], truncated=True)
    only_keys = listing_xml(keys=["data/a", "data/c"], truncated=True)
    only_prefixes = listing_xml(prefixes=["data/b/", "data/d/"], truncated=True)

    assert parse_listing(keys_last).next_marker == "data/m"
    assert parse_listing(prefixes_last).next_marker == "data/q/"
    assert parse_listing(only_keys).next_marker == "data/c"
    assert parse_listing(only_prefixes).next_marker == "data/d/"


def test_a_truncated_page_with_nothing_to_continue_from_is_refused():
    # Otherwise list_all would ask for the same page for ever.
    with pytest.raises(ValueError, match="truncated.*marker"):
        parse_listing(listing_xml(truncated=True))


def test_the_listing_page_is_immutable():
    page = parse_listing(listing_xml(keys=["data/a"]))

    with pytest.raises(FrozenInstanceError):
        page.keys = ()  # type: ignore[misc]


def s3(body: str) -> bytes:
    """A document in the S3 namespace whose root is a ListBucketResult holding ``body``."""
    return f'<ListBucketResult xmlns="{NS}">{body}</ListBucketResult>'.encode()


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        (b"", "XML"),
        (b"not xml at all", "XML"),
        (listing_xml(keys=["data/a"])[:-30], "XML"),  # cut short mid-document
        (b"<?xml version='1.0'?><ListBucketResult><Contents><Key>a</Key></Contents>", "XML"),
        # well-formed, but not an S3 ListBucketResult in the S3 namespace
        (b"<ListBucketResult><Contents><Key>data/a</Key></Contents></ListBucketResult>", "S3"),
        (b'<ListBucketResult xmlns="http://example.org/"/>', "S3"),
        (f'<Error xmlns="{NS}"><Code>AccessDenied</Code></Error>'.encode(), "S3"),
        (f'<html xmlns="{NS}"></html>'.encode(), "S3"),
        # not UTF-8
        (s3("<Name>x</Name>").replace(b"x", bytes([0xFF])), "UTF-8"),
        # a DTD, and the entity expansions it allows
        (
            b'<?xml version="1.0"?><!DOCTYPE ListBucketResult [<!ENTITY a "aaaa">]>'
            + s3("<Name>&a;</Name>"),
            "DOCTYPE",
        ),
        (b'<!DOCTYPE x SYSTEM "http://evil.example/x.dtd">' + s3(""), "DOCTYPE"),
        # entries without their text, and a flag that is not a boolean
        (s3("<Contents><Size>1</Size></Contents>"), "Key"),
        (s3("<Contents><Key></Key></Contents>"), "Key"),
        (s3("<CommonPrefixes/>"), "Prefix"),
        (s3("<CommonPrefixes><Prefix></Prefix></CommonPrefixes>"), "Prefix"),
        (s3("<IsTruncated>maybe</IsTruncated>"), "IsTruncated"),
    ],
)
def test_parse_listing_refuses_what_is_not_a_listing(xml, message):
    with pytest.raises(ValueError, match=message):
        parse_listing(xml)


def test_parse_listing_refuses_a_page_over_four_mebibytes():
    limit = 4 * 1024 * 1024
    assert limit == archives.MAX_LISTING_BYTES
    padding = b"<Name>" + b"x" * limit + b"</Name>"
    over = listing_xml().replace(b"<Name>data.binance.vision</Name>", padding)
    assert len(over) > limit

    with pytest.raises(ValueError, match="size limit"):
        parse_listing(over)


@pytest.mark.parametrize("not_bytes", ["<ListBucketResult/>", None, bytearray(b"<a/>"), 7])
def test_parse_listing_wants_bytes(not_bytes):
    with pytest.raises(ValueError, match="bytes"):
        parse_listing(not_bytes)


# --- list_all -----------------------------------------------------------------------------


def test_listing_follows_next_marker_until_not_truncated():
    first, second, third = (f"{KLINES}{s}/" for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT"))
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[first], truncated=True, next_marker=first),
            url_of(KLINES, first): listing_xml(
                prefixes=[second], truncated=True, next_marker=second
            ),
            url_of(KLINES, second): listing_xml(prefixes=[third], truncated=False),
        }
    )

    page = list_all(bucket, KLINES)

    assert page == ListingPage(prefixes=(first, second, third), keys=(), next_marker=None)
    assert bucket.requests == [url_of(KLINES), url_of(KLINES, first), url_of(KLINES, second)]


def test_listing_merges_keys_across_pages_in_order():
    prefix = "data/futures/um/monthly/fundingRate/BTCUSDT/"
    keys = month_keys("funding", "BTCUSDT", "2020-01", "2020-02", "2020-03")
    bucket = FakeBucket(
        {
            url_of(prefix): listing_xml(keys=keys[:2], truncated=True, next_marker=keys[1]),
            url_of(prefix, keys[1]): listing_xml(keys=keys[2:]),
        }
    )

    assert list_all(bucket, prefix).keys == tuple(keys)


def test_listing_continues_after_the_last_entry_when_the_page_names_no_marker():
    # S3's V1 listing: a truncated page that names no NextMarker is continued after its last key.
    prefix = "data/spot/monthly/klines/BTCUSDT/1d/"
    keys = month_keys("spot_1d", "BTCUSDT", "2020-01", "2020-02")
    bucket = FakeBucket(
        {
            url_of(prefix): listing_xml(keys=keys[:1], truncated=True),
            url_of(prefix, keys[0]): listing_xml(keys=keys[1:]),
        }
    )

    assert list_all(bucket, prefix).keys == tuple(keys)
    assert bucket.requests == [url_of(prefix), url_of(prefix, keys[0])]


def test_listing_refuses_a_marker_that_does_not_advance():
    marker = f"{KLINES}BTCUSDT/"
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[marker], truncated=True, next_marker=marker),
            # the same marker again, and then an earlier one
            url_of(KLINES, marker): listing_xml(
                prefixes=[marker], truncated=True, next_marker=marker
            ),
        }
    )

    with pytest.raises(ValueError, match="advance"):
        list_all(bucket, KLINES)
    assert bucket.requests == [url_of(KLINES), url_of(KLINES, marker)]

    earlier = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[marker], truncated=True, next_marker=marker),
            url_of(KLINES, marker): listing_xml(truncated=True, next_marker=f"{KLINES}AAAUSDT/"),
        }
    )
    with pytest.raises(ValueError, match="advance"):
        list_all(earlier, KLINES)


def test_listing_of_a_prefix_the_bucket_does_not_answer_is_an_error():
    bucket = FakeBucket()

    with pytest.raises(ValueError, match="404"):
        list_all(bucket, KLINES)
    assert bucket.requests == [url_of(KLINES)]


def test_listing_refuses_a_page_that_is_not_a_listing():
    bucket = FakeBucket({url_of(KLINES): b"<html>Service Unavailable</html>"})

    with pytest.raises(ValueError, match="S3"):
        list_all(bucket, KLINES)


def test_listing_the_result_is_one_merged_page_with_no_marker():
    bucket = klines_bucket("BTCUSDT")

    page = list_all(bucket, KLINES)

    assert page.next_marker is None


# --- the listing query --------------------------------------------------------------------


def test_listing_query_is_bucket_and_prefix_only():
    marker = f"{KLINES}BTCUSDT/"
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[marker], truncated=True, next_marker=marker),
            url_of(KLINES, marker): listing_xml(prefixes=[f"{KLINES}ETHUSDT/"]),
        }
    )

    list_all(bucket, KLINES)

    assert bucket.requests == [
        "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
        "?delimiter=/&prefix=data/spot/monthly/klines/",
        "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
        "?delimiter=/&prefix=data/spot/monthly/klines/&marker=data/spot/monthly/klines/BTCUSDT/",
    ]
    assert listing.LISTING_URL == LISTING


def test_every_listing_url_passes_the_transports_allowlist(network_blocked, config):
    """HttpTransport refuses a URL outside its allowlist before opening a socket; an allowed
    one gets as far as the (blocked) connection, which fails as a transport failure."""
    marker = f"{KLINES}BTCUSDT/"
    sent: list[str] = []
    discovery = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[marker], truncated=True, next_marker=marker),
            url_of(KLINES, marker): listing_xml(prefixes=[f"{KLINES}ETHUSDT/"]),
        }
    )
    list_all(discovery, KLINES)
    sent += discovery.requests
    for kind in KINDS:
        bucket, prefix = months_bucket(kind, "BTCUSDT", [])
        discover_months(bucket, kind, "BTCUSDT", config)
        sent += bucket.requests
        assert bucket.requests == [url_of(prefix)]

    assert len(sent) == 6
    for url in sent:
        with pytest.raises(ValueError, match="transport failed") as caught:
            HttpTransport().get(url)
        assert isinstance(caught.value.__cause__, OSError)  # the blocked socket, not a refusal
    assert len(network_blocked) == len(sent)


def test_a_marker_is_percent_encoded_into_the_query(network_blocked):
    # A marker is whatever the server says; one with a query character in it must stay one value.
    odd = f"{KLINES}A&B=C+D E/"
    encoded = f"{KLINES}A%26B%3DC%2BD%20E/"
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[odd], truncated=True, next_marker=odd),
            url_of(KLINES, encoded): listing_xml(prefixes=[f"{KLINES}ZZZUSDT/"]),
        }
    )

    page = list_all(bucket, KLINES)

    assert page.prefixes == (odd, f"{KLINES}ZZZUSDT/")
    assert bucket.requests == [url_of(KLINES), url_of(KLINES, encoded)]
    for url in bucket.requests:  # both are allowlisted: they get as far as the blocked socket
        with pytest.raises(ValueError, match="transport failed"):
            HttpTransport().get(url)


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "other/",
        "Data/",
        "data",
        7,
        None,
        "data/../secret/",
        "data/a/..",
        "data/&marker=data/x",  # a second query parameter
        "data/a b/",
        "data/a%2Fb/",
        "data/a?b",
        "data/a#b",
        "data/a\n",
    ],
)
def test_listing_refuses_a_prefix_outside_the_data_tree_before_any_request(prefix):
    bucket = FakeBucket()

    with pytest.raises(ValueError, match="prefix"):
        list_all(bucket, prefix)

    assert bucket.requests == []


# --- discover_spot_usdt_symbols -----------------------------------------------------------


def test_spot_usdt_symbols_come_from_the_klines_prefixes():
    # LUNAUSDT was delisted but its archives remain; BTCUPUSDT is a leveraged token and is kept
    # here (exclusions are the universe step's job); BTCBUSD is not USDT-quoted and USDTBRL
    # has USDT as its base.
    bucket = klines_bucket(
        "LUNAUSDT", "BTCUSDT", "BTCUPUSDT", "BTCBUSD", "USDTBRL", "ETHBTC", "USDCUSDT"
    )

    symbols = discover_spot_usdt_symbols(bucket)

    assert symbols == ("BTCUPUSDT", "BTCUSDT", "LUNAUSDT", "USDCUSDT")
    assert bucket.requests == [url_of(KLINES)]
    for symbol in symbols:
        archive_path("spot_1d", symbol, "2020-01")  # each is usable for a later request


def test_spot_usdt_symbols_need_a_base_and_a_clean_name():
    bucket = klines_bucket(
        "USDT",  # no base
        "AUSDT",
        "1000SHIBUSDT",
        "btcusdt",  # not a symbol the archive paths accept
        "BTC-USDT",
        "X" * 40 + "USDT",
        "BTCUSDT.OLD",
    )

    assert discover_spot_usdt_symbols(bucket) == ("1000SHIBUSDT", "AUSDT")


def test_spot_usdt_symbols_are_sorted_unique_and_span_pages():
    first, second = f"{KLINES}ZZZUSDT/", f"{KLINES}AAAUSDT/"
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(prefixes=[first], truncated=True, next_marker=first),
            url_of(KLINES, first): listing_xml(prefixes=[second, first]),
        }
    )

    assert discover_spot_usdt_symbols(bucket) == ("AAAUSDT", "ZZZUSDT")


def test_spot_usdt_symbols_ignore_entries_outside_the_klines_prefix_and_keys():
    bucket = FakeBucket(
        {
            url_of(KLINES): listing_xml(
                prefixes=[
                    f"{KLINES}BTCUSDT/",
                    "data/spot/monthly/klines/BTCUSDT/1d/",  # deeper than one level
                    "data/spot/daily/klines/ETHUSDT/",
                    "data/futures/um/monthly/klines/SOLUSDT/",
                ],
                keys=[f"{KLINES}XRPUSDT/readme"],
            )
        }
    )

    assert discover_spot_usdt_symbols(bucket) == ("BTCUSDT",)


def test_spot_usdt_symbols_of_an_empty_listing_is_empty():
    assert discover_spot_usdt_symbols(FakeBucket({url_of(KLINES): listing_xml()})) == ()


def test_the_symbols_prefix_is_the_prefix_of_the_spot_archive_paths():
    for kind in ("spot_1d", "spot_1h"):
        assert archive_path(kind, "BTCUSDT", "2020-01").startswith("/" + KLINES)


# --- discover_months ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "prefix", "name"),
    [
        ("spot_1d", "data/spot/monthly/klines/BTCUSDT/1d/", "BTCUSDT-1d-{month}.zip"),
        ("spot_1h", "data/spot/monthly/klines/BTCUSDT/1h/", "BTCUSDT-1h-{month}.zip"),
        ("futures_1h", "data/futures/um/monthly/klines/BTCUSDT/1h/", "BTCUSDT-1h-{month}.zip"),
        (
            "funding",
            "data/futures/um/monthly/fundingRate/BTCUSDT/",
            "BTCUSDT-fundingRate-{month}.zip",
        ),
    ],
)
def test_months_are_listed_under_each_kinds_prefix(kind, prefix, name, config):
    keys = [prefix + name.format(month=month) for month in ("2020-03", "2020-01", "2020-02")]
    bucket = FakeBucket({url_of(prefix): listing_xml(keys=keys, requested=prefix)})

    months = discover_months(bucket, kind, "BTCUSDT", config)

    assert months == ("2020-01", "2020-02", "2020-03")
    assert bucket.requests == [url_of(prefix)]
    assert keys == month_keys(kind, "BTCUSDT", "2020-03", "2020-01", "2020-02")


def test_months_come_from_zip_keys_and_stop_at_end_month(config):
    keys = [
        *month_keys("spot_1d", "BTCUSDT", "2026-08", "2026-09", "2026-10", "2027-01"),
        # a checksum is not an archive, whatever month it names
        *(key + ".CHECKSUM" for key in month_keys("spot_1d", "BTCUSDT", "2026-07", "2026-10")),
    ]
    bucket, _ = months_bucket("spot_1d", "BTCUSDT", keys)

    months = discover_months(bucket, "spot_1d", "BTCUSDT", config)

    assert months == ("2026-08", "2026-09")  # 2026-10 and 2027-01 are after end_month 2026-09


def test_the_end_month_is_included_and_a_later_key_is_left_out_not_refused(config):
    keys = month_keys("funding", "BTCUSDT", "2026-09", "2026-10")
    bucket, _ = months_bucket("funding", "BTCUSDT", keys)

    assert discover_months(bucket, "funding", "BTCUSDT", config) == ("2026-09",)

    earlier = replace(config, end_month="2026-08")
    bucket, _ = months_bucket("funding", "BTCUSDT", keys)
    assert discover_months(bucket, "funding", "BTCUSDT", earlier) == ()


def test_months_ignore_keys_that_are_not_this_symbols_kind_archives(config):
    prefix = "data/spot/monthly/klines/BTCUSDT/1h/"
    keys = [
        *month_keys("spot_1h", "BTCUSDT", "2020-05"),
        prefix + "ETHUSDT-1h-2020-06.zip",  # another symbol
        prefix + "BTCUSDT-1d-2020-07.zip",  # another interval
        prefix + "BTCUSDT-1h-2020-13.zip",  # not a month
        prefix + "BTCUSDT-1h-2020-00.zip",
        prefix + "BTCUSDT-1h-2020-1.zip",
        prefix + "BTCUSDT-1h-20-01.zip",
        prefix + "BTCUSDT-1h-2020-08-01.zip",  # a daily archive
        prefix + "BTCUSDT-1h-2020-09.csv",
        prefix + "BTCUSDT-1h-2020-09.zip.CHECKSUM",
        prefix + "BTCUSDT-1h-2020-10.zip.bak",
        prefix + "xBTCUSDT-1h-2020-11.zip",
        prefix + "btcusdt-1h-2020-12.zip",
        prefix + "BTCUSDT-fundingRate-2020-02.zip",
        "data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1h-2020-03.zip",  # another directory
        "BTCUSDT-1h-2020-04.zip",
        prefix,  # the directory itself
    ]
    bucket, _ = months_bucket("spot_1h", "BTCUSDT", keys)

    assert discover_months(bucket, "spot_1h", "BTCUSDT", config) == ("2020-05",)


def test_months_for_a_funding_listing_need_the_funding_name(config):
    prefix = "data/futures/um/monthly/fundingRate/BTCUSDT/"
    keys = [
        prefix + "BTCUSDT-fundingRate-2020-01.zip",
        prefix + "BTCUSDT-1h-2020-02.zip",
        prefix + "BTCUSDT-fundingrate-2020-03.zip",
    ]
    bucket, _ = months_bucket("funding", "BTCUSDT", keys)

    assert discover_months(bucket, "funding", "BTCUSDT", config) == ("2020-01",)


def test_months_are_sorted_unique_and_span_pages(config):
    prefix = "data/futures/um/monthly/klines/BTCUSDT/1h/"
    keys = month_keys("futures_1h", "BTCUSDT", "2021-02", "2020-12", "2021-01", "2020-12")
    bucket = FakeBucket(
        {
            url_of(prefix): listing_xml(keys=keys[:2], truncated=True, next_marker=keys[1]),
            url_of(prefix, keys[1]): listing_xml(keys=keys[2:]),
        }
    )

    assert discover_months(bucket, "futures_1h", "BTCUSDT", config) == (
        "2020-12",
        "2021-01",
        "2021-02",
    )


def test_months_of_a_symbol_with_no_archives_is_empty(config):
    for kind in KINDS:
        bucket, _ = months_bucket(kind, "NEWUSDT", [])
        assert discover_months(bucket, kind, "NEWUSDT", config) == ()


@pytest.mark.parametrize(
    ("kind", "symbol"),
    [
        ("spot_1m", "BTCUSDT"),
        ("", "BTCUSDT"),
        (None, "BTCUSDT"),
        ("spot_1h", "btcusdt"),
        ("spot_1h", "BTC/../USDT"),
        ("spot_1h", ""),
        ("spot_1h", "B"),
        ("spot_1h", None),
    ],
)
def test_months_refuse_an_unknown_kind_or_a_bad_symbol_before_any_request(kind, symbol, config):
    bucket = FakeBucket()

    with pytest.raises(ValueError):
        discover_months(bucket, kind, symbol, config)

    assert bucket.requests == []


@pytest.mark.parametrize("end_month", ["2026-13", "2026-9", "", "later", "2026-09-30"])
def test_months_refuse_a_malformed_end_month_instead_of_dropping_every_key(end_month, config):
    keys = month_keys("spot_1d", "BTCUSDT", "2020-01")
    bucket, _ = months_bucket("spot_1d", "BTCUSDT", keys)

    with pytest.raises(ValueError, match="end_month"):
        discover_months(bucket, "spot_1d", "BTCUSDT", replace(config, end_month=end_month))


def test_discovery_opens_no_connection_of_its_own(network_blocked, config):
    bucket, _ = months_bucket("spot_1d", "BTCUSDT", month_keys("spot_1d", "BTCUSDT", "2020-01"))

    discover_months(bucket, "spot_1d", "BTCUSDT", config)
    discover_spot_usdt_symbols(klines_bucket("BTCUSDT"))

    assert network_blocked == []
