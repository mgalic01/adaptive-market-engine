"""Mechanical checks on the review index and on Bob's reports, run in CI.

Each check here once cost a review round (PRs #40, #59, #60, #65, #66, #89, #100):

* every row of the frozen legacy table in ``docs/reviews/README.md`` links to a file
  that exists, and the table itself is unchanged (pinned by ``LEGACY_SHA256``);
* every review file outside that table carries its own index entry: a ``# Title`` first
  line and exactly one ``Index:`` line near the top. ``--index`` prints the whole index,
  newest first, from those entries and the legacy table. Nothing generated is committed,
  so two PRs that each add a review file never edit the same line;
* every index row in ``docs/reviews/README.md`` links to a file that exists, no target
  is listed twice, and every review file is indexed;
* every SHA-256 a review states for a ``*.py`` path is accounted for: either a fenced
  block in the same review hashes to it, or the review's mismatch is corrected in place
  with the real digest written out, or the pair is listed in ``UNVERIFIABLE`` below with
  a reason. A stated hash that is none of those three is an error;
* Bob reports fence script sources as ``text``: ``ruff format`` rewrites ``python``
  blocks in Markdown, which would change the hashed source;
* with ``--changed`` (a Bob task branch), the branch adds only its one report and
  leaves the index unchanged.

Nothing here is allowed to pass quietly: every run prints the verified, corrected and
unverifiable pins by name, and the three counts sum to every pin found. A pin is a
``*.py`` path in backticks with a SHA-256 beside it; a path named without one is a
mention, counted and printed as information. In a Bob report a mention of a ``data/``
script is an error unless the pair is listed in ``UNVERIFIABLE``: those scripts live in
a git-ignored directory, so the report's hash is the only record of what ran.

Judgement stays with the reviewers; this only removes the checks a script can do.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REVIEWS = Path("docs/reviews")
INDEX = REVIEWS / "README.md"
# The link in a row's first cell, with any "#anchor" dropped. Emphasis or other text
# may precede it: a row written "| **[x](y)** |" must not read as having no link.
ROW_LINK = re.compile(r"^\|[^|\n]*?\[[^\]]*\]\(([^)\s#]+)(?:#[^)\s]*)?\)", re.MULTILINE)
# A pinned artifact is named by its repository-relative path in backticks, at any
# heading level, in a table, or in prose. The "/" is required: a bare `events.py`
# inside a sentence is a mention, not a pin, and pairing it with the next digest on
# the line mispairs corrections with the hash they correct.
PIN_PATH = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_.-]+\.py)`")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*)$", re.MULTILINE)
FENCE = re.compile(r"^```(\w*)[ \t]*$", re.MULTILINE)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
BOB_REPORT = re.compile(r"docs/reviews/[0-9]{4}-[0-9]{2}-[0-9]{2}-bob-[A-Za-z0-9._-]+\.md")
BOB_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-bob-[A-Za-z0-9._-]+\.md")
CORRECTION = "Correction at review"
# The legacy table was frozen on 2026-09-27 at main c3c8e25, with 83 rows. This is the
# SHA-256 of every README line that starts with "|", joined with "\n" plus a final "\n".
# It changes only if someone adds or edits a table row, which is exactly what the freeze
# forbids: a row added by every PR at the same place made each merge conflict every PR.
LEGACY_SHA256 = "eb915343394ef3f8a9f104f21c42f830186f6001a61ff3a72c849064eeec5c21"
DATED_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-[A-Za-z0-9._-]+\.md")
INDEX_LINE = re.compile(r"Index:[ \t]*(.*?)[ \t]*")
ENTRY_LINES = 20  # the Index: line must be within a file's first ENTRY_LINES lines
HOW_TO = "give the file a '# Title' first line and one 'Index: <summary>' line near the top"


@dataclass(frozen=True)
class Entry:
    date: str
    name: str
    title: str
    summary: str


# How far after the path a digest may sit and still be the digest of that path.
WINDOW = 200

_NO_SOURCE = (
    "merged before this check existed; `data/` is git-ignored, the source is in no "
    "commit and the report carries no appendix, so nothing in the repository can "
    "confirm this digest"
)
# Hashes stated for a script that no appendix carries and no commit holds. ``data/``
# is git-ignored by policy, so requiring the file on disk would make the check
# host-dependent and vacuous in CI; the only in-repo evidence for a ``data/`` script
# is its appendix. Each entry is therefore a one-time, reviewed admission that a
# named digest in a named document cannot be checked, and every run prints it. The
# entry lives here, in reviewed code, and not in the document, so that a document
# cannot exempt itself; the digest is part of the entry, so an entry cannot be
# re-pointed at a different artifact without a new review. An entry that no longer
# matches a stated hash is an error, so this cannot rot into a blanket exemption.
UNVERIFIABLE: dict[tuple[str, str], tuple[str, str]] = {
    ("2026-09-25-bob-dev-data-inventory.md", "data/inventory.py"): (
        "790c6f8b7b69db7a8fe7ae67a1eea848b3451fcdc19d984a1d70b97902bb0006",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/analyze.py"): (
        "a98f4d37d07d5cb17780b252dbaa88a4dd3c287f4b944d080020be27709d7110",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/analyze_details.py"): (
        "534b73631aecef434f0e1f7c1ffbd427a925957649855ba0947386aaed822e7e",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/inspect_csv.py"): (
        "9110fe20bd5f665bb764fca46ee90111501d02283e17b5683a7f8821bc77b300",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/check_proposal.py"): (
        "4f234505c09ca417014be97f29bae18bba18b9daf404ab411084409ff5bc983f",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/check_early.py"): (
        "d7105064e977a2b537c78f4de4797fe383330813736bc8a9553304738b955341",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-dev-data-inventory.md", "data/generate_summary_table.py"): (
        "5073ee3c778a71e72fc337baebb6b43d0cbda9e90b731454d182c9266331a2f3",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-docs-audit.md", "data/links.py"): (
        "0bb844577884ecb1e9eb10c9d7a2faaa05161680ff1ff2851ee83fcf6450a80e",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-docs-audit.md", "data/check_review_index.py"): (
        "ca5350088f3b54bbfc75b12963054a2c0017884ae091942253ce839c0d8c186c",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-docs-audit.md", "data/check_task_index.py"): (
        "1279a2e647ff8a63d31f22fecd729f85c4e5b632121e7a3c70658c571c306782",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-test-suite-audit.md", "data/untested.py"): (
        "db563af487b88c11c7f5cc9875e16745989aa81e5cffd88c665a05454ab0c17f",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-test-suite-audit.md", "data/spot_check.py"): (
        "65dd777956b29b08db4827a6de0c505b9ee6d35e6c47790362065616e8db7e32",
        _NO_SOURCE,
    ),
    ("2026-09-25-bob-v0-dev-scorecard.md", "data/score.py"): (
        "8324d14b275e672e1e29d2511609144fe4c2a610cc44de5c091d4ce222d04c2b",
        _NO_SOURCE,
    ),
    ("2026-09-26-bob-hourly-defect-calendar.md", "data/generate_report_tables.py"): (
        "595c21467ad57d0b448d992f37c9af5d6f6ca4c9137d0a68fcd15f1f428a061a",
        "merged before this check existed; the report appendices carry `data/calendar.py` "
        "and `data/events.py` only, and this script's source is in no commit",
    ),
}


def index_links(text: str) -> list[str]:
    return ROW_LINK.findall(text)


def table_lines(readme: str) -> list[str]:
    return [line for line in readme.splitlines() if line.startswith("|")]


def legacy_digest(readme: str) -> str:
    return hashlib.sha256(("\n".join(table_lines(readme)) + "\n").encode("utf-8")).hexdigest()


def check_frozen(readme: str, expected: str = LEGACY_SHA256) -> list[str]:
    """The legacy table must stay exactly as frozen: no new, edited or removed rows."""
    actual = legacy_digest(readme)
    if actual == expected:
        return []
    return [
        f"the legacy table in {INDEX.as_posix()} changed (SHA-256 {actual}, pinned "
        f"{expected}); it is frozen: do not add or edit rows, {HOW_TO}"
    ]


def read_entry(path: Path) -> tuple[Entry | None, list[str]]:
    """The file's own index entry, or the problems with it.

    ``(None, [])`` means the file has no ``Index:`` line in its first lines at all.
    """
    lines = path.read_text(encoding="utf-8").removeprefix("﻿").splitlines()
    found = [m.group(1) for line in lines[:ENTRY_LINES] if (m := INDEX_LINE.fullmatch(line))]
    if not found:
        return None, []
    errors = []
    dated = DATED_NAME.fullmatch(path.name)
    if dated is None:
        errors.append(f"{path.name}: an indexed review is named YYYY-MM-DD-<author>-<topic>.md")
    title = lines[0][2:].strip() if lines[0].startswith("# ") else ""
    if not title:
        errors.append(f"{path.name}: the first line must be the '# Title' heading")
    if len(found) != 1:
        errors.append(f"{path.name}: {len(found)} 'Index:' lines in the first {ENTRY_LINES}")
    elif not found[0]:
        errors.append(f"{path.name}: the 'Index:' line is empty")
    if errors or dated is None:
        return None, errors
    return Entry(dated.group(1), path.name, title, found[0]), []


def check_index(reviews: Path = REVIEWS) -> list[str]:
    """Every legacy link resolves; every other review file has one valid entry."""
    links = index_links((reviews / "README.md").read_text(encoding="utf-8"))
    errors = [
        f"index links a missing file: {link}" for link in links if not (reviews / link).is_file()
    ]
    # ``links`` is a list, so a target listed twice passed before: two rows for one
    # file are two different claims about its status, and the second is invisible.
    errors += [
        f"index lists {link} in {count} rows; a file gets one row"
        for link, count in sorted(Counter(links).items())
        if count > 1
    ]
    for path in sorted(p for p in reviews.glob("*.md") if p.name != "README.md"):
        entry, problems = read_entry(path)
        errors += problems
        if path.name in links:
            if entry is not None or problems:
                errors.append(f"{path.name}: has a legacy row and an 'Index:' line; keep one")
        elif entry is None and not problems:
            errors.append(f"review file not in the index: {path.name}; {HOW_TO}")
    return errors


def cell(text: str) -> str:
    """Escape text for one Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def link_text(text: str) -> str:
    return cell(text).replace("[", "\\[").replace("]", "\\]")


