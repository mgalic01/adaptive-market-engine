"""Claims on PRs and issues: who is working on what, and the checks that enforce them.

Design and rules: docs/reviews/2026-09-28-claude-pr-claims-design.md and the "Claims"
section of docs/AGENT_HANDOFF.md. A claim is a comment from the owner's account whose
first line starts with a sender tag and whose second line is the command:

    [Claude Code e0b16be3]
    /claim 24h review of head 76a7561

`/claim [<N>h] [note]` (1 to 24 hours, default 24), `/release` by the holder, and
`/release all` as the whole first line, which only the owner types. Nothing else counts:
not the PR description, not an edit, not a command quoted anywhere but line 2.

    status [N ...]       active claims on the open PRs, or on the given numbers
    check N --as TAG     exit 0 if N is free or held by TAG, 1 if held by another, 2 if unknown
    hook                 Claude Code PreToolUse hook: refuse a push or merge on a PR that
                         another holder has claimed
    workflow             GitHub Actions: set the claim-guard status and the claimed label

Standard library only. Reads GitHub with a token from the environment when there is one,
then the signed-in `gh`, then anonymously (the repository is public). Never prints a token.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = "mgalic01/adaptive-market-engine"
OWNER_LOGIN = "mgalic01"
CONTEXT = "claim-guard"
LABEL = "claimed"
MAX_HOURS = 24
API = "https://api.github.com/"
REJECT_MARK = "<!-- claim-rejected:{} -->"

TAG_RE = re.compile(r"^\**\[(Claude Code [A-Za-z0-9_-]+|Codex Desktop|Bob)\]\**")
CLAIM_RE = re.compile(r"^/claim(?:\s+(\d+)h)?(?:\s+(.*\S))?\s*$")
RELEASE_RE = re.compile(r"^/release\s*$")
RELEASE_ALL_RE = re.compile(r"^/release\s+all\s*$")
OWNER = "owner"


class GitHubError(RuntimeError):
    """GitHub could not be read or written; the message never contains a token."""


# --- Claims --------------------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    comment_id: int
    at: datetime
    holder: str
    kind: str  # "claim", "release" or "release-all"
    hours: int = 0
    note: str = ""
    error: str | None = None


@dataclass(frozen=True)
class Claim:
    holder: str
    since: datetime
    until: datetime
    note: str
    comment_id: int


@dataclass
class State:
    active: Claim | None = None
    expired: Claim | None = None
    rejected: list[tuple[Command, str]] = field(default_factory=list)


def parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


def normalize_tag(tag: str) -> str:
    """'[Bob]', '**[Bob]**' and 'Bob' all name the holder 'Bob'."""
    return tag.strip().strip("*").strip().removeprefix("[").removesuffix("]").strip()


def parse_command(comment: dict[str, Any]) -> Command | None:
    """The claim command in one comment, or None if the comment is not one."""
    if (comment.get("user") or {}).get("login") != OWNER_LOGIN:
        return None
    if comment.get("author_association", "OWNER") != "OWNER":
        return None
    if comment.get("updated_at", comment["created_at"]) != comment["created_at"]:
        return None  # an edited comment no longer counts: post a new one
    lines = (comment.get("body") or "").splitlines()
    if not lines:
        return None
    cid, at = int(comment["id"]), parse_time(comment["created_at"])
    if RELEASE_ALL_RE.match(lines[0].strip()):
        return Command(cid, at, OWNER, "release-all")
    tag = TAG_RE.match(lines[0].strip())
    if tag is None or len(lines) < 2:
        return None
    holder, line = tag.group(1), lines[1].strip()
    if RELEASE_RE.match(line):
        return Command(cid, at, holder, "release")
    claim = CLAIM_RE.match(line)
    if claim is None:
        return None
    hours = int(claim.group(1)) if claim.group(1) else MAX_HOURS
    error = None if 1 <= hours <= MAX_HOURS else f"a claim lasts 1 to {MAX_HOURS} hours"
    return Command(cid, at, holder, "claim", hours, claim.group(2) or "", error)


def evaluate(comments: Iterable[dict[str, Any]], now: datetime) -> State:
    """Replay the commands in order: one holder at a time, expiry by GitHub's clock."""
    state = State()
    commands = [c for c in map(parse_command, comments) if c is not None]
    for cmd in sorted(commands, key=lambda c: (c.at, c.comment_id)):
        held = state.active if state.active and state.active.until > cmd.at else None
        if cmd.kind == "release-all":
            state.active = None
        elif cmd.kind == "release":
            if held and held.holder == cmd.holder:
                state.active = None
        elif cmd.error:
            state.rejected.append((cmd, cmd.error))
        elif held and held.holder != cmd.holder:
            state.rejected.append((cmd, f"held by [{held.holder}] until {fmt(held.until)}"))
        else:
            until = cmd.at + timedelta(hours=cmd.hours)
            state.active = Claim(cmd.holder, cmd.at, until, cmd.note, cmd.comment_id)
    if state.active and state.active.until <= now:
        state.expired, state.active = state.active, None
    return state


