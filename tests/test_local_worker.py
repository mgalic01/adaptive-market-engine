import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def module():
    assert importlib.util.find_spec("local_worker_queue"), "receiver/queue not implemented"
    import local_worker_queue

    return local_worker_queue


SECRET = b"test-only-secret-not-a-real-credential"


def payload(**changes):
    value = {
        "repository": {"id": 1384347674, "full_name": "mgalic01/adaptive-market-engine"},
        "sender": {"login": "mgalic01"},
        "action": "opened",
        "number": 91,
        "pull_request": {"number": 91},
    }
    value.update(changes)
    return json.dumps(value).encode()


def signed(body):
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def test_authenticate_before_parsing_and_reject_tamper():
    m = module()
    body = payload()
    assert m.validate(body, signed(body), "pull_request", SECRET) == 91
    for changed, signature in [(body + b" ", signed(body)), (body, ""), (b"{", "bad")]:
        with pytest.raises(ValueError):
            m.validate(changed, signature, "pull_request", SECRET)


@pytest.mark.parametrize("value", [[], None, 5, "text", {"repository": []}])
def test_malformed_signed_json_is_rejected(value):
    body = json.dumps(value).encode()
    with pytest.raises(ValueError):
        module().validate(body, signed(body), "pull_request", SECRET)


def test_pin_repository_sender_and_pr_event():
    m = module()
    for changes in [
        {"repository": {"id": 1, "full_name": m.REPO}},
        {"sender": {"login": "stranger"}},
        {"number": True, "pull_request": {"number": True}},
    ]:
        body = payload(**changes)
        with pytest.raises(ValueError):
            m.validate(body, signed(body), "pull_request", SECRET)
    body = payload(action="edited")
    assert m.validate(body, signed(body), "pull_request", SECRET) is None
    body = payload(action="created", issue={"number": 91})
    assert m.validate(body, signed(body), "issue_comment", SECRET) is None
    body = payload(action="created", issue={"number": 91, "pull_request": {}})
    assert m.validate(body, signed(body), "issue_comment", SECRET) == 91


def test_durable_dedup_debounce_and_budget(tmp_path):
    m = module()
    q = m.Queue(tmp_path / "queue.sqlite")
    assert q.add(payload(), 91, 0)
    assert not q.add(payload(), 91, 1)
    assert q.claim(29) is None
    batch = q.claim(30)
    assert batch and batch[1] == [91]
    q.finish(batch[0], "completed", "report.md")
    q = m.Queue(tmp_path / "queue.sqlite")
    assert not q.add(payload(), 91, 31)
    for i in range(1, 6):
        q.add(payload(number=i), i, i * 40)
        batch = q.claim(i * 40 + 30)
        assert batch
        q.finish(batch[0], "failed", "")
    q.add(payload(number=20), 20, 300)
    assert q.claim(400) is None
    assert q.claim(3700)


def test_claim_serializes_and_restart_does_not_repeat_uncertain_run(tmp_path):
    q = module().Queue(tmp_path / "queue.sqlite")
    q.add(payload(), 91, 0)
    batch = q.claim(30)
    assert batch
    q.add(payload(number=92), 92, 40)
    assert q.claim(90) is None
    q.recover()
    assert q.status()["runs"][0][1] == "interrupted"
    assert q.claim(90)[1] == [92]


def worker():
    assert importlib.util.find_spec("local_worker"), "worker not implemented"
    import local_worker

    return local_worker


def test_worker_command_is_isolated_and_has_no_payload_in_arguments(tmp_path):
    m = worker()
    args = m.command("codex.exe", tmp_path, tmp_path / "report.md")
    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "features.shell_tool=false" in args
    assert "features.apps=false" in args
    assert args[-1] == "-"
    env = m.child_environment({"PATH": "path", "Codex_token": "secret", "GH_TOKEN": "secret"})
    assert env == {"PATH": "path"}


def test_public_fetch_rejects_external_url_before_request():
    with pytest.raises(ValueError):
        worker().fetch("https://attacker.invalid/secret")


