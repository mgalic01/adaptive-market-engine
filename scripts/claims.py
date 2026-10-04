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
        if COMPUTED_RE.search(spec):
            out.append(Target("push", unknown=f"the branch {spec!r} is known only at run time"))
            continue
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
WRAPPERS = {"env", "timeout", "nohup", "nice", "time", "command", "exec"}
# Wrapper options that take the next word as their value (env, timeout, nice, exec and
# GNU time); `env -C sub gh pr merge 5` was read as running `sub` (Codex review of #159).
WRAPPER_VALUE_OPTS = {
    "-u",
    "--unset",
    "-C",
    "--chdir",
    "-P",
    "-s",
    "--signal",
    "-k",
    "--kill-after",
    "-n",
    "--adjustment",
    "-a",
    "-f",
    "--format",
    "-o",
    "--output",
}
# `env -S 'gh pr merge 5'` (or -S'...', --split-string=...) runs the words of its value.
SPLIT_STRING_RE = re.compile(r"(?:-S|--split-string=?)(.*)", re.DOTALL)
WRAPPER_NUMBER_RE = re.compile(r"\d[\d.]*[smhd]?")  # `timeout 60`, `timeout 1.5m`
POSIX_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
SHELLS = (*POSIX_SHELLS, "pwsh", "powershell", "cmd")
EVALS = ("eval", "iex", "invoke-expression")
MAX_DEPTH = 3  # how deep `bash -c "pwsh -Command '...'"` and `$(...)` are read


def unwrap(words: list[str]) -> list[str]:
    """The command without what runs it: `VAR=1`, PowerShell's `$out =`, `& git` or
    `&git`, a shell keyword, or a wrapper with its options (`timeout -s KILL 60`)."""
    while words:
        w = words[0]
        if w in PREFIX_WORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            words = words[1:]
        elif w.startswith("$") and words[1:2] == ["="]:
            words = words[2:]
        elif w.startswith("&"):
            words = [w[1:], *words[1:]]
        elif _exe(w) in WRAPPERS:
            words = words[1:]
            while words and (words[0].startswith("-") or WRAPPER_NUMBER_RE.fullmatch(words[0])):
                if split := SPLIT_STRING_RE.fullmatch(words[0]):
                    if split[1]:
                        value, rest = split[1], words[1:]
                    else:
                        value, rest = (words[1] if len(words) > 1 else ""), words[2:]
                    words = [*split_words(value), *rest]
                    break
                words = words[2:] if words[0] in WRAPPER_VALUE_OPTS else words[1:]
        else:
            break
    return words


