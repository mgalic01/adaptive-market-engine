"""The owner-approved V3.1 test plan, which every real run must carry exactly.

The owner's decisions on the test plan of 2026-10-12 (``docs/V3_1_SOURCE_INVENTORY.md``,
"Owner decisions on the test plan, 2026-10-12"), as the run driver's design fixes them
(``docs/superpowers/specs/2026-10-12-v3-1-run-driver-design.md``, "Fixed inputs"), with
the capitals of the owner's decision of 2026-10-14 (the same file, "Owner decision on the
capitals, 2026-10-14"):

- W1, pass/fail: 2021-07-01 00:00 UTC to 2025-01-01 00:00 UTC, on ten coins: BTC, ETH,
  BNB, SOL, XRP, ADA, DOGE, LTC, LINK and TRX;
- W0, reported only: 2020-03-01 00:00 UTC to 2025-01-01 00:00 UTC, on the eight coins
  with futures then: BTC, ETH, BNB, XRP, ADA, LINK, LTC and TRX;
- three starting capitals, all USDT, each opening at exactly its amount: ``research``
  10,000, ``medium`` 1,000 and ``small`` 100. They replace 10,000 USDT plus EUR 100 at the
  ECB euro reference rate for 2024-12-31: no capital converts a currency.

``owner_plan_errors`` checks a prepare config, and optionally a loaded registration,
against ``OWNER_PLAN``. The driver (``scripts/v31_driver.py``, ``plan_gate``) applies it in
every real mode (prepare-only, registered and timing) before anything is fetched or
replayed. The smoke and the rehearsal run synthetic plans and never apply it: the smoke
calls no gate, and ``plan_gate`` exempts the rehearsal mode, which ``world_gate`` admits
only on a world committing the rehearsal marker. The registration and prepare loaders keep
their general rules, which synthetic registrations pass too.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.combined.driver.registration import (
    ACCEPTANCE_WINDOW,
    REPORTED_WINDOW,
    DriverRegistration,
    PrepareConfig,
)
from crypto_grid_bot.combined.experiment import Capital


@dataclass(frozen=True, slots=True)
class PlanWindow:
    """A window of the plan: its id, ``[start_ms, end_ms)`` and its coin set."""

    id: str
    start_ms: int
    end_ms: int
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class PlanCapital:
    """A starting capital of the plan: its id, currency, amount and initial equity, the
    only fields a registered capital may hold."""

    id: str
    currency: str
    amount: Decimal
    initial_equity: Decimal


@dataclass(frozen=True, slots=True)
class OwnerPlan:
    """The windows a real run prepares and registers (W1 judged, W0 reported) and the
    starting capitals it registers."""

    windows: tuple[PlanWindow, ...]
    capitals: tuple[PlanCapital, ...]


W1_SYMBOLS = frozenset(
    {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "TRXUSDT",
    }
)
W0_SYMBOLS = frozenset(
    {"BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT"}
)
W1_START_MS = 1_625_097_600_000  # 2021-07-01 00:00 UTC
W0_START_MS = 1_583_020_800_000  # 2020-03-01 00:00 UTC
END_MS = 1_735_689_600_000  # 2025-01-01 00:00 UTC, the reserved boundary
# The owner's three starting capitals (2026-10-14), all USDT, in the registration's cell
# order; each opens at exactly its amount.
OWNER_CAPITALS = (
    PlanCapital("research", "USDT", Decimal(10000), Decimal(10000)),
    PlanCapital("medium", "USDT", Decimal(1000), Decimal(1000)),
    PlanCapital("small", "USDT", Decimal(100), Decimal(100)),
)
OWNER_PLAN = OwnerPlan(
    windows=(
        PlanWindow(ACCEPTANCE_WINDOW, W1_START_MS, END_MS, W1_SYMBOLS),
        PlanWindow(REPORTED_WINDOW, W0_START_MS, END_MS, W0_SYMBOLS),
    ),
    capitals=OWNER_CAPITALS,
)
_CAPITAL_FIELDS = frozenset(field.name for field in fields(PlanCapital))


def owner_plan_errors(
    prepare: PrepareConfig, registration: DriverRegistration | None = None
) -> list[str]:
    """Every way ``prepare`` (and ``registration``, when given) differs from the owner's
    plan; empty when it is exactly that plan.

    The prepare config must name exactly the plan's windows, each with its start, end and
    coin set (no coin missing, none extra; order free). A registration must register
    exactly those windows' ids and dates (``check_registration`` makes W1 the judged one
    and W0 the reported one) and exactly the plan's capitals (order free): each one's id,
    currency, amount and initial equity, and no other field, so a capital carrying an FX
    rate, record or pin is refused whatever its value.

    ``OWNER_PLAN`` is read at each call, so a test running a real mode on a synthetic
    world can stand that world's own plan in for it.
    """
    plan = OWNER_PLAN
    errors: list[str] = []
    errors.extend(_window_errors("prepare config", _prepare_windows(prepare), plan))
    if registration is not None:
        registered = {
            window.id: (window.start_ms, window.end_ms, None)
            for window in (*registration.registration.windows, *registration.reported_windows)
        }
        errors.extend(_window_errors("registration", registered, plan))
        errors.extend(_capital_errors(registration.registration.capitals, plan))
    return errors


def _prepare_windows(
    prepare: PrepareConfig,
) -> dict[str, tuple[int, int, frozenset[str] | None]]:
    return {
        window.id: (window.start_ms, window.end_ms, frozenset(window.symbols))
        for window in prepare.windows
    }


def _window_errors(
    what: str,
    given: Mapping[str, tuple[int, int, frozenset[str] | None]],
    plan: OwnerPlan,
) -> list[str]:
    """How ``given`` (window id: start, end and coin set, or None for no coin list)
    differs from the plan's windows."""
    expected = {window.id: window for window in plan.windows}
    errors = []
    if missing := sorted(expected.keys() - given.keys()):
        errors.append(f"{what}: the owner's window(s) {', '.join(missing)} missing")
    if extra := sorted(given.keys() - expected.keys()):
        errors.append(f"{what}: window(s) {', '.join(extra)} outside the owner's plan")
    for window_id in sorted(expected.keys() & given.keys()):
        want = expected[window_id]
        start, end, symbols = given[window_id]
        if (start, end) != (want.start_ms, want.end_ms):
            errors.append(
                f"{what}: window {window_id} is {_span(start, end)}, not the owner's "
                f"{_span(want.start_ms, want.end_ms)}"
            )
        if symbols is not None and symbols != want.symbols:
            errors.append(
                f"{what}: window {window_id} must hold the owner's {len(want.symbols)} coins "
                f"(missing: {', '.join(sorted(want.symbols - symbols)) or 'none'}; "
                f"outside the plan: {', '.join(sorted(symbols - want.symbols)) or 'none'})"
            )
    return errors