def test_real_http_rejects_unsigned_and_queues_once(tmp_path):
    import http.client
    import threading

    m = worker()
    q = module().Queue(tmp_path / "queue.sqlite")
    server = m.server(q, SECRET, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = payload()
        headers = {"Content-Type": "application/json", "X-GitHub-Event": "pull_request"}
        for sig, expected in [("wrong", 403), (signed(body), 202), (signed(body), 200)]:
            headers["X-Hub-Signature-256"] = sig
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            conn.request("POST", "/github", body, headers)
            response = conn.getresponse()
            assert response.status == expected
            response.read()
            conn.close()
        assert q.status()["pending"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_queue_capacity_preserves_existing_events(tmp_path):
    q = module().Queue(tmp_path / "queue.sqlite")
    with q.connect() as db:
        db.executemany("INSERT INTO events VALUES (?,1,0,NULL)", [(str(i),) for i in range(1000)])
    with pytest.raises(ValueError, match="queue full"):
        q.add(payload(), 91, 0)
    assert q.status()["pending"] == 1000


def test_run_requires_nonempty_report_and_handles_failure(tmp_path, monkeypatch):
    import subprocess

    m = worker()
    q = module().Queue(tmp_path / "queue.sqlite")
    monkeypatch.setattr(m, "evidence", lambda numbers: {"prs": numbers})
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    q.add(payload(), 91, 0)
    m.run_batch(q, q.claim(30), tmp_path, "dummy.exe")
    assert q.status()["runs"][0][1] == "failed"


def ready_snapshot():
    head = "a" * 40
    return {
        "pr": {
            "number": 1,
            "state": "open",
            "draft": False,
            "title": "Routine fix",
            "head": {"sha": head, "repo": {"id": 1384347674}},
            "base": {"ref": "main", "sha": "b" * 40},
            "mergeable": True,
            "mergeable_state": "clean",
        },
        "files": [
            {"filename": "src/example.py"},
            {"filename": "docs/reviews/README.md"},
            {"filename": "docs/reviews/example.md"},
        ],
        "complete": True,
        "inline": [],
        "reviews": [],
        "statuses": [],
        "checks": [{"name": "test-and-audit", "status": "completed", "conclusion": "success"}],
        "protection": {
            "required_status_checks": {"strict": True, "contexts": ["test-and-audit"]},
            "enforce_admins": {"enabled": True},
        },
        "comments": [
            {
                "created_at": "1",
                "user": {"login": "github-actions[bot]"},
                "body": "IBM Bob\n"
                + "Substantive evidence. " * 12
                + f"\nVERDICT: NO ISSUES at {head}\nSCOPE: read full diff",
            },
            {
                "created_at": "2",
                "user": {"login": "claude[bot]"},
                "body": f"Verdict: APPROVE\nReviewed at head {head}.\n" + "Evidence checked. " * 15,
            },
        ],
    }


def test_only_complete_current_agreement_is_mergeable():
    worker()
    from local_worker_github import merge_blocks

    s = ready_snapshot()
    assert merge_blocks(s, "READY") == []
    assert merge_blocks(s, "BLOCKED")
    s["comments"][0]["body"] = s["comments"][0]["body"].replace("a" * 40, "c" * 40)
    assert "Bob" in " ".join(merge_blocks(s, "READY"))


@pytest.mark.parametrize(
    "body",
    [
        "IBM Bob\nVERDICT: FLAGGED at "
        + "a" * 40
        + " - 1 concern(s), listed above\nSCOPE: "
        + "x" * 200,
        "IBM Bob: stop, this is wrong",
    ],
)
def test_new_bob_negative_invalidates_old_clean_verdict(body):
    worker()
    from local_worker_github import merge_blocks

    s = ready_snapshot()
    s["comments"].append(
        {"created_at": "3", "user": {"login": "github-actions[bot]"}, "body": body}
    )
    assert "Bob" in " ".join(merge_blocks(s, "READY"))


def test_new_claude_negative_and_sha_mentioned_outside_review_header_block():
    worker()
    from local_worker_github import merge_blocks

    s = ready_snapshot()
    s["comments"][-1]["body"] = s["comments"][-1]["body"].replace("Reviewed at head", "Mentioning")
    assert "Claude" in " ".join(merge_blocks(s, "READY"))
    s = ready_snapshot()
    s["comments"].append({"created_at": "3", "user": {"login": "claude[bot]"}, "body": "Stop"})
    assert "Claude" in " ".join(merge_blocks(s, "READY"))


@pytest.mark.parametrize("change", ["checks", "inline", "protection", "rename", "handoff", "draft"])
def test_merge_gate_failure_cases(change):
    worker()
    from local_worker_github import merge_blocks

    s = ready_snapshot()
    if change == "checks":
        s["checks"][0]["conclusion"] = "failure"
    elif change == "inline":
        s["inline"] = [{"commit_id": "a" * 40}]
    elif change == "protection":
        s["protection"] = {}
    elif change == "rename":
        s["files"][0]["previous_filename"] = "docs/tasks/task.md"
    elif change == "handoff":
        s["files"] = s["files"][:1]
    else:
        s["pr"]["draft"] = True
    assert merge_blocks(s, "READY")


def test_discussion_fingerprint_ignores_only_own_report():
    worker()
    from local_worker_github import MARKER, discussion_digest

    s = ready_snapshot()
    original = discussion_digest(s)
    s["comments"].append({"user": {"login": "mgalic01"}, "body": MARKER + "report"})
    assert discussion_digest(s) == original
    s["comments"].append({"user": {"login": "mgalic01"}, "body": "Critical defect"})
    assert discussion_digest(s) != original


def test_partial_patch_and_data_tree_abort_before_content(monkeypatch):
    worker()
    from local_worker_github import GitHub, patch_complete

    assert not patch_complete({"patch": "+one", "changes": 2, "additions": 2, "deletions": 0})
    assert patch_complete({"patch": "+one", "changes": 1, "additions": 1, "deletions": 0})
    s = ready_snapshot()
    s["pr"]["base"]["repo"] = {"id": 1384347674}
    calls = []

    def request(path):
        calls.append(path)
        if path.startswith("pulls/"):
            assert path == "pulls/1", "must not fetch files/patches after restricted tree"
            return s["pr"]
        return {
            "truncated": False,
            "tree": [{"type": "blob", "path": "data/2025-01.csv", "sha": path[10]}],
        }

    api = GitHub()
    monkeypatch.setattr(api, "request", request)
    with pytest.raises(ValueError, match="data changes"):
        api.snapshot(1)
    assert len(calls) == 3


def test_worker_report_success_and_changed_discussion_prevent_merge(tmp_path, monkeypatch):
    import copy
    import subprocess

    m = worker()
    s = ready_snapshot()
    s["pr"]["number"] = 91
    monkeypatch.setattr(m, "evidence", lambda _: copy.deepcopy(s))
    current = copy.deepcopy(s)
    current["comments"].append(
        {
            "created_at": "3",
            "user": {"login": "mgalic01"},
            "body": "New critical defect not reviewed",
        }
    )
    monkeypatch.setattr(m.GitHub, "snapshot", lambda *_: current)
    posts = []
    monkeypatch.setattr(m.GitHub, "comment", lambda *args: posts.append(args))
    monkeypatch.setattr(m.GitHub, "merge", lambda *_: pytest.fail("must not merge unread findings"))

    def run(args, **kwargs):
        out = Path(args[args.index("--output-last-message") + 1])
        out.write_text(
            json.dumps(
                {
                    "number": 91,
                    "head": "a" * 40,
                    "verdict": "READY",
                    "review": "Test review with no findings. " * 8,
                }
            )
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    q = module().Queue(tmp_path / "queue.sqlite")
    q.add(payload(), 91, 0)
    m.run_batch(q, q.claim(30), tmp_path, "dummy.exe", True, True)
    assert q.status()["runs"][0][1] == "completed"
    assert len(posts) == 1
    assert "discussion changed" in posts[0][-1]
