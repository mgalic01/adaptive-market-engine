# Claude: draft spec part 3 — the return series the deflated Sharpe ratio is computed on

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** The go/no-go test on the reserved 2025–26 window is
  only worth running if development results survive the multiple-testing correction.
  The deflated Sharpe ratio (DSR) is that correction. It has two inputs: the number of
  trials, **proposed** in part 2 ([PR #93](https://github.com/mgalic01/adaptive-market-engine/pull/93),
  not yet merged), and **the return series whose Sharpe is deflated, which nothing
  defines yet**. Each choice below changes the Sharpe of identical runs. Left open, they
  would be settled after results exist — by whichever answer looks better. This fixes
  them first.
- **Scope.** A proposal for three-agent agreement, written before any variant has run.
  It computes nothing from any strategy result and reads no market data. The
  [data-reuse agreement](2026-09-25-claude-data-reuse-proposal.md), layer 4, lists what
  the spec must fix; this report takes that list item by item. A cloud Claude review on
  PR #93 found the gap; Codex had accepted the requirement earlier.
- **Revision 2 (same day):** reworked for nine Codex Cloud findings and the automated
  review on PR #101. Section 11 lists each change.

## 1. The list this must answer

From the data-reuse agreement, layer 4, accepted by Codex: *return frequency,
reserve-inclusive equity basis, risk-free benchmark, annualisation, calendar alignment
and fold stitching; no-trade / zero-variance / invalid-run treatment; tested family; raw
and effective trial counts; and dependence adjustment.* It also requires validating the
existing hourly-equity output's sampling and gap/halt semantics before using it, and
says that serial dependence and an iid DSR probability must not be sold as calibrated
confidence.

Part 2 proposes the trial counts. Sections 2–8 propose the rest.

## 2. Basis: one account's total equity, reserves included

**Proposal.** The series is **total equity** of one simulated account — active equity
as `Account.equity` values it (cash − pending reserve + inventory × bid × (1 − slippage)
× (1 − taker fee)), plus the pending and secured reserves. This is the existing
`total_equity` field (`runner.py`: active equity + pending + secured), the same basis as
criterion C1(a).

- **Why reserve-inclusive:** vault transfers move money between the account's own
  buckets. Measured on active equity alone, every transfer would look like a loss.
- **No external flows exist** in a replay: no deposits or withdrawals. So returns need no
  flow adjustment, and any future flow must be recorded and excluded explicitly.
- **Marking at the exit price** (bid, slippage and taker fee) is conservative and is what
  C1 already uses. One consequence belongs here: an invested account's mark moves with
  the spread even when nothing trades, adding noise that a flat account does not have.
  Section 3's daily frequency is partly chosen to damp this.

## 3. Frequency and calendar: daily, UTC, clock time

**Proposal.** One observation per **UTC calendar day** *d*: `E_d`, total equity after
the last quote of the last valid bar whose open time falls in that day.
- The return is the simple return `E_d / E_(d−1) − 1`.
- **The first return of each test window** uses as `E_0` the equity immediately before
  the window's first quote. For a fresh account (section 6) that is the initial capital,
  so the first day's P&L is never dropped.

- **Why daily, not hourly or per minute.**
  - Hourly marks carry bid-ask bounce and the grid's own short-horizon mean reversion,
    which make returns strongly autocorrelated. That is exactly the case where naive
    annualisation misleads.
  - Daily is the cadence of the slowest signals: variant A's SMA, H's cycle phase.
  - A 3-month test window then gives about 90 observations, and the stitched stream up
    to 2,284 (2018-08-01 .. 2024-10-31, 75 months). That is long enough for skewness and
    kurtosis estimates to mean something.
- **Hourly is a reported sensitivity only,** never used for selection or for the
  headline DSR.
- **Clock time, not trade time.** Every calendar day of a test window is an observation,
  whether or not the account traded. Section 4 gives the reason and its limits.
- **Risk-free rate: zero.** Cash in the simulator earns nothing, and the question the
  owner asks is whether the bot beats holding cash. So excess return equals return.
- **Annualisation is for display only:** × √365, since crypto trades every day. The DSR
  itself uses the per-period (daily) Sharpe and an effective number of observations
  (section 8), never an annualised figure.

### The existing `hourly_equity` output is not this series

Validated against `backtest/replay.py` (lines 437–440 at `de38fdb`), it records total
equity after the **first** minute bar of each hour. An hour with no valid bar is silently
absent, with no marker. So it is neither an end-of-period sample nor gap-aware. It stays
as it is, as a diagnostic. The DSR series needs a new measurement: a per-day, end-of-day
sample, with each missing day recorded explicitly.

Like P2, that measurement must not change any V0 decision or fill. A V0 replay must stay
byte-identical in every existing field; PR #99 shows how that was checked for variant B.

## 4. Flat, paused and halted days

**Proposal.**
- **Every day's return comes from actual equity.** Days when the account is flat,
  paused or halted are kept in the series, not trimmed.
- **A day's return is zero only when consecutive end-of-day equities are equal.** A
  paused or newly halted account is not necessarily flat. It may still hold inventory
  and resting sells, and drain or liquidation is limited by bid depth, so its marked
  equity can keep moving. That P&L is real and stays in the series.
- **A series with zero variance has no Sharpe.** That run is reported as
  **indeterminate**, never as a pass.

**Why clock time, and what it does to the Sharpe — correcting both the review that raised
this and my own first version.** The PR #93 review said that including zero-return
periods lowers the volatility estimate "while mean return is unchanged", so the Sharpe
rises. But the zeros lower the mean too.

Take an account active a fraction *p* of the days, with mean *μ* and standard deviation
*σ* on active days. Over clock time:
- the mean is *pμ*;
- the variance is *pσ²* + *p*(1 − *p*)*μ²*, which is about *pσ²* for daily *μ* much
  smaller than *σ*;
- so the per-period Sharpe is about √*p* × *μ*/*σ*.

That is a **shrinkage toward zero by about √*p***: × 0.55 for an account active 30% of
the time. My first version called this conservative without qualification. Codex Cloud
showed that is only half true:
- **For a candidate with positive skill** (*μ* > 0), shrinkage lowers the Sharpe. That
  is the case that decides go/no-go.
- **For a losing candidate** (*μ* < 0), the same shrinkage makes its Sharpe less
  negative.
- **Across the trial family**, shrinkage also narrows the spread of Sharpe estimates.
  That lowers the DSR's expected-maximum benchmark (section 8), which pushes the DSR
  *up*.

So clock time is not conservative in every direction. It is chosen because it measures
what the owner's money actually experiences, per calendar day. The alternative — a
Sharpe over trading days only, annualised as if the account traded every day — silently
drops the √*p* factor and inflates a positive candidate. That alternative is ruled out.
Every trial in the family must use the same clock-time rule, so that their Sharpes are
comparable.

Two further effects:
- **Heavy tails.** A mostly-zero series has high kurtosis. Section 8's variance term grows
  with kurtosis, so the deflated figure falls.
- **Halts and lockouts count.** After a hard-drawdown halt the account is liquidated and
  then flat for the rest of the window. A replay check on PR #99's thread found the same
  after an 8% soft drawdown: in every run that went flat at about 8% or more, equity
  never changed again, for between 102 and 235 days. Those days are real — the owner's
  money would sit idle — and they stay in. A halt still fails C1 separately; the DSR
  does not soften that.

## 5. Gaps: any missing day makes the fold indeterminate

Part 1 leaves masked hours and outages to settings still to be agreed. The return series
depends on them only through this rule.

**Proposal.**
- A day with **at least one valid bar** gives an observation, sampled after its last
  valid bar.
- **If any eligible pair has a day with no valid bar in a fold's test window, that
  fold's series is indeterminate for the DSR.** It still counts for C1–C6 as the spec
  already defines.
- The report states each indeterminate fold and the missing days that caused it.
- **An invalid run** (§5 of the spec) contributes no series. It already fails C4.

My first version kept a return that spans a missing day as one flagged "daily"
observation, up to 5% of a fold. Codex Cloud pointed out that this mixes horizons and
gives the Sharpe the wrong period count; flagging does not correct the statistic. The 5%
allowance is therefore withdrawn. A whole UTC day with no valid bar is rare in the
basket (Bob's outage calendar has 58 hours in 14 events in parsed coverage), so the
strict rule should cost little. The indeterminate-fold count will show whether it does.

## 6. Fold stitching

**Proposal.** Each development fold's test window starts a **fresh account at the
initial capital**, using that fold's tuned parameters. Returns are computed only within a
window: no return spans a fold boundary. The stitched series is the windows' daily
returns concatenated in calendar order, 2018-08 .. 2024-10 at most, with each calendar
day scored once, since test windows do not overlap.

- **The reserved evaluation** (spec §7) is one window run once. It also starts from a
  fresh account at the initial capital, and its series is built by the same rules.
- **Why fresh accounts, not one carried account:** carrying inventory and high-water marks
  across a boundary would mix two parameter sets in one position. The data-reuse
  agreement already requires boundary state to be defined before execution. A fresh
  account at each boundary is the simplest definition that is causal.
- **Consequence to accept:** compounding across folds is not measured. That is right for
  a Sharpe (a per-period statistic), and C1–C6 are judged per run anyway.

## 7. Pairs and paths: which series gets deflated

Pairs over the same dates are not independent observations, and the spec judges both
intrabar paths.

**Proposal.**
- **Per path and per fold, the headline series is the return of the combined pair
  accounts:** `B_d = Σ_i E_(i,d)` over the fold's eligible pairs, and the return is
  `B_d / B_(d−1) − 1`, with `B_0` = the number of eligible pairs × initial capital.
- **Eligibility is fixed per fold.** A pair is eligible for a whole fold or not at all,
  so the basket does not change within a window.
- **Why not an equal-weight average of pair returns:** once the pair accounts diverge,
  that average assumes a daily rebalance back to equal weights, which no account does.
  My first version proposed it; Codex Cloud pointed out it is not the return of holding
  separate accounts. The equity-weighted form above is.
- **The variant's DSR is the lower of its two path DSRs,** matching C2's worse-path
  logic.
- Per-pair series and DSRs are reported, never used for selection.

## 8. The DSR, frozen: formula, moments, dependence and role

Everything a result could otherwise steer is fixed here.

- **Formula:** Bailey and López de Prado (2014). With the per-period (daily) Sharpe
  `SR`, its skewness `γ3` and kurtosis `γ4`, and the number of observations `T`:
  `PSR(SR*) = Φ( (SR − SR*) · √(T − 1) / √(1 − γ3·SR + (γ4 − 1)/4 · SR²) )`, and
  `DSR = PSR(SR0)`, where
  `SR0 = √V · ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) )`.
  Here `V` is the variance of the daily Sharpes across the `N` trials of the family,
  and `γ` ≈ 0.5772 is the Euler–Mascheroni constant.
- **Moment conventions:** `γ4` is **Pearson kurtosis**, not excess kurtosis: a normal
  distribution has 3. Skewness, kurtosis and the Sharpe's standard deviation use
  **population (divide-by-`T`) moment estimators**, with no small-sample correction.
  Any library must be checked against these conventions before use.
- **The Sharpe that enters is the raw daily Sharpe,** mean over standard deviation of
  the stitched daily returns.
- **Dependence enters through `T`, not through an adjusted Sharpe.** `T` is replaced by
  an effective count `T_eff = T / (1 + 2·Σ_(k=1..5) (1 − k/6)·ρ_k)`, using Bartlett
  weights on the first five autocorrelations.
  - It is capped at `T`, so negative autocorrelation never earns extra observations.
  - Each `ρ_k` is estimated from lag pairs **within the same fold only**: the pair
    formed by one fold's last return and the next fold's first return is excluded,
    because those come from different accounts and parameter sets.
- **Lo's adjusted annual Sharpe** is reported next to the naive one, for information
  only; it does not enter the DSR.
- **`V` and `N`:** each trial's Sharpe is built by these same rules, and `N` comes from
  part 2 and the trial register. With `N` = 2, the central count proposed in part 2,
  `V` rests on two numbers and is very uncertain. The report must say so, and must
  show the DSR at part 2's sensitivity count too.
- **Threshold and role — an owner question.** Spec §6 does not include the DSR in
  acceptance or selection. I propose it stays a **reported** diagnostic, with
  "DSR ≥ 0.95" shown as a flag, unless the owner decides it should gate the go/no-go
  run. It is **not** calibrated confidence: correlated trials and the remaining serial
  dependence break its iid assumption. Unsupported assumptions give an
  **indeterminate** DSR, never a pass.

## 9. Decisions this asks for, before any variant runs

1. Basis: reserve-inclusive total equity of one account (section 2).
2. Daily UTC end-of-day samples in clock time, the first return seeded from the equity
   before the window's first quote, risk-free rate zero, √365 for display only; hourly
   as a sensitivity only (section 3).
3. Returns from actual equity on every day, flat, paused and halted days included;
   zero variance is indeterminate (section 4).
4. Any day with no valid bar makes the fold indeterminate for the DSR (section 5).
5. A fresh account per test window, the reserved run included; no return across a
   boundary (section 6).
6. An equity-weighted basket per path and fold; the lower path DSR (section 7).
7. The frozen DSR: formula, Pearson kurtosis, population moments, raw Sharpe, `T_eff`
   with within-fold Bartlett lags 1–5 capped at `T`; Lo reported only; a 0.95 flag.
   Whether it gates the go/no-go run is the owner's call (section 8).
8. Implementation: a new end-of-day equity measurement, V0 byte-identical, and the
   existing `hourly_equity` left as a diagnostic.

## 10. What I checked, and what I could not

- **Checked:**
  - the layer-4 list against the agreement text and Codex's response
    (`2026-09-26-codex-data-reuse-response.md`);
  - the hourly-equity sampling point in `replay.py`;
  - the P2 and C1 definitions in `EXPERIMENT_SPEC_V1.md`;
  - the clock-time algebra in section 4, which is exact for the mean and exact for the
    variance before the stated approximation.
- **Did not compute** any Sharpe, flat-time share or DSR from any run, V0 included.
  These rules must be fixed without knowing which one flatters a variant. The lockout
  durations in section 4 are equity-change timings from V0 replays already reported,
  not Sharpe figures.
- **Not settled here:** the masking and outage settings of part 1 (proposed values are
  in PR #100), which section 5 depends on only through its gap rule; the trial count
  (part 2, PR #93); and the trusted process that writes the trial register.

## 11. Changes in revision 2

| Finding (PR #101) | Change |
| --- | --- |
| Automated review: part 2 linked as if merged | Links PR #93 and says "proposed, not yet merged" (header, §1, §8, §10) |
| Automated review nit: reserved run unclear | §6 states the reserved run also starts fresh |
| Automated review nit: 5% threshold needs sign-off | Moot: the allowance is withdrawn (§5) |
| Cloud P2: first day of each fold has no `E_(d−1)` | §3 seeds `E_0` from the equity before the first quote |
| Cloud P1: paused/halted days forced to zero | §4 takes every return from actual equity; zero only when equal |
| Cloud P2: direction of the zero effect | §4 qualified: shrinkage toward zero; lowers a positive Sharpe, raises a negative one, and narrows the trial spread |
| Cloud P1: gap-spanning returns mix horizons | §5: any missing day makes the fold indeterminate; the 5% allowance withdrawn |
| Cloud P1: arithmetic mean of pair returns implies rebalancing | §7: equity-weighted basket `ΣE_d / ΣE_(d−1)` |
| Cloud P2: autocorrelation across fold resets | §8: lag pairs within a fold only |
| Cloud P1: how dependence enters the DSR | §8: raw Sharpe; dependence through capped `T_eff`; Lo reported only |
| Cloud P1: kurtosis convention | §8: Pearson kurtosis, population moments |
