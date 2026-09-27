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
    assert m.validate(body, signed(body), "pull_request", SECRET) == 91
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


def test_daily_budget_allows_40_starts_and_survives_restart(tmp_path):
    path = tmp_path / "queue.sqlite"
    q = module().Queue(path)
    for i in range(40):
        # More than ten minutes apart: the separate six/hour limit is respected.
        now = i * 601
        q.add(payload(number=i + 1), i + 1, now)
        batch = q.claim(now + 30)
        assert batch is not None, f"start {i + 1} should fit the owner's daily allowance"
        q.finish(batch[0], "failed" if i % 2 else "completed", "")
    q = module().Queue(path)
    q.add(payload(number=41), 41, 40 * 601)
    assert q.claim(40 * 601 + 30) is None
    assert q.claim(86429) is None
    assert q.claim(86430) is not None  # First start ages out of the rolling window.


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


def test_discussion_fingerprint_includes_earlier_worker_reports():
    worker()
    from local_worker_github import MARKER, discussion_digest

    s = ready_snapshot()
    original = discussion_digest(s)
    s["comments"].append({"user": {"login": "mgalic01"}, "body": MARKER + "report"})
    assert discussion_digest(s) != original
    original = discussion_digest(s)
    s["comments"][-1]["body"] += "New blocking finding"
    assert discussion_digest(s) != original
    s["comments"].append({"user": {"login": "mgalic01"}, "body": "Critical defect"})
    assert discussion_digest(s) != original


@pytest.mark.parametrize(
    "restricted_path",
    [
        "data/2025-01.csv",
        "tests/fixtures/2025-01.csv",
        "prices.parquet",
        "docs/raw-prices.json",
        "tests/fixtures/observations.py",
    ],
)
def test_partial_patch_and_data_tree_abort_before_content(monkeypatch, restricted_path):
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
            "tree": [{"type": "blob", "path": restricted_path, "sha": path[10]}],
        }

    api = GitHub()
    monkeypatch.setattr(api, "request", request)
    with pytest.raises(ValueError, match="data or unclassified changes"):
        api.snapshot(1)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "changed,complete,expected",
    [(False, True, "READY"), (True, True, "STALE"), (False, False, "BLOCKED")],
)
def test_worker_report_binds_recommendation_to_reviewed_base_and_head(
    tmp_path, monkeypatch, changed, complete, expected
):
    import copy
    import subprocess

    m = worker()
    s = ready_snapshot()
    s["pr"]["number"] = 91
    s["complete"] = complete
    monkeypatch.setattr(m, "evidence", lambda _: copy.deepcopy(s))
    current = copy.deepcopy(s)
    if changed:
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
    m.run_batch(q, q.claim(30), tmp_path, "dummy.exe", True)
    assert q.status()["runs"][0][1] == "completed"
    assert len(posts) == 1
    if changed:
        assert "discussion changed" in posts[0][2]
    elif not complete:
        assert "Evidence incomplete" in posts[0][2]
    assert f"recommendation: {expected}" in posts[0][2]
    report = (tmp_path / "run-1" / "report.md").read_text(encoding="utf-8")
    assert report == posts[0][2]
    assert f"head **{'a' * 40}**" in report
    assert f"base **{'b' * 40}**" in report
    assert "invalid if either the head or base changes" in report


def test_queue_closes_connections_and_rolls_back(tmp_path):
    import sqlite3

    q = module().Queue(tmp_path / "queue.sqlite")
    with pytest.raises(RuntimeError), q.connect() as db:
        db.execute("INSERT INTO events VALUES ('dummy',1,0,NULL)")
        raise RuntimeError("simulated failure")
    assert q.status()["pending"] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_service_lock_rejects_second_owner(tmp_path):
    with worker().service_lock(tmp_path), pytest.raises(OSError), worker().service_lock(tmp_path):
        pytest.fail("second service must not acquire the lock")


