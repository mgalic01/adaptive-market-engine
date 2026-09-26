# Bob's working practice

Read this before every review and every task run. It collects what reviews of Bob's
work have found, with how to catch each problem yourself before anyone else does. The
rules in [the handbook](AGENT_HANDOFF.md) still decide what Bob may do; this file is
about doing it well. Claude adds a lesson after each review that finds one.

## Before you finish: self-check

Run through this list and fix anything it finds before your final message.

1. **Every check you report, you ran.** Name the command and quote the part of its
   output that shows the result. A check you did not run is written "not run", with
   the reason. Never write "would pass".
2. **Every path you cite exists.** For each file or link in your report, run
   `test -f <path>` (or `ls`) and fix the path if it fails.
3. **Only your report changed.** `git status --porcelain --untracked-files=all`
   shows exactly one new file, your report under `docs/reviews/`. Working files go
   under `data/`.
   Then run `python scripts/check_reports.py`: CI runs it on every PR (index links,
   appendix hashes, `text` fences) and, on a `bob/task-` branch, also checks that
   the branch changes only your report and adds exactly one index row.
4. **Every number has its source.** For each count, hash or total, the report says
   which command or file produced it, so another agent can reproduce it.
5. **Failures are in the report.** Errors, invalid runs, retries and anything skipped
   are listed with the exact message, not left out or summarised away.
6. **Findings and ideas are separate.** Facts you measured go under the results; your
   suggestions go under "Ideas and proposals", each with why it would help and how to
   test it.
7. **Counts come from code.** Every "N months", "N files" or "N of M" is printed by a
   script from the same list the report shows (`len(...)`), never typed. State what
   was counted (for example, whether links inside code are included).
8. **Times come from the clock** (task runs). Run `date -u` at the start and the end
   and paste the output. Never write a time from memory. In a review, where you cannot
   run commands, write no times.
9. **Every sentence agrees with your own tables.** Reread each summary sentence
   ("clean throughout 2022", "a bull market") against the rows it summarises.
10. **The report is final text.** Fix a table when you find an error in it; do not
    append "correction" notes or leave working ("Wait — …") in the report. Reread it
    once from the top, as the reader will.
11. **Every verdict has its table.** A pass or fail must be recomputable from rows in
    the report.

## Reviewing a change

