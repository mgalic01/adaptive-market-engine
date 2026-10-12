"""Pure fixed-matrix V3.1 acceptance; no execution, registration writes or pooling.

The caller supplies an already frozen registration and observed outcomes. These
records do not authorize execution. Every window/capital is judged separately;
repeated attempts never replace failures or become independent observations.

Baselines (owner decision 2026-10-11, "V3 family, hold, V0-V2 and D") are named
``unchanged_v3_selector``, ``unchanged_v3_r<1..6>_long_only``, ``matched_spot_hold``
and, in each native path mode ``<mode>`` of ``backtest.replay.PATH_MODES``,
``matched_v0_grid_<mode>``, ``matched_v1_<variant>_grid_<mode>`` for every V1
variant the registration pins, ``matched_v2_grid_<mode>`` and
``matched_d_trend_<mode>``. A registration names exactly these baselines.
"""

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from itertools import product

from crypto_grid_bot.backtest.replay import PATH_MODES

from .baseline_records import NATIVE_STOPS
from .common_series import CommonSeries, common_hourly_series, skipped_hours_valid
from .observation_policy import POLICY_ID, PolicyEvidence
from .report import Report, analyze

# The frozen V3 baselines, the only frozen code that stops natively.
_V3_BASELINES = frozenset(
    ("unchanged_v3_selector", *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)))
)
_BASELINES = _V3_BASELINES | {"matched_spot_hold"}
_V1_VARIANT = re.compile("[a-z0-9]+")
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
_DAY = 86_400_000
# Plausible USDT per EUR rates for the owner_small conversion, both ends included.
_FX_BAND = (Decimal("0.5"), Decimal("2.0"))
SCENARIOS = ("open_low_high_close", "open_high_low_close")


def required_baselines(v1_variants: tuple[str, ...]) -> frozenset[str]:
    """Every baseline arm the owner requires, by the documented names."""
    return _BASELINES | {
        name
        for mode in PATH_MODES
        for name in (
            f"matched_v0_grid_{mode}",
            *(f"matched_v1_{variant}_grid_{mode}" for variant in v1_variants),
            f"matched_v2_grid_{mode}",
            f"matched_d_trend_{mode}",
        )
    }