def test_completed_checks_wake_one_pr_and_own_comments_do_not():
    body = payload(action="completed", check_suite={"pull_requests": [{"number": 94}]})
    assert module().validate(body, signed(body), "check_suite", SECRET) == 94
    body = payload(
        action="created",
        issue={"number": 94, "pull_request": {}},
        comment={"body": "<!-- codex-local-worker -->\nreport"},
    )
    assert module().validate(body, signed(body), "issue_comment", SECRET) is None


def test_no_automatic_merge_interface():
    import inspect

    m = worker()
    assert not hasattr(m.GitHub, "merge")
    assert "allow_merge" not in inspect.signature(m.run_batch).parameters
    with pytest.raises(ValueError, match="only read or publish"):
        m.GitHub().request("pulls/1/merge", "PUT", {"sha": "a" * 40})


def test_ancestry_blocks_unreviewed_merge_base_before_patches(monkeypatch):
    worker()
    from local_worker_github import GitHub

    api = GitHub()
    calls = []

    def request(path):
        calls.append(path)
        assert path.startswith("git/commits/")
        return {"parents": []}

    monkeypatch.setattr(api, "request", request)
    with pytest.raises(ValueError, match="ancestry"):
        api.require_ancestor("b" * 40, "a" * 40)
    assert calls == ["git/commits/" + "a" * 40]
    monkeypatch.setattr(api, "request", lambda _: {"parents": [{"sha": "b" * 40}]})
    api.require_ancestor("b" * 40, "a" * 40)


