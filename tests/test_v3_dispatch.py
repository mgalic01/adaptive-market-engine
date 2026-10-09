"""Synthetic composition: never load historical archives or run a strategy."""

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    import v3_dispatch as module

    root = tmp_path / "checkout"
    root.mkdir()
    inventory = tmp_path / "inventory"
    inventory.mkdir()
    output = tmp_path / "invocation"
    snapshot = SimpleNamespace(
        root=root, revision="1" * 40, trial_id="v3", code_sha256="2" * 64, files=()
    )
    documents = SimpleNamespace(
        trial_id="v3",
        revision="1" * 40,
        code_sha256="2" * 64,
        completion_id="complete",
        registration_id="registered",
        manifest_sha256="3" * 64,
        config_sha256="4" * 64,
        spec_sha256="5" * 64,
        code_commit="6" * 40,
    )
    task = dict(
        schema_version=1,
        trial_id="v3",
        code_sha256="2" * 64,
        manifest_sha256="3" * 64,
        config_sha256="4" * 64,
        inventory_root=str(inventory.resolve()),
        output_root=str(output.resolve()),
        owner_approval_reference="synthetic owner decision",
        review_reference="synthetic review",
    )
    raw = json.dumps(task).encode()
    calls = []
    monkeypatch.setattr(module, "_git", lambda *args: raw)
    monkeypatch.setattr(module, "recheck_runtime", lambda s: calls.append("recheck"))
    monkeypatch.setattr(module, "read_registered_documents", lambda *args: documents)
    fields = (
        "spot_bars",
        "first_months",
        "spot_hourly",
        "hold_hourly",
        "futures_hourly",
        "spot_filters",
        "futures_filters",
        "funding",
        "futures_exclusions",
        "spot_exclusions",
    )
    inputs = SimpleNamespace(**{name: object() for name in fields})
    monkeypatch.setattr(
        module, "load_inventory_inputs", lambda *args: calls.append("load") or object()
    )
    monkeypatch.setattr(
        module, "bind_registered_inputs", lambda *args: SimpleNamespace(inputs=inputs)
    )
    report = SimpleNamespace(selection=SimpleNamespace(quarters=()))

    def run(**kwargs):
        calls.append(("run", kwargs))
        kwargs["directory"].mkdir()
        return report

    monkeypatch.setattr(module, "run_experiment", run)
    monkeypatch.setattr(module, "reconcile_experiment_evidence", lambda *args: ())
    monkeypatch.setattr(
        module, "publish_experiment_report", lambda *args: SimpleNamespace(receipt_sha256="7" * 64)
    )
    return module, snapshot, inventory, output, raw, inputs, calls


def invoke(prepared):
    module, snapshot, inventory, output, raw, _, _ = prepared
    return module.dispatch_registered(
        snapshot,
        inventory_root=inventory,
        output_root=output,
        execution_task="docs/tasks/synthetic.json",
        execution_task_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_exact_once_mapping_and_uncertified_receipt(prepared):
    _, _, _, output, _, inputs, calls = prepared
    result = invoke(prepared)
    runs = [c[1] for c in calls if isinstance(c, tuple)]
    assert len(runs) == 1
    for field, value in vars(inputs).items():
        assert runs[0][field] is value
    assert runs[0]["directory"] == output / "attempts"
    assert result == "7" * 64
    end = json.loads((output / "finished.json").read_bytes())
    assert end["status"] == "diagnostics_published_uncertified"
    assert end["verdict"] is None
    assert end["publication_receipt_sha256"] == "7" * 64


@pytest.mark.parametrize(
    "damage", ["task_hash", "task_trial", "task_output", "completion", "runtime", "existing"]
)
def test_rejection_before_market_input(prepared, monkeypatch, damage):
    module, _, _, output, raw, _, calls = prepared
    if damage.startswith("task_"):
        task = json.loads(raw)
        if damage == "task_trial":
            task["trial_id"] = "wrong"
        elif damage == "task_output":
            task["output_root"] = "wrong"
        else:
            task["extra"] = True
        monkeypatch.setattr(module, "_git", lambda *args: json.dumps(task).encode())
    elif damage == "existing":
        output.mkdir()
    else:

        def reject(*args):
            raise ValueError("rejected")

        monkeypatch.setattr(
            module,
            "read_registered_documents" if damage == "completion" else "recheck_runtime",
            reject,
        )
    with pytest.raises((ValueError, FileExistsError)):
        invoke(prepared)
    assert "load" not in calls
    assert not any(isinstance(c, tuple) for c in calls)


@pytest.mark.parametrize("stage", ["load", "run", "reconcile", "publish", "interrupt"])
def test_failure_preserved_and_no_retry(prepared, monkeypatch, stage):
    module, _, _, output, _, _, calls = prepared

    def fail(*args, **kwargs):
        if stage == "interrupt":
            raise KeyboardInterrupt()
        raise ValueError("synthetic failure")

    target = {
        "load": "load_inventory_inputs",
        "run": "run_experiment",
        "reconcile": "reconcile_experiment_evidence",
        "publish": "publish_experiment_report",
        "interrupt": "run_experiment",
    }[stage]
    monkeypatch.setattr(module, target, fail)
    with pytest.raises((ValueError, KeyboardInterrupt)):
        invoke(prepared)
    assert (output / "started.json").is_file()
    end = json.loads((output / "finished.json").read_bytes())
    assert end["status"] == ("interrupted" if stage == "interrupt" else "failed")
    assert end["verdict"] is None
    with pytest.raises(FileExistsError):
        invoke(prepared)


def test_post_publication_recheck_failure_preserves_receipt_pin(prepared, monkeypatch):
    module, _, _, output, _, _, _ = prepared
    checks = 0

    def recheck(_):
        nonlocal checks
        checks += 1
        if checks == 4:
            raise ValueError("post-publication drift")

    monkeypatch.setattr(module, "recheck_runtime", recheck)
    with pytest.raises(ValueError, match="drift"):
        invoke(prepared)
    end = json.loads((output / "finished.json").read_bytes())
    assert end["publication_receipt_sha256"] == "7" * 64
    assert end["status"] == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("trial_id", "foreign"),
        ("code_sha256", "0" * 64),
        ("manifest_sha256", "0" * 64),
        ("config_sha256", "0" * 64),
        ("schema_version", True),
        ("review_reference", ""),
        ("owner_approval_reference", None),
        ("extra", True),
    ],
)
def test_hash_matching_task_still_requires_exact_contract(prepared, monkeypatch, field, value):
    module, snapshot, inventory, output, raw, _, calls = prepared
    task = json.loads(raw)
    task[field] = value
    changed = json.dumps(task).encode()
    monkeypatch.setattr(module, "_git", lambda *args: changed)
    with pytest.raises(ValueError, match="task does not match"):
        module.dispatch_registered(
            snapshot,
            inventory_root=inventory,
            output_root=output,
            execution_task="docs/tasks/synthetic.json",
            execution_task_sha256=hashlib.sha256(changed).hexdigest(),
        )
    assert "load" not in calls
    assert not output.exists()


