"""Reconcile one supplied completed menu; no replay, registration or acceptance.

Bindings authenticate artifact bytes and menu semantics, plus training Sharpe.
They do not establish nontraining report derivation, market provenance, or attempt
history outside this directory. Caller must provide exclusive directory ownership.
"""

import hashlib
import json
from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.account import AccountingAudit
from crypto_grid_bot.trend.evidence_journal import LIMIT, _json_value, _object
from crypto_grid_bot.trend.evidence_writer import AttemptRecorder
from crypto_grid_bot.trend.metrics import (
    TRADE_RECONCILIATION_TOLERANCE,
    sample_returns,
    sharpe,
    validate_sample_path,
)
from crypto_grid_bot.trend.orchestration import INVALID, TrainingScore
from crypto_grid_bot.trend.runner import EquityState
from crypto_grid_bot.trend.selection_report import selection_report
from crypto_grid_bot.trend.spot_account import SpotAudit
from crypto_grid_bot.trend.walk_forward import RULES, windows


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    role: str
    run_id: str
    path: str
    sha256: str
    bytes: int
    records: int
    reason: str | None


def _decimal(value: Any) -> Decimal:
    if type(value) is not str:
        raise ValueError("evidence Decimal must be a string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid evidence Decimal") from exc
    if not result.is_finite():
        raise ValueError("nonfinite evidence Decimal")
    return result


