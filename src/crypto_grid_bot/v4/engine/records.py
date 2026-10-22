"""The hash-chained records of one cell and the cell's receipt.

Implements the spec's "Records" (what is recorded) and its "Integrity" line: all records are
hash-chained in V3.1's ``combined-v1`` style under the schema name ``v4-cell-1``, and each cell's
bundle carries a receipt. The module knows records, not prices or the engine's rules.

* **One chain, one line per record.** A line of ``records.jsonl`` is the canonical JSON of
  ``{"kind", "record", "schema", "previous_hash", "hash"}`` (sorted keys, no spaces, ASCII) and a
  newline. ``hash`` is the SHA-256 of the canonical JSON of the other four keys, and the first
  line's ``previous_hash`` is the seed, 64 zeros. Every kind goes into the same chain, so
  reordering, dropping or inserting a line breaks a link. V3.1's ``_canonical`` and ``_digest`` do
  the serialising and hashing, so the two packs share one definition of both.
* **Exact values.** A record is a mapping with string keys whose values are strings, integers,
  booleans, null, lists, tuples (written as lists), nested mappings and Decimals. A Decimal is
  written as ``str(value)``, as it is, with no normalisation: the engine is deterministic, so the
  strings are reproducible, and readers compare values numerically. Floats, non-finite Decimals
  and everything else V3.1's canonical form refuses are a ``ValueError`` naming the path to the
  value, and a refused record writes nothing and does not move the chain. The reader refuses floats
  and duplicate keys in the file the same way.
* **The receipt** binds a records file: its SHA-256, the record count, how many records each kind
  has and the final chain hash. ``write_receipt`` stores it as canonical JSON and returns the
  SHA-256 of that file (the summary's ``receipt_sha256``); ``read_receipt`` refuses anything that
  is not exactly such a file.
* **Streaming.** A real cell writes about 70,000 hourly records and the daily, fill and event
  records besides: about 135 MB for a V4 cell and about 45 MB for a hold cell over the real
  window, and about 3.6 GB for all the engine's 32 cells (measured in the final review). The
  writer holds one record and a running SHA-256; the reader holds one line.

``read_records`` checks the file's SHA-256 against the receipt before it returns, then checks each
line's schema, link and hash as the lines are yielded, and the receipt's counts and final chain
hash when the iterator reaches the end. Consume it to the end before trusting what it read.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import BinaryIO, Self, cast

from crypto_grid_bot.combined.artifacts import _canonical, _digest

RECORD_SCHEMA = "v4-cell-1"
RECEIPT_SCHEMA = "v4-receipt-1"
SEED = "0" * 64

KINDS: tuple[str, ...] = (
    "daily_coin",
    "fill",
    "funding",
    "lifecycle",
    "monthly",
    "hourly",
    "event",
    "outcome",
)

_KNOWN_KINDS = frozenset(KINDS)
_LINE_KEYS = frozenset({"kind", "record", "schema", "previous_hash", "hash"})
_RECEIPT_KEYS = frozenset({"schema", "records_sha256", "record_count", "final_chain_hash", "kinds"})
_HEX64 = re.compile("[0-9a-f]{64}")
_WRITE_BUFFER = 1 << 20
_MAX_DEPTH = 40
_MAX_RECEIPT_BYTES = 1 << 16


def _require_hash(name: str, value: object) -> None:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 lowercase hex digits, got {value!r}")


@dataclass(frozen=True, slots=True)
class Receipt:
    """What a records file must be: its SHA-256, record count, count per kind and final hash.

    ``kinds`` lists the kinds that occur, each with a positive count, in name order, and the
    counts add up to ``record_count``. A file with no records has the seed as its final hash.
    """

    records_sha256: str
    record_count: int
    final_chain_hash: str
    kinds: Mapping[str, int]

    def __post_init__(self) -> None:
        _require_hash("records_sha256", self.records_sha256)
        _require_hash("final_chain_hash", self.final_chain_hash)
        if type(self.record_count) is not int or self.record_count < 0:
            raise ValueError(
                f"record_count must be a non-negative integer, got {self.record_count!r}"
            )
        if not isinstance(self.kinds, Mapping):
            raise ValueError(f"kinds must be a mapping of kind to count, got {self.kinds!r}")
        counts: dict[str, int] = {}
        for kind, count in self.kinds.items():
            if kind not in _KNOWN_KINDS:
                raise ValueError(f"unknown kind {kind!r} in kinds")
            if type(count) is not int or count < 1:
                raise ValueError(f"the count of kind {kind!r} must be a positive integer")
            counts[kind] = count
        if sum(counts.values()) != self.record_count:
            raise ValueError(
                f"record_count {self.record_count} and the kind counts do not add up "
                f"({sum(counts.values())})"
            )
        if self.record_count == 0 and self.final_chain_hash != SEED:
            raise ValueError("the final_chain_hash of an empty file must be the seed")
        object.__setattr__(self, "kinds", MappingProxyType(dict(sorted(counts.items()))))

    def __hash__(self) -> int:
        return hash(
            (
                self.records_sha256,
                self.record_count,
                self.final_chain_hash,
                tuple(self.kinds.items()),
            )
        )


class _BadValue(Exception):
    """A value that is not exact JSON; the frames it unwinds through add the path to it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.trail: list[str] = []


