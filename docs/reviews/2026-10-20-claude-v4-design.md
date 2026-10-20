# Claude: V4 design, review round 2 answered

Index: V4.0 design spec (PR #289), round 2. Addresses Codex's ten new P1 findings and Bob's six concerns at `7bce5b6`. Two parts were removed because neither could change a result: the two intrabar price paths (60 cells become 36) and the margin cushion. The rest makes rules exact. No owner decision changes; the owner was told in chat.

Author: Claude Code (session f7f187df), 2026-10-20 UTC. Branch `claude/v4-design`.
Documents only: the spec, `docs/START_HERE.md` §1 and this file. No code, no data.

## What I checked

- Each finding against the spec text at `7bce5b6` and against V3's spec
  (`docs/EXPERIMENT_SPEC_V3.md`): §2 funding schedules and excluded months, §4 lookbacks,
  §5 sizing and filters, §6 order of events, §8 the hold benchmark and the terminal mark.
- Bob's arithmetic on the margin cushion. With maintenance at 1% of futures notional,
  equity over maintenance is below 3 only when futures notional is above 33 x equity. The
  3x ceiling cuts that at the same mark, so the cushion can never decide anything. Bob is
  right, and the rule is dropped rather than redefined.
- Whether the price paths matter. V4 places no order inside an hour. With liquidation
  checked at all adverse extremes at once, as V3 §6 does, the high-first and low-first
  paths give identical results, so they are dropped.

## Codex's findings

| Thread | Finding | Resolution |
|---|---|---|
| 4320263378 | `v3_as_built` must keep V3's terminal mark | Agreed. `v3_as_built` keeps V3's ending: a terminal mark, censored lifecycles, no exit fill. Condition 2 compares both arms on hour-open marks up to 2024-12-31 23:00, with no synthetic close for either. |
| 4320263381 | Band test with two venue legs | Agreed. `current` is the signed notional over both venues at their own opens. If any venue the order needs lacks the fill-hour bar, the coin's whole order is deferred under V3's masked rules. |
| 4320263384 | Per-coin spot allocation | Agreed. There is now an exact per-coin rule. Spot-only coins come first; if capacity is short, they are scaled by one factor and coins with a perpetual go fully on futures. Otherwise coins with a perpetual share the remaining spot capacity pro rata. |
| 4320263389 | Fetch minimum and maximum quantity | Agreed. The filters are `MARKET_LOT_SIZE`, else `LOT_SIZE`, per symbol and venue, pinned. Delisted symbols get inferred, labelled filters. |
| 4320263393 | Terminal dust | Agreed. Dust still unsellable at the window end stays marked, censored as "window end (dust)", with no synthetic sale. |
| 4320263400 | Downtrend windows across missing days | Agreed. Every lookback counts available daily bars (V3 §4), and "10 days earlier" is 10 bars earlier. A day without a bar adds no observation. |
| 4320263407 | One global start boundary | Agreed. The window starts at 00:00 UTC of the first month whose selection has at least one eligible candidate. Every arm starts there, and a short universe is permitted. |
| 4320263416 | Funding schedule validation | Agreed. Each month is validated as in V3 §2: strictly increasing, no duplicates, inside the month, spaced by the file's interval, else 8 h. An incomplete or missing month removes the perpetual for that month, and held futures get a target of 0 at its first decision. The whole-month look-ahead is disclosed, as in V3. |
| 4320263421 | Perpetual delisted while spot trades | Agreed. The 7-day dead-market rule applies to each held venue on its own, at that venue's last close with the 10% penalty. No funding is charged without a record. |
| 4320263423 | Cash-feasible hold rebalances | Agreed. The hold arms use V3 §8's spot rules: targets of 0.99 x equity / n, sells before buys, buys cut to the cash available, fee included, and orders under the filters skipped and recorded. |

## Bob's concerns

1. **Margin cushion:** dropped (above). Gross exposure is now defined as spot plus
   futures notional over equity. V3 §6 counts futures only, and V4 says so.
2. **Order of events:** now exactly V3 §6, with no additions. The leverage check runs at
   the post-fill mark and after each funding event, and delevering fills at the open.
   Liquidation is checked at all adverse extremes at once, and an excursion inside an hour
   is not a breach. The per-extreme cuts are removed.
3. **Pass rule against `summary.json`:** each cell now stores its open mark for every
   hour, with a "complete" flag, plus final equity after the window-end close. The
   verdict derives the common hours of any pair of arms. Condition 1 appends both arms'
   final equity after the close; condition 2 has no close for either.
4. **`v3_as_built` ending:** keeps V3's terminal mark (Codex 4320263378).
5. **Dead and exiting markets:** a dead-market rule per venue (Codex 4320263421). A coin
   leaving the top 10 gets target 0 at the same 00:00 decision, because the selection is
   made first, and fills out at the next hour's open.
6. **Smaller gaps:**
   - hourly spot is fetched over each entering coin's whole history;
   - spot-only coins have an exact allocation (Codex 4320263384);
   - a liquidation or accounting failure in any `v4_main` cell means fail, whatever else is
     missing;
   - `docs/START_HERE.md` §1 now notes the owner's V4 exception (v4-d03);
   - this file carries the index entry.

## Effect on the step-2 plan

The universe-and-data plan on `claude/v4-step2-data` gets an amendment on that branch
before its affected tasks run. It covers the minimum and maximum quantity filters,
funding-month validation, the whole-history hourly fetch, the short universe and the start
boundary. Tasks 1 and 2 (config and verified archive fetch) are unaffected.
