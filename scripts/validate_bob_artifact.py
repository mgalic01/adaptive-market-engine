"""Validate the artifact a Bob task worker uploaded, before anything is published.

The worker runs Bob with command access and sudo, so everything it uploads is untrusted.
bob-task.yml's publish job runs this on a fresh machine, from a clean checkout of main,
and commits nothing unless it passes. Accepted content is exactly:

- ``summary.md``: Bob's final answer, required (a blank one means no final answer);
- exactly one ``report/YYYY-MM-DD-bob-<topic>.md``, not already in docs/reviews/.

A summary alone is rejected, including when the task could not finish. The publisher
then fails and alerts the owner rather than silently skipping publication and delivery.

Both must be regular files of UTF-8 text within size limits, free of secret-like
values, and without control, format, separator or private-use characters (Unicode
categories Cc except tab and newlines, Cf, Zl, Zp, Co, Cs). Those include invisible and
bidirectional characters that could hide text from a reviewer in files every agent
reads.

Environment: IN_DIR (the downloaded artifact), BOBSHELL_API_KEY (optional, scanned for),
GITHUB_OUTPUT (receives ``report=<name>`` only on success). Run from the
repository root. Exit status 1 with a "Rejected:" line on any failure.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

SUMMARY_MAX_BYTES = 20_000
REPORT_MAX_BYTES = 200_000
# Report topics may use dots, underscores and capitals; task-file slugs are stricter.
REPORT_NAME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-bob-[A-Za-z0-9._-]+\.md$")
SECRET_LIKE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_")
HIDDEN_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Co", "Cs"}
ALLOWED_CONTROLS = {"\n", "\r", "\t"}


class Rejected(Exception):
    """The artifact must not be published."""


def _check_text(path: Path, cap: int, label: str, key: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise Rejected(f"{label} is not a regular file")
    size = path.stat().st_size
    if size == 0 or size > cap:
        raise Rejected(f"{label} size {size} is outside 1..{cap} bytes")
    try:
        body = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected(f"{label} is not UTF-8 text") from None
    for c in body:
        if c not in ALLOWED_CONTROLS and unicodedata.category(c) in HIDDEN_CATEGORIES:
            raise Rejected(f"{label} contains a control or invisible character U+{ord(c):04X}")
    if (key and key in body) or SECRET_LIKE.search(body):
        raise Rejected(f"{label} contains a secret-like value")
    if not body.strip():
        raise Rejected(f"{label} is blank")


def validate(root: Path, reviews_dir: Path, key: str = "") -> str:
    """Return the accepted report's file name; a summary alone is not a task report."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():
                raise Rejected("a directory is a symlink")
        for f in filenames:
            found.append((Path(dirpath) / f).relative_to(root).as_posix())
    reports = [p for p in found if p.startswith("report/")]
    others = sorted(p for p in found if p not in reports and p != "summary.md")
    if others:
        raise Rejected(f"unexpected files: {others}")
    if "summary.md" not in found:
        raise Rejected("summary.md is missing (no final answer from Bob)")
    _check_text(root / "summary.md", SUMMARY_MAX_BYTES, "summary.md", key)
    if len(reports) > 1:
        raise Rejected(f"more than one report: {sorted(reports)}")
    if not reports:
        raise Rejected("report is missing (a summary alone cannot complete a task run)")
    name = reports[0].removeprefix("report/")
    if "/" in name or not REPORT_NAME.match(name):
        raise Rejected(f"report name {name!r} does not match YYYY-MM-DD-bob-<topic>.md")
    if os.path.lexists(reviews_dir / name):
        raise Rejected(f"docs/reviews/{name} already exists on main")
    _check_text(root / reports[0], REPORT_MAX_BYTES, name, key)
    return name


def main() -> int:
    try:
        report = validate(
            Path(os.environ["IN_DIR"]),
            Path("docs") / "reviews",
            os.environ.get("BOBSHELL_API_KEY", ""),
        )
    except Rejected as exc:
        print(f"Rejected: {exc}")
        return 1
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"report={report}\n")
    print(f"Accepted: summary.md, {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
