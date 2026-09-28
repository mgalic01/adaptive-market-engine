"""Claims on PRs: parsing, expiry, one holder at a time, and the hook's decisions."""

import io
import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import claims  # noqa: E402
from claims import REPO, evaluate, find_targets, hook_decision, parse_command  # noqa: E402

ME = "e0b16be3-c9c5-4cc7-8ca2-46dcfa9af199"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
_ids = iter(range(1000, 100000))


def comment(body, at="2026-09-28T11:00:00Z", login="mgalic01", assoc="OWNER"):
    return {
        "id": next(_ids),
        "created_at": at,
        "body": body,
        "user": {"login": login},
        "author_association": assoc,
    }


def claim(tag="Claude Code e0b16be3", cmd="/claim 24h review", at="2026-09-28T11:00:00Z"):
    return comment(f"[{tag}]\n{cmd}", at=at)


def git_stub(branch="claude/x", origin=f"https://github.com/{REPO}.git"):
    def fake(cwd, *args):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return branch
        if args[:2] == ("remote", "get-url"):
            return origin if args[2] == "origin" else "https://github.com/other/repo.git"
        return None

    return mock.patch.object(claims, "_git", side_effect=fake)


class ParseTest(unittest.TestCase):
    def test_claim_with_duration_and_note(self):
        c = parse_command(claim(cmd="/claim 5h review of head abc"))
        self.assertEqual(
            (c.kind, c.holder, c.hours, c.note),
            ("claim", "Claude Code e0b16be3", 5, "review of head abc"),
        )

    def test_default_duration_is_the_maximum(self):
        self.assertEqual(parse_command(claim(cmd="/claim fixes")).hours, 24)

    def test_duration_out_of_bounds_is_an_error(self):
        self.assertIsNotNone(parse_command(claim(cmd="/claim 25h x")).error)
        self.assertIsNotNone(parse_command(claim(cmd="/claim 0h x")).error)

    def test_bold_bob_tag_and_other_tags(self):
        self.assertEqual(parse_command(comment("**[Bob]** hand-off\n/claim 2h")).holder, "Bob")
        self.assertEqual(parse_command(comment("[Codex Desktop]\n/release")).kind, "release")

    def test_only_the_owner_account_counts(self):
        self.assertIsNone(parse_command(comment("[Bob]\n/claim", login="stranger", assoc="NONE")))
        self.assertIsNone(parse_command(comment("[Bob]\n/claim", assoc="CONTRIBUTOR")))

    def test_command_must_be_on_line_two(self):
        self.assertIsNone(parse_command(comment("[Bob]\ntext\n/claim 2h")))
        self.assertIsNone(parse_command(comment("[Bob]\n> /claim 2h")))
        self.assertIsNone(parse_command(comment("[Bob]\n```\n/claim 2h\n```")))
        self.assertIsNone(parse_command(comment("/claim 2h")))  # no tag
        self.assertIsNone(parse_command(comment("[Bob]\n/claims")))  # refresh only

    def test_an_edited_comment_no_longer_counts(self):
        edited = claim()
        edited["updated_at"] = "2026-09-28T11:05:00Z"
        self.assertIsNone(parse_command(edited))
        unedited = claim()
        unedited["updated_at"] = unedited["created_at"]
        self.assertIsNotNone(parse_command(unedited))

    def test_release_all_is_the_whole_first_line(self):
        self.assertEqual(parse_command(comment("/release all")).kind, "release-all")
        self.assertIsNone(parse_command(comment("please /release all")))


