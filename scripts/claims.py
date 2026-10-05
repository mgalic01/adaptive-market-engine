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
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

REPO = "mgalic01/adaptive-market-engine"  # lowercase: GitHub ignores the case of names
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
    if comment.get("author_association") != "OWNER":
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
    # API ends with "/", so no path can change the host the token is sent to.
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=data, method=method)  # nosec B310
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "amengine-claims")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
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
                [gh, "api", path], capture_output=True, text=True, timeout=10, check=False
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


def _pages(path: str, reader: Callable[[str], Any]) -> list[dict[str, Any]]:
    """Every item of a list endpoint, read 100 per page."""
    out: list[dict[str, Any]] = []
    sep = "&" if "?" in path else "?"
    page = 1
    while True:
        batch = reader(f"{path}{sep}per_page=100&page={page}")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def fetch_comments(number: int, reader: Callable[[str], Any] = get) -> list[dict[str, Any]]:
    return _pages(f"repos/{REPO}/issues/{number}/comments", reader)


def open_prs(reader: Callable[[str], Any] = get) -> list[dict[str, Any]]:
    return _pages(f"repos/{REPO}/pulls?state=open", reader)


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
    """This repository, anchored: `...-fork` or `other-mgalic01/...` is not it. GitHub
    ignores case, so `MGalic01/...` is it (automated audit, 2026-09-29)."""
    if url is None:
        return True
    url = url.strip().removesuffix("/").removesuffix(".git").removesuffix("/").lower()
    return url == REPO or url.endswith(("/" + REPO, ":" + REPO))


def remote_is_ours(remote: str, cwd: str) -> bool:
    """Unknown counts as ours: the check is skipped only for a remote known to differ."""
    if "://" in remote or "@" in remote or remote.endswith(".git"):
        return is_this_repo(remote)
    return is_this_repo(_git(cwd, "remote", "get-url", remote))


PUSH_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
# A PR or branch the shell computes: `$n`, `${n}`, `$(...)` or backticks.
COMPUTED_RE = re.compile(r"\$[\w{(]|`")


def _branch_of(ref: str, cwd: str) -> str | None:
    if ref in ("HEAD", "@", ""):
        return current_branch(cwd)
    return ref.removeprefix("refs/heads/")


def _mapped(source: str, remote: str, cwd: str) -> str | None:
    """Where a `remote.<remote>.push` refspec sends ``source``, or None when none
    names it."""
    full = source if source.startswith("refs/") else f"refs/heads/{source}"
    for spec in (_git(cwd, "config", "--get-all", f"remote.{remote}.push") or "").split():
        mine, _, theirs = spec.lstrip("+").partition(":")
        if theirs and mine in (full, source):
            return theirs
        if mine.endswith("*") and theirs.endswith("*") and full.startswith(mine[:-1]):
            return theirs[:-1] + full[len(mine) - 1 :]
    return None


def _push_remote(cwd: str) -> str:
    """The remote `git push` with no repository goes to: the current branch's
    pushRemote, then remote.pushDefault, then the branch's remote, then origin (Codex
    review of #159)."""
    branch = current_branch(cwd)
    keys = [f"branch.{branch}.pushRemote", "remote.pushDefault", f"branch.{branch}.remote"]
    for key in keys if branch else ["remote.pushDefault"]:
        if value := _git(cwd, "config", "--get", key):
            return value
    return "origin"


def _default_destination(branch: str, cwd: str) -> str | None:
    """The remote branch push.default sends the current ``branch`` to: its upstream
    for `upstream`, every branch (None) for `matching`, else its own name."""
    mode = (_git(cwd, "config", "--get", "push.default") or "simple").lower()
    if mode == "matching":
        return None
    if mode in ("upstream", "tracking"):
        merge = _git(cwd, "config", "--get", f"branch.{branch}.merge")
        if merge:
            return merge.removeprefix("refs/heads/")
    return branch


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
    remote, refspecs = (positional[0], positional[1:]) if positional else (_push_remote(cwd), [])
    if not remote_is_ours(remote, cwd):
        return []
    if every:
        return [Target("push", every_branch=True)]
    if not refspecs:
        if tags:
            return []
        # Where git sends a push with no refspec: the remote's own push refspecs, or
        # where push.default sends the current branch, which `upstream` can make
        # another branch than its own name (Codex review of #159).
        configured = _git(cwd, "config", "--get-all", f"remote.{remote}.push")
        if configured:
            refspecs = configured.split()
        else:
            branch = current_branch(cwd)
            if branch is None:
                return [Target("push", unknown="the current branch could not be read")]
            destination = _default_destination(branch, cwd)
            if destination is None:
                return [Target("push", every_branch=True)]
            return [Target("push", branch=destination)]
    out = []
    for spec in refspecs:
        if COMPUTED_RE.search(spec):
            out.append(Target("push", unknown=f"the branch {spec!r} is known only at run time"))
            continue
        spec = spec.lstrip("+")
        dst = spec if delete or ":" not in spec else (spec.split(":", 1)[1] or spec.split(":")[0])
        if ":" not in spec and not delete and spec not in ("HEAD", "@"):
            # `git push origin work` goes where a remote push refspec maps `work`.
            dst = _mapped(spec, remote, cwd) or dst
        if dst.startswith("refs/tags/"):
            continue
        if "*" in dst:  # a pattern: any branch it matches
            out.append(Target("push", every_branch=True))
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
    """`git`, `/usr/bin/git` and `C:\\...\\git.exe` are all `git`, on any platform."""
    return PureWindowsPath(token).name.lower().removesuffix(".exe")


def split_words(segment: str) -> list[str]:
    """Shell words; Windows paths keep their backslashes. A segment cut out of a quoted
    string (`bash -c "cd x && git push"`) loses the quote at its edge."""
    try:
        if "\\" in segment:
            return [w.strip("\"'") for w in shlex.split(segment, posix=False)]
        return shlex.split(segment, posix=True)
    except ValueError:
        return [w.strip("\"'") for w in segment.split()]


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


