"""The owner's V3.1 test plan (owner decisions of 2026-10-12, capitals of 2026-10-14): its
constants, and every way a prepare config or a registration can differ from it.

Synthetic files under ``tmp_path``, written by the registration tests' own helpers (whose
documents carry the owner's plan); the driver's refusals in every real mode are in
tests/test_v31_driver_cli.py. Nothing touches the network.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from test_v31_registration import (
    DAY,
    EIGHT,
    TEN,
    load,
    prepare_document,
    write_json,
)

from crypto_grid_bot.combined.driver.owner_plan import (
    OWNER_CAPITALS,
    OWNER_PLAN,
    W0_SYMBOLS,
    W1_SYMBOLS,
    PlanCapital,
    owner_plan_errors,
)
from crypto_grid_bot.combined.driver.registration import load_prepare_config
from crypto_grid_bot.combined.experiment import Capital

Edit = Callable[[dict[str, Any]], object]


@dataclass(frozen=True, slots=True)
class FxCapital(Capital):
    """A capital record carrying the replaced FX fields, as no loader builds one."""

    fx_rate: D | None = None
    fx_pin: str | None = None


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()) * 1000


def prepare_config(tmp_path: Path, edit: Edit | None = None):
    document = prepare_document()
    if edit is not None:
        edit(document)
    path = tmp_path / "prepare.json"
    write_json(path, document)
    return load_prepare_config(path)


def test_the_plan_is_the_owners_decisions() -> None:
    """docs/V3_1_SOURCE_INVENTORY.md, owner decisions on the test plan of 2026-10-12 and
    on the capitals of 2026-10-14."""
    (w1, w0) = OWNER_PLAN.windows
    assert (w1.id, w1.start_ms, w1.end_ms) == ("w1", utc_ms("2021-07-01"), utc_ms("2025-01-01"))
    assert (w0.id, w0.start_ms, w0.end_ms) == ("w0", utc_ms("2020-03-01"), utc_ms("2025-01-01"))
    assert (w1.start_ms, w0.start_ms, w1.end_ms) == (
        1_625_097_600_000,
        1_583_020_800_000,
        1_735_689_600_000,
    )
    assert w1.symbols == W1_SYMBOLS == frozenset(TEN) and len(W1_SYMBOLS) == 10
    assert w0.symbols == W0_SYMBOLS == frozenset(EIGHT) and len(W0_SYMBOLS) == 8
    w1_only = W1_SYMBOLS - W0_SYMBOLS
    assert w1_only == {"SOLUSDT", "DOGEUSDT"}  # neither had futures in early 2020
    # Three USDT capitals, each opening at exactly its amount; none converts a currency.
    assert (
        OWNER_PLAN.capitals
        == OWNER_CAPITALS
        == (
            PlanCapital("research", "USDT", D(10000), D(10000)),
            PlanCapital("medium", "USDT", D(1000), D(1000)),
            PlanCapital("small", "USDT", D(100), D(100)),
        )
    )
    assert not hasattr(OWNER_PLAN, "fx_reference_date")


def test_the_owners_prepare_config_and_registration_pass(tmp_path: Path) -> None:
    reg = load(tmp_path / "repo")
    prepare = load_prepare_config(tmp_path / "repo" / "config/v3_1_prepare.json")
    assert [(c.id, c.currency, c.amount, c.initial_equity) for c in reg.registration.capitals] == [
        (c.id, c.currency, c.amount, c.initial_equity) for c in OWNER_CAPITALS
    ]
    assert owner_plan_errors(prepare) == []
    assert owner_plan_errors(prepare, reg) == []
    # The coin order is free: a set, exactly equal.
    reordered = prepare_config(tmp_path, _symbols(0, sorted(TEN, reverse=True)))
    assert owner_plan_errors(reordered) == []
    # So is the capitals' order.
    backwards = tuple(reversed(reg.registration.capitals))
    flipped = replace(reg, registration=replace(reg.registration, capitals=backwards))
    assert owner_plan_errors(prepare, flipped) == []


def _symbols(window: int, symbols: list[str]) -> Edit:
    return lambda d: d["windows"][window].update(symbols=symbols)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            _symbols(0, [s for s in TEN if s != "SOLUSDT"]),
            "prepare config: window w1 must hold the owner's 10 coins (missing: SOLUSDT; "
            "outside the plan: none)",
        ),
        (
            _symbols(0, [*TEN, "AVAXUSDT"]),
            "prepare config: window w1 must hold the owner's 10 coins (missing: none; "
            "outside the plan: AVAXUSDT)",
        ),
        (
            _symbols(1, [*EIGHT, "SOLUSDT"]),
            "prepare config: window w0 must hold the owner's 8 coins (missing: none; "
            "outside the plan: SOLUSDT)",
        ),
        (
            _symbols(1, [*(s for s in EIGHT if s != "TRXUSDT"), "DOGEUSDT"]),
            "prepare config: window w0 must hold the owner's 8 coins (missing: TRXUSDT; "
            "outside the plan: DOGEUSDT)",
        ),
        (
            lambda d: d["windows"][0].update(start_ms=d["windows"][0]["start_ms"] + DAY),
            "prepare config: window w1 is [2021-07-02 00:00 UTC, 2025-01-01 00:00 UTC), not "
            "the owner's [2021-07-01 00:00 UTC, 2025-01-01 00:00 UTC)",
        ),
        (
            lambda d: d["windows"][1].update(end_ms=d["windows"][1]["end_ms"] - DAY),
            "prepare config: window w0 is [2020-03-01 00:00 UTC, 2024-12-31 00:00 UTC), not "
            "the owner's [2020-03-01 00:00 UTC, 2025-01-01 00:00 UTC)",
        ),
        (lambda d: d["windows"].pop(1), "prepare config: the owner's window(s) w0 missing"),
        (
            lambda d: d["windows"].append({**d["windows"][1], "id": "w2"}),
            "prepare config: window(s) w2 outside the owner's plan",
        ),
    ],
)
def test_a_prepare_config_other_than_the_owners_is_listed(
    tmp_path: Path, edit: Edit, message: str
) -> None:
    errors = owner_plan_errors(prepare_config(tmp_path, edit))
    assert message in errors, errors


def test_every_difference_is_listed_at_once(tmp_path: Path) -> None:
    def edit(document: dict[str, Any]) -> None:
        document["windows"][0]["symbols"] = [s for s in TEN if s != "SOLUSDT"]
        document["windows"][1]["start_ms"] += DAY

    errors = owner_plan_errors(prepare_config(tmp_path, edit))
    assert len(errors) == 2 and "SOLUSDT" in errors[1] and "2020-03-02" in errors[0], errors


def test_a_registration_other_than_the_owners_is_listed(tmp_path: Path) -> None:
    prepare = prepare_config(tmp_path)
    assert owner_plan_errors(prepare) == []  # a prepare config names no capital
    # Another reported window than the owner's W0.
    shifted = load(tmp_path / "w0", lambda d: d["reported_windows"][0].update(start_ms=0))
    assert owner_plan_errors(prepare, shifted) == [
        "registration: window w0 is [1970-01-01 00:00 UTC, 2025-01-01 00:00 UTC), not the "
        "owner's [2020-03-01 00:00 UTC, 2025-01-01 00:00 UTC)"
    ]


def _with_capitals(reg: Any, *capitals: object) -> Any:
    """``reg`` holding ``capitals``: a registration no loader passes, which the owner's plan
    must refuse on its own (``check_registration`` already refuses each of these)."""
    return replace(reg, registration=replace(reg.registration, capitals=capitals))


@pytest.mark.parametrize(
    ("capitals", "messages"),
    [
        (
            lambda r, m, s: (r, replace(m, amount=D(1001), initial_equity=D(1001)), s),
            [
                "registration: capital medium is 1001 USDT opening at 1001, not the owner's "
                "1000 USDT opening at 1000"
            ],
        ),
        (
            lambda r, m, s: (r, m, replace(s, initial_equity=D("103.89"))),
            [
                "registration: capital small is 100 USDT opening at 103.89, not the owner's "
                "100 USDT opening at 100"
            ],
        ),
        (
            lambda r, m, s: (r, m, replace(s, currency="EUR")),
            [
                "registration: capital small is 100 EUR opening at 100, not the owner's 100 "
                "USDT opening at 100"
            ],
        ),
        (lambda r, m, s: (r, m), ["registration: the owner's capital(s) small missing"]),
        (
            lambda r, m, s: (r, m, s, Capital("owner_small", D("103.89"), "EUR", D(100))),
            ["registration: capital(s) owner_small outside the owner's plan"],
        ),
        (
            lambda r, m, s: (r, r, m, s),
            ["registration: capital research is registered twice"],
        ),
        (
            # The replaced EUR 100 capital's FX fields, on a capital whose money is right.
            lambda r, m, s: (r, m, FxCapital("small", D(100), "USDT", D(100), D(1), "e" * 64)),
            [
                "registration: capital small holds fx_pin, fx_rate beyond its id, currency, "
                "amount and initial equity; no capital of the owner's plan converts a currency"
            ],
        ),
        (
            # Even unset FX fields are fields beyond the plan's.
            lambda r, m, s: (FxCapital("research", D(10000), "USDT", D(10000)), m, s),
            [
                "registration: capital research holds fx_pin, fx_rate beyond its id, "
                "currency, amount and initial equity; no capital of the owner's plan converts "
                "a currency"
            ],
        ),
        (
            lambda r, m, s: (r, m, "small"),
            [
                "registration: 'small' is not a capital record",
                "registration: the owner's capital(s) small missing",
            ],
        ),
    ],
    ids=[
        "medium at 1001",
        "small opening at 103.89",
        "small in EUR",
        "no small",
        "owner_small too",
        "research twice",
        "an FX rate and pin",
        "unset FX fields",
        "not a capital",
    ],
)
def test_a_registration_without_exactly_the_owners_capitals_is_listed(
    tmp_path: Path, capitals: Callable[..., tuple], messages: list[str]
) -> None:
    prepare = prepare_config(tmp_path)
    reg = load(tmp_path / "repo")
    research, medium, small = reg.registration.capitals
    errors = owner_plan_errors(prepare, _with_capitals(reg, *capitals(research, medium, small)))
    assert errors == messages