class EvaluateTest(unittest.TestCase):
    def test_active_until_expiry_measured_from_github_time(self):
        s = evaluate([claim(cmd="/claim 2h x", at="2026-09-28T10:30:00Z")], NOW)
        self.assertEqual(s.active.until, datetime(2026, 9, 28, 12, 30, tzinfo=UTC))
        s = evaluate([claim(cmd="/claim 1h x", at="2026-09-28T10:30:00Z")], NOW)
        self.assertIsNone(s.active)
        self.assertIsNotNone(s.expired)

    def test_second_holder_rejected_while_active(self):
        s = evaluate([claim(), claim(tag="Bob", at="2026-09-28T11:10:00Z")], NOW)
        self.assertEqual(s.active.holder, "Claude Code e0b16be3")
        self.assertEqual(len(s.rejected), 1)
        self.assertIn("held by [Claude Code e0b16be3]", s.rejected[0][1])

    def test_other_claude_session_is_another_holder(self):
        s = evaluate([claim(), claim(tag="Claude Code 012TnmLL", at="2026-09-28T11:10:00Z")], NOW)
        self.assertEqual(len(s.rejected), 1)

    def test_holder_renews_and_releases(self):
        s = evaluate(
            [claim(cmd="/claim 1h a"), claim(cmd="/claim 3h b", at="2026-09-28T11:30:00Z")], NOW
        )
        self.assertEqual(s.active.note, "b")
        s = evaluate([claim(), claim(cmd="/release", at="2026-09-28T11:30:00Z")], NOW)
        self.assertIsNone(s.active)

    def test_only_the_holder_releases(self):
        s = evaluate([claim(), claim(tag="Bob", cmd="/release", at="2026-09-28T11:30:00Z")], NOW)
        self.assertEqual(s.active.holder, "Claude Code e0b16be3")

    def test_owner_override(self):
        s = evaluate([claim(), comment("/release all", at="2026-09-28T11:30:00Z")], NOW)
        self.assertIsNone(s.active)

    def test_a_new_holder_may_claim_after_expiry_or_release(self):
        s = evaluate([claim(cmd="/claim 1h x", at="2026-09-28T09:00:00Z"), claim(tag="Bob")], NOW)
        self.assertEqual(s.active.holder, "Bob")
        self.assertEqual(s.rejected, [])

    def test_invalid_claim_is_rejected_and_takes_nothing(self):
        s = evaluate([claim(cmd="/claim 48h x")], NOW)
        self.assertIsNone(s.active)
        self.assertEqual(len(s.rejected), 1)

    def test_status_description_fits_the_limit(self):
        s = evaluate([claim(cmd="/claim 2h " + "x" * 300)], NOW)
        self.assertLessEqual(len(claims.describe(s)), 140)


class TargetTest(unittest.TestCase):
    def test_push_forms(self):
        with git_stub(branch="claude/cur"):
            cases = {
                "git push": ["claude/cur"],
                "git push -u origin claude/a": ["claude/a"],
                "git push --force origin +claude/a": ["claude/a"],
                "git push -f origin HEAD:refs/heads/claude/b": ["claude/b"],
                "git push origin HEAD": ["claude/cur"],
                "git push origin --delete claude/c": ["claude/c"],
                "git push origin :claude/d": ["claude/d"],
                "cd sub && git -C x push -q origin claude/e 2>&1 | tail -2": ["claude/e"],
                "git push --force-with-lease=claude/a:abc origin claude/a": ["claude/a"],
                "git push origin claude/f > log.txt 2>/dev/null": ["claude/f"],
            }
            for command, branches in cases.items():
                with self.subTest(command=command):
                    self.assertEqual([t.branch for t in find_targets(command, ".")], branches)

    def test_pushes_that_are_not_to_a_branch_here(self):
        with git_stub():
            self.assertEqual(find_targets("git push --dry-run origin claude/a", "."), [])
            self.assertEqual(find_targets("git push --tags", "."), [])
            self.assertEqual(find_targets("git push upstream claude/a", "."), [])
            self.assertEqual(find_targets("git commit -m 'then git push'", "."), [])
        self.assertTrue(find_targets("git push --all", ".")[0].every_branch)

    def test_detached_head_is_unknown_not_skipped(self):
        with git_stub(branch="HEAD"):
            self.assertIsNotNone(find_targets("git push", ".")[0].unknown)

    def test_merge_forms(self):
        with git_stub(branch="claude/cur"):
            self.assertEqual(
                find_targets("gh pr merge 139 --merge --match-head-commit abc", ".")[0].pr, 139
            )
            self.assertEqual(
                find_targets(f"gh pr merge https://github.com/{REPO}/pull/141 --squash", ".")[0].pr,
                141,
            )
            self.assertEqual(find_targets("gh pr merge --merge", ".")[0].branch, "claude/cur")
            self.assertEqual(
                find_targets(f"gh api -X PUT repos/{REPO}/pulls/7/merge", ".")[0].pr, 7
            )
            self.assertIsNotNone(
                find_targets("gh api graphql -f query='mutation{mergePullRequest}'", ".")[0].unknown
            )
            self.assertEqual(find_targets("gh pr merge 5 --repo other/repo", "."), [])
            url = f"gh pr merge 5 --repo https://github.com/{REPO}.git"
            self.assertEqual(find_targets(url, ".")[0].pr, 5)
            self.assertEqual(find_targets("gh pr merge 5 --repo=other/repo", "."), [])
            self.assertEqual(find_targets(f"gh pr merge 5 --repo={REPO}", ".")[0].pr, 5)
            # Option values that read like a repository flag are values, not the flag.
            for cmd in (
                'gh pr merge 141 --body "-R" --squash',
                "gh pr merge 141 --subject '--repo=other/repo' --merge",
                'gh pr merge 141 -t "--repo" -b x',
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.pr for t in find_targets(cmd, ".")], [141])
            # The REST path names the repository; field values cannot redirect it.
            api = f"gh api -X PUT repos/{REPO}/pulls/8/merge -f commit_title=-R"
            self.assertEqual(find_targets(api, ".")[0].pr, 8)
            self.assertEqual(find_targets("gh api -X PUT repos/other/repo/pulls/8/merge", "."), [])

    def test_windows_paths_keep_backslashes(self):
        with git_stub() as g:
            find_targets(r"git -C C:\Users\x\wt push origin claude/a", ".")
            self.assertIn(r"C:\Users\x\wt", str(g.call_args_list[0].args[0]))


