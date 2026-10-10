"""Require recorded main-head evidence before releasing a manually requested Bob run.

This runs on resolve's trusted runner, never on Bob's worker. API uncertainty fails
closed. Main-head evidence is not a substitute for human approval of that revision.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_PAGES = 20
MAX_BYTES = 2_000_000
GetPage = Callable[[str], tuple[object, str]]


class Rejected(ValueError):
    """No complete, trustworthy evidence for the requested run revision."""


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise Rejected("Invalid evidence timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Rejected("Invalid evidence timestamp") from exc


def next_page(link: str, repo: str, repo_id: str) -> str:
    if not link:
        return ""
    following = ""
    for part in link.split(","):
        match = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="(next|prev|first|last)"\s*', part)
        if not match:
            raise Rejected("Malformed activity pagination")
        url, relation = match.groups()
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.github.com"
            or parsed.path not in (f"/repos/{repo}/activity", f"/repositories/{repo_id}/activity")
            or parsed.fragment
            or query.get("ref") != ["refs/heads/main"]
            or query.get("per_page") != ["100"]
            or set(query) - {"ref", "per_page", "after", "before"}
            or any(len(values) != 1 for values in query.values())
        ):
            raise Rejected("Untrusted activity pagination")
        if relation == "next":
            if following:
                raise Rejected("Duplicate next page")
            following = url
    return following


def verify_revision(repo: str, repo_id: str, revision: str, cutoff: str, get: GetPage) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise Rejected("Invalid repository")
    if not re.fullmatch(r"[0-9]+", repo_id) or not SHA.fullmatch(revision):
        raise Rejected("Invalid repository id or full revision")
    deadline = timestamp(cutoff)
    url = f"https://api.github.com/repos/{repo}/activity?ref=refs%2Fheads%2Fmain&per_page=100"
    seen: set[str] = set()
    found = False
    try:
        for _ in range(MAX_PAGES):
            if url in seen:
                raise Rejected("Activity pagination loop")
            seen.add(url)
            rows, link = get(url)
            if not isinstance(rows, list) or len(rows) > 100:
                raise Rejected("Malformed activity page")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("id")) is not int
                    or row["id"] <= 0
                    or not all(
                        isinstance(row.get(key), str)
                        for key in ("before", "after", "ref", "activity_type")
                    )
                    or not SHA.fullmatch(row["before"])
                    or not SHA.fullmatch(row["after"])
                ):
                    raise Rejected("Malformed activity record")
                when = timestamp(row.get("timestamp"))
                if (
                    row["ref"] == "refs/heads/main"
                    and row["activity_type"] in {"push", "pr_merge"}
                    and row["after"] == revision
                    and when <= deadline
                ):
                    found = True
            # Validate the whole matching page and its Link before accepting evidence.
            # Unrelated older pages are not part of this positive-evidence predicate.
            url = next_page(link, repo, repo_id)
            if url in seen:
                raise Rejected("Activity pagination loop")
            if found:
                return revision
            if not url:
                raise Rejected(
                    "Requested revision has no recorded main-head evidence before trigger"
                )
        raise Rejected("Activity pagination limit reached")
    except (OSError, ValueError, TypeError) as exc:
        raise Rejected(str(exc)) from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        # Never forward the token, even to a redirect on the same hostname.
        raise Rejected("API redirects are refused")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("Duplicate JSON object key")
        result[key] = value
    return result


def api_page(url: str, token: str) -> tuple[object, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    # URL is the fixed API endpoint or a validated pagination link.
    with opener.open(request, timeout=10) as response:  # nosec B310
        if response.status != 200:
            raise Rejected("API did not return HTTP 200")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise Rejected("API response size limit exceeded")
        return json.loads(body, object_pairs_hook=unique_object), response.headers.get("Link", "")


def main() -> int:
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        repo_id = os.environ["REPOSITORY_ID"]
        revision = os.environ["REVISION"]
        token = os.environ["GH_TOKEN"]
        event = os.environ["EVENT"]
        if not token or event not in {"issue_comment", "workflow_dispatch"}:
            raise Rejected("Missing token or invalid manual trigger")
        if event == "issue_comment":
            cutoff = os.environ["COMMENT_CREATED_AT"]
        else:
            run_id = os.environ["GITHUB_RUN_ID"]
            if not run_id.isdecimal() or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
                raise Rejected("Invalid run identity")
            run, _ = api_page(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}", token)
            if (
                not isinstance(run, dict)
                or run.get("id") != int(run_id)
                or run.get("event") != "workflow_dispatch"
                or not isinstance(run.get("repository"), dict)
                or run["repository"].get("id") != int(repo_id)
            ):
                raise Rejected("Invalid run metadata")
            cutoff = run.get("created_at", "")
        verified = verify_revision(
            repo, repo_id, revision, cutoff, lambda url: api_page(url, token)
        )
        print(f"Verified requested main-head revision: {verified}")
        return 0
    except (KeyError, OSError, ValueError, TypeError) as exc:
        # Do not print URLs, response bodies or exception details that could carry credentials.
        print(
            f"Run revision evidence rejected ({type(exc).__name__}); Bob will not run.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
