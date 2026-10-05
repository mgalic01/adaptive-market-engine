"""Claims on PRs: parsing, expiry, one holder at a time, and the hook's decisions."""

import io
import json
import shlex
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
            # A PR URL with a tab path, a query, a fragment or a trailing slash still
            # names the PR.
            for suffix in ("?tab=files", "#issuecomment-1", "/", "/files", "/commits/?x=1"):
                cmd = f"gh pr merge https://github.com/{REPO}/pull/141{suffix} --merge"
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, ".")[0].pr, 141)
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
            # A global repository flag before the subcommand.
            for cmd in (
                f"gh -R {REPO} pr merge 141 --squash",
                f"gh --repo {REPO} pr merge 141",
                f"gh --repo={REPO} pr merge 141",
                f"gh -R {REPO} api -X PUT repos/{REPO}/pulls/141/merge",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.pr for t in find_targets(cmd, ".")], [141])
            self.assertEqual(find_targets("gh -R other/repo pr merge 141", "."), [])
            # gh fills {owner}/{repo} from -R or from the checkout's origin.
            placeholder = (
                "gh api -X PUT repos/{owner}/{repo}/pulls/141/merge -f merge_method=squash"
            )
            self.assertEqual([t.pr for t in find_targets(placeholder, ".")], [141])
            with_r = f"gh -R {REPO} api -X PUT repos/{{owner}}/{{repo}}/pulls/141/merge"
            self.assertEqual([t.pr for t in find_targets(with_r, ".")], [141])
            other = "gh -R other/repo api -X PUT repos/{owner}/{repo}/pulls/141/merge"
            self.assertEqual(find_targets(other, "."), [])
            self.assertIsNotNone(find_targets("gh api -X PUT pulls/141/merge", ".")[0].unknown)
            # Any client can call the same REST or GraphQL merge.
            curl = f"curl -X PUT -H x https://api.github.com/repos/{REPO}/pulls/141/merge"
            self.assertEqual([t.pr for t in find_targets(curl, ".")], [141])
            other_curl = "curl -X PUT https://api.github.com/repos/other/repo/pulls/141/merge"
            self.assertEqual(find_targets(other_curl, "."), [])
            gql = "python -c 'post(\"mutation { mergePullRequest }\")'"
            self.assertIsNotNone(find_targets(gql, ".")[0].unknown)

    def test_windows_paths_keep_backslashes(self):
        with git_stub() as g:
            find_targets(r"git -C C:\Users\x\wt push origin claude/a", ".")
            self.assertIn(r"C:\Users\x\wt", str(g.call_args_list[0].args[0]))

    # Automated audit, 2026-09-29: every form below used to yield no target at all.

    def branches(self, command):
        return [t.branch for t in find_targets(command, ".")]

    def prs(self, command):
        return [t.pr for t in find_targets(command, ".")]

    def test_powershell_call_operator(self):
        git_exe = r"& 'C:\Program Files\Git\cmd\git.exe' push origin claude/a"
        with git_stub():
            for cmd in ("& git push origin claude/a", "&git push origin claude/a", git_exe):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])
            for cmd in ("& gh pr merge 141 --merge", "$out = gh pr merge 141 --merge"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [141])
            self.assertEqual(find_targets("& git push upstream claude/a", "."), [])
            self.assertEqual(find_targets("& git status", "."), [])

    def test_wrappers_and_shell_keywords(self):
        with git_stub():
            for cmd in (
                "env GIT_TRACE=1 git push origin claude/a",
                "env -u GH_TOKEN GIT_TRACE=1 git push origin claude/a",
                "/usr/bin/env git push origin claude/a",
                "timeout 60 git push origin claude/a",
                "timeout -s KILL 1.5m git push origin claude/a",
                "nohup git push origin claude/a",
                "nice -n 10 git push origin claude/a",
                "command git push origin claude/a",
                "time git push origin claude/a",
                "for i in 1; do git push origin claude/a; done",
                "! git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])
            for cmd in (
                "timeout 60 gh pr merge 5",
                "exec gh pr merge 5",
                "if true; then gh pr merge 5; fi",
                "{ gh pr merge 5; }",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            for cmd in (
                "env GIT_TRACE=1 git status",
                "timeout 60 git push upstream claude/a",
                "nohup git push --dry-run origin claude/a",
                "command -v gh",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])

    def test_shells_are_read_inside(self):
        bash_exe = r"& 'C:\Program Files\Git\bin\bash.exe' -c 'git push origin claude/a'"
        with git_stub():
            for cmd in (
                'bash -c "git push origin claude/a"',
                "sh -c 'git push origin claude/a'",
                'bash -lc "cd sub && git push origin claude/a"',
                'pwsh -c "git push origin claude/a"',
                bash_exe,
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])
            for cmd in (
                'bash -c "gh pr merge 5 --squash"',
                'pwsh -Command "gh pr merge 5 --squash"',
                "powershell -NoProfile -Command gh pr merge 5",
                'pwsh -NoProfile -Command "Set-Location sub; gh pr merge 5"',
                "cmd /c gh pr merge 5",
                "zsh -c \"bash -c 'gh pr merge 5'\"",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            for cmd in (
                'bash -c "git status"',
                "bash merge.sh",
                "pwsh -File merge.ps1",
                'bash -c "gh pr merge 5 --repo other/repo"',
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])

    def test_nesting_deeper_than_the_limit_is_unknown(self):
        cmd = "gh pr merge 5"
        for _ in range(claims.MAX_DEPTH):
            cmd = "bash -c " + shlex.quote(cmd)
        with git_stub():
            self.assertEqual(self.prs(cmd), [5])
            deeper = find_targets("bash -c " + shlex.quote(cmd), ".")
        self.assertEqual([(t.kind, t.pr) for t in deeper], [("merge", None)])
        self.assertIsNotNone(deeper[0].unknown)

    def test_command_substitutions_are_read_inside(self):
        with git_stub():
            # Codex review of #159: a quoted ")" does not end the substitution.
            self.assertEqual(self.prs("""echo $(eval 'printf ")"; gh pr merge 5')"""), [5])
            for cmd in (
                "echo $(gh pr merge 5)",
                "echo `gh pr merge 5`",
                "$(gh pr merge 5)",
                "x=$(echo $(gh pr merge 5 --squash))",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            self.assertEqual(self.branches("out=$(git push origin claude/a 2>&1)"), ["claude/a"])
            # A body read by the shell leaves the PR known; a commit message is no merge.
            body = 'gh pr merge 141 --squash --body "$(cat body.md)"'
            self.assertEqual([(t.pr, t.unknown) for t in find_targets(body, ".")], [(141, None)])
            commit = "git commit -m \"$(cat <<'EOF'\nFix the merge check\nEOF\n)\""
            self.assertEqual(find_targets(commit, "."), [])

    def test_substitutions_in_single_quotes_are_text(self):
        # Codex review of #159: the shell runs none of these.
        with git_stub():
            for cmd in (
                "echo '$(gh pr merge 5)'",
                "printf '%s' '`gh pr merge 5`'",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])
            # Double quotes still run them, and so do a closed or an escaped quote before.
            for cmd in (
                'echo "$(gh pr merge 5)"',
                "echo 'x' $(gh pr merge 5)",
                r"echo it\'s $(gh pr merge 5)",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])

    def test_here_document_bodies_are_input(self):
        # Codex review of #159: a quoted body is never expanded; an unquoted one only
        # runs its substitutions; a shell reading the body runs all of it.
        with git_stub():
            for cmd in (
                "cat <<'EOF' > notes.md\nrun $(gh pr merge 5) later\nEOF",
                'cat <<"EOF"\n`gh pr merge 5`\nEOF\necho done',
                "cat <<EOF\ngh pr merge 5\nEOF",
                "cat <<-\\EOF\n\t$(gh pr merge 5)\n\tEOF",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])
            # Codex review of #159: a quoted or escaped `<<` is text, so the next
            # line is a command, not a body.
            for cmd in (
                'echo "<<EOF"\ngh pr merge 5\necho EOF',
                "echo '<<EOF'\ngh pr merge 5\nEOF",
                "echo \\<<EOF\ngh pr merge 5\nEOF",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: a delimiter that is not a whole recognised word leaves
            # the here-document unstripped, so the merge after it is still found.
            for cmd in (
                "cat <<END+\nliteral\nEND+\ngh pr merge 5",
                "cat <<'END+'\nliteral\nEND+\ngh pr merge 5",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: a `<<` in a comment is no operator.
            for cmd in ("# <<EOF\ngh pr merge 5\nEOF", "echo hi # <<EOF\ngh pr merge 5"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: a body piped into a shell runs; an arithmetic shift is
            # no here-document.
            for cmd in (
                "cat <<'EOF' | bash\ngh pr merge 5\nEOF",
                "cat <<EOF | sh -s\ngh pr merge 5\nEOF",
                "((x << 1))\ngh pr merge 5",
                "echo $((x << 2))\ngh pr merge 5",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: a sourced body runs; an interpreter's body can send
            # an API merge, and may run more than the scan reads, so its merge word is
            # refused as well.
            for cmd in (
                "source /dev/stdin <<'EOF'\ngh pr merge 5\nEOF",
                ". /dev/stdin <<'EOF'\ngh pr merge 5\nEOF",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            api = f"https://api.github.com/repos/{REPO}/pulls/5/merge"
            put = (
                f"python3 - <<'EOF'\nimport urllib.request as r\n"
                f"r.urlopen(r.Request('{api}', method='PUT'))\nEOF"
            )
            self.assertCountEqual(self.prs(put), [5, None])
            # Codex review of #159: the legacy `$[...]` is arithmetic too, nested brackets
            # included.
            for cmd in ("x=$[x << END ]\ngh pr merge 5", "x=$[a[1] << 2]\ngh pr merge 5"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: a reader inside a command substitution still runs the
            # body; a quoted pipe is no pipeline.
            self.assertEqual(self.prs("x=$(bash <<'EOF'\ngh pr merge 5\nEOF\n)"), [5])
            self.assertEqual(find_targets("echo '| bash' <<'EOF'\ngh pr merge 5\nEOF", "."), [])
            # Codex review of #159: a reader not known to read data runs the body, whatever
            # shell it is, and one not known to be a shell may run more than the scan
            # reads, so its merge word is refused too; data readers and gh's own data
            # stay data.
            for cmd in (
                "ash <<'EOF'\ngh pr merge 5\nEOF",
                "busybox sh <<'EOF'\ngh pr merge 5\nEOF",
                "ssh host <<'EOF'\ngh pr merge 5\nEOF",
                "cat <<'EOF' | mksh\ngh pr merge 5\nEOF",
            ):
                with self.subTest(cmd=cmd):
                    self.assertCountEqual(self.prs(cmd), [5, None])
            for cmd in (
                "git commit -F - <<'EOF'\nfix: then gh pr merge 5\nEOF",
                "gh pr comment 7 -F - <<'EOF'\nplease gh pr merge 5\nEOF",
                "cat <<'EOF' | grep merge\ngh pr merge 5\nEOF",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])
            mutation = "gh api graphql -F query=@- <<'EOF'\nmutation { mergePullRequest }\nEOF"
            self.assertEqual([t.kind for t in find_targets(mutation, ".")], ["merge"])
            # Codex review of #159: an interpreter can run anything it reads.
            run = (
                "python3 - <<'EOF'\nimport subprocess\n"
                "subprocess.run(['gh', 'pr', 'merge', '5'])\nEOF"
            )
            self.assertIn("merge", [t.kind for t in find_targets(run, ".") if t.unknown])
            self.assertEqual(find_targets("node - <<'EOF'\nconsole.log(1)\nEOF", "."), [])
            # Codex review of #159: awk, sed and editors can run commands too; a shell's
            # input is read exactly, so its echoed words are not refused.
            for cmd in (
                "awk -f - <<'EOF'\nBEGIN { system(\"gh pr merge 5\") }\nEOF",
                "sed -f - x <<'EOF'\n1e gh pr merge 5\nEOF",
                "vim -es <<'EOF'\n!gh pr merge 5\nEOF",
            ):
                with self.subTest(cmd=cmd):
                    unknown = [t.kind for t in find_targets(cmd, ".") if t.unknown]
                    self.assertEqual(unknown, ["merge"])
            # A merge the scan reads does not hide one it cannot (`system()` here).
            hidden = "awk -f - <<'EOF'\nBEGIN { system(\"gh pr merge 5\") }\ngh pr merge 6\nEOF"
            self.assertCountEqual(self.prs(hidden), [6, None])
            self.assertEqual(find_targets("bash <<'EOF'\necho merge later\nEOF", "."), [])
            # Codex review of #159: a function body's opener is not the reader.
            for cmd in (
                "f(){ bash <<'EOF'\ngh pr merge 5\nEOF\n}; f",
                "f() { bash <<'EOF'\ngh pr merge 5\nEOF\n}",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            # Codex review of #159: an argument named like a shell is not the reader.
            self.assertEqual(find_targets("echo bash <<'EOF'\n(gh pr merge 5)\nEOF", "."), [])
            # Codex review of #159: a shell elsewhere on the line is not this body's reader.
            self.assertEqual(
                find_targets("bash -c true; cat <<'EOF'\n(gh pr merge 5)\nEOF", "."), []
            )
            # Codex review of #159: a quoted reader name is still the shell that runs it.
            self.assertEqual(self.prs("/bin/'bash' <<'EOF'\ngh pr merge 5\nEOF"), [5])
            # Codex review of #159: two bodies on one line, read in order.
            self.assertEqual(find_targets("cat <<'A' <<'B'\nfirst\nA\ngh pr merge 5\nB", "."), [])
            for cmd in (
                "cat <<EOF\nit's $(gh pr merge 5)\nEOF",
                "bash <<'EOF'\ngh pr merge 5\nEOF",
                "cat <<'EOF'\ntext\nEOF\ngh pr merge 5",
                "cat <<'A' <<'B'\nfirst\nA\nsecond\nB\ngh pr merge 5",
                "cat <<'A'; bash <<'B'\nfirst\nA\ngh pr merge 5\nB",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])

    def test_wrapper_options_with_values_and_env_split_strings(self):
        # Codex review of #159: each runs the merge after the wrapper's options.
        with git_stub():
            for cmd in (
                "env -C sub gh pr merge 5",
                "env --chdir sub gh pr merge 5",
                "env -S 'gh pr merge 5'",
                "env -S'gh pr merge 5'",
                "env --split-string='gh pr merge 5'",
                "env -u HOME -S 'gh pr merge 5 --squash'",
                "/usr/bin/time -f %e gh pr merge 5",
                "nice --adjustment 5 gh pr merge 5",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])

    def test_separators_inside_quotes_are_text(self):
        # Codex review of #159: splitting inside the quotes cut `bash -c`'s merge off.
        with git_stub():
            for cmd in (
                'bash -c "gh pr merge 5; echo done"',
                "sh -c 'cd sub && gh pr merge 5'",
                'gh pr merge 5 --body "a; b & c | d"',
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(
                        [(t.pr, t.unknown) for t in find_targets(cmd, ".")], [(5, None)]
                    )

    def test_git_global_options_with_values(self):
        # Codex review of #159: the option's value is not the subcommand.
        with git_stub():
            for cmd in (
                "git --git-dir .git push origin claude/a",
                "git --work-tree . --namespace ns push origin claude/a",
                "git --git-dir=.git push origin claude/a",
                "git -c core.pager=cat --config-env x=Y push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])

    def test_the_repository_selected_by_git_dir_is_checked(self):
        # Codex review of #159: a push into this repository from another directory.
        def fake(cwd, *args):
            ours = "other" not in Path(cwd).as_posix()
            if args[:2] == ("remote", "get-url"):
                return f"https://github.com/{REPO}.git" if ours else "https://x/other.git"
            return "claude/x" if args[:2] == ("rev-parse", "--abbrev-ref") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            for cmd in (
                "cd /tmp/other && git --git-dir /work/repo/.git push origin claude/a",
                "cd /tmp/other && git --git-dir=/work/repo/.git push origin claude/a",
                "cd /tmp/other && GIT_DIR=/work/repo/.git git push origin claude/a",
                "cd /tmp/other && env GIT_DIR=/work/repo/.git git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    targets = find_targets(cmd, ".")
                    self.assertEqual([t.branch for t in targets], ["claude/a"])
            # The other repository's own push is not this repository's.
            self.assertEqual(find_targets("cd /tmp/other && git push origin claude/a", "."), [])

    def test_env_chdir_selects_the_repository(self):
        # Codex review of #159: env -C runs the push in this repository.
        def fake(cwd, *args):
            ours = "other" not in Path(cwd).as_posix()
            if args[:2] == ("remote", "get-url"):
                return f"https://github.com/{REPO}.git" if ours else "https://x/other.git"
            return "claude/x" if args[:2] == ("rev-parse", "--abbrev-ref") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            for cmd in (
                "cd /tmp/other && env -C /work/repo git push origin claude/a",
                "cd /tmp/other && env --chdir=/work/repo git push origin claude/a",
                "cd /tmp/other && env -u HOME -C /work/repo git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.branch for t in find_targets(cmd, ".")], ["claude/a"])

    def test_each_wrapper_consumes_its_own_value_options(self):
        # Codex review of #159: sudo's values, and `time -p`, which takes none.
        with git_stub():
            for cmd in (
                "sudo --user root git push origin claude/a",
                "sudo -g wheel -u root git push origin claude/a",
                "sudo -S -u root git push origin claude/a",
                "time -p git push origin claude/a",
                "doas -u root git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])

        def fake(cwd, *args):
            ours = "other" not in Path(cwd).as_posix()
            if args[:2] == ("remote", "get-url"):
                return f"https://github.com/{REPO}.git" if ours else "https://x/other.git"
            return "claude/x" if args[:2] == ("rev-parse", "--abbrev-ref") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            for cmd in (
                "cd /tmp/other && sudo -D /work/repo git push origin claude/a",
                "cd /tmp/other && sudo --chdir=/work/repo git push origin claude/a",
                "cd /tmp/other && sudo -u root env -C /work/repo git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.branch for t in find_targets(cmd, ".")], ["claude/a"])

    def test_git_aliases_that_push_are_checked(self):
        # Codex review of #159: an alias, given with -c or configured, runs a push.
        calls = []

        def fake(cwd, *args):
            calls.append(args)
            if args == ("config", "--get", "alias.p"):
                return "push"
            if args == ("config", "--get", "alias.pp"):
                return "p --force"  # an alias of an alias
            if args[:2] == ("remote", "get-url"):
                return f"https://github.com/{REPO}.git"
            return "claude/x" if args[:2] == ("rev-parse", "--abbrev-ref") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            for cmd in (
                "git -c alias.q=push q origin claude/a",
                "git p origin claude/a",
                "git pp origin claude/a",
                "git -c 'alias.r=!git push origin claude/a' r",
                "git send-pack origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.branch for t in find_targets(cmd, ".")], ["claude/a"])
            calls.clear()
            self.assertEqual(find_targets("git status && git log -1", "."), [])
            self.assertFalse([c for c in calls if c[:1] == ("config",)])  # builtins: no lookup

    def test_api_merges_count_only_from_clients_that_send_them(self):
        # Codex review of #159: a command that only names the API merges nothing.
        url = f"https://api.github.com/repos/{REPO}/pulls/5/merge"
        with git_stub():
            for cmd in ("echo mergePullRequest", f"printf '%s\\n' {url}"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])
            for cmd in (
                f"curl -X PUT {url}",
                f"sudo curl -X PUT {url}",
                f"Invoke-RestMethod -Method Put -Uri {url}",
                # Codex review of #159: a versioned interpreter is still one.
                f"python3.12 -c \"Request('{url}', method='PUT')\"",
                f"ruby3.2 -e 'put(\"{url}\")'",
                f"perl5.36 -e 'put(q({url}))'",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual([t.pr for t in find_targets(cmd, ".")], [5])

    def test_case_arms_and_function_bodies_are_read(self):
        # Codex review of #159: the command follows a case pattern or a function's name.
        with git_stub():
            for cmd in (
                "case x in x) gh pr merge 5;; esac",
                "case $b in main) echo no;; *) gh pr merge 5;; esac",
                "f() { gh pr merge 5; }; f",
                "f () { gh pr merge 5; }",
                "function f { gh pr merge 5; }",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            self.assertEqual(
                self.branches("case $b in (main|dev) git push origin claude/a;; esac"),
                ["claude/a"],
            )

    def test_subshells_and_process_substitutions_are_read(self):
        # Codex review of #159: bash runs what the parentheses hold.
        with git_stub():
            for cmd in ("(gh pr merge 5)", "cat <(gh pr merge 5)", "tee >(gh pr merge 5) < x"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            for cmd in (
                "if true; then (git push origin claude/a); fi",
                "diff <(git show HEAD) <(git push origin claude/a)",
                "sudo -R / git push origin claude/a",
                "sudo --chroot / git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])
            # A command substitution is still read once, by substitutions().
            self.assertEqual(self.prs("echo $(gh pr merge 5)"), [5])

    def test_launchers_run_commands_known_only_at_run_time(self):
        # Codex review of #159: xargs supplies the PR or branch when it runs.
        with git_stub():
            merge = find_targets("printf '5\\n' | xargs gh pr merge", ".")
            self.assertEqual([(t.kind, bool(t.unknown)) for t in merge], [("merge", True)])
            push = find_targets("git branch | xargs -I{} git push origin {}", ".")
            self.assertEqual([(t.kind, bool(t.unknown)) for t in push], [("push", True)])
            self.assertEqual(find_targets("find . -name '*.py' -print", "."), [])

    def test_a_lone_ampersand_ends_a_command(self):
        # Codex review of #159: the shell runs both commands. A redirection is no separator,
        # and PowerShell's call operator still works.
        with git_stub():
            self.assertEqual(self.prs("true & gh pr merge 5"), [5])
            for cmd in (
                "git status & git push origin claude/a",
                "git push origin claude/a 2>&1 &",
                "git push origin claude/a &> log.txt",
                "$r = & git push origin claude/a",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.branches(cmd), ["claude/a"])

    def test_a_pr_or_branch_the_shell_computes_is_unknown(self):
        with git_stub():
            for cmd in (
                "gh pr merge $(gh pr view --json number -q .number)",
                "gh pr merge $n --squash",
                "gh pr merge `cat pr.txt`",
            ):
                with self.subTest(cmd=cmd):
                    unknown = [t.kind for t in find_targets(cmd, ".") if t.unknown]
                    self.assertEqual(unknown, ["merge"])
            push = find_targets("git push origin $branch", ".")
            self.assertEqual([(t.kind, t.branch) for t in push], [("push", None)])
            self.assertIsNotNone(push[0].unknown)

    def test_commands_known_only_at_run_time(self):
        with git_stub():
            for cmd in (
                'cmd="gh pr merge 5"; eval "$cmd"',
                'eval "gh pr merge $n"',
                '$gh = "gh"; & $gh pr merge 5',
                "$GH pr merge 5",
            ):
                with self.subTest(cmd=cmd):
                    targets = find_targets(cmd, ".")
                    self.assertEqual([t.kind for t in targets], ["merge"])
                    self.assertIsNotNone(targets[0].unknown)
            push = find_targets('b="claude/a"; eval "git push origin $b"', ".")
            self.assertEqual([(t.kind, t.branch) for t in push], [("push", None)])
            # Nothing pushed or merged, and a variable PowerShell only prints.
            for cmd in (
                'eval "$(ssh-agent -s)"',
                "$j = gh pr view 5 --json mergeable; $j | ConvertFrom-Json",
                'eval "$msg"; echo the merger is submerged',
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])

    def test_a_shell_body_or_bash_line_known_only_at_run_time(self):
        # Codex review of #159: a POSIX shell runs a lone variable as a command, so the
        # merge in the outer text counts, as for eval; PowerShell only prints `$c`.
        with git_stub():
            for cmd, posix in (
                ("cmd='gh pr merge 5'; bash -c \"$cmd\"", False),
                ("cmd='gh pr merge 6'; bash -c \"gh pr merge 5; $cmd\"", False),
                ("c='gh pr merge 5'; $c", True),
            ):
                with self.subTest(cmd=cmd):
                    targets = find_targets(cmd, ".", posix=posix)
                    self.assertIn("merge", [t.kind for t in targets if t.unknown])
            self.assertEqual(find_targets("$c = 'gh pr merge 5'; $c", "."), [])
            # A literal body keeps its PR known.
            body = "bash -c 'gh pr merge 5 --body \"$(cat b.md)\"'"
            self.assertEqual([(t.pr, t.unknown) for t in find_targets(body, ".")], [(5, None)])

    def test_literal_eval_text_is_read_as_the_command_it_runs(self):
        # Codex review of #159: only literal text is read; `$`, backticks or a backslash
        # leave it known only at run time (above).
        with git_stub():
            for cmd in (
                'eval "gh pr merge 5"',
                'iex "gh pr merge 5"',
                "Invoke-Expression 'gh pr merge 5'",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(
                        [(t.pr, t.unknown) for t in find_targets(cmd, ".")], [(5, None)]
                    )
            self.assertEqual(self.branches('eval "git push origin claude/a"'), ["claude/a"])
            for cmd in ("eval 'echo submerged'", "eval 'echo merge done'", "iex 'Write-Host push'"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(find_targets(cmd, "."), [])

    def test_repository_names_ignore_case(self):
        mixed = "MGalic01/Adaptive-Market-Engine"
        with git_stub():
            for cmd in (
                f"gh pr merge 5 -R {mixed}",
                "gh pr merge 5 --repo=MGALIC01/adaptive-market-engine",
                f"gh pr merge 5 --repo {REPO}.git/",
                f"gh -R {mixed} pr merge 5",
                f"gh api -X PUT repos/{mixed}/pulls/5/merge",
                f"gh -R {mixed} api -X PUT repos/{{owner}}/{{repo}}/pulls/5/merge",
                f"curl -X PUT https://api.github.com/repos/{mixed}/pulls/5/merge",
            ):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.prs(cmd), [5])
            self.assertEqual(
                self.branches(f"git push https://github.com/{mixed}.git claude/a"), ["claude/a"]
            )
            self.assertEqual(find_targets("gh pr merge 5 -R MGalic01/Other-Repo", "."), [])


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

    def test_case_is_ignored(self):
        for url in (
            "MGalic01/Adaptive-Market-Engine",
            "https://github.com/MGALIC01/adaptive-market-engine.git",
            "git@github.com:MGalic01/adaptive-market-engine.git",
            f"{REPO}.git/",
        ):
            self.assertTrue(claims.is_this_repo(url), url)
        self.assertFalse(
            claims.is_this_repo("https://github.com/MGalic01/Adaptive-Market-Engine-fork")
        )


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

    def test_own_claim_with_the_full_session_id_is_own(self):
        with git_stub():
            self.assertIsNone(
                hook_decision(
                    self.payload("gh pr merge 139"),
                    self.reader([claim(tag=f"Claude Code {ME}")]),
                    NOW,
                )
            )
            other = claim(tag="Claude Code e0b16be4-0000")
            out = hook_decision(self.payload("gh pr merge 139"), self.reader([other]), NOW)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_is_own(self):
        self.assertTrue(claims.is_own("Claude Code e0b16be3", ME))
        self.assertTrue(claims.is_own(f"Claude Code {ME}", ME))
        self.assertFalse(claims.is_own("Claude Code e0b16b", ME))  # too short to be sure
        self.assertFalse(claims.is_own("Bob", ME))
        self.assertFalse(claims.is_own("Claude Code e0b16be3", ""))

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

    def test_wrapped_forms_are_denied_when_held_and_allowed_when_own_or_free(self):
        # Automated audit, 2026-09-29: each of these used to run with no claim check.
        prs = [{"number": 139, "head": {"ref": "claude/a", "repo": {"full_name": REPO}}}]
        forms = (
            ("& git push origin claude/a", "PowerShell"),
            (r"& 'C:\Program Files\Git\cmd\git.exe' push origin claude/a", "PowerShell"),
            ("& gh pr merge 139 --merge", "PowerShell"),
            ('pwsh -Command "gh pr merge 139 --squash"', "Bash"),
            ('bash -c "cd sub && git push origin claude/a"', "Bash"),
            ("timeout 60 gh pr merge 139", "Bash"),
            ("env GIT_TRACE=1 git push origin claude/a", "Bash"),
            ("echo $(gh pr merge 139)", "Bash"),
            ("gh pr merge 139 -R MGalic01/Adaptive-Market-Engine", "Bash"),
        )
        with git_stub():
            for command, tool in forms:
                with self.subTest(command=command):
                    held = hook_decision(
                        self.payload(command, tool), self.reader([claim(tag="Bob")], prs), NOW
                    )
                    self.assertEqual(held["hookSpecificOutput"]["permissionDecision"], "deny")
                    own = self.reader([claim()], prs)
                    self.assertIsNone(hook_decision(self.payload(command, tool), own, NOW))
                    free = self.reader([], prs)
                    self.assertIsNone(hook_decision(self.payload(command, tool), free, NOW))

    def test_a_git_alias_line_is_read_although_it_never_says_push(self):
        # Codex review of #159: the hook's pre-filter let `git p` through unread.
        prs = [{"number": 141, "head": {"ref": "claude/a", "repo": {"full_name": REPO}}}]

        def fake(cwd, *args):
            if args == ("config", "--get", "alias.p"):
                return "push"
            return f"https://github.com/{REPO}.git" if args[:2] == ("remote", "get-url") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            out = hook_decision(
                self.payload("git p origin claude/a"), self.reader([claim(tag="Bob")], prs), NOW
            )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_the_pre_filter_ignores_case(self):
        # Codex review of #159: PowerShell runs `Git p` as git.
        prs = [{"number": 141, "head": {"ref": "claude/a", "repo": {"full_name": REPO}}}]

        def fake(cwd, *args):
            if args == ("config", "--get", "alias.p"):
                return "push"
            return f"https://github.com/{REPO}.git" if args[:2] == ("remote", "get-url") else None

        with mock.patch.object(claims, "_git", side_effect=fake):
            out = hook_decision(
                self.payload("Git p origin claude/a", tool="PowerShell"),
                self.reader([claim(tag="Bob")], prs),
                NOW,
            )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_github_reporting_another_case_is_still_this_repo(self):
        mixed = {"full_name": "MGalic01/Adaptive-Market-Engine"}
        prs = [{"number": 141, "head": {"ref": "claude/a", "repo": mixed}}]
        with git_stub():
            out = hook_decision(
                self.payload("git push origin claude/a"), self.reader([claim(tag="Bob")], prs), NOW
            )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_run_time_commands_refuse_a_merge_and_warn_on_a_push(self):
        with git_stub():
            for command in ('c="gh pr merge 139"; eval "$c"', "gh pr merge $(cat pr.txt)"):
                with self.subTest(command=command):
                    out = hook_decision(self.payload(command), self.reader([]), NOW)
                    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                    self.assertIn("could not be determined", reason)
            push = hook_decision(
                self.payload('b="claude/a"; eval "git push origin $b"'), self.reader([]), NOW
            )
        self.assertIn("known only at run time", push["systemMessage"])

    def test_a_bash_line_running_a_variable_is_refused_as_a_merge(self):
        # Codex review of #159: the Bash tool runs a POSIX shell.
        with git_stub():
            out = hook_decision(self.payload("c='gh pr merge 5'; $c", "Bash"), self.reader([]), NOW)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "could not be determined", out["hookSpecificOutput"]["permissionDecisionReason"]
        )

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
            claims.workflow(event, NOW)
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
            claims.workflow(event, NOW)
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
            claims.workflow(event, NOW)
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
            claims.workflow(event, NOW)
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
            claims.workflow(event, NOW)
        self.assertFalse(any("/statuses/" in a[1] for a in sent))
        self.assertTrue(any(a[1].endswith("/issues/134/labels") for a in sent))


if __name__ == "__main__":
    unittest.main()
