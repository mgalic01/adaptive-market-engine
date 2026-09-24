# Agent handoff index

Read [the collaboration guide](../AGENT_HANDOFF.md) for message locations and reply
format. Check the associated PR and commit before treating a note as current.
Add new entries at the top; retain older files as history.

| Handoff | Status / purpose |
| --- | --- |
| [Claude: spec v1 prerequisites](2026-09-24-claude-spec-v1-prerequisites.md) | P1–P7 implemented on PR #16 with V0 equivalence evidence (16/16 valid runs identical). practice-2022 fails strict daily P3 on 2022-04-13 (volume only); options for Codex. |
| [Claude: three-agent proposal](2026-09-24-claude-three-agent-proposal.md) | Roles for Claude (design/code), Codex (review/merge) and Bob (runs/checks/monitoring from task files). **Not in force** until Codex and Bob both agree on PR #16 and it merges. |
| [Claude: experiment spec v1 draft](2026-09-24-claude-experiment-spec-v1.md) | Draft [`EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md): prerequisites P1–P5, variants V0/A/B/C/D/F (E deferred), owner acceptance criteria and a single untouched run. Awaiting Codex's review. |
| [Owner decision: Variant H — Bitcoin cycle context layer](2025-09-25-owner-variant-h-cycle-context.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). Cycle awareness via halving phase tracker (H1), overextension guard (H2, >60% above SMA200 in peak window), and deep discount signal (H3, >50% below ATH in bear window). Price-based, no hard-coded calendar dates. |
| [Owner decision: Variant G — Binance funding rate confirmation](2025-09-25-owner-variant-g-funding-rate.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). No new grid when BTC perpetual funding rate persistently >+0.05% across last 3 periods (24h). Free, independent of spot price/volume. |
| [Owner decision: acceptance criteria for untouched window](2025-09-25-owner-acceptance-criteria.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). Six criteria agreed and locked: integrity, beats cash (median >0%), risk, gate earns its place (≥60%), economics (€100 budget), minimum activity (≥10% bars invested). All must pass. |
| [Owner decision: archive volume drift tolerance](2025-09-25-owner-volume-drift-decision.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). Tolerate Binance volume drift ≤0.1% when OHLC matches exactly; count separately as `hours_volume_drift`. All other chronology gates remain fatal. |
| [Owner decision: tick-size fix method](2025-09-25-owner-tick-size-decision.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). Historical filters per month (Option A) as primary; single-tick rounding (Option B) as documented fallback where historical data unavailable. Unlocks practice-2022 SOL runs. |
| [Owner decision: variants A–F approved](2025-09-25-owner-variants-decision.md) | **PROPOSAL, not yet agreed** (committed directly to `main` without PR review; owner asked on 2026-09-24 that it be treated as a proposal and confirmed on PR #16). Owner approves all six variants for pre-registration. A, B, C, D, E approved; F approved at lowest priority. Pre-registration rules accepted. Harness decisions and acceptance criteria still open. |
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
