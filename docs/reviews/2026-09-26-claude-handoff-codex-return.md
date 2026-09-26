# Claude → Codex: welcome back, what changed, and what to do first

- **Date:** 2026-09-26
- **From:** Claude (cloud session)
- **Why now:** the owner says Codex is back, with more allowance, and asked Claude to
  update Codex on everything and "tell him to get to work".
- **Earlier note:** [the catch-up for #20 to #42](2026-09-25-claude-handoff-to-codex.md).
  This note continues it from #43.

## 0. Read this first

A new file, [`docs/START_HERE.md`](../START_HERE.md) (merged in #68, owner request), is
now the first thing every agent reads at each start: seven steps in a fixed order.
`AGENTS.md` points to it. Please follow it, starting today.

**The stop-gap merge rule ends now that you are back.** Merging on Bob's NOTED with
green checks applied only "while Codex has no allowance"
([quick reference](../AGENT_HANDOFF.md#quick-reference-how-to-reach-each-agent-keep-this-current)).
From this note on, Claude does not merge on that rule. Merges go back to you, after
your review.

## 1. Merged while you were away, #43 to #68

Every merge below was made under the stop-gap rule: Bob NOTED at the head, green
`test-and-audit`, and no unaddressed required fix from the automated review. You
review them after the fact. Post findings in a **new PR**, never on the merged ones.

| PR | Merge | What | Notes for your review |
| --- | --- | --- | --- |
| #43 | `b136639` | Catch-up rows for #37–#42 in the earlier note | Documentation only. |
| #44 | `670085b` | Robust extractor for Bob's answers | Markdown-decorated headers accepted; a signature must end its line; structure-only diagnostics; the exponential-backtracking header pattern replaced by a linear one. |
| #49 | `e9fa449` | Bob: development data inventory, 2017-08 to 2024-12 | Six statements corrected at review, marked in place. |
| #50 | `dd3b275` | Bob: documentation audit | |
| #51 | `7c4d4d0` | Bob: test-suite audit | Its untested-loader finding led to #54. |
| #52 | `5c7dd48` | Bob: V0 development scorecard | Diagnostic only. **V0 fails C1** (5 of 8 runs drop more than 10%) **and C2** (negative medians). |
| #53 | `40f6fbd` | Lessons from batch 1 in `docs/BOB_PRACTICE.md` | |
| #54 | `6455949` | Tests for the loaders and small input gateways | `SUMMARY_FIELDS` pinned at 49 keys. |
| #55 | `1410892` | **Owner decision:** hard stop stays 12%, C1 stays 10% | [record](2026-09-26-claude-owner-decision-drawdown.md) |
| #56 | `8df478f` | Batch 1 marked done; lesson from #54 | |
| #59 | `853d780` | Bob: parser anomaly classes | Headline counts corrected at review; 66,179 unaligned-open rows; 66,199 total other-class rows including 20 earlier anomalies (Codex count correction, 2026-09-26). |
| #60 | `7ae6d0f` | Bob: hour-level defect calendar | **Gap found at review:** hours missing from both archives got no status, so the real outages were invisible. #62 re-ran it properly. |
| #61 | `b884e02` | Lessons from batch 2 | |
| #62 | `8fe6484` | Bob batch 3 task files | Revised five times before merge: Bob's five ambiguities, then three automated-review findings. |
| #66 | `169e84e` | Bob: outage calendar and field-level mismatches | Claude's independent script matched all 14 events, 58 hours and 6,646 mismatches. |
| #65 | `b2684b9` | Bob: refined parser rule | Claude's independent script matched: narrow rule 82, refined rule 99 usable pair-months. |
| #67 | `071dad2` | CI: `scripts/check_reports.py` | Owner request: script the repeatable review checks. Covers index links, appendix hashes, `text` fences and, on `bob/task-` PRs, scope. It found #66's stray index rows by itself. |
| #68 | `a5bb058` | `docs/START_HERE.md` | Owner request. |

**Please check in particular:**
- `quality.yml` now uses `fetch-depth: 2` and diffs the PR merge commit against
  `HEAD^1` for the Bob-branch scope step (#67). Is that sound for every PR shape?
- The stop-gap merges of Bob's own reports (#49–#52, #59, #60, #65, #66). Their
  numbers were rechecked independently by Claude, but the merge decisions were Bob's
  NOTED plus Claude's.
- Claude's mistakes, for the record:
  - On 2026-09-26 at 07:02 UTC Claude force-pushed an unrelated commit onto #33's
    branch, then restored `6017079` about a minute later. No content was lost.
  - One comment on #59 landed at the moment of its merge.

## 2. Open, and what each needs from you

- **#33, the data-reuse method** (walk-forward, a block bootstrap, a trial register,
  deflated Sharpe). It needs all three agents' agreement.
  - Bob agrees, with four conditions written into the proposal.
  - Claude agrees.
  - **Your review is the last gate.** The branch was brought up to date with `main`
    at `122b3aa`.
- **Branch `claude/data-audit`** (PR coming). `backtest/audit.py` and `audit_run.py`
  hold the checks Bob and Claude kept rewriting: expected hours, outage events,
  differing fields and both repair rules, tested on synthetic data.
  - On real data it already reproduces #65 exactly (82 / 99).
  - The #66 reproduction is running now.

## 3. Decisions waiting for the owner (your advice welcome)

1. **The refined parser rule:** adopt it (99 usable pair-months) or keep the strict
   parser. Also, whether DOGEUSDT 2020-02's one-tick open disagreement between the 1m
   and 1h archives should block that pair-month (99 vs 100).
2. **Outages and folds:** whether walk-forward folds start and end around the seven
   all-pairs outages of 3 hours or more (#66). This feeds #33's condition 1.
3. **"No GPL or AGPL code":** in `START_HERE.md` step 1, but no owner decision on
   `main` records it yet. Claude has asked the owner; all 41 current dependencies are
   permissive or MPL-2.0.

## 4. What Claude asks you to do, in order

1. Follow [`START_HERE.md`](../START_HERE.md) steps 1–4.
2. Review #20–#42 (the earlier note) and #43–#68 (above). Post one Codex → Claude
   handoff **in a new PR**, and remove the "first action" paragraph from `AGENTS.md`
   in that PR, as it asks.
3. Review #33 and record your agreement, or the changes you need.
4. Review the data-audit PR when it opens, and merge the ready PRs from now on.
5. A possible batch-4 task for Bob, for your view: 79% of all mismatched hours differ
   **only on the open** (5,277 of 6,646). A hypothesis to test is that the 1h open
   comes from a different source than the first minute's open. If it holds, most of
   2017–2020 is usable for a price-only strategy.

Nothing here changes code or data. Paper-only, and the reserved window is untouched.
No compatibility risks are known.


## Codex → Claude handoff — completion checkpoint, 2026-09-26

This checkpoint supersedes the pending-action statuses above while preserving Claude's original requests as history. The retrospective audit is completed and merged in [PR #73](https://github.com/mgalic01/adaptive-market-engine/pull/73), merge `e43d097b4681204ece18a92b7b5ddb4173914379`; see the [indexed audit](2026-09-26-codex-retrospective-review.md). It covers exact merged commits, independent evidence, findings and limits. The obsolete first-action paragraph was removed there and remains removed after this integration.

The report-publication/Windows fixes merged in [#71](https://github.com/mgalic01/adaptive-market-engine/pull/71). Replay precision [#72](https://github.com/mgalic01/adaptive-market-engine/pull/72) and the checksum-failure blocker in data-audit [#70](https://github.com/mgalic01/adaptive-market-engine/pull/70) are under Codex's active fix/review. Codex answered [#33](https://github.com/mgalic01/adaptive-market-engine/pull/33) point by point with AGREE WITH CHANGES; Bob acknowledged the revised response at `ad66e12a019939f865d3b085b28f91ba3085ad2d`. Claude's acknowledgment of the substantive revisions remains pending. The proposal is being consolidated and is not ready to merge under its three-agent agreement gate.

The counts above now distinguish 66,179 unaligned-open rows from 66,199 total other-class rows. The 82/99 counts concern repair-rule eligibility, not satisfaction of the full replay mask; the 14-event/58-hour outage result covers parsed pair-months, with unparsed coverage unknown. No strategy adoption, tolerance policy, fold selection, specification freeze or new experiment is approved by this documentation update. In particular, a different-source hypothesis for hourly opens would not itself establish economic or replay validity.

Verification: the historical merge ledger was checked against GitHub; documentation integration preserves current main's corrected report annotations and index. The report checker validates all five embedded appendix hashes with zero problems. This checks the committed evidence, not the original external datasets. No market data was downloaded and no reserved window was accessed. This documentation-only change has no known runtime compatibility risk or new security finding. Claude is unavailable until 18:10 local per the owner; Codex owns the routine fixes, and Claude owns acknowledgment of the revised #33 and role-proposal #74 when available. The three owner policy questions above remain decisions, not inferred approvals.
