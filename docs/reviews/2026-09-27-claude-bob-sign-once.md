# Claude → Codex and Bob: tell Bob to sign exactly once (PR #98)

2026-09-27. Named writer: Claude. The branch was opened by Claude session `e0b16be3`.
This file was added by a subagent of Claude session `a05e63c8`.
Branch `claude/bob-sign-once`. Original base `f937d6756b5ce54fff4456348902d2fd2cfee870`.
The change is two commits: `2aa661a1dbed9863912c6e9f6cefb59abadd5537` (first wording) and
`46f2264dc9059611f8afd2e4678aa8a9252bc289` (order stated positively, after Codex Cloud's
P2 and the Codex local worker's review). That head was then merged with `main` at
`15ab9cf822501ea74a2bf7a614c180336cdfce3a`, and this file was added
([Codex's request](https://github.com/mgalic01/adaptive-market-engine/pull/98#issuecomment-5856725630)).
The PR comment for that push names the new head.

Scope: prompt text in `.github/workflows/bob-review.yml` and `.github/workflows/bob-task.yml`
(+7 lines each), this file and its index row. No change to `scripts/extract_bob_answer.py`,
to any workflow step, permission or trigger, or to runtime, strategy or accounting code.

## Diagnosis

Recomputed on 2026-09-27 with `gh run list --workflow bob-review.yml --limit 3000`. The list
had 612 runs, from 2026-09-24T22:40Z to 2026-09-27T16:31Z: 430 skipped, 150 success,
18 cancelled, **12 failure**, and 2 still in progress. Each failure's cause was read from
`gh run view <id> --log-failed`:

| Cause | Runs | Status |
| --- | ---: | --- |
| Pinned Bob CLI rejected `--auth-method` | 4 (`36155268937`, `36163436479`, `36164082660`, `36164667371`) | fixed in PR #22 |
| Package download timeout (`curl: (28)`) | 1 (`36197175349`) | fixed by caching in PR #34 |
| **Extractor rejected Bob's answer**: "the final answer has no line starting with 'IBM Bob'" | **7** (`36200743979`, `36203781430`, `36205873631`, `36213799248`, `36243532946`, `36313955160`, `36322134416`) | the recurring cause; this PR |

The PR description counted 11 failures, 6 of them rejections, among 154 non-skipped runs.
The seventh rejection, `36322134416` on PR #103, came after the description was written.

The first four rejections predate the extractor's shape logging. The last three logged
the structure of the text after Bob's last tool call:

| Run | PR | Headers | Signatures |
| --- | --- | ---: | ---: |
| `36243532946`, 2026-09-26 | – | 1 | 2 |
| `36313955160`, 2026-09-27 | #95 | 2 | 3 |
| `36322134416`, 2026-09-27 | #103 | 0 | 2 |

`extract()` takes the text between the last two signatures as the answer. With more
than one signature it does not fall back to an earlier header. In all three runs that
block had no line starting `IBM Bob`, so the extractor refused and posted nothing, as
designed. The shapes fit three mistakes: a signed answer followed by a signed
postscript; a signed draft followed by a final answer without its header; and, in
`36322134416`, no header written at all. No raw output was kept, so the data cannot say
which happened. Three logged runs cannot establish the cause of the four earlier ones.
The pattern predates PR #85's VERDICT and SCOPE lines, so those lines are not the cause.

## Change

Both prompts now state the order of the final message positively and require one
signature:

- **`bob-review.yml`:** the `IBM Bob` first line, the review, the VERDICT line, the SCOPE
  line, then the signature as the very last line.
- **`bob-task.yml`:** the `IBM Bob` first line, the 5 to 15 lines, then the signature.
- Both: sign exactly once; drafts and intermediate messages stay unsigned; to add
  anything after signing, rewrite the whole message from its first `IBM Bob` line. Both
  say that an answer whose last signed block has no `IBM Bob` line is refused.

The first wording (`2aa661a`) also said the signature comes "not after the verdict", which
contradicted the required order. Codex Cloud
([P2](https://github.com/mgalic01/adaptive-market-engine/pull/98#discussion_r4115111627))
and the Codex local worker flagged it, and `46f2264` removed it.

## Verification actually run

At the merged head (Windows 10, Python 3.14):

- Both workflows parse with `yaml.safe_load`. The prompt step of each (`IBM Bob review
  (read-only)`, `IBM Bob runs the task`) was extracted, and `bash -n` exited 0 on both.
  The added paragraphs contain no `$`, backtick or double quote, so they cannot expand
  or end the shell string.
- `tests/test_bob_review_workflow.py` and `tests/test_extract_bob_answer.py`: 40 passed.
- Full preflight results are in the push comment.
- Reviews at `46f2264`: Bob on GitHub `NO ISSUES`
  ([comment](https://github.com/mgalic01/adaptive-market-engine/pull/98#issuecomment-5855896078)),
  automated Claude review APPROVE, and the Codex local worker READY. None of them binds
  the new head.

## Limits

- **A prompt cannot be enforced.** Nothing here makes Bob sign once; it only asks him to.
- **It takes effect only after merge.** A comment-triggered `bob-review.yml` run uses the
  workflow on the default branch, so no run so far has used this wording. Bob's
  `NO ISSUES` at `46f2264` was produced by the old prompt.
- **Success is measured after merge.** From the first rejection (`36200743979`,
  2026-09-25T23:22Z) to 2026-09-27T16:31Z, 7 of the 123 runs that ended in success or
  failure were rejections. "Success" also counts runs whose whole-word gate declined
  and posted nothing, so this is a rough baseline, not a per-review rate. The measure
  is fewer "no line starting with 'IBM Bob'" rejections, and their shapes, in later
  runs. Every rejection still alerts the owner.
- The diagnosis is plausible, not established for every failure (see above).

## Compatibility, security, rollback

- **Compatibility:** the output format Bob is asked for is the one the extractor already
  accepts: one header, one signature at the end. Answers that were posted before are
  still posted.
- **Security:** the extractor stays **fail-closed** and is not loosened. An unheaded final
  block could be a postscript or a real answer after a signed draft, and guessing wrong
  would post a draft. No runtime, permission, token, trigger or step change. The added
  text is inside the existing double-quoted `PROMPT` string and has no characters that
  expand.
- **Rollback:** revert the two prompt commits (`2aa661a`, `46f2264`). Nothing is migrated
  or persisted.
