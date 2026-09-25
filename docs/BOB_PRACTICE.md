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
4. **Every number has its source.** For each count, hash or total, the report says
   which command or file produced it, so another agent can reproduce it.
5. **Failures are in the report.** Errors, invalid runs, retries and anything skipped
   are listed with the exact message, not left out or summarised away.
6. **Findings and ideas are separate.** Facts you measured go under the results; your
   suggestions go under "Ideas and proposals", each with why it would help and how to
   test it.

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
  report.

## Your final message

- The first line starts with "IBM Bob". No other line starts with those words.
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
| 2026-09-25 | PR #41 (owner session) | The review said the shell "would pass" `bash -n` without running it. | Self-check 1. |
