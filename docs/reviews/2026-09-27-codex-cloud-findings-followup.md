# Codex → Claude and Bob: Cloud findings follow-up

Date: 2026-09-27. Status: audit and assigned corrections; not a blanket merge approval.

Named writer for this publication: Codex, delegated to the PR #97 documentation writer on `codex/agent-workflow-guide`, isolated worktree `work/github-local-worker`. Other agents retain ownership of their branches.

The coordinating Codex Desktop session supplied this audit and its captured-head
evidence. The documentation writer checked publication consistency and local
documentation/preflight results; it did not independently repeat the broader audit.

## Evidence boundary

The owner asked whether findings in the Cloud activity history still exist, then requested notification, delegated fixes, independent Claude/Bob review and an explicit merge decision. Main checked: `de38fdb27e3e094061c69f8ecc7530761120f9f4`. The audit read actual paginated PR comments, review bodies and source; badges, duplicate activity rows and resolved-thread flags were not treated as proof.

Windows bounded verification reproduced the hostname/marker failures below and the main-branch spawn failure. In isolated archived source, `python -m pytest tests/test_backtest_pool.py -q -p no:cacheprovider` failed on main with the candidate regression copied in, and passed all three tests at PR #103 head. The standalone pickle case alone did not expose the old package-invocation bug. No market data, large replay matrix, reserved windows or live operations were used. This is not a new whole-project equivalence proof. Fresh main report check was also recorded as zero problems by the worker-fix implementer.

## Remaining work at captured heads

