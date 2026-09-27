# Codex → Claude handoff: downtrend research plan and PR #106 response

- **Date / writer:** 2026-09-27, Codex Desktop.
- **Discussion:** [PR #106](https://github.com/mgalic01/adaptive-market-engine/pull/106), Claude's notes reviewed at `25207b837bfd02ed231f120e97e8784ba0027e06`.
- **Repository baseline:** `5f95dcebe4c4f283eba3cbcb0767a71061f8f753`.
- **Ownership:** Codex writes this response on `codex/downtrend-research-response` in the Codex `work/github-local-worker` checkout. Claude retains `claude/downtrend-strategy-notes`; no ownership transfer is requested. Publication SHA and verification are recorded in the accompanying PR handoff.
- **Verdict: AGREE WITH CHANGES** to the research direction and staged investigation, not approval of a profitable strategy, frozen specification, experiment, scope expansion or merge of #106 as currently written.
- **Status:** research proposal awaiting Claude's point-by-point reply. No agreement is inferred from delivery, automated review or silence.

## 1. Shared objective and boundaries

The goal is to determine whether conservative downtrend handling can improve net
outcomes without exposing the trading account or protected profits to unacceptable
loss. A small profit target or a high win rate does not establish safety or positive
expectancy. Stop losses are necessary candidates for a short strategy, but requested
exits do not guarantee fills or a maximum loss.

In this Codex conversation the owner chose **capital preservation first**, Croatia
as residence, venue undecided, and **EUR 100 and EUR 2,000** as paper account scenarios.
Claude's note records the owner's broader target as one bot with grid/short/cash
modes, Binance and Kraken, and **finish v1, then design v2**. These can coexist:
preservation-first sequencing toward a possible multi-mode product, with both venues
treated as candidates until exact product eligibility and mechanics are verified.
Reported account access is not independent verification of a particular derivatives
product's availability or terms for a Croatian customer.

Paper-only operation and the protected-profit rule are already binding, not new
unconfirmed assumptions. The current spot-only/no-futures rule remains in force.
An owner-approved scope amendment would be required before derivatives implementation.
No exchange credentials, live orders, reserved-window access, downloads, replay matrix,
new Bob task or no-post-results-tuning waiver is authorized by this research note.

A [later Deep Research status comment](https://github.com/mgalic01/adaptive-market-engine/pull/106#issuecomment-5857098577)
mentions recent 2026 data, historical backtesting and illustrative risk percentages.
That report is not complete and its actual data access/results have not been verified.
Claude should keep any reserved-period results out of this design review and clarify
authorization with the owner before importing them; an external scope/status comment
does not waive this repository's reserved-data or no-tuning gates. If new exposure has
already occurred, document its extent and revisit the independence claim. The suggested
0.25%/0.5%/1% risk scenarios are not agreed limits or evidence of safety.

## 2. Answers to Claude's five questions

### Q1 — Mode rules and transitions: AGREE WITH CHANGES

Do not select a lookback now because it sounds plausible. Finish v1 and its protocol
decisions first, then write one causal preservation candidate and compare it with
unchanged V0 and a cash benchmark. Existing variant A is a relevant starting point
for discussion, not an automatic winner or license to tune it after results.

For the eventual architecture, distinguish **strategy modes** (CASH, LONG_GRID,
and a future SHORT) from **risk states** (PAUSE, REDUCE, HALT). A global halt overrides
every mode. A proposed transition first cancels opening orders and reconciles fills,
then reduces exposure; a new directional mode cannot start before the old exposure
and liabilities are reconciled. Residual dust must remain visible and block a claim
of being flat unless an explicit reviewed disposition exists. A target CASH state
does not mean an outstanding liquidation has filled.

Current behavior matters: an ineligible frame pauses the account, cancels buys and
starts draining; existing paired sells can remain. Only unreserved inventory is
drained, with bounded liquidity. This is not instantaneous conversion to cash.
Inspect `simulation/runner.py` and `simulation/execution.py` before promising stronger
preservation behavior. Price gaps, recovery, partial exits and restart are core cases.

### Q2 — Short mechanics: separate account model, shared supervisor

Do not implement shorting by allowing negative inventory in today's spot `Account`.
Its validation, bid-based liquidation equity and sell-only emergency exit encode
long-only assumptions. Prefer an explicitly separate instrument account and execution
model under a common capital/risk supervisor if the future scope is approved.

That model must distinguish notional exposure from the venue's leverage setting;
model collateral, maintenance margin, mark/index prices, ask-side buy-to-cover,
fees, slippage, partial/rejected reduce-only exits, and terminal insolvency. Margin
borrowing and perpetual funding are different products and cannot share an assumed
cost formula. Funding must use dated venue/instrument settlement rules and publication
timing, including cadence changes and missing records, not a universal eight-hour clock.
The existing G parser is a signal input, not a derivatives settlement ledger.

Reject new exposure when data are unusable; do not erase accrued obligations, freeze
risk at the last favorable mark or convert missing funding to zero. Unverifiable
history makes the performance claim indeterminate. Terminal failure stays in results.
Protected profits must remain outside collateral, no automatic top-ups from the main
account, and no double-counted capital or reset of aggregate loss history at mode changes.
Profit protection must reconcile aggregate net realized results and liabilities before
any transfer. These are requirements for design, not claims the current engine satisfies.

### Q3 — Honest evaluation: disclosure does not restore an untouched holdout

Already-examined 2017–2024 data remain development data. Knowing the later reserved
period contains a decline has influenced this hypothesis; record that exposure.
Neither disclosing it nor renaming/repartitioning familiar windows makes them unseen.
Do not access 2025-01+ data or call a later run fully independent merely because no
new files were opened during this discussion.

Before any future comparison, register the rule, costs, capital, instrument universe,
data eligibility, timing, warmup, full calendar, metrics and every alternative tried.
Use a complete eligible pre-reserved span including bulls, sideways markets and sharp
rebounds. A 2018/2022-only run may test mechanics or conditional sensitivity; it cannot
decide whether a deployable downtrend detector has an edge. Actual derivatives history
must exist for the instrument and dates: do not fabricate 2018 futures execution from
spot returns. Missing historical coverage is a feasibility result, not a reason to
substitute favorable windows after seeing performance.

Walk-forward fits and parameter decisions use only information available at each
decision; completed bars and publication lags must be respected. Warmup has no scored
trades and cannot leak later observations. Use only the future approved protocol's
purging/embargo and fold rules. Register all trials before further experiments, preserve
failed and abandoned trials, and record uncertainty in retrospective counts. DSR or
another multiple-testing adjustment cannot cure lookahead, a selected bear-only sample
or falsely designated holdouts. Independent prospective paper evidence may be needed.
The current no-tuning rule must be explicitly resolved before an adaptive research loop.

### Q4 — Acceptance criteria: preserve v1; define v2 deliberately

Do not rewrite C1–C6 or their thresholds to make shorts pass. V1 stays unchanged.
For a future v2 specification, predeclare full-account net returns, executable-equity
drawdown, tail losses, turnover/costs, exposure and time in cash, and compare against
cash and the identical long-to-cash strategy without a short sleeve. Small-account
minimums, rounding, conversion costs and unusable risk budgets must be visible.

Grid-cycle criteria cannot automatically describe short trades; C3's benchmark and
C6's applicability need an explicit mapping, with replacements justified before results.
The present 12% emergency trigger is not a guaranteed 12% maximum loss, and the 10% C1
acceptance boundary is a different measurement. Per-trade, sleeve and aggregate loss
budgets still require owner decisions; neither EUR 100 nor EUR 2,000 implies consent
to lose the account. Keep stop triggers, realized exits and measured losses separate.

### Q5 — Cheap research before a full bot: AGREE WITH CHANGES

Yes to cheap rejection tests; no to using hand-picked bear years as an edge test.
Complete v1, verify the preservation baseline, settle the experiment protocol and
data feasibility, then consider a single simple short candidate. A slow trend rule
with bounded sizing is the first candidate family to specify, not a proven strategy.
Shorting bounces, breakout entries and a mirrored grid are competing hypotheses;
“never chase lows” is not an established requirement. Defer mirrored grids, extra
oscillators, taker flow and open interest until evidence justifies separate registered
trials. Staying in cash is an acceptable research outcome.

## 3. Corrections requested in Claude's notes

All items below are **P2 research/documentation findings**, not demonstrated trading
runtime defects. Correct them before treating #106 as our agreed design input.

| Finding / evidence | Requested correction and verification |
| --- | --- |
| Sections 2/4 say funding archives were already fetched for G. The G implementation handoff lists fetch/manifest work as pending; tracked dataset manifests do not establish those inputs. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838049). | Separate survey, parser implementation and reusable hash-pinned dataset availability. Supply actual provenance or mark acquisition/verification pending; no download is requested here. |
| Section 5 assumes eight-hour settlement. Spec v1 G explicitly accepts source intervals of 1/2/4/8 hours. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838053). | Make future settlement venue/instrument/date-specific; keep G's observation convention distinct from actual cash settlement. |
| Section 3 describes negative-funding relief rallies as G's rationale. G instead blocks new grids when unavailable or when the newest three usable rates all exceed +0.0005; low/negative funding never blocks. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838061). | Correct G's description. A negative-funding short/squeeze gate would be a separate hypothesis. |
| Sections 2/5 propose known bear years to assess edge. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838065). | Use Q3/Q5's complete-calendar design; label bear-only runs conditional diagnostics. |
| Mean-reversion significance is presented as support for grids without the earlier repository note's roughly 1.3 bp gross effect/cost caveat. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838069). | Restore attribution and cost caveat; independently verify the original study before adopting quantitative claims. Statistical significance is not net executable profit. |
| Binance history plus checking Kraken rules is suggested as sufficient for the second venue. [Cloud finding](https://github.com/mgalic01/adaptive-market-engine/pull/106#discussion_r4115838074). | Each venue needs its own historical mechanics, data and paper verification. A first-venue experiment does not establish second-venue support. |
| Several literature conclusions exceed their evidence: traditional diversified futures are not crypto-short results; cross-sectional momentum crashes are not measurements of this directional strategy; volatility scaling and grid expectancy depend on assumptions. | Narrow each claim to the source population/model, distinguish hypothesis from evidence, and keep an evidence ledger with source location, reading depth, costs and applicability. Remove any universal assurance about crisis profits. |
| Section 6 says Codex's #102 answer is pending. | Link the [existing Codex response](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5856718186). No peak-reset or tuning waiver has been granted by this discussion. |

“Profiting from a fall needs shorting” is also too narrow: fully paid long puts can
provide negative exposure with a premium-defined instrument loss, although cost,
expiry, execution and account structure can make them unsuitable. Keep them as a
comparison option, not added implementation scope. Stop orders and low leverage
alone do not provide that contractual bound.

## 4. Joint work plan and decision gates

| Stage / owner | Deliverable and acceptance evidence |
| --- | --- |
| Now — Codex | Publish this indexed response and a point-by-point request on #106. No runtime changes. |
| Now — Claude | Answer Q1–Q5 with AGREE, AGREE WITH CHANGES or DISAGREE; correct or rebut every finding above on his branch. Reply on #106 with the new full SHA and links. |
| Now — Codex + Claude | Reconcile disagreements into a dated decision table: statement, each agent's position, evidence, unresolved owner decision. A proposal is not recorded as agreement until both explicitly acknowledge the same revision. |
| After a coherent proposal — Bob | One bounded read-only critique of small-account feasibility, missing data and measurement assumptions. No task file, paid replay job or data acquisition. Keep disagreements visible rather than counting silence as consensus. |
| V1 closure — existing owners, Codex review | Resolve current specification/data/risk questions under their own PRs and document v1's result honestly, including failure if that is the result. This note does not change v1 or force it to succeed. |
| After v1 — Claude designs; Codex challenges | Write the preservation design and registered comparison first. Audit cancel/drain/exit/recovery/restart behavior; resolve no-tuning and acceptance gates before experiments. |
| Only if justified — Claude + Codex, owner scope decision | Produce a separate paper-only v2 design for one simple short sleeve: precise venue/product, rules, risk budgets, settlement/account model and evaluation protocol. No product implementation from this note alone. |

Required future simulator scenarios: sustained decline; violent rebound through the
stop; trend whipsaw; partial/rejected exits; wide/stale/missing quotes; funding changes,
gaps and recovery; mark/last divergence; insufficient collateral; restart during exit;
minimum-size/dust constraints at both account sizes; and terminal loss with the vault
untouched. Tests must verify continuous loss accounting, no phantom fills/profits,
no collateral reuse and no new direction before reconciliation. These are a future
test inventory, not executed tests or a complete trading specification.

## 5. Sources, verification and limits

- [Moskowitz, Ooi and Pedersen, *Time series momentum*](https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf): primary paper supports investigating trend rules across traditional futures; it distinguishes time-series from cross-sectional momentum. It does not prove this crypto strategy profitable.
- [Bailey and Lopez de Prado, *The Deflated Sharpe Ratio*](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): primary methodological reference for selection/multiple-testing concerns, not a substitute for valid data and predeclared experiments.
- [Kraken EEA multi-collateral contract documentation](https://support.kraken.com/articles/multi-collateral-derivatives-contracts-eea): current product mechanics distinguish cross and isolated margin. Current documentation does not establish historical terms or this owner's eligibility; verify both separately before any product-specific design claim.

Verification on 2026-09-27: refreshed main and open-PR metadata, read #106's full
notes/discussion and six Cloud findings, inspected the current spot account validation,
pause/drain/liquidation paths and G specification, and ran the repository report checker
on the baseline (0 problems, seven embedded appendices checked). Publication checks
and exact response head are recorded on the response PR.

No strategy performance is established. No new replay, reserved market-data access,
installation, market-data download or trading occurred for this response. Claude's
entire literature list has not been independently replicated or fully read; quantitative
claims from summaries remain unverified. No new concrete security defect was found
in this documentation scope; exchange/custody/credential protections were not audited.
Existing paper-only, protected-profit and branch-ownership boundaries are preserved.
Runtime and persisted formats are unchanged; rollback is deletion/reversion of this
note and its index entry. Claude owns the next substantive response on #106.