# Words before the command that still run it (automated audit, 2026-09-29): the shell's
# `then git push`, `! git push` or `{ git push; }`, PowerShell's call and dot-source
# operators (`& git push`), and wrappers such as `env X=1 git push`.
PREFIX_WORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "(", "&", "."}
WRAPPERS = {"env", "timeout", "nohup", "nice", "time", "command", "exec", "sudo", "doas"}
# The options that take the next word as their value, per wrapper (Codex review of #159:
# `env -C sub gh pr merge 5` was read as running `sub`, `sudo --user root git push` as
# running `root`). Per wrapper, since `time -p` takes none.
WRAPPER_VALUE_OPTS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-P"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "exec": {"-a"},
    "time": {"-f", "--format", "-o", "--output"},
    "sudo": {
        "-u", "--user", "-g", "--group", "-D", "--chdir", "-h", "--host", "-p", "--prompt",
        "-C", "--close-from", "-r", "--role", "-t", "--type", "-T", "--command-timeout",
        "-U", "--other-user", "-R", "--chroot", "-a", "--auth-type", "-c", "--login-class",
    },
    "doas": {"-u", "-C"},
}  # fmt: skip
# The options that run a wrapper's command in another directory: (short, long).
WRAPPER_CHDIR_OPTS = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir")}
# Git's global options that take the next word as their value: `git --git-dir .git push`
# was read as running the subcommand `.git` (Codex review of #159). -C and --git-dir are
# handled apart, since they select where the repository is read.
GIT_VALUE_OPTS = {"-c", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
# Git's own commands, which an alias of the same name cannot replace; any other
# subcommand may be an alias (Codex review of #159: `git -c alias.p=push p` pushed).
GIT_BUILTINS = {
    "add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file",
    "checkout", "cherry", "cherry-pick", "clean", "clone", "commit", "config", "describe",
    "diff", "difftool", "fetch", "for-each-ref", "format-patch", "fsck", "gc", "grep",
    "help", "init", "log", "ls-files", "ls-remote", "ls-tree", "maintenance", "merge",
    "merge-base", "mergetool", "mv", "notes", "pull", "push", "range-diff", "rebase",
    "reflog", "remote", "repack", "replace", "reset", "restore", "rev-list", "rev-parse",
    "revert", "rm", "send-pack", "shortlog", "show", "show-ref", "sparse-checkout", "stash",
    "status", "submodule", "switch", "symbolic-ref", "tag", "update-index", "update-ref",
    "version", "worktree",
}  # fmt: skip
# Clients that can send a REST or GraphQL merge themselves; any other command only names
# one (Codex review of #159: `echo mergePullRequest` was refused as a merge).
HTTP_CLIENTS = {
    "curl", "wget", "http", "https", "xh", "python", "python3", "py", "node", "deno",
    "bun", "ruby", "perl", "php", "pypy", "nodejs", "invoke-restmethod", "invoke-webrequest",
    "irm", "iwr",
}  # fmt: skip
# Clients that can run any program, not only send a request.
INTERPRETERS = {"python", "py", "pypy", "node", "nodejs", "deno", "bun", "ruby", "perl", "php"}
# Commands that run another command with arguments known only at run time (`printf 5 |
# xargs gh pr merge`, `find -exec`); a merge or push in their line counts as unknown
# (Codex review of #159).
LAUNCHERS = {"xargs", "parallel", "find", "fd", "watch", "entr"}
# A client's version suffix: `python3.12`, `ruby3.2` and `perl5.36` are python, ruby and
# perl (Codex review of #159).
CLIENT_VERSION_RE = re.compile(r"[\d.]+$")
# A `case` arm's pattern word, which the arm's command follows.
CASE_PATTERN_RE = re.compile(r"\(?[^()]*\)")
# `env -S 'gh pr merge 5'` (or -S'...', --split-string=...) runs the words of its value.
SPLIT_STRING_RE = re.compile(r"(?:-S|--split-string=?)(.*)", re.DOTALL)
WRAPPER_NUMBER_RE = re.compile(r"\d[\d.]*[smhd]?")  # `timeout 60`, `timeout 1.5m`
POSIX_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
SHELLS = (*POSIX_SHELLS, "pwsh", "powershell", "cmd")
EVALS = ("eval", "iex", "invoke-expression")
MAX_DEPTH = 3  # how deep `bash -c "pwsh -Command '...'"` and `$(...)` are read


def unwrap(words: list[str]) -> list[str]:
    """The command without what runs it: `VAR=1`, PowerShell's `$out =`, `& git` or
    `&git`, a shell keyword, a wrapper with its options (`timeout -s KILL 60`), a `case`
    header or arm pattern, or a function definition's name. A command in a function
    body counts although it runs only when called (fail closed)."""
    while words:
        w = words[0]
        if w in PREFIX_WORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            words = words[1:]
        elif w == "case":
            # `case x in x) gh pr merge 5;; esac` (Codex review of #159).
            words = words[words.index("in") + 1 :] if "in" in words else []
        elif CASE_PATTERN_RE.fullmatch(w):
            words = words[1:]  # an arm's pattern: `x)`, `*)`, `(main|dev)`
        elif w == "function":
            words = words[2:]  # `function f { ...`
        elif w.endswith("()") or words[1:2] == ["()"]:
            words = words[1:] if w.endswith("()") else words[2:]  # `f() { ...`, `f () {`
        elif w.startswith("$") and words[1:2] == ["="]:
            words = words[2:]
        elif w.startswith("&"):
            words = [w[1:], *words[1:]]
        elif (wrapper := _exe(w)) in WRAPPERS:
            opts = WRAPPER_VALUE_OPTS.get(wrapper, set())
            words = words[1:]
            while words and (words[0].startswith("-") or WRAPPER_NUMBER_RE.fullmatch(words[0])):
                if wrapper == "env" and (split := SPLIT_STRING_RE.fullmatch(words[0])):
                    if split[1]:
                        value, rest = split[1], words[1:]
                    else:
                        value, rest = (words[1] if len(words) > 1 else ""), words[2:]
                    words = [*split_words(value), *rest]
                    break
                words = words[2:] if _takes_value(words[0], opts) else words[1:]
        else:
            break
    return words


def _takes_value(option: str, opts: set[str]) -> bool:
    """Whether a wrapper's option word takes the next word as its value: one in
    ``opts``, or a bundle of short flags whose first value option ends it (`sudo -Eu
    root`; Codex review of #159). A value attached to it (`-uroot`) is in the word."""
    return option in opts or _bundled_value(option, opts) == len(option) - 1


def _bundled_value(option: str, opts: set[str]) -> int | None:
    """In a bundle of short flags (`-Eu`), the index of the first that takes a value."""
    if not re.fullmatch(r"-[A-Za-z]{2,}", option):
        return None
    return next((k for k, c in enumerate(option[1:], 1) if f"-{c}" in opts), None)


def shell_command(exe: str, args: list[str]) -> tuple[str, list[str]] | None:
    """The command string that `bash -c`, `pwsh -Command` or `cmd /c` runs, with the
    words a POSIX shell gives its positional parameters ($0, $1...), or None."""
    for i, a in enumerate(args):
        if exe in POSIX_SHELLS and re.fullmatch(r"-[a-z]*c[a-z]*", a):  # -c, -lc, -ec
            return (args[i + 1], args[i + 2 :]) if i + 1 < len(args) else None
        name = a.lower().lstrip("-/") if a[:1] in ("-", "/") else ""
        if exe in ("pwsh", "powershell") and name and "command".startswith(name):
            return " ".join(args[i + 1 :]), []
        if exe == "cmd" and a[:1] == "/" and name in ("c", "k"):
            return " ".join(args[i + 1 :]), []
    return None


# A positional parameter of a `sh -c` script, quoted or not: `$1`, `${2}`, or all of
# them, `$@` and `$*`.
POSITIONAL_RE = re.compile(r'"\$(?:\{([@*]|\d+)\}|([@*]|\d))"|\$(?:\{([@*]|\d+)\}|([@*]|\d))')


def _positional(script: str, params: list[str]) -> str:
    """``script`` with its positional parameters replaced by the words `sh -c script
    name args...` gives them: $0 the name, $1... the args, $@ and $* every arg (Codex
    review of #159: `sh -c '"$@"' _ git push origin x` runs the push). A quoted `"$*"`
    is one word, the args joined by a space (Codex review of #159)."""

    def words(m: re.Match[str]) -> str:
        quoted = m.group(1) or m.group(2)
        name = quoted or m.group(3) or m.group(4)
        if name == "*" and quoted:
            return shlex.quote(" ".join(params[1:]))
        if name in ("@", "*"):
            return " ".join(shlex.quote(p) for p in params[1:])
        return shlex.quote(params[int(name)]) if int(name) < len(params) else ""

    return POSITIONAL_RE.sub(words, script)


def substitutions(command: str, quotes: bool = True) -> list[str]:
    """The commands in `$(...)` and backticks, which the shell runs first. Inside single
    quotes the shell reads them as text, so they are skipped there (Codex review of
    #159); a here-document body has no quoting (``quotes=False``). A nested one is
    inside its outer one's text."""
    found: list[str] = []
    quote, i = "", 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            i += 1  # an escaped quote or backtick is plain text
        elif quotes and not quote and command.startswith("$'", i):
            quote, i = "$'", i + 1  # ANSI-C: text, with backslash escapes
        elif quote == "$'" and c == "'":
            quote = ""
        elif quotes and c in "'\"" and quote in ("", c):
            quote = "" if quote else c
        elif quote not in ("'", "$'") and c == "`":
            end = command.find("`", i + 1)
            if end < 0:
                break
            found.append(command[i + 1 : end])
            i = end
        elif quote not in ("'", "$'") and command.startswith("$(", i):
            # Its own quoting starts afresh, and a quoted or escaped parenthesis does not
            # close it (Codex review of #159: `$(eval 'printf ")"; gh pr merge 5')`).
            quoted = _quoted(command[i + 1 :])
            level, end = 0, i + 1
            while end < len(command):
                if not quoted[end - i - 1]:
                    level += {"(": 1, ")": -1}.get(command[end], 0)
                    if level == 0:
                        break
                end += 1
            found.append(command[i + 2 : end])
            i = end
        i += 1
    return found


# The delimiter must be the whole shell word. One with other characters (`END+`) is not
# recognised, so its here-document stays in the command and its lines are read as
# commands: a merge after it cannot be stripped as body (Codex review of #159).
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(\\?)(['\"]?)([\w.-]+)\3(?=[\s;&|<>()]|$)")


def _quoted(command: str) -> list[bool]:
    """Whether the shell reads each character as text: inside quotes, a quote itself, or
    escaped by a backslash. There `;`, `&`, `|`, `<<` and `#` are no operators. Bash's
    ANSI-C quotes, `$'...'`, take backslash escapes, `\\'` included (Codex review of
    #159: `printf %s $'a\\'b'; gh pr merge 5`)."""
    mask = [False] * len(command)
    quote, i = "", 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            mask[i : i + 2] = [True] * len(mask[i : i + 2])
            i += 2
            continue
        if not quote and command.startswith("$'", i):
            quote, mask[i : i + 2] = "$'", [True, True]
            i += 2
            continue
        if quote == "$'" and c == "'":
            quote, mask[i] = "", True
        elif c in "'\"" and quote in ("", c):
            quote = "" if quote else c
            mask[i] = True
        else:
            mask[i] = bool(quote)
        i += 1
    return mask


def _heredoc_operators(command: str, start: int, end: int) -> Iterator[re.Match[str]]:
    """The here-document operators the shell sees in ``command[start:end]``. One inside
    quotes, escaped, in a comment or in arithmetic (`((x << 1))` or the legacy
    `$[x << 1]`, a shift) is not one (Codex review of #159: each hid the merge on the
    next line as a body)."""
    quoted, i, arithmetic, legacy = _quoted(command), start, 0, 0
    while i < end:
        if quoted[i]:
            i += 1
        elif command.startswith("((", i):
            arithmetic, i = arithmetic + 1, i + 2
        elif arithmetic and command.startswith("))", i):
            arithmetic, i = arithmetic - 1, i + 2
        elif command.startswith("$[", i) or (legacy and command[i] == "["):
            legacy, i = legacy + 1, i + (2 if command[i] == "$" else 1)
        elif legacy and command[i] == "]":
            legacy, i = legacy - 1, i + 1
        elif command[i] == "#" and (i == 0 or command[i - 1] in " \t\n;&|("):
            line_end = command.find("\n", i, end)  # a comment runs to the end of its line
            i = end if line_end < 0 else line_end
        elif not arithmetic and not legacy and (m := HEREDOC_RE.match(command, i, end)):
            yield m
            i = m.end()
        else:
            i += 1


# Where a pipeline ends on a line: `;`, `&&`, `||` or a lone `&`, but not a pipe, which
# feeds a here-document into its consumer, nor bash's `|&`, a pipe that adds stderr.
PIPELINE_ENDS = re.compile(r"&&|\|\||(?<![>&|])&(?![&>])|;")


def _writes(words: list[str]) -> set[str]:
    """The files a pipeline stage's words write its output to: `> file`, `>> file`,
    `>file`, `&> file`, and `tee`'s file arguments."""
    files = set()
    for i, word in enumerate(words):
        if m := re.fullmatch(r"(?:1|&)?>>?\|?(.*)", word):
            target = m[1] or (words[i + 1] if i + 1 < len(words) else "")
            if target and not target.startswith("&"):  # `>&2` is a descriptor
                files.add(os.path.normpath(target))
    toks = unwrap(drop_redirections(words))
    if toks and _exe(toks[0]) == "tee":
        files |= {os.path.normpath(a) for a in toks[1:] if not a.startswith("-")}
    return files


def _readers(command: str, start: int, end: int, at: int) -> tuple[list[list[str]], set[str]]:
    """The commands that read the here-document whose `<<` is at ``at`` on the line
    ``command[start:end]``: the command of the `<<`'s own pipeline stage and of each
    stage after it, which its output feeds (`cat <<'EOF' | bash`); a stage before it
    never sees the body. The pipeline is the one in the innermost group still open at
    the `<<` (`x=$(bash <<EOF`), and a group closed before it, such as `<(echo arg)`, is
    an argument of its stage, not where a command starts. Each command is parsed into
    shell words and unwrapped (`/bin/'bash'` is bash, `sudo bash` is bash), so that an
    argument such as the `bash` of `echo bash <<EOF` is never taken for its reader.
    Also the files those commands write the body to (`cat > run <<EOF`), which a
    later command on the line may run. (Codex reviews of #159.)"""
    quoted = _quoted(command)
    groups: list[tuple[str, int]] = []  # the groups open before `at`: opener, text start
    for i in range(start, at):
        c = command[i]
        if quoted[i] or c not in "()`":
            continue
        if groups and (groups[-1][0], c) in (("(", ")"), ("`", "`")):
            groups.pop()
        elif c != ")":
            groups.append((c, i + 1))
    opener, region = groups[-1] if groups else ("", start)
    first = region
    stages: list[tuple[int, int]] = []
    nested: list[str] = []
    i = first
    while i < end:
        c = command[i]
        m = None if quoted[i] or nested else PIPELINE_ENDS.match(command, i, end)
        if quoted[i]:
            pass
        elif nested:
            if (nested[-1], c) in (("(", ")"), ("`", "`")):
                nested.pop()
            elif c in "(`":
                nested.append(c)
        elif m or c == ")" or (c == "`" and opener == "`"):
            # The pipeline ends: at a separator, or where its group closes (an unmatched
            # `)` before the `<<` ends a `case` pattern).
            if i >= at:
                break
            stages, first = [], m.end() if m else i + 1
            i = first
            continue
        elif c in "(`":
            nested.append(c)
        elif c == "|":
            stages.append((first, i))
            first = i + 1
        i += 1
    stages.append((first, i))
    readers: list[list[str]] = []
    written: set[str] = set()
    for s, e in stages:
        if e <= at or (s <= at and command[at] == "(" and not command[s:at].strip()):
            continue  # upstream of the `<<`, or a subshell around it: neither reads it
        raw = split_words(command[s:e])
        written |= _writes(raw)
        words = drop_redirections(raw)
        # A function body's opener before its command: `f(){ bash <<EOF`, `f() { bash`.
        while words and re.fullmatch(r"[^\s(){}]*\(\)\{?|[(){}]+", words[0]):
            words = words[1:]
        if words[:1] in (["."], ["source"]) or unwrap(words):
            readers.append(words)
    if groups:
        # What the group prints goes to the command around it: `bash < <(cat <<EOF)`,
        # `eval $(cat <<EOF)` or `(cat <<EOF) | bash` (Codex review of #159).
        outer, outer_written = _readers(command, start, end, region - 1)
        readers, written = readers + outer, written | outer_written
    return readers, written


# Commands that only read their input as data (git: by its subcommand, below). A
# here-document read by anything else (a shell under any name, `source`, ssh, a tool not
# listed) may run it, so its body is read as commands (Codex review of #159: `ash
# <<'EOF'`, `busybox sh <<'EOF'`). awk (`system()`), sed (`e`), the pagers (`!`) and
# patch (`-e` hands its input to ed) can run commands, so they are not here (Codex
# review of #159).
DATA_READERS = {
    "cat", "tee", "echo", "printf", "true", "false", "grep", "egrep", "fgrep",
    "rg", "sort", "uniq", "wc", "head", "tail", "cut", "tr", "jq",
    "yq", "diff", "base64", "xxd", "od", "column", "fold",
    "fmt", "nl", "rev", "paste", "comm", "join", "tac", "iconv", "sha256sum",
    "sha1sum", "md5sum", "read", "mapfile", "readarray", "clip", "pbcopy", "xclip",
    "xsel", "wl-copy",
}  # fmt: skip
# The git commands that only read their input as data (a patch, objects, refs), and
# those that do when told to read their message from it (`git commit -F -`) and open
# no editor. Any other may run it, an alias above all (`git -c alias.x='!sh' x <<EOF`),
# and so may any git given a setting or an environment, which can name a command to
# run: an editor (`GIT_EDITOR='sh -s'`), a pager, an alias, settings included from that
# very input (Codex review of #159).
GIT_DATA_COMMANDS = {
    "am", "apply", "cat-file", "check-attr", "check-ignore", "hash-object",
    "interpret-trailers", "mktag", "mktree", "patch-id", "stripspace", "update-index",
    "update-ref",
}  # fmt: skip
GIT_MESSAGE_COMMANDS = {"commit", "notes", "tag"}


def _git_reads_data(args: list[str]) -> bool:
    """Whether `git` with ``args`` only reads its input as data."""
    while args and args[0].startswith("-"):
        if args[0] in ("-c", "--config-env") or args[0].startswith("--config-env="):
            return False
        args = args[2:] if args[0] in (*GIT_VALUE_OPTS, "-C", "--git-dir") else args[1:]
    if not args:
        return False
    if args[0] in GIT_DATA_COMMANDS:
        return True
    rest = args[1:]
    stdin = any(
        re.fullmatch(r"-[A-Za-z]*F-|--file=-", w)
        or (re.fullmatch(r"-[A-Za-z]*F|--file", w) and rest[i + 1 : i + 2] == ["-"])
        for i, w in enumerate(rest)
    )
    edit = any(w == "--edit" or re.fullmatch(r"-[A-Za-z]*e[A-Za-z]*", w) for w in rest)
    return args[0] in GIT_MESSAGE_COMMANDS and stdin and not edit


def _reader_kind(words: list[str]) -> str:
    """What a here-document's reader does with it: "shell" (it runs it as commands),
    "interpreter" (python, node...: it can run anything and send API calls), "client"
    (curl, gh: it can send an API merge, and its other input is data), "data" (it only
    reads it) or "run" (anything else, which may run it: awk, sed, vim, ssh...)."""
    # `.` and `source` stay as they are: they run their input.
    toks = words[:1] if words[:1] in (["."], ["source"]) else unwrap(words)
    word = toks[0]
    name = _exe(word)
    if word in (".", "source") or name in (*SHELLS, *EVALS):
        return "shell"
    if CLIENT_VERSION_RE.sub("", name) in INTERPRETERS:
        return "interpreter"
    if name == "gh" or CLIENT_VERSION_RE.sub("", name) in HTTP_CLIENTS:
        return "client"
    if name == "git":
        # Nothing may come before it: an assignment or a wrapper can change what it runs.
        return "data" if toks == words and _git_reads_data(toks[1:]) else "run"
    return "data" if name in DATA_READERS else "run"


def heredocs(
    command: str,
) -> tuple[str, list[tuple[str, bool, list[list[str]], set[str]]]]:
    """The command without its here-document bodies, and each body with whether its
    delimiter is quoted (the shell expands nothing in it) and the commands that read
    it (``_readers``): the command it feeds and those its output is piped into (`cat
    <<'EOF' | bash`), never another command on the same line. A body is its readers'
    input, not commands (Codex review of #159)."""
    found: list[tuple[str, bool, list[list[str]], set[str]]] = []
    pos = 0
    while (first := next(_heredoc_operators(command, pos, len(command)), None)) is not None:
        line_start = command.rfind("\n", 0, first.start()) + 1
        line_end = command.find("\n", first.start())
        if line_end < 0:
            break
        # The bodies follow the line in the order of its `<<`s (Codex review of #159).
        cursor = line_end + 1
        for m in _heredoc_operators(command, first.start(), line_end):
            delimiter, tabs = m.group(4), m.group(1) == "-"
            end = cursor
            while end < len(command):
                row_end = command.find("\n", end)
                row_end = len(command) if row_end < 0 else row_end
                row = command[end:row_end]
                if (row.lstrip("\t") if tabs else row) == delimiter:
                    body, after = command[cursor:end], row_end + 1
                    break
                end = row_end + 1
            else:
                body, after = command[cursor:], len(command)
            readers, written = _readers(command, line_start, line_end, m.start())
            found.append((body, bool(m.group(2) or m.group(3)), readers, written))
            cursor = after
        command, pos = command[: line_end + 1] + command[cursor:], line_end + 1
    return command, found


# `merge` or `push` as a word, or GraphQL's mergePullRequest; not `submerged`, `merger`
# or `pushd` (Codex review of #159).
UNKNOWN_KINDS = {
    "merge": re.compile(r"(?<![a-z])merge(?![a-z])|mergepullrequest"),
    "push": re.compile(r"(?<![a-z])push(?![a-z])"),
}


def _unknown(text: str, why: str) -> list[Target]:
    """A command known only when it runs: a merge in it is refused (fail closed), a push
    only warned about (fail open), as when GitHub cannot be read."""
    lowered = text.lower()
    return [
        Target(kind, unknown=why) for kind, word in UNKNOWN_KINDS.items() if word.search(lowered)
    ]


# Command separators: `&&`, `||`, `;`, a pipe, a newline, a lone `&` that sends a
# command to the background (Codex review of #159: `true & gh pr merge 5`), and the
# parentheses of a subshell or a process substitution (`(gh pr merge 5)`, `<(git push)`;
# Codex review of #159). A `&` next to `>` is a redirection (`2>&1`, `&>out`), and the
# `(` of `$(` stays: substitutions() reads those. PowerShell's call operator (`& git
# push`) leaves an empty segment before its command, which is then read as before.
SEPARATORS = re.compile(r"&&|\|\||(?<![>&])&(?![&>])|[;|\n)]|(?<!\$)\(")


def segments(command: str) -> list[str]:
    """The commands of a command line, split at ``SEPARATORS`` outside quotes (Codex
    review of #159: a split inside `bash -c "gh pr merge 5; echo"` cut off its merge)."""
    quoted, parts, start, i = _quoted(command), [], 0, 0
    while i < len(command):
        if not quoted[i] and (m := SEPARATORS.match(command, i)):
            parts.append(command[start:i])
            start = i = m.end()
        else:
            i += 1
    parts.append(command[start:])
    return parts


def _assignments(words: list[str]) -> dict[str, str]:
    """The `NAME=value` words among ``words``, the last of each name winning."""
    found: dict[str, str] = {}
    for word in words:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word, re.DOTALL):
            name, _, value = word.partition("=")
            found[name] = value
    return found


def _command_env(prefix: list[str], exported: dict[str, str], removed: set[str]) -> dict[str, str]:
    """A command's environment: the hook's own, what the line exported before it and
    did not take out, then what its own prefix sets: `env -i` clears it, `env -u NAME`
    drops NAME, `NAME=value` sets it (Codex review of #159)."""
    env = {k: v for k, v in {**os.environ, **exported}.items() if k not in removed}
    for i, w in enumerate(prefix):
        if w in ("-i", "--ignore-environment") and "env" in map(_exe, prefix[:i]):
            env = {}
        elif w in ("-u", "--unset") and i + 1 < len(prefix):
            env.pop(prefix[i + 1], None)
        elif w.startswith("--unset="):
            env.pop(w.split("=", 1)[1], None)
    env.update(_assignments(prefix))
    return env


def _absolute(cwd: str, path: str) -> str:
    """``path`` as seen from ``cwd``, normalised, so two spellings of one file match."""
    return os.path.normpath(os.path.join(cwd, path))


def _is_git(word: str) -> bool:
    """`git`, or one of git's own commands run directly (`/usr/lib/git-core/git-push`,
    which pushes without the `git` dispatcher; Codex review of #159)."""
    name = _exe(word)
    return name == "git" or (name.startswith("git-") and name[4:] in GIT_BUILTINS)


# A command word known only at run time: a variable or a positional parameter, `$1`,
# `$@` or `$*` (Codex review of #159).
RUNTIME_WORD = re.compile(r"\$\{?[\w@*]")


def _env_dir(words: list[str], cwd: str) -> str:
    """The directory the leading wrappers run their command in: `env -C DIR`, `sudo -D DIR`
    or either's `--chdir` (Codex review of #159: `env -C <this repo> git push` was
    checked in another repository)."""
    i = 0
    while i < len(words):
        w, name = words[i], _exe(words[i])
        if w in PREFIX_WORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            i += 1
            continue
        if name not in WRAPPERS:
            break
        opts, chdir = WRAPPER_VALUE_OPTS.get(name, set()), WRAPPER_CHDIR_OPTS.get(name)
        i += 1
        while i < len(words) and (
            words[i].startswith("-") or WRAPPER_NUMBER_RE.fullmatch(words[i])
        ):
            o, k = words[i], _bundled_value(words[i], opts)
            if chdir and k is not None and f"-{o[k]}" == chdir[0]:
                # `env -iC DIR`, its value attached or the next word (Codex review of #159)
                value = o[k + 1 :] or (words[i + 1] if i + 1 < len(words) else "")
                cwd, i = str(Path(cwd, value)), i + (1 if o[k + 1 :] else 2)
            elif chdir and o in chdir and i + 1 < len(words):
                cwd, i = str(Path(cwd, words[i + 1])), i + 2
            elif chdir and o.startswith(chdir[1] + "="):
                cwd, i = str(Path(cwd, o.split("=", 1)[1])), i + 1
            elif chdir and o.startswith(chdir[0]) and len(o) > len(chdir[0]):
                cwd, i = str(Path(cwd, o[len(chdir[0]) :])), i + 1
            else:
                i += 2 if _takes_value(o, opts) else 1
    return cwd


# Files that are a process's own standard input.
STDIN_FILES = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
# An interpreter option followed by its program: python's -c, perl's -e or -lne,
# node's -e, -p, --eval or --print, ruby's -e, php's -r.
INLINE_CODE_RE = re.compile(r"-[A-Za-z]*[ceEpr]|--eval|--print")


def _run_time_code(exe: str, args: list[str], segment: str, command: str) -> list[Target]:
    """What a shell without `-c`, `source` or an interpreter runs is text known only
    at run time: a here-string or an interpreter's inline program (`bash <<< ...`,
    `python3 -c ...`), or, when it reads its standard input, what the rest of
    ``command`` feeds it (`echo ... | bash`, `bash <(...)`). A merge or push word in
    that text counts as unknown; a script's name is not its text (Codex review of
    #159). A here-document's body is read on its own (heredocs())."""
    code = segment.partition("<<<")[2]
    if CLIENT_VERSION_RE.sub("", exe) in INTERPRETERS:
        inline = [args[i + 1] for i, a in enumerate(args[:-1]) if INLINE_CODE_RE.fullmatch(a)]
        code = " ".join([code, *inline, *(args[1:] if args[:1] == ["eval"] else [])])
    found = _unknown(code, f"{exe} runs code known only at run time")
    stdin = (
        all(a.startswith("-") for a in args)
        or any(a in STDIN_FILES for a in args)
        or (exe in POSIX_SHELLS and "-s" in args)
    )
    if not found and stdin and next(_heredoc_operators(segment, 0, len(segment)), None) is None:
        found = _unknown(command, f"{exe} runs what it reads from its input")
    return found


def find_targets(
    command: str, cwd: str, depth: int = 0, *, posix: bool = False, root: str | None = None
) -> list[Target]:
    """Every push or merge in a shell command, with the working directory it runs in.
    What `bash -c`, `pwsh -Command`, `cmd /c`, `$(...)` or backticks run is read too, to
    MAX_DEPTH levels (automated audit, 2026-09-29).

    ``posix``: the text runs in a POSIX shell, where a lone `$cmd` runs the command it
    holds (PowerShell only prints it). ``root``: the whole command line, the only text a
    command known at run time can be judged by (Codex review of #159: in
    `cmd='gh pr merge 5'; bash -c "$cmd"` the merge is only in the outer text)."""
    root = command if root is None else root
    if depth > MAX_DEPTH:
        return _unknown(root, "a command nested too deep to read")
    command, bodies = heredocs(command)
    targets: list[Target] = []
    # The files the line runs (`bash run`, `. ./run`, `./run`), and the directory each
    # here-document's command runs in, so that a file written there and run from
    # elsewhere is the same path (Codex review of #159: `cd /tmp; cat > run <<EOF
    # ...; bash /tmp/run`).
    executed: set[str] = set()
    heredoc_dirs: list[str] = []
    removed: set[str] = set()  # variables the line takes out of the environment
    variables: dict[str, str] = {}  # the shell variables the line sets
    exported: dict[str, str] = {}  # what `export` puts in later commands' environment
    for segment in segments(command):
        heredoc_dirs += [cwd] * sum(1 for _ in _heredoc_operators(segment, 0, len(segment)))
        words = drop_redirections(split_words(segment))
        if words[:1] == ["source"] or (posix and words[:1] == ["."]):
            # They run a file, or what they read from their input (`source <(...)`);
            # PowerShell's `.` runs the command after it, which is read as before.
            executed.update(_absolute(cwd, w) for w in words[1:2])
            targets.extend(_run_time_code(words[0], words[1:], segment, command))
            continue
        toks = unwrap(words)
        prefix = words[: len(words) - len(toks)]  # what runs the command: wrappers, NAME=v
        names = [w.partition("=")[0] for w in toks[1:] if not w.startswith("-")]
        if toks[:1] == ["export"] and "-n" not in toks[1:]:
            # `export NAME=value`, or `export NAME` of a variable set before it (Codex
            # review of #159: `GIT_DIR=...; export GIT_DIR; git push`).
            variables.update(_assignments(toks[1:]))
            exported.update({n: variables[n] for n in names if n in variables})
            removed.difference_update(names)
        elif toks[:1] in (["unset"], ["export"]):
            # `unset NAME` and `export -n NAME` take it out of the environment (Codex
            # review of #159).
            for name in names:
                exported.pop(name, None)
                if toks[0] == "unset":
                    variables.pop(name, None)
            removed.update(names)
        elif not toks:  # a plain assignment sets a variable, and an exported one's value
            variables.update(_assignments(words))
            inherited = {k for k in os.environ if k not in removed}
            exported.update({k: v for k, v in variables.items() if k in exported or k in inherited})
        if not toks:
            continue
        exe = _exe(toks[0])
        if "/" in toks[0] or "\\" in toks[0]:
            executed.add(_absolute(cwd, toks[0]))  # `./run`, `/tmp/run`
        if exe in SHELLS or CLIENT_VERSION_RE.sub("", exe) in INTERPRETERS:
            executed.update(_absolute(cwd, a) for a in toks[1:] if not a.startswith("-"))
        if exe != "git" and _is_git(exe):
            exe, toks = "git", ["git", exe[4:], *toks[1:]]
        base = _env_dir(words, cwd)
        if exe in ("cd", "set-location", "pushd", "sl") and len(toks) > 1:
            cwd = str(Path(cwd, toks[-1]))
        elif exe == "git":
            work, git_dir, rest, aliases = base, "", toks[1:], {}
            unknown_aliases: set[str] = set()
            # The repository is the git directory that --git-dir or GIT_DIR names, read
            # from where -C leaves git, or that place itself: git runs fine inside a git
            # directory (Codex review of #159: `cd other && git --git-dir <this
            # repo>/.git push` was checked against the other repository, and so was
            # `git --git-dir <this repo>/.git -C other push`).
            # Git's environment: the hook's own, what the line exported before this
            # command, then this command's own assignments; never a later one (Codex
            # review of #159).
            env = _command_env(prefix, exported, removed)
            git_dir = env.get("GIT_DIR", "")
            while rest and rest[0].startswith("-"):
                if rest[0] == "-C" and len(rest) > 1:
                    work, rest = str(Path(work, rest[1])), rest[2:]
                elif rest[0] == "--git-dir" and len(rest) > 1:
                    git_dir, rest = rest[1], rest[2:]
                elif rest[0].startswith("--git-dir="):
                    git_dir, rest = rest[0].split("=", 1)[1], rest[1:]
                elif rest[0].startswith("--config-env=") or (
                    rest[0] == "--config-env" and len(rest) > 1
                ):
                    # `--config-env=alias.p=VAR` takes the alias from git's environment;
                    # one it cannot read could be anything (Codex review of #159).
                    attached = rest[0].startswith("--config-env=")
                    key, _, variable = (rest[0][13:] if attached else rest[1]).partition("=")
                    if key.lower().startswith("alias."):
                        name = key[len("alias.") :].lower()
                        value = env.get(variable)
                        if value is None:
                            unknown_aliases.add(name)
                        else:
                            aliases[name] = value
                    rest = rest[1:] if attached else rest[2:]
                elif rest[0] in GIT_VALUE_OPTS and len(rest) > 1:
                    # Setting names are case-insensitive: `-c ALIAS.P=push` defines `p`.
                    if rest[0] == "-c" and rest[1].lower().startswith("alias."):
                        name, _, value = rest[1][len("alias.") :].partition("=")
                        aliases[name.lower()] = value
                    rest = rest[2:]
                else:
                    rest = rest[1:]
            here = str(Path(work, git_dir)) if git_dir else work
            # An alias, given with -c or configured, runs what it expands to, through any
            # number of aliases (git stops only at a loop) and past the options one may
            # begin with; a `!` alias runs its text in a shell (Codex review of #159).
            seen: set[str] = set()
            while rest and rest[0] not in GIT_BUILTINS and rest[0] not in seen:
                seen.add(rest[0])
                if rest[0].lower() in unknown_aliases:
                    # Its text is known only at run time: any push, and a merge if the
                    # line names one, counts.
                    targets.append(Target("push", every_branch=True))
                    targets.extend(_unknown(root, "a git alias set from the environment"))
                    rest = []
                    break
                alias = aliases.get(rest[0].lower()) or _git(
                    here, "config", "--get", f"alias.{rest[0]}"
                )
                if not alias:
                    break
                if alias.startswith("!"):
                    line = " ".join([alias[1:], *rest[1:]])
                    targets.extend(find_targets(line, here, depth + 1, posix=True, root=root))
                    rest = []
                else:
                    rest = [*split_words(alias), *rest[1:]]
                    while rest and rest[0].startswith("-"):
                        rest = rest[2:] if rest[0] in GIT_VALUE_OPTS else rest[1:]
            if rest and rest[0] in ("push", "send-pack"):
                targets.extend(push_targets(rest[1:], here))
        elif exe == "gh":
            # GH_REPO names the repository when no -R does (Codex review of #159).
            gh_repo = _command_env(prefix, exported, removed).get("GH_REPO")
            targets.extend(_gh_targets(toks[1:], segment, base, gh_repo))
        elif exe in SHELLS:
            found = shell_command(exe, toks[1:])
            if found is not None:
                inner, params = found
                inner = _positional(inner, params) if params else inner
                shell = exe in POSIX_SHELLS
                targets.extend(find_targets(inner, base, depth + 1, posix=shell, root=root))
            else:
                targets.extend(_run_time_code(exe, toks[1:], segment, command))
        elif exe in LAUNCHERS:
            targets.extend(_unknown(root, f"{exe} runs a command known only at run time"))
        elif CLIENT_VERSION_RE.sub("", exe) in INTERPRETERS:
            # An API call that names its PR counts, and so does a merge word in the
            # code it runs (`subprocess.run(["gh", "pr", "merge", "5"])`).
            targets.extend(_rest_merge_targets(segment, base, None))
            targets.extend(_run_time_code(exe, toks[1:], segment, command))
        elif CLIENT_VERSION_RE.sub("", exe) in HTTP_CLIENTS and (
            "/merge" in segment or "mergePullRequest" in segment
        ):
            # curl, python and other clients can call the same REST or GraphQL merge.
            targets.extend(_rest_merge_targets(segment, base, None))
        elif exe in EVALS and not any(c in "".join(toks[1:]) for c in "$`\\"):
            # `eval "gh pr merge 5"` runs literal text: read it as the command it is
            # (Codex review of #159: `eval 'echo submerged'` was refused as a merge).
            body = " ".join(toks[1:])
            targets.extend(find_targets(body, base, depth + 1, posix=posix, root=root))
        elif exe in EVALS or ((len(toks) > 1 or posix) and RUNTIME_WORD.match(toks[0])):
            # `eval "$cmd"`, `iex $cmd`, `& $gh pr merge 5`: the text of the whole command
            # line is all there is to go on. A lone `$x` runs nothing in PowerShell (it
            # prints), but runs `$x` in a POSIX shell.
            targets.extend(_unknown(root, f"{toks[0]} runs a command known only at run time"))
    inners = substitutions(command)
    for index, (body, quoted, readers, written) in enumerate(bodies):
        kinds = {_reader_kind(words) for words in readers}
        where = heredoc_dirs[index] if index < len(heredoc_dirs) else cwd
        if {_absolute(where, path) for path in written} & executed:
            # Written to a file that a later command runs (`cat > run <<EOF ...; bash
            # run`): the body is read as that command's code (Codex review of #159).
            kinds.add("run")
        if kinds & {"shell", "run"}:
            # Read as commands, where its reader runs them (`env -C DIR bash <<EOF`): a
            # shell, `source`, ssh or anything unknown may run it.
            runners = [w for w in readers if _reader_kind(w) in ("shell", "run")]
            here = _env_dir(runners[0], cwd) if runners else cwd
            targets.extend(find_targets(body, here, depth + 1, posix=posix, root=root))
        elif not quoted:
            inners.extend(substitutions(body, quotes=False))
        if kinds & {"interpreter", "client"}:
            # `python3 - <<EOF`, `gh api --input -`: the body can send an API merge.
            targets.extend(_rest_merge_targets(body, cwd, None))
        if kinds & {"interpreter", "run"}:
            # A program that runs commands in its own language (`subprocess.run`, awk's
            # `system()`, vim's `!`) may run more than the scan reads, so a merge or push
            # word in its input is a command known only at run time, whatever else is
            # found (Codex review of #159). A shell's input is read exactly, so `bash`
            # echoing "merge" is not refused.
            targets.extend(_unknown(body, "a program that can run commands reads this"))
    for inner in inners:
        targets.extend(find_targets(inner, cwd, depth + 1, posix=posix, root=root))
    return targets


def _gh_targets(
    toks: list[str], segment: str, cwd: str, env_repo: str | None = None
) -> list[Target]:
    """Merges in a `gh` command. The option scan knows which words are option values, so
    a body or subject that reads `-R` or `--repo=...` is never taken for the repository
    (automated review at 3875759: that silently skipped the claim check). A global
    `-R`/`--repo` before the subcommand counts too (automated review at 987702a), and so
    does ``env_repo``, the command's GH_REPO, when no flag names one."""
    global_repo: str | None = env_repo
    while toks and toks[0].startswith("-"):
        if toks[0] in ("-R", "--repo") and len(toks) > 1:
            global_repo, toks = toks[1], toks[2:]
        elif toks[0].startswith("--repo="):
            global_repo, toks = toks[0].split("=", 1)[1], toks[1:]
        elif toks[0].startswith("-R"):  # attached: `-Rowner/repo` (Codex review of #159)
            global_repo, toks = toks[0][2:].removeprefix("="), toks[1:]
        else:
            toks = toks[1:]
    if toks[:1] == ["api"]:
        return _rest_merge_targets(segment, cwd, global_repo)
    if toks[:2] != ["pr", "merge"]:
        return []
    repo_flag: str | None = None
    arg: str | None = None
    pending: str | None = None  # the option whose value is the next word
    for t in toks[2:]:
        if pending is not None:
            if pending in ("-R", "--repo"):
                repo_flag = t
            pending = None
        elif t in GH_MERGE_VALUE_OPTS:
            pending = t
        elif t.startswith("--repo="):
            repo_flag = t.split("=", 1)[1]
        elif t.startswith("-R") and len(t) > 2:  # attached: `-Rowner/repo`
            repo_flag = t[2:].removeprefix("=")
        elif not t.startswith("-") and arg is None:
            arg = t
    repo_flag = repo_flag if repo_flag is not None else global_repo
    if not is_this_repo(repo_flag or _git(cwd, "remote", "get-url", "origin")):
        return []
    if arg is None:
        branch = current_branch(cwd)
        return [Target("merge", branch=branch, unknown=None if branch else "no PR named")]
    if COMPUTED_RE.search(arg):
        return [Target("merge", unknown=f"the PR {arg!r} is known only at run time")]
    # A PR URL may carry a tab path (/files), ?query, #fragment or a trailing slash
    # after the number, as gh accepts (automated reviews at f3f334a and 01c221f).
    number = re.search(r"/pull/(\d+)(?:[/?#]|$)", arg) or re.fullmatch(r"(\d+)", arg)
    return [Target("merge", pr=int(number.group(1)))] if number else [Target("merge", branch=arg)]


def _rest_merge_targets(segment: str, cwd: str, global_repo: str | None) -> list[Target]:
    """REST or GraphQL merges in any client's command (`gh api`, curl, python...).
    `{owner}`/`{repo}` placeholders are filled the way gh does, from -R or the
    checkout (automated review at 6b88b44). A merge whose repository cannot be
    resolved is refused, never skipped."""
    out: list[Target] = []
    for owner, name, n in re.findall(
        r"repos/([^/\s'\"]+)/([^/\s'\"]+)/pulls/(\d+)/merge\b", segment
    ):
        repo = f"{owner}/{name}"
        if "{" in repo:
            ours = is_this_repo(global_repo or _git(cwd, "remote", "get-url", "origin"))
        else:
            ours = is_this_repo(repo)
        if ours:
            out.append(Target("merge", pr=int(n)))
    if out:
        return out
    if re.search(r"pulls/\d+/merge\b", segment) and "repos/" not in segment:
        return [Target("merge", unknown="a merge path without repos/<owner>/<repo>/")]
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
    # A git alias need not say "push", and PowerShell runs `Git` as git (Codex review of
    # #159), so any git command is read, whatever its case.
    if not any(word in command.lower() for word in ("push", "merge", "git")):
        return None
    cwd = str(payload.get("cwd") or os.getcwd())
    targets = find_targets(command, cwd, posix=payload.get("tool_name") == "Bash")
    if not targets:
        return None
    session_id = str(payload.get("session_id") or "")
    me = f"Claude Code {session_id[:8]}" if session_id else None
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
                same_repo = ((head.get("repo") or {}).get("full_name") or "").lower() == REPO
                if same_repo and (
                    head.get("ref") in wanted or any(t.every_branch for t in targets)
                ):
                    numbers.add(int(pr["number"]))
        for number in sorted(numbers):
            state = evaluate(fetch_comments(number, reader), now)
            c = state.active
            if c and not is_own(c.holder, session_id):
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


def is_own(holder: str, session_id: str) -> bool:
    """A claim is this session's when its tag names this session: the usual first 8
    characters of the id, or any longer prefix up to the full id (Bob at b00a461)."""
    prefix = "Claude Code "
    if not session_id or not holder.startswith(prefix):
        return False
    tag = holder[len(prefix) :]
    return len(tag) >= 8 and session_id.startswith(tag)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "claims: " + reason,
        }
    }


# --- The workflow --------------------------------------------------------------------


def workflow(event: dict[str, Any], now: datetime) -> list[str]:
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
        try:
            answer = hook_decision(payload, now=now)
        except Exception as e:  # a crash must never let a merge through
            command = str((payload.get("tool_input") or {}).get("command") or "")
            reason = f"the claims check failed ({type(e).__name__})"
            answer = (
                _deny(f"{reason}, so the merge is refused (fail closed).")
                if "merge" in command.lower()
                else {"systemMessage": f"claims: {reason}; the command is allowed"}
            )
        if answer:
            print(json.dumps(answer))
        return 0
    if args.cmd == "workflow":
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
            event = json.load(f)
        for line in workflow(event, now):
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
