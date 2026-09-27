# Codex → Claude handoff: post-merge audit for issue #111

Reviewed main `58edafe82de5d2a675515df32b009c405b90a0d6` on 2026-09-27.
Purpose: independently check the eight owner-approved merges and their research
dependency #100, then correct remaining misleading instructions. This is not adoption
of the research proposals, permission to run experiments, or strategy approval.

## Exact reviewed PR heads

These are the merged PR heads, not the subsequent main merge-commit identifiers.

| PR | Head | Independent disposition |
| --- | --- | --- |
| #88 | `a65cb7d669eb7ac5e5f3684dca6884e58190a9ad` | Exact host membership, case normalization and reversed-marker rejection verified; non-Binance/dynamic-host limits remain disclosed. |
| #90 | `98963d378ba8622533e5cb3cc52a52ecb0c59072` | Handoff trigger surfaces corrected; startup contradiction fixed below. |
| #91 | `14986b8a98038604929278f6ed2fe61ff05b7ff2` | Step 0 survives both workflow integrations; C1–C6 bind, R1 informs, post-pass work is only a paper-validation proposal. |
| #98 | `4c7f3a48e9b940bad1585906849a8510b911902f` | Sign-once order and step 0 coexist; unsigned-draft publication hazard corrected in prompts below. |
| #99 | `557808d48ad5a67ab68e2a5e9daa8036a383908e` | Inventory cap defaults off, preserves legacy identity, shrinks/skips buys only, restores Decimal on resume; no new blocker found. |
| #92 | `80936b85960cfd6edfdbed826d8a666735a30e06` | Report-only appendix reproduces fold/warm-up ceilings; no fully eligible dataset is established. |
| #93 | `2c45fb5322eb9bf90e629e308b9659d92855e11e` | Report-only counts reproduced; raw/effective counts and incomplete search history remain explicit proposals. |
| #101 | `4f83e2aec3f4c7be1da65de638125b32ef5a0b70` | Timing, gaps, dependence and indeterminate cases addressed; stale central trial count corrected below. |
| #100 | `2f0f15723d9fa12b1cb2d46a1b05fe79f424f34e` | Measurement dependency: appendix hashes verified; thresholds remain proposals. Author's 890-row rerun claim was not independently rerun. |

## Findings and fixes in this PR

1. **P2 — conflicting trigger guidance.** START_HERE still said triggers fire wherever
   they appear, despite #90's surface-specific handoff. Replace it with a precise
   newly-created PR Conversation-comment rule for Bob and link the detailed rules.
   Confirms [Cloud's follow-up](https://github.com/mgalic01/adaptive-market-engine/pull/90#discussion_r4116078319).
2. **P2 — emitted unsigned drafts can be published.** An unsigned `IBM Bob draft`
   with `FLAGGED`, followed by a signed final `NO ISSUES`, is retained by the current
   extractor with both verdicts. Its existing multiline-header test explicitly permits
   this. Both workflow prompts now require drafts/revisions to stay internal and only
   the completed final answer to be emitted. This is a prompt correction, not an
   enforced output-isolation guarantee; the extractor is unchanged. Confirms
   [Cloud's follow-up](https://github.com/mgalic01/adaptive-market-engine/pull/98#discussion_r4116112160).
3. **P2 — inconsistent research count.** DSR §8 still named N=2 as part 2's central
   proposal after #93 proposed N=6 central/N=9 sensitivity. Correct those references,
   retain undecided status and variance uncertainty; N=2 examples are hypothetical.
   This repairs an integration contradiction, not the statistical methodology.

## Independent verification

- Isolated Windows Python 3.12.14 copies from immutable Git objects, source-import
  location verified: **140 targeted tests passed** with socket connections disabled.
- Removing #99's Decimal resume conversion in the temporary copy makes its regression
  test fail. Twelve synthetic baseline frames produce identical full reports and
  account state before #99 and on audited main.
- Combined Bob workflow shell bodies pass `bash -n`. No paid Bob job was started.
- All four research report files match their exact merged heads; #100's two appendix
  hashes and #92's appendix hash match. Report-only #92 execution reproduces 25 folds,
  0 strict warm-up folds, 8 under the daily-file exception, and ceilings 185/177/108.
- Report-only #93 execution reproduces 152 results (8 inferred), 20 invalid retained,
  counts 1/6/7/9, and 16 R4–R3 comparisons with zero mismatches.
- These are offline synthetic/source checks. No raw archives, market downloads,
  reserved-window data, strategy replays or performance selection were used.

## Authority, limits and next steps

Issue #111 records Claude's account of the owner's merge authorization. This review
does not independently authenticate the separate conversation and does not extend it.
The owner decisions on warm-up, masks/repair, fold geometry, trial counting/registration,
DSR timestamp/staleness and acceptance use remain outstanding.

Claude or Bob must substantively review this correction PR at its latest full SHA
before Codex merges it. Existing extractor regression tests, report checker and workflow
parsing/shell checks are rerun for the correction; exact results belong in the PR
handoff. Security boundaries, permissions and publication code are unchanged. No new
credential exposure was found in this scope. Paper-only behavior and protected-profit
accounting are unchanged. Real-data equivalence and actual model adherence to the new
prompt were not measured.

PR #116's proposed index migration is not adopted here: this report follows current
main's index rule. Its writer must preserve this entry when integrating the migration.
Rollback is a documentation/prompt revert; it requires no account-state migration.
