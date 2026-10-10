"""Pure fixed-matrix V3.1 acceptance; no execution, registration writes or pooling.

The caller supplies an already frozen registration and observed outcomes. These
records do not authorize execution. Every window/capital is judged separately;
repeated attempts never replace failures or become independent observations.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import product

_BASELINES = frozenset(
    (
        "unchanged_v3_selector",
        *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)),
        "matched_spot_hold",
    )
)
_COMPONENTS = frozenset(
    (
        "spot_trend",
        "futures_trend",
        "futures_trend_long_only",
        "spot_grid",
        "combined",
        "combined_without_continuation",
        "combined_without_full_short_qualification",
        "combined_without_discretionary_trailing",
        "combined_without_funding_admission",
        "combined_without_recovery",
    )
)
_RESERVED = 1_735_689_600_000


@dataclass(frozen=True, slots=True)
class Window:
    id: str
    start_ms: int
    end_ms: int
    data_pin: str


@dataclass(frozen=True, slots=True)
class Capital:
    id: str
    initial_equity: Decimal
    currency: str
    amount: Decimal
    fx_rate: Decimal | None = None
    fx_pin: str | None = None


@dataclass(frozen=True, slots=True)
class Registration:
    arms: tuple[str, ...]
    baseline_arms: tuple[str, ...]
    windows: tuple[Window, ...]
    capitals: tuple[Capital, ...]
    cost_profiles: tuple[tuple[int, str], ...]
    code_pin: str
    config_pin: str
    pending: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunIdentity:
    arm: str
    window: str
    capital: str
    cost_multiple: int
    data_pin: str
    cost_profile_pin: str
    start_ms: int
    end_ms: int
    code_pin: str
    config_pin: str


@dataclass(frozen=True, slots=True)
class RunOutcome:
    identity: RunIdentity
    initial_equity: Decimal
    final_equity: Decimal
    max_drawdown: Decimal
    liquidations: int
    accounting_residual: Decimal
    accounting_explained: bool = False
    complete: bool = False
    failed: bool = False
    attempt_id: str = ""
    wallet_quantity_exact: bool = False


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    status: str
    failures: tuple[str, ...]
    incomplete_reasons: tuple[str, ...]
    outcomes: tuple[RunOutcome, ...]


def _pin(value: str | None, length: int = 64) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _finite(value: Decimal | None, positive: bool = False) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and (not positive or value > 0)


def _registration_errors(registration: Registration) -> list[str]:
    reg = registration
    errors: list[str] = []
    arms, baselines = set(reg.arms), set(reg.baseline_arms)
    if (
        len(arms) != len(reg.arms)
        or not arms >= (_BASELINES | _COMPONENTS)
        or "matched_spot_baselines" in arms
        or not all(isinstance(a, str) and a for a in arms)
    ):
        errors.append("registration: fixed menu missing, duplicated or unexpanded")
    if (
        len(baselines) != len(reg.baseline_arms)
        or not baselines >= _BASELINES
        or not baselines - _BASELINES
        or not baselines <= arms
        or bool(baselines & _COMPONENTS)
        or not arms <= baselines | _COMPONENTS
    ):
        errors.append("registration: every earlier baseline and explicit spot expansion required")
    if reg.pending:
        errors.append("registration: unresolved pins or decisions")
    if not _pin(reg.code_pin, 40) or not _pin(reg.config_pin):
        errors.append("registration: full code/config pins required")
    if (
        len(reg.cost_profiles) != 2
        or {multiple for multiple, _ in reg.cost_profiles} != {1, 2}
        or any(type(multiple) is not int or not _pin(pin) for multiple, pin in reg.cost_profiles)
    ):
        errors.append("registration: base and doubled cost profiles required")
    if not reg.windows or len({w.id for w in reg.windows}) != len(reg.windows):
        errors.append("registration: nonempty unique windows required")
    for window in reg.windows:
        if (
            not window.id
            or type(window.start_ms) is not int
            or type(window.end_ms) is not int
            or not 0 <= window.start_ms < window.end_ms <= _RESERVED
            or not _pin(window.data_pin)
        ):
            errors.append("registration: invalid window dates or data pin")
    if len(reg.capitals) != 2 or {c.id for c in reg.capitals} != {"research", "owner_small"}:
        errors.append("registration: research and EUR100 capital scenarios required")
    for capital in reg.capitals:
        if not _finite(capital.initial_equity, True) or not _finite(capital.amount, True):
            errors.append("registration: invalid capital amount")
            continue
        if capital.id == "research":
            if (
                capital.currency != "USDT"
                or capital.amount != 10000
                or capital.initial_equity != 10000
            ):
                errors.append("registration: research capital must be 10000 USDT")
        elif capital.id == "owner_small":
            if (
                capital.currency != "EUR"
                or capital.amount != 100
                or not _finite(capital.fx_rate, True)
                or not _pin(capital.fx_pin)
            ):
                errors.append("registration: EUR100 requires pinned positive FX conversion")
            elif capital.fx_rate is not None and Fraction(capital.initial_equity) != Fraction(
                capital.amount
            ) * Fraction(capital.fx_rate):
                errors.append("registration: initial equity does not equal EUR100 conversion")
    return errors


def _key(identity: RunIdentity) -> tuple[str, str, str, int]:
    return identity.arm, identity.window, identity.capital, identity.cost_multiple


def _metrics_valid(row: RunOutcome) -> bool:
    return (
        _finite(row.initial_equity, True)
        and _finite(row.final_equity)
        and _finite(row.max_drawdown)
        and row.max_drawdown >= 0
        and _finite(row.accounting_residual)
        and type(row.liquidations) is int
        and row.liquidations >= 0
        and all(
            type(flag) is bool
            for flag in (
                row.accounting_explained,
                row.complete,
                row.failed,
                row.wallet_quantity_exact,
            )
        )
    )


def evaluate(registration: Registration, outcomes: tuple[RunOutcome, ...]) -> AcceptanceResult:
    """Evaluate every registered cell; known failures and missing evidence both survive.

    Historical baselines need comparable valid evidence, not V3.1's drawdown/profit
    limits. Liquidation/accounting defects in V3.1 components are engineering failures.
    Only explained trade/equity residuals get the1e-18 tolerance; wallets/quantities
    require an explicit exactness verification. Zero-DD ratios remain indeterminate.
    """
    retained = tuple(outcomes)
    incomplete = _registration_errors(registration)
    if incomplete:
        return AcceptanceResult("incomplete", (), tuple(incomplete), retained)
    failures: list[str] = []
    expected: dict[tuple[str, str, str, int], tuple[RunIdentity, Decimal]] = {}
    for arm, window, capital, profile in product(
        registration.arms, registration.windows, registration.capitals, registration.cost_profiles
    ):
        multiple, pin = profile
        identity = RunIdentity(
            arm,
            window.id,
            capital.id,
            multiple,
            window.data_pin,
            pin,
            window.start_ms,
            window.end_ms,
            registration.code_pin,
            registration.config_pin,
        )
        expected[_key(identity)] = (identity, capital.initial_equity)
    grouped: dict[tuple[str, str, str, int], list[RunOutcome]] = {}
    attempts: dict[str, int] = {}
    for row in retained:
        grouped.setdefault(_key(row.identity), []).append(row)
        attempts[row.attempt_id] = attempts.get(row.attempt_id, 0) + 1
    for key in grouped.keys() - expected.keys():
        incomplete.append(f"{key}: unregistered outcome")
    valid: dict[tuple[str, str, str, int], RunOutcome] = {}
    for key, (identity, expected_capital) in expected.items():
        rows = grouped.get(key, [])
        if len(rows) != 1:
            incomplete.append(f"{key}: missing or repeated cell ({len(rows)} outcomes)")
            continue
        row = rows[0]
        if not row.attempt_id or attempts[row.attempt_id] != 1:
            incomplete.append(f"{key}: missing or repeated attempt identity")
            continue
        if row.identity != identity or any(
            type(value) is not int
            for value in (row.identity.cost_multiple, row.identity.start_ms, row.identity.end_ms)
        ):
            incomplete.append(f"{key}: mismatched evidence identity")
            continue
        if not _metrics_valid(row) or row.initial_equity != expected_capital:
            incomplete.append(f"{key}: invalid metrics or initial capital")
            continue
        if not row.complete or row.failed:
            incomplete.append(f"{key}: failed or incomplete attempt retained")
            continue
        residual = abs(Fraction(row.accounting_residual))
        invalid = (
            row.liquidations > 0
            or not row.wallet_quantity_exact
            or residual > Fraction(1, 10**18)
            or (bool(residual) and not row.accounting_explained)
        )
        if invalid:
            message = f"{key}: liquidation or invalid accounting"
            (incomplete if identity.arm in registration.baseline_arms else failures).append(message)
            continue
        valid[key] = row
        if identity.arm == "combined":
            if row.max_drawdown > Decimal(".30"):
                failures.append(f"{key}: full maximum drawdown exceeds30%")
            if identity.cost_multiple == 2 and row.final_equity <= row.initial_equity:
                failures.append(f"{key}: doubled-cost full profit is not positive")
    for window, capital in product(registration.windows, registration.capitals):
        full = valid.get(("combined", window.id, capital.id, 1))
        if full is None:
            continue
        full_return = Fraction(full.final_equity) / Fraction(full.initial_equity) - 1
        for baseline in registration.baseline_arms:
            key = (baseline, window.id, capital.id, 1)
            other = valid.get(key)
            if other is None:
                continue  # The missing/invalid cell already has a visible reason.
            other_return = Fraction(other.final_equity) / Fraction(other.initial_equity) - 1
            if full_return <= other_return:
                failures.append(f"{key}: full return does not strictly beat baseline")
            if full.max_drawdown == 0 or other.max_drawdown == 0:
                incomplete.append(f"{key}: return/drawdown is indeterminate at zero drawdown")
            elif full_return / Fraction(full.max_drawdown) <= other_return / Fraction(
                other.max_drawdown
            ):
                failures.append(f"{key}: full return/drawdown does not strictly beat baseline")
    status = "fail" if failures else "incomplete" if incomplete else "pass"
    return AcceptanceResult(status, tuple(failures), tuple(incomplete), retained)
