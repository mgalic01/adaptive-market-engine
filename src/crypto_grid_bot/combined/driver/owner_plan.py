"""The owner-approved V3.1 test plan, which every real run must carry exactly.

The owner's decisions on the test plan of 2026-10-12 (``docs/V3_1_SOURCE_INVENTORY.md``,
"Owner decisions on the test plan, 2026-10-12"), as the run driver's design fixes them
(``docs/superpowers/specs/2026-10-12-v3-1-run-driver-design.md``, "Fixed inputs"):

- W1, pass/fail: 2021-07-01 00:00 UTC to 2025-01-01 00:00 UTC, on ten coins: BTC, ETH,
  BNB, SOL, XRP, ADA, DOGE, LTC, LINK and TRX;
- W0, reported only: 2020-03-01 00:00 UTC to 2025-01-01 00:00 UTC, on the eight coins
  with futures then: BTC, ETH, BNB, XRP, ADA, LINK, LTC and TRX;
- the owner_small capital: EUR 100 at the ECB euro reference rate for 2024-12-31.

``owner_plan_errors`` checks a prepare config, and optionally a loaded registration,
against ``OWNER_PLAN``. The driver (``scripts/v31_driver.py``, ``plan_gate``) applies it in
every real mode (prepare-only, registered and timing) before anything is fetched or
replayed. The smoke and the rehearsal run synthetic plans and never apply it: the smoke
calls no gate, and ``plan_gate`` exempts the rehearsal mode, which ``world_gate`` admits
only on a world committing the rehearsal marker. The registration and prepare loaders keep
their general rules, which synthetic registrations pass too.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from crypto_grid_bot.combined.driver.registration import (
    ACCEPTANCE_WINDOW,
    REPORTED_WINDOW,
    DriverRegistration,
    PrepareConfig,
)


@dataclass(frozen=True, slots=True)
class PlanWindow:
    """A window of the plan: its id, ``[start_ms, end_ms)`` and its coin set."""

    id: str
    start_ms: int
    end_ms: int
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class OwnerPlan:
    """The windows a real run prepares and registers (W1 judged, W0 reported) and the
    reference date of the FX record its EUR capital names."""

    windows: tuple[PlanWindow, ...]
    fx_reference_date: date


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
OWNER_PLAN = OwnerPlan(
    windows=(
        PlanWindow(ACCEPTANCE_WINDOW, W1_START_MS, END_MS, W1_SYMBOLS),
        PlanWindow(REPORTED_WINDOW, W0_START_MS, END_MS, W0_SYMBOLS),
    ),
    fx_reference_date=date(2024, 12, 31),
)
_FX_CAPITAL = "owner_small"


def owner_plan_errors(
    prepare: PrepareConfig, registration: DriverRegistration | None = None
) -> list[str]:
    """Every way ``prepare`` (and ``registration``, when given) differs from the owner's
    plan; empty when it is exactly that plan.

    The prepare config must name exactly the plan's windows, each with its start, end and
    coin set (no coin missing, none extra; order free). A registration must register
    exactly those windows' ids and dates (``check_registration`` makes W1 the judged one
    and W0 the reported one), and its owner_small capital must name an FX record whose
    reference date is the plan's; so must any other FX capital.

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
        dates = dict(registration.fx_reference_dates)
        if _FX_CAPITAL not in dates:
            errors.append(
                f"registration: the {_FX_CAPITAL} capital names no FX record; the owner's "
                f"is the ECB reference rate for {plan.fx_reference_date.isoformat()}"
            )
        for capital_id, reference in sorted(dates.items()):
            if reference != plan.fx_reference_date:
                errors.append(
                    f"registration: capital {capital_id}'s FX record is the reference rate "
                    f"for {reference.isoformat()}, not the owner's "
                    f"{plan.fx_reference_date.isoformat()}"
                )
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


def _span(start_ms: int, end_ms: int) -> str:
    return f"[{_utc(start_ms)}, {_utc(end_ms)})"


def _utc(stamp_ms: int) -> str:
    try:
        return datetime.fromtimestamp(stamp_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return f"{stamp_ms} ms"
