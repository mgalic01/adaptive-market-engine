"""Synthetic serialized evidence only: never dispatch a replay or read market data."""

import hashlib
import json
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Context, localcontext
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.evidence_journal import EvidenceJournal
from crypto_grid_bot.trend.evidence_writer import _write_rows
from crypto_grid_bot.trend.orchestration import TrainingScore
from crypto_grid_bot.trend.walk_forward import RULES

FIRST = {"BTCUSDT": "2023-04"}
START = month_bounds_ms("2024-10")[0]
TRAIN = month_bounds_ms("2023-04")[0]
END = month_bounds_ms("2025-01")[0]
HOUR = 3600000


def rows(identity):
    phase = identity["phase"]
    start, end = identity["start_ms"], identity["end_ms_exclusive"]
    if phase in ("spot_hold", "full_size_hold"):
        header = {"initial": D(10000), "cost_multiple": identity["cost_multiple"]}
        if phase == "spot_hold":
            header["stopped"] = "completed"
        else:
            header.update(
                start_ms=start,
                end_ms_exclusive=end,
                scheduled_ms=start + HOUR,
                budgets={"BTCUSDT": D(10000)},
                reason=None,
                missing_symbols=[],
            )
        yield ("spot_account" if phase == "spot_hold" else phase), header
        yield "spot_audit", {"cash_residual": D(0), "quantity_residuals": {}}
    else:
        yield (
            "outcome",
            {"reason": None, "trade_reconciliation_residual": D(0), "close_requirements": []},
        )
        yield (
            "account",
            {
                "initial": D(10000),
                "multiple": identity["multiple"],
                "cost_multiple": identity["cost_multiple"],
                "stopped": "completed",
            },
        )
        yield "audit", {"wallet_residual": D(0), "quantity_residuals": {}, "equity_residual": D(0)}
    for stamp, kind in ((start, "open"), (start + HOUR, "open"), (end, "terminal")):
        yield (
            "equity",
            {
                "timestamp_ms": stamp,
                "kind": kind,
                "equity": D(10000),
                "peak": D(10000),
                "drawdown": D(0),
            },
        )
    yield "sample", (start + HOUR, D(10000))
    yield "sample", (end, D(10000))


def publish(directory, run_id, identity, evidence_rows=None):
    journal = EvidenceJournal(directory)
    journal.record(run_id, "started", identity)
    metadata = _write_rows(
        directory, run_id, iter(rows(identity) if evidence_rows is None else evidence_rows)
    )
    journal.record(run_id, "finished", {**identity, "error": None, "evidence": metadata})


def futures(phase, rule=None, start=START, end=END, multiple=2, cost=1):
    return dict(
        phase=phase,
        rule=rule,
        start_ms=start,
        end_ms_exclusive=end,
        multiple=multiple,
        cost_multiple=cost,
        pick_schedule=[[start, rule or "R1"]],
    )


def menu(directory):
    training = []
    for index, rule in enumerate(RULES):
        run_id = f"train-{index}"
        publish(directory, run_id, futures("training", rule, TRAIN, START))
        training.append(TrainingScore(run_id, "2024-10", rule, D(0), None))
    publish(directory, "main", futures("out_of_sample"))
    for multiple, cost in ((1, 1), (3, 1), (1, 2), (2, 2), (3, 2)):
        publish(
            directory,
            f"stress-{multiple}-{cost}",
            futures("sensitivity", multiple=multiple, cost=cost),
        )
    for rule in RULES:
        publish(directory, f"fixed-{rule}", futures("fixed_rule", rule))
    for cost in (1, 2):
        publish(
            directory,
            f"spot-{cost}",
            dict(phase="spot_hold", start_ms=START, end_ms_exclusive=END, cost_multiple=cost),
        )
    publish(
        directory,
        "hold",
        dict(phase="full_size_hold", start_ms=START, end_ms_exclusive=END, cost_multiple=1),
    )
    return training


