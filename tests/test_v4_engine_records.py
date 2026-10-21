"""V4 engine task 11: the hash-chained records of one cell and its receipt (spec "Records").

Every line of ``records.jsonl`` is ``{"kind", "record", "schema", "previous_hash", "hash"}`` and the
hash covers the other four, V3.1's ``combined-v1`` chain with the schema name ``v4-cell-1``. The
receipt binds the file: its SHA-256, the record count, the count of each kind and the final chain
hash. The expected hashes below are worked with ``hashlib`` and ``json`` directly, not through the
module's helpers, so the chain rule is checked against an independent reading of it.

Tampering tests come in pairs. With the original receipt the file's SHA-256 already disagrees. With
a receipt refitted to the tampered bytes (only ``records_sha256`` replaced) the file's own chain,
count or kinds must still catch it, so each check holds without the SHA-256 doing the work for it.
Files live under pytest's ``tmp_path``. No network and no market data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from crypto_grid_bot.v4.engine.records import (
    KINDS,
    RECEIPT_SCHEMA,
    RECORD_SCHEMA,
    SEED,
    Receipt,
    RecordWriter,
    read_receipt,
    read_records,
    write_receipt,
)

# One record of every kind, with the value shapes the engine writes: Decimals as they are, nested
# lists and mappings, integers, booleans, null and non-ASCII text.
SAMPLE: list[tuple[str, dict[str, object]]] = [
    ("monthly", {"month": "2022-03", "universe": ["BTC", "ETH"], "validated": True}),
    (
        "daily_coin",
        {
            "day": "2022-03-02",
            "symbol": "BTC",
            "speeds": [{"speed": 3, "value": Decimal("0.125"), "vote": 1}],
            "sigma": Decimal("0.0200"),
            "order": None,
        },
    ),
    ("hourly", {"hour": 1646179200000, "equity": Decimal("1000.5"), "complete": True}),
    ("fill", {"symbol": "BTC", "qty": Decimal("0.01"), "price": Decimal("43000.1")}),
    ("funding", {"symbol": "BTC", "rate": Decimal("1E-4"), "paid": Decimal("-0.043")}),
    ("lifecycle", {"symbol": "BTC", "side": "long", "exit_reason": "signal", "hold_hours": 72}),
    ("event", {"what": "deferral", "note": "prüfung €"}),
    ("outcome", {"outcome": "complete", "final_equity": Decimal("1234.56")}),
]


def independent_hash(kind: str, record: object, previous: str, schema: str = RECORD_SCHEMA) -> str:
    """The chain rule written out with hashlib and json, not with the module's own helpers."""
    payload = {"kind": kind, "record": record, "schema": schema, "previous_hash": previous}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def plain(value: object) -> object:
    """The JSON reading of a sample value: Decimals become their strings."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def forged_line(
    kind: str,
    record: object,
    previous: str,
    *,
    schema: str = RECORD_SCHEMA,
    extra: dict[str, object] | None = None,
) -> bytes:
    """A line whose hash is right for its content, however wrong the content is otherwise."""
    row: dict[str, object] = {
        "kind": kind,
        "record": record,
        "schema": schema,
        "previous_hash": previous,
        "hash": independent_hash(kind, record, previous, schema),
    }
    row.update(extra or {})
    return json.dumps(row, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def write_sample(
    directory: Path, samples: list[tuple[str, dict[str, object]]] | None = None
) -> tuple[Path, Receipt, list[str]]:
    path = directory / "records.jsonl"
    writer = RecordWriter(path)
    hashes = [
        writer.append(kind, record) for kind, record in (SAMPLE if samples is None else samples)
    ]
    return path, writer.close(), hashes


def fitted(receipt: Receipt, raw: bytes) -> Receipt:
    """The receipt with only its file hash replaced, so the other checks must stand alone."""
    return replace(receipt, records_sha256=hashlib.sha256(raw).hexdigest())


def drain(path: Path, receipt: Receipt) -> list[tuple[str, dict[str, object]]]:
    return list(read_records(path, receipt))


def rewrite(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)


# --- the chain and the receipt ---------------------------------------------------------------


def test_every_record_is_chained_and_the_receipt_binds_the_file(tmp_path: Path) -> None:
    path, receipt, hashes = write_sample(tmp_path)
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    assert lines.pop() == b""  # every line, the last included, ends in a newline
    assert len(lines) == len(SAMPLE) == len(hashes)

    previous = "0" * 64
    for (kind, record), line, returned in zip(SAMPLE, lines, hashes, strict=True):
        row = json.loads(line)
        assert set(row) == {"kind", "record", "schema", "previous_hash", "hash"}
        assert row["kind"] == kind
        assert row["record"] == plain(record)
        assert row["schema"] == "v4-cell-1" == RECORD_SCHEMA
        assert row["previous_hash"] == previous
        assert row["hash"] == independent_hash(kind, row["record"], previous)
        assert returned == row["hash"]  # append returns the record's hash
        # The line itself is the canonical form: sorted keys, no spaces, ASCII only.
        assert line == json.dumps(row, sort_keys=True, separators=(",", ":")).encode("ascii")
        previous = row["hash"]

    assert SEED == "0" * 64
    assert receipt.records_sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.record_count == len(SAMPLE)
    assert receipt.final_chain_hash == hashes[-1]
    assert dict(receipt.kinds) == {kind: 1 for kind in KINDS}
    assert set(KINDS) == {
        "daily_coin",
        "fill",
        "funding",
        "lifecycle",
        "monthly",
        "hourly",
        "event",
        "outcome",
    }

    # The reader yields every record again, in order, with Decimals as the strings written.
    assert drain(path, receipt) == [(kind, plain(record)) for kind, record in SAMPLE]


def test_decimals_are_written_as_they_are_and_tuples_become_lists(tmp_path: Path) -> None:
    record: dict[str, object] = {
        "a": Decimal("1.50"),
        "b": Decimal("1E+2"),
        "c": Decimal("-0"),
        "d": (1, (Decimal("2"), "x")),
        "e": {"z": [True, None, 7], "y": ""},
    }
    path, receipt, _ = write_sample(tmp_path, [("event", record)])
    row = json.loads(path.read_text(encoding="ascii"))
    assert row["record"] == {
        "a": "1.50",
        "b": "1E+2",
        "c": "-0",
        "d": [1, ["2", "x"]],
        "e": {"z": [True, None, 7], "y": ""},
    }
    assert drain(path, receipt) == [("event", row["record"])]


def test_the_same_records_always_give_the_same_bytes_and_receipt(tmp_path: Path) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    first = write_sample(tmp_path / "one")
    second = write_sample(tmp_path / "two")
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1] == second[1]
    assert first[2] == second[2]


def test_an_empty_file_has_the_seed_as_its_final_hash(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path, [])
    assert path.read_bytes() == b""
    assert receipt == Receipt(hashlib.sha256(b"").hexdigest(), 0, "0" * 64, {})
    assert drain(path, receipt) == []


def test_receipt_is_immutable_comparable_and_hashable() -> None:
    receipt = Receipt("a" * 64, 3, "b" * 64, {"fill": 2, "event": 1})
    assert list(receipt.kinds) == ["event", "fill"]  # sorted, whatever order it came in
    assert receipt == Receipt("a" * 64, 3, "b" * 64, {"event": 1, "fill": 2})
    assert hash(receipt) == hash(Receipt("a" * 64, 3, "b" * 64, {"event": 1, "fill": 2}))
    with pytest.raises(TypeError):
        receipt.kinds["fill"] = 5  # type: ignore[index]
    with pytest.raises(AttributeError):
        receipt.record_count = 4  # type: ignore[misc]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("A" * 64, 1, "b" * 64, {"fill": 1}), "records_sha256"),
        (("a" * 63, 1, "b" * 64, {"fill": 1}), "records_sha256"),
        ((None, 1, "b" * 64, {"fill": 1}), "records_sha256"),
        (("a" * 64, 1, "g" * 64, {"fill": 1}), "final_chain_hash"),
        (("a" * 64, 1.0, "b" * 64, {"fill": 1}), "record_count"),
        (("a" * 64, True, "b" * 64, {"fill": 1}), "record_count"),
        (("a" * 64, -1, "b" * 64, {}), "record_count"),
        (("a" * 64, 2, "b" * 64, {"fill": 1}), "do not add up"),
        (("a" * 64, 1, "b" * 64, {"fill": 1, "event": 1}), "do not add up"),
        (("a" * 64, 1, "b" * 64, {"price": 1}), "unknown kind"),
        (("a" * 64, 0, "b" * 64, {}), "empty"),
        (("a" * 64, 1, "b" * 64, {"fill": 0, "event": 1}), "positive"),
        (("a" * 64, 1, "b" * 64, {"fill": True}), "positive"),
        (("a" * 64, 1, "b" * 64, {"fill": 1.0}), "positive"),
        (("a" * 64, 1, "b" * 64, [("fill", 1)]), "mapping"),
        (("a" * 64, 1, "b" * 64, {1: 1}), "unknown kind"),
    ],
)
def test_a_receipt_that_cannot_be_true_is_refused(args: tuple[object, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Receipt(*args)  # type: ignore[arg-type]


# --- tampering -------------------------------------------------------------------------------


def test_a_tampered_line_breaks_the_chain(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    raw = path.read_bytes()
    tampered = raw.replace(b'"qty":"0.01"', b'"qty":"0.02"')
    assert tampered != raw and len(tampered) == len(raw)
    rewrite(path, tampered)

    with pytest.raises(ValueError, match="SHA-256"):
        drain(path, receipt)
    with pytest.raises(ValueError, match=r"line 4: hash does not match"):
        drain(path, fitted(receipt, tampered))


def test_a_tampered_hash_field_is_refused_too(tmp_path: Path) -> None:
    path, receipt, hashes = write_sample(tmp_path)
    raw = path.read_bytes()
    tampered = raw.replace(hashes[2].encode(), b"f" * 64)
    assert tampered != raw
    rewrite(path, tampered)
    with pytest.raises(ValueError, match=r"line 3: hash does not match"):
        drain(path, fitted(receipt, tampered))


def test_a_reordered_pair_of_lines_breaks_the_chain(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    lines[2], lines[3] = lines[3], lines[2]
    swapped = b"".join(lines)
    rewrite(path, swapped)

    # The count, the kinds and the final hash are the same; only the links tell.
    with pytest.raises(ValueError, match="SHA-256"):
        drain(path, receipt)
    with pytest.raises(ValueError, match=r"line 3: previous_hash does not link"):
        drain(path, fitted(receipt, swapped))


def test_a_deleted_middle_line_breaks_the_chain(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    del lines[3]
    shorter = b"".join(lines)
    rewrite(path, shorter)
    with pytest.raises(ValueError, match=r"line 4: previous_hash does not link"):
        drain(path, fitted(receipt, shorter))


def test_an_appended_line_is_caught_by_the_receipt(tmp_path: Path) -> None:
    path, receipt, hashes = write_sample(tmp_path)
    # A correctly chained extra line: the chain alone cannot see it, the receipt must.
    longer = path.read_bytes() + forged_line("event", {"what": "extra"}, hashes[-1])
    rewrite(path, longer)
    with pytest.raises(ValueError, match="SHA-256"):
        drain(path, receipt)
    with pytest.raises(ValueError, match="record count"):
        drain(path, fitted(receipt, longer))

    # The count and the kinds fitted too, only the final chain hash is left to disagree.
    new_final = independent_hash("event", {"what": "extra"}, hashes[-1])
    counted = replace(
        fitted(receipt, longer),
        record_count=len(SAMPLE) + 1,
        kinds={**receipt.kinds, "event": 2},
    )
    with pytest.raises(ValueError, match="final chain hash"):
        drain(path, counted)
    assert len(drain(path, replace(counted, final_chain_hash=new_final))) == len(SAMPLE) + 1


def test_a_truncated_file_is_refused(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    raw = path.read_bytes()

    # Whole last line gone: every remaining link is good, the receipt must say what is missing.
    without_last = raw[: raw.rstrip(b"\n").rfind(b"\n") + 1]
    rewrite(path, without_last)
    with pytest.raises(ValueError, match="SHA-256"):
        drain(path, receipt)
    with pytest.raises(ValueError, match="record count"):
        drain(path, fitted(receipt, without_last))

    # Cut mid-line: no newline ends the file.
    mid_line = raw[:-30]
    assert not mid_line.endswith(b"\n")
    rewrite(path, mid_line)
    with pytest.raises(ValueError, match="incomplete final line"):
        drain(path, fitted(receipt, mid_line))

    # Cut to nothing.
    rewrite(path, b"")
    with pytest.raises(ValueError, match="SHA-256"):
        drain(path, receipt)
    with pytest.raises(ValueError, match="record count"):
        drain(path, fitted(receipt, b""))


def test_a_missing_final_newline_alone_is_refused(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    raw = path.read_bytes()[:-1]
    rewrite(path, raw)
    with pytest.raises(ValueError, match="incomplete final line"):
        drain(path, fitted(receipt, raw))


def test_a_duplicate_json_key_is_refused(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    raw = path.read_bytes()
    doubled = raw.replace(b'"sigma":"0.0200"', b'"sigma":"0.0200","sigma":"0.0200"')
    assert doubled != raw
    rewrite(path, doubled)
    with pytest.raises(ValueError, match=r"line 2: .*duplicate JSON key"):
        drain(path, fitted(receipt, doubled))

    # A repeated key of the line itself.
    doubled = raw.replace(b'"schema":"v4-cell-1"', b'"schema":"v4-cell-1","schema":"v4-cell-1"', 1)
    rewrite(path, doubled)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        drain(path, fitted(receipt, doubled))


@pytest.mark.parametrize("replacement", [b'"order":1.0', b'"order":1e2', b'"order":NaN'])
def test_a_float_in_the_file_is_refused(tmp_path: Path, replacement: bytes) -> None:
    path, receipt, _ = write_sample(tmp_path)
    raw = path.read_bytes()
    floaty = raw.replace(b'"order":null', replacement)
    assert floaty != raw
    rewrite(path, floaty)
    with pytest.raises(ValueError, match=r"line 2: .*(floats|NaN|Infinity)"):
        drain(path, fitted(receipt, floaty))


LINE_CASES: dict[str, tuple[Callable[[bytes, list[str]], bytes], str]] = {
    "unknown kind": (lambda first, hashes: forged_line("price", {"x": 1}, SEED), "unknown kind"),
    "wrong schema": (
        lambda first, hashes: forged_line("event", {"x": 1}, SEED, schema="combined-v1"),
        "schema",
    ),
    "extra key": (
        lambda first, hashes: forged_line("event", {"x": 1}, SEED, extra={"note": "hi"}),
        "keys",
    ),
    "missing key": (lambda first, hashes: first.replace(b',"schema":"v4-cell-1"', b""), "keys"),
    "record not an object": (
        lambda first, hashes: forged_line("event", [1, 2], SEED),
        "record must be an object",
    ),
    "blank line": (lambda first, hashes: b"\n", "line 1"),
    "not JSON": (lambda first, hashes: b"{not json}\n", "line 1: invalid JSON"),
    "not an object": (lambda first, hashes: b"[1]\n", "line 1: .*object"),
    "not UTF-8": (lambda first, hashes: b"\xff\xfe\n", "line 1: invalid JSON"),
    "first line not seeded": (
        lambda first, hashes: forged_line("event", {"x": 1}, hashes[0]),
        "line 1: previous_hash does not link",
    ),
    "hash not hex": (
        lambda first, hashes: first.replace(hashes[0].encode(), b"Z" * 64),
        "line 1: hash is not",
    ),
    "hash of the wrong length": (
        lambda first, hashes: first.replace(hashes[0].encode(), b"ab"),
        "line 1: hash is not",
    ),
}


@pytest.mark.parametrize("case", list(LINE_CASES))
def test_lines_that_break_the_line_format_are_refused(tmp_path: Path, case: str) -> None:
    path, receipt, hashes = write_sample(tmp_path, SAMPLE[:2])
    first, second = path.read_bytes().splitlines(keepends=True)
    build, message = LINE_CASES[case]
    raw = build(first, hashes) + second
    rewrite(path, raw)
    with pytest.raises(ValueError, match=message):
        drain(path, fitted(receipt, raw))


def test_the_file_hash_is_checked_before_any_record_is_yielded(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    rewrite(path, path.read_bytes().replace(b"deferral", b"deferrals"))
    # The refusal comes with the call: no iterator exists for a consumer to stop early on.
    with pytest.raises(ValueError, match="SHA-256"):
        read_records(path, receipt)


def test_a_consumer_that_stops_early_gets_only_verified_records(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    iterator = read_records(path, receipt)
    assert next(iterator) == ("monthly", plain(SAMPLE[0][1]))
    assert next(iterator) == ("daily_coin", plain(SAMPLE[1][1]))


def test_the_file_changing_during_the_read_is_caught_at_the_end(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    iterator = read_records(path, receipt)  # the SHA-256 is right at this point
    tampered = path.read_bytes().replace(b"deferral", b"deferrals")
    rewrite(path, tampered)  # but not by the time the lines are read
    with pytest.raises(ValueError, match=r"line 7: hash does not match"):
        list(iterator)


def test_bytes_that_change_nothing_a_line_says_are_still_caught_by_the_file_hash(
    tmp_path: Path,
) -> None:
    path, receipt, _ = write_sample(tmp_path)
    iterator = read_records(path, receipt)  # the SHA-256 is right at this point
    raw = path.read_bytes()
    spaced = raw.replace(b'{"hash":', b'{"hash" :', 1)  # same JSON, same hashes, other bytes
    assert spaced != raw
    rewrite(path, spaced)
    # Every line, the count, the kinds and the final hash check out; only the bytes differ.
    with pytest.raises(ValueError, match="changed while it was read"):
        list(iterator)
    # A fresh read refuses it up front.
    with pytest.raises(ValueError, match="SHA-256"):
        read_records(path, receipt)


def test_the_kind_counts_must_match_the_receipt(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    # Same total, wrong split: one fill is claimed to be a second event.
    kinds = {**receipt.kinds, "event": 2}
    del kinds["fill"]
    wrong = replace(receipt, kinds=kinds)
    assert wrong.record_count == sum(wrong.kinds.values())
    with pytest.raises(ValueError, match="kind counts"):
        drain(path, wrong)
    # The final chain hash is checked on its own too.
    with pytest.raises(ValueError, match="final chain hash"):
        drain(path, replace(receipt, final_chain_hash="c" * 64))


# --- the writer ------------------------------------------------------------------------------


def test_existing_records_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_bytes(b"keep me\n")
    with pytest.raises(FileExistsError):
        RecordWriter(path)
    assert path.read_bytes() == b"keep me\n"

    # A finished writer's file is protected the same way.
    (tmp_path / "sub").mkdir()
    other, _, _ = write_sample(tmp_path / "sub")
    before = other.read_bytes()
    with pytest.raises(FileExistsError):
        RecordWriter(other)
    assert other.read_bytes() == before


def test_floats_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    writer = RecordWriter(path)
    first = writer.append("event", {"what": "first"})

    bad_values: list[tuple[dict[str, object], str]] = [
        ({"price": 1.5}, r"record\['price'\]"),
        ({"fills": [{"qty": Decimal("1")}, {"qty": 2.0}]}, r"record\['fills'\]\[1\]\['qty'\]"),
        ({"deep": {"a": [[0.1]]}}, r"record\['deep'\]\['a'\]\[0\]\[0\]"),
        ({"t": (1, 2.5)}, r"record\['t'\]\[1\]"),
        ({"nan": Decimal("NaN")}, r"record\['nan'\]"),
        ({"snan": Decimal("sNaN")}, r"record\['snan'\]"),
        ({"inf": Decimal("Infinity")}, r"record\['inf'\]"),
        ({"ninf": Decimal("-Infinity")}, r"record\['ninf'\]"),
        ({"f": float("nan")}, r"record\['f'\]"),
    ]
    for record, where in bad_values:
        with pytest.raises(ValueError, match=where):
            writer.append("event", record)

    # Nothing was written for the refusals and the chain did not move: the next record links to the
    # first one.
    second = writer.append("event", {"what": "second"})
    receipt = writer.close()
    lines = path.read_bytes().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["previous_hash"] == first
    assert receipt.record_count == 2 and receipt.final_chain_hash == second
    assert drain(path, receipt) == [("event", {"what": "first"}), ("event", {"what": "second"})]


@pytest.mark.parametrize(
    "value",
    [
        Fraction(1, 2),
        b"bytes",
        {1, 2},
        object(),
        1 + 2j,
        Path("x"),
        type("S", (str,), {})("subclass of str"),
        type("I", (int,), {})(3),
    ],
)
def test_values_json_cannot_hold_exactly_are_refused(tmp_path: Path, value: object) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    with pytest.raises(ValueError, match=r"record\['v'\]\[0\]"):
        writer.append("event", {"v": [value]})
    assert writer.close().record_count == 0


def test_keys_must_be_strings(tmp_path: Path) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    with pytest.raises(ValueError, match="string keys"):
        writer.append("event", {1: "a"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="string keys"):
        writer.append("event", {"a": {2: "b"}})
    assert writer.close().record_count == 0


def test_unknown_kinds_and_non_mappings_are_refused(tmp_path: Path) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    for kind in ("price", "", "Fill", "daily", None, 3):
        with pytest.raises(ValueError, match="kind"):
            writer.append(kind, {"x": 1})  # type: ignore[arg-type]
    for record in ([("a", 1)], "text", None, 5, ["a"]):
        with pytest.raises(ValueError, match="mapping"):
            writer.append("event", record)  # type: ignore[arg-type]
    receipt = writer.close()
    assert receipt.record_count == 0
    assert (tmp_path / "records.jsonl").read_bytes() == b""


def test_a_record_nested_too_deep_is_refused(tmp_path: Path) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    nested: object = 1
    for _ in range(200):
        nested = [nested]
    with pytest.raises(ValueError, match="nesting"):
        writer.append("event", {"n": nested})
    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="nesting"):
        writer.append("event", {"n": cycle})
    assert writer.close().record_count == 0


def test_a_closed_writer_accepts_nothing_and_closes_once(tmp_path: Path) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    writer.append("event", {"what": "one"})
    receipt = writer.close()
    with pytest.raises(ValueError, match="closed"):
        writer.append("event", {"what": "two"})
    with pytest.raises(ValueError, match="closed"):
        writer.close()
    assert read_back_count(tmp_path / "records.jsonl") == 1
    assert receipt.record_count == 1


def read_back_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


class FailingFile:
    """Stands in for the open file when the disk fails mid-write."""

    def __init__(self) -> None:
        self.closed = False

    def write(self, data: bytes) -> int:
        raise OSError("disk full")

    def close(self) -> None:
        self.closed = True


def test_a_failed_write_spends_the_writer(tmp_path: Path) -> None:
    writer = RecordWriter(tmp_path / "records.jsonl")
    writer.append("event", {"what": "before"})
    real = writer._file
    assert real is not None
    stub = FailingFile()
    writer._file = stub  # type: ignore[assignment]
    with pytest.raises(OSError, match="disk full"):
        writer.append("event", {"what": "lost"})
    assert stub.closed
    # A partial line may be on disk, so no later record or receipt can be trusted.
    with pytest.raises(ValueError, match="closed"):
        writer.append("event", {"what": "after"})
    with pytest.raises(ValueError, match="closed"):
        writer.close()
    real.close()


def test_the_context_manager_releases_the_file_when_the_run_fails(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    with pytest.raises(RuntimeError, match="boom"), RecordWriter(path) as writer:
        writer.append("event", {"what": "before"})
        raise RuntimeError("boom")
    # The handle is closed (the file can be replaced on any platform) and the writer is spent.
    path.unlink()
    with pytest.raises(ValueError, match="closed"):
        writer.append("event", {"what": "after"})
    with pytest.raises(ValueError, match="closed"):
        writer.close()

    # A clean run that closed itself inside the block leaves nothing for the exit to do.
    with RecordWriter(path) as finished:
        finished.append("event", {"what": "ok"})
        receipt = finished.close()
    assert receipt.record_count == 1


def test_many_records_stream_through_the_writer_and_the_reader(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    count = 3000
    writer = RecordWriter(path)
    for hour in range(count):
        writer.append("hourly", {"hour": hour, "equity": Decimal(hour) / 8, "complete": hour % 2})
    receipt = writer.close()
    assert receipt.record_count == count and dict(receipt.kinds) == {"hourly": count}

    def consume() -> Iterator[int]:
        for kind, record in read_records(path, receipt):
            assert kind == "hourly"
            assert isinstance(record["hour"], int)
            yield record["hour"]

    assert list(consume()) == list(range(count))


# --- the receipt file ------------------------------------------------------------------------


def test_the_receipt_round_trips_through_its_file(tmp_path: Path) -> None:
    path, receipt, _ = write_sample(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    digest = write_receipt(receipt_path, receipt)

    raw = receipt_path.read_bytes()
    assert digest == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == {
        "schema": "v4-receipt-1",
        "records_sha256": receipt.records_sha256,
        "record_count": len(SAMPLE),
        "final_chain_hash": receipt.final_chain_hash,
        "kinds": dict(receipt.kinds),
    }
    assert RECEIPT_SCHEMA == "v4-receipt-1"
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode("ascii")
    assert read_receipt(receipt_path) == receipt
    # The receipt read from disk verifies the records file.
    assert drain(path, read_receipt(receipt_path)) == [(k, plain(r)) for k, r in SAMPLE]


def test_an_existing_receipt_file_is_refused(tmp_path: Path) -> None:
    _, receipt, _ = write_sample(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        write_receipt(receipt_path, receipt)
    assert receipt_path.read_bytes() == b"keep me"


def good_receipt_dict() -> dict[str, object]:
    return {
        "schema": "v4-receipt-1",
        "records_sha256": "a" * 64,
        "record_count": 3,
        "final_chain_hash": "b" * 64,
        "kinds": {"event": 1, "fill": 2},
    }


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def with_(**changes: object) -> dict[str, object]:
    return {**good_receipt_dict(), **changes}


def without(key: str) -> dict[str, object]:
    data = good_receipt_dict()
    del data[key]
    return data


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (canonical_bytes(with_(schema="v4-receipt-2")), "schema"),
        (canonical_bytes(with_(schema="combined-v1")), "schema"),
        (canonical_bytes(without("schema")), "keys"),
        (canonical_bytes(without("kinds")), "keys"),
        (canonical_bytes(without("final_chain_hash")), "keys"),
        (canonical_bytes(with_(extra=1)), "keys"),
        (canonical_bytes(with_(records_sha256="A" * 64)), "records_sha256"),
        (canonical_bytes(with_(records_sha256="a" * 63)), "records_sha256"),
        (canonical_bytes(with_(records_sha256=None)), "records_sha256"),
        (canonical_bytes(with_(final_chain_hash="xyz")), "final_chain_hash"),
        (canonical_bytes(with_(record_count=4)), "do not add up"),
        (canonical_bytes(with_(record_count=2)), "do not add up"),
        (canonical_bytes(with_(record_count=-3)), "record_count"),
        (canonical_bytes(with_(record_count=True)), "record_count"),
        (canonical_bytes(with_(record_count="3")), "record_count"),
        (canonical_bytes(with_(kinds={"event": 1, "fill": 2, "price": 0})), "unknown kind"),
        (canonical_bytes(with_(kinds={"event": 1, "fill": 1})), "do not add up"),
        (canonical_bytes(with_(kinds={"event": 0, "fill": 3})), "positive"),
        (canonical_bytes(with_(kinds=[["event", 3]])), "kinds"),
        (canonical_bytes(with_(kinds=None)), "kinds"),
        (canonical_bytes(with_(record_count=0, kinds={})), "empty"),
        (b'{"schema":"v4-receipt-1","schema":"v4-receipt-1"}', "duplicate JSON key"),
        (canonical_bytes(good_receipt_dict()).replace(b":3,", b":3.0,"), "floats"),
        (canonical_bytes(good_receipt_dict()).replace(b":3,", b":NaN,"), "NaN"),
        (json.dumps(good_receipt_dict(), sort_keys=True, indent=1).encode(), "canonical"),
        (canonical_bytes(good_receipt_dict()) + b"\n", "canonical"),
        (json.dumps(good_receipt_dict(), sort_keys=False, separators=(",", ":")).encode(), "canon"),
        (canonical_bytes([good_receipt_dict()]), "object"),
        (b"", "JSON"),
        (b"not json", "JSON"),
        (b"\xff\xfe", "JSON"),
    ],
)
def test_read_receipt_refuses_what_is_not_exactly_a_receipt(
    tmp_path: Path, raw: bytes, message: str
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(raw)
    with pytest.raises(ValueError, match=message):
        read_receipt(receipt_path)


def test_read_receipt_accepts_the_good_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical_bytes(good_receipt_dict()))
    assert read_receipt(receipt_path) == Receipt("a" * 64, 3, "b" * 64, {"event": 1, "fill": 2})


def test_an_empty_cell_receipt_round_trips(tmp_path: Path) -> None:
    _, receipt, _ = write_sample(tmp_path, [])
    receipt_path = tmp_path / "receipt.json"
    write_receipt(receipt_path, receipt)
    assert read_receipt(receipt_path) == receipt


def test_read_receipt_refuses_a_file_that_is_too_large(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(b"x" * 70_000)
    with pytest.raises(ValueError, match="too large"):
        read_receipt(receipt_path)
