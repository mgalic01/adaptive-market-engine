"""Acceptance outcomes from replay and baseline evidence; no new judgement here.

Each outcome carries exactly its report's final equity, drawdown and residual, so
``experiment.evaluate`` can recompute the report and match it. It also carries the
report's disclosures and capital label, which are information only. The registered run
harness supplies the identity (window, capital, cost profile, pins, scenario) and
a unique attempt ID; a failed or incomplete attempt is retained, never retried.
"""

from decimal import Decimal
from fractions import Fraction

from .baseline_records import NATIVE_STOPS, BaselineEvidence
from .experiment import ReportEvidence, RunIdentity, RunOutcome
from .report import RESIDUAL_TOLERANCE, Report
from .strategy_replay import StrategyTrace


def _outcome(
    identity: RunIdentity,
    report: Report,
    *,
    attempt_id: str,
    complete: bool,
    failed: bool,
    liquidations: int,
    explained: bool,
    wallet_exact: bool | None,
    native_stop: str | None = None,
) -> RunOutcome:
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("unique attempt identity required")
    return RunOutcome(
        identity,
        report.initial_equity,
        report.final_equity if report.final_equity is not None else Decimal("NaN"),
        report.max_drawdown if report.max_drawdown is not None else Decimal("NaN"),
        liquidations,
        report.reconciliation_residual
        if report.reconciliation_residual is not None
        else Decimal("NaN"),
        explained,
        complete,
        failed,
        attempt_id,
        wallet_exact,
        ReportEvidence(identity, attempt_id, report),
        native_stop,
        report.disclosures,
        report.capital_label,
    )


def strategy_outcome(
    trace: StrategyTrace, report: Report, identity: RunIdentity, *, attempt_id: str
) -> RunOutcome:
    """A V3.1 component run: liquidation and accounting come from the engine's marks.

    A trade-to-equity residual up to 1e-18 USDT either way is explained and leaves the
    report complete (``report.analyze``); the residual itself is carried unchanged.
    """
    marks = [o.snapshot for o in trace.observations]
    last = marks[-1].account if marks else None
    residual = report.reconciliation_residual
    return _outcome(
        identity,
        report,
        attempt_id=attempt_id,
        complete=trace.failure is None and report.complete,
        failed=trace.failure is not None,
        liquidations=int(any(snapshot.liquidation for snapshot in marks)),
        explained=residual is not None and abs(Fraction(residual)) <= RESIDUAL_TOLERANCE,
        wallet_exact=None if last is None else last.integrity_ok,
    )


def baseline_outcome(
    evidence: BaselineEvidence, identity: RunIdentity, *, attempt_id: str
) -> RunOutcome:
    """A frozen baseline cell; a native stop is a finished result, other stops are not.

    Owner decisions 2026-10-11 and 2026-10-12: a baseline liquidated under its own
    rules is complete and keeps its stop reason; its report holds the stop equity,
    labelled frozen, to the window end. Any other status (V3's no_tradable_position or
    leverage_not_restored, which the V3 adapter keeps as a ``baseline_stop:`` producer
    issue, an engine or parity failure, a missing input) leaves the cell failed and
    incomplete. As for a strategy run, a residual up to 1e-18 USDT leaves the report
    complete and a larger one does not, whatever the adapter claims.
    """
    report = evidence.report
    stop = evidence.status if evidence.status in NATIVE_STOPS else None
    finished = evidence.status is None or stop is not None
    return _outcome(
        identity,
        report,
        attempt_id=attempt_id,
        complete=finished and not report.issues,
        failed=not finished,
        liquidations=evidence.liquidations,
        explained=evidence.accounting_explained,
        wallet_exact=evidence.wallet_quantity_exact,
        native_stop=stop,
    )