def build_index(reviews: Path = REVIEWS) -> str:
    """The whole handoff index, newest first: generated rows, then the legacy table.

    Deterministic: generated rows sort by date (newest first), then by file name, never
    by directory order or modification time. A file whose entry is missing or malformed
    is listed at the end rather than dropped, so a reader sees that something is wrong.
    """
    readme = (reviews / "README.md").read_text(encoding="utf-8")
    legacy = set(index_links(readme))
    entries: list[Entry] = []
    broken: list[str] = []
    for path in sorted(p for p in reviews.glob("*.md") if p.name != "README.md"):
        if path.name in legacy:
            continue
        entry, _ = read_entry(path)
        if entry is None:
            broken.append(path.name)
        else:
            entries.append(entry)
    entries.sort(key=lambda e: e.name)
    entries.sort(key=lambda e: e.date, reverse=True)
    out = [
        "# Agent handoff index (generated; do not commit)",
        "",
        "Printed by `python scripts/check_reports.py --index`: each review's own `Index:`",
        "line, newest first, then the frozen legacy table of `docs/reviews/README.md`.",
        "Links are relative to `docs/reviews/`.",
        "",
        "| Handoff | Status / purpose |",
        "| --- | --- |",
        *(f"| [{link_text(e.title)}]({e.name}) | {e.date}: {cell(e.summary)} |" for e in entries),
        *(line for line in table_lines(readme) if index_links(line)),
    ]
    if broken:
        out += ["", "Review files without a valid index entry (run check_reports.py):", ""]
        out += [f"- [{name}]({name})" for name in broken]
    return "\n".join(out) + "\n"


