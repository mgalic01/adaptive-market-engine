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

from .report import Report, analyze

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
    """Observed endpoints; the terminal mark must precede the reserved window.

    A later adapter may support a prior-interval closing mark at the boundary only
    under a reviewed endpoint policy; this evaluator does not infer that meaning.
    """

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
class ReportEvidence:
    """Caller-attributed report for one attempt; pins are not authenticated here.

    Acceptance recomputes retained observations and checks their window and values.
    Registration/artifact validation must establish authenticity of the supplied
    identity and source references; this pure evaluator never fetches sources.
    """

    identity: RunIdentity
    attempt_id: str
    report: Report


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
    wallet_quantity_exact: bool | None = None
    report_evidence: ReportEvidence | None = None


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
        or len({pin for _, pin in reg.cost_profiles}) != 2
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
            or not 0 <= window.start_ms < window.end_ms < _RESERVED
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
        and (row.wallet_quantity_exact is None or type(row.wallet_quantity_exact) is bool)
        and all(
            type(flag) is bool
            for flag in (
                row.accounting_explained,
                row.complete,
                row.failed,
            )
        )
    )


def _report_valid(row: RunOutcome) -> bool:
    evidence = row.report_evidence
    if not isinstance(evidence, ReportEvidence) or not isinstance(evidence.report, Report):
        return False
    if (
        evidence.identity != row.identity
        or evidence.attempt_id != row.attempt_id
        or any(
            type(value) is not int
            for value in (
                evidence.identity.start_ms,
                evidence.identity.end_ms,
                evidence.identity.cost_multiple,
            )
        )
    ):
        return False
    report = evidence.report
    try:
        rebuilt = analyze(
            report.initial_equity,
            report.equity_points,
            report.contributions,
            report.opportunities,
            report.recovery,
            report.source_refs,
            opportunity_gap_ms=report.observation_gap_ms,
            metrics_start_ms=report.metrics_start_ms,
            daily_samples=report.daily_samples,
            utilization=report.utilization,
        )
        if report != rebuilt or type(report.complete) is not bool:
            return False
        if (
            not rebuilt.equity_points
            or rebuilt.metrics_start_ms != row.identity.start_ms
            or rebuilt.equity_points[0].timestamp_ms != row.identity.start_ms
            or rebuilt.equity_points[-1].timestamp_ms != row.identity.end_ms
            or (
                rebuilt.initial_equity,
                rebuilt.final_equity,
                rebuilt.max_drawdown,
                rebuilt.reconciliation_residual,
            )
            != (row.initial_equity, row.final_equity, row.max_drawdown, row.accounting_residual)
        ):
            return False
        # Preserve the frozen explained trade/equity tolerance. This is the only
        # structural issue acceptance may forgive; all required metrics remain mandatory.
        tolerated = row.accounting_explained and abs(Fraction(row.accounting_residual)) <= Fraction(
            1, 10**18
        )
        return all(_finite(metric.value) for metric in rebuilt.metrics) and not (
            set(rebuilt.issues) - ({"contribution_equity_residual"} if tolerated else set())
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        return False


def _safety_failures(observed: RunOutcome) -> list[str]:
    identity = observed.identity
    key = _key(identity)
    failures: list[str] = []
    if identity.arm in _COMPONENTS:
        if type(observed.liquidations) is int and observed.liquidations > 0:
            failures.append(f"{key}: observed liquidation")
        if observed.wallet_quantity_exact is False:
            failures.append(f"{key}: observed wallet/quantity mismatch")
        if _finite(observed.accounting_residual):
            residual = abs(Fraction(observed.accounting_residual))
            if residual > Fraction(1, 10**18) or (
                residual and observed.accounting_explained is False
            ):
                failures.append(f"{key}: observed invalid accounting")
    if (
        identity.arm == "combined"
        and _finite(observed.max_drawdown)
        and observed.max_drawdown > Decimal(".30")
    ):
        failures.append(f"{key}: full maximum drawdown exceeds30%")
    return failures


def _matched_safety_failures(reg: Registration, row: RunOutcome) -> list[str]:
    """Incomplete registration cannot authorize comparisons or erase known failures.

    Require a unique cell and complete valid identity pins. Ambiguous duplicate
    declarations are never collapsed, even when they happen to have equal values.
    """
    identity = row.identity
    if (
        identity.arm not in _COMPONENTS
        or reg.arms.count(identity.arm) != 1
        or identity.arm in reg.baseline_arms
        or not _pin(reg.code_pin, 40)
        or not _pin(reg.config_pin)
        or identity.code_pin != reg.code_pin
        or identity.config_pin != reg.config_pin
        or any(
            type(value) is not int
            for value in (identity.start_ms, identity.end_ms, identity.cost_multiple)
        )
    ):
        return []
    windows = [w for w in reg.windows if w.id == identity.window]
    capitals = [c for c in reg.capitals if c.id == identity.capital]
    profiles = [p for p in reg.cost_profiles if p[0] == identity.cost_multiple]
    if len(windows) != 1 or len(capitals) != 1 or len(profiles) != 1:
        return []
    window, capital, profile = windows[0], capitals[0], profiles[0]
    if (
        not isinstance(window.id, str)
        or not window.id
        or type(window.start_ms) is not int
        or type(window.end_ms) is not int
        or not 0 <= window.start_ms < window.end_ms < _RESERVED
        or not _pin(window.data_pin)
        or (identity.start_ms, identity.end_ms, identity.data_pin)
        != (window.start_ms, window.end_ms, window.data_pin)
        or type(profile[0]) is not int
        or profile[0] not in {1, 2}
        or not _pin(profile[1])
        or identity.cost_profile_pin != profile[1]
        or capital.id not in {"research", "owner_small"}
        or not _finite(capital.initial_equity, True)
        or not _finite(row.initial_equity, True)
        or row.initial_equity != capital.initial_equity
    ):
        return []
    return _safety_failures(row)


def evaluate(registration: Registration, outcomes: tuple[RunOutcome, ...]) -> AcceptanceResult:
    """Evaluate every registered cell; known failures and missing evidence both survive.

    Historical baselines need comparable valid evidence, not V3.1's drawdown/profit
    limits. Liquidation/accounting defects in V3.1 components are engineering failures.
    Only explained trade/equity residuals get the1e-18 tolerance; wallets/quantities
    require an explicit exactness verification (None is unknown, False is a mismatch).
    Terminal profit tests require complete matching reports; already observed safety
    failures remain failures without them. Zero-DD ratios remain indeterminate.
    """
    retained = tuple(outcomes)
    incomplete = _registration_errors(registration)
    if incomplete:
        observed_failures = tuple(
            failure for row in retained for failure in _matched_safety_failures(registration, row)
        )
        return AcceptanceResult(
            "fail" if observed_failures else "incomplete",
            observed_failures,
            tuple(incomplete),
            retained,
        )
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
        # Comparability requires one complete attempt; observed safety failures do not.
        # Inspect every attributable attempt before rejecting duplicates or partial runs.
        for observed in rows:
            if observed.identity != identity or any(
                type(value) is not int
                for value in (
                    observed.identity.cost_multiple,
                    observed.identity.start_ms,
                    observed.identity.end_ms,
                )
            ):
                continue
            failures.extend(_safety_failures(observed))
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
        if row.wallet_quantity_exact is None:
            incomplete.append(f"{key}: wallet/quantity verification unavailable")
            continue
        if not row.complete or row.failed:
            incomplete.append(f"{key}: failed or incomplete attempt retained")
            continue
        if not _report_valid(row):
            incomplete.append(f"{key}: missing, incomplete or mismatched report evidence")
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
        if (
            identity.arm == "combined"
            and identity.cost_multiple == 2
            and row.final_equity <= row.initial_equity
        ):
            failures.append(f"{key}: doubled-cost full profit is not positive")
    for window, capital, profile in product(
        registration.windows, registration.capitals, registration.cost_profiles
    ):
        multiple, _ = profile
        full = valid.get(("combined", window.id, capital.id, multiple))
        if full is None:
            continue
        full_return = Fraction(full.final_equity) / Fraction(full.initial_equity) - 1
        for baseline in registration.baseline_arms:
            key = (baseline, window.id, capital.id, multiple)
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