@dataclass(frozen=True, slots=True)
class Window:
    """Observed endpoints; the terminal mark must precede the reserved window.

    A later adapter may support a prior-interval closing mark at the boundary only
    under a reviewed endpoint policy; this evaluator does not infer that meaning.
    ``skipped_hours`` are the hours some registered price source has no bar for,
    pinned with the data and skipped for every arm alike (owner, 2026-10-11): sorted
    hour stamps strictly inside the window, never its first hour or its last, whose
    close is the terminal mark. The list is a registration fact this evaluator cannot
    verify from outcomes: it must be derived mechanically from the pinned data (the
    union of every registered source's missing bars inside the window) and frozen
    before any run.
    """

    id: str
    start_ms: int
    end_ms: int
    data_pin: str
    skipped_hours: tuple[int, ...] = ()


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
    observation_policy: str | None = None
    adapter_pins: tuple[tuple[str, str], ...] = ()
    scenarios: tuple[str, ...] = ()
    v1_variants: tuple[str, ...] = ()  # pinned V1 grid variants: lowercase letters, digits


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Serialized run provenance, including mandatory owner-small FX source binding.

    Adapters must populate fx_pin for owner_small. Research needs no conversion
    and retains None; older owner-small identities with no FX pin are incomplete.
    Components require one of SCENARIOS; frozen baselines use "native". Each
    modeled scenario is a separate account outcome, never a pooled observation.
    """

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
    fx_pin: str | None = None
    observation_policy: str | None = None
    adapter_pin: str | None = None
    scenario: str | None = None


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
    native_stop: str | None = None  # a frozen baseline that ended under its own rules
    # Carried from the report: information only, never an input to acceptance.
    disclosures: tuple[str, ...] = ()
    capital_label: str | None = None


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """The full combined arm against one baseline, exactly as acceptance compared them.

    Compounded return and lifetime maximum drawdown of each cell's common hourly series
    (``common_series``), and whether the full arm strictly beat the baseline on return
    and on return/drawdown. A cell without valid comparison evidence leaves its values
    and both verdicts None; a zero drawdown leaves the return/drawdown verdict None.
    """

    window: str
    capital: str
    cost_multiple: int
    scenario: str  # the full arm's modeled scenario; the baseline cell is native
    baseline: str
    full_return: Fraction | None
    full_max_drawdown: Fraction | None
    baseline_return: Fraction | None
    baseline_max_drawdown: Fraction | None
    beats_return: bool | None
    beats_return_drawdown: bool | None
    baseline_native_stop: str | None = None  # held frozen at its stop equity


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    status: str
    failures: tuple[str, ...]
    incomplete_reasons: tuple[str, ...]
    outcomes: tuple[RunOutcome, ...]
    skipped_hours: tuple[tuple[str, tuple[int, ...]], ...] = ()  # per window id
    # Every registered baseline against every full combined cell, once the registration
    # is complete; information for reports, already reflected in status and failures.
    comparisons: tuple[BaselineComparison, ...] = ()


@dataclass(frozen=True, slots=True)
class CellComparison:
    """One full combined cell as acceptance judged it, for that cell's report page.

    ``status`` is the whole evaluation's: one failing cell fails acceptance, so a cell's
    passing measures never pass it alone. ``cell_status`` and the reasons cover this cell:
    those naming the full cell, one of its baseline cells or their comparison, plus those
    naming no cell (the registration, malformed records); reasons of other cells are only
    counted. ``baselines`` are every registered baseline, so one without a row still shows.
    """

    window: str
    capital: str
    cost_multiple: int
    scenario: str
    status: str
    cell_status: str
    baselines: tuple[str, ...]
    rows: tuple[BaselineComparison, ...]
    failures: tuple[str, ...]
    incomplete_reasons: tuple[str, ...]
    other_failures: int
    other_incomplete: int


def cell_comparison(
    registration: Registration,
    result: AcceptanceResult,
    *,
    window: str,
    capital: str,
    cost_multiple: int,
    scenario: str,
) -> CellComparison:
    """The registered full combined cell's part of ``result``; judges nothing new.

    Reasons are attributed by the cell keys ``evaluate`` writes them with.
    """
    windows = registration.windows if isinstance(registration.windows, (tuple, list)) else ()
    capitals = registration.capitals if isinstance(registration.capitals, (tuple, list)) else ()
    profiles = (
        registration.cost_profiles if isinstance(registration.cost_profiles, (tuple, list)) else ()
    )
    if (
        window not in {w.id for w in windows if isinstance(w, Window)}
        or capital not in {c.id for c in capitals if isinstance(c, Capital)}
        or cost_multiple not in {p[0] for p in profiles if _cost_profile_valid(p)}
        or scenario not in SCENARIOS
    ):
        raise ValueError("a registered full combined cell required")
    arms = registration.baseline_arms
    baselines = (
        tuple(arms)
        if isinstance(arms, (tuple, list)) and all(isinstance(a, str) for a in arms)
        else ()
    )
    prefixes = (
        f"{('combined', window, capital, cost_multiple, scenario)}:",
        *(
            f"{(baseline, window, capital, cost_multiple, 'native')}{end}"
            for baseline in baselines
            for end in (":", f"/{scenario}:")
        ),
    )

    def own(reason: str) -> bool:
        return not reason.startswith("(") or reason.startswith(prefixes)

    failures = tuple(reason for reason in result.failures if own(reason))
    incomplete = tuple(reason for reason in result.incomplete_reasons if own(reason))
    return CellComparison(
        window,
        capital,
        cost_multiple,
        scenario,
        result.status,
        "fail" if failures else "incomplete" if incomplete else "pass",
        baselines,
        tuple(
            row
            for row in result.comparisons
            if (row.window, row.capital, row.cost_multiple, row.scenario)
            == (window, capital, cost_multiple, scenario)
        ),
        failures,
        incomplete,
        len(result.failures) - len(failures),
        len(result.incomplete_reasons) - len(incomplete),
    )


def _pin(value: str | None, length: int = 64) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _finite(value: Decimal | None, positive: bool = False) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and (not positive or value > 0)


def _cost_profile_valid(profile: object) -> bool:
    """Validate deserialized pair shape and scalar types before unpacking/hashing."""
    return (
        isinstance(profile, (tuple, list))
        and len(profile) == 2
        and type(profile[0]) is int
        and profile[0] in {1, 2}
        and _pin(profile[1])
    )


def _registration_errors(registration: Registration) -> list[str]:
    reg = registration
    errors: list[str] = []
    if reg.scenarios != SCENARIOS:
        errors.append("registration: both ordered modeled scenarios required")
    arms_valid = isinstance(reg.arms, (tuple, list)) and all(
        isinstance(arm, str) and arm.strip() for arm in reg.arms
    )
    baselines_valid = isinstance(reg.baseline_arms, (tuple, list)) and all(
        isinstance(arm, str) and arm.strip() for arm in reg.baseline_arms
    )
    arms = set(reg.arms) if arms_valid else set()
    baselines = set(reg.baseline_arms) if baselines_valid else set()
    variants = reg.v1_variants
    variants_valid = (
        isinstance(variants, tuple)
        and bool(variants)
        and all(isinstance(v, str) and _V1_VARIANT.fullmatch(v) for v in variants)
        and len(set(variants)) == len(variants)
    )
    if not variants_valid:
        errors.append("registration: a nonempty list of unique V1 variant names required")
    required = required_baselines(variants if variants_valid else ())
    if (
        not arms_valid
        or len(arms) != len(reg.arms)
        or not arms >= (required | _COMPONENTS)
        or "matched_spot_baselines" in arms
    ):
        errors.append("registration: fixed menu missing, duplicated or unexpanded")
    if (
        not baselines_valid
        or len(baselines) != len(reg.baseline_arms)
        or baselines != required
        or not baselines <= arms
        or bool(baselines & _COMPONENTS)
        or not arms <= baselines | _COMPONENTS
    ):
        errors.append("registration: every earlier baseline and explicit spot expansion required")
    if baselines_valid:
        if missing := sorted(required - baselines):
            errors.append(f"registration: baselines missing: {', '.join(missing)}")
        if unknown := sorted(baselines - required - _COMPONENTS):
            errors.append(
                f"registration: baselines outside the documented names: {', '.join(unknown)}"
            )
    if reg.pending:
        errors.append("registration: unresolved pins or decisions")
    if (
        reg.observation_policy != POLICY_ID
        or not isinstance(reg.adapter_pins, tuple)
        or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not _pin(pair[1])
            for pair in reg.adapter_pins
        )
        or len({pair[0] for pair in reg.adapter_pins}) != len(reg.adapter_pins)
        or {pair[0] for pair in reg.adapter_pins} != arms
    ):
        errors.append("registration: approved observation policy and every adapter pin required")
    if not _pin(reg.code_pin, 40) or not _pin(reg.config_pin):
        errors.append("registration: full code/config pins required")
    if (
        not isinstance(reg.cost_profiles, (tuple, list))
        or len(reg.cost_profiles) != 2
        or not all(_cost_profile_valid(profile) for profile in reg.cost_profiles)
        or len({pin for _, pin in reg.cost_profiles}) != 2
        or {multiple for multiple, _ in reg.cost_profiles} != {1, 2}
    ):
        errors.append("registration: base and doubled cost profiles required")
    windows = reg.windows if isinstance(reg.windows, (tuple, list)) else ()
    capitals = reg.capitals if isinstance(reg.capitals, (tuple, list)) else ()
    if (
        not windows
        or any(
            not isinstance(w, Window) or not isinstance(w.id, str) or not w.id.strip()
            for w in windows
        )
        or len({w.id for w in windows}) != len(windows)
    ):
        errors.append("registration: nonempty unique windows required")
    for window in windows:
        if (
            not isinstance(window, Window)
            or not isinstance(window.id, str)
            or not window.id.strip()
            or type(window.start_ms) is not int
            or type(window.end_ms) is not int
            # A window may END at the reserved boundary: its last bar is development
            # data, marked at its own close, with nothing read at or after the boundary.
            or not 0 <= window.start_ms < window.end_ms <= _RESERVED
            or not _pin(window.data_pin)
        ):
            errors.append("registration: invalid window dates or data pin")
        elif (
            window.start_ms % _DAY
            or window.end_ms % _DAY
            or window.end_ms - window.start_ms < 2 * _DAY
        ):
            # Feasibility of the existing mandatory UTC-daily metric contract only;
            # this does not select an intratimestamp observation/sampling policy.
            errors.append(
                "registration: daily metrics require UTC day endpoints and at least two days"
            )
        elif not skipped_hours_valid(window.skipped_hours, window.start_ms, window.end_ms):
            errors.append(
                "registration: skipped hours must be sorted hours strictly inside the window, "
                "never its first or last hour"
            )
    if (
        len(capitals) != 2
        or any(not isinstance(c, Capital) or not isinstance(c.id, str) for c in capitals)
        or {c.id for c in capitals} != {"research", "owner_small"}
    ):
        errors.append("registration: research and EUR100 capital scenarios required")
    for capital in capitals:
        if isinstance(capital, Capital):
            errors.extend(_capital_errors(capital))
    return errors


def _capital_errors(capital: Capital) -> list[str]:
    """Research is 10000 USDT; owner_small is EUR100 at a pinned, plausible FX rate.

    The rate is USDT per EUR. A rate of exactly 1 would label 100 USDT as EUR100, and a
    rate outside 0.5 to 2.0 is no EUR rate at all: both are refused.
    """
    if not _finite(capital.initial_equity, True) or not _finite(capital.amount, True):
        return ["registration: invalid capital amount"]
    if capital.id == "research" and (
        capital.currency != "USDT" or capital.amount != 10000 or capital.initial_equity != 10000
    ):
        return ["registration: research capital must be 10000 USDT"]
    if capital.id != "owner_small":
        return []
    if (
        capital.currency != "EUR"
        or capital.amount != 100
        or capital.fx_rate is None
        or not _finite(capital.fx_rate, True)
        or not _pin(capital.fx_pin)
    ):
        return ["registration: EUR100 requires pinned positive FX conversion"]
    if capital.fx_rate == 1 or not _FX_BAND[0] <= capital.fx_rate <= _FX_BAND[1]:
        return ["registration: EUR100 needs a plausible USDT per EUR rate (0.5 to 2.0, never 1)"]
    if Fraction(capital.initial_equity) != Fraction(capital.amount) * Fraction(capital.fx_rate):
        return ["registration: initial equity does not equal EUR100 conversion"]
    return []


def capital_label(capital: Capital) -> str:
    """The capital scenario as reports label it, so 100 USDT never passes for EUR100.

    ``research_10000_usdt``, or ``owner_small`` with its currency, amount, USDT per EUR
    rate (as registered) and FX pin. Only a registrable capital has a label.
    """
    if (
        not isinstance(capital, Capital)
        or capital.id not in {"research", "owner_small"}
        or _capital_errors(capital)
    ):
        raise ValueError("a registrable research or owner_small capital required")
    if capital.id == "research":
        return "research_10000_usdt"
    return f"owner_small:EUR:100:usdt_per_eur={capital.fx_rate}:fx_pin={capital.fx_pin}"


def _outcome_shape_valid(row: object) -> bool:
    """Malformed records stay retained but are never grouped, hashed or attributed."""
    if not isinstance(row, RunOutcome) or not isinstance(row.identity, RunIdentity):
        return False
    identity = row.identity
    return (
        all(
            isinstance(value, str) and bool(value.strip())
            for value in (identity.arm, identity.window, identity.capital)
        )
        and type(identity.cost_multiple) is int
        and (identity.scenario is None or isinstance(identity.scenario, str))
    )


def _key(identity: RunIdentity) -> tuple[str, str, str, int, str | None]:
    return (
        identity.arm,
        identity.window,
        identity.capital,
        identity.cost_multiple,
        identity.scenario,
    )


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
        and (
            row.native_stop is None
            or (type(row.native_stop) is str and row.native_stop in NATIVE_STOPS)
        )
        and all(
            type(flag) is bool
            for flag in (
                row.accounting_explained,
                row.complete,
                row.failed,
            )
        )
    )


def _matching_report(row: RunOutcome, initial_equity: Decimal) -> Report | None:
    """Recompute attributable observations independently of wrapper result scalars.

    Identity and source authenticity remain the caller/artifact validator's duty.
    Missing metrics do not erase a provable safety breach, but a foreign window,
    capital, attempt or a report that differs from recomputation cannot supply one.
    """
    evidence = row.report_evidence
    if not isinstance(evidence, ReportEvidence) or not isinstance(evidence.report, Report):
        return None
    if (
        evidence.identity != row.identity
        or not isinstance(row.attempt_id, str)
        or not row.attempt_id.strip()
        or not isinstance(evidence.attempt_id, str)
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
        return None
    report = evidence.report
    if isinstance(report.policy_evidence, PolicyEvidence) and (
        report.policy_evidence.scenario != row.identity.scenario
        or report.policy_evidence.policy_id != row.identity.observation_policy
        or report.policy_evidence.adapter_pin != row.identity.adapter_pin
    ):
        return None
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
            policy_evidence=report.policy_evidence,
            skipped_hours=report.skipped_hours,
            utilization=report.utilization,
            capital_observations=report.capital_observations,
            producer_issues=report.producer_issues,
            disclosures=report.disclosures,
            capital_label=report.capital_label,
        )
        if report != rebuilt or type(report.complete) is not bool:
            return None
        if (
            not rebuilt.equity_points
            or rebuilt.metrics_start_ms != row.identity.start_ms
            or rebuilt.equity_points[0].timestamp_ms != row.identity.start_ms
            or rebuilt.equity_points[-1].timestamp_ms != row.identity.end_ms
            or rebuilt.initial_equity != initial_equity
            or rebuilt.equity_points[0].equity != initial_equity
        ):
            return None
        return rebuilt
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        return None


def _report_valid(row: RunOutcome, skipped_hours: tuple[int, ...] = ()) -> bool:
    """A report built against skipped hours the registration does not pin is foreign."""
    report = _matching_report(row, row.initial_equity)
    if report is not None and not set(report.skipped_hours) <= set(skipped_hours):
        return False
    if report is not None and (
        not isinstance(report.policy_evidence, PolicyEvidence)
        or report.policy_evidence.policy_id != row.identity.observation_policy
        or report.policy_evidence.adapter_pin != row.identity.adapter_pin
        or report.policy_evidence.scenario != row.identity.scenario
    ):
        return False
    if report is None or (
        report.final_equity,
        report.max_drawdown,
        report.reconciliation_residual,
    ) != (row.final_equity, row.max_drawdown, row.accounting_residual):
        return False
    # Preserve the frozen explained trade/equity tolerance. This is the only
    # structural issue acceptance may forgive; all required metrics remain mandatory.
    tolerated = row.accounting_explained is True and abs(
        Fraction(row.accounting_residual)
    ) <= Fraction(1, 10**18)
    return all(_finite(metric.value) for metric in report.metrics) and not (
        set(report.issues) - ({"contribution_equity_residual"} if tolerated else set())
    )


def _safety_failures(observed: RunOutcome) -> list[str]:
    identity = observed.identity
    key = _key(identity)
    failures: list[str] = []
    if identity.arm in _COMPONENTS:
        if _finite(observed.final_equity) and observed.final_equity <= 0:
            failures.append(f"{key}: observed capital exhaustion")
        if type(observed.liquidations) is int and observed.liquidations > 0:
            failures.append(f"{key}: observed liquidation")
        if observed.wallet_quantity_exact is False:
            failures.append(f"{key}: observed wallet/quantity mismatch")
        if _finite(observed.accounting_residual):
            residual = abs(Fraction(observed.accounting_residual))
            if residual > Fraction(1, 10**18) or (
                residual and observed.accounting_explained is not True
            ):
                failures.append(f"{key}: observed invalid accounting")
    if (
        identity.arm == "combined"
        and _finite(observed.max_drawdown)
        and observed.max_drawdown > Decimal(".30")
    ):
        failures.append(f"{key}: full maximum drawdown exceeds30%")
    return failures


def _observed_safety_failures(row: RunOutcome, initial_equity: Decimal) -> list[str]:
    """Attribute each evidence source against the registered capital independently.

    A wrong-capital scalar wrapper cannot assign its failures to this trial, but
    cannot erase a matching report's observations. Both original records survive.
    """
    failures = (
        _safety_failures(row)
        if _finite(row.initial_equity, True) and row.initial_equity == initial_equity
        else []
    )
    report = _matching_report(row, initial_equity)
    if (
        report is not None
        and row.identity.arm in _COMPONENTS
        and report.final_equity is not None
        and report.max_drawdown is not None
        and report.reconciliation_residual is not None
    ):
        failures.extend(
            _safety_failures(
                replace(
                    row,
                    final_equity=report.final_equity,
                    max_drawdown=report.max_drawdown,
                    accounting_residual=report.reconciliation_residual,
                    liquidations=0,
                    wallet_quantity_exact=None,
                )
            )
        )
        if any(point.equity <= 0 for point in report.equity_points):
            failures.append(f"{_key(row.identity)}: observed capital exhaustion")
    return list(dict.fromkeys(failures))


def _matched_safety_failures(reg: Registration, row: RunOutcome) -> list[str]:
    """Incomplete registration cannot authorize comparisons or erase known failures.

    Require a unique cell and complete valid identity pins. Ambiguous duplicate
    declarations are never collapsed, even when they happen to have equal values.
    """
    identity = row.identity
    if (
        identity.arm not in _COMPONENTS
        or identity.scenario not in SCENARIOS
        or not isinstance(reg.arms, (tuple, list))
        or reg.arms.count(identity.arm) != 1
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
    if any(
        not isinstance(records, (tuple, list))
        for records in (reg.windows, reg.capitals, reg.cost_profiles)
    ):
        return []
    if (
        reg.observation_policy != POLICY_ID
        or identity.observation_policy != reg.observation_policy
        or not isinstance(reg.adapter_pins, (tuple, list))
    ):
        return []
    adapters = [
        pair
        for pair in reg.adapter_pins
        if isinstance(pair, (tuple, list)) and pair and pair[0] == identity.arm
    ]
    if (
        len(adapters) != 1
        or len(adapters[0]) != 2
        or not _pin(adapters[0][1])
        or identity.adapter_pin != adapters[0][1]
    ):
        return []
    # Unrelated malformed records cannot erase a uniquely attributable failure.
    windows = [w for w in reg.windows if isinstance(w, Window) and w.id == identity.window]
    capitals = [c for c in reg.capitals if isinstance(c, Capital) and c.id == identity.capital]
    # Keep malformed candidates with an identifiable matching multiple: they must
    # not disappear and turn an ambiguous declaration into a unique valid profile.
    profiles = [
        p
        for p in reg.cost_profiles
        if isinstance(p, (tuple, list)) and p and p[0] == identity.cost_multiple
    ]
    if len(windows) != 1 or len(capitals) != 1 or len(profiles) != 1:
        return []
    window, capital, profile = windows[0], capitals[0], profiles[0]
    if (
        not isinstance(window.id, str)
        or not window.id.strip()
        or type(window.start_ms) is not int
        or type(window.end_ms) is not int
        or not 0 <= window.start_ms < window.end_ms <= _RESERVED
        or not _pin(window.data_pin)
        or (identity.start_ms, identity.end_ms, identity.data_pin)
        != (window.start_ms, window.end_ms, window.data_pin)
        or not _cost_profile_valid(profile)
        or identity.cost_profile_pin != profile[1]
        or not isinstance(capital.id, str)
        or capital.id not in {"research", "owner_small"}
        or not _finite(capital.initial_equity, True)
        or (capital.id == "owner_small" and not _pin(capital.fx_pin))
        or identity.fx_pin != (capital.fx_pin if capital.id == "owner_small" else None)
    ):
        return []
    return _observed_safety_failures(row, capital.initial_equity)


def evaluate(registration: Registration, outcomes: tuple[RunOutcome, ...]) -> AcceptanceResult:
    """Evaluate every registered cell; known failures and missing evidence both survive.

    Historical baselines need comparable valid evidence, not V3.1's drawdown/profit
    limits. Liquidation/accounting defects in V3.1 components are engineering failures.
    Only an exact True explanation grants the 1e-18 trade/equity residual tolerance.
    Wallets/quantities require explicit exactness verification (None unknown, False mismatch).
    Terminal profit tests require complete matching reports; already observed safety
    failures remain failures without them. Zero-DD ratios remain indeterminate.
    Every component requires both modeled scenarios; the same native baseline
    control is compared to each separately, never counted as an extra trial.
    Comparisons skip each window's registered skipped hours for every arm alike;
    the 30% drawdown gate still uses every native mark. A baseline that ended at a
    native stop is a finished result held frozen at its stop equity, still to beat.
    """
    retained = tuple(outcomes)
    malformed = sum(not _outcome_shape_valid(row) for row in retained)
    incomplete = _registration_errors(registration)
    if incomplete:
        if malformed:
            incomplete.append(f"{malformed} malformed outcome record(s) retained")
        observed_failures = tuple(
            failure
            for row in retained
            if _outcome_shape_valid(row)
            for failure in _matched_safety_failures(registration, row)
        )
        return AcceptanceResult(
            "fail" if observed_failures else "incomplete",
            observed_failures,
            tuple(incomplete),
            retained,
        )
    failures: list[str] = []
    expected: dict[
        tuple[str, str, str, int, str | None], tuple[RunIdentity, Decimal, tuple[int, ...]]
    ] = {}
    for arm, window, capital, profile, scenario in product(
        registration.arms,
        registration.windows,
        registration.capitals,
        registration.cost_profiles,
        (*registration.scenarios, "native"),
    ):
        if (arm in _COMPONENTS) == (scenario == "native"):
            continue
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
            capital.fx_pin if capital.id == "owner_small" else None,
            registration.observation_policy,
            dict(registration.adapter_pins)[arm],
            scenario,
        )
        expected[_key(identity)] = (identity, capital.initial_equity, window.skipped_hours)
    grouped: dict[tuple[str, str, str, int, str | None], list[RunOutcome]] = {}
    attempts: dict[str, int] = {}
    if malformed:
        incomplete.append(f"{malformed} malformed outcome record(s) retained")
    for row in retained:
        if not _outcome_shape_valid(row):
            continue
        if not isinstance(row.identity.scenario, str) or row.identity.scenario not in (
            *SCENARIOS,
            "native",
        ):
            incomplete.append("invalid scenario identity retained")
            continue
        grouped.setdefault(_key(row.identity), []).append(row)
        if isinstance(row.attempt_id, str) and row.attempt_id.strip():
            attempts[row.attempt_id] = attempts.get(row.attempt_id, 0) + 1
    for key in grouped.keys() - expected.keys():
        incomplete.append(f"{key}: unregistered outcome")
    valid: dict[tuple[str, str, str, int, str | None], RunOutcome] = {}
    common: dict[tuple[str, str, str, int, str | None], CommonSeries] = {}
    for key, (identity, expected_capital, skipped_hours) in expected.items():
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
            failures.extend(_observed_safety_failures(observed, expected_capital))
        if len(rows) != 1:
            incomplete.append(f"{key}: missing or repeated cell ({len(rows)} outcomes)")
            continue
        row = rows[0]
        if (
            not isinstance(row.attempt_id, str)
            or not row.attempt_id.strip()
            or attempts[row.attempt_id] != 1
        ):
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
        if row.native_stop is not None and not (
            identity.arm in registration.baseline_arms and identity.arm in _V3_BASELINES
        ):
            incomplete.append(f"{key}: only a frozen V3 baseline can end at a native stop")
            continue
        if row.wallet_quantity_exact is None:
            incomplete.append(f"{key}: wallet/quantity verification unavailable")
            continue
        if not row.complete or row.failed:
            incomplete.append(f"{key}: failed or incomplete attempt retained")
            continue
        if not _report_valid(row, skipped_hours):
            incomplete.append(f"{key}: missing, incomplete or mismatched report evidence")
            continue
        residual = abs(Fraction(row.accounting_residual))
        invalid = (
            # A baseline's own liquidation ends it as a finished result (owner, 2026-10-11).
            row.liquidations != int(row.native_stop == "liquidation")
            or not row.wallet_quantity_exact
            or residual > Fraction(1, 10**18)
            or (bool(residual) and row.accounting_explained is not True)
        )
        if invalid:
            message = f"{key}: liquidation or invalid accounting"
            if identity.arm in registration.baseline_arms:
                incomplete.append(message)
            # Component failures were recorded specifically during the safety scan.
            continue
        if (
            identity.arm == "combined"
            and identity.cost_multiple == 2
            and row.final_equity <= row.initial_equity
        ):
            failures.append(f"{key}: doubled-cost full profit is not positive")
        report = row.report_evidence.report if row.report_evidence is not None else None
        try:
            if report is None or report.policy_evidence is None:
                raise ValueError("missing policy")
            series = common_hourly_series(
                report.equity_points,
                report.policy_evidence,
                start_ms=identity.start_ms,
                end_ms=identity.end_ms,
                skipped_hours=skipped_hours,
            )
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            incomplete.append(f"{key}: common hourly comparison evidence unavailable")
            continue
        if series.native_stop != row.native_stop:
            incomplete.append(f"{key}: frozen marks and native stop disagree")
            continue
        common[key] = series
        valid[key] = row
    comparisons: list[BaselineComparison] = []
    for window, capital, profile, scenario in product(
        registration.windows,
        registration.capitals,
        registration.cost_profiles,
        registration.scenarios,
    ):
        multiple, _ = profile
        # A series exists only for a valid cell; a missing or invalid cell already has a
        # visible reason and its comparisons stay unavailable.
        full_series = common.get(("combined", window.id, capital.id, multiple, scenario))
        for baseline in registration.baseline_arms:
            key = (baseline, window.id, capital.id, multiple, "native")
            other_series = common.get(key)
            beats_return: bool | None = None
            beats_ratio: bool | None = None
            if full_series is not None and other_series is not None:
                full_return, other_return = full_series.net_return, other_series.net_return
                beats_return = full_return > other_return
                if not beats_return:
                    failures.append(
                        f"{key}/{scenario}: full return does not strictly beat baseline"
                    )
                if full_series.max_drawdown == 0 or other_series.max_drawdown == 0:
                    incomplete.append(
                        f"{key}/{scenario}: return/drawdown is indeterminate at zero drawdown"
                    )
                else:
                    beats_ratio = (
                        full_return / full_series.max_drawdown
                        > other_return / other_series.max_drawdown
                    )
                    if not beats_ratio:
                        failures.append(
                            f"{key}/{scenario}: full return/drawdown does not strictly beat "
                            "baseline"
                        )
            comparisons.append(
                BaselineComparison(
                    window.id,
                    capital.id,
                    multiple,
                    scenario,
                    baseline,
                    None if full_series is None else full_series.net_return,
                    None if full_series is None else full_series.max_drawdown,
                    None if other_series is None else other_series.net_return,
                    None if other_series is None else other_series.max_drawdown,
                    beats_return,
                    beats_ratio,
                    None if other_series is None else other_series.native_stop,
                )
            )
    status = "fail" if failures else "incomplete" if incomplete else "pass"
    skipped = tuple((window.id, window.skipped_hours) for window in registration.windows)
    return AcceptanceResult(
        status, tuple(failures), tuple(incomplete), retained, skipped, tuple(comparisons)
    )