def test_exact_menu_returns_deterministic_byte_bindings(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    bindings = reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)
    assert len(bindings) == 33
    assert [b.role for b in bindings] == sorted(b.role for b in bindings)
    by_role = {b.role: b for b in bindings}
    assert by_role["training/2024-10/R1"].run_id == "train-0"
    assert by_role["main"].run_id == "main"
    assert by_role["full_size_hold"].reason is None
    assert all(len(b.sha256) == 64 and b.bytes > 0 and b.records > 0 for b in bindings)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def rewrite_rows(directory, run_id, change):
    path = directory / f"{run_id}.evidence.jsonl"
    evidence = [json.loads(line) for line in path.read_bytes().splitlines()]
    change(evidence)
    raw = b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in evidence)
    path.write_bytes(raw)
    finish = directory / f"{run_id}.finished.json"
    doc = json.loads(finish.read_bytes())
    doc["payload"]["evidence"].update(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), records=len(evidence)
    )
    finish.write_text(json.dumps(doc), encoding="utf-8")


def value(evidence, kind):
    return next(row["value"] for row in evidence if row["kind"] == kind)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: value(e, "account").update(initial="9999"),
        lambda e: value(e, "account").update(multiple=3),
        lambda e: value(e, "account").update(cost_multiple=2),
        lambda e: value(e, "account").update(stopped="liquidation"),
        lambda e: value(e, "outcome").update(reason="unknown"),
        lambda e: value(e, "outcome").update(trade_reconciliation_residual="0.1"),
        lambda e: value(e, "audit").update(wallet_residual="1"),
        lambda e: value(e, "equity").update(timestamp_ms=TRAIN + 1),
        lambda e: value(e, "equity").update(equity="9999"),
        lambda e: value(e, "sample").__setitem__(1, "10001"),
        lambda e: e.append(e[0]),
        lambda e: e.append(dict(schema=1, kind="active_lifecycle", value={})),
        lambda e: e.append(
            dict(schema=1, kind="decision", value={"timestamp_ms": TRAIN, "rule": "R2"})
        ),
    ],
)
def test_rehashed_training_artifact_semantic_tampering_rejected(tmp_path, mutation):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    rewrite_rows(tmp_path, "train-0", mutation)
    with pytest.raises(ValueError):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_training_score_is_recomputed_not_merely_ranked(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    training[0] = replace(training[0], sharpe=D(1))
    with pytest.raises(ValueError, match="Sharpe"):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_known_invalid_and_unavailable_diagnostic_remain_distinct(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    training[1] = replace(training[1], sharpe=None, invalid_reason="liquidation")

    def invalidate(evidence):
        value(evidence, "outcome")["reason"] = "liquidation"
        value(evidence, "account")["stopped"] = "liquidation"

    rewrite_rows(tmp_path, "train-1", invalidate)
    rewrite_rows(
        tmp_path,
        "hold",
        lambda e: value(e, "full_size_hold").update(
            reason="unavailable_first_purchase", missing_symbols=["BTCUSDT"]
        ),
    )
    bindings = reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)
    reasons = {b.role: b.reason for b in bindings}
    assert reasons["training/2024-10/R2"] == "liquidation"
    assert reasons["full_size_hold"] == "unavailable_first_purchase"


@pytest.mark.parametrize(
    "field,new",
    [
        ("multiple", 3),
        ("cost_multiple", True),
        ("start_ms", TRAIN + 1),
        ("rule", "R2"),
        ("pick_schedule", [[TRAIN, "R2"]]),
    ],
)
def test_consistently_rewritten_journal_settings_rejected(tmp_path, field, new):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    for state in ("started", "finished"):
        path = tmp_path / f"train-0.{state}.json"
        doc = json.loads(path.read_bytes())
        doc["payload"][field] = new
        path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "pending", "failed", "orphan", "hash"])
