"""Reject corrupt or rewritten experiment history rather than silently losing trials."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from trial_register import load_events, validate_append  # noqa: E402


def record(event_id="old"):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "trial_id": "v0",
        "event_type": "retrospective",
        "recorded_at": "2026-10-08T17:00:00Z",
        "agent": "Codex Desktop",
        "family": "grid",
        "parent_trial_id": None,
        "sources": ["docs/backtests/source.md"],
        "payload": {
            "preregistered": False,
            "scope": "recorded trials only",
            "missing_fields": ["exact trial count"],
            "outcome": "see source",
        },
    }


def encode(*events):
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def test_valid_history_and_append(tmp_path):
    old = encode(record())
    new = old + encode(record("next"))
    path = tmp_path / "register.jsonl"
    path.write_bytes(new)
    assert [e["event_id"] for e in load_events(path)] == ["old", "next"]
    validate_append(old, new)


@pytest.mark.parametrize(
    "data",
    [
        b"{}\n",
        b"\n",
        b"{",
        b"[]\n",
        b'{"event_id":"a","event_id":"b"}\n',
        encode(record()).replace(b"false", b"NaN"),
        encode(record()).replace(b"false", b"1e999"),
        encode(record()) + b"\n",
        encode(record()).rstrip(b"\n"),
    ],
)
def test_malformed_history_is_rejected(tmp_path, data):
    path = tmp_path / "register.jsonl"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="line"):
        load_events(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("recorded_at", "2026-10-08"),
        ("event_type", "unknown"),
        ("sources", []),
        ("event_id", " "),
        ("payload", {}),
    ],
)
def test_invalid_fields(tmp_path, field, value):
    event = record()
    event[field] = value
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(event))
    with pytest.raises(ValueError):
        load_events(path)


def test_retrospective_cannot_claim_preregistration(tmp_path):
    event = record()
    event["payload"]["preregistered"] = True
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(event))
    with pytest.raises(ValueError):
        load_events(path)


def test_duplicate_ids_rejected(tmp_path):
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(record(), record()))
    with pytest.raises(ValueError, match="line 2"):
        load_events(path)


@pytest.mark.parametrize(
    "replacement", [b"", encode(record("changed")), encode(record("next"), record())]
)
def test_history_cannot_be_deleted_reordered_or_rewritten(replacement):
    with pytest.raises(ValueError):
        validate_append(encode(record()), replacement)


def candidate():
    event = record("registered")
    event.update(trial_id="v3", event_type="registration")
    event["payload"] = {
        "preregistered": True,
        "hypothesis": "directional edge",
        "spec": {"path": "docs/spec.md", "commit": "a" * 40, "sha256": "b" * 64},
        "candidates": ["R1-long"],
        "sizes": [1, 2, 3],
        "fees": "spec section 5",
        "folds": "18/3 months",
        "mask": "spec section 2",
        "seeds": [],
        "budget": "fixed candidate grid",
        "stopping": "all declared folds",
        "selection": "train Sharpe",
        "data": None,
        "code": None,
    }
    return event


def completion():
    event = record("completed")
    event.update(trial_id="v3", event_type="completion")
    event["payload"] = {
        "registration_id": "registered",
        "code_commit": "c" * 40,
        "code_sha256": "d" * 64,
        "code_paths": ["src/engine.py"],
        "manifest": {"path": "config/manifest.json", "sha256": "e" * 64},
        "config": {"path": "config/run.json", "sha256": "f" * 64},
        "review": "https://github.com/example/project/pull/1#review",
    }
    return event


def result_event():
    event = record("result")
    event.update(trial_id="v3", event_type="result")
    event["payload"] = {
        "completion_id": "completed",
        "run_id": "run-1",
        "status": "failed",
        "provenance": "run log",
        "report": "failure report",
        "metrics": {},
        "reason": "worker terminated",
    }
    return event


def test_valid_registration_completion_and_failed_result(tmp_path):
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(candidate(), completion(), result_event()))
    assert len(load_events(path)) == 3


@pytest.mark.parametrize(
    "events",
    [
        [completion()],
        [candidate(), result_event()],
        [completion(), candidate()],
        [candidate(), candidate()],
        [candidate(), completion(), completion()],
    ],
)
def test_wrong_stage_or_duplicate_events_rejected(tmp_path, events):
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(*events))
    with pytest.raises(ValueError):
        load_events(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("code_commit", "short"),
        ("code_sha256", "z" * 64),
        ("code_paths", ["../escape"]),
        ("registration_id", "missing"),
        ("review", ""),
    ],
)
def test_completion_rejects_invalid_pins(tmp_path, field, value):
    event = completion()
    event["payload"][field] = value
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(candidate(), event))
    with pytest.raises(ValueError):
        load_events(path)


def test_result_cannot_reference_another_trial(tmp_path):
    event = result_event()
    event["trial_id"] = "another"
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(candidate(), completion(), event))
    with pytest.raises(ValueError):
        load_events(path)


def test_duplicate_run_id_rejected_even_with_new_event_id(tmp_path):
    event = result_event()
    event["event_id"] = "another-result"
    path = tmp_path / "register.jsonl"
    path.write_bytes(encode(candidate(), completion(), result_event(), event))
    with pytest.raises(ValueError):
        load_events(path)


@pytest.mark.parametrize("change", ["modify", "add", "late-registration"])
def test_ready_requires_committed_completion_and_matching_blobs(tmp_path, change):
    import hashlib
    import subprocess

    from trial_register import check_ready, code_digest

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args]).decode().strip()

    git("init")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "test@example.invalid")
    for name, content in {
        "docs/spec.md": b"spec\n",
        "config/manifest.json": b"{}\n",
        "config/run.json": b"{}\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if change == "late-registration":
        (tmp_path / "src").mkdir()
        (tmp_path / "src/engine.py").write_bytes(b"pass\n")
    git("add", ".")
    git("commit", "-m", "frozen spec and inputs")
    code = git("rev-parse", "HEAD")
    reg = candidate()
    reg["payload"]["spec"].update(commit=code, sha256=hashlib.sha256(b"spec\n").hexdigest())
    path = tmp_path / "docs/trials/register.jsonl"
    path.parent.mkdir(parents=True)
    if change != "late-registration":
        path.write_bytes(encode(reg))
        git("add", ".")
        git("commit", "-m", "candidate registration")
        (tmp_path / "src").mkdir()
        (tmp_path / "src/engine.py").write_bytes(b"pass\n")
        git("add", ".")
        git("commit", "-m", "synthetic implementation")
        code = git("rev-parse", "HEAD")
    done = completion()
    done["payload"].update(code_commit=code, code_sha256=code_digest({"src/engine.py": b"pass\n"}))
    for key in ("manifest", "config"):
        done["payload"][key]["sha256"] = hashlib.sha256(b"{}\n").hexdigest()
    path.write_bytes(encode(reg, done))
    git("add", ".")
    with pytest.raises(ValueError):
        check_ready(tmp_path, "v3", code)
    git("commit", "-m", "registration")
    ready = git("rev-parse", "HEAD")
    if change == "late-registration":
        with pytest.raises(ValueError, match="registration"):
            check_ready(tmp_path, "v3", ready)
        return
    assert check_ready(tmp_path, "v3", ready)["event_id"] == "completed"
    (tmp_path / ("src/engine.py" if change == "modify" else "src/new.py")).write_bytes(b"changed\n")
    git("add", ".")
    git("commit", "-m", "unregistered code change")
    with pytest.raises(ValueError, match="code"):
        check_ready(tmp_path, "v3", git("rev-parse", "HEAD"))
    assert check_ready(tmp_path, "v3", ready)["event_id"] == "completed"


def test_atomic_append_preserves_history_on_invalid_event(tmp_path):
    from trial_register import append_event

    path = tmp_path / "register.jsonl"
    append_event(path, record())
    before = path.read_bytes()
    with pytest.raises(ValueError):
        append_event(path, record())
    assert path.read_bytes() == before
    append_event(path, record("next"))
    assert path.read_bytes().startswith(before)
    assert len(load_events(path)) == 2


def test_append_refuses_concurrent_writer(tmp_path):
    from trial_register import append_event

    path = tmp_path / "register.jsonl"
    path.with_suffix(".jsonl.lock").write_text("another writer")
    with pytest.raises(ValueError, match="lock"):
        append_event(path, record())
    assert not path.exists()


def test_correction_preserves_target(tmp_path):
    from trial_register import append_event

    path = tmp_path / "register.jsonl"
    append_event(path, record())
    event = record("correction")
    event["event_type"] = "correction"
    event["payload"] = {
        "target_id": "old",
        "reason": "incorrect scope",
        "details": "source establishes narrower scope",
    }
    append_event(path, event)
    assert load_events(path)[0] == record()
    event["event_id"] = "bad-correction"
    event["payload"]["target_id"] = "missing"
    with pytest.raises(ValueError):
        append_event(path, event)


def test_cli_validate_and_append(tmp_path, capsys):
    from trial_register import main

    path = tmp_path / "register.jsonl"
    event = tmp_path / "event.json"
    event.write_text(json.dumps(record()), encoding="utf-8")
    assert main(["append", "--register", str(path), "--event", str(event)]) == 0
    assert main(["validate", "--register", str(path)]) == 0
    assert main(["append", "--register", str(path), "--event", str(event)]) == 1
    assert "duplicate" in capsys.readouterr().err


def test_registered_v3_bootstrap_seed_matches_frozen_spec():
    events = load_events(Path(__file__).resolve().parents[1] / "docs/trials/register.jsonl")
    registration = next(e for e in reversed(events) if e["event_type"] == "registration")
    assert registration["payload"]["seeds"] == [20261008]
