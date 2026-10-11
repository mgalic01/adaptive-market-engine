# V3.1 replay observation convention — owner decision pending

Status: proposal only. This does not amend the reviewed specification or authorize
a historical run. No market results were consulted to choose this convention.

## Problem

Hourly OHLC gives each asset's open, high, low and close, but not their order or
whether different assets reached their extremes together. Portfolio drawdown and
recovery depend on the observation sequence. Close-only marks can miss intrabar
stress; synchronized extrema are modeled scenarios, not observed tick history.
Literal high-before-low paths also conflict with the reviewed requirement to apply
an old adverse stop before a favorable target when both are touched.

## Recommended convention

1. Register two explicitly modeled valuation scenarios: open/low/high/close and
   open/high/low/close, with synchronized phase boundaries and deterministic symbol
   ordering. Every combined component arm uses both, at both cost profiles and both
   capital scenarios. Keep independent accounts, lifetime peaks and outcomes.
2. Preserve the reviewed adverse execution precedence over valuation vertex order:
   old stops take priority over targets when both are touched. These are therefore
   conservative valuation/execution scenarios, not claims of literal price paths.
   Intrabar grid purchases cannot earn an unproven same-bar target; adverse stops
   still apply. Opening fills have separately provable timing. A stopped position
   must be removed at its executable stop/gap event before later extreme marks;
   marking already-exited inventory at a later low/high would create fictional
   liquidation. The implementation and synthetic path tests must demonstrate this.
3. Record interval identity, modeled phase and settlement boundary. Do not invent
   exact intrabar milliseconds. Funding at a boundary applies after the previous
   interval's executions and before simultaneous boundary exits or new entries.
4. Report each scenario separately. Both must satisfy the absolute risk and
   integrity gates. Display adverse return and drawdown summaries separately;
   never combine one scenario's peak with another's trough, or count scenarios as
   independent statistical trials. This is not a universal worst-case bound.
5. For cross-version comparisons, use a second, common hourly-boundary equity and
   drawdown series for every adapter. Compare return-to-drawdown on that identical
   schedule. Also retain native baseline diagnostics, clearly labeled. Keep the
   combined system's 30% risk gate on its scenario-local intrabar observations.
   If a baseline cannot supply the common observations, comparison is incomplete,
   never a pass. Frozen baseline trading decisions and implementations stay intact.

## Cost and limitation

### Additional decision: same-time settlement observations

Bob's review of PR269 found that funding and fills can produce several different
equity marks at the same timestamp. Record IDs identify those marks but cannot
decide which economic boundary a daily return or utilization interval represents.
The current report deliberately treats such samples as incomplete. Dropping marks,
moving their timestamps or choosing a favorable mark is not a permitted workaround.

The proposed convention must therefore also declare, before registration:

- Interior daily samples: the completed boundary state after ordered funding,
  protective reductions and opening fills, before the next intrabar movement.
- Opening sample: the initial account before the window's first execution costs;
  those costs belong to the first return interval.
- Terminal sample: the final completed in-window interval's close and its execution
  obligations, excluding funding or new entries belonging to the next window.
  It needs an explicit interval-end identity; it must not be fabricated by renaming
  an earlier event or by reading reserved-window prices.
- Utilization: the capital state after all settlements at each interval start,
  carried only until the next actual observation. Every intervening event remains
  in the lifetime drawdown evidence, including zero-duration same-time changes.
  Same-time changes do not create positive-duration utilization intervals; the
  current interval interface rejects zero-length intervals.
- The approved phase policy and adapter conformance must be pinned in registration
  and bound into report evidence. Baselines require the same declared economic
  boundaries; native output timestamps alone are insufficient proof.

This addition is still a proposal requiring the owner's decision. It has not been
implemented or used to permit complete reports. Current registration rejects an
endpoint at the reserved boundary because the current engine cannot emit that
event; an interval-end adapter needs separate reviewed implementation after the
observation contract is approved. The downside is additional adapter complexity
and another source of incomparable or incomplete results if evidence is absent.

### Modeling cost

Two scenarios approximately double the combined-arm execution work. Adverse
precedence can penalize returns relative to an actual favorable price path. The
common-boundary comparison is fairer across adapters but can omit intrabar stress,
which is why the separate intrabar absolute-risk gate remains mandatory. Neither
observation convention proves a real-world drawdown ceiling or profitability.

Alternative: defer this convention and retain a blocked replay registration until
a different comparable execution/observation model is agreed. Engineering of the
account, decision records, controls and dashboard can continue independently.
