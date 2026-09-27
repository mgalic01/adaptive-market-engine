"""The CI report checker: each case is a mistake that once cost a review round."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_reports import (  # noqa: E402
    LEGACY_SHA256,
    build_index,
    check_frozen,
    check_index,
    check_report,
    check_scope,
    legacy_digest,
    parse_name_status,
)

REPO_REVIEWS = Path(__file__).resolve().parents[1] / "docs" / "reviews"

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

    def test_a_report_pinning_no_hash_is_skipped_entirely(self):
        # An older review may embed a python block without pinning any hash (e.g.
        # 2026-09-24-codex-replay-fixes-verification.md). The text-fence rule exists
        # only to protect a pinned hash, so it must not fire there.
        text = "# Note\n\n```python\nx = 1\n```\n"
        self.assertEqual([], check_report(self.write(text)))

    def test_python_fence_fails(self):
        errors = check_report(self.write(report(fence="python")))
        self.assertTrue(any("fenced as python" in e for e in errors))

    def test_appendix_without_a_stated_hash_fails(self):
        text = "## Appendix: `data/x.py` source\n\n```text\n" + SOURCE + "```\n"
        self.assertIn("no stated SHA-256", check_report(self.write(text))[0])


def entry(title="New note", summary="What it is for.", extra=""):
    return f"# {title}\n\n{extra}Index: {summary}\n\nBody.\n"


class IndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.reviews = Path(tmp.name)
        (self.reviews / "a.md").write_text("a", encoding="utf-8")
        (self.reviews / "README.md").write_text(index("a.md"), encoding="utf-8")

    def add(self, name, text):
        (self.reviews / name).write_text(text, encoding="utf-8")

    def test_complete_index_passes(self):
        self.assertEqual([], check_index(self.reviews))

    def test_missing_file_and_unindexed_file_fail(self):
        # PRs #65/#66: rows for files that existed only on another branch.
        self.add("b.md", "b")
        (self.reviews / "README.md").write_text(index("a.md", "gone.md"), encoding="utf-8")
        errors = check_index(self.reviews)
        self.assertIn("index links a missing file: gone.md", errors)
        self.assertTrue(any(e.startswith("review file not in the index: b.md") for e in errors))

    def test_a_file_carrying_its_own_entry_needs_no_row(self):
        self.add("2026-09-27-claude-x.md", entry())
        self.assertEqual([], check_index(self.reviews))

    def test_a_missing_entry_fails(self):
        # The new rule's whole guarantee: a review cannot silently drop out of the index.
        self.add("2026-09-27-claude-x.md", "# New note\n\nNo index line.\n")
        errors = check_index(self.reviews)
        self.assertEqual(1, len(errors))
        self.assertIn("review file not in the index: 2026-09-27-claude-x.md", errors[0])

    def test_malformed_entries_fail(self):
        for name, text in (
            ("2026-09-27-claude-x.md", "No heading\n\nIndex: summary\n"),
            ("2026-09-27-claude-x.md", entry(summary="")),
            ("2026-09-27-claude-x.md", entry(extra="Index: a second one\n")),
            ("undated-note.md", entry()),
            ("2026-09-27-claude-x.md", "# T\n" + "\n" * 25 + "Index: too far down\n"),
        ):
            with self.subTest(name=name, text=text):
                for old in self.reviews.glob("*.md"):
                    if old.name not in {"a.md", "README.md"}:
                        old.unlink()
                self.add(name, text)
                self.assertTrue(check_index(self.reviews))

    def test_a_legacy_file_may_not_also_carry_an_entry(self):
        self.add("a.md", entry())
        self.assertTrue(check_index(self.reviews))


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.reviews = Path(tmp.name)

    def make(self, names):
        for old in self.reviews.glob("*.md"):
            old.unlink()
        (self.reviews / "old.md").write_text("old", encoding="utf-8")
        (self.reviews / "README.md").write_text(
            "Header.\n\n" + index("old.md") + "\nPRs: #1.\n", encoding="utf-8"
        )
        for name in names:
            title = "Title | with [pipe]" if "b-" in name else f"Title {name[11:-3]}"
            (self.reviews / name).write_text(entry(title, f"About {name}."), encoding="utf-8")

    NAMES = ["2026-09-27-b-z.md", "2026-09-28-a-y.md", "2026-09-27-a-x.md"]

    def test_output_is_exact_newest_first_and_escaped(self):
        self.make(self.NAMES)
        rows = [line for line in build_index(self.reviews).splitlines() if line.startswith("| [")]
        self.assertEqual(
            [
                "| [Title a-y](2026-09-28-a-y.md) | 2026-09-28: About 2026-09-28-a-y.md. |",
                "| [Title a-x](2026-09-27-a-x.md) | 2026-09-27: About 2026-09-27-a-x.md. |",
                "| [Title \\| with \\[pipe\\]](2026-09-27-b-z.md) | 2026-09-27: About "
                "2026-09-27-b-z.md. |",
                "| [old.md](old.md) | summary |",
            ],
            rows,
        )

    def test_output_is_deterministic_whatever_the_creation_order(self):
        outputs = set()
        for order in (self.NAMES, list(reversed(self.NAMES)), sorted(self.NAMES)):
            self.make(order)
            outputs.add(build_index(self.reviews))
            outputs.add(build_index(self.reviews))
        self.assertEqual(1, len(outputs))

    def test_a_file_without_an_entry_is_listed_not_dropped(self):
        self.make(self.NAMES)
        (self.reviews / "2026-09-29-c-w.md").write_text("# No entry\n", encoding="utf-8")
        self.assertIn("- [2026-09-29-c-w.md](2026-09-29-c-w.md)", build_index(self.reviews))

    def test_the_real_index_builds_and_keeps_every_legacy_row(self):
        readme = (REPO_REVIEWS / "README.md").read_text(encoding="utf-8")
        built = build_index(REPO_REVIEWS)
        for row in (line for line in readme.splitlines() if line.startswith("| [")):
            self.assertIn(row + "\n", built)
        self.assertNotIn("without a valid index entry", built)


class FrozenTableTests(unittest.TestCase):
    def test_the_committed_legacy_table_matches_its_pin(self):
        readme = (REPO_REVIEWS / "README.md").read_text(encoding="utf-8")
        self.assertEqual(LEGACY_SHA256, legacy_digest(readme))
        self.assertEqual([], check_frozen(readme))

    def test_drift_fails(self):
        # An added row (the old habit), an edited row and a removed row all fail.
        readme = (REPO_REVIEWS / "README.md").read_text(encoding="utf-8")
        first = next(line for line in readme.splitlines() if line.startswith("| ["))
        for i, drifted in enumerate(
            (
                readme.replace(first, "| [New](2026-09-28-claude-x.md) | new |\n" + first),
                readme.replace(first, first.replace("|", "| edited", 2)),
                readme.replace(first + "\n", ""),
            )
        ):
            with self.subTest(i=i):
                self.assertNotEqual(readme, drifted)
                self.assertEqual(1, len(check_frozen(drifted)))

    def test_prose_outside_the_table_may_change(self):
        readme = (REPO_REVIEWS / "README.md").read_text(encoding="utf-8")
        self.assertEqual([], check_frozen("Reworded header.\n" + readme))


class ScopeTests(unittest.TestCase):
    NEW = "docs/reviews/2026-09-26-bob-x.md"
    INDEX = "docs/reviews/README.md"

    def setUp(self):
        self.changed = [("A", self.NEW)]
        self.base = "Existing policy.\n" + index("old.md")

    def test_one_report_and_no_index_change_pass_on_every_host(self):
        self.assertEqual([], check_scope(self.changed, self.base, self.base))

    def test_report_name_matches_the_artifact_publishers_allowed_names(self):
        changed = [("A", "docs/reviews/2026-09-26-bob-Topic_v1.2.md")]
        self.assertEqual([], check_scope(changed, self.base, self.base))

    def test_any_index_edit_fails_including_the_old_added_row(self):
        for head in (
            self.base + "| [New report](2026-09-26-bob-x.md) | new |\n",
            self.base.replace("Existing policy.", "New policy."),
            self.base.replace("| summary |", "| APPROVED |"),
        ):
            with self.subTest(head=head):
                self.assertTrue(check_scope(self.changed, self.base, head))
                self.assertTrue(check_scope(self.changed + [("M", self.INDEX)], self.base, head))

    def test_existing_report_edits_deletions_type_changes_and_renames_fail(self):
        for status in ("M", "D", "T", "R100", "C100"):
            with self.subTest(status=status):
                self.assertTrue(check_scope([(status, self.NEW)], self.base, self.base))

    def test_extra_files_second_report_and_duplicate_status_entries_fail(self):
        for extra in (
            ("M", "src/x.py"),
            ("A", "docs/reviews/2026-09-26-bob-y.md"),
            ("A", self.NEW),
            ("M", self.INDEX),
            ("D", self.INDEX),
        ):
            with self.subTest(extra=extra):
                self.assertTrue(check_scope(self.changed + [extra], self.base, self.base))

    def test_no_report_fails(self):
        self.assertTrue(check_scope([], self.base, self.base))

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
