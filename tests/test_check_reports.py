"""The CI report checker: each case is a mistake that once cost a review round."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_reports import (  # noqa: E402
    check_index,
    check_report,
    check_scope,
    parse_name_status,
)

SOURCE = 'print("hello")\n'
DIGEST = hashlib.sha256(SOURCE.encode()).hexdigest()
OTHER = "0" * 64


def report(stated=DIGEST, fence="text", note="", newline_before_hash=False):
    gap = "\n  " if newline_before_hash else " "
    return (
        "# Report\n\n"
        f"- **Script:** `data/x.py`{gap}(SHA-256: `{stated}`){note}\n\n"
        "## Appendix: `data/x.py` source\n\n"
        f"```{fence}\n{SOURCE}```\n"
    )


def index(*names):
    rows = "".join(f"| [{n}]({n}) | summary |\n" for n in names)
    return "| Handoff | Status |\n| --- | --- |\n" + rows


class ReportTests(unittest.TestCase):
    def write(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "2026-09-26-bob-x.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_matching_appendix_passes_and_is_counted(self):
        checked = []
        self.assertEqual([], check_report(self.write(report()), checked))
        self.assertEqual(["2026-09-26-bob-x.md:data/x.py"], checked)

    def test_hash_on_the_next_line_is_found(self):
        self.assertEqual([], check_report(self.write(report(newline_before_hash=True))))

    def test_mismatch_fails(self):
        errors = check_report(self.write(report(stated=OTHER)))
        self.assertEqual(1, len(errors))
        self.assertIn(f"appendix hashes to {DIGEST}", errors[0])

    def test_mismatch_marked_at_review_passes(self):
        text = report(stated=OTHER, note=" *[Correction at review: differs.]*")
        self.assertEqual([], check_report(self.write(text)))

    def test_python_fence_fails(self):
        errors = check_report(self.write(report(fence="python")))
        self.assertTrue(any("fenced as python" in e for e in errors))

    def test_appendix_without_a_stated_hash_fails(self):
        text = "## Appendix: `data/x.py` source\n\n```text\n" + SOURCE + "```\n"
        self.assertIn("no stated SHA-256", check_report(self.write(text))[0])


class IndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.reviews = Path(tmp.name)
        (self.reviews / "a.md").write_text("a", encoding="utf-8")

    def test_complete_index_passes(self):
        (self.reviews / "README.md").write_text(index("a.md"), encoding="utf-8")
        self.assertEqual([], check_index(self.reviews))

    def test_missing_file_and_unindexed_file_fail(self):
        # PRs #65/#66: rows for files that existed only on another branch.
        (self.reviews / "b.md").write_text("b", encoding="utf-8")
        (self.reviews / "README.md").write_text(index("a.md", "gone.md"), encoding="utf-8")
        errors = check_index(self.reviews)
        self.assertIn("index links a missing file: gone.md", errors)
        self.assertIn("review file not in the index: b.md", errors)


class ScopeTests(unittest.TestCase):
    NEW = "docs/reviews/2026-09-26-bob-x.md"

    def test_one_report_and_its_row_pass(self):
        changed = [("A", self.NEW), ("M", "docs/reviews/README.md")]
        self.assertEqual(
            [], check_scope(changed, index("old.md"), index("2026-09-26-bob-x.md", "old.md"))
        )

    def test_rows_for_other_files_fail(self):
        head = index("2026-09-26-bob-x.md", "claude-proposal.md", "old.md")
        errors = check_scope([("A", self.NEW)], index("old.md"), head)
        self.assertEqual(1, len(errors))
        self.assertIn("gains ['2026-09-26-bob-x.md', 'claude-proposal.md']", errors[0])

    def test_removed_row_extra_file_and_second_report_fail(self):
        changed = [("A", self.NEW), ("A", "docs/reviews/2026-09-26-bob-y.md"), ("M", "src/x.py")]
        errors = check_scope(changed, index("old.md"), index())
        self.assertTrue(any("src/x.py" in e for e in errors))
        self.assertTrue(any("exactly one Bob report, found 2" in e for e in errors))
        errors = check_scope([("A", self.NEW)], index("old.md"), index("2026-09-26-bob-x.md"))
        self.assertIn("the index must not lose rows; it loses ['old.md']", errors)

    def test_name_status_parsing_keeps_the_new_path_of_a_rename(self):
        lines = ["A\tdocs/reviews/x.md", "R100\told.md\tnew.md", ""]
        self.assertEqual([("A", "docs/reviews/x.md"), ("R100", "new.md")], parse_name_status(lines))


if __name__ == "__main__":
    unittest.main()