def test_json_publication_header(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import local_worker_github

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(
                (
                    self.headers.get("Content-Type"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(local_worker_github, "API", f"http://127.0.0.1:{server.server_port}/")
    try:
        local_worker_github.GitHub("dummy").request("issues/1/comments", "POST", {"body": "review"})
        assert seen[0][0] == "application/json"
        assert json.loads(seen[0][1]) == {"body": "review"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_run_directory_collision_is_terminal_and_preserves_files(tmp_path):
    m = worker()
    q = module().Queue(tmp_path / "queue.sqlite")
    q.add(payload(), 91, 0)
    batch = q.claim(30)
    run = tmp_path / f"run-{batch[0]}"
    run.mkdir()
    report = run / "report.md"
    report.write_text("preserve me")
    m.run_batch(q, batch, tmp_path, "dummy.exe")
    assert q.status()["runs"][0][1] == "failed"
    assert report.read_text() == "preserve me"


def test_report_write_failure_still_finishes_queue(tmp_path, monkeypatch):
    m = worker()
    q = module().Queue(tmp_path / "queue.sqlite")
    q.add(payload(), 91, 0)
    monkeypatch.setattr(m, "evidence", lambda _: {})

    def fail(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "write_text", fail)
    m.run_batch(q, q.claim(30), tmp_path, "dummy.exe")
    assert q.status()["runs"][0][1] == "failed"


def test_publication_neutralizes_task_trigger_and_rejects_oversize(monkeypatch):
    import re

    from local_worker_github import GitHub

    api = GitHub("dummy")
    calls = []

    def request(path, method="GET", body=None):
        calls.append((path, method, body))
        return {"state": "open", "head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}}

    monkeypatch.setattr(api, "request", request)
    text = "Quoted trigger:\n/bob-run docs/tasks/2026-09-27-bob-example.md\n@bob @codex review"
    api.comment(1, text, "a" * 40, "b" * 40)
    body = calls[-1][2]["body"]
    assert not re.search(r"(^|\s)/bob-run\s+docs/tasks/[A-Za-z0-9._-]+\.md", body)
    assert "@" not in body
    calls.clear()
    with pytest.raises(ValueError, match="oversized"):
        api.comment(1, "Finding. " * 3000, "a" * 40, "b" * 40)
    assert calls == []


@pytest.mark.parametrize("last_change", [None, "base", "head", "state"])
def test_worker_rechecks_identity_immediately_before_publication(
    tmp_path, monkeypatch, last_change
):
    import copy
    import subprocess

    m = worker()
    snapshot = ready_snapshot()
    snapshot["pr"]["number"] = 91
    monkeypatch.setenv("LOCAL_WORKER_GITHUB_TOKEN", "dummy")
    monkeypatch.setattr(m, "evidence", lambda _: copy.deepcopy(snapshot))
    monkeypatch.setattr(m.GitHub, "snapshot", lambda *_: copy.deepcopy(snapshot))
    latest_pr = copy.deepcopy(snapshot["pr"])
    if last_change == "state":
        latest_pr["state"] = "closed"
    elif last_change:
        latest_pr[last_change]["sha"] = "c" * 40
    calls = []

    def request(self, path, method="GET", body=None):
        calls.append((path, method, body))
        if method == "GET":
            assert path == "pulls/91"
            return latest_pr
        assert path == "issues/91/comments" and method == "POST"
        return {}

    monkeypatch.setattr(m.GitHub, "request", request)

    def run(args, **kwargs):
        out = Path(args[args.index("--output-last-message") + 1])
        out.write_text(
            json.dumps(
                {
                    "number": 91,
                    "head": "a" * 40,
                    "verdict": "READY",
                    "review": "Synthetic review with no findings. " * 8,
                }
            )
        )
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    q = module().Queue(tmp_path / "queue.sqlite")
    q.add(payload(), 91, 0)
    m.run_batch(q, q.claim(30), tmp_path, "dummy.exe", True)
    if last_change:
        assert calls == [("pulls/91", "GET", None)]
        assert q.status()["runs"][0][1] == "failed"
        assert "publishing review comment" in (tmp_path / "run-1" / "failure.md").read_text()
    else:
        assert [method for _, method, _ in calls] == ["GET", "POST"]
        assert q.status()["runs"][0][1] == "completed"
        assert "recommendation: READY" in calls[-1][2]["body"]
    assert (tmp_path / "run-1" / "report.md").is_file()


def test_check_and_status_changes_invalidate_fingerprint():
    from local_worker_github import discussion_digest

    s = ready_snapshot()
    old = discussion_digest(s)
    s["checks"][0]["conclusion"] = "failure"
    assert discussion_digest(s) != old
    old = discussion_digest(s)
    s["statuses"].append({"context": "extra", "state": "pending"})
    assert discussion_digest(s) != old


def test_worker_start_requires_read_token(tmp_path, monkeypatch):
    m = worker()
    secret = tmp_path / "secret"
    secret.write_bytes(SECRET)
    monkeypatch.delenv("LOCAL_WORKER_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(m.shutil, "which", lambda _: "dummy.exe")
    monkeypatch.setattr(m, "server", lambda *a: pytest.fail("must reject before listening"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "serve", "--state", str(tmp_path), "--secret-file", str(secret), "--run-worker"],
    )
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code == 2


def test_edits_to_earlier_worker_comment_queue_review():
    body = payload(
        action="edited",
        issue={"number": 94, "pull_request": {}},
        comment={"body": "<!-- codex-local-worker --> amended finding"},
    )
    assert module().validate(body, signed(body), "issue_comment", SECRET) == 94


def test_inspected_retry_uses_new_event_not_duplicate_delivery(tmp_path):
    q = module().Queue(tmp_path / "queue.sqlite")
    original = payload()
    q.add(original, 91, 0)
    run = q.claim(30)
    q.finish(run[0], "failed", "failure.md")
    assert not q.add(original, 91, 40)
    assert q.claim(70) is None
    fresh = payload(
        action="created",
        issue={"number": 91, "pull_request": {}},
        comment={"id": 123, "body": "Inspected run 1; request another review"},
    )
    assert module().validate(fresh, signed(fresh), "issue_comment", SECRET) == 91
    assert q.add(fresh, 91, 80)
    assert q.claim(110)[1] == [91]


def test_reviewable_path_allowlist():
    from local_worker_github import reviewable_path

    for path in [
        "src/crypto_grid_bot/app.py",
        "tests/test_app.py",
        "docs/LOCAL_WORKER.md",
        ".github/workflows/quality.yml",
        "requirements-dev.lock",
    ]:
        assert reviewable_path(path)
    for path in [
        "tests/data_prices.py",
        "config/market.json",
        "src/fixtures/observations.py",
        "prices.csv",
        "data/README.md",
    ]:
        assert not reviewable_path(path)
