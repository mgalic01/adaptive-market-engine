"""Fixed GitHub API operations and conservative, independently checked merge gates."""

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from local_worker_queue import REPO, REPO_ID

API = f"https://api.github.com/repos/{REPO}/"
MARKER = "<!-- codex-local-worker -->"
SHA = re.compile(r"[0-9a-f]{40}\Z")
# These changes require owner decisions beyond the standing routine-merge authority.
RESTRICTED = ("docs/tasks/", "config/", "data/", "docs/EXPERIMENT_SPEC", "docs/datasets/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("GitHub redirect refused")


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = token
        self.deadline = time.monotonic() + 90

    def request(self, path: str, method: str = "GET", body: Any = None) -> Any:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("GitHub operation deadline")
        immutable_compare = re.fullmatch(
            r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}\?per_page=1", path
        )
        if not re.fullmatch(r"[a-zA-Z0-9_/?=&.-]+", path) or (
            ".." in path and not immutable_compare
        ):
            raise ValueError("invalid GitHub path")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ame-local-worker"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS API origin
            API + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=min(20, remaining)
        ) as response:
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise ValueError("GitHub response too large")
            return json.loads(content)

    def pages(self, path: str) -> list[Any]:
        results: list[Any] = []
        for page in range(1, 6):
            data = self.request(f"{path}?per_page=100&page={page}")
            if not isinstance(data, list):
                raise ValueError("unexpected GitHub collection")
            results.extend(data)
            if len(data) < 100:
                return results
        raise ValueError("GitHub collection exceeds review bound")

    def snapshot(self, number: int) -> dict[str, Any]:
        if type(number) is not int or number <= 0:
            raise ValueError("invalid PR")
        pr = self.request(f"pulls/{number}")
        if pr["base"]["repo"]["id"] != REPO_ID or not SHA.fullmatch(pr["head"]["sha"]):
            raise ValueError("unexpected repository/head")
        head = pr["head"]["sha"]
        # Tree metadata contains paths/hashes, not file content. Reject reserved/data scope
        # before requesting patches or blobs, including renames out of restricted paths.
        trees = []
        for sha in (pr["base"]["sha"], head):
            if not SHA.fullmatch(sha):
                raise ValueError("invalid base/head")
            tree = self.request(f"git/trees/{sha}?recursive=1")
            if tree.get("truncated"):
                raise ValueError("tree metadata truncated")
            trees.append({e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"})
        for path in set(trees[0]) | set(trees[1]):
            if path.startswith(("data/", "docs/datasets/")) and trees[0].get(path) != trees[1].get(
                path
            ):
                raise ValueError("data changes require owner-directed review")
        comparison = self.request(f"compare/{pr['base']['sha']}...{head}?per_page=1")
        files = comparison["files"]
        if len(files) != pr["changed_files"] or len(files) > 30:
            raise ValueError("immutable diff coverage incomplete or too large")
        comments = self.pages(f"issues/{number}/comments")
        reviews = self.pages(f"pulls/{number}/reviews")
        inline = self.pages(f"pulls/{number}/comments")
        checks = self.request(f"commits/{head}/check-runs?per_page=100&filter=latest")
        statuses = self.request(f"commits/{head}/status?per_page=100")
        if checks["total_count"] > 100 or statuses["total_count"] > 100:
            raise ValueError("check list truncated")
        # GitHub can omit patches for binary/large files. Never infer they were reviewed.
        complete = all(patch_complete(f) for f in files) and len(files) <= 30
        if complete:
            for file in files:
                if not SHA.fullmatch(file.get("sha", "")):
                    complete = False
                    break
                blob = self.request(f"git/blobs/{file['sha']}")
                if blob.get("encoding") != "base64" or blob.get("size", 0) > 100000:
                    complete = False
                    break
                file["contents"] = base64.b64decode(blob["content"]).decode("utf-8")
        try:
            protection = self.request("branches/main/protection")
        except urllib.error.HTTPError as exc:
            if exc.code not in {403, 404}:
                raise
            protection = {}
        result = {
            "pr": pr,
            "files": files,
            "comments": comments,
            "reviews": reviews,
            "inline": inline,
            "checks": checks["check_runs"],
            "statuses": statuses["statuses"],
            "complete": complete,
            "protection": protection,
        }
        # Limit the whole prompt too, rather than silently truncating evidence.
        if len(json.dumps(result)) > 250_000:
            raise ValueError("PR exceeds bounded review size; desktop review required")
        return result

    def comment(self, number: int, body: str) -> None:
        if not self.token:
            raise ValueError("publication requires local GitHub token")
        current = self.request(f"pulls/{number}")
        if current["state"] != "open":
            raise ValueError("PR closed before publication")
        # Never forward mention triggers returned by the model.
        safe = body.replace("@", "＠")[:16000]
        self.request(f"issues/{number}/comments", "POST", {"body": MARKER + "\n" + safe})

    def merge(self, number: int, head: str) -> dict[str, Any]:
        if not self.token or not SHA.fullmatch(head):
            raise ValueError("merge requires credential and full head")
        result: dict[str, Any] = self.request(
            f"pulls/{number}/merge", "PUT", {"sha": head, "merge_method": "merge"}
        )
        return result


def merge_blocks(snapshot: dict[str, Any], verdict: str) -> list[str]:
    """No model can override these gates. Snapshot always comes from GitHub, not model output."""
    pr = snapshot["pr"]
    head = pr["head"]["sha"]
    blocks = []
    if verdict != "READY":
        blocks.append("Codex review did not find this ready")
    if pr["state"] != "open" or pr.get("draft") or pr["base"]["ref"] != "main":
        blocks.append("PR must be open, non-draft, targeting main")
    if pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
        blocks.append("GitHub does not report a clean merge")
    if pr["head"].get("repo", {}).get("id") != REPO_ID:
        blocks.append("fork PR requires desktop review")
    if not snapshot["complete"]:
        blocks.append("incomplete/large patch requires desktop review")
    if any(
        f.get(key, "").startswith(RESTRICTED)
        for f in snapshot["files"]
        for key in ("filename", "previous_filename")
    ):
        blocks.append("owner-gated task/config/data/spec changes require desktop review")
    paths = {f["filename"] for f in snapshot["files"]}
    if "docs/reviews/README.md" not in paths or not any(
        p.startswith("docs/reviews/") and p.endswith(".md") and p != "docs/reviews/README.md"
        for p in paths
    ):
        blocks.append("missing indexed durable handoff in this PR")
    protection = snapshot.get("protection", {})
    required = protection.get("required_status_checks", {}) or {}
    contexts = set(required.get("contexts", []))
    contexts.update(c["context"] for c in required.get("checks", []))
    if (
        not required.get("strict")
        or "test-and-audit" not in contexts
        or not protection.get("enforce_admins", {}).get("enabled")
    ):
        blocks.append("strict base checks enforced for admins are required for unattended merge")
    # Protocol/strategy proposals must not turn an AI verdict into three-agent agreement.
    if "proposal" in pr.get("title", "").lower() or "agreement" in pr.get("title", "").lower():
        blocks.append("proposal/agreement requires explicit desktop coordination")
    checks = snapshot["checks"]
    if not any(c["name"] == "test-and-audit" for c in checks):
        blocks.append("missing test-and-audit")
    if any(c.get("status") != "completed" or c.get("conclusion") != "success" for c in checks):
        blocks.append("one or more checks are pending or not successful")
    if any(s.get("state") != "success" for s in snapshot["statuses"]):
        blocks.append("one or more commit statuses are not successful")
    # Conservative: any current-head inline finding needs a desktop resolution check.
    if any(
        c.get("original_commit_id") == head or c.get("commit_id") == head
        for c in snapshot["inline"]
    ):
        blocks.append("current-head inline findings need desktop resolution verification")
    if any(r.get("state") == "CHANGES_REQUESTED" for r in snapshot["reviews"]):
        blocks.append("a changes-requested review is present")
    bob: str | None = None
    claude: str | None = None
    for comment in sorted(snapshot["comments"], key=lambda c: c["created_at"]):
        body = comment["body"].replace("**", "").replace("`", "")
        author = comment["user"]["login"]
        if author == "github-actions[bot]" and "IBM Bob" in body:
            bob = None
            match = re.search(
                r"^VERDICT: (NO ISSUES|FLAGGED) at " + head + r"(?:\s+-[^\n]*)?\s*$",
                body,
                re.M,
            )
            if match and "SCOPE:" in body and len(body) >= 200:
                bob = match[1]
        if author == "claude[bot]":
            claude = None
            match = re.search(r"^Verdict: (APPROVE|CHANGES NEEDED)\s*$", body, re.M | re.I)
            reviewed_head = re.search(r"Reviewed at head\s+" + head + r"\b", body, re.I)
            if match and reviewed_head and len(body) >= 200:
                claude = match[1].upper()
    if bob != "NO ISSUES":
        blocks.append("missing substantive Bob NO ISSUES at current full head")
    if claude != "APPROVE":
        blocks.append("missing substantive automated Claude APPROVE at current full head")
    return blocks


def patch_complete(file: dict[str, Any]) -> bool:
    patch = file.get("patch")
    if not isinstance(patch, str) or file.get("changes", 0) >= 2000:
        return False
    lines = patch.splitlines()
    return bool(
        sum(line.startswith("+") for line in lines) == file["additions"]
        and sum(line.startswith("-") for line in lines) == file["deletions"]
    )


def discussion_digest(snapshot: dict[str, Any]) -> str:
    """Changed discussions invalidate a verdict; only our own report is excluded."""
    comments = [
        c
        for c in snapshot["comments"]
        if not (c["user"]["login"] == "mgalic01" and c["body"].startswith(MARKER))
    ]
    value = {
        "comments": comments,
        "reviews": snapshot["reviews"],
        "inline": snapshot["inline"],
        "title": snapshot["pr"].get("title"),
        "body": snapshot["pr"].get("body"),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