def _rows(directory: Path, metadata: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Hash the same bounded bytes whose semantics the caller consumes."""
    digest = hashlib.sha256()
    size = count = 0
    with (directory / metadata["path"]).open("rb") as source:
        while raw := source.readline(LIMIT + 1):
            if len(raw) > LIMIT or not raw.endswith(b"\n"):
                raise ValueError("invalid evidence row length")
            row = json.loads(raw, object_pairs_hook=_object)
            if (
                type(row) is not dict
                or set(row) != {"schema", "kind", "value"}
                or type(row["schema"]) is not int
                or row["schema"] != 1
                or type(row["kind"]) is not str
            ):
                raise ValueError("invalid evidence row")
            _json_value(row)
            digest.update(raw)
            size += len(raw)
            count += 1
            yield row["kind"], row["value"]
    if (digest.hexdigest(), size, count) != (
        metadata["sha256"],
        metadata["bytes"],
        metadata["records"],
    ):
        raise ValueError("evidence changed while reconciling")


def _artifact(
    directory: Path,
    metadata: dict[str, Any],
    identity: dict[str, Any],
    score: TrainingScore | None,
    first_months: Mapping[str, str],
) -> str | None:
    phase = identity["phase"]
    futures = phase not in ("spot_hold", "full_size_hold")
    header_kind = (
        "account" if futures else ("spot_account" if phase == "spot_hold" else "full_size_hold")
    )
    headers: dict[str, Any] = {}
    samples = []
    equity = []
    audits = 0
    start, end = identity["start_ms"], identity["end_ms_exclusive"]
    schedule = identity.get("pick_schedule", [])
    stamps = [p[0] for p in schedule]
    for kind, value in _rows(directory, metadata):
        if kind in ("outcome", "account", "spot_account", "full_size_hold"):
            if (
                kind in headers
                or kind not in ({"outcome", "account"} if futures else {header_kind})
                or type(value) is not dict
            ):
                raise ValueError("duplicate or incompatible evidence header")
            headers[kind] = value
        elif kind == "active_lifecycle":
            raise ValueError("unfinished lifecycle")
        elif kind in ("audit", "spot_audit"):
            if kind != ("audit" if futures else "spot_audit") or type(value) is not dict:
                raise ValueError("incompatible audit")
            quantities = {s: _decimal(v) for s, v in value["quantity_residuals"].items()}
            accepted = (
                AccountingAudit(
                    _decimal(value["wallet_residual"]),
                    quantities,
                    _decimal(value["equity_residual"]),
                ).accepted
                if futures
                else SpotAudit(_decimal(value["cash_residual"]), quantities).exact
            )
            if not accepted:
                raise ValueError("rejected accounting audit")
            audits += 1
        elif kind == "decision" and futures:
            stamp = value["timestamp_ms"]
            if type(stamp) is not int or not start <= stamp < end:
                raise ValueError("decision outside attempt boundaries")
            if value["rule"] != schedule[bisect_right(stamps, stamp) - 1][1]:
                raise ValueError("decision disagrees with pick schedule")
        elif kind == "sample" and score is not None:
            if type(value) is not list or len(value) != 2 or type(value[0]) is not int:
                raise ValueError("invalid training sample")
            samples.append((value[0], _decimal(value[1])))
        elif kind == "equity" and score is not None:
            stamp = value["timestamp_ms"]
            if type(stamp) is not int or not start <= stamp <= end:
                raise ValueError("training equity outside boundaries")
            equity.append(
                EquityState(
                    stamp,
                    value["kind"],
                    _decimal(value["equity"]),
                    _decimal(value["peak"]),
                    _decimal(value["drawdown"]),
                )
            )
    if header_kind not in headers or not audits:
        raise ValueError("missing account or audit evidence")
    account = headers[header_kind]
    if _decimal(account["initial"]) != 10000:
        raise ValueError("unexpected initial account equity")
    for key in ("multiple", "cost_multiple") if futures else ("cost_multiple",):
        if type(account[key]) is not int or account[key] != identity[key]:
            raise ValueError("artifact account settings disagree")
    reason: str | None
    if futures:
        if "outcome" not in headers:
            raise ValueError("missing outcome")
        outcome = headers["outcome"]
        reason = outcome["reason"]
        if reason is not None and (type(reason) is not str or reason not in INVALID):
            raise ValueError("unknown strategy reason")
        if account["stopped"] != (reason or "completed"):
            raise ValueError("outcome and stopped reason disagree")
        if _decimal(outcome["trade_reconciliation_residual"]).copy_abs() > (
            TRADE_RECONCILIATION_TOLERANCE
        ):
            raise ValueError("unreconciled lifecycle residual")
    elif phase == "spot_hold":
        if account["stopped"] not in ("completed", "unavailable_exclusion_close"):
            raise ValueError("unknown spot stopped reason")
        reason = None if account["stopped"] == "completed" else account["stopped"]
    else:
        reason = account["reason"]
        if reason not in (None, "unavailable_first_purchase"):
            raise ValueError("unknown hold diagnostic reason")
        for key, wanted in (
            ("start_ms", start),
            ("end_ms_exclusive", end),
            ("scheduled_ms", start + 3600000),
        ):
            if type(account[key]) is not int or account[key] != wanted:
                raise ValueError("hold diagnostic boundaries disagree")
        members = {s for s, month in first_months.items() if month_bounds_ms(month)[0] <= start}
        if set(account["budgets"]) != members:
            raise ValueError("hold diagnostic initial members disagree")
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            budget = Decimal(10000) / len(members)
        if any(_decimal(v) != budget for v in account["budgets"].values()):
            raise ValueError("hold diagnostic budgets disagree")
        missing = account["missing_symbols"]
        if (
            type(missing) is not list
            or any(type(s) is not str for s in missing)
            or len(missing) != len(set(missing))
            or not set(missing) <= members
            or bool(missing) != (reason == "unavailable_first_purchase")
        ):
            raise ValueError("hold diagnostic availability disagrees")
    if score is not None:
        if reason != score.invalid_reason:
            raise ValueError("training invalid reason disagrees")
        if not equity or equity[0].timestamp_ms != start or equity[0].equity != 10000:
            raise ValueError("training initial equity or boundary disagrees")
        if reason is None:
            if equity[-1].timestamp_ms != end:
                raise ValueError("training terminal boundary disagrees")
            validate_sample_path(samples, equity)
            if sharpe(sample_returns(samples)) != score.sharpe:
                raise ValueError("training Sharpe disagrees with artifact samples")
    return reason


def _expected(
    training: Sequence[TrainingScore],
    picks: Mapping[int, str | None],
    first_months: Mapping[str, str],
) -> dict[str, tuple[dict[str, Any], TrainingScore | None]]:
    selection_report(training, picks, first_months)
    calendar = windows(first_months["BTCUSDT"])
    start = min(picks)
    end = month_bounds_ms(calendar[-1].test_end_exclusive)[0]
    schedule = [list(p) for p in sorted(picks.items())]
    expected: dict[str, tuple[dict[str, Any], TrainingScore | None]] = {}

    def add(
        role: str,
        phase: str,
        rule: str | None,
        begin: int,
        stop: int,
        multiple: int,
        cost: int,
        chosen: list[list[Any]],
        score: TrainingScore | None = None,
    ) -> None:
        expected[role] = (
            dict(
                phase=phase,
                rule=rule,
                start_ms=begin,
                end_ms_exclusive=stop,
                multiple=multiple,
                cost_multiple=cost,
                pick_schedule=chosen,
            ),
            score,
        )

    indexed = {(s.test_month, s.rule): s for s in training}
    for window in calendar:
        begin = month_bounds_ms(window.train_start)[0]
        stop = month_bounds_ms(window.train_end_exclusive)[0]
        for rule in RULES:
            add(
                f"training/{window.test_start}/{rule}",
                "training",
                rule,
                begin,
                stop,
                2,
                1,
                [[begin, rule]],
                indexed[window.test_start, rule],
            )
    add("main", "out_of_sample", None, start, end, 2, 1, schedule)
    for multiple, cost in ((1, 1), (3, 1), (1, 2), (2, 2), (3, 2)):
        add(
            f"sensitivity/{multiple}/{cost}",
            "sensitivity",
            None,
            start,
            end,
            multiple,
            cost,
            schedule,
        )
    for rule in RULES:
        add(
            f"fixed_rule/{rule}",
            "fixed_rule",
            rule,
            start,
            end,
            2,
            1,
            [[stamp, rule] for stamp in sorted(picks)],
        )
    for phase, costs in (("spot_hold", (1, 2)), ("full_size_hold", (1,))):
        for cost in costs:
            role = f"spot_hold/{cost}" if phase == "spot_hold" else phase
            expected[role] = (
                dict(phase=phase, start_ms=start, end_ms_exclusive=end, cost_multiple=cost),
                None,
            )
    return expected


def reconcile_experiment_evidence(
    directory: Path,
    training: Sequence[TrainingScore],
    picks: Mapping[int, str | None],
    first_months: Mapping[str, str],
) -> tuple[EvidenceBinding, ...]:
    """Return deterministic bindings for exactly 12Q+21 error-free attempts.

    Known invalid strategies and unavailable hold diagnostics retain their reason.
    No report prerequisite is removed and no historical authorization is granted.
    """
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        raise ValueError("existing regular evidence directory required")
    for path in directory.iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("regular evidence files required")
    expected = _expected(training, picks, first_months)
    recorder = AttemptRecorder(directory)
    bindings = []
    referenced = set()
    for path in sorted(directory.glob("*.finished.json")):
        run_id = path.name[:-14]
        payload = recorder.journal._read(run_id, "finished")["payload"]
        identity = {k: v for k, v in payload.items() if k not in ("error", "evidence")}
        matches = [
            (role, score)
            for role, (want, score) in expected.items()
            if json.dumps(identity, sort_keys=True) == json.dumps(want, sort_keys=True)
        ]
        if len(matches) != 1:
            raise ValueError("unexpected or duplicate attempt semantics")
        role, score = matches[0]
        if score is not None and score.run_id != run_id:
            raise ValueError("training score belongs to another attempt")
        if payload["error"] is not None or payload["evidence"] is None:
            raise ValueError("completed menu contains an engine failure")
        metadata = payload["evidence"]
        try:
            reason = _artifact(directory, metadata, identity, score, first_months)
        except (KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError("malformed artifact fields") from exc
        referenced.add(metadata["path"])
        bindings.append(
            EvidenceBinding(
                role,
                run_id,
                metadata["path"],
                metadata["sha256"],
                metadata["bytes"],
                metadata["records"],
                reason,
            )
        )
        del expected[role]
    if expected:
        raise ValueError("missing expected attempts")
    if {p.name for p in directory.glob("*.evidence.jsonl")} != referenced:
        raise ValueError("orphan evidence artifact")
    return tuple(sorted(bindings, key=lambda b: b.role))
