# Task for Bob: publish and cross-check the 40 V0 baseline trace hashes

- **Written by:** Claude, 2026-09-25. It closes the open item in
  [the V0 equivalence results](../reviews/2026-09-25-claude-v0-equivalence-results.md)
  ("the owner will revisit Bob's cross-check of his 40 baseline hashes after the merge").
- **Review:** start only after Codex approves this file at a named SHA, or the owner says
  go.
- **Branch for your report:** `bob/v0-trace-crosscheck`. Do not push to any other
  branch. Do not merge.

## Why

Claude wrote the code under test and ran both trees on Linux, so its 40/40 result is
**not independent**. You already produced the 40 **baseline** traces (`c07f856`) on
Windows during the approved V0 task, and your one candidate trace matched Claude's
(`b12c0ffe…`). Publishing all 40 baseline hashes and comparing them with Claude's table
turns this into a cross-platform, cross-agent check at almost no cost.

## Steps

1. **Use your existing traces if they are still on disk.** These are the 40
   `.trace.jsonl` files from the baseline tree (`c07f856`) that the approved task
   produced: every dataset, fee level and run listed in the results table.
   - If they are gone, re-run **only the baseline tree**. Use the scripts and fixed
     inputs in [`2026-09-24-bob-v0-equivalence.md`](2026-09-24-bob-v0-equivalence.md),
     unchanged. Record that you re-ran it, and your Python version.
   - Do not fetch data for the reserved window (2025-01 onward). Do not change tracked
     files.
2. **Hash each trace:** compute SHA-256 over each file's bytes, for example with
   `Get-FileHash -Algorithm SHA256` or `sha256sum`.
3. **Compare** each hash with the SHA-256 column of the table
   "Candidate trace fingerprints" in
   [the results file](../reviews/2026-09-25-claude-v0-equivalence-results.md). Claude
   showed that baseline and candidate traces are byte-identical, so those values are also
   the expected baseline hashes.
4. **Report** in `docs/reviews/2026-09-25-bob-v0-trace-crosscheck.md` on your branch:
   - a table: dataset, fee level, run, fill count, your SHA-256, match yes/no;
   - the count of matches out of 40;
   - your OS, Python version and the commit you ran;
   - whether the traces were existing files or a fresh baseline run.

   For any mismatch, list both hashes and the first differing line of the two traces,
   if you have Claude's trace or can regenerate it. Do not change code or fix anything.
5. Open a PR from your branch and hand it back to Claude and Codex.

## Out of scope

- Any code, config, manifest, spec or result change.
- The reserved evaluation window.
- Merging or approving anything.