- **Trace the failure paths, not only the success path.** For each changed step ask:
  what happens if this command fails, if an input is empty or missing, if it runs
  twice, or if an earlier step failed? Then read what the next step (an alert, a
  cleanup, a reply) says in that case, and check that it is still true.
  *Example (PR #41):* the review confirmed that a failed PR creation no longer failed
  the job. It did not follow the case where the later reply step failed: the alert then
  said "nothing was committed" although the report was already pushed. The automated
  review found it.
- **Compare against the stated goal and the handbook.** Check that the PR does what its
  description says. Check that it does nothing more. Check that it agrees with
  `docs/AGENT_HANDOFF.md`.
- **A suggested fix must name real things.** Before you propose a field, function,
  file or option, find it (`grep -n`, or read the file) and quote where it is. If it
  does not exist, say so and describe what is missing instead of inventing a name.
  *Example (PR #42):* the review rightly flagged that the scorecard task did not say
  where the filter failure is recorded, but suggested a `rejection_reason` field that
  does not exist; the count is `transient_pauses`.
- **Regular expressions on untrusted text:** look for nested quantifiers such as
  `(a+)*` or `(?:[#*]+ *)*`. They can backtrack exponentially on a long run of
  matching characters. Ask for one flat character class instead, and a timing test.
  *Example (PR #42):* the automated review found such a pattern in the extractor; a
  24-character run took over a second.
- **Read the whole test before judging it.** A test's input can be built in a
  different place from its expected value. Trace what is passed in, not only what is
  compared. *Example (PR #42):* the review called
  `test_handoff_heading_before_the_header_is_dropped` misleading because `body` has no
  heading; the heading is added inside the `stream(...)` call that builds the input.
- **Say what you could not check.** The GitHub review cannot run commands. Say which
  claims you took from the diff alone.
- **One verdict, at the head you read.** NOTED or FLAGGED, with the full head SHA.

## Running a task

- **Do exactly the task, then look further.** Do everything the task file asks, in its
  order, and stop on its stop conditions. When you notice something useful beyond the
  task, report it under "Ideas and proposals". Never act on it in the same run.
- **Verify beyond the minimum.** When a task asks you to compare some columns and more
  are available, compare them all and report the extra ones separately.
  *Example (PR #40):* the trace cross-check compared hashes and fill counts. Return %
  and rejected frames were in the same table and were not compared.
- **Keep to the task's paths.** The task names your report path. Do not edit
  `docs/reviews/README.md` or any other tracked file; the index row is added at
  review. *Example (issue #31):* an index edit failed a 78-minute run.
- **Write scripts to files under `data/`, then run them.** This keeps the log readable
  and lets a reviewer rerun exactly what you ran. Put each script's SHA-256 in the
  report, and the source of every script under about 80 lines in an appendix: `data/`
  is git-ignored and disappears with the machine, so a hash alone cannot be rerun.
  Fence the appendix as `text`, not `python`: CI's `ruff format --check` reformats
  Python blocks in Markdown, which would change the source. Hash the file after its
  last edit, and check that the appendix copy gives the same hash:
  `sed -n '<first>,<last>p' <report> | sha256sum`. *Example (PR #60):* the
  `events.py` in the appendix did not match its stated hash.
- **Test an idea against your own evidence before proposing it.** *Example (PR #49):*
  the proposed parser rule `close_ms <= open_ms + step - 1` would still reject the
  2017-09 row the same report quoted (close one millisecond past the boundary).
- **Check that an idea does not already exist.** `grep -rn <keyword> src config docs`
  first. *Example (PR #49):* daily warm-up from `1d` bars was proposed; it is P3
  (`daily_warmup_start` in both dataset specs).
- **Settle "likely" with data.** When you write "likely" or "appears", look for the
  field that confirms or refutes it (for example `decisions_by_bar` and
  `top_reasons_by_bar` in `results.json`) and report what it shows.
- **Implement every definition in the task.** Before running, list each class, status
  or rule the task defines and note the line of your script that implements it. A class
  with zero or very few rows is a reason to check the test, not a finding.
  *Example (PR #59):* the task counted an unaligned open as `other`; the script never
  tested the open, omitting 66,179 unaligned-open rows. The `other` total was therefore
  reported as 20 instead of 66,199 (66,179 plus the 20 `close < open` rows).
- **Enumerate what should exist, not what you found.** Build expected hours, days or
  files from the listed span, then compare the data against it. Check one known event
  end to end. *Example (PR #60):* hours missing from both the 1m and 1h archives were
  in neither key set, so the real outages (2018-06-26, 2019-05-15) never reached the
  event tables.
- **Say which fields differ.** When a comparison reports a mismatch, print the fields
  and the size of the difference. *Example (PR #60):* "price/volume mismatch" on
  2021-01-21 was a volume-only difference of 2.4%.
- **Proposed paths must survive the machine.** Nothing under `data/` can be used by
  CI or another agent (`git check-ignore -v <path>`).

## Your final message

- The first line starts with the plain words "IBM Bob": not a heading, not bold, and
  not a "Bob → Claude handoff" title, even when the request carries one. No other line
  starts with those words. (The handoff titles in the handbook are for the owner's Bob
  session, not for the GitHub workflows.)
- Read every file you need first, then write the whole answer in one go, with no file
  reads after it starts.
- Write the signature only as your last line. When you refer to it in the text, say
  "the signature" rather than quoting it.
- End with the signature line the prompt gives you, and write nothing after it.
- Keep the message to the prompt's length limit. Put details in the report file.

## Lessons log

| Date | Where | What happened | The habit that catches it |
| --- | --- | --- | --- |
| 2026-09-25 | Issue #31 | The first task run edited `docs/reviews/README.md`; the run failed. | Self-check 3. |
| 2026-09-25 | PR #40 | The report linked a task file that does not exist (`…-trace-crosscheck.md` instead of `…-trace-hash-crosscheck.md`). | Self-check 2. |
| 2026-09-25 | PR #40 | Only the requested columns were compared. | "Verify beyond the minimum". |
| 2026-09-25 | PR #39 | A reply had a body line starting with "IBM Bob", which cut the posted answer short (now fixed in the extractor as well). | "Your final message". |
| 2026-09-25 | PR #41 | The review checked the happy path; the failure alert's wording was wrong in one failure case. | "Trace the failure paths". |
| 2026-09-25 | PR #42 | A valid flag suggested a field name (`rejection_reason`) that does not exist. | "A suggested fix must name real things". |
| 2026-09-25 | PR #42 | A re-review was refused by the workflow: no line started with "IBM Bob", most likely because the answer opened with a handoff title or bold name. (The extractor now accepts bold and heading forms too.) | "Your final message". |
| 2026-09-25 | PR #41 (owner session) | The review said the shell "would pass" `bash -n` without running it. | Self-check 1. |
| 2026-09-26 | PR #42 | Neither Bob review caught the exponential-backtracking pattern; the automated review did. Bob agreed the habit belongs here. | "Regular expressions on untrusted text". |
| 2026-09-26 | PR #42 | A test was called misleading because only the expected value was read, not the input built from it. | "Read the whole test before judging it". |
| 2026-09-26 | PRs #42–#44 | Review answers were refused by the workflow three times. With "read first, answer in one go", the #43 answer got through; the #44 cause is not visible until #44's structure-only diagnostics merge. | "Your final message". |
| 2026-09-26 | PR #49 | A parser proposal contradicted the report's own example; a proposed feature already existed; two counts differed from their lists; the run times were wrong; "clean throughout 2022" contradicted the tables. | "Test an idea against your own evidence", "Check that an idea does not already exist", self-checks 7, 8, 9. |
| 2026-09-26 | PR #50 | A true statement was flagged as a mismatch; CI was proposed to run a script under the git-ignored `data/`; a link count had no stated rule. | Self-checks 7, 9; "Proposed paths must survive the machine". |
| 2026-09-26 | PR #51 | A correction was appended below a table that still showed the old claim; lower-risk functions were ranked above untested data loaders. | Self-check 10. |
| 2026-09-26 | PR #52 | Working ("Wait — …") left in the report; a reference-fee verdict without its table; a "likely" cause not checked against the recorded reasons. | Self-checks 10, 11; "Settle 'likely' with data". |
| 2026-09-26 | PR #54 | A review said `SUMMARY_FIELDS` has 46 keys; it has 49. The claim was stated as verified ("I verified … exactly those 46 keys"). | Self-check 7: count with code (`len(...)`) before stating a number, in reviews too. |
| 2026-09-26 | PR #59 | The summary gave 9 usable months, 280 files and 98 pair-months; the report's own sections give 10, 214 and 107. The task's unaligned-open class was not implemented. A rule was called safe without the test that was possible in the same run. | Self-checks 7, 9; "Implement every definition in the task"; "Test an idea against your own evidence". |
| 2026-09-26 | PR #60 | Hours missing from both archives got no status, so the outages named in the ideas were in no table; an idea's "7 hours" was 14 by the year table; a volume-only mismatch was called price/volume; the appendix `events.py` did not match its stated hash; `python` fences failed CI's format check on both reports. | "Enumerate what should exist"; self-checks 9, 11; "Say which fields differ"; "Write scripts to files under `data/`". |
