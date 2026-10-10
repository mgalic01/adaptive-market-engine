"""One registered invocation; imported only after explicit-file runtime preflight.

Task/reference checks bind declared inputs, not authenticated owner approval.
The operator must establish reviewed execution authorization before calling.
No network, retries, canonical register writes or final acceptance verdict.
"""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from trial_register import _digest, _object, _path, read_registered_documents
from v3_inventory_loader import load_inventory_inputs
from v3_registered_inputs import bind_registered_inputs
from v3_report_publication import publish_experiment_report
from v3_runtime_preflight import RuntimeSnapshot, _git, recheck_runtime

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.evidence_reconciliation import reconcile_experiment_evidence
from crypto_grid_bot.trend.experiment_runner import run_experiment


def _write(path: Path, raw: bytes) -> None:
    with path.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def dispatch_registered(
    snapshot: RuntimeSnapshot,
    *,
    inventory_root: Path,
    output_root: Path,
    execution_task: str,
    execution_task_sha256: str,
) -> str:
    """Publish uncertified diagnostics once, preserving every partial invocation.

    A RuntimeSnapshot or committed task is not permission. Caller first establishes
    external approval and boots a fresh -I -S -B process by explicit checker path.
    Any exception after output creation requires inspection, never rerunning.
    """
    recheck_runtime(snapshot)
    documents = read_registered_documents(snapshot.root, snapshot.trial_id, snapshot.revision)
    _path(execution_task)
    _digest(execution_task_sha256, 64)
    raw = _git(snapshot.root, "show", f"{snapshot.revision}:{execution_task}")
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != execution_task_sha256:
        raise ValueError("execution task hash or size mismatch")
    task = json.loads(raw, object_pairs_hook=_object)
    inventory = inventory_root.resolve()
    output = output_root.resolve()
    if (
        inventory.is_relative_to(snapshot.root)
        or output.is_relative_to(snapshot.root)
        or output.is_relative_to(inventory)
        or inventory.is_relative_to(output)
    ):
        raise ValueError("invocation and inventory must be separate from each other and checkout")
    expected = dict(
        schema_version=1,
        trial_id=documents.trial_id,
        code_sha256=documents.code_sha256,
        manifest_sha256=documents.manifest_sha256,
        config_sha256=documents.config_sha256,
        inventory_root=str(inventory),
        output_root=str(output),
    )
    references = {"owner_approval_reference", "review_reference"}
    if (
        type(task) is not dict
        or set(task) != set(expected) | references
        or type(task["schema_version"]) is not int
        or any(task[k] != v for k, v in expected.items())
        or any(type(task[k]) is not str or not task[k].strip() for k in references)
    ):
        raise ValueError("execution task does not match registered invocation")
    output.mkdir(parents=True, exist_ok=False)
    identities = {
        name: getattr(documents, name)
        for name in (
            "trial_id",
            "revision",
            "registration_id",
            "completion_id",
            "code_commit",
            "code_sha256",
            "manifest_sha256",
            "config_sha256",
            "spec_sha256",
        )
    }
    _write(output / "execution-task.json", raw)
    _write(
        output / "started.json",
        _json(
            dict(
                identities=identities,
                execution_task=execution_task,
                execution_task_sha256=execution_task_sha256,
                inventory_root=str(inventory),
                output_root=str(output),
                approval_scope="operator_reviewed_references_not_authenticated",
                runtime_files=snapshot.files,
            )
        ),
    )
    receipt = None
    try:
        loaded = load_inventory_inputs(inventory, documents.manifest_sha256)
        bound = bind_registered_inputs(documents, loaded).inputs
        recheck_runtime(snapshot)
        report = run_experiment(
            directory=output / "attempts",
            spot_bars=bound.spot_bars,
            first_months=bound.first_months,
            spot_hourly=bound.spot_hourly,
            hold_hourly=bound.hold_hourly,
            futures_hourly=bound.futures_hourly,
            spot_filters=bound.spot_filters,
            futures_filters=bound.futures_filters,
            funding=bound.funding,
            futures_exclusions=bound.futures_exclusions,
            spot_exclusions=bound.spot_exclusions,
        )
        training = tuple(s for q in report.selection.quarters for s in q.training)
        picks = {month_bounds_ms(q.test_month)[0]: q.picked_rule for q in report.selection.quarters}
        bindings = reconcile_experiment_evidence(
            output / "attempts", training, picks, bound.first_months
        )
        binding_raw = _json([asdict(binding) for binding in bindings])
        _write(output / "bindings.json", binding_raw)
        recheck_runtime(snapshot)
        published = publish_experiment_report(output / "attempts", report, documents)
        receipt = published.receipt_sha256
        recheck_runtime(snapshot)
        _write(
            output / "finished.json",
            _json(
                dict(
                    status="diagnostics_published_uncertified",
                    verdict=None,
                    identities=identities,
                    publication_receipt_sha256=receipt,
                    bindings_sha256=hashlib.sha256(binding_raw).hexdigest(),
                )
            ),
        )
        return receipt
    except BaseException as exc:
        # A failed terminal write can itself leave partial metadata. Never replace it.
        if not (output / "finished.json").exists():
            _write(
                output / "finished.json",
                _json(
                    dict(
                        status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                        verdict=None,
                        identities=identities,
                        error=f"{type(exc).__name__}: {exc}",
                        publication_receipt_sha256=receipt,
                        recovery="inspect existing evidence; never automatically retry",
                    )
                ),
            )
        raise
