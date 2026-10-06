# Spec v1 freeze: the evidence for every status claim

Index: **Claude: spec v1 freeze (#171), 2026-10-06.** The evidence behind the frozen spec's status block. Codex's final verdicts on #163, #168 and #170, and Codex Desktop's review of amendment 1 at #171's head, owed since #124 (#134). The owner's confirmations of C1–C6 and C2. The owner's decisions 12–22, which leave no reading open. Codex found the gaps that decisions 14–22 closed.

- **Date and author:** 2026-10-06, written by Claude (session `b9db01ca`).
- **PR:** #171, which freezes `docs/EXPERIMENT_SPEC_V1.md` as the owner decided on 2026-10-05 (decision 12 in the [test-plan record](2026-10-05-claude-owner-decisions-test-plan.md), "Later decisions").
- **Scope:** documents only. No rule, criterion, threshold, dataset or code changes.

## The freeze condition

The spec's header made the freeze wait until Codex had reviewed it and the owner had confirmed the acceptance criteria in §6.

### Codex's reviews, by amendment

| Spec text | PR | Codex's final verdict |
| --- | --- | --- |
| Amendment 1 (drawdown recovery) | #124, merged as `c8cddc2` while Codex was unavailable; owed in #134 | [Codex Desktop: no issues at #171's head `c7a45f4`](https://github.com/mgalic01/adaptive-market-engine/issues/134#issuecomment-6012217278), 2026-10-06. Scope: the section, `runner.py`, `models.py` and both drawdown-recovery test files (90 passed) |
| Amendments 2 and 3 (D15, D16) and the owner's D1–D16 | #163 | [no major issues at the final head `64e605c`](https://github.com/mgalic01/adaptive-market-engine/pull/163#issuecomment-5988156033) |
| Amendment 4 (the test plan) | #168 | [no major issues at the final head `7a5b59a`](https://github.com/mgalic01/adaptive-market-engine/pull/168#issuecomment-5998184708) |
| E's eligibility record, the traded proxy's split | #170 | [no major issues at the final head `aca084d`](https://github.com/mgalic01/adaptive-market-engine/pull/170#issuecomment-6002592186) |
| The freeze itself | #171 | in the PR's thread; it merges only when Codex, Bob and the automated review are clean at its final head |

### The owner's criteria
- **C1–C6:** confirmed on 2026-09-24. See spec §6's heading and [the record](2026-09-24-owner-decisions-confirmed.md).
- **C2:** amended on 2026-10-05 to compound annualised returns (test-plan record, decision 6).

## No readings left open

Every passage that called a rule "Claude's reading, open to the owner" now cites the owner's decision. The questions and answers are in the test-plan record, word for word.

| Reading | Spec | Decision |
| --- | --- | --- |
| A traded market proxy's defects | §5, "Failures that reach every pair-window" | 13 |
| The post-mask expected set | §5 | 15 |
| XRP's statistic | §5, rule 8 | 16 |
| The tie band and the −100% rule | §6, "Annualised returns", and selection step 2 | 17 |
| The stage-1 identity check | §6, "Two stages" | 18 |
| Amendment 1's manual-resume rule | §3, amendment 1 | 19 |
| The unique-bars condition of hour masking | §5, rule 1 | 20 |
| V2's gate-loosening report | §3, V2 | 21 |
| An untraded proxy's repaired hours | §5, rule 1 | 22 |

Only whether stage 2 also runs the reported-only sensitivities is left for later, and those decide nothing.

## How the gaps were found

Codex's review of #171 at `2b69c5c` found two gaps.
- The freeze question had said "Codex has reviewed every amendment", but amendment 1 never had its Codex review.
- Four outcome-affecting readings were still open.

Claude told the owner, who chose to get amendment 1's review first (decision 14) and decided every open reading (decisions 15–22). Claude's search of the spec found three readings beyond Codex's four, and those went to the owner too.