def _plain(value: object, depth: int) -> object:
    """The exact-JSON form of ``value``: Decimals as strings, tuples as lists, mappings as dicts."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is Decimal:
        if not value.is_finite():
            raise _BadValue(f"a Decimal that is not finite ({value}) is refused")
        return str(value)
    if type(value) is float:
        raise _BadValue(f"floats are refused ({value!r}); give the exact Decimal")
    if depth >= _MAX_DEPTH:
        raise ValueError(f"record nesting is deeper than {_MAX_DEPTH} levels, or refers to itself")
    if isinstance(value, Mapping):
        plain: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _BadValue(f"a mapping needs string keys, got a {type(key).__name__} key")
            try:
                plain[key] = _plain(item, depth + 1)
            except _BadValue as bad:
                bad.trail.append(f"[{key!r}]")
                raise
        return plain
    if type(value) in (list, tuple):
        items: list[object] = []
        for index, item in enumerate(cast("list[object] | tuple[object, ...]", value)):
            try:
                items.append(_plain(item, depth + 1))
            except _BadValue as bad:
                bad.trail.append(f"[{index}]")
                raise
        return items
    raise _BadValue(f"a {type(value).__name__} is not an exact JSON value")


def _plain_record(record: object) -> dict[str, object]:
    if not isinstance(record, Mapping):
        raise ValueError(
            f"a record must be a mapping with string keys, got {type(record).__name__}"
        )
    try:
        return cast("dict[str, object]", _plain(record, 0))
    except _BadValue as bad:
        raise ValueError(f"record{''.join(reversed(bad.trail))}: {bad.reason}") from None


class RecordWriter:
    """Creates ``records.jsonl`` exclusively and appends hash-chained records to it.

    ``append`` returns the record's hash and ``close`` returns the ``Receipt``. A closed writer
    accepts nothing, and closing twice is an error. Used as a context manager, it releases the
    file when the block fails; a writer abandoned that way has no receipt and is spent.
    """

    def __init__(self, path: Path) -> None:
        # "x" refuses an existing file; a records file is never extended or replaced.
        self._file: BinaryIO | None = open(  # noqa: SIM115
            path, "xb", buffering=_WRITE_BUFFER
        )
        self._sha = hashlib.sha256()
        self._chain = SEED
        self._count = 0
        self._counts: Counter[str] = Counter()

    def _open_file(self) -> BinaryIO:
        if self._file is None:
            raise ValueError("the record writer is closed")
        return self._file

    def append(self, kind: str, record: Mapping[str, object]) -> str:
        handle = self._open_file()
        if type(kind) is not str or kind not in _KNOWN_KINDS:
            raise ValueError(f"unknown kind {kind!r}; the kinds are {', '.join(KINDS)}")
        payload: dict[str, object] = {
            "kind": kind,
            "record": _plain_record(record),
            "schema": RECORD_SCHEMA,
            "previous_hash": self._chain,
        }
        digest = _digest(_canonical(payload))
        line = _canonical({**payload, "hash": digest}) + b"\n"
        try:
            handle.write(line)
        except BaseException:
            # A partial line may be on disk, so the file no longer matches the running hash.
            self._abandon()
            raise
        self._sha.update(line)
        self._chain = digest
        self._count += 1
        self._counts[kind] += 1
        return digest

    def close(self) -> Receipt:
        handle = self._open_file()
        self._file = None
        handle.close()
        return Receipt(self._sha.hexdigest(), self._count, self._chain, dict(self._counts))

    def _abandon(self) -> None:
        handle, self._file = self._file, None
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._abandon()


def _refuse_float(text: str) -> object:
    raise ValueError(f"floats are refused (found {text})")


def _refuse_constant(text: str) -> object:
    raise ValueError(f"{text} is refused: NaN and the infinities are not exact JSON")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _loads(raw: bytes) -> object:
    """Strict JSON: UTF-8, no duplicate keys, no floats, no NaN or infinities."""
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid JSON: not UTF-8 ({exc})") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None


def _check_line(raw: bytes, previous: str) -> tuple[str, dict[str, object], str]:
    """Parse and verify one line (without its newline): ``(kind, record, hash)``."""
    row = _loads(raw)
    if not isinstance(row, dict):
        raise ValueError("a line must be a JSON object")
    if set(row) != _LINE_KEYS:
        raise ValueError(f"line keys must be exactly {sorted(_LINE_KEYS)}, got {sorted(row)}")
    if row["schema"] != RECORD_SCHEMA:
        raise ValueError(f"schema must be {RECORD_SCHEMA!r}, got {row['schema']!r}")
    kind = row["kind"]
    if type(kind) is not str or kind not in _KNOWN_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    record = row["record"]
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    if row["previous_hash"] != previous:
        raise ValueError("previous_hash does not link to the previous record")
    digest = row["hash"]
    if type(digest) is not str or _HEX64.fullmatch(digest) is None:
        raise ValueError(f"hash is not 64 lowercase hex digits, got {digest!r}")
    payload = {"kind": kind, "record": record, "schema": RECORD_SCHEMA, "previous_hash": previous}
    if _digest(_canonical(payload)) != digest:
        raise ValueError("hash does not match the record")
    return kind, record, digest


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _verified_lines(path: Path, receipt: Receipt) -> Iterator[tuple[str, dict[str, object]]]:
    sha = hashlib.sha256()
    previous = SEED
    counts: Counter[str] = Counter()
    number = 0
    with path.open("rb") as handle:
        for number, line in enumerate(handle, start=1):
            sha.update(line)
            if not line.endswith(b"\n"):
                raise ValueError(f"line {number}: incomplete final line (no newline)")
            try:
                kind, record, previous = _check_line(line[:-1], previous)
            except ValueError as exc:
                raise ValueError(f"line {number}: {exc}") from None
            counts[kind] += 1
            yield kind, record
    if number != receipt.record_count:
        raise ValueError(
            f"record count {number} does not match the receipt's {receipt.record_count}"
        )
    if dict(sorted(counts.items())) != dict(receipt.kinds):
        raise ValueError(
            f"kind counts {dict(sorted(counts.items()))} do not match the receipt's "
            f"{dict(receipt.kinds)}"
        )
    if previous != receipt.final_chain_hash:
        raise ValueError("the final chain hash does not match the receipt")
    if sha.hexdigest() != receipt.records_sha256:
        raise ValueError("the records file changed while it was read (SHA-256 differs)")


def read_records(path: Path, receipt: Receipt) -> Iterator[tuple[str, dict[str, object]]]:
    """Verify a records file against its receipt and yield its ``(kind, record)`` pairs in order.

    Before this returns, the whole file's SHA-256 is compared with ``receipt.records_sha256`` (one
    streaming read that only hashes), so a file changed in any way is refused before a record is
    yielded. Then, as the lines are yielded, each one is parsed strictly (no duplicate keys, no
    floats) and checked for its exact keys, the schema, a known kind, its link to the previous
    line (the first links to the seed) and its hash. When the iterator reaches the end, the record
    count, the count of each kind, the final chain hash and the SHA-256 of the bytes just read are
    checked against the receipt. Every refusal is a ``ValueError``; those on a line name it.

    A consumer must exhaust the iterator before trusting what it read: the receipt's count and
    final-hash checks run only at the end, so one that stops early has seen a verified prefix of a
    file whose bytes matched the receipt, and no more than that. The cost of the early check is a
    second read of the file, about a second per 100 MB.
    """
    if _file_sha256(path) != receipt.records_sha256:
        raise ValueError("the records file's SHA-256 does not match the receipt")
    return _verified_lines(path, receipt)


def _receipt_bytes(receipt: Receipt) -> bytes:
    return _canonical(
        {
            "schema": RECEIPT_SCHEMA,
            "records_sha256": receipt.records_sha256,
            "record_count": receipt.record_count,
            "final_chain_hash": receipt.final_chain_hash,
            "kinds": dict(receipt.kinds),
        }
    )


def write_receipt(path: Path, receipt: Receipt) -> str:
    """Create ``path`` exclusively as the receipt's canonical JSON; return that file's SHA-256."""
    raw = _receipt_bytes(receipt)
    with path.open("xb") as handle:
        handle.write(raw)
    return _digest(raw)


def read_receipt(path: Path) -> Receipt:
    """Read a receipt file, refusing anything that is not exactly what ``write_receipt`` writes.

    That is: the schema ``v4-receipt-1``, exactly the five keys, valid hashes, known kinds with
    positive counts that add up to the record count, no duplicate keys or floats, and the file's
    bytes equal to the canonical JSON of what they say (so a receipt has one spelling and one
    SHA-256).
    """
    try:
        size = path.stat().st_size
        if size > _MAX_RECEIPT_BYTES:
            raise ValueError(f"receipt file is too large ({size} bytes)")
        raw = path.read_bytes()
        data = _loads(raw)
        if not isinstance(data, dict):
            raise ValueError("a receipt must be a JSON object")
        if set(data) != _RECEIPT_KEYS:
            raise ValueError(
                f"receipt keys must be exactly {sorted(_RECEIPT_KEYS)}, got {sorted(data)}"
            )
        if data["schema"] != RECEIPT_SCHEMA:
            raise ValueError(f"receipt schema must be {RECEIPT_SCHEMA!r}, got {data['schema']!r}")
        receipt = Receipt(
            data["records_sha256"], data["record_count"], data["final_chain_hash"], data["kinds"]
        )
        if _receipt_bytes(receipt) != raw:
            raise ValueError("the receipt file is not in canonical form")
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from None
    return receipt
