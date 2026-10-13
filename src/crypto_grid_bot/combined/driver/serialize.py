"""Exact JSON for a V3.1 cell's outcome and report, which its run job writes once and
aggregation reads back.

The text is canonical: sorted keys, no spaces, ASCII. A dataclass is an object holding
exactly its fields (``artifacts._schema``'s field types drive both directions), a tuple
is a list, and a Decimal or a Fraction is its ``str()`` as a string, under a default
decimal context. Decoding refuses a JSON float, a NaN or Infinity constant, a duplicate
key, a missing or unknown field, a value of another type and any text that is not the
canonical encoding of what it decodes to, so ``decode(encode(x)) == x`` and each value
has exactly one encoding.

Every Decimal is finite except in three ``RunOutcome`` fields: ``strategy_outcome``
writes ``Decimal("NaN")`` for the final equity, maximum drawdown and accounting residual
of a report that has none, and those fields carry it as ``"NaN"``.
"""

import json
import re
import types
from dataclasses import is_dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from typing import Any, Union, cast, get_args, get_origin

from crypto_grid_bot.combined.artifacts import _schema
from crypto_grid_bot.combined.experiment import RunOutcome
from crypto_grid_bot.combined.report import Report

OUTCOME_SCHEMA = "v3.1-outcome-1"
REPORT_SCHEMA = "v3.1-report-1"

# The fields ``outcomes._outcome`` fills with Decimal NaN when the report has no value.
_NAN_FIELDS = frozenset(
    {
        (RunOutcome, "final_equity"),
        (RunOutcome, "max_drawdown"),
        (RunOutcome, "accounting_residual"),
    }
)
_FRACTION = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?")


def encode_outcome(outcome: RunOutcome) -> str:
    """The outcome's canonical JSON, its report evidence included; refuses a value the
    JSON cannot hold exactly (a float, a list for a tuple, a non-finite Decimal)."""
    return _encode(OUTCOME_SCHEMA, "outcome", outcome, RunOutcome)


def decode_outcome(text: str) -> RunOutcome:
    """The outcome ``encode_outcome`` wrote as ``text``; any other text is refused."""
    return cast(RunOutcome, _decode(text, OUTCOME_SCHEMA, "outcome", RunOutcome))


def encode_report(report: Report) -> str:
    """The report's canonical JSON; refuses a value the JSON cannot hold exactly."""
    return _encode(REPORT_SCHEMA, "report", report, Report)


def decode_report(text: str) -> Report:
    """The report ``encode_report`` wrote as ``text``; any other text is refused."""
    return cast(Report, _decode(text, REPORT_SCHEMA, "report", Report))


def _encode(schema: str, key: str, value: object, kind: type) -> str:
    if type(value) is not kind:
        raise ValueError(f"{key}: a {kind.__name__} required")
    with localcontext(Context()):  # str() reads the context's exponent letter case
        document = {"schema": schema, key: _to_json(value, kind, key)}
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _decode(text: str, schema: str, key: str, kind: type) -> object:
    if type(text) is not str:
        raise ValueError(f"{key}: JSON text (str) required")
    try:
        document = json.loads(
            text, object_pairs_hook=_unique, parse_float=_refuse, parse_constant=_refuse
        )
    except RecursionError as exc:
        raise ValueError(f"{key}: JSON nested too deeply") from exc
    if type(document) is not dict or set(document) != {"schema", key}:
        raise ValueError(f"{key}: an object of schema and {key} required")
    if document["schema"] != schema:
        raise ValueError(f"{key}: schema {schema!r} required, got {document['schema']!r}")
    with localcontext(Context()):
        value = _from_json(document[key], kind, key)
    if _encode(schema, key, value, kind) != text:
        raise ValueError(f"{key}: not the canonical encoding (sorted keys, no spaces, ASCII)")
    return value


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _refuse(text: str) -> object:
    raise ValueError(f"{text} is a JSON float or constant; exact values are strings")


def _optional(hint: object) -> object | None:
    """``X`` for ``X | None``; None for a hint that is not a union."""
    if get_origin(hint) not in (types.UnionType, Union):
        return None
    args = get_args(hint)
    kinds: list[object] = [arg for arg in args if arg is not type(None)]
    if len(args) != 2 or len(kinds) != 1:
        raise TypeError(f"unsupported union {hint!r}: only X | None")
    return kinds[0]


