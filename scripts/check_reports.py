"""Mechanical checks on the review index and on Bob's reports, run in CI.

Each check here once cost a review round (PRs #40, #59, #60, #65, #66, #89, #100):

* every row of the frozen legacy table in ``docs/reviews/README.md`` links to a file
  that exists, and the table itself is unchanged (pinned by ``LEGACY_SHA256``);
* every review file outside that table carries its own index entry: a ``# Title`` first
  line and exactly one ``Index:`` line near the top. ``--index`` prints the whole index,
  newest first, from those entries and the legacy table. Nothing generated is committed,
  so two PRs that each add a review file never edit the same line;
* a script source copied into a Bob report hashes to the SHA-256 the report states
  for it, unless that mismatch is marked "Correction at review" on the same line;
* Bob reports fence script sources as ``text``: ``ruff format`` rewrites ``python``
  blocks in Markdown, which would change the hashed source;
* with ``--changed`` (a Bob task branch), the branch adds only its one report and
  leaves the index unchanged.

Judgement stays with the reviewers; this only removes the checks a script can do.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REVIEWS = Path("docs/reviews")
INDEX = REVIEWS / "README.md"
ROW_LINK = re.compile(r"^\| \[[^\]]*\]\(([^)#\s]+)\)", re.MULTILINE)
SCRIPT_HEADING = re.compile(r"^#{2,4} .*?`(data/[\w.-]+\.py)`", re.MULTILINE)
FENCE = re.compile(r"^```(\w*)[ \t]*$", re.MULTILINE)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
BOB_REPORT = re.compile(r"docs/reviews/[0-9]{4}-[0-9]{2}-[0-9]{2}-bob-[A-Za-z0-9._-]+\.md")
CORRECTION = "Correction at review"
# The legacy table was frozen on 2026-09-27 at main c3c8e25, with 83 rows. This is the
# SHA-256 of every README line that starts with "|", joined with "\n" plus a final "\n".
# It changes only if someone adds or edits a table row, which is exactly what the freeze
# forbids: a row added by every PR at the same place made each merge conflict every PR.
LEGACY_SHA256 = "d30769549f49c533e191f5a1760e35525ae6587212f75e26918d1300a35fd002"
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


def stated_hash(text: str, script: str) -> tuple[str, bool] | None:
    """The first SHA-256 given for ``script`` outside its appendix, and whether the
    line carrying it marks a correction at review."""
    for match in re.finditer(re.escape(f"`{script}`"), text):
        window = text[match.end() : match.end() + 200]
        found = HEX64.search(window)
        if found:
            line_end = text.find("\n", match.end() + found.end())
            line_start = text.rfind("\n", 0, match.start()) + 1
            line = text[line_start : line_end if line_end >= 0 else len(text)]
            return found.group(0), CORRECTION in line
    return None


def check_report(path: Path, checked: list[str] | None = None) -> list[str]:
    """Problems in one review; appends each hash-checked script to ``checked``.

    A report with no appendix heading and no stated hash is a no-op: the ``text``
    fence rule exists only to stop ``ruff format`` rewriting a block whose SHA-256
    the report pins, so it is not imposed on prose that pins nothing.
    """
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    blocks = fenced_blocks(text)
    if not SCRIPT_HEADING.search(text):
        # Prose with an incidental python block pins nothing, so the text-fence rule
        # has nothing to protect. An appendix heading *without* a hash still errors.
        return errors
    errors += [
        f"{path}: script fenced as python at offset {start}; use text"
        for start, language, _ in blocks
        if language == "python"
    ]
    for heading in SCRIPT_HEADING.finditer(text):
        script = heading.group(1)
        following = [b for b in blocks if b[0] > heading.end()]
        if not following:
            continue
        _, _, body = following[0]
        stated = stated_hash(text, script)
        if stated is None:
            errors.append(f"{path}: {script} has an appendix but no stated SHA-256")
            continue
        expected, marked = stated
        if checked is not None:
            checked.append(f"{path.name}:{script}")
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != expected and not marked:
            errors.append(f"{path}: {script} appendix hashes to {actual}, report states {expected}")
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
    errors = check_index() + check_frozen(INDEX.read_text(encoding="utf-8"))
    checked: list[str] = []
    # Every review with an embedded appendix, not only Bob's: Claude publishes
    # hashed appendices too (2026-09-26 open-mismatch note), and an unchecked hash
    # is exactly the defect this script exists to catch. Reviews without an
    # appendix heading are a no-op in check_report.
    for report in sorted(REVIEWS.glob("*.md")):
        if report.name != "README.md":
            errors += check_report(report, checked)
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
    print(f"check_reports: {len(checked)} appendix script(s) hash-checked: {', '.join(checked)}")
    print(f"check_reports: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
