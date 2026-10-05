# V2 market structure: pre-registration

- **Date:** 2026-10-05. **Written by:** Claude. **Decided by:** the owner, decisions
  D19, D20 and D21 of the [strategy audit](reviews/2026-09-29-claude-strategy-audit.md),
  and the zone width of 2026-10-05 (rule 2).
- **What it does:** writes down and freezes every rule and setting of V2, the
  market-structure layer, before any V2 result counts (D20: "Write down and pin every V2
  rule and setting now. V2 results count only after that.").
- **Status:** V2 is exploratory until this document is merged. This document chooses
  nothing by looking at results: no V2 run was made for it, every setting is the value
  already in the code except the zone width, which the owner set without seeing any
  result, and the one new rule, sell-at-resistance, follows the owner's own description
  (D19). One rule already in the code was chosen after looking at results,
  the RANGE-only rule; it is kept and disclosed [below](#the-range-only-rule). The only
  V2 runs behind this change are code checks on synthetic random walks.
- **Details D19 leaves open** were decided by Claude on 2026-10-05 from the owner's
  words and from risk logic, and the synthetic check results played no part: the
  nearest known zone on any timeframe, at any distance, always caps a target (rule 9);
  only a zone within its timeframe's radius raises one, and a timeframe without a
  positive radius raises none (rule 3); a skipped level enlarges no other order (rule
  14, step 5).

## What V2 is

V2 is everything the `--structure` switch (`SimulationPolicy.structure`) turns on. It is
off by default, and with it off the engine is V0, byte for byte. With it on:

1. **A sixth vote** in the regime classifier, the multi-timeframe structure alignment.
2. **Sell targets just below resistance** (D19): each buy level's sell sits just below
   the nearest resistance above it. It replaces the earlier FTA cap on grid levels,
   which is removed (D19 in the audit explains why the cap was a hidden entry veto).

A `--structure` run's ungated rows stay the ungated V0 baseline. Its results are
labelled `price-only-v1+structure-v2`; earlier V2 results carry `+structure-v1` or no
label at all.

## What V2 results can count for

- **Exploratory until merged.** No V2 result produced before this document is merged is
  evidence (see [prior trials](#prior-v2-trials-disclosed-their-results-do-not-count)).
- **Not part of v1.** V2 is not a v1 variant and plays no part in v1's selection, so
  v1's family and its `N_family`
  ([spec v1 §6, C7](EXPERIMENT_SPEC_V1.md#6-acceptance-and-selection-owner-decisions-2026-09-24))
  are unchanged.
- **Spec v2.** V2 will be folded into the post-v1 spec v2, which is to set how V2 is
  judged and counted. Sell-at-resistance enters it as one registered trial (D19: "A new
  V2 grid design, registered as a trial").

## Frozen rules and settings

| # | Rule or setting | Frozen value | In the code | Source |
| --- | --- | --- | --- | --- |
| 1 | Swing points | strict: higher (lower) than **3** bars on each side (`swing_n`) | `StructureParams`, `detect_swing_highs/lows` | #147 (Bob); kept strict by **D21**, below |
| 2 | Zone merge distance | **1.0** ATR (`merge_atr`): in price order, a swing joins a zone if it lies less than 1.0 ATR above the zone's lowest swing, and otherwise starts the next zone; a zone's price is the mean of its swings | `StructureParams`, `cluster_into_zones` | **the owner**, 2026-10-05, following his 29 September record: "Cluster nearby swing points (within one ATR) into zones" |
| 3 | Resistance search radius | **5.0** ATR of that timeframe (`max_distance_atr`). For a sell target it limits **only raising**: a zone within it may raise a target; a zone beyond it, or on a timeframe whose radius is not positive (a zero ATR), can only lower one | `StructureParams`, `find_fta`, `nearest_resistance` | #147; its use for sell targets: Claude, 2026-10-05 |
| 4 | Swings needed for a trend | **2** highs and 2 lows (`min_swings`) | `StructureParams`, `classify_structural_trend` | #147 |
| 5 | Structure ATR | simple mean of the true range over the last **14** bars of that timeframe (`atr_period`) | `StructureParams`, `compute_atr` | #147 |
| 6 | Zone recency weight | **0.5** (`zone_recency_weight`); zone strength is read by no decision | `StructureParams`, `cluster_into_zones` | #147 |
| 7 | Hourly bars read | the pair's last **500** completed hourly candles | `features._STRUCTURE_HOURLY_WINDOW` | #151 |
| 8 | Daily and weekly bars read | every daily bar closed at or before the decision minute (open + 1 day ≤ minute, variant A's rule); **no weekly bars** | `FeatureEngine._completed_days`, `_structure_features` | #160 (the lookahead fix); weekly never loaded since #151 |
| 9 | Across timeframes | the **nearest** known zone above the level on **any** timeframe, at **any** distance; no timeframe is preferred | `nearest_resistance` | Claude, 2026-10-05, from D19's "nearest resistance zone above the buy price" and "never set a target above a strong resistance" |
| 10 | Timeframe weights of the alignment | hourly **0.15**, daily **0.35**, weekly **0.50**, renormalised over the timeframes present: without weekly bars, daily **0.70** and hourly **0.30** | `analyse_multi_timeframe` | #147 |
| 11 | Regime vote | trend **0.25**, breadth 0.20, momentum 0.15, volatility health 0.15, liquidity health 0.15, structure alignment **0.10**; the dispersion averages all six | `RegimeClassifier._STRUCTURE_WEIGHTS` | #150 |
| 12 | Target buffer | **0.999** of the resistance price, then floored to the tick | `runner.RESISTANCE_TARGET` | #148 (Bob); D19 |
| 13 | Market condition | **RANGE only**: in any other regime the targets stay V0's | `PaperSimulator._open_grid` | #151, below |
| 14 | Sell-at-resistance | the rule below; every order sized as in V0 | `PaperSimulator._open_grid`, `_below_resistance`, `nearest_resistance` | **D19**; sizing: Claude, 2026-10-05 |
| 15 | Results label | `price-only-v1+structure-v2` | `features.STRUCTURE_FEATURE_VERSION` | this document |

Everything else V2 uses is V0's, unchanged: the grid's levels and spacing, the 3× cost
multiple, the risk rules and the profit vault (`config/default.toml`), and the fees and
slippage of the dataset spec. V2 adds nothing to `config/default.toml`, since that
file's hash is part of every result's identity.

The code merged zones within 0.5 ATR until the owner's decision of 2026-10-05.

**The 0.999 buffer** has a thin source: it was not derived from data, and #148 calls it
"a sensible default based on the project's fee scale". It reproduces the owner's example
exactly (resistance $0.355, target $0.354).

## The sell-at-resistance rule (D19)

The owner's words, 29 September: "the sell target should be placed just below the
nearest resistance zone above the buy price. If the nearest resistance is at $0.355 and
the geometric level is at $0.342, the FTA-aware target is $0.354 (just below $0.355). If
no resistance is within range, fall back to the geometric level. Never set a target
above a strong resistance without the bot knowing it is trying to break through."

When a grid opens under `--structure` and the market is RANGE (rule 13), the grid's buy
levels and spacing are exactly V0's. Each buy level `low` then gets its sell target:

1. **The nearest resistance.** Z is the nearest resistance zone strictly above `low` on
   any timeframe, at any distance: every known zone counts (rule 9). Zone strength is
   not used: the nearest zone of any strength counts. Only resistance zones, from swing
   highs, count: a support zone above a buy level is not resistance, and a resistance
   zone below the current price still counts for the buy levels beneath it, since a
   zone that price falls back through acts as resistance on the rebound.
2. **No zone above:** the target is the geometric next level, as in V0.
3. **Z in reach,** that is within its own timeframe's radius (rule 3: the radius is
   positive and Z − low ≤ radius): the target is Z × 0.999, floored to the tick, whether
   that is above or below the geometric level (raised or lowered).
4. **Z out of reach,** beyond its radius or on a timeframe whose radius is not
   positive: the geometric level stands, unless it would sit at or above Z × 0.999; then
   the target is lowered to Z × 0.999, floored to the tick. So no target ever sits at or
   above a known zone, and a target is raised to a zone only when that zone is in reach.
   A zero radius never raises, but its zones still cap. (`find_fta`, which reports the
   FTA at fair value, instead searches without limit at a zero ATR.)
5. **Costs.** A target a zone moved (raised, lowered or capped) must clear the
   spacing-versus-cost test the engine applies to every grid: (target − low) / low ≥
   round-trip cost × 3, the round-trip cost being 2 × (fee + slippage) plus the quoted
   spread. If it does not, the level gets no buy order: it may not sit higher and
   cannot profit lower. A geometric target left standing keeps V0's rule, under which a
   pair that cannot clear costs refuses the whole grid. Every order is
   sized exactly as in V0, with every candidate buy level counted: the grid's budget
   (80% of unprotected cash) divided by the number of buy levels before any is skipped.
   A skipped level's share stays unspent, so a skip never enlarges, or adds risk to, the
   orders that remain. If no level is left, no grid opens, with the reason "no buy level
   can sell below resistance at … and clear costs", naming the zones.
6. **Fixed at grid open, from completed bars only.** The zones come from the same
   completed candles as every other structure input (rules 7 and 8). A target does not
   move afterwards: the sell placed when the buy fills, and every re-entry of that
   level, keep it.
7. **Grid bounds.** The grid's upper bound is the higher of its top level and the
   highest sell target placed, so a target raised above the top level stays inside the
   range the outside-range clock watches. The lower bound is the bottom level.

## The RANGE-only rule

Sell targets follow resistance only when the regime is RANGE. Its justification is the
owner's source idea: targeting the first trouble area is for a ranging, consolidating
market ("This works especially in consolidation", in the
[owner's requirement record](reviews/2026-09-29-owner-market-structure-perception.md),
which relays the idea).

**Disclosure.** The rule was first chosen after looking at development results: #151
added it to the old FTA cap following Bob's 2026-09-30 V2 comparison (§8.4), which
blamed the cap for a loss in trending windows. Those results were later found invalid:
they read future daily bars, and the structure vote was silently zeroed (see below).
The rule is kept, with the justification above, and registered here as it stands; that
it was chosen after looking is part of the record.

## Swing points (D21)

The owner's decision: "swing highs stay strict, 'higher than N bars on each side' as in
your own definition, and this gets written down. Only flat tops within 3 bars are
missed."

A bar is a swing high if its high is strictly higher than the highs of the 3 bars
before it and the 3 bars after it; a swing low likewise, with lows. A tie is not a
swing. So two equal highs within 3 bars of each other, a flat top or a double top that
close, give no swing and no resistance zone; equal highs further apart are each a swing,
and they merge into one zone. Lows behave the same. The first and last 3 bars of a
series are never swings: the last 3 cannot be confirmed yet.

## Prior V2 trials (disclosed; their results do not count)

Every V2 run inspected before this document is a prior trial. Its results do not count
and may not be used for any decision:

- **Bob's V2 comparison of 2026-09-30**
  ([report](reviews/2026-09-30-bob-v2-backtest-comparison.md), task report PR #157):
  structure features with the FTA cap on four development windows. It read future daily
  bars, and the structure alignment never reached the classifier (its finding F1). The
  RANGE-only rule was chosen from it.
- **Bob's "V2 corrected baseline" of 2026-10-01** (PR #156,
  `docs/reviews/2026-10-01-bob-v2-corrected-baseline.md` on its branch): V2 and V2 with
  variant A on long-bull-bear-2022 and long-recovery-2023-2024. It read future daily
  bars.
- **Every other V0 or V2 backtest on main from #151 until #160** on a spec with daily
  bars (practice-2022, verify-2024h1, long-bull-bear-2022, long-recovery-2023-2024): the
  invalid lookahead runs.
- **The V0 rows changed by the vote:** every V0 row run from #150 until #160 used V2's
  six-signal vote and, from #151, the FTA cap under V0's label, so it was a V2 trial,
  not a V0 result.
- **Any other V2 run made before this document is merged,** published or not.

The V2 runs in the strategy audit's code checks (#160) and in this change's byte-identity
check ran on synthetic, fixed-seed random walks to test the code. They are not trials.

## Changing a frozen rule

[`tests/test_structure_preregistration.py`](../tests/test_structure_preregistration.py)
pins every value above and the owner's example, so a change fails it;
`SellAtResistanceTests` in `tests/test_backtest_replay.py` pins the behaviour of rules
3, 8, 9 and 12–14. A change to any frozen rule or setting is a re-registration, never a
fix: amend this document first, dated, with what changed and why; bump
`STRUCTURE_FEATURE_VERSION`; then update the tests. Results under the old label stay
reported, and a change made after V2 results have been seen is one more trial in spec
v2's count.