def _items(hint: object, count: int, what: str) -> tuple[object, ...]:
    """The item type of each of ``count`` items of a tuple hint."""
    args = get_args(hint)
    kinds = (args[0],) * count if args[1:] == (Ellipsis,) else args
    if len(kinds) != count:
        raise ValueError(f"{what}: {len(kinds)} items required, got {count}")
    return kinds


def _to_json(value: object, hint: object, what: str, *, nan: bool = False) -> object:
    """``value`` as exact JSON, checked against its declared type ``hint``."""
    inner = _optional(hint)
    if inner is not None:
        return None if value is None else _to_json(value, inner, what, nan=nan)
    if get_origin(hint) is tuple:
        if type(value) is not tuple:
            raise ValueError(f"{what}: a tuple required, got {type(value).__name__}")
        kinds = _items(hint, len(value), what)
        return [_to_json(item, kind, f"{what}[]") for item, kind in zip(value, kinds, strict=True)]
    if isinstance(hint, type) and is_dataclass(hint):
        if type(value) is not hint:
            raise ValueError(f"{what}: a {hint.__name__} required")
        return {
            name: _to_json(
                getattr(value, name), field, f"{what}.{name}", nan=(hint, name) in _NAN_FIELDS
            )
            for name, field in _schema(hint)
        }
    if hint is Decimal:
        if type(value) is not Decimal:
            raise ValueError(f"{what}: a Decimal required, got {type(value).__name__}")
        if value.is_finite():
            return str(value)
        if nan and value.is_qnan() and not value.is_signed():
            return "NaN"
        raise ValueError(f"{what}: a finite Decimal required, got {value}")
    if hint is Fraction:
        if type(value) is not Fraction:
            raise ValueError(f"{what}: a Fraction required, got {type(value).__name__}")
        return str(value)
    if hint in (str, int, bool):
        if type(value) is not hint:
            raise ValueError(f"{what}: {_NAMES[hint]} required, got {type(value).__name__}")
        return value
    raise TypeError(f"{what}: unsupported field type {hint!r}")


def _from_json(data: object, hint: object, what: str, *, nan: bool = False) -> object:
    """The value of type ``hint`` that ``_to_json`` wrote as ``data``."""
    inner = _optional(hint)
    if inner is not None:
        return None if data is None else _from_json(data, inner, what, nan=nan)
    if get_origin(hint) is tuple:
        if type(data) is not list:
            raise ValueError(f"{what}: a list required")
        kinds = _items(hint, len(data), what)
        return tuple(
            _from_json(item, kind, f"{what}[]") for item, kind in zip(data, kinds, strict=True)
        )
    if isinstance(hint, type) and is_dataclass(hint):
        schema = _schema(hint)
        names = {name for name, _ in schema}
        if type(data) is not dict:
            raise ValueError(f"{what}: an object required")
        if missing := sorted(names - data.keys()):
            raise ValueError(f"{what}: missing fields: {', '.join(missing)}")
        if extra := sorted(data.keys() - names):
            raise ValueError(f"{what}: unexpected fields: {', '.join(extra)}")
        return hint(
            **{
                name: _from_json(
                    data[name], field, f"{what}.{name}", nan=(hint, name) in _NAN_FIELDS
                )
                for name, field in schema
            }
        )
    if hint is Decimal:
        return _decimal(data, what, nan=nan)
    if hint is Fraction:
        if type(data) is not str or _FRACTION.fullmatch(data) is None:
            raise ValueError(f'{what}: a Fraction string such as "-3/2" required')
        number = Fraction(data)
        if str(number) != data:
            raise ValueError(f"{what}: a Fraction in lowest terms required, got {data}")
        return number
    if hint in (str, int, bool):
        if type(data) is not hint:
            raise ValueError(f"{what}: {_NAMES[hint]} required")
        return data
    raise TypeError(f"{what}: unsupported field type {hint!r}")


def _decimal(data: object, what: str, *, nan: bool) -> Decimal:
    if type(data) is not str:
        raise ValueError(f"{what}: a Decimal string required")
    try:
        number = Decimal(data)
    except ArithmeticError as exc:
        raise ValueError(f"{what}: not a Decimal string: {data!r}") from exc
    if str(number) != data:
        raise ValueError(f"{what}: not a canonical Decimal string: {data!r}")
    if not number.is_finite() and not (nan and data == "NaN"):
        raise ValueError(f"{what}: a finite Decimal required, got {data}")
    return number


_NAMES = {str: "a string", int: "an integer", bool: "true or false"}
