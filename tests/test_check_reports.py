"""The CI report checker: each case is a mistake that once cost a review round."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_reports  # noqa: E402
from check_reports import (  # noqa: E402
    LEGACY_SHA256,
    build_index,
    check_allow_list,
    check_frozen,
    check_index,
    check_report,
    check_scope,
    legacy_digest,
    parse_name_status,
    stated_hashes,
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
    def write(self, text, name="2026-09-26-bob-x.md"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def allow(self, name, script, digest, reason="reason"):
        check_reports.UNVERIFIABLE[(name, script)] = (digest, reason)
        self.addCleanup(check_reports.UNVERIFIABLE.pop, (name, script))

    def only(self, name, script, digest, reason="reason"):
        """Replace the whole allow-list, for the checks that scan a temp directory."""
        kept = dict(check_reports.UNVERIFIABLE)

        def restore():
            check_reports.UNVERIFIABLE.clear()
            check_reports.UNVERIFIABLE.update(kept)

        self.addCleanup(restore)
        check_reports.UNVERIFIABLE.clear()
        check_reports.UNVERIFIABLE[(name, script)] = (digest, reason)

    def test_matching_appendix_passes_and_is_counted(self):
        checked = []
        self.assertEqual([], check_report(self.write(report()), checked))
        self.assertEqual(["verified 2026-09-26-bob-x.md:data/x.py"], checked)

    def test_hash_on_the_next_line_is_found(self):
        self.assertEqual([], check_report(self.write(report(newline_before_hash=True))))

    def test_mismatch_fails(self):
        errors = check_report(self.write(report(stated=OTHER)))
        self.assertEqual(1, len(errors))
        self.assertIn(f"appendix hashes to {DIGEST}", errors[0])

    # --- the "Correction at review" bypass -------------------------------------

    def test_correction_must_state_the_digest_the_appendix_really_hashes_to(self):
        # The bypass token lives inside the artifact being verified, so a bare marker
        # silenced any mismatch with no output at all (PR #120 audit).
        errors = check_report(self.write(report(stated=OTHER, note=" *[Correction at review.]*")))
        self.assertEqual(1, len(errors))
        self.assertIn("does not give the digest", errors[0])
        self.assertIn(DIGEST, errors[0])

    def test_correction_with_both_hashes_passes_and_is_reported(self):
        note = f" *[Correction at review: the appendix hashes to `{DIGEST}`.]*"
        checked = []
        self.assertEqual([], check_report(self.write(report(stated=OTHER, note=note)), checked))
        self.assertEqual(1, len(checked))
        self.assertTrue(checked[0].startswith("corrected 2026-09-26-bob-x.md:data/x.py"))
        self.assertIn(DIGEST[:12], checked[0])

    def test_correction_stating_a_third_digest_fails(self):
        note = f" *[Correction at review: it hashes to `{'1' * 64}`.]*"
        self.assertEqual(1, len(check_report(self.write(report(stated=OTHER, note=note)))))

    # --- pinned with no appendix and no source --------------------------------

    def test_hash_in_a_table_row_without_an_appendix_fails(self):
        # data/generate_report_tables.py and data/generate_summary_table.py were
        # pinned in table rows only, so the old heading-driven check skipped them
        # while printing "0 problem(s)".
        text = f"# R\n\n| Script | SHA-256 |\n| --- | --- |\n| `data/t.py` | `{OTHER}` |\n"
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors))
        self.assertIn("no appendix in this review and no committed source", errors[0])

    def test_an_allow_list_entry_makes_it_unverifiable_not_silent(self):
        self.allow("2026-09-26-bob-x.md", "data/t.py", OTHER, "source in no commit")
        text = f"# R\n\n| `data/t.py` | `{OTHER}` |\n"
        checked = []
        self.assertEqual([], check_report(self.write(text), checked))
        self.assertEqual(
            [f"UNVERIFIABLE 2026-09-26-bob-x.md:data/t.py {OTHER} - source in no commit"], checked
        )

    def test_an_allow_list_entry_does_not_cover_a_different_digest(self):
        self.allow("2026-09-26-bob-x.md", "data/t.py", OTHER)
        text = f"# R\n\n| `data/t.py` | `{'2' * 64}` |\n"
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors))
        self.assertIn("re-review the entry", errors[0])

    def test_an_allow_list_entry_does_not_cover_another_document(self):
        self.allow("other.md", "data/t.py", OTHER)
        self.assertEqual(1, len(check_report(self.write(f"# R\n\n| `data/t.py` | `{OTHER}` |\n"))))

    def test_a_stale_allow_list_entry_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        reviews = Path(tmp.name)
        (reviews / "r.md").write_text("# R\n\nnothing pinned.\n", encoding="utf-8")
        self.only("r.md", "data/gone.py", OTHER)
        self.assertIn("matches no stated hash", check_allow_list(reviews)[0])

    def test_an_allow_list_entry_for_a_missing_review_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.only("absent.md", "data/x.py", OTHER)
        self.assertIn("missing review", check_allow_list(Path(tmp.name))[0])

    # --- appendix shape --------------------------------------------------------

    def test_appendix_heading_with_no_fenced_block_fails(self):
        text = (
            f"# R\n\n`data/x.py` (SHA-256: `{OTHER}`)\n\n## Appendix: `data/x.py` source\n\nTODO.\n"
        )
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors))
        self.assertIn("no fenced block", errors[0])

    def test_the_hashed_block_must_be_the_first_in_the_appendix(self):
        text = (
            f"# R\n\n`data/x.py` (SHA-256: `{DIGEST}`)\n\n"
            "## Appendix: `data/x.py` source\n\n"
            "```text\nunrelated output\n```\n\n"
            f"```text\n{SOURCE}```\n"
        )
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors))
        self.assertIn("block 2 of its appendix, not the first", errors[0])

    def test_two_different_digests_for_one_script_fail(self):
        text = (
            f"# R\n\n| `data/x.py` | `{DIGEST}` |\n| `data/x.py` | `{OTHER}` |\n\n"
            f"## Appendix: `data/x.py` source\n\n```text\n{SOURCE}```\n"
        )
        errors = check_report(self.write(text))
        self.assertTrue(any("different SHA-256 values" in e for e in errors))

    def test_an_unclosed_fence_fails(self):
        text = report() + "\n```text\nstray\n"
        self.assertTrue(any("unclosed" in e for e in check_report(self.write(text))))

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

    # --- what counts as a pin --------------------------------------------------

    def test_a_digest_stated_before_its_script_is_still_a_pin(self):
        # "| SHA-256 | Script |" is the natural column order for a table; searching only
        # forward from the path let such a stated hash through unchecked.
        report = self.write(
            f"# R\n\n| SHA-256 | Script |\n| --- | --- |\n| `{'a' * 64}` | `data/early.py` |\n"
        )
        (problem,) = check_report(report)
        self.assertIn("data/early.py", problem)
        self.assertIn("no appendix in this review", problem)

    def test_a_table_row_cannot_borrow_the_previous_rows_digest(self):
        report = self.write(
            "# R\n\n| SHA-256 | Script |\n| --- | --- |\n"
            f"| `{'a' * 64}` | `data/one.py` |\n| `data/two.py` | no digest |\n"
        )
        pins = {path for path, _, _ in stated_hashes(report.read_text(encoding="utf-8"))}
        self.assertEqual({"data/one.py"}, pins)

    def test_a_digest_on_an_earlier_line_is_not_borrowed(self):
        text = f"The digest was `{'a' * 64}`.\n\nSee `data/other.py` for the method.\n"
        self.assertEqual([], stated_hashes(text))

    def test_a_bare_file_name_in_prose_is_not_a_pin(self):
        # In 2026-09-26-bob-hourly-defect-calendar.md a correction note names
        # `events.py` and `calendar.py` without a directory; pairing those with the
        # next digest on the line invents pins that no appendix can satisfy.
        text = f"# R\n\nThe appendix of `events.py` hashes to `{OTHER}`.\n"
        self.assertEqual([], stated_hashes(text))
        self.assertEqual([], check_report(self.write(text)))

    def test_a_table_row_cannot_borrow_the_next_rows_digest(self):
        text = f"| `data/a.py` |\n| `data/b.py` | `{OTHER}` |\n"
        self.assertEqual(
            [("data/b.py", OTHER, f"| `data/b.py` | `{OTHER}` |")], stated_hashes(text)
        )

    def test_any_heading_level_and_any_directory_are_in_scope(self):
        for heading in ("# ", "## ", "###### "):
            with self.subTest(heading=heading):
                text = (
                    f"`scripts/x.py` SHA-256: `{DIGEST}`\n\n"
                    f"{heading}`scripts/x.py`\n\n```text\n{SOURCE}```\n"
                )
                self.assertEqual([], check_report(self.write(text)))

    def test_a_heading_naming_a_path_with_no_block_is_not_an_appendix(self):
        text = "# R\n\n## Why `src/x.py` broke\n\nIt did not close the file.\n"
        self.assertEqual([], check_report(self.write(text)))

    def test_a_path_with_no_digest_near_it_is_not_a_pin(self):
        self.assertEqual(
            [], stated_hashes("See `src/crypto_grid_bot/app.py` for the entry point.\n")
        )


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

    def test_a_duplicated_row_fails(self):
        # ``links`` was a list and membership was tested one way only, so N identical
        # rows passed: two rows are two claims about one file's status.
        (self.reviews / "README.md").write_text(index("a.md", "a.md"), encoding="utf-8")
        self.assertEqual(
            ["index lists a.md in 2 rows; a file gets one row"], check_index(self.reviews)
        )

    def test_a_row_whose_link_carries_an_anchor_is_seen(self):
        (self.reviews / "README.md").write_text(
            "| H | S |\n| --- | --- |\n| [a](a.md#findings) | x |\n", encoding="utf-8"
        )
        self.assertEqual([], check_index(self.reviews))

    def test_a_row_whose_link_is_not_first_in_the_cell_is_seen(self):
        (self.reviews / "README.md").write_text(
            "| H | S |\n| --- | --- |\n| **[a](a.md)** | x |\n", encoding="utf-8"
        )
        self.assertEqual([], check_index(self.reviews))


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

    def test_a_link_outside_the_directory_still_resolves(self):
        # The live index has one such row, for ../tasks/README.md.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        reviews = Path(tmp.name) / "reviews"
        reviews.mkdir()
        (reviews / "a.md").write_text("a", encoding="utf-8")
        (Path(tmp.name) / "tasks").mkdir()
        (Path(tmp.name) / "tasks" / "README.md").write_text("t", encoding="utf-8")
        (reviews / "README.md").write_text(
            index("a.md") + "| [Tasks](../tasks/README.md) | x |\n", encoding="utf-8"
        )
        self.assertEqual([], check_index(reviews))


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


class LiveTreeTests(unittest.TestCase):
    def test_every_allow_list_entry_is_live(self):
        self.assertEqual([], check_allow_list())

    def test_the_live_index_passes(self):
        self.assertEqual([], check_index())


if __name__ == "__main__":
    unittest.main()


def _write(text, name="2026-09-26-bob-x.md"):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / name
    path.write_text(text, encoding="utf-8")
    return tmp, path


class PanelFixTests(unittest.TestCase):
    """Findings of the 2026-09-28 panel review on the checker (PR #122 follow-up)."""

    def write(self, text, name="2026-09-26-bob-x.md"):
        tmp, path = _write(text, name)
        self.addCleanup(tmp.cleanup)
        return path

    def test_a_hash_line_inside_a_fence_is_not_a_heading(self):
        # Bob's text-fenced Python carries "#" comments; one naming the script used to
        # be read as the innermost appendix heading, with no block under it.
        source = "# see `data/x.py` for the entry point\nprint(1)\n"
        digest = hashlib.sha256(source.encode()).hexdigest()
        text = (
            "# Report\n\n- **Script:** `data/x.py` (SHA-256: `" + digest + "`)\n\n"
            "## Appendix: `data/x.py` source\n\n```text\n" + source + "```\n"
        )
        checked = []
        self.assertEqual([], check_report(self.write(text), checked))
        self.assertEqual(1, len(checked))
        self.assertTrue(checked[0].startswith("verified "))

    def test_a_correction_cannot_borrow_the_digest_of_the_next_pin_on_the_line(self):
        text = (
            "# Report\n\n| Script | SHA-256 | Note | Script | SHA-256 |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"| `data/x.py` | `{OTHER}` | Correction at review | `data/y.py` | `{DIGEST}` |\n\n"
            f"## Appendix: `data/x.py` source\n\n```text\n{SOURCE}```\n\n"
            f"## Appendix: `data/y.py` source\n\n```text\n{SOURCE}```\n"
        )
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors), errors)
        self.assertIn("does not give the digest the appendix actually hashes to", errors[0])

    def test_a_bob_report_naming_a_data_script_with_no_hash_fails(self):
        text = "# Report\n\nRun `data/z.py` to reproduce; `data/z.py` reads the cache.\n"
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors), errors)
        self.assertIn("data/z.py is named with no SHA-256 beside it", errors[0])

    def test_the_same_mention_in_a_claude_record_or_of_a_repository_path_is_not_an_error(self):
        text = "# Report\n\nRun `data/z.py` to reproduce.\n"
        self.assertEqual([], check_report(self.write(text, "2026-09-26-claude-x.md")))
        repo = "# Report\n\nSee `tests/test_z.py` and `scripts/check_reports.py`.\n"
        self.assertEqual([], check_report(self.write(repo)))

    def test_an_allow_list_entry_covers_a_hashless_bob_mention(self):
        check_reports.UNVERIFIABLE[("2026-09-26-bob-x.md", "data/z.py")] = (OTHER, "reason")
        self.addCleanup(check_reports.UNVERIFIABLE.pop, ("2026-09-26-bob-x.md", "data/z.py"))
        text = "# Report\n\nRun `data/z.py` to reproduce.\n"
        self.assertEqual([], check_report(self.write(text)))

    def test_mentions_are_reported_once_each_and_exclude_pins(self):
        text = report() + "\nAlso `a/b.py`, again `a/b.py`, and `c/d.py`.\n"
        self.assertEqual(["a/b.py", "c/d.py"], check_reports.hashless_mentions(text))
        mentions = []
        self.assertEqual(
            [], check_report(self.write(text, "2026-09-26-claude-x.md"), None, mentions)
        )
        self.assertEqual(
            ["2026-09-26-claude-x.md:a/b.py", "2026-09-26-claude-x.md:c/d.py"], mentions
        )

    def test_an_appendix_without_a_hash_is_one_error_not_two(self):
        text = "## Appendix: `data/x.py` source\n\n```text\n" + SOURCE + "```\n"
        errors = check_report(self.write(text))
        self.assertEqual(1, len(errors), errors)
        self.assertIn("no stated SHA-256", errors[0])
