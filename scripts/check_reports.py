"""Mechanical checks on the review index and on Bob's reports, run in CI.

Each check here once cost a review round (PRs #40, #59, #60, #65, #66):

* every index row in ``docs/reviews/README.md`` links to a file that exists, no target
  is listed twice, and every review file is indexed;
* every SHA-256 a review states for a ``*.py`` path is accounted for: either a fenced
  block in the same review hashes to it, or the review's mismatch is corrected in place
  with the real digest written out, or the pair is listed in ``UNVERIFIABLE`` below with
  a reason. A stated hash that is none of those three is an error;
* Bob reports fence script sources as ``text``: ``ruff format`` rewrites ``python``
  blocks in Markdown, which would change the hashed source;
* with ``--changed`` (a Bob task branch), the branch touches only its one report and
  the index, and the index gains exactly one row, for that report, and loses none.

Nothing here is allowed to pass quietly: every run prints the verified, corrected and
unverifiable pins by name, and the three counts sum to every pin found.

Judgement stays with the reviewers; this only removes the checks a script can do.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

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
CORRECTION = "Correction at review"
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


def check_index(reviews: Path = REVIEWS) -> list[str]:
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
    files = sorted(p.name for p in reviews.glob("*.md") if p.name != "README.md")
    errors += [f"review file not in the index: {name}" for name in files if name not in links]
    return errors


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
    heads = list(HEADING.finditer(text))
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
    """(path, digest, line) for every ``path.py`` in backticks with a digest after it.

    The window stops at the next pinned path so a table row cannot borrow the next
    row's digest, and a correction naming another script cannot steal its hash.
    """
    pins = []
    for match in PIN_PATH.finditer(text):
        window = text[match.end() : match.end() + WINDOW]
        following = PIN_PATH.search(window)
        if following:
            window = window[: following.start()]
        digest = HEX64.search(window)
        if digest is None:
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end() + digest.end())
        pins.append(
            (
                match.group(1),
                digest.group(0),
                text[line_start : line_end if line_end >= 0 else len(text)],
            )
        )
    return pins


def check_report(path: Path, checked: list[str] | None = None) -> list[str]:
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
    if not pins and not named:
        return errors
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
        if CORRECTION in line and actual in line:
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
    """Allow one new report and exactly one inserted index row; preserve everything else.

    Git paths use forward slashes on every host. Status matters: a rename into the
    report directory would also delete its source, and an edit could rewrite history.
    """
    index_path = INDEX.as_posix()
    reports = [path for status, path in changed if status == "A" and BOB_REPORT.fullmatch(path)]
    errors = [
        f"a Bob task branch may only add its report and modify the index: {status} {path}"
        for status, path in changed
        if not (
            (status == "A" and BOB_REPORT.fullmatch(path)) or (status == "M" and path == index_path)
        )
    ]
    if len(reports) != 1:
        errors.append(f"expected exactly one added Bob report, found {len(reports)}: {reports}")
    if changed.count(("M", index_path)) != 1 or len(changed) != 2:
        errors.append("expected exactly one report addition and one index modification")
    if len(reports) != 1:
        return errors
    report = PurePosixPath(reports[0]).name
    lines = head_index.splitlines(keepends=True)
    rows = [i for i, line in enumerate(lines) if index_links(line) == [report]]
    if len(rows) != 1:
        errors.append(f"the index must gain exactly one row, for {report}; found {len(rows)}")
    elif "".join(lines[: rows[0]] + lines[rows[0] + 1 :]) != base_index:
        errors.append("the index must preserve all existing content and add only its report row")
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
    args = parser.parse_args(argv)
    errors = check_index() + check_allow_list()
    checked: list[str] = []
    # Every review that states a hash, not only Bob's: Claude publishes hashed
    # appendices too (2026-09-26 open-mismatch note), and an unchecked hash is
    # exactly the defect this script exists to catch.
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
    for entry in checked:
        print(f"check_reports: {entry}")
    counts = Counter(entry.split(" ", 1)[0] for entry in checked)
    print(
        f"check_reports: {len(checked)} stated hash(es): {counts['verified']} verified, "
        f"{counts['corrected']} corrected in place, {counts['UNVERIFIABLE']} unverifiable"
    )
    print(f"check_reports: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
