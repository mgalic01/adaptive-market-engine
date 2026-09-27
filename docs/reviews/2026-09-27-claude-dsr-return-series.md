# Claude: draft spec part 3 — the return series the deflated Sharpe ratio is computed on

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** The go/no-go test on the reserved 2025–26 window is
  only worth running if development results survive the multiple-testing correction.
  The deflated Sharpe ratio (DSR) is that correction, and it has two inputs: the
  number of trials, fixed in [part 2](2026-09-27-claude-retrospective-trial-count.md),
  and **the return series whose Sharpe is deflated, which nothing defines yet**. Each
  choice below changes the Sharpe of identical runs. Left open, they would be settled
  after results exist — by whichever answer looks better. This fixes them first.
- **Scope.** A proposal for three-agent agreement, written before any variant has run.
  It computes nothing from any strategy result and reads no market data. The
  [data-reuse agreement](2026-09-25-claude-data-reuse-proposal.md), layer 4, lists what
  the spec must fix; this report takes that list item by item. A cloud Claude review on
  PR #93 found the gap; Codex had accepted the requirement earlier.

## 1. The list this must answer

From the data-reuse agreement, layer 4, accepted by Codex: *return frequency,
reserve-inclusive equity basis, risk-free benchmark, annualisation, calendar alignment
and fold stitching; no-trade / zero-variance / invalid-run treatment; tested family; raw
and effective trial counts; and dependence adjustment.* It also requires validating the
existing hourly-equity output's sampling and gap/halt semantics before using it, and
says that serial dependence and an iid DSR probability must not be sold as calibrated
confidence.

Part 2 covers the trial counts. Sections 2–8 propose the rest.

## 2. Basis: one account's total equity, reserves included

**Proposal.** The series is **total equity** of one simulated account — active equity
as `Account.equity` values it (cash − pending reserve + inventory × bid × (1 − slippage)
× (1 − taker fee)), plus the pending and secured reserves. This is the same basis as
criterion C1(a).

- **Why reserve-inclusive:** vault transfers move money between the account's own
  buckets. Measured on active equity alone, every transfer would look like a loss.
- **No external flows exist** in a replay: no deposits or withdrawals. So returns need no
  flow adjustment, and any future flow must be recorded and excluded explicitly.
- **Marking at the exit price** (bid, slippage and taker fee) is conservative and is
  what C1 already uses. One consequence belongs here: an invested account's mark moves
  with the spread even when nothing trades, adding noise that a flat account does not
  have. Section 3's daily frequency is partly chosen to damp this.

## 3. Frequency and calendar: daily, UTC, clock time

**Proposal.** One observation per **UTC calendar day**: total equity after the last
quote of the last valid bar whose open time falls in that day. The return for day *d*
is `E_d / E_(d−1) − 1`, a simple return.

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
  whether or not the account traded. Section 4 explains why this is the conservative
  choice.
- **Risk-free rate: zero.** Cash in the simulator earns nothing, and the question the
  owner asks is whether the bot beats holding cash. So excess return equals return.
- **Annualisation is for display only:** × √365, since crypto trades every day. The DSR
  itself uses the per-period (daily) Sharpe and the number of observations, never an
  annualised figure.

### The existing `hourly_equity` output is not this series

Validated against `backtest/replay.py` (lines 437–440 at `de38fdb`), it records total
equity after the **first** minute bar of each hour. An hour with no valid bar is
silently absent, with no marker. So it is neither an end-of-period sample nor
gap-aware. It stays as it is, as a diagnostic. The DSR series needs a new measurement:
a per-day, end-of-day sample, with each missing day recorded explicitly.

Like P2, that measurement must not change any V0 decision or fill. A V0 replay must stay
byte-identical in every existing field; PR #99 shows how that was checked for variant B.

## 4. Flat periods, halts and zero variance

**Proposal.** Flat days are included as the zero returns they are, including days after
a halt and days spent paused. A series with zero variance has no Sharpe; that run is
reported as **indeterminate**, never as a pass.

**Why including flat days is conservative — a correction to the review that raised
this.** The review on PR #93 said that including zero-return periods lowers the
volatility estimate "while mean return is unchanged", so the Sharpe rises mechanically.
The mean does not stay unchanged: the zeros lower it too.

Take an account active a fraction *p* of the days, with mean *μ* and standard deviation
*σ* on active days. Over clock time:
- the mean is *pμ*;
- the variance is *pσ²* + *p*(1 − *p*)*μ²*, which is about *pσ²* for daily *μ* much
  smaller than *σ*;