def describe(state: State) -> str:
    """At most 140 characters, the limit of a commit status description."""
    if state.active is None:
        return "no active claim"
    c = state.active
    text = f"claimed by [{c.holder}] until {fmt(c.until)}" + (f": {c.note}" if c.note else "")
    return text if len(text) <= 140 else text[:139] + "…"


# --- GitHub --------------------------------------------------------------------------


def _windows_user_token() -> str | None:
    """The owner keeps GITHUB_TOKEN in the Windows user environment (AGENT_HANDOFF)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "GITHUB_TOKEN")
            return str(value) or None
    except OSError:
        return None


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or _windows_user_token()


def _http(method: str, path: str, token: str | None, payload: Any = None) -> Any:
    url = API + path
    if not url.startswith(API):
        raise GitHubError("refusing a non-GitHub URL")
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)  # nosec B310
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "amengine-claims")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else None


def get(path: str) -> Any:
    """Read: token, then `gh`, then anonymous. Raises GitHubError with a short reason."""
    token = _token()
    if token:
        try:
            return _http("GET", path, token)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise GitHubError(f"GitHub HTTP {e.code} on {path.split('?')[0]}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GitHubError("GitHub unreachable") from None
    gh = shutil.which("gh")
    if gh:
        try:
            r = subprocess.run(  # nosec B603
                [gh, "api", path], capture_output=True, text=True, timeout=20, check=False
            )
            if r.returncode == 0:
                return json.loads(r.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        return _http("GET", path, None)
    except urllib.error.HTTPError as e:
        raise GitHubError(f"GitHub HTTP {e.code} on {path.split('?')[0]}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GitHubError("GitHub unreachable") from None


def send(method: str, path: str, payload: Any = None) -> Any:
    """Write with the environment's token (the workflow's GITHUB_TOKEN)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubError("no GITHUB_TOKEN for a write")
    try:
        return _http(method, path, token, payload)
    except urllib.error.HTTPError as e:
        raise GitHubError(f"GitHub HTTP {e.code} on {method} {path.split('?')[0]}") from None


def fetch_comments(number: int, reader: Callable[[str], Any] = get) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = reader(f"repos/{REPO}/issues/{number}/comments?per_page=100&page={page}")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def open_prs(reader: Callable[[str], Any] = get) -> list[dict[str, Any]]:
    return list(reader(f"repos/{REPO}/pulls?state=open&per_page=100"))


# --- The Claude Code hook ------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    kind: str  # "merge" or "push"
    pr: int | None = None
    branch: str | None = None
    every_branch: bool = False
    unknown: str | None = None  # why the PR could not be determined