@pytest.mark.parametrize("location", ["checkout", "inventory", "contains_inventory"])
def test_output_location_cannot_change_runtime_or_input(prepared, location):
    module, snapshot, inventory, _, raw, _, calls = prepared
    output = {
        "checkout": snapshot.root / "out",
        "inventory": inventory / "out",
        "contains_inventory": inventory.parent,
    }[location]
    with pytest.raises(ValueError, match="separate"):
        module.dispatch_registered(
            snapshot,
            inventory_root=inventory,
            output_root=output,
            execution_task="docs/tasks/synthetic.json",
            execution_task_sha256=hashlib.sha256(raw).hexdigest(),
        )
    assert "load" not in calls


def test_unwritable_terminal_record_preserves_partial_invocation(prepared, monkeypatch):
    module, _, _, output, _, _, _ = prepared
    original = module._write

    def fail(path, raw):
        if path.name == "finished.json":
            path.write_bytes(b"partial")
            raise OSError("synthetic disk failure")
        original(path, raw)

    monkeypatch.setattr(module, "_write", fail)
    with pytest.raises(OSError):
        invoke(prepared)
    assert (output / "finished.json").read_bytes() == b"partial"
    assert (output / "started.json").is_file()
    with pytest.raises(FileExistsError):
        invoke(prepared)


def test_fresh_isolated_bootstrap_imports_real_dispatcher(tmp_path):
    import os
    import subprocess

    from test_trial_register import candidate, completion, encode
    from test_v3_runtime_preflight import git
    from trial_register import code_digest

    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "registered"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    for name, raw in {
        "docs/spec.md": b"spec\n",
        "config/run.json": b"{}\n",
        "config/manifest.json": b"{}\n",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic spec")
    registration = candidate()
    registration["payload"]["spec"].update(
        commit=git(root, "rev-parse", "HEAD"), sha256=hashlib.sha256(b"spec\n").hexdigest()
    )
    register = root / "docs/trials/register.jsonl"
    register.parent.mkdir()
    register.write_bytes(encode(registration))
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic registration")
    names = git(source, "ls-files", "src", "scripts").splitlines()
    names.append("scripts/v3_dispatch.py")
    implementation = {name: (source / name).read_bytes() for name in set(names)}
    for name, raw in implementation.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic implementation")
    done = completion()
    done["payload"].update(
        code_commit=git(root, "rev-parse", "HEAD"),
        code_paths=sorted(implementation),
        code_sha256=code_digest(implementation),
    )
    for name in ("config", "manifest"):
        done["payload"][name]["sha256"] = hashlib.sha256(b"{}\n").hexdigest()
    register.write_bytes(encode(registration, done))
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic completion")
    revision = git(root, "rev-parse", "HEAD")
    code = f"""
import importlib.util, sys
from pathlib import Path
root = Path({str(root)!r})
spec = importlib.util.spec_from_file_location(
    'v3_runtime_preflight', root/'scripts/v3_runtime_preflight.py')
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)
snapshot = runtime.preflight_runtime(root, 'v3', {revision!r})
import v3_dispatch
runtime.recheck_runtime(snapshot)
print('DISPATCH_IMPORT_OK')
"""
    result = subprocess.run(
        [os.environ.get("V3_PREFLIGHT_TEST_PYTHON", sys.executable), "-I", "-S", "-B", "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "DISPATCH_IMPORT_OK"
