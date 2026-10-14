# V3.1 exact registration: proposal for owner review

Status: draft by Claude, 2026-10-11, updated 2026-10-12. **The owner approved the window, the
FX source, all nine V1 variants and the cost profiles on 2026-10-12** and added a reported-only
window W0 (2020-03-01 onward, eight coins; see the source inventory). Updated after the conformance fixes,
the owner's decisions of 2026-10-11 and 2026-10-12, and the minute-bar fetch. **This is
not a registration and does not authorize a run.** It proposes the finite trial set, its
inputs and its pins for the owner to approve or change. After approval:
1. the data are prepared and pinned;
2. the exact registration is committed to the trial register and reviewed;
3. only then is a separate owner go requested for one historical execution.

No market data was read to draft this beyond the committed dataset manifests. Nothing at
or after 2025-01-01 is read.

## 1. Window

One window, **W1 = 2021-07-01 00:00 UTC to 2025-01-01 00:00 UTC**: 3.5 years, ending
exactly at the reserved boundary. The replay supports that end without reading past it.

- **Every coin has warm-up history.** All ten coins have eligible futures and funding
  months by 2020-10 in `config/datasets/v3-20261009/inventory.manifest.json` (SOL is the
  last). Each therefore has at least eight months of history for the assessment's
  warm-ups.
- **W1 is exactly V3's own out-of-sample period.** BTCUSDT's first portfolio month is
  2020-01, so V3's first test quarter is 2021-Q3. The V3 selector baseline has frozen
  picks for the whole window; an earlier window would leave it incomplete.
- **This is development evidence.** 2019-2024 have been seen in earlier experiments, as
  the design states. A V3.1 pass would still need the reserved-window step and, before
  any real money, a forward paper-trading period on live prices.

## 2. Universe

- **V3.1 components, V3 baselines and the hold:** BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC,
  LINK, TRX, the V3 universe. The hindsight in choosing today's large coins is disclosed,
  as in V3.
- **V0-V2 grids and comparator D:** their own frozen traded pairs, BTC, ETH and XRP. Their
  different universe is disclosed; capital and dates match.

## 3. Inputs and their sources