| PR | Full checked head | Severity / disposition and next action |
| --- | --- | --- |
| [#88](https://github.com/mgalic01/adaptive-market-engine/pull/88) | `8abe8db45b175fc945a83c33cf1c3350861396d1` | **P2:** Uppercase hostname extraction and reversed markers still fail synthetic checks. Exact membership was corrected; non-Binance coverage is explicitly outside this proposal. |
| [#89](https://github.com/mgalic01/adaptive-market-engine/pull/89) | `f015f6a6e56c1b6450ee86a59393ba13aa424c60` | **P2:** Pending protocol proposal still has no-carry, lapse/merge, raw-patch comparison, base-change review, carried-timer and allowance-expiry contradictions. Do not adopt it as policy. |
| [#90](https://github.com/mgalic01/adaptive-market-engine/pull/90) | `93a100d8138afa5961169432f0fcc9ceb3b2e9ce` | **P2:** Description-only requests produce no issue_comment run; Bob requests require PR Conversation comments; automatic Cloud review is not guaranteed. |
| [#91](https://github.com/mgalic01/adaptive-market-engine/pull/91) | `fcf3934840252e3504047bdc20395f522d9e56ea` | **P2:** After passing research, the next proposal must be live-price paper/shadow validation; wording must not imply authorization for a live-capital pilot. |
| [#92](https://github.com/mgalic01/adaptive-market-engine/pull/92) | `b689b4c98da5087984316553b7718dddb36fd566` | **P2:** Warmup/eligibility is not verified by month coverage alone; appendix assertions, overlap explanation, tolerance claims, universe/denominator and pair examples need correction. Branch also needs conflict resolution. |
| [#93](https://github.com/mgalic01/adaptive-market-engine/pull/93) | `2b6aea1c09bad88611833a7037e1579c9679a196` | **P1/P2:** Retrospective count omits intermediate e7e8bc5db4468e46fc399b333c24c4483804f5e8 and R3 ungated results. Preserve unknown upper bound and register every attempted trial. |
| [#97](https://github.com/mgalic01/adaptive-market-engine/pull/97) | `949560d42bf16f320ffbf02c78366546b8a769b2` | **P2:** Captured overview reproduced literal trigger phrases and incomplete request/deduplication mechanics. Corrected in this publication batch by linking the canonical guide; latest pushed SHA and review/check state are in the PR Conversation handoff. |
| [#98](https://github.com/mgalic01/adaptive-market-engine/pull/98) | `46f2264dc9059611f8afd2e4678aa8a9252bc289` | **Review:** Signature-order contradiction corrected in branch. Prompt reliability remains unproven; inspect review/checks and handoff before merge. |
| [#99](https://github.com/mgalic01/adaptive-market-engine/pull/99) | `557808d48ad5a67ab68e2a5e9daa8036a383908e` | **Review:** Cap-resume regression supplied in branch; no substantive Cloud defect in captured records. Strategy adoption is separate from code being off by default. |
| [#100](https://github.com/mgalic01/adaptive-market-engine/pull/100) | `ca116751f519b1c1cbd198aa749b87662cd117d0` | **P1/P2:** Measurement appendix skips rejected months without refined repair, does not prove completeness/condition-based open-only treatment/daily checks/cached hashes, and lacks a headline reducer. Exact owner adoption of proposed values was not verified by the audit. |
| [#101](https://github.com/mgalic01/adaptive-market-engine/pull/101) | `404b56f145e4f17db39668e4e6d81e67b664ce4f` | **P2:** Revision 4 addresses missing-Sharpe handling, conditional-vs-indeterminate list, Lo formula removal and per-pair DSR removal. Latest Cloud finding: label square-root scaling as naive or omit it. Automated Claude also requires index revision update. Final-hour pair valuation synchronization still needs an explicit common timestamp convention. |
| [#102](https://github.com/mgalic01/adaptive-market-engine/pull/102) | `339e25f609dfa787cd49b00e1b05e0dad269fa45` | **Policy/P2:** Soft-drawdown lockout exists, but changing recovery is a policy decision. Resolve no-tuning rule explicitly, daily-loss recovery, equity-change-versus-trading evidence, and USDT-versus-live-EUR scope. Owner preference for C was relayed as preference pending discussion, not a waiver. |
| [#103](https://github.com/mgalic01/adaptive-market-engine/pull/103) | `4dc85c81fbb06d57ef10800b91ae244becd881a9` | **Runtime:** Windows spawn failure reproduced on main. Three synthetic regressions pass on proposed fix. Current-head review/checks plus indexed handoff still need final merge assessment. |

## Merged corrections and two post-merge defects

The 18 historical corrections from PRs #6, #9, #12, #14, #16 and #18 remain in inspected main source. Five are draft-specification corrections, not implemented strategies. PR #95 licensing corrections are present. No additional substantive Cloud defect was found in the captured #83–87/#96 records.

PR #94 merged before two later P2 findings were posted. Both remain at the main SHA above and are assigned to a separate Codex worker-fix subagent on `codex/worker-review-provenance`:

- [Review identity omits the captured base SHA](https://github.com/mgalic01/adaptive-market-engine/pull/94#discussion_r4115018328). Publish full base and head, and explain that the recommendation applies to that pair. Existing during-run stale checks remain; no mechanical merger is added.
- [Webhook setup omits the required endpoint path](https://github.com/mgalic01/adaptive-market-engine/pull/94#discussion_r4115018334). Document `/github` after the tunnel origin. The existing deployed webhook already uses this path; this is a reproducible future-setup documentation failure.

Most earlier #94 findings were fixed or removed with the automatic-merge feature. Inspected retries already use a deliberate new Conversation comment; duplicate delivery is not automatic retry. Existing path screening does not claim semantic detection of disguised data or full same-user OS isolation.

## Specific evidence for pending corrections

- #88: [uppercase hostname](https://github.com/mgalic01/adaptive-market-engine/pull/88#discussion_r4115058760), [reversed markers](https://github.com/mgalic01/adaptive-market-engine/pull/88#discussion_r4115058764).
- #93: [missing intermediate trial](https://github.com/mgalic01/adaptive-market-engine/pull/93#discussion_r4115079307), [missing R3 ungated results](https://github.com/mgalic01/adaptive-market-engine/pull/93#discussion_r4115079311).
- #97: [literal trigger strings](https://github.com/mgalic01/adaptive-market-engine/pull/97#discussion_r4115052995), [local reviewer request-deduplication finding](https://github.com/mgalic01/adaptive-market-engine/pull/97#issuecomment-5855782975).
- #101: [revision-4 handoff](https://github.com/mgalic01/adaptive-market-engine/pull/101#issuecomment-5856631216), [naive annualisation finding](https://github.com/mgalic01/adaptive-market-engine/pull/101#discussion_r4115684670), [index required fix](https://github.com/mgalic01/adaptive-market-engine/pull/101#issuecomment-5856669770). Older four revision-3 objections must not be repeated as unresolved after the verified revision-4 diff.
- #102: [owner preference and questions](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5856617516); preference is not recorded as an adopted risk-policy change.

## Owners, review and acceptance

1. Codex corrects its own #97 and the two #94 defects in focused branches, tests them, and asks Claude or Bob for substantive feedback naming the latest full SHA. Subagents and Cloud do not satisfy that external-review requirement.
2. Claude retains the named-writer role for #88–93 and #98–103. This handoff requests correction batches for confirmed defects, with current-head evidence and explicit replies to disagreements. Codex does not silently take over those branches.
3. Codex independently assesses #103 and #98 for routine integration. Any missing required handoff, outstanding finding, failed check or stale review blocks the merge. A green workflow alone is not acceptance.
4. Bob reviews the proposed correction batch and identifies omissions; quick review is reading, not test execution. No large Bob task or data run is authorized by this handoff.
5. Research/policy proposals remain unadopted until their agreement and owner-decision gates are met. No risk relaxation, strategy implementation, specification freeze or reserved-window access follows from this audit.

No known new secret-exposure finding in this publication. Protected-profit accounting and paper-only scope remain unchanged. Revert of this documentation restores only wording; code/deployment fixes are separately reviewed. After each merge, publish the merge SHA and remaining actions on an open follow-up PR, never on the now-closed PR.

## 2026-09-27 integration addendum

The table above remains a historical assessment of its captured heads. Subsequently,
[PR #104](https://github.com/mgalic01/adaptive-market-engine/pull/104) fixed the two
post-merge #94 defects and merged as
`238e2c71c5ee812ffb46d6169ce54eae565571ff`, following
[Bob's substantive exact-head review](https://github.com/mgalic01/adaptive-market-engine/pull/104#issuecomment-5856734683)
and the [coordinating Codex session's explicit merge decision](https://github.com/mgalic01/adaptive-market-engine/pull/104#issuecomment-5856751061).
PR #97 integrates that main commit without changing its worker implementation;
both the workflow/audit and worker-provenance index entries are retained.
This is source integration only: the running immutable worker release is unchanged,
with no deployment or restart performed by this publication. See the
[post-merge handoff](https://github.com/mgalic01/adaptive-market-engine/pull/97#issuecomment-5856751495).

After that merge, the [automated Claude review](https://github.com/mgalic01/adaptive-market-engine/pull/104#issuecomment-5856753484)
requested a final base-SHA recheck at the GitHub comment publication boundary.
The coordinating session assigned this bounded follow-up to the worker writer on
`codex/worker-publication-base-check`; it remains pending, outside PR #97's edits.
The existing non-atomic publication race remains acknowledged; a final base check
can narrow the race, not make the read and publication atomic. The earlier merge
decision does not waive this later finding.

The coordinating session explicitly notified Claude on #88–93, #98 and #100–103.
The remaining indexed-handoff requests are on
[#98](https://github.com/mgalic01/adaptive-market-engine/pull/98#issuecomment-5856725630)
and [#103](https://github.com/mgalic01/adaptive-market-engine/pull/103#issuecomment-5856725792).
These notifications do not establish acknowledgment, completed corrections or
adoption of any policy proposal.

[Bob reviewed the audit](https://github.com/mgalic01/adaptive-market-engine/pull/97#issuecomment-5856740006)
with `NO ISSUES` at `ce8dfb13732ebf54caf0e5a1bc6da1bc3259da42`.
That result is historical after the main integration. New-head checks and substantive
Claude/Bob review are required before the coordinating session decides whether to
merge PR #97; no old verdict is carried forward.
