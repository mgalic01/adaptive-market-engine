"""Stream replay evidence before publishing a finished attempt record."""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crypto_grid_bot.trend.evidence_journal import (
    LIMIT,
    EvidenceJournal,
    _identity,
    _json_value,
    _object,
)
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import ReplayResult

if TYPE_CHECKING:
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.trend.filters import OrderFilters
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotRunner


def _value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (set, frozenset)):
        return [_value(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("evidence map keys must be strings")
        return {key: _value(item) for key, item in value.items()}
    return _json_value(value)


def replay_rows(result: ReplayResult) -> Iterator[tuple[str, Any]]:
    yield (
        "outcome",
        {
            "reason": result.reason,
            "trade_reconciliation_residual": result.trade_reconciliation_residual,
            "close_requirements": result.close_requirements,
        },
    )
    for stamp, rule, decision in result.daily_decisions:
        yield "decision", {"timestamp_ms": stamp, "rule": rule, "decision": decision}
    runner = result.runner
    if runner is None:
        return
    account = runner.account
    yield (
        "account",
        {
            "initial": account.initial,
            "wallet": account.wallet,
            "positions": account.positions,
            "cost_multiple": account.cost_multiple,
            "multiple": runner.multiple,
            "stopped": runner.stopped,
            "liquidation": account.liquidation,
            "masked_held_hours": runner.masked_held_hours,
        },
    )
    for kind, values in (
        ("event", account.events),
        ("fill", account.fills),
        ("funding", account.funding),
        ("hour", runner.hours),
        ("audit", runner.audits),
        ("equity", runner.equity_path),
        ("sample", runner.daily_samples),
        ("lifecycle", runner.lifecycles.completed),
    ):
        for value in values:
            yield kind, value
    for symbol, value in sorted(runner.lifecycles.active.items()):
        yield "active_lifecycle", {"symbol": symbol, "value": value}


def write_replay(directory: Path, run_id: str, result: ReplayResult) -> dict[str, Any]:
    return _write_rows(directory, run_id, replay_rows(result))


def spot_rows(runner: "SpotRunner") -> Iterator[tuple[str, Any]]:
    """Retain partial or completed spot evidence without asserting validity."""
    yield (
        "spot_account",
        {
            "initial": runner.account.initial,
            "cash": runner.account.cash,
            "holdings": runner.account.holdings,
            "cost_multiple": runner.account.cost_multiple,
            "stopped": runner.stopped,
            "close_requirements": runner.close_requirements,
            "masked_held_hours": runner.masked_held_hours,
        },
    )
    for stamp, decision in runner.daily_decisions:
        yield "spot_decision", {"timestamp_ms": stamp, "decision": decision}
    for receipt in runner.decision_inputs:
        yield "spot_input", receipt
    for kind, values in (
        ("spot_fill", runner.account.fills),
        ("spot_audit", runner.audits),
        ("spot_dispatch", runner.dispatches),
        ("spot_rebalance", runner.rebalances),
        ("spot_exclusion_dust", runner.exclusion_dust),
        ("equity", runner.equity_path),
        ("sample", runner.samples),
    ):
        for value in values:
            yield kind, value


def write_spot_replay(directory: Path, run_id: str, runner: "SpotRunner") -> dict[str, Any]:
    """Publish exact spot diagnostics; caller must separately journal the attempt."""
    return _write_rows(directory, run_id, spot_rows(runner))


def replay_spot_recorded(
    directory: Path,
    run_id: str,
    decisions: "HoldDecisions",
    filters: Mapping[str, "OrderFilters"],
    hourly: Mapping[str, Sequence["Kline"]],
    start_ms: int,
    end_ms_exclusive: int,
    *,
    cost_multiple: int = 1,
) -> "SpotRunner":
    """Journal a supplied spot replay; registered historical dispatch is upstream.

    Record completion does not mean strategy acceptance: the account's stopped
    reason and error must be inspected. Recording failures leave a pending start.
    KeyboardInterrupt leaves the start unfinished and never triggers a retry.
    """
    from crypto_grid_bot.trend.spot_benchmark import (
        SpotReplayExecutionError,
        replay_spot_benchmark,
    )

    recorder = AttemptRecorder(directory)
    identity = {
        "phase": "spot_hold",
        "start_ms": start_ms,
        "end_ms_exclusive": end_ms_exclusive,
        "cost_multiple": cost_multiple,
    }
    recorder.journal.record(run_id, "started", identity)
    try:
        runner = replay_spot_benchmark(
            decisions, filters, hourly, start_ms, end_ms_exclusive, cost_multiple=cost_multiple
        )
    except Exception as exc:
        evidence = (
            write_spot_replay(recorder.journal.directory, run_id, exc.runner)
            if isinstance(exc, SpotReplayExecutionError)
            else None
        )
        recorder.journal.record(
            run_id,
            "finished",
            {**identity, "error": f"{type(exc).__name__}: {exc}", "evidence": evidence},
        )
        raise
    evidence = write_spot_replay(recorder.journal.directory, run_id, runner)
    recorder.journal.record(run_id, "finished", {**identity, "error": None, "evidence": evidence})
    return runner


def _write_rows(directory: Path, run_id: str, rows: Iterator[tuple[str, Any]]) -> dict[str, Any]:
    _identity(run_id, "finished")
    filename = f"{run_id}.evidence.jsonl"
    digest = hashlib.sha256()
    count = size = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".evidence-", delete=False) as f:
            temporary = Path(f.name)
            for kind, value in rows:
                data = (
                    json.dumps(
                        {"schema": 1, "kind": kind, "value": _value(value)},
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                ).encode()
                if len(data) > LIMIT:
                    raise ValueError("evidence row exceeds size limit")
                f.write(data)
                digest.update(data)
                size += len(data)
                count += 1
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, directory / filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"path": filename, "sha256": digest.hexdigest(), "bytes": size, "records": count}


def verify_artifact(directory: Path, metadata: dict[str, Any]) -> None:
    """Stream-verify a published artifact; never trust a finish filename alone."""
    name = metadata.get("path")
    if not isinstance(name, str) or not name.endswith(".evidence.jsonl"):
        raise ValueError("invalid evidence path")
    _identity(name[:-15], "finished")
    digest_text = metadata.get("sha256")
    if not isinstance(digest_text, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_text):
        raise ValueError("invalid evidence digest")
    if any(type(metadata.get(key)) is not int or metadata[key] < 0 for key in ("bytes", "records")):
        raise ValueError("invalid evidence counts")
    actual = _inspect_artifact(directory, name)
    if any(actual[key] != metadata[key] for key in ("sha256", "records", "bytes")):
        raise ValueError("evidence digest or counts disagree")


def _inspect_artifact(directory: Path, name: str) -> dict[str, Any]:
    """Read framing and compute current bytes; does not certify replay completeness."""
    digest = hashlib.sha256()
    count = size = 0
    with (directory / name).open("rb") as source:
        while data := source.readline(LIMIT + 1):
            if len(data) > LIMIT or not data.endswith(b"\n"):
                raise ValueError("invalid evidence row length")
            row = json.loads(data, object_pairs_hook=_object)
            if (
                not isinstance(row, dict)
                or set(row) != {"schema", "kind", "value"}
                or type(row["schema"]) is not int
                or row["schema"] != 1
                or type(row["kind"]) is not str
            ):
                raise ValueError("invalid evidence row")
            _json_value(row)
            digest.update(data)
            count += 1
            size += len(data)
    if not count:
        raise ValueError("evidence has no rows")
    return {"path": name, "sha256": digest.hexdigest(), "bytes": size, "records": count}


def recover_interrupted(directory: Path, run_id: str, *, reason: str) -> None:
    """Explicitly record an unfinished attempt as an unconfirmed failure.

    Requires exclusive writer ownership and a caller-supplied diagnosis. An
    orphan artifact is retained with its current digest, never adopted as valid
    experiment evidence. This does not authorize a retry or historical dispatch.
    Malformed published artifacts remain blocked for separate investigation;
    temporary files are left untouched. A duplicate finish is never overwritten.
    """
    _identity(run_id, "finished")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("explicit recovery reason is required")
    journal = EvidenceJournal(directory)
    if run_id not in journal.pending():
        raise ValueError("recovery requires an unfinished attempt")
    start = journal._read(run_id, "started")["payload"]
    name = f"{run_id}.evidence.jsonl"
    artifact = journal.directory / name
    evidence = _inspect_artifact(journal.directory, name) if artifact.exists() else None
    journal.record(
        run_id,
        "finished",
        {
            **start,
            "error": f"InterruptedAttempt: outcome unconfirmed; {reason}",
            "evidence": evidence,
        },
    )


class AttemptRecorder:
    """Orchestration callback; records failures as failures, never as success.

    A publication/serialization failure propagates and leaves the start pending.
    Orphan artifacts are retained; retrying an existing artifact never overwrites it.
    """

    def __init__(self, directory: Path) -> None:
        self.journal = EvidenceJournal(directory)
        pending = self.journal.pending()
        for path in self.journal.directory.glob("*.finished.json"):
            run_id = path.name[:-14]
            start = self.journal._read(run_id, "started")["payload"]
            finish = self.journal._read(run_id, "finished")["payload"]
            if set(finish) != set(start) | {"error", "evidence"} or any(
                finish[key] != value for key, value in start.items()
            ):
                raise ValueError("finished attempt identity differs from start")
            evidence = finish["evidence"]
            if evidence is None:
                if (self.journal.directory / f"{run_id}.evidence.jsonl").exists():
                    raise ValueError("finished attempt has unreferenced published evidence")
                if not isinstance(finish["error"], str) or not finish["error"]:
                    raise ValueError("finished attempt lacks evidence or error")
            else:
                if not isinstance(evidence, dict) or evidence.get("path") != (
                    f"{run_id}.evidence.jsonl"
                ):
                    raise ValueError("finished evidence belongs to another attempt")
                verify_artifact(self.journal.directory, evidence)
        if pending:
            raise ValueError(f"unfinished attempts require explicit recovery: {', '.join(pending)}")

    def __call__(self, attempt: Attempt) -> None:
        _identity(attempt.run_id, attempt.state)
        identity = {
            name: getattr(attempt, name)
            for name in (
                "phase",
                "rule",
                "start_ms",
                "end_ms_exclusive",
                "multiple",
                "cost_multiple",
            )
        }
        identity["pick_schedule"] = [list(pick) for pick in attempt.pick_schedule]
        if attempt.state == "started":
            if attempt.result is not None or attempt.error is not None:
                raise ValueError("started attempt cannot have a result")
            self.journal.record(attempt.run_id, "started", identity)
            return
        if self.journal._read(attempt.run_id, "started")["payload"] != identity:
            raise ValueError("finished attempt identity differs from start")
        if attempt.result is None and attempt.error is None:
            raise ValueError("finished attempt requires a result or error")
        evidence = (
            None
            if attempt.result is None
            else write_replay(self.journal.directory, attempt.run_id, attempt.result)
        )
        self.journal.record(
            attempt.run_id,
            "finished",
            {
                **identity,
                "error": attempt.error,
                "evidence": evidence,
            },
        )