def shell_command(exe: str, args: list[str]) -> str | None:
    """The command string that `bash -c`, `pwsh -Command` or `cmd /c` runs, or None."""
    for i, a in enumerate(args):
        if exe in POSIX_SHELLS and re.fullmatch(r"-[a-z]*c[a-z]*", a):  # -c, -lc, -ec
            return args[i + 1] if i + 1 < len(args) else None
        name = a.lower().lstrip("-/") if a[:1] in ("-", "/") else ""
        if exe in ("pwsh", "powershell") and name and "command".startswith(name):
            return " ".join(args[i + 1 :])
        if exe == "cmd" and a[:1] == "/" and name in ("c", "k"):
            return " ".join(args[i + 1 :])
    return None


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
        elif quotes and c in "'\"" and quote in ("", c):
            quote = "" if quote else c
        elif quote != "'" and c == "`":
            end = command.find("`", i + 1)
            if end < 0:
                break
            found.append(command[i + 1 : end])
            i = end
        elif quote != "'" and command.startswith("$(", i):
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
    escaped by a backslash. There `;`, `&`, `|`, `<<` and `#` are no operators."""
    mask = [False] * len(command)
    quote, i = "", 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            mask[i : i + 2] = [True] * len(mask[i : i + 2])
            i += 2
            continue
        if c in "'\"" and quote in ("", c):
            quote = "" if quote else c
            mask[i] = True
        else:
            mask[i] = bool(quote)
        i += 1
    return mask


def _heredoc_operators(command: str, start: int, end: int) -> Iterator[re.Match[str]]:
    """The here-document operators the shell sees in ``command[start:end]``. One inside
    quotes, escaped or in a comment is text (Codex review of #159: `echo "<<EOF"` and
    `# <<EOF` each hid the merge on the next line as a body)."""
    quoted, i = _quoted(command), start
    while i < end:
        if quoted[i]:
            i += 1
        elif command[i] == "#" and (i == 0 or command[i - 1] in " \t\n;&|("):
            line_end = command.find("\n", i, end)  # a comment runs to the end of its line
            i = end if line_end < 0 else line_end
        elif m := HEREDOC_RE.match(command, i, end):
            yield m
            i = m.end()
        else:
            i += 1


def heredocs(command: str) -> tuple[str, list[tuple[str, bool, str]]]:
    """The command without its here-document bodies, and each body with whether its
    delimiter is quoted (the shell expands nothing in it) and the text before the `<<`
    on its line, which names the reader. A body is the reader's input, not commands
    (Codex review of #159)."""
    found: list[tuple[str, bool, str]] = []
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
            found.append((body, bool(m.group(2) or m.group(3)), command[line_start : m.start()]))
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


# Command separators: `&&`, `||`, `;`, a pipe, a newline, and a lone `&` that sends a
# command to the background (Codex review of #159: `true & gh pr merge 5`). A `&` next to
# `>` is a redirection (`2>&1`, `&>out`); PowerShell's call operator (`& git push`) leaves
# an empty segment before its command, which is then read as before.
SEPARATORS = re.compile(r"&&|\|\||(?<![>&])&(?![&>])|[;|\n]")


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


# A command word known only at run time: a variable.
RUNTIME_WORD = re.compile(r"\$\{?\w")


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
    for segment in segments(command):
        toks = unwrap(drop_redirections(split_words(segment)))
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
        elif exe in SHELLS:
            inner = shell_command(exe, toks[1:])
            if inner is not None:
                shell = exe in POSIX_SHELLS
                targets.extend(find_targets(inner, cwd, depth + 1, posix=shell, root=root))
        elif "/merge" in segment or "mergePullRequest" in segment:
            # curl, python and other clients can call the same REST or GraphQL merge.
            targets.extend(_rest_merge_targets(segment, cwd, None))
        elif exe in EVALS and not any(c in "".join(toks[1:]) for c in "$`\\"):
            # `eval "gh pr merge 5"` runs literal text: read it as the command it is
            # (Codex review of #159: `eval 'echo submerged'` was refused as a merge).
            body = " ".join(toks[1:])
            targets.extend(find_targets(body, cwd, depth + 1, posix=posix, root=root))
        elif exe in EVALS or ((len(toks) > 1 or posix) and RUNTIME_WORD.match(toks[0])):
            # `eval "$cmd"`, `iex $cmd`, `& $gh pr merge 5`: the text of the whole command
            # line is all there is to go on. A lone `$x` runs nothing in PowerShell (it
            # prints), but runs `$x` in a POSIX shell.
            targets.extend(_unknown(root, f"{toks[0]} runs a command known only at run time"))
    inners = substitutions(command)
    for body, quoted, reader in bodies:
        # Shell words, so that `/bin/'bash' <<EOF` is bash (Codex review of #159).
        if any(_exe(w) in (*SHELLS, *EVALS) for w in split_words(reader)):
            inners.append(body)  # `bash <<EOF` runs its body
        elif not quoted:
            inners.extend(substitutions(body, quotes=False))
    for inner in inners:
        targets.extend(find_targets(inner, cwd, depth + 1, posix=posix, root=root))
    return targets


def _gh_targets(toks: list[str], segment: str, cwd: str) -> list[Target]:
    """Merges in a `gh` command. The option scan knows which words are option values, so
    a body or subject that reads `-R` or `--repo=...` is never taken for the repository
    (automated review at 3875759: that silently skipped the claim check). A global
    `-R`/`--repo` before the subcommand counts too (automated review at 987702a)."""
    global_repo: str | None = None
    while toks and toks[0].startswith("-"):
        if toks[0] in ("-R", "--repo") and len(toks) > 1:
            global_repo, toks = toks[1], toks[2:]
        elif toks[0].startswith("--repo="):
            global_repo, toks = toks[0].split("=", 1)[1], toks[1:]
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
    if "push" not in command and "merge" not in command and "Merge" not in command:
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
