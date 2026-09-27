"""Fixed GitHub read/comment operations for a sceptical reviewer; no merge operation."""

import base64
import hashlib
import json
import re
import time
import urllib.request
from pathlib import PurePosixPath
from typing import Any

from local_worker_queue import REPO, REPO_ID

API = f"https://api.github.com/repos/{REPO}/"
MARKER = "<!-- codex-local-worker -->"
SHA = re.compile(r"[0-9a-f]{40}\Z")
RULES = ("docs/START_HERE.md", "AGENTS.md", "docs/AGENT_HANDOFF.md", "docs/reviews/README.md")


def reviewable_path(path: str) -> bool:
    """Conservative source/docs allowlist; fixtures/data are never inferred safe."""
    p = PurePosixPath(path)
    if any(
        part.lower() in {"data", "dataset", "datasets", "fixture", "fixtures"} for part in p.parts
    ):
        return False
    if path in {
        ".gitignore",
        "LICENSE",
        "pyproject.toml",
        "requirements.lock",
        "requirements-dev.lock",
    }:
        return True
    if p.suffix == ".md" and (len(p.parts) == 1 or path.startswith(("docs/", ".bob/skills/"))):
        return True
    if p.suffix == ".py":
        return path.startswith(("src/", "scripts/", ".bob/hooks/")) or (
            path.startswith("tests/") and (p.name.startswith("test_") or p.name == "conftest.py")
        )
    if path.startswith(".github/workflows/") and p.suffix in {".yml", ".yaml"}:
        return True
    return path.startswith("config/") and p.suffix == ".toml"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("GitHub redirect refused")


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = token
        self.deadline = time.monotonic() + 90

    def request(self, path: str, method: str = "GET", body: Any = None) -> Any:
        if method != "GET" and not (
            method == "POST" and re.fullmatch(r"issues/[0-9]+/comments", path)
        ):
            raise ValueError("worker may only read or publish review comments")
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
        if body is not None:
            headers["Content-Type"] = "application/json"
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
            if trees[0].get(path) != trees[1].get(path) and not reviewable_path(path):
                raise ValueError("data or unclassified changes require owner-directed review")
        # Three-dot patches must cover the same base as our content screening.
        # Reject outdated branches instead of inspecting an unknown merge-base diff.
        self.require_ancestor(pr["base"]["sha"], head)
        rules = {}
        for path in RULES:
            rules[path] = self.blob(trees[0][path])
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
                file["contents"] = self.blob(file["sha"])
        result = {
            "pr": pr,
            "files": files,
            "comments": comments,
            "reviews": reviews,
            "inline": inline,
            "checks": checks["check_runs"],
            "statuses": statuses["statuses"],
            "complete": complete,
            "base_rules": rules,
        }
        # Limit the whole prompt too, rather than silently truncating evidence.
        if len(json.dumps(result)) > 250_000:
            raise ValueError("PR exceeds bounded review size; desktop review required")
        return result

    def require_ancestor(self, base: str, head: str) -> None:
        pending = [head]
        visited: set[str] = set()
        while pending and len(visited) < 32:
            sha = pending.pop()
            if sha == base:
                return
            if sha in visited:
                continue
            if not SHA.fullmatch(sha):
                raise ValueError("invalid ancestry SHA")
            visited.add(sha)
            commit = self.request(f"git/commits/{sha}")
            pending.extend(parent["sha"] for parent in commit["parents"])
        raise ValueError("base ancestry unverified; desktop review needed")

    def blob(self, sha: str) -> str:
        if not SHA.fullmatch(sha):
            raise ValueError("invalid blob SHA")
        blob = self.request(f"git/blobs/{sha}")
        if blob.get("encoding") != "base64" or blob.get("size", 0) > 100000:
            raise ValueError("blob encoding/size outside review limit")
        return base64.b64decode(blob["content"]).decode("utf-8")

    def comment(self, number: int, body: str, head: str) -> None:
        if not self.token:
            raise ValueError("publication requires local GitHub token")
        if len(body) > 16000:
            raise ValueError("oversized review requires desktop publication")
        current = self.request(f"pulls/{number}")
        if current["state"] != "open" or current["head"]["sha"] != head:
            raise ValueError("PR closed or head changed before publication")
        # Never forward mention triggers returned by the model.
        safe = body.replace("@", "＠").replace("/bob-run", "／bob-run")
        self.request(f"issues/{number}/comments", "POST", {"body": MARKER + "\n" + safe})


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
    """Every earlier comment counts; this runs before publishing our new report."""
    value = {
        "comments": snapshot["comments"],
        "reviews": snapshot["reviews"],
        "inline": snapshot["inline"],
        "checks": snapshot["checks"],
        "statuses": snapshot["statuses"],
        "title": snapshot["pr"].get("title"),
        "body": snapshot["pr"].get("body"),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