def test_incomplete_or_corrupt_menu_rejected(tmp_path, damage):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    if damage == "missing":
        for path in tmp_path.glob("spot-2.*"):
            path.unlink()
    elif damage == "duplicate":
        publish(tmp_path, "duplicate", futures("out_of_sample"))
    elif damage == "pending":
        (tmp_path / "main.finished.json").unlink()
    elif damage == "failed":
        path = tmp_path / "main.finished.json"
        doc = json.loads(path.read_bytes())
        doc["payload"]["error"] = "EngineFailure: deliberate synthetic failure"
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "orphan":
        _write_rows(tmp_path, "orphan", iter(rows(futures("out_of_sample"))))
    else:
        with (tmp_path / "main.evidence.jsonl").open("ab") as source:
            source.write(b"\n")
    with pytest.raises(ValueError):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_valid_nonzero_score_uses_frozen_decimal_context(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)

    def growing(evidence):
        evidence[:] = [row for row in evidence if row["kind"] not in ("sample", "equity")]
        for stamp, kind, amount in (
            (TRAIN, "open", "10000"),
            (TRAIN + HOUR, "open", "10000"),
            (TRAIN + 25 * HOUR, "open", "11000"),
            (START, "terminal", "13200"),
        ):
            evidence.append(
                dict(
                    schema=1,
                    kind="equity",
                    value=dict(
                        timestamp_ms=stamp, kind=kind, equity=amount, peak=amount, drawdown="0"
                    ),
                )
            )
            if stamp != TRAIN:
                evidence.append(dict(schema=1, kind="sample", value=[stamp, amount]))

    rewrite_rows(tmp_path, "train-0", growing)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        expected = D(".15") / D(".005").sqrt() * D(365).sqrt()
    training[0] = replace(training[0], sharpe=expected)
    with localcontext(Context(prec=6)):
        bindings = reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)
    assert len(bindings) == 33


@pytest.mark.parametrize(
    "run_id,kind,update",
    [
        ("spot-1", "spot_account", {"cost_multiple": 2}),
        ("spot-1", "spot_account", {"stopped": "engine_failure"}),
        ("stress-1-1", "account", {"multiple": 2}),
        ("hold", "full_size_hold", {"scheduled_ms": START}),
        ("hold", "full_size_hold", {"budgets": {"BTCUSDT": "9000"}}),
        ("hold", "full_size_hold", {"reason": "unavailable_first_purchase"}),
    ],
)
def test_nontraining_account_metadata_crosschecked(tmp_path, run_id, kind, update):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    rewrite_rows(tmp_path, run_id, lambda e: value(e, kind).update(update))
    with pytest.raises(ValueError):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_same_read_hash_detects_change_after_initial_validation(tmp_path, monkeypatch):
    from crypto_grid_bot.trend import evidence_reconciliation as module

    training = menu(tmp_path)
    original = module.AttemptRecorder

    def change_after_check(directory):
        result = original(directory)
        path = directory / "main.evidence.jsonl"
        path.write_bytes(path.read_bytes().replace(b'"initial":"10000"', b'"initial": "10000"'))
        return result

    monkeypatch.setattr(module, "AttemptRecorder", change_after_check)
    with pytest.raises(ValueError, match="changed while reconciling"):
        module.reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_missing_directory_is_not_created(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="existing"):
        reconcile_experiment_evidence(missing, [], {}, FIRST)
    assert not missing.exists()


def test_accepted_audit_rounding_bound_and_ignored_rows(tmp_path):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)

    def amend(evidence):
        value(evidence, "audit")["equity_residual"] = "1e-18"
        evidence.extend(
            dict(schema=1, kind="event", value={"opaque": "x" * 1000}) for _ in range(1000)
        )

    rewrite_rows(tmp_path, "train-0", amend)
    assert len(reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)) == 33


@pytest.mark.parametrize("damage", ["score_id", "reason", "terminal", "audit_missing"])
def test_training_binding_and_finalization_required(tmp_path, damage):
    from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence

    training = menu(tmp_path)
    if damage == "score_id":
        training[0], training[1] = (
            replace(training[0], run_id="train-1"),
            replace(training[1], run_id="train-0"),
        )
    elif damage == "reason":
        training[1] = replace(training[1], sharpe=None, invalid_reason="liquidation")
    elif damage == "terminal":
        rewrite_rows(
            tmp_path,
            "train-0",
            lambda e: next(
                row["value"]
                for row in e
                if row["kind"] == "equity" and row["value"]["kind"] == "terminal"
            ).update(timestamp_ms=START - 1),
        )
    else:
        rewrite_rows(
            tmp_path,
            "train-0",
            lambda e: e.__setitem__(slice(None), [row for row in e if row["kind"] != "audit"]),
        )
    with pytest.raises(ValueError):
        reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)


def test_reader_rejects_oversized_row_after_integrity_check(tmp_path, monkeypatch):
    from crypto_grid_bot.trend import evidence_reconciliation as module

    training = menu(tmp_path)
    monkeypatch.setattr(module, "LIMIT", 32)
    with pytest.raises(ValueError, match="row length"):
        module.reconcile_experiment_evidence(tmp_path, training, {START: "R1"}, FIRST)
