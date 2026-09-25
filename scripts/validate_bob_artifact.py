"""Validate the artifact a Bob task worker uploaded, before anything is published.

The worker runs Bob with command access and sudo, so everything it uploads is untrusted.
bob-task.yml's publish job runs this on a fresh machine, from a clean checkout of main,
and commits nothing unless it passes. Accepted content is exactly:

- ``summary.md``: Bob's final answer, required (a blank one means no final answer);
- at most one ``report/YYYY-MM-DD-bob-<topic>.md``, not already in docs/reviews/.

Both must be regular files of UTF-8 text without control characters, within size
limits, and free of secret-like values.

Environment: IN_DIR (the downloaded artifact), BOBSHELL_API_KEY (optional, scanned for),
GITHUB_OUTPUT (receives ``report=<name>``, empty when there is no report). Run from the
repository root. Exit status 1 with a "Rejected:" line on any failure.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SUMMARY_MAX_BYTES = 20_000
REPORT_MAX_BYTES = 200_000
REPORT_NAME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-bob-[A-Za-z0-9._-]+\.md$")
SECRET_LIKE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_")


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
    if any(ord(c) < 32 and c not in "\n\r\t" for c in body):
        raise Rejected(f"{label} contains control characters")
    if (key and key in body) or SECRET_LIKE.search(body):
        raise Rejected(f"{label} contains a secret-like value")
    if not body.strip():
        raise Rejected(f"{label} is blank")


def validate(root: Path, reviews_dir: Path, key: str = "") -> str:
    """Return the accepted report's file name, or "" when there is only a summary."""
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
        return ""
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
    print(f"Accepted: summary.md{', ' + report if report else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