def _capital_errors(capitals: Sequence[Capital], plan: OwnerPlan) -> list[str]:
    """How the registered ``capitals`` differ from the plan's: none missing, none extra,
    none twice, and each a capital record holding the plan's id, currency, amount and
    initial equity and no other field."""
    expected = {capital.id: capital for capital in plan.capitals}
    errors: list[str] = []
    given: dict[str, Capital] = {}
    for capital in capitals:
        if not isinstance(capital, Capital) or type(capital.id) is not str:
            errors.append(f"registration: {capital!r} is not a capital record")
            continue
        if capital.id in given:
            errors.append(f"registration: capital {capital.id} is registered twice")
        given[capital.id] = capital
    if missing := sorted(expected.keys() - given.keys()):
        errors.append(f"registration: the owner's capital(s) {', '.join(missing)} missing")
    if extra := sorted(given.keys() - expected.keys()):
        errors.append(f"registration: capital(s) {', '.join(extra)} outside the owner's plan")
    for capital_id in sorted(expected.keys() & given.keys()):
        want, held = expected[capital_id], given[capital_id]
        if beyond := sorted({field.name for field in fields(held)} - _CAPITAL_FIELDS):
            errors.append(
                f"registration: capital {capital_id} holds {', '.join(beyond)} beyond its id, "
                "currency, amount and initial equity; no capital of the owner's plan converts "
                "a currency"
            )
        if (held.currency, held.amount, held.initial_equity) != (
            want.currency,
            want.amount,
            want.initial_equity,
        ):
            errors.append(
                f"registration: capital {capital_id} is {held.amount} {held.currency} opening "
                f"at {held.initial_equity}, not the owner's {want.amount} {want.currency} "
                f"opening at {want.initial_equity}"
            )
    return errors


def _span(start_ms: int, end_ms: int) -> str:
    return f"[{_utc(start_ms)}, {_utc(end_ms)})"


def _utc(stamp_ms: int) -> str:
    try:
        return datetime.fromtimestamp(stamp_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return f"{stamp_ms} ms"