| Input | Coins | Source | Status |
| --- | --- | --- | --- |
| Futures 1h klines, funding, futures filters | 10 | `v3-20261009` inventory (Binance public archives, checksummed) | inventory committed; final manifest pins pending |
| SOL funding 2022-11 | SOL | the published archive month (excluded from the inventory for a cadence change) | register as published; it pins the `interval_hours` convention (section 7) |
| Spot 1h klines | 9 | `full-range-2017-2024` manifest | committed |
| Spot 1h klines | ADA | `v3-20261009` inventory (79 eligible spot months) | inventory committed |
| Spot daily bars | 10 | rebuilt inside the replay from the registered spot 1h bars with V3's day rule (at least 20 of 24 usable hours) | implemented |
| Spot 1m klines | BTC, ETH, XRP | `full-range-2017-2024` manifest | committed |
| Spot 1m klines | ADA, BNB, DOGE, LINK, LTC, SOL, TRX | `v3-1-minute-bars-2021-2024` manifest `589b9a8c493240e24f24900e8c9b81f43a4330bd652c4c8ebf628c7c5403444d` (Bob's run, PRs #273/#274) | committed on `main` |
| Spot and futures filters | 10 | saved present-day snapshots | disclosed as not historical, on every report |

**Known gaps inside W1,** from the committed inventory:
- about ten masked spot hours on every coin (2021-08, 2021-09, 2021-12, 2023-03);
- 120 masked futures hours on LTC, SOL, TRX and XRP (2022-02, 2022-04);
- about 0.025% of one-minute bars per coin.

Owner decision 2026-10-11: hours missing from any registered source are skipped for every
arm alike and listed. Owner decision 2026-10-12: positions without a price follow the
protective rule (no new trades while blind; close the blind position when prices return).

## 4. Costs, capital and scenarios

- **Base cost profile:**
  - spot: fee 0.10% and slippage 0.05% per side;
  - futures: fee 0.05% and slippage 0.05% per side (V3's frozen values);
  - conservative round-trip bounds for admission: 0.40% spot, 0.25% futures.
- **Doubled profile:** both rates doubled. Frozen baselines use their own declared
  doubled-cost settings:
  - V3: `cost_multiple=2`;
  - V0-V2 and D: maker, taker and slippage doubled, with the fill trigger kept at base
    slippage so only costs change, and the spread unchanged.
- **Capitals:**
  - research: 10,000 USDT;
  - owner-small: EUR 100, converted at a pinned EUR/USDT rate. **Owner choice, the FX
    pin:** either the ECB euro reference rate for the last 2024 business day (about 1.04
    USD per EUR; the exact figure is copied from the ECB publication at registration, with
    USDT taken at par), or a round 1.08.
  - *Note, 2026-10-14: the owner replaced both with three USDT capitals, `research`
    10,000, `medium` 1,000 and `small` 100 USDT, with no FX pin
    (`docs/V3_1_SOURCE_INVENTORY.md`, "Owner decision on the capitals, 2026-10-14").*
- **Scenarios:** both approved modeled scenarios for every component arm.

## 5. Arms

- **Components (10):**
  - combined;
  - spot_trend;
  - futures_trend;
  - futures_trend_long_only;
  - spot_grid;
  - combined without continuation;
  - combined without full short qualification;
  - combined without discretionary trailing;
  - combined without funding admission;
  - combined without recovery.
- **Baselines** (owner decision 2026-10-11, enforced by acceptance):
  - the unchanged V3 selector;
  - V3's six long-only rules, R1L-R6L;
  - the matched spot hold;
  - the V0 grid;
  - V1, as the spec-v1 grid variants listed at registration. The proposal is all nine,
    pinned as `a`, `b`, `c`, `e`, `f`, `g`, `cg`, `h` and `ch` (acceptance names must be
    alphanumeric). This is an owner choice;
  - the spec-v2 mode switcher as V2;
  - comparator D.

  Each minute baseline runs both native path modes as separate arms. With all nine V1
  variants that is 2 x (1 + 9 + 1 + 1) = 24 minute arms, plus 8, giving **32 baseline
  arms**.
- **Finished baselines:** only a liquidation counts as a finished baseline result (owner,
  2026-10-12). A V3 stop caused by masked or untradable coins makes that comparison
  incomplete.

## 6. Known effects worth knowing before approval

- **V3 at ~EUR100:** V3 could stop with `leverage_not_restored` because of exchange step
  sizes rather than missing data. Under the 2026-10-12 rule that comparison would be
  incomplete, so a pass at ~EUR100 could be blocked. This is the cautious side by design.
- **The day after a short daily bar:** on 2021-08-13 every coin has 19 usable hours (a
  5-hour exchange outage), so no daily bar. The next day every coin's correlation is
  unknown, the coins form one group, and the 80% group cap applies for that day. The
  protective close rule will already have closed the positions held during the outage.
- **Minute baselines' capital:** 10,000 USDT does not split exactly across three pairs.
  Each pair gets an equal share floored to 8 decimals, and the remainder stays as
  disclosed cash.

## 7. Run matrix and size

- **Components:** 10 arms x 2 scenarios x 2 cost profiles x 2 capitals = **80 runs**.
- **Baselines:** 32 arms x 2 cost profiles x 2 capitals = **128 runs**.
- *Note, 2026-10-14: with the owner's three capitals these are 120 and 192 W1 runs, and
  with W0's 12 the registration lists 324 cells.*
- **Estimated time:** a V3.1 run of W1 with ten coins takes about 20-25 minutes, scaled
  from the synthetic benchmark. Minute baselines take longer. The run is split into
  independent CI jobs; every attempt is recorded and none is retried.

## 8. Registration checklist

These are enforced at registration, not in the replay (they come from the conformance
review):
- **Spot hourly input:** reader-repaired and masked hours are removed. A window whose spot
  data includes a month V3 excludes (more than 17% missing) is refused; none exists in W1
  or its warm-up.
- **V3's daily decisions:** built from the same registered hourly bars (`hourly_month`).
- **Skipped hours:** derived mechanically. They are the union of every registered source's
  missing bars inside W1, including hours whose opening minute is missing in a minute
  source. The list is pinned, and a window whose first or last hour would need skipping is
  refused.
- **Funding:** the `interval_hours` convention is pinned from the SOL 2022-11 records, and
  the pinned funding is scanned for missing settlements inside W1.
- **Replay driver:** it passes `skipped_hours` and the registered capital label everywhere.
  It writes the evidence bundle and renders large reports as a bundle file. It binds each
  path-mode arm to a replay in that mode.
- **Execution gate:** each run carries its `RunIdentity` together with the pins it actually
  used: cost profile, data manifest hashes and the bundle receipt. A run whose costs or
  inputs differ from its registered cell is refused, so a doubled-cost cell can never be
  replayed at base costs.
- **Minute sources:** every minute source has its final in-window minute (2024-12-31 23:59);
  otherwise the minute baselines' terminal value is unavailable and the window is refused.
- **Order and disclosures:** the fixed lexical symbol order of decisions is pinned. The
  registration record discloses the V0-V2/D universe (BTC, ETH, XRP) and the hindsight in
  choosing today's large coins, since the adapters' report disclosures are fixed.

## 9. Pins (to be filled at registration)

- code commit and per-adapter module hashes;
- configuration hash;
- data manifest hashes per input;
- the saved spot and futures filter snapshots (`config/datasets/v3-20261009/snapshots/`);
- the skipped-hours list;
- cost profile pins;
- the FX pin;
- observation policy `v3.1-owner-2026-10-11-settlement-v1`;
- the trial register family `spec-v3.1`, with a candidate-space registration and a
  completing event before any run.

## 10. What the owner is asked

Approve or change:
- the window (section 1);
- the universes (section 2);
- the FX pin (section 4);
- the cost profiles (section 4);
- the V1 variant list (section 5).

Approval permits data preparation and the exact registration only.