class RepoMatchTest(unittest.TestCase):
    def test_anchored_match(self):
        for url in (
            REPO,
            f"https://github.com/{REPO}.git",
            f"https://github.com/{REPO}/",
            f"git@github.com:{REPO}.git",
        ):
            self.assertTrue(claims.is_this_repo(url), url)
        for url in (f"https://github.com/{REPO}-fork.git", f"https://github.com/x{REPO}"):
            self.assertFalse(claims.is_this_repo(url), url)


class MainHookTest(unittest.TestCase):
    def run_hook(self, command):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": ME}
        out = io.StringIO()
        with (
            mock.patch.object(claims, "hook_decision", side_effect=KeyError("boom")),
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(sys, "stdout", out),
        ):
            self.assertEqual(claims.main(["hook"]), 0)
        return json.loads(out.getvalue())

    def test_a_crash_refuses_a_merge_and_allows_the_rest(self):
        merge = self.run_hook("gh pr merge 1")
        self.assertEqual(merge["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("systemMessage", self.run_hook("git push origin claude/a"))


class CliTest(unittest.TestCase):
    def test_pagination_reads_every_page(self):
        pages = {1: [comment("x")] * 100, 2: [claim()]}

        def read(path):
            return pages.get(int(path.rsplit("page=", 1)[1]), [])

        self.assertEqual(len(claims.fetch_comments(5, read)), 101)
        self.assertEqual(len(claims.open_prs(read)), 101)

    def test_status_and_check(self):
        out = io.StringIO()
        recent = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (
            mock.patch.object(claims, "open_prs", return_value=[{"number": 7}]),
            mock.patch.object(claims, "fetch_comments", return_value=[claim(tag="Bob", at=recent)]),
            mock.patch.object(sys, "stdout", out),
        ):
            self.assertEqual(claims.main(["status"]), 0)
            self.assertEqual(claims.main(["check", "7", "--as", "**[Bob]**"]), 0)
            self.assertEqual(claims.main(["check", "7", "--as", "[Codex Desktop]"]), 1)
        self.assertIn("#7: claimed by [Bob]", out.getvalue())


class HookTest(unittest.TestCase):
    def reader(self, comments, prs=()):
        def read(path):
            if "/comments" in path:
                return comments if "page=1" in path else []
            if "pulls?state=open" in path:
                return list(prs) if "page=1" in path else []
            raise AssertionError(path)

        return read

    def payload(self, command, tool="Bash"):
        return {"tool_name": tool, "tool_input": {"command": command}, "session_id": ME, "cwd": "."}

    def test_merge_of_a_pr_held_by_another_is_denied(self):
        with git_stub():
            out = hook_decision(
                self.payload("gh pr merge 139 --merge"), self.reader([claim(tag="Bob")]), NOW
            )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("[Bob]", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn(
            "[Claude Code e0b16be3]", out["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_own_claim_and_free_pr_are_allowed(self):
        with git_stub():
            self.assertIsNone(
                hook_decision(self.payload("gh pr merge 139"), self.reader([claim()]), NOW)
            )
            self.assertIsNone(hook_decision(self.payload("gh pr merge 139"), self.reader([]), NOW))

    def test_push_to_a_claimed_branch_is_denied_in_powershell_too(self):
        prs = [{"number": 141, "head": {"ref": "claude/a", "repo": {"full_name": REPO}}}]
        with git_stub():
            out = hook_decision(
                self.payload("git push origin claude/a", tool="PowerShell"),
                self.reader([claim(tag="Claude Code 012TnmLL")], prs),
                NOW,
            )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_github_down_fails_closed_for_merge_and_open_for_push(self):
        def down(path):
            raise claims.GitHubError("GitHub unreachable")

        with git_stub():
            merge = hook_decision(self.payload("gh pr merge 1"), down, NOW)
            push = hook_decision(self.payload("git push origin claude/a"), down, NOW)
        self.assertEqual(merge["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("fail open", push["systemMessage"])

    def test_unrelated_commands_are_ignored_without_reading_github(self):
        def boom(path):
            raise AssertionError("read GitHub")

        self.assertIsNone(hook_decision(self.payload("git status"), boom, NOW))
        self.assertIsNone(hook_decision({"tool_name": "Read", "tool_input": {}}, boom, NOW))


class WorkflowTest(unittest.TestCase):
    def test_status_label_and_one_rejection_answer(self):
        comments = [claim(), claim(tag="Bob", at="2026-09-28T11:10:00Z")]
        sent = []
        event = {"pull_request": {"number": 9, "head": {"sha": "a" * 40}, "labels": []}}
        with (
            mock.patch.object(claims, "fetch_comments", return_value=comments),
            mock.patch.object(claims, "send", side_effect=lambda *a: sent.append(a)),
        ):
            claims.workflow("pull_request", event, NOW)
        status = next(a for a in sent if "/statuses/" in a[1])
        self.assertEqual(status[2]["state"], "failure")
        self.assertEqual(status[2]["context"], "claim-guard")
        self.assertTrue(any(a[1].endswith("/issues/9/labels") for a in sent))
        rejections = [a for a in sent if a[1].endswith("/issues/9/comments")]
        self.assertEqual(len(rejections), 1)

        # Re-evaluation does not answer the same rejected claim twice.
        answered = comments + [
            comment(rejections[0][2]["body"], login="github-actions[bot]", assoc="NONE")
        ]
        sent.clear()
        with (
            mock.patch.object(claims, "fetch_comments", return_value=answered),
            mock.patch.object(claims, "send", side_effect=lambda *a: sent.append(a)),
        ):
            claims.workflow("pull_request", event, NOW)
        self.assertFalse(any(a[1].endswith("/comments") for a in sent))

    def test_free_pr_is_green_and_loses_the_label(self):
        sent = []
        event = {
            "pull_request": {
                "number": 9,
                "head": {"sha": "b" * 40},
                "labels": [{"name": "claimed"}],
            }
        }
        with (
            mock.patch.object(claims, "fetch_comments", return_value=[]),
            mock.patch.object(claims, "send", side_effect=lambda *a: sent.append(a)),
        ):
            claims.workflow("pull_request", event, NOW)
        self.assertEqual(next(a for a in sent if "/statuses/" in a[1])[2]["state"], "success")
        self.assertTrue(any(a[0] == "DELETE" for a in sent))

    def test_comment_on_a_pr_reads_the_head_and_sets_the_status(self):
        sent = []
        event = {"issue": {"number": 9, "labels": [], "pull_request": {"url": "x"}}}
        with (
            mock.patch.object(claims, "fetch_comments", return_value=[claim()]),
            mock.patch.object(claims, "get", return_value={"head": {"sha": "c" * 40}}) as get,
            mock.patch.object(claims, "send", side_effect=lambda *a: sent.append(a)),
        ):
            claims.workflow("issue_comment", event, NOW)
        get.assert_called_once_with(f"repos/{REPO}/pulls/9")
        status = next(a for a in sent if "/statuses/" in a[1])
        self.assertTrue(status[1].endswith("/statuses/" + "c" * 40))
        self.assertEqual(status[2]["state"], "failure")

    def test_issue_gets_label_but_no_status(self):
        sent = []
        event = {"issue": {"number": 134, "labels": []}}
        with (
            mock.patch.object(claims, "fetch_comments", return_value=[claim()]),
            mock.patch.object(claims, "send", side_effect=lambda *a: sent.append(a)),
        ):
            claims.workflow("issue_comment", event, NOW)
        self.assertFalse(any("/statuses/" in a[1] for a in sent))
        self.assertTrue(any(a[1].endswith("/issues/134/labels") for a in sent))


if __name__ == "__main__":
    unittest.main()