def _git(cwd: str, *args: str) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run(  # nosec B603
            [git, "-C", cwd, *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def current_branch(cwd: str) -> str | None:
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return None if branch in (None, "", "HEAD") else branch


def is_this_repo(url: str | None) -> bool:
    return url is None or REPO in url.removesuffix(".git")


def remote_is_ours(remote: str, cwd: str) -> bool:
    """Unknown counts as ours: the check is skipped only for a remote known to differ."""
    if "://" in remote or "@" in remote or remote.endswith(".git"):
        return is_this_repo(remote)
    return is_this_repo(_git(cwd, "remote", "get-url", remote))


PUSH_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}


def _branch_of(ref: str, cwd: str) -> str | None:
    if ref in ("HEAD", "@", ""):
        return current_branch(cwd)
    return ref.removeprefix("refs/heads/")


def push_targets(args: list[str], cwd: str) -> list[Target]:
    positional: list[str] = []
    every = delete = tags = dry = False
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in PUSH_VALUE_OPTS:
            skip = True
        elif a in ("--all", "--branches", "--mirror"):
            every = True
        elif a in ("-d", "--delete"):
            delete = True
        elif a == "--tags":
            tags = True
        elif a in ("-n", "--dry-run"):
            dry = True
        elif not a.startswith("-"):
            positional.append(a)
    if dry:
        return []
    remote, refspecs = (positional[0], positional[1:]) if positional else ("origin", [])
    if not remote_is_ours(remote, cwd):
        return []
    if every:
        return [Target("push", every_branch=True)]
    if not refspecs:
        if tags:
            return []
        branch = current_branch(cwd)
        if branch is None:
            return [Target("push", unknown="the current branch could not be read")]
        return [Target("push", branch=branch)]
    out = []
    for spec in refspecs:
        spec = spec.lstrip("+")
        dst = spec if delete or ":" not in spec else (spec.split(":", 1)[1] or spec.split(":")[0])
        if dst.startswith("refs/tags/"):
            continue
        branch = _branch_of(dst, cwd)
        out.append(
            Target("push", branch=branch)
            if branch
            else Target("push", unknown=f"the branch of {spec!r} could not be read")
        )
    return out


GH_MERGE_VALUE_OPTS = {
    "-t", "--subject", "-b", "--body", "-F", "--body-file",
    "--match-head-commit", "-A", "--author-email", "-R", "--repo",
}  # fmt: skip


def _exe(token: str) -> str:
    return Path(token).name.lower().removesuffix(".exe")


def split_words(segment: str) -> list[str]:
    """Shell words; Windows paths keep their backslashes."""
    try:
        if "\\" in segment:
            return [w.strip("\"'") for w in shlex.split(segment, posix=False)]
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


REDIRECT_RE = re.compile(r"^(?:\d*|&)(?:>>?|<)(.*)$")


def drop_redirections(words: list[str]) -> list[str]:
    """`2>&1`, `>out` and `> out` are the shell's, not the command's arguments."""
    out: list[str] = []
    skip = False
    for w in words:
        if skip:
            skip = False
            continue
        m = REDIRECT_RE.match(w)
        if m:
            skip = m.group(1) == ""
            continue
        out.append(w)
    return out


def find_targets(command: str, cwd: str) -> list[Target]:
    """Every push or merge in a shell command, with the working directory it runs in."""
    targets: list[Target] = []
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        toks = drop_redirections(split_words(segment))
        while toks and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[0]):
            toks = toks[1:]
        if not toks:
            continue
        exe = _exe(toks[0])
        if exe in ("cd", "set-location", "pushd", "sl") and len(toks) > 1:
            cwd = str(Path(cwd, toks[-1]))
        elif exe == "git":
            here, rest = cwd, toks[1:]
            while rest and rest[0].startswith("-"):
                if rest[0] == "-C" and len(rest) > 1:
                    here, rest = str(Path(here, rest[1])), rest[2:]
                elif rest[0] == "-c" and len(rest) > 1:
                    rest = rest[2:]
                else:
                    rest = rest[1:]
            if rest and rest[0] == "push":
                targets.extend(push_targets(rest[1:], here))
        elif exe == "gh":
            targets.extend(_gh_targets(toks[1:], segment, cwd))
    return targets


def _gh_targets(toks: list[str], segment: str, cwd: str) -> list[Target]:
    repo_flag = next((toks[i + 1] for i, t in enumerate(toks[:-1]) if t in ("-R", "--repo")), None)
    if repo_flag is not None:
        repo_flag = repo_flag.removesuffix(".git").removesuffix("/")
        if repo_flag != REPO and not repo_flag.endswith("/" + REPO):
            return []
    if repo_flag is None and not is_this_repo(_git(cwd, "remote", "get-url", "origin")):
        return []
    if toks[:2] == ["pr", "merge"]:
        arg, skip = None, False
        for t in toks[2:]:
            if skip:
                skip = False
            elif t in GH_MERGE_VALUE_OPTS:
                skip = True
            elif not t.startswith("-") and arg is None:
                arg = t
        if arg is None:
            branch = current_branch(cwd)
            return [Target("merge", branch=branch, unknown=None if branch else "no PR named")]
        number = re.search(r"(?:^|/pull/)(\d+)$", arg)
        return (
            [Target("merge", pr=int(number.group(1)))] if number else [Target("merge", branch=arg)]
        )
    if toks[:1] == ["api"]:
        merges = [int(n) for n in re.findall(r"pulls/(\d+)/merge\b", segment)]
        if merges:
            return [Target("merge", pr=n) for n in merges]
        if "mergePullRequest" in segment:
            return [Target("merge", unknown="a GraphQL merge; use `gh pr merge <N>`")]
    return []