- so the per-period Sharpe is about √*p* × *μ*/*σ*.

**Including flat days lowers the Sharpe by roughly √*p*.** For an account invested 30%
of the time, that is × 0.55.

The choice that inflates is the other one: computing the Sharpe over **trading time
only** and then annualising it as if the account traded every day. That silently drops
the factor √*p*. It is ruled out here. The reviewer's underlying concern is right —
this choice can dominate the go/no-go number, so it must be fixed before results exist.
Only the direction was reversed.

Two further effects, both in the conservative direction:
- **Heavy tails.** A mostly-zero series has high excess kurtosis. The DSR's variance
  term grows with kurtosis, so the deflated figure falls.
- **Halts and lockouts count.** After a hard-drawdown halt the account is flat for the
  rest of the window. My code reading on PR #99 suggests the same may happen after an 8%
  soft drawdown, because the pause never clears on a flat account; that is being checked
  empirically. Those days are real: the owner's money would sit idle. They are
  included, not trimmed. A halt still fails C1 separately; the DSR does not soften that.

## 5. Gaps, masked hours and invalid runs

Part 1 leaves masked hours and outages to settings still to be agreed. The return
series depends on them only through this rule.

**Proposal.**
- A day with **at least one valid bar** gives an observation, sampled after its last
  valid bar.
- A day with **no valid bar** gives none. The next observed return then spans the gap.
  It is kept as one observation and flagged, not split into invented daily returns.
- The report states, for each run, how many returns span a gap and the longest gap.
- **An invalid run** (§5 of the spec) contributes no series. It already fails C4.

**For agreement:** the largest share of gap-spanning returns a fold may carry before its
series counts as indeterminate. I propose **5% of the fold's days**. It is a data rule,
chosen here before any result, not a strategy parameter.

## 6. Fold stitching

**Proposal.** Each fold's test window starts a **fresh account at the initial capital**,
using that fold's tuned parameters. Returns are computed only within a window: no return
spans a fold boundary. The stitched series is the windows' daily returns concatenated in
calendar order, 2018-08 .. 2024-10 at most, with each calendar day scored once, since
test windows do not overlap.

- **Why fresh accounts, not one carried account:** carrying inventory and high-water
  marks across a boundary would mix two parameter sets in one position. The data-reuse
  agreement already requires boundary state to be defined before execution. A fresh
  account at each boundary is the simplest definition that is causal.
- **Consequence to accept:** compounding across folds is not measured. That is right for
  a Sharpe (a per-period statistic), and C1–C6 are judged per run anyway.

## 7. Pairs and paths: which series gets deflated

Pairs over the same dates are not independent observations, and the spec judges both
intrabar paths.

**Proposal.**
- **Per path**, the headline series is the **equal-weight daily average of the included
  pairs' returns**. That is the return of holding one separate €100 account per pair.
  Pairs join and leave as their folds are eligible; a day's average uses the pairs
  eligible that day.
- **The variant's DSR is the lower of its two path DSRs**, matching C2's worse-path
  logic.
- Per-pair series and DSRs are reported, never used for selection.

## 8. Dependence, threshold, and what DSR decides

- **Dependence adjustment:** report the Sharpe with Lo's autocorrelation adjustment next
  to the naive figure, using the first five autocorrelations of the daily series. The
  DSR is computed with the kurtosis and skewness of that series. Its probability is
  **not** called calibrated confidence: serial dependence and correlated trials break
  the iid assumption, as the data-reuse agreement already says.
- **Trial family and count:** from part 2 and the register. The variance of Sharpe
  estimates across trials uses each trial's series, built by these same rules.
- **Threshold and its role — an owner question.** Spec §6 does not include DSR in
  acceptance or selection. I propose it stays a **reported** diagnostic, with
  "DSR ≥ 0.95" shown as a flag, unless the owner decides it should gate the go/no-go
  run. Under the agreement, unsupported assumptions give an **indeterminate** DSR,
  never a pass.

## 9. Decisions this asks for, before any variant runs

1. Basis: reserve-inclusive total equity of one account (section 2).
2. Daily UTC end-of-day samples in clock time, risk-free rate zero, √365 for display
   only; hourly as a sensitivity only (section 3).
3. Flat, paused and post-halt days included as zeros; zero variance is indeterminate
   (section 4).
4. Gap rule, with the 5% indeterminate limit (section 5).
5. Fresh account per test window; no return across a boundary (section 6).
6. Equal-weight pair average per path; the lower path DSR (section 7).
7. Lo-adjusted Sharpe reported; DSR reported with a 0.95 flag; whether it gates the
   go/no-go run is the owner's call (section 8).
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
  These rules must be fixed without knowing which one flatters a variant.
- **Not settled here:** the masking and outage settings of part 1, which section 5
  depends on only through its gap rule, and the trusted process that writes the trial
  register.
