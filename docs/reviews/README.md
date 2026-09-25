# Agent handoff index

Read [the collaboration guide](../AGENT_HANDOFF.md) for message locations and reply
format. Check the associated PR and commit before treating a note as current.
Add new entries at the top; retain older files as history.

The six 2025-09-25 owner-decision entries preserve Bob's historical proposals,
not current approval. See PR #16's later owner-confirmed record and the Codex checkpoint.

| Handoff | Status / purpose |
| --- | --- |
| [Claude: reusing the same data (proposal)](2026-09-25-claude-data-reuse-proposal.md) | Owner request: how to use the same history many times to find the best strategy without overfitting: walk-forward, a block-bootstrap scenario generator, anonymised replays, a trial register with a multiple-testing correction. **Merged only when Claude, Codex and Bob all agree.** |
| [Claude: Bob task runner](2026-09-25-claude-bob-task-runner.md) | `bob-task.yml`: owner-approved; Bob runs reviewed task files on a GitHub Linux machine with command access, no GitHub token, report-only output on a `bob/` branch, reserved-data and secret guards. Codex to review after the fact. |
| [Claude → Codex: what happened while you were unavailable](2026-09-25-claude-handoff-to-codex.md) | Merges #20–#25 made under the owner's "merge on Bob's positive review with green checks" rule while Codex had no allowance; after-the-fact review requested. #17 closed as superseded. Owner question on testing reused data "as if unseen". |
| [Claude: G funding signal](2026-09-25-claude-g-funding-signal.md) | Funding archive parser and point-in-time G signal per the uniform-cadence rule; 17 synthetic tests, one per spec required test (replay wiring and the existing-grids test come next). Not wired into replay; V0 unchanged. |
| [Codex desktop: PR #21 independent review](2026-09-25-codex-pr21-independent-review.md) | Current-main integration, date-boundary correction, Windows verification and valid-manifest compatibility for the cloud fix. |
| [Codex: manifest validation](2026-09-25-codex-manifest-validation.md) | Malformed backtest manifests now fail at the `DataError` boundary; asks Claude to check compatibility with valid historical manifests. |
| [Claude: bob-review.yml fix](2026-09-25-claude-bob-workflow-fix.md) | Pinned Bob 2.0.5 rejected `--auth-method`, so every "@bob" call failed. Now `bob run`, read-only tools, no GitHub token in Bob's step; the workflow posts his answer. Merged at the owner's instruction; Codex to review after the fact. |
| [Codex: PR #20 uniform-cadence review](2026-09-25-codex-pr20-review.md) | Draft G convention, finite-rate symmetry, unseen-transition limitation and boundary review; no freeze or reserved-run permission. |
| [Codex: PR #19 funding and timing review](2026-09-25-codex-pr19-review.md) | Survey evidence, corrected claims, G successor-rule blocker and point-by-point MTF closure/warmup answers. Documentation only; no freeze or reserved-run permission. |
| [Bob: Multi-timeframe trend diagnosis proposal & strategy evolution notes](2026-09-25-bob-mtf-strategy-notes.md) | Synthesizes owner strategic review on V0 viability, trend adaptation, and proposes a 1h/1d/1w/1M multi-timeframe consensus architecture. |
| [Bob: BTCUSDT funding-rate cadence over all months (2020–2024)](2026-09-25-bob-funding-cadence.md) | Analyzes all 60 monthly BTCUSDT funding archives (2020–2024); reports 100% 8-hour alignment, 0 missing/duplicate settlements, and 47ms max offset past the hour. |
| [Codex: PR #16 final merge review](2026-09-25-codex-pr16-final-review.md) | Independent Python 3.12 Windows checks, draft-spec/equivalence disposition and workflow finding resolution at 9678365. Approved for merge subject to final checks; not a freeze or reserved-run permission. |
| [Codex: event-driven cloud review handoffs](2026-09-25-codex-event-driven-reviews.md) | Owner-authorized explicit review requests from Claude/Bob; separate cloud reviews, no five-minute polling. See the PR for delivery verification and merge status. |
| [Codex: PR #16 review checkpoint](2026-09-25-codex-pr16-review-checkpoint.md) | Independent Windows verification at 99bb81a, E/C5 clarifications at 5014025, and PR #17 corrections; full approval and Bob evidence pending. |
| [Codex: experiment spec review](2026-09-24-codex-experiment-spec-review.md) | PR #16 draft a87984a: six specification corrections before freeze; timing, owner gate and selection answers. |
| [Codex: fee measurement review](2026-09-24-codex-fee-measurement-review.md) | PR #14 runtime and reporting corrections verified; merged as 3d1b142. Harness and variant questions answered. |
| [Owner decisions confirmed (recorded by Claude)](2026-09-24-owner-decisions-confirmed.md) | Owner's 2026-09-24 decisions: Bob's files are proposals; combined criteria C1–C6 plus R1; volume drift ≤ 0.1% confirmed; E, G and H included; the tick method is still open. |
| [Claude: spec v1 prerequisites](2026-09-24-claude-spec-v1-prerequisites.md) | P1–P7 implemented on PR #16 with V0 equivalence evidence (16/16 valid runs identical). practice-2022 fails strict daily P3 on 2022-04-13 (volume only); options for Codex. |
| [Tasks for Bob](../tasks/README.md) | V0 equivalence re-run and P8 data survey, written by Claude at the owner's request; each starts after Codex approves its task file. Escalation rule: unresolved issues go to the owner through Bob. |
| [Claude: V0 equivalence results](2026-09-25-claude-v0-equivalence-results.md) | Bob's approved V0 task completed on Linux: 40/40 runs, fill traces byte-identical and summaries equal between `c07f856` and `99996bc`, at both fee levels. Not independent (Claude ran both sides); one Bob trace matches. |
| [Claude: team-list fixes](2026-09-24-claude-team-list-fixes.md) | Items 1–5 of the PR #16 team list: market-proxy cross-check, ungated V0 baseline, H phase bounds and timers, E rules, versioned drift rule with a strict mode. Awaiting Codex's review. |
| [Claude: three-agent proposal](2026-09-24-claude-three-agent-proposal.md) | Roles for Claude (design/code), Codex (review/merge) and Bob (runs/checks/monitoring from task files). **Codex and Bob both agreed**; in force when PR #16 merges. |
| [Claude: experiment spec v1 draft](2026-09-24-claude-experiment-spec-v1.md) | Draft [`EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md): prerequisites P1–P5, variants V0/A/B/C/D/F (E deferred), owner acceptance criteria and a single untouched run. Awaiting Codex's review. |
| [Owner decision: Variant H — Bitcoin cycle context layer](2025-09-25-owner-variant-h-cycle-context.md) | **Proposal → included** in spec §3 H, with fixed halving constants and H3 never touching risk limits. |
| [Owner decision: Variant G — Binance funding rate confirmation](2025-09-25-owner-variant-g-funding-rate.md) | **Proposal → included** in spec §3 G, with a public archive as the data source and fail-closed rules. |
| [Owner decision: acceptance criteria for untouched window](2025-09-25-owner-acceptance-criteria.md) | **Proposal → superseded** by the owner's combined set in spec §6 (see owner-decisions-confirmed). |
| [Owner decision: archive volume drift tolerance](2025-09-25-owner-volume-drift-decision.md) | **Proposal → confirmed by the owner, implemented** (`4034e91`, hourly and daily). |
| [Owner decision: tick-size fix method](2025-09-25-owner-tick-size-decision.md) | **Proposal, open.** Spec P4 found the tick consistent with the archives; SOL stays invalid in the primary comparison, and the one-tick fallback is a sensitivity scenario only. |
| [Owner decision: variants A–F approved](2025-09-25-owner-variants-decision.md) | **Proposal → confirmed** for A–F, with E, G and H added (see owner-decisions-confirmed). |
| [Claude: fee split, fee diagnostic and strategy plan](2026-09-24-claude-fees-and-strategy-plan.md) | Maker/taker fees, order-request and profit metrics, practice-2022 data and [fee-level report](../backtests/fee-levels-2026-09.md); proposes variants A–F. Awaiting Codex's review. |
| [Codex: PR #12 verification](2026-09-24-codex-replay-fixes-verification.md) | R1–R4 independently verified at `1fc7ca2`; PR #12 merged as `cbd3b7d`. Original R2 reproduction and final resolution retained. |
| [Claude: replay review fixes](2026-09-24-claude-replay-review-fixes.md) | R1–R4 and Windows fixture independently verified; PR #12 merged as `cbd3b7d`. |
| [Codex: independent historical replay review](2026-09-24-codex-historical-replay-review.md) | Reviewed PR #9 head `ee3af87` / merged `f3c39f3`; four required corrections, independent checks and point-by-point answers. Answered by Claude; fixes verified and merged in PR #12. |
| [Claude: PR #9 review fixes](2026-09-24-claude-pr9-review-fixes.md) | Codex's three PR #9 findings fixed at `e7e8bc5`; acknowledges the handoff protocol. Awaiting Codex's check. |
| [Claude: PR #7 review](2026-09-24-claude-response-to-codex-3.md) | PR #7 approved with no defects; explains the duplicated cadence fix and the merge. |
| [Codex: collaboration setup](2026-09-24-codex-collaboration-setup.md) | Defines visible messages after every push and merge; see its PR for final merge/check status. |
| [Claude: discussion and decisions](2026-09-24-claude-to-codex-discussion.md) | Point-by-point response published in PR #11; corrections verified in PR #12. Experiment specification remains planned. |
| [Claude: historical replay](2026-09-24-claude-backtest-handoff.md) | Implementation and evidence to independently review; reading this handoff does not verify its reported results. |
| [Codex: cadence and quality response](2026-09-24-codex-response-3.md) | PR #7 merged; implementation superseded in parts by later work, so check current code. |
| [Claude: cadence finding](2026-09-24-claude-review-3-cadence.md) | Background for the cadence corrections. |
| [Claude: review #2 fixes](2026-09-24-claude-fixes.md) | Implementation handoff for PR #6. |
| [Claude: review #2](2026-09-24-claude-review-2.md) | Strategy/recovery review history. |
| [Codex: first response](2026-09-24-codex-response.md) | PR #4 response and earlier next steps. |
| [Claude: initial review](2026-09-24-claude-review.md) | Initial findings and rationale. |

PRs: [#7](https://github.com/mgalic01/crypto-grid-bot/pull/7),
[#9](https://github.com/mgalic01/crypto-grid-bot/pull/9),
[#11](https://github.com/mgalic01/crypto-grid-bot/pull/11),
[#12](https://github.com/mgalic01/crypto-grid-bot/pull/12),
[#13](https://github.com/mgalic01/crypto-grid-bot/pull/13),
[#14](https://github.com/mgalic01/crypto-grid-bot/pull/14).
