# Claude: V4 design, review round 2 answered

Index: V4.0 design spec (PR #289), all review rounds on 2026-10-20 (Codex and Bob, from `7bce5b6` to the final head). Final state: 36 cells (the two intrabar price paths removed); the margin cushion kept, defined on V3.1's futures backing with spot excluded; agreement between the speeds sets the size; V3's masking, no-bar and funding rules adopted; exact allocation, cash clip and cell outcomes. No owner decision changes; the owner was told in chat.

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
| 4320263389 | Fetch minimum and maximum quantity | Agreed. The minimum and maximum quantity are the stricter of `LOT_SIZE` and `MARKET_LOT_SIZE`, as V3.1's venue rules read them, per symbol and venue, pinned. Delisted symbols get inferred, labelled filters. |
| 4320263393 | Terminal dust | Agreed. Dust still unsellable at the window end stays marked, censored as "window end (dust)", with no synthetic sale. |
| 4320263400 | Downtrend windows across missing days | Agreed. Every lookback counts available daily bars (V3 §4), and "10 days earlier" is 10 bars earlier. A day without a bar adds no observation. |
| 4320263407 | One global start boundary | Agreed. The window starts at 00:00 UTC of the first month whose selection has at least one eligible candidate. Every arm starts there, and a short universe is permitted. |
| 4320263416 | Funding schedule validation | Agreed. Each month is validated with V3 §2's exact schedule rule: one interval I dividing 24, slots at 00:00 + k x I, each record within 60 s after its slot, one record per slot. An incomplete or missing month removes the perpetual for that month. Held futures close at the decision of the previous month's last day, filling at 01:00, so no funding of that month is charged. The look-ahead is disclosed, as in V3. |
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

## Codex at `9b031f3` (five more findings)

| Thread | Finding | Resolution |
|---|---|---|
| 4320404162 (P1) | A delisted candidate with no bars in the 30-day volume window | Agreed. A symbol with no daily bar in the 7 UTC days before the selection is not eligible: a dead market, by the same 7-day rule as "Safety". Every ranked candidate therefore has a volume observation. |
| 4320404191 (P1) | The pre-registration timing run must not use 2025+ data | Agreed. The timing run uses synthetic data of the real packs' size, or real data before 2025-01 only. It reports times, memory and sizes, never performance. v4-d03 opens 2025+ data for preparation and the registered run, not for trials. |
| 4320404167 (P2) | Dead-market close against unsellable dust | The dead-market close is synthetic and ignores the filters, so dust closes with the rest of the leg at the penalised price. |
| 4320404172 (P2) | Return / drawdown at zero drawdown | V3 §8's Calmar convention: +infinity for a positive return, 0 otherwise. +infinity is greater than every finite value and not greater than itself. |
| 4320404185 (P2) | Accounting failures visible in summaries | Every cell writes a `summary.json` with an `outcome`: `complete`, `liquidated`, `accounting_failure` (the failed identity, hour and values) or `engine_error`. The verdict maps them to fail, fail and incomplete. |

## Codex at `db211ad` (five more findings)

| Thread | Finding | Resolution |
|---|---|---|
| 4320470221 (P1) | Spot capacity ignores dust and band-kept legs; no cash clip | Band-kept legs (S_K, F_K) and dust (D) are fixed holdings that reduce the room: `R = 0.98 x equity - S_K - D - F_K/3`. The split uses R. Increases then take V3's cash clip: alphabetical after reductions, cut to free cash with fee and initial margin, and skipped below the filters. |
| 4320470226 (P1) | Filters for delisted symbols are not determined by decimals | A fixed fallback, pinned and labelled `inferred`: tick and step from the most decimals after trailing zeros are dropped, minimum quantity = step, maximum 9,000,000,000, minimum notional 5 USDT. It is disclosed under known limitations. |
| 4320470229 (P2) | Dead-market close in the hourly order | After 168 consecutive hours without a bar, the leg closes at the next hour's open time as that hour's first event, before V3's open mark. Funding at or after that instant is not charged on it. |
| 4320470232 (P1) | Hourly defects to masks | V3's rules re-implemented: spec v1 §5 rule 1's repairing reader on both venues, repaired and missing hours masked, and a daily bar needing 20 of 24 unmasked hours. V3's 17% month exclusion is not adopted, because with delisted coins it would foresee delistings. |
| 4320470239 (P1) | Deferred funding-month exit could fall inside the month | V3's fallback applies: the next unmasked perpetual hour before the month starts. If there is none, the leg closes synthetically at the month's 00:00, before its funding, at the last close with the 10% penalty. V3 would have invalidated the run. Funding slots are judged only between the perpetual's first and last records, so a delisting month is not foreseen. |

## Bob at `db211ad` (five more concerns)

1. **Unrestorable limit:** V3's factor k′ is restated with V4's 2.7 target and spot counted. Masked legs and dust are untradable gross. If no leg can trade, or gross still exceeds 3.0 after a cut, or a required fill cannot be made, the outcome is `limit_unrestorable`, which fails, as V3 §8 treats an invalid run.
2. **V3 §2's integrity rules:** these were adopted explicitly at `af65366`, before this review was posted: the repairing reader, hour masks and the 20-of-24 day rule. The 17% month rule is not adopted (it would foresee delistings), and there is no spot-month exclusion with it. Now also: the funding-month close is the decision at 00:00 on the previous month's last day, made after the close of the day before; it overrides the no-bar rule; and futures return from the first decision whose fill falls after the month.
3. **Band-kept legs and cash shortfalls:** fixed holdings and the cash clip were added at `af65366`. The liquidation check now marks every leg, spot included, at its adverse extreme.
4. **Volatility scaling undid agreement sizing.** Bob is right, and this is a real defect: scaling the raw weights to the 40% target cancels L and S whenever every coin shares the same |s|. Step 2 now takes its scale from the full-strength book, `c = 0.40 / sqrt(full' Sigma full)` with `full = sign(s) / sigma`, and applies it to `s / sigma`. Each coin's weight is |s| times its full-strength weight, as the design describes. The owner is told, since this lowers average exposure when the speeds disagree.
5. **Dead-market booking hour:** fixed at `af65366`. It counts 168 hours, masked hours included, and the close is the next hour's first event.

## Bob at `8f59d3d`: NO ISSUES. Codex at `8f59d3d` (six more findings)

| Thread | Finding | Resolution |
|---|---|---|
| 4320534574 (P1) | Funding span anchored to the file being judged | The expected slots now fall within the perpetual's trading span from its klines: at or after its first hourly bar's open, at or before its last bar's close, over its whole history. A file that loses its first or last records still fails. |
| 4320534580 (P2) | Zero sigma or zero portfolio estimate | As in V3, sigma = 0 gives a raw weight of 0, and so `full` is 0. If `full' Sigma full` is 0, every target is 0. |
| 4320534588 (P1) | START_HERE §0 still names V3 as the scope | A dated scope note makes V4 the current build scope. "v3" in the goal test reads as V4, v4-d03 is stated, and the V3 text is kept as history. |
| 4320534593 (P2) | Terminal state of a cell that stops early | As V3 §8 does: no later event and no closing fill. Every position, dust included, is marked at the stopping check's prices, with masked legs at carried marks. Lifecycles are censored with the reason. That mark is final equity. |
| 4320534596 (P1) | Missing daily bar at a decision | V3 §4's no-bar rule: the coin keeps its signal, takes no order, and keeps any deferred order pending; the others are decided as usual. A universe exit and the funding-month close override it. |
| 4320534598 (P1) | Deferral against the coupled allocation | Deferrals are decided first, from the venues each coin needs (spot if it holds spot or is long; the perpetual if it holds futures, is short, or is long with an eligible perpetual). Deferred, no-bar and band-kept coins keep their legs as fixed holdings, and the allocation runs once over the rest. |

## Bob at `6384e06`: NO ISSUES. Codex at `6384e06` (four more findings)

| Thread | Finding | Resolution |
|---|---|---|
| 4320644217 (P1) | Spot inventory must not back futures | Agreed. V4 now uses V3.1's `futures_margin` model: backing is free cash plus futures collateral plus futures unrealised P&L, with spot excluded, and maintenance is 1% of futures notional. Liquidation happens when backing is at or below maintenance, with futures legs at their adverse extremes. **This supersedes round 2's removal of the margin cushion.** With spot excluded, the ratio can fall below 3 after futures losses while the 3x ceiling, which counts equity, does not act. So the owner-approved cushion returns on this backing: admission keeps the ratio at least 4, and a ratio below 3 cuts tradable futures pro rata back to 4. It runs just before the ceiling, at the ceiling's check points. |
| 4320644221 (P2) | S_K and D overlap | S_K now excludes dust, and D holds every coin's dust, so nothing is reserved twice. |
| 4320644229 (P2) | Lifecycles for dual-venue longs | A lifecycle is per coin and side, from the signed position over both venues leaving zero to its return to zero or a sign change. A venue transfer stays inside it, with per-venue fills, fees and funding. Best unrealized profit and give-back are measured on the combined position. |
| 4320644235 (P1) | Universe eligibility needs usable hourly spot | A candidate with no unmasked hourly spot bar in the 168 hours before the selection is skipped. The universe takes the first 10 that pass, down to rank 20, so the data step fetches hourly spot for every symbol ever in a top 20. A short universe is permitted if fewer pass. |

## Bob at `f7a9cae`: NO ISSUES. Codex at `f7a9cae` (ten more findings)

| Thread | Finding | Resolution |
|---|---|---|
| 4320748019 (P1) | Monthly eligibility vs a missing bar | Eligibility is the trading span plus a complete funding month. A missing bar at one decision or fill is handled only by deferral. |
| 4320748027 (P1) | Unrestorable cushion | A ratio below 3 with no tradable futures leg, or still below 3 after a cut, ends the cell `limit_unrestorable` with reason `margin_cushion`. |
| 4320748036 (P2) | Lifecycle across a full transfer | The zero and sign tests run after a whole batch of fills, so a full spot-to-futures move stays one lifecycle. |
| 4320748037 (P1) | Dust against a coin's target | A trading coin's dust is part of its own spot leg. Its futures target nets the signed position, dust included, to the target. D holds only the fixed coins' dust. |
| 4320748041 (P1) | Spot buys could erode futures backing | Free cash is the smaller of USDT minus initial margin, and backing minus 4 x maintenance. No increase takes the ratio below 4, and none is made below it. This replaces the separate admission rule. |
| 4320748045 (P2) | Costs of synthetic closes | The penalty replaces slippage, and the venue's normal fee is charged on the penalised notional, for both dead-market and funding-month closes. |
| 4320748049 (P1) | Mandatory futures exit blocked by a missing spot bar | A universe exit or funding-month exit closes each leg on its own venue's bar. The replacement spot buy defers on its own. |
| 4320748052 (P1) | Solvency at the penalised price | The liquidation check runs with the leg at its penalised price before the close is booked. Equity at or below zero after any close also means liquidation. |
| 4320748058 (P2) | Empty hold universe | All targets are 0: sell what can be sold, hold cash and dust, and no division by zero. |
| 4320748062 (P1) | Daily duplicates | A duplicate or out-of-order daily row removes both its day and the last kept day, as the reader masks both. |

Also from the step-2 task review: a base that is exactly UP, DOWN, BULL or BEAR is a leveraged token. BULLUSDT and BEARUSDT, the BTC members of that family, are in the pinned spot snapshot. No real coin has such a base.

## Bob at `50ed617` (three concerns) and Codex at `50ed617` (three P2, no P1)

- **The Index line was stale** (Bob 1, Codex 4320800082). It now describes the file's final state, including that the margin cushion is kept on V3.1's backing. The round-2 sections below it stay as history.
- **`margin_cushion` in the outcome schema** (Bob 2, Codex 4320800079). Reports now lists all three `limit_unrestorable` reasons: `ceiling`, `margin_cushion` and `required_fill`.
- **A mandatory-exit leg in the fixed holdings** (Bob 3). A leg that a mandatory exit closes this hour counts as 0, since it fills in the same batch's reductions. The coin's other, deferred leg stays fixed.
- **Venue order inside the cash clip** (Codex 4320800073). Increases go alphabetically by symbol, and within one coin the spot leg goes before the futures leg, consistent with longs on spot first.

## Bob at `c9d41cb`: NO ISSUES. Codex at `c9d41cb` (two P1)

- **Simultaneous synthetic closes** (4320853545). All synthetic closes due at one instant form one batch. The liquidation check runs once, with every closing leg at its penalised price at the same time, and then all are booked together. The outcome no longer depends on processing order.
- **Stale deferred orders at a dead-market close** (4320853551). The close cancels any deferred order the coin has. Re-entry needs a later daily decision whose decision day has a bar.

## Bob at `5ade767`: NO ISSUES. Codex at `5ade767` (three P1, one P2)

- **Early-stop summaries** (4320903426). The outcome is read first and takes precedence. In a `liquidated` or `limit_unrestorable` summary, equity at 2025-01-01 (if the stop came earlier) and the post-close final equity are null. The final equity is the stop's mark. These nulls never make the cell incomplete.
- **Dust in the allocation** (4320903428). Every coin's dust, trading or not, is fixed spot in D. Each trading coin's target is reduced by its own dust first (`residual = target - dust`), and the split runs on residuals. The futures notional offsetting dust is inside G_E or G_S, and nothing is counted twice. This replaces round 7's "dust is part of its own spot leg" wording.
- **Point-in-time listing** (4320903432). A perpetual is listed at a decision if its first bar is at or before it and it has had a bar within the last 168 hours. The eventual last kline is never consulted.
- **Replacement buy after the futures exit** (4320903436). The spot buy that goes with a funding-month exit waits for that futures close: it is placed at the first hour at or after the close's fill that has a spot bar.
