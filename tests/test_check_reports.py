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
    INDEX = "docs/reviews/README.md"

    def setUp(self):
        self.changed = [("A", self.NEW), ("M", self.INDEX)]
        self.base = "Existing policy.\n" + index("old.md")
        self.head = self.base + "| [New report](2026-09-26-bob-x.md) | new |\n"

    def test_one_report_and_its_row_pass_on_every_host(self):
        self.assertEqual([], check_scope(self.changed, self.base, self.head))

    def test_report_name_matches_the_artifact_publishers_allowed_names(self):
        name = "2026-09-26-bob-Topic_v1.2.md"
        changed = [("A", "docs/reviews/" + name), ("M", self.INDEX)]
        self.assertEqual(
            [], check_scope(changed, self.base, self.base + f"| [New]({name}) | x |\n")
        )

    def test_row_can_be_inserted_at_the_top_of_the_table(self):
        head = self.base.replace("| [old.md]", "| [New](2026-09-26-bob-x.md) | new |\n| [old.md]")
        self.assertEqual([], check_scope(self.changed, self.base, head))

    def test_existing_content_is_preserved_including_status_labels_and_prose(self):
        for head in (
            self.head.replace("Existing policy.", "New policy."),
            self.head.replace("| summary |", "| APPROVED |"),
            self.head.replace("[old.md]", "[Different label]"),
            self.head.replace("| [old.md](old.md) | summary |\n", ""),
            self.head + "| [Duplicate](old.md) | summary |\n",
        ):
            with self.subTest(head=head):
                self.assertTrue(check_scope(self.changed, self.base, head))

    def test_missing_duplicate_and_unrelated_new_rows_fail(self):
        row = "| [New](2026-09-26-bob-x.md) | new |\n"
        for head in (self.base, self.head + row, self.head + "| [Other](other.md) | x |\n"):
            with self.subTest(head=head):
                self.assertTrue(check_scope(self.changed, self.base, head))

    def test_existing_report_edits_deletions_type_changes_and_renames_fail(self):
        for status in ("M", "D", "T", "R100", "C100"):
            with self.subTest(status=status):
                changed = [(status, self.NEW), ("M", self.INDEX)]
                self.assertTrue(check_scope(changed, self.base, self.head))

    def test_extra_files_second_report_and_duplicate_status_entries_fail(self):
        for extra in (
            ("M", "src/x.py"),
            ("A", "docs/reviews/2026-09-26-bob-y.md"),
            ("M", self.INDEX),
        ):
            with self.subTest(extra=extra):
                self.assertTrue(check_scope(self.changed + [extra], self.base, self.head))

    def test_deleted_or_missing_index_fails(self):
        for changed in ([self.changed[0]], [self.changed[0], ("D", self.INDEX)]):
            with self.subTest(changed=changed):
                self.assertTrue(check_scope(changed, self.base, self.head))

    def test_name_status_parsing(self):
        lines = ["A\tdocs/reviews/x.md", "M\tdocs/reviews/README.md"]
        self.assertEqual([("A", "docs/reviews/x.md"), ("M", self.INDEX)], parse_name_status(lines))
        self.assertEqual([], parse_name_status([]))

    def test_rename_copy_and_malformed_status_never_drop_the_source(self):
        for line in (
            "R100\tLICENSE\t" + self.NEW,
            "C100\tLICENSE\t" + self.NEW,
            "R100\t" + self.NEW,
            "A",
            "A\t",
            "A\tx\textra",
            "BOGUS\tx",
            "",
            "\tfile.md",
        ):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_name_status([line])


if __name__ == "__main__":
    unittest.main()
