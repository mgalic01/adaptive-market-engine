"""Offline evidence checks: an ancestor is not necessarily a recorded main head."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_bob_revision.py"
SHA = "5fd961cace769bdfda9eed2fb5c86316247648e7"
OLD = "807ed6dfa8c1c88ea0a5778f21a058efbe1f13e7"
REPO = "mgalic01/adaptive-market-engine"
REPO_ID = "1384347674"
START = f"https://api.github.com/repos/{REPO}/activity?ref=refs%2Fheads%2Fmain&per_page=100"
NEXT = f"https://api.github.com/repositories/{REPO_ID}/activity?ref=refs%2Fheads%2Fmain&per_page=100&after=cursor"
CUTOFF = "2026-10-10T16:00:00Z"


def test_verifier_entrypoint_exists():
    assert SCRIPT.is_file(), "activity evidence verifier is missing"


@pytest.fixture
def verifier():
    assert SCRIPT.is_file(), "activity evidence verifier is missing"
    spec = importlib.util.spec_from_file_location("verify_bob_revision", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recorded():
    return json.loads((ROOT / "tests/fixtures/bob-main-activity.json").read_text())


def transport(pages):
    """Only the external HTTP boundary is replaced; unknown calls fail the test."""

    def get(url):
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    return get


def verify(module, pages, revision=SHA, cutoff=CUTOFF):
    return module.verify_revision(REPO, REPO_ID, revision, cutoff, transport(pages))


def test_recorded_merge_accepts_exact_requested_sha(verifier, recorded):
    assert verify(verifier, {START: (recorded, "")}) == SHA


def test_only_after_on_main_is_evidence(verifier, recorded):
    for change in (
        {"after": "a" * 40},
        {"ref": "refs/heads/other"},
        {"activity_type": "branch_creation"},
    ):
        rows = [{**recorded[0], **change}]
        with pytest.raises(verifier.Rejected):
            verify(verifier, {START: (rows, "")})


def test_push_head_is_evidence_but_future_activity_is_not(verifier, recorded):
    rows = [{**recorded[0], "activity_type": "push"}]
    assert verify(verifier, {START: (rows, "")}) == SHA
    with pytest.raises(verifier.Rejected):
        verify(verifier, {START: (rows, "")}, cutoff="2026-10-10T14:00:00Z")


def test_recorded_old_head_can_be_on_second_page(verifier, recorded):
    assert (
        verify(
            verifier,
            {START: ([recorded[0]], f'<{NEXT}>; rel="next"'), NEXT: ([recorded[1]], "")},
            OLD,
        )
        == OLD
    )


@pytest.mark.parametrize("bad", [None, {}, "oops", [None], [{}], [{"after": SHA}]])
def test_malformed_payload_fails_closed(verifier, bad):
    with pytest.raises(verifier.Rejected):
        verify(verifier, {START: (bad, "")})


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("after", 3),
        ("before", "short"),
        ("ref", None),
        ("timestamp", "tomorrow"),
        ("activity_type", 9),
    ],
)
def test_malformed_record_rejects_even_after_match(verifier, recorded, field, value):
    with pytest.raises(verifier.Rejected):
        verify(verifier, {START: ([recorded[0], {**recorded[1], field: value}], "")})


def test_missing_or_unavailable_evidence_rejects(verifier):
    for payload in (([], ""), OSError("unavailable"), TimeoutError("timeout")):
        with pytest.raises(verifier.Rejected):
            verify(verifier, {START: payload})


def test_later_page_failure_without_matching_evidence_rejects(verifier, recorded):
    for payload in (({}, ""), OSError("429")):
        with pytest.raises(verifier.Rejected):
            verify(verifier, {START: ([recorded[1]], f'<{NEXT}>; rel="next"'), NEXT: payload})


def test_valid_evidence_does_not_require_unrelated_older_pages(verifier, recorded):
    assert verify(verifier, {START: ([recorded[0]], f'<{NEXT}>; rel="next"')}) == SHA


@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.example/activity>; rel="next"',
        '<http://api.github.com/repos/mgalic01/adaptive-market-engine/activity>; rel="next"',
        '<https://api.github.com/repositories/999/activity>; rel="next"',
        '<https://api.github.com/repos/someone/else/activity>; rel="next"',
        f'<{START}>; rel="next"',
        "nonsense",
        f'<{NEXT}>; rel="next", <{NEXT}>; rel="next"',
        f'<{NEXT}&ref=refs%2Fheads%2Fother>; rel="next"',
    ],
)
def test_unsafe_or_looping_pagination_rejects(verifier, recorded, link):
    with pytest.raises(verifier.Rejected):
        verify(verifier, {START: ([recorded[1]], link)})


def test_pagination_limit_rejects_without_silent_partial_success(verifier, recorded):
    pages = {}
    url = START
    for i in range(20):
        following = NEXT + str(i)
        pages[url] = ([{**recorded[1], "id": i + 1}], f'<{following}>; rel="next"')
        url = following
    with pytest.raises(verifier.Rejected):
        verify(verifier, pages)


def test_fast_forward_intermediate_is_rejected_despite_first_parent_membership(
    verifier, recorded, tmp_path
):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    revisions = []
    for text in ("base", "unapproved intermediate", "reviewed pushed head"):
        (tmp_path / "task.md").write_text(text)
        git("add", "task.md")
        git("commit", "-m", text)
        revisions.append(git("rev-parse", "HEAD"))
    a, b, c = revisions
    assert b in git("rev-list", "--first-parent", "main").splitlines()
    rows = [{**recorded[0], "before": a, "after": c, "activity_type": "push"}]
    with pytest.raises(verifier.Rejected):
        verify(verifier, {START: (rows, "")}, b)
    assert verify(verifier, {START: (rows, "")}, c) == c


def test_dispatch_checks_run_event_and_repository_identity(verifier, recorded, monkeypatch):
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "REPOSITORY_ID": REPO_ID,
        "REVISION": SHA,
        "GH_TOKEN": "test",
        "EVENT": "workflow_dispatch",
        "GITHUB_RUN_ID": "42",
    }.items():
        monkeypatch.setenv(key, value)
    run_url = f"https://api.github.com/repos/{REPO}/actions/runs/42"
    for mutation in ({"event": "push"}, {"repository": {"id": 999}}):
        run = {
            "id": 42,
            "created_at": CUTOFF,
            "event": "workflow_dispatch",
            "repository": {"id": int(REPO_ID)},
            **mutation,
        }
        get = transport({run_url: (run, ""), START: (recorded, "")})
        monkeypatch.setattr(verifier, "api_page", lambda url, token, get=get: get(url))
        assert verifier.main() == 1


def test_manual_entrypoint_never_falls_back_on_evidence_failure(verifier, monkeypatch):
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "REPOSITORY_ID": REPO_ID,
        "REVISION": SHA,
        "GH_TOKEN": "test",
        "EVENT": "issue_comment",
        "COMMENT_CREATED_AT": CUTOFF,
    }.items():
        monkeypatch.setenv(key, value)

    def unavailable(url, token):
        raise urllib.error.HTTPError(url, 403, "denied", Message(), None)

    monkeypatch.setattr(verifier, "api_page", unavailable)
    assert verifier.main() == 1


@pytest.mark.parametrize("event", ["issue_comment", "workflow_dispatch"])
def test_entrypoint_accepts_recorded_revision_for_both_manual_triggers(
    verifier, recorded, monkeypatch, capsys, event
):
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "REPOSITORY_ID": REPO_ID,
        "REVISION": SHA,
        "GH_TOKEN": "test",
        "EVENT": event,
        "COMMENT_CREATED_AT": CUTOFF,
        "GITHUB_RUN_ID": "42",
    }.items():
        monkeypatch.setenv(key, value)
    run = {
        "id": 42,
        "created_at": CUTOFF,
        "event": "workflow_dispatch",
        "repository": {"id": int(REPO_ID)},
    }
    get = transport(
        {
            START: (recorded, ""),
            f"https://api.github.com/repos/{REPO}/actions/runs/42": (run, ""),
        }
    )
    monkeypatch.setattr(verifier, "api_page", lambda url, token: get(url))
    assert verifier.main() == 0
    assert capsys.readouterr().out.strip() == f"Verified requested main-head revision: {SHA}"


@pytest.mark.parametrize(
    "body,status",
    [
        (b"invalid JSON", 200),
        (b"[]", 500),
        (b"x" * 2_000_001, 200),
        (b'{"after":"a","after":"b"}', 200),
    ],
    ids=["json", "status", "size", "duplicate-keys"],
)
def test_http_transport_rejects_invalid_responses(verifier, monkeypatch, body, status):
    class Response(io.BytesIO):
        headers = Message()

    response = Response(body)
    response.status = status

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == START and timeout == 10
            return response

    monkeypatch.setattr(verifier.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError):
        verifier.api_page(START, "test")


def test_redirect_handler_refuses_even_same_host(verifier):
    with pytest.raises(verifier.Rejected):
        verifier.NoRedirect().redirect_request(None, None, 302, "redirect", {}, START)


def test_workflow_manual_gate_runs_in_trusted_resolve_checkout():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/bob-task.yml").read_text())
    job = workflow["jobs"]["resolve"]
    checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert "if" not in checkouts[0]
    assert checkouts[0]["with"]["ref"] == "${{ github.workflow_sha }}"
    gate = next(s for s in job["steps"] if s.get("id") == "evidence")
    assert gate["env"]["REVISION"] == "${{ steps.list.outputs.revision }}"
    assert "verify_bob_revision.py" in gate["run"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
