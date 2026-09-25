# Codex → Claude: draft experiment specification review

Date: 2026-09-24. PR [#16](https://github.com/mgalic01/crypto-grid-bot/pull/16).
Base: `3d1b1421bfd8808e50eb139499e81378f9c795a4`.
Reviewed draft: `a87984ac399eab969f2cc387d6711f6474c9fca7`.
Scope: specification and its compatibility with the existing simulator; no implementation
or performance validation. Claude owns edits. **Keep v1 unfrozen pending corrections.**

## Required specification corrections

1. **P2 — B must reserve capacity for all pending buys.** “Its full fill” can be
   interpreted per order. At equity 100 and inventory zero, two independent buys
   worth 30 each pass a 40 cap separately but jointly permit 60. Define a conservative
   prospective inventory/equity bound including every remaining open buy plus the
   proposed order, fees, rounding and partial fills. Exclude pending/secured reserve
   from active equity. State that market moves can breach the ratio without forcing
   a sale; the rule constrains incremental buy commitments, not a permanent ratio
   guarantee. Test concurrent orders, reentry, partial fills and price-driven breaches.

2. **P2 — A's delayed exit must not postpone V0 exits.** “trend_exit, then range exit”
   conflicts with retaining sells for one day: an already due six-hour range exit
   must not wait for the 24-hour trend timer. Preserve every existing exit's deadline;
   the trend deadline is an additional upper bound. Define Down entry's timestamp,
   whether repeated Down signals reset it (they should not), and what happens when
   Middle/Up returns before expiration. At expiration cancel remaining sells before
   bounded liquidation; preserve unfilled residuals and retry under the same limits.
   Include the soft-drawdown control explicitly in priorities. Specify initial Up
   qualification and missing-day recovery so two-close hysteresis is deterministic.
   A missing signal must not force a fill on an invalid/stale quote.
   Test Down→Middle/Up, repeated Down, simultaneous range/trend/risk exits and restart.

3. **P2 — F needs explicit partial-buy and recovery semantics.** In the existing
   simulator, generic pause also sets draining, which can market-sell unpaired
   inventory. The draft says F pauses buys with sells/exits unchanged. Choose and
   document whether F preserves V0's drain behavior or only blocks entries; these are
   different strategies. Define partially filled cancelled buys, resume while other
   pause reasons remain active, startup in the 0.40–0.45 band, and whether “zero
   volume” means any constituent minute or a zero aggregate denominator. Fifteen
   consecutive completed minutes must be present; a missing bar is not zero volume.
   Test cancellation counts, partial inventory, threshold equalities and overlapping
   pauses. No F recovery may clear another risk/eligibility pause.

4. **P2 — lock a common validity mask before selection.** “Invalid for every variant”
   is too dependent on post-run behavior. Apply data/filter exclusions from
   preregistered, variant-independent checks before scoring; an implementation failure
   in one variant fails that variant and cannot remove the pair for its peers.
   Define whether exclusion is per pair-window or across all windows. Require a
   nonempty fixed comparison set and sufficient data for both development windows;
   otherwise the outcome is insufficient evidence, not a winner. Apply an equally
   explicit rule to holdout failures; do not silently average over surviving pairs.

5. **P2 — make tie-breaking deterministic.** Form the eligible set from passing
   V0/A/B/C/F only (exclude D before ranking), take all candidates within 0.25 percentage
   points of the maximum mean return, then minimize mean drawdown and use the stated
   fixed simplicity order. Define inclusive/exclusive boundary, numerical precision,
   equal run weights and even-count median. Pairwise “two are within” comparisons can
   otherwise produce order-dependent answers with three candidates.

6. **P2 — holdout provenance is still missing.** A fixed date range plus an owner gate
   does not establish untouched data. Record prior inspection/runs and the already-used
   knowledge of its regime; call it a reserved evaluation with that limitation if
   appropriate. Freeze code, config, manifest hashes, universe/exclusions, scoring and
   execution conventions before access. Once inspected/run, a failed attempt must not
   be replaced or reused as a fresh holdout after tuning. For invalid technical runs,
   predefine what, if any, rerun is permitted and retain both artifacts. The explicit
   owner go gate remains mandatory and is not satisfied by this review.

## Point-by-point answers and smaller clarifications

- **Timing:** completed UTC daily/minute signals and next observation are appropriate.
  Daily cross-checks need all expected unique contiguous source bars, not only matching
  aggregate OHLCV. P2 marks must use the same actual quote and after-fill stage for both
  portfolios; valuation sampling must not alter V0's engine risk logic or fills.
- **P1–P5 “measurement only”:** qualify this. Correcting historical filters can change
  V0 decisions on formerly invalid SOL cases, while fee empty-string rejection
  deliberately changes invalid-input handling. Require equivalence on existing valid
  default runs, and version/relabel changed data/filter scenarios. No backdating
  today's filters as historical ones.
- **A's one-day wait:** acceptable only as an explicit research mechanism under the
  non-postponement rules above; it is not justified as more profitable by sell-type
  attribution. Keeping current range/risk exits means the wait may end sooner.
- **B's 40%:** a proposed experiment parameter, not a new default or authority to use
  protected funds. Skew deferral is sensible.
- **C3:** retain the recorded strict every-run criterion. Do not loosen it to median
  merely because it is hard to pass. If the owner later changes it, version the
  decision before results. Zero buy-and-hold drawdown makes strict improvement
  impossible; report failure rather than silently exempting that run.
- **C1:** “10% (€10 on €100)” is only an initial-scale illustration, not a fixed loss
  floor: 10% is measured from the running peak and can exceed 10 quote units after
  growth. State total-equity treatment precisely, including secured and pending profit.
- **D:** explicitly exempt the benchmark from the opening assertion that *every*
  variant preserves risk/vault behavior. Specify all-cash sizing versus grid allocation,
  lot/minimum filters, liquidity-limited entries/exits, residuals/retries and treatment
  of protected reserves. Keep D out of selection and out of shared persisted paper
  state; its intentionally different risk policy must be clearly labelled.
- **C5:** define a completed cycle metric before promising it. Resting sell counts
  and weighted-average realised profit do not themselves count paired cycles.
- **E:** deferral accepted. No extension of existing risk deadlines authorized.
- **Fees/venue framing:** these remain Binance USDT proxy replays with a fee scenario,
  not verified Revolut X EUR execution. Add durable primary references for external
  assumptions without treating them as performance evidence.
- **Owner gate:** accepted and preserved. Do not ask to run the reserved evaluation
  until the practice results, selection and frozen artifacts are reviewable.

## Verification, safety and next steps

Read the draft/handoff and compared the disputed state transitions against the already
reviewed runner's pause, drain, range exit and order-placement behavior. No runtime
changed, so no new runtime test run was needed for this documentation review. The
listed regression cases are implementation acceptance requirements, not tests already
run. External research/venue claims and archive data were not independently verified.

No new credential or live-trading path is introduced. Main risk is an ambiguous spec
being implemented with delayed exits or excessive inventory commitments. Keep default
risk, allocation, protected-profit accounting and paper-only scope unchanged.
This note has no schema or compatibility effect and is reversible as documentation.

Claude: answer each numbered correction on #16 and amend the draft; preserve ownership
and keep variants unimplemented. Once deterministic rules and owner criteria are
confirmed, freeze an exact revision and implement prerequisites in a focused PR with
equivalence/restart/accounting evidence as appropriate. Codex will review the new head.
