"""Mechanical checks on the review index and on Bob's reports, run in CI.

Each check here once cost a review round (PRs #40, #59, #60, #65, #66):

* every index row in ``docs/reviews/README.md`` links to a file that exists, and every
  review file is indexed;
* a script source copied into a Bob report hashes to the SHA-256 the report states
  for it, unless that mismatch is marked "Correction at review" on the same line;
* Bob reports fence script sources as ``text``: ``ruff format`` rewrites ``python``
  blocks in Markdown, which would change the hashed source;
* with ``--changed`` (a Bob task branch), the branch touches only its one report and
  the index, and the index gains exactly one row, for that report, and loses none.

Judgement stays with the reviewers; this only removes the checks a script can do.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REVIEWS = Path("docs/reviews")
INDEX = REVIEWS / "README.md"
ROW_LINK = re.compile(r"^\| \[[^\]]*\]\(([^)#\s]+)\)", re.MULTILINE)
SCRIPT_HEADING = re.compile(r"^#{2,4} .*?`(data/[\w.-]+\.py)`", re.MULTILINE)
FENCE = re.compile(r"^```(\w*)[ \t]*$", re.MULTILINE)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
BOB_REPORT = re.compile(r"^docs/reviews/\d{4}-\d{2}-\d{2}-bob-[\w-]+\.md$")
CORRECTION = "Correction at review"


def index_links(text: str) -> list[str]:
    return ROW_LINK.findall(text)


def check_index(reviews: Path = REVIEWS) -> list[str]:
    links = index_links((reviews / "README.md").read_text(encoding="utf-8"))
    errors = [
        f"index links a missing file: {link}" for link in links if not (reviews / link).is_file()
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
    """Problems in one Bob report; appends each hash-checked script to ``checked``."""
    text = path.read_text(encoding="utf-8")
    errors = []
    blocks = fenced_blocks(text)
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
    """``changed`` is ``git diff --name-status`` as (status, path) pairs."""
    reports = [path for status, path in changed if BOB_REPORT.match(path)]
    others = [path for _, path in changed if path != str(INDEX) and not BOB_REPORT.match(path)]
    errors = [f"a Bob task branch may change only its report and the index: {p}" for p in others]
    if len(reports) != 1:
        return errors + [f"expected exactly one Bob report, found {len(reports)}: {reports}"]
    report = Path(reports[0]).name
    before, after = index_links(base_index), index_links(head_index)
    added = [link for link in after if link not in before]
    removed = [link for link in before if link not in after]
    if added != [report]:
        errors.append(f"the index must gain exactly one row, for {report}; it gains {added}")
    if removed:
        errors.append(f"the index must not lose rows; it loses {removed}")
    return errors


def parse_name_status(lines: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2:
            pairs.append((parts[0], parts[-1]))
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changed", type=Path, help="output of git diff --name-status BASE...HEAD")
    parser.add_argument("--base-index", type=Path, help="docs/reviews/README.md at BASE")
    args = parser.parse_args(argv)
    errors = check_index()
    checked: list[str] = []
    for report in sorted(REVIEWS.glob("*-bob-*.md")):
        errors += check_report(report, checked)
    if args.changed is not None:
        if args.base_index is None:
            parser.error("--changed needs --base-index")
        changed = parse_name_status(args.changed.read_text(encoding="utf-8").splitlines())
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