def hook_decision(
    payload: dict[str, Any],
    reader: Callable[[str], Any] = get,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The hook's JSON answer, or None to let the command run unremarked."""
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if "push" not in command and "merge" not in command and "Merge" not in command:
        return None
    cwd = str(payload.get("cwd") or os.getcwd())
    targets = find_targets(command, cwd)
    if not targets:
        return None
    session = str(payload.get("session_id") or "")[:8]
    me = f"Claude Code {session}" if session else None
    now = now or datetime.now(UTC)
    merge = any(t.kind == "merge" for t in targets)
    warnings: list[str] = [f"{t.kind}: {t.unknown}" for t in targets if t.unknown]
    blocks: list[str] = []
    try:
        numbers: set[int] = {t.pr for t in targets if t.pr is not None}
        wanted = {t.branch for t in targets if t.branch and t.pr is None}
        if wanted or any(t.every_branch for t in targets):
            for pr in open_prs(reader):
                head = pr.get("head") or {}
                same_repo = (head.get("repo") or {}).get("full_name") == REPO
                if same_repo and (
                    head.get("ref") in wanted or any(t.every_branch for t in targets)
                ):
                    numbers.add(int(pr["number"]))
        for number in sorted(numbers):
            state = evaluate(fetch_comments(number, reader), now)
            c = state.active
            if c and c.holder != me:
                blocks.append(
                    f"PR #{number} is claimed by [{c.holder}] until {fmt(c.until)}"
                    + (f" ({c.note})" if c.note else "")
                )
    except GitHubError as e:
        if merge:
            return _deny(f"claims could not be read ({e}), so the merge is refused (fail closed).")
        warnings.append(f"claims could not be read ({e}); the push is allowed (fail open)")
    unknown_merge = [t for t in targets if t.kind == "merge" and t.unknown]
    if unknown_merge and not blocks:
        return _deny(f"the PR to merge could not be determined: {unknown_merge[0].unknown}.")
    if blocks:
        who = f"[{me}]" if me else "this session (no session id)"
        return _deny(
            "; ".join(blocks)
            + f". You are {who}. Do not push or merge: comment on the PR to reach the "
            "holder, wait for its `/release` or the expiry, or ask the owner."
        )
    if warnings:
        return {"systemMessage": "claims: " + "; ".join(warnings)}
    return None


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "claims: " + reason,
        }
    }


# --- The workflow --------------------------------------------------------------------


def workflow(event_name: str, event: dict[str, Any], now: datetime) -> list[str]:
    """Set the status and label for one PR or issue, and answer rejected claims."""
    pr_event = event.get("pull_request")
    issue = event.get("issue") or {}
    number = int((pr_event or issue)["number"])
    is_pr = pr_event is not None or "pull_request" in issue
    comments = fetch_comments(number)
    state = evaluate(comments, now)
    log = [f"#{number}: {describe(state)}"]
    if is_pr:
        sha = (pr_event or get(f"repos/{REPO}/pulls/{number}"))["head"]["sha"]
        send(
            "POST",
            f"repos/{REPO}/statuses/{sha}",
            {
                "state": "failure" if state.active else "success",
                "context": CONTEXT,
                "description": describe(state),
            },
        )
        log.append(f"status on {sha[:7]}: {'failure' if state.active else 'success'}")
    labels = {lab["name"] for lab in issue.get("labels") or (pr_event or {}).get("labels") or []}
    if state.active and LABEL not in labels:
        with contextlib.suppress(GitHubError):  # the label already exists
            send("POST", f"repos/{REPO}/labels", {"name": LABEL, "color": "d93f0b"})
        send("POST", f"repos/{REPO}/issues/{number}/labels", {"labels": [LABEL]})
        log.append("label added")
    elif not state.active and LABEL in labels:
        send("DELETE", f"repos/{REPO}/issues/{number}/labels/{LABEL}")
        log.append("label removed")
    answered = {
        m
        for c in comments
        if (c.get("user") or {}).get("login") == "github-actions[bot]"
        for m in re.findall(r"<!-- claim-rejected:(\d+) -->", c.get("body") or "")
    }
    for cmd, reason in state.rejected:
        if str(cmd.comment_id) in answered:
            continue
        send(
            "POST",
            f"repos/{REPO}/issues/{number}/comments",
            {
                "body": f"**Claim rejected** for [{cmd.holder}] (comment {cmd.comment_id}): "
                f"{reason}. Comment to reach the holder, or wait for its `/release`. "
                f'Rules: `docs/AGENT_HANDOFF.md`, "Claims".\n\n'
                + REJECT_MARK.format(cmd.comment_id)
            },
        )
        log.append(f"rejected comment {cmd.comment_id}")
    return log


# --- CLI -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("numbers", nargs="*", type=int)
    ck = sub.add_parser("check")
    ck.add_argument("number", type=int)
    ck.add_argument("--as", dest="holder", required=True)
    sub.add_parser("hook")
    sub.add_parser("workflow")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)

    if args.cmd == "hook":
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
        answer = hook_decision(payload, now=now)
        if answer:
            print(json.dumps(answer))
        return 0
    if args.cmd == "workflow":
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
            event = json.load(f)
        for line in workflow(os.environ.get("GITHUB_EVENT_NAME", ""), event, now):
            print(line)
        return 0
    try:
        if args.cmd == "check":
            state = evaluate(fetch_comments(args.number), now)
            c = state.active
            if c and c.holder != normalize_tag(args.holder):
                print(f"#{args.number}: {describe(state)}. Do not push or merge.")
                return 1
            print(f"#{args.number}: {describe(state)}")
            return 0
        numbers = args.numbers or [int(p["number"]) for p in open_prs()]
        for n in numbers:
            print(f"#{n}: {describe(evaluate(fetch_comments(n), now))}")
        return 0
    except GitHubError as e:
        print(f"claims could not be read: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