def fenced_blocks(text: str) -> list[tuple[int, str, str]]:
    """(start offset, language, body) of each fenced block; the body keeps its newlines."""
    blocks = []
    marks = list(FENCE.finditer(text))
    i = 0
    while i + 1 < len(marks):
        opening, closing = marks[i], marks[i + 1]
        body = text[opening.end() + 1 : closing.start()]
        blocks.append((opening.start(), opening.group(1), body))
        i += 2
    return blocks


def fence_marks(text: str) -> int:
    return len(FENCE.findall(text))


def sections(text: str) -> list[tuple[str, int, int]]:
    """(heading line, body start, body end) for every heading, nested by level.

    A section ends at the next heading of the same or a higher level, so an appendix
    written as ``## Appendix`` + ``### 1. `data/x.py``` gives each script its own body.
    """
    found = []
    # A ``#`` line inside a fenced block is a comment in the fenced source, not a
    # heading; Bob's ``text``-fenced Python carries them.
    fenced = [(start, start + len(body)) for start, _, body in fenced_blocks(text)]
    heads = [
        head
        for head in HEADING.finditer(text)
        if not any(start <= head.start() <= end for start, end in fenced)
    ]
    for i, head in enumerate(heads):
        level = len(head.group(1))
        end = len(text)
        for later in heads[i + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        found.append((head.group(0), head.end(), end))
    return found


def stated_hashes(text: str) -> list[tuple[str, str, str]]:
    """(path, digest, line) for every ``path.py`` in backticks with a digest beside it.

    The digest is looked for after the path first, then — only on the same line, and
    only when nothing follows it — before the path. A table written
    ``| SHA-256 | Script |`` puts the digest in the earlier column, and searching
    forward alone let such a pin through unchecked.

    Either way the search stops at the neighbouring pinned path, so a table row cannot
    borrow another row's digest and a correction naming a second script cannot steal its
    hash.
    """
    pins = []
    for match in PIN_PATH.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        after = text[match.end() : match.end() + WINDOW]
        following = PIN_PATH.search(after)
        if following:
            after = after[: following.start()]
        digest = HEX64.search(after)
        if digest is None:
            # Same line only: a digest on an earlier line belongs to earlier prose, and
            # a path is never far from its own hash in a table row.
            before = text[line_start : match.start()]
            preceding = list(PIN_PATH.finditer(before))
            if preceding:
                before = before[preceding[-1].end() :]
            found = list(HEX64.finditer(before))
            digest = found[-1] if found else None
        if digest is None:
            continue
        line_end = text.find("\n", match.end())
        pins.append(
            (
                match.group(1),
                digest.group(0),
                text[line_start : line_end if line_end >= 0 else len(text)],
            )
        )
    return pins


def hashless_mentions(text: str) -> list[str]:
    """Distinct ``*.py`` paths named in backticks with no digest beside them, in order."""
    pinned = {script for script, _, _ in stated_hashes(text)}
    seen: list[str] = []
    for match in PIN_PATH.finditer(text):
        script = match.group(1)
        if script not in pinned and script not in seen:
            seen.append(script)
    return seen


def check_report(
    path: Path, checked: list[str] | None = None, mentions: list[str] | None = None
) -> list[str]:
    """Problems in one review; appends one line per stated hash to ``checked``.

    Every stated hash ends up in exactly one of three states, all of them printed:
    ``verified`` (a fenced block in this review hashes to it), ``corrected`` (the
    review says on the same line that the appendix hashes to some other digest, and
    it does), or ``unverifiable`` (listed in ``UNVERIFIABLE``). Anything else errors.

    A review that states no hash for a ``*.py`` path is a no-op: the ``text`` fence
    rule exists only to stop ``ruff format`` rewriting a block whose SHA-256 the
    review pins, so it is not imposed on prose that pins nothing.
    """
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    pins = stated_hashes(text)
    blocks = fenced_blocks(text)
    # An appendix is a heading that names a path and carries a fenced block. A heading
    # that merely names a path ("Why `src/x.py` broke") pins nothing and is left alone.
    named = {
        found.group(1)
        for heading, start, end in sections(text)
        for found in PIN_PATH.finditer(heading)
        if any(start <= b[0] < end for b in blocks)
    }
    unhashed = hashless_mentions(text)
    if mentions is not None:
        mentions += [f"{path.name}:{script}" for script in unhashed]
    if BOB_NAME.fullmatch(path.name):
        # Bob's scripts live in git-ignored ``data/``; a report that names one without
        # its hash leaves no way to know what ran. Repository paths need no pin, and a
        # script with an appendix is reported below as missing its hash, once.
        errors += [
            f"{path}: {script} is named with no SHA-256 beside it; Bob's data/ scripts "
            "must be pinned, or the pair listed in UNVERIFIABLE in scripts/check_reports.py"
            for script in unhashed
            if script.startswith("data/")
            and script not in named
            and (path.name, script) not in UNVERIFIABLE
        ]
    if not pins and not named:
        return errors  # a review that pins nothing; any Bob data/ mention is already listed
    errors += [
        f"{path}: {script} has an appendix but no stated SHA-256"
        for script in sorted(named - {script for script, _, _ in pins})
    ]
    if fence_marks(text) % 2:
        errors.append(f"{path}: odd number of ``` fences; a block is unclosed")
    errors += [
        f"{path}: script fenced as python at offset {start}; use text"
        for start, language, _ in blocks
        if language == "python"
    ]
    # One script, two different stated digests: only the first was ever checked.
    by_path: dict[str, set[str]] = {}
    for script, digest, _ in pins:
        by_path.setdefault(script, set()).add(digest)
    for script, digests in sorted(by_path.items()):
        if len(digests) > 1:
            errors.append(
                f"{path}: {script} is given {len(digests)} different SHA-256 values: "
                + ", ".join(sorted(digests))
            )
    seen: set[tuple[str, str]] = set()
    for script, digest, line in pins:
        if (script, digest) in seen:
            continue
        seen.add((script, digest))
        errors += check_pin(path, script, digest, line, text, blocks, checked)
    return errors


def appendix_blocks(
    script: str, text: str, blocks: list[tuple[int, str, str]]
) -> list[tuple[int, str, str]] | None:
    """The fenced blocks under the innermost heading naming ``script``, or None."""
    best: tuple[int, int] | None = None
    for heading, start, end in sections(text):
        if f"`{script}`" in heading and (best is None or start >= best[0]):
            best = (start, end)
    if best is None:
        return None
    return [b for b in blocks if best[0] <= b[0] < best[1]]


def check_pin(
    path: Path,
    script: str,
    digest: str,
    line: str,
    text: str,
    blocks: list[tuple[int, str, str]],
    checked: list[str] | None,
) -> list[str]:
    def record(state: str, detail: str = "") -> None:
        if checked is not None:
            checked.append(f"{state} {path.name}:{script}{detail}")

    section = appendix_blocks(script, text, blocks)
    if section is not None:
        if not section:
            # Was ``if not following: continue`` — an appendix heading with no block
            # meant the stated hash was never checked and nothing was said.
            return [f"{path}: {script} has an appendix heading but no fenced block"]
        actual = hashlib.sha256(section[0][2].encode("utf-8")).hexdigest()
        if actual == digest:
            record("verified")
            return []
        matching = [i for i, b in enumerate(section) if _sha(b[2]) == digest]
        if matching:
            # ``following[0]`` was positional: the hashed source must be the first
            # block of the appendix, or a later edit silently changes what is hashed.
            return [
                f"{path}: {script} is stated as {digest}, which is block "
                f"{matching[0] + 1} of its appendix, not the first"
            ]
        # Only the part of the line that belongs to this pin: from the path to the next
        # pinned path, so a correction cannot borrow the digest stated for another script
        # on the same line.
        own = line[line.find(f"`{script}`") :] if f"`{script}`" in line else line
        following = PIN_PATH.search(own, len(script) + 2)
        if following:
            own = own[: following.start()]
        if CORRECTION in line and actual in own:
            # The only accepted form: the correction names the real digest, so the
            # appendix is still hash-checked, against the corrected value.
            record("corrected", f" (states {digest[:12]}.., appendix is {actual[:12]}..)")
            return []
        if CORRECTION in line:
            return [
                f"{path}: {script} is marked '{CORRECTION}' but the line does not give "
                f"the digest the appendix actually hashes to, {actual}"
            ]
        return [f"{path}: {script} appendix hashes to {actual}, report states {digest}"]
    allowed = UNVERIFIABLE.get((path.name, script))
    if allowed is None:
        return [
            f"{path}: {script} is pinned to {digest} with no appendix in this review and "
            "no committed source, so the digest cannot be checked; add the source as the "
            "first fenced block under a heading naming the path, or add the pair to "
            "UNVERIFIABLE in scripts/check_reports.py with a reason"
        ]
    expected, reason = allowed
    if expected != digest:
        return [
            f"{path}: {script} is allowed as unverifiable for {expected} but the review "
            f"now states {digest}; re-review the entry in scripts/check_reports.py"
        ]
    record("UNVERIFIABLE", f" {digest} - {reason}")
    return []


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check_allow_list(reviews: Path = REVIEWS) -> list[str]:
    """Every ``UNVERIFIABLE`` entry must still match a stated hash in its document."""
    errors = []
    for (name, script), (digest, _) in sorted(UNVERIFIABLE.items()):
        report = reviews / name
        if not report.is_file():
            errors.append(f"UNVERIFIABLE names a missing review: {name}")
            continue
        pins = stated_hashes(report.read_text(encoding="utf-8"))
        if (script, digest) not in {(p, d) for p, d, _ in pins}:
            errors.append(
                f"UNVERIFIABLE entry {name}:{script} {digest} matches no stated hash "
                "there any more; remove it"
            )
    return errors


def check_scope(changed: list[tuple[str, str]], base_index: str, head_index: str) -> list[str]:
    """Allow exactly one added report and nothing else; the index stays byte-for-byte.

    The report carries its own ``Index:`` line, which ``check_index`` verifies, so the
    branch has no reason to touch ``docs/reviews/README.md``. Git paths use forward
    slashes on every host. Status matters: a rename into the report directory would
    also delete its source, and an edit could rewrite history.
    """
    reports = [path for status, path in changed if status == "A" and BOB_REPORT.fullmatch(path)]
    errors = [
        f"a Bob task branch may only add its one report: {status} {path}"
        for status, path in changed
        if not (status == "A" and BOB_REPORT.fullmatch(path))
    ]
    if len(reports) != 1 or len(changed) != 1:
        errors.append(f"expected exactly one added Bob report and nothing else: {changed}")
    if head_index != base_index:
        errors.append(f"a Bob task branch must not edit {INDEX.as_posix()}; {HOW_TO}")
    return errors


def parse_name_status(lines: list[str]) -> list[tuple[str, str]]:
    """Read ordinary one-path Git changes; never discard a rename or copy source."""
    pairs = []
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2 or parts[0] not in {"A", "M", "D", "T", "U", "X", "B"} or not parts[1]:
            raise ValueError(f"unsupported or malformed name-status entry: {line!r}")
        pairs.append((parts[0], parts[1]))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changed", type=Path, help="output of git diff --name-status BASE...HEAD")
    parser.add_argument("--base-index", type=Path, help="docs/reviews/README.md at BASE")
    parser.add_argument(
        "--index", action="store_true", help="print the whole handoff index, newest first"
    )
    args = parser.parse_args(argv)
    if args.index:
        # Bytes, not text: a Windows console code page cannot encode every title.
        sys.stdout.buffer.write(build_index().encode("utf-8"))
        return 0
    errors = check_index() + check_frozen(INDEX.read_text(encoding="utf-8")) + check_allow_list()
    checked: list[str] = []
    mentions: list[str] = []
    # Every review that states a hash, not only Bob's: Claude publishes hashed
    # appendices too (2026-09-26 open-mismatch note), and an unchecked hash is
    # exactly the defect this script exists to catch.
    for report in sorted(REVIEWS.glob("*.md")):
        if report.name != "README.md":
            errors += check_report(report, checked, mentions)
    if args.changed is not None:
        if args.base_index is None:
            parser.error("--changed needs --base-index")
        try:
            changed = parse_name_status(args.changed.read_text(encoding="utf-8").splitlines())
        except ValueError as exc:
            parser.error(str(exc))
        errors += check_scope(
            changed,
            args.base_index.read_text(encoding="utf-8"),
            INDEX.read_text(encoding="utf-8"),
        )
    for error in errors:
        print(error)
    for entry in checked:
        print(f"check_reports: {entry}")
    counts = Counter(entry.split(" ", 1)[0] for entry in checked)
    print(
        f"check_reports: {len(checked)} stated hash(es): {counts['verified']} verified, "
        f"{counts['corrected']} corrected in place, {counts['UNVERIFIABLE']} unverifiable"
    )
    print(
        f"check_reports: {len(mentions)} script mention(s) without a hash "
        f"(information; a mention is not a pin)"
    )
    print(f"check_reports: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
