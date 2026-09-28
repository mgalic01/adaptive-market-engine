# Claude: draft spec part 3 — the return series the deflated Sharpe ratio is computed on

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** The go/no-go test on the reserved 2025–26 window is
  only worth running if development results survive the multiple-testing correction.
  The deflated Sharpe ratio (DSR) is that correction. It has two inputs: the number of
  trials, **proposed** in part 2 ([PR #93](https://github.com/mgalic01/adaptive-market-engine/pull/93),
  merged as a proposal, not an adopted counting rule), and **the return series whose Sharpe is deflated, which nothing
  defines yet**. Each choice below changes the Sharpe of identical runs. Left open, they
  would be settled after results exist — by whichever answer looks better. This fixes
  them first.
- **Scope.** A proposal for three-agent agreement, written before any variant has run.
  It computes nothing from any strategy result and reads no market data. The
  [data-reuse agreement](2026-09-25-claude-data-reuse-proposal.md), layer 4, lists what
  the spec must fix; this report takes that list item by item. A cloud Claude review on
  PR #93 found the gap; Codex had accepted the requirement earlier.
- **Revisions (same day):** revision 2 answered nine Codex Cloud findings and the
  automated review; revision 3 answered Bob, the automated review and seven further Cloud
  findings; revision 4 answered Bob's eligibility point and four more Cloud findings;
  revision 5 answers Codex's audit, one more Cloud finding and the automated review.
  Section 11 lists each change.
- **Revision 6 (2026-09-27, after merge):** the DSR cannot be estimated on this family.
  `V` is unestimable — the counted runs never produced the daily series, so their Sharpes
  do not exist to take a variance of — and the estimator's hurdle falls as more trials
  are disclosed. The owner adopted a Holm step-down instead, as C7 in the spec.
  In section 8, the `SR0`/`V` definition, the `N` = 2 sentence, the missing-Sharpe rule,
  `N < 2`, and the open "owner question" are superseded; the PSR formula, moment
  conventions and `T_eff` stand. The daily series is required of forward runs only. See
  [the coherence record](2026-09-27-claude-dsr-coherence.md).

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

**Proposal.** One observation per **UTC calendar day** *d*, taken at one **valuation
timestamp** shared by every pair and every account: `τ_d` = 00:00:00 UTC of day *d* + 1,
the close of day *d*.
- **Which bar marks a pair.** For each eligible pair *i*, `E_(i,d)` is total equity after
  the closing quote of that pair's **last valid 1m bar that closes at or before `τ_d`**,
  that is, the last valid bar opening at or before 23:59 UTC on day *d*. "Valid" means
  present and not masked under part 1's rules (PR #92, with the values proposed in
  PR #100, once agreed). No bar at or after `τ_d` is ever used.
- **Only the price can be stale, not the account.** A replay changes the account only at
  a quote. Between that bar's closing quote and `τ_d` nothing fills and nothing moves, so
  `E_(i,d)` is the account's exact state at `τ_d`. What can be old is the price its
  inventory is marked at.
- **Maximum mark age: 60 minutes.** The age is `τ_d` minus the open time of the marking
  bar. Normally the 23:59 bar marks the pair, at an age of 1 minute. The marking bar must
  open at 23:00 UTC or later.
- **Beyond that age, the pair-day is masked.** The pair has no mark for day *d*. It is
  treated like a masked hour: the pair-day is masked, and since the basket (section 7)
  needs every eligible pair, the day counts as missing for section 5. A stale mark is
  never carried forward, and a pair is never dropped from the basket for a day. Masked
  hours earlier in the day do not affect the mark; how the replay trades through them is
  part 1's gap policy.
- **Why these values.** Every pair is marked within the same final hour, so the basket
  is valued at one time to within an hour, and each pair's daily return spans between 23
  and 25 hours: at most one hour in 24 of mixed horizon. A longer limit would admit more
  of the horizon mixing that section 5 rules out. A shorter one would turn brief outages
  just before midnight into missing days. The cost is known in advance: a masked or
  outage hour at 23:00 UTC in any eligible pair makes that day missing, and so its fold
  indeterminate. The indeterminate-fold count will show how often.
- **Fixed before any result exists.** The timestamp, the at-or-before rule, the
  60-minute limit and the masking treatment are fixed now. They are proposals for the
  owner and Codex to accept. Changing any of them after a run has been seen would be
  post-hoc tuning.
- For one account, the return is the simple return `E_d / E_(d−1) − 1`. Section 7
  combines the pair accounts, each marked at the same `τ_d`.
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
- **Clock time, not trade time.** Every calendar day of a test window is an observation,
  whether or not the account traded. Section 4 gives the reason and its limits.
- **Risk-free rate: zero.** Cash in the simulator earns nothing, and the question the
  owner asks is whether the bot beats holding cash. So excess return equals return.
- **No annualised figure.** Only the daily Sharpe is reported. Multiplying it by √365
  gives an annual Sharpe only for serially independent returns, and section 8 expects
  dependence; a correct aggregation would depend on the autocorrelations. Nothing
  downstream needs an annual figure: the DSR uses the daily Sharpe and an effective
  number of observations (section 8), and no criterion C1–C6 uses a Sharpe. So none is
  shown, and layer 4's "annualisation" item is answered by this: none.

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
- **Across the trial family**, each trial is shrunk by its own √*p*. The spread of Sharpe
  estimates, which sets the DSR's benchmark (section 8), can therefore narrow, widen or
  reorder.
- **Net effect on the DSR:** the candidate's own shrinkage and the benchmark's change can
  pull in opposite directions. The net sign is **not claimed** for any case.

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
- A day counts as **missing** if any eligible pair-day is masked: the pair has no valid
  bar opening at or after 23:00 UTC that day, so its mark at `τ_d` would be more than
  60 minutes old (section 3).
- **A fold with any missing day is indeterminate for the DSR.** It still counts for
  C1–C6 as the spec already defines.
- **One indeterminate fold makes the variant's headline DSR indeterminate.** Dropping the
  fold and stitching the rest would change the tested calendar in a way that could
  flatter or hurt the result, so it is not the headline. The DSR over the remaining folds
  is shown only as a labelled sensitivity.
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
- **Eligibility is fixed per fold, and fixed before any run.** A pair is eligible for a
  whole fold or not at all, so the basket does not change within a window.
  - Eligibility is decided **only from data coverage**: the fold-eligibility rule of part 1
    (PR #92) with the masking values proposed in PR #100, once agreed.
  - It never depends on anything a run produces — trades, returns, activity, or whether a
    Sharpe is defined.
  - The eligible pair set for every fold is published before the first variant run.
- **Why not an equal-weight average of pair returns:** once the pair accounts diverge,
  that average assumes a daily rebalance back to equal weights, which no account does.
  My first version proposed it; Codex Cloud pointed out it is not the return of holding
  separate accounts. The equity-weighted form above is.
- **Each path is deflated against its own family.** For path *q*, `V_q` is the variance
  of the trials' Sharpes **on path *q***, and `N` is the same trial count for both
  paths. Paths are never pooled into one family, because that would count dependent
  paths as extra trials.
- **The variant's DSR is the lower of its two path DSRs,** matching C2's worse-path
  logic.
- **Per pair, only return statistics are reported** (mean, standard deviation, Sharpe),
  never a per-pair DSR, and never used for selection. A per-pair DSR would need its own
  trial family and fold rules, and nothing depends on it.

## 8. The DSR, frozen: formula, moments, dependence and role

Everything a result could otherwise steer is fixed here.

- **Formula:** Bailey and López de Prado (2014). With the per-period (daily) Sharpe
  `SR`, its skewness `γ3` and kurtosis `γ4`, and the number of observations `T`:
  `PSR(SR*) = Φ( (SR − SR*) · √(T − 1) / √(1 − γ3·SR + (γ4 − 1)/4 · SR²) )`, and
  `DSR = PSR(SR0)`, where
  `SR0 = √V · ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) )`.
  Here `V` is the variance of the daily Sharpes across the `N` trials of the family,
  and `γ` ≈ 0.5772 is the Euler–Mascheroni constant.
- **`V` uses the sample variance, divisor `N − 1`.** With `N` = 2 that is twice the
  divide-by-`N` value, so `SR0` is √2 larger. That is the more demanding choice, and it
  is fixed here so that no library default can decide it. `V` is computed per path
  (section 7).
- **Moment conventions:** `γ4` is **Pearson kurtosis**, not excess kurtosis: a normal
  distribution has 3. Skewness, kurtosis and the Sharpe's standard deviation use
  **population (divide-by-`T`) moment estimators**, with no small-sample correction.
  Any library must be checked against these conventions before use.
- **The Sharpe that enters is the raw daily Sharpe,** mean over standard deviation of
  the stitched daily returns.
- **Dependence enters through `T`, not through an adjusted Sharpe.**
  - Let `Dn = 1 + 2·Σ_(k=1..5) (1 − k/6)·ρ_k`, using Bartlett weights on the first five
    autocorrelations. Then `T_eff = T / Dn` when `Dn > 1`, and `T_eff = T` when
    `Dn ≤ 1`. Negative autocorrelation therefore never earns extra observations, and a
    zero or negative `Dn` cannot produce a meaningless count.
  - **`T_eff` replaces `T` only in the `√(T − 1)` factor.** The moments — mean, standard
    deviation, skewness and kurtosis — are always estimated over the `T` actual
    observations.
  - **If `T_eff < 2`, the DSR is indeterminate**, since `√(T_eff − 1)` then gives no
    usable scale.
- **The autocorrelation estimator, frozen.**
  - `r̄` is the mean of the whole stitched series. There is no per-fold demeaning.
  - `ρ_k = Σ (r_t − r̄)(r_(t−k) − r̄) / Σ (r_t − r̄)²`.
  - The numerator sums only over pairs `(t, t − k)` **within the same fold**; the pair
    formed by one fold's last return and the next fold's first return is excluded,
    because they come from different accounts and parameter sets.
  - The denominator sums over all `T` observations.
  - There is no fold weighting and no divisor correction.
- **`V` and `N`:** each trial's Sharpe is built by these same rules, and `N` comes from
  part 2 (PR #93: merged as a proposal, not an adopted counting rule) and the trial
  register. Part 2 proposes a raw count of **6** centrally and **9** for sensitivity;
  these small counts do not establish a reliable cross-trial variance `V` or an
  effective independent count. The report must disclose that uncertainty and show
  the sensitivity result too. Any `N = 2` example here is illustrative only, not the
  current central proposal. Final counts depend on the agreed rule and full register.
- **A registered trial without a Sharpe on a path makes that path's DSR indeterminate.**
  This covers a trial that is invalid, has an indeterminate fold, or has zero variance.
  Dropping it, or lowering `N`, would quietly select out failed trials and change `SR0`.
- **Indeterminate versus conditional — an exhaustive list.**
  - A path DSR is **indeterminate** (not computed, never a pass) exactly when: the series
    has zero variance; `T_eff < 2`; any fold is indeterminate (section 5); `N < 2`; or a
    registered trial has no Sharpe on that path.
  - Otherwise it is **computed and labelled conditional**. Its known assumption
    violations — correlated trials, residual serial dependence beyond lag 5, dependent
    paths — are stated beside it and do not suppress it.
- **Threshold and role — an owner question.** Spec §6 does not include the DSR in
  acceptance or selection. I propose it stays a **reported** diagnostic, with
  "DSR ≥ 0.95" shown as a flag on a computed value, unless the owner decides it should
  gate the go/no-go run. It is **not** calibrated confidence.

## 9. Decisions this asks for, before any variant runs

1. Basis: reserve-inclusive total equity of one account (section 2).
2. Daily samples in clock time at one valuation timestamp, 00:00:00 UTC of the next
   day; each pair marked from its last valid 1m bar closing at or before it, at most 60
   minutes old, or that pair-day is masked and the day missing; the first return seeded
   from the equity before the window's first quote; risk-free rate zero; no annualised
   figure; no hourly sensitivity (section 3).
3. Returns from actual equity on every day, flat, paused and halted days included;
   zero variance is indeterminate (section 4).
4. Any missing day makes the fold indeterminate for the DSR, and any indeterminate fold
   makes the headline DSR indeterminate (section 5).
5. A fresh account per test window, the reserved run included; no return across a
   boundary (section 6).
6. An equity-weighted basket per path and fold; each path deflated against its own
   trial family; the lower path DSR (section 7).
7. The frozen DSR: formula, Pearson kurtosis, population moments, raw Sharpe, sample
   variance for `V`, and `T_eff` from within-fold Bartlett lags 1–5 that only lowers
   `T`, replaces `T` only in `√(T − 1)`, and makes the DSR indeterminate below 2. An
   exhaustive indeterminate list, otherwise a conditional value; a 0.95 flag; no Lo
   figure and no per-pair DSR.
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
  in PR #100), which sections 3 and 5 depend on only through the valid-bar and gap
  rules; the trial count (part 2, PR #93: merged as a proposal, not adopted); and the trusted
  process that writes the trial register.

## 11. Changes in revisions 2 to 5

| Finding (PR #101) | Change |
| --- | --- |
| Automated review: part 2 linked as if merged | At that revision, qualified PR #93 as proposed and unmerged. Post-merge correction: its current references now say merged as a proposal, not adopted. |
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
| Bob (rev. 2): which `T` does `T_eff` replace? | §8: only in `√(T − 1)`; moments use the actual `T` |
| Automated review (rev. 2): `T_eff` unbounded below the cap | §8: `Dn ≤ 1` gives `T`; the DSR is indeterminate if `T_eff < 2` |
| Automated review nit, Cloud: dispersion direction | §4: trials shrink by their own √*p*; the net DSR direction is not claimed |
| Cloud P1: asynchronous end-of-day valuations | §3: a common cutoff, with each pair's last valid bar at or after 23:00 UTC |
| Cloud P1: cross-trial variance divisor | §8: sample variance, `N − 1` |
| Cloud P2: effect of an indeterminate fold | §5: the headline DSR is indeterminate; the remaining folds are a labelled sensitivity only |
| Cloud P2: benchmark family per path | §7: `V_q` per path, never pooled |
| Cloud P2: hourly sensitivity undefined | §3: removed |
| Cloud P2: autocorrelation estimator | §8: stitched mean, within-fold lag products, fixed denominator |
| Bob (rev. 3): pair eligibility undefined | §7: coverage only, part 1 and PR #100; never result-dependent; published before the first run |
| Cloud P2: a trial with no Sharpe | §8: that path's DSR is indeterminate; `N` never lowered |
| Cloud P2: Lo-adjusted Sharpe undefined | §8: removed |
| Cloud P2: caveated versus indeterminate | §8: an exhaustive indeterminate list; otherwise computed and labelled conditional |
| Cloud P2: per-pair DSR family undefined | §7: per-pair return statistics only; no per-pair DSR |
| Codex audit (rev. 4): pairs valued at different times in the final hour | §3: one valuation timestamp `τ_d`; the last valid 1m bar at or before it; a 60-minute maximum mark age; beyond it the pair-day is masked and the day missing (§5); fixed now, for the owner and Codex to accept |
| Cloud P2, Codex (rev. 4): √365 is not an annual Sharpe under dependence | §3: omitted, since nothing downstream needs it; no annualised figure is reported |
| Automated review (rev. 4, required): index row still said revision 3 | Index row updated to revision 5, with the revision-4 and revision-5 points |
| Automated review nit (rev. 4): part 2 qualifier absent near §8 | At that revision, repeated the proposed/unmerged status in §8 and §10; both now reflect the subsequent merge without treating it as adoption. |
