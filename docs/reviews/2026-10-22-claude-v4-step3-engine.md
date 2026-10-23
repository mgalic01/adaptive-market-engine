# Claude: V4 step 3, the engine (build record)

Index: 2026-10-22. The V4 engine, `src/crypto_grid_bot/v4/engine/` and `scripts/v4_cell.py`, was built subagent-driven in 15 tasks (v4-d14). Every task was reviewed, then a whole-branch review was run, a fix wave applied and re-reviewed, and one residual look-ahead fixed. It records the owner decisions v4-d14 to v4-d20, every ruling made where the spec or plan was silent, and the notes for reviewers. Nothing runs on real data.

Written by Claude Code (session f7f187df). The plan is
`docs/superpowers/plans/2026-10-20-v4-step3-engine.md`, and the spec
`docs/superpowers/specs/2026-10-17-v4-design.md` carries this step's amendment ("Amended in
the V4 step-3 PR").

## What it builds

The engine replays one cell (an arm, a capital and a cost level) hour by hour over the step-2
packs, on one shared spot and USDT-M futures account. It writes:

- hash-chained `records.jsonl`;
- a `receipt.json`;
- a `summary.json` that is rebuilt from the records and must match before it is written;
- a self-contained `report.html` with no script.

| Module | Role |
|---|---|
| `numbers`, `arms` | one Decimal context, exact converters; the eight arms, cells, costs and constants |
| `market` | compact `array("q")` store of the pinned packs; daily bars, point-in-time perpetual eligibility, funding events, the monthly selection, the data pins |
| `signals`, `sizing` | three speeds, the downtrend, L, S and s; full-strength volatility sizing, caps and band. Both are copied from V3 and checked against V3 on pre-2025 data |
| `pending` | deferrals, the 00:00 rule, mandatory exits, replacement buys |
| `ledger` | FIFO lots keyed by (venue, symbol), exact Fractions, an hourly audit with independent identities |
| `orders`, `allocation` | filters, splits, reduce-only, dust; the spot-first split and the cash clip |
| `safety`, `lifecycle` | liquidation, cushion, ceiling, dead markets and the penalty; per coin and side lifecycles |
| `records`, `run`, `hold`, `summary` | the chain and receipt; the hour loop; the two hold comparisons; the summary, page and verification |
| `scripts/v4_cell.py` | the one-cell CLI for step 4. It verifies the summary before writing it and prints counts only |

Measured on synthetic worlds: about 330 hours/s for a V4 arm with trades, funding and cuts,
so about 3.5 minutes for a 70,000-hour cell on one core. A hold arm runs at 850 to 3,500
hours/s. Loading the real packs takes about 90 s and about 280 MB of price arrays. Records
come to about 135 MB per V4 cell.

## Owner decisions recorded in this step

- **v4-d14:** step 3 subagent-driven.
- **v4-d15:** step 4 follows without waiting for a plan review; the work always stops before step 5.
- **v4-d16:** the universe stays the monthly top 10, with the rank-20 fallback.
- **v4-d17:** a coin dead for 7 days leaves the sizing book.
- **v4-d18:** the cash clip stays as written.
- **v4-d19:** the long-only arm keeps the dust-offset leg.
- **v4-d20:** a reported-only `hold_btc_trend` comparison is added (built in step 4, 40 cells).

## Rulings made during the build

These are where the spec or plan was silent or wrong. Each is cheap to reverse. The
behaviour-changing ones are also stated in the spec's step-3 amendment.

**Interfaces and records**
- `Costs` is imported as a type only. `HourBar` is defined in `market.py`.
- `write_receipt` and `read_receipt` exist. The cell's directory holds the records, receipt, summary and page.
- An exception in the loop becomes outcome `engine_error`, with the records closed and the receipt written.
- Hold arms write the V4 record shapes, with no `daily_coin`.
- A coin-day has a decision record and a fill-hour order record.
- The monthly record carries the full selection: ranks, volumes, exclusions, who entered and who left.
- Each outcome record names its cell, its window and the data pins, and the summary refuses records of any other cell, window or capital.
- The CLI writes a summary only after verifying it. A cell that cannot run writes nothing and counts as incomplete. The CLI's stderr carries only the exception type, never its text, which can hold prices.

**Signals and sizing**
- L, S and s are 0 while warming. L of 1/3 and 2/3 is a 60-digit quotient.
- A negative quadratic form raises, as in V3.
- The band's `current` is a Decimal quotient under the one context.
- A no-bar coin stays in the sizing book with its kept signal (its sign taken from the current eligibility). Only its own new target is discarded.
- A coin with no spot bar for 168 hours leaves the book (v4-d17).

**Orders and the account**
- Dust is the whole spot holding when it cannot be sold at the open. A spot-only coin holds its dust, and dust is sold at the coin's next order once it can be.
- A max-quantity split uses the fewest pieces, near equal in whole steps.
- Every leg rounds its target toward zero, and the order is the difference to what is held, as in V3. A futures reduction is never refused for size.
- Target notional becomes venue units with a quotient that is cut toward zero.
- The cash clip uses the spec's literal rule (v4-d18). It is applied one increase at a time, on the account after each real fill.
- The ledger's audit takes futures realised P&L from an independent flow, so a FIFO booking error shows as a residual.

**Funding months, safety and stops**
- At the decision before an incomplete funding month, the coin may not open futures, whether or not it holds any.
- A funding-month exit applies to a held futures leg. It fills at the perpetual's first bar from 01:00, or becomes a synthetic close at the month's first 00:00.
- A month with no funding status (the perpetual has no bars in it) counts as complete. This applies both to the next month at a last-day decision and to the decision's own month for eligibility. A delisting is then judged only point in time, by the 168-hour rule, and closed by the dead-market close. This removes a foresight the first version had in two places.
- A replacement spot buy follows a funding-month close of either side only when the latest target is long.
- A dead market and a funding-month close at the same midnight close as a delisting.
- Synthetic and window-end closes charge the cell's own rates.
- A required cut sale that the filters refuse leaves the leg held. If the limit is still breached, the outcome is `limit_unrestorable` / `required_fill`.
- The adverse-extremes check takes spot at its low, and a stop there is marked at those prices.

**Lifecycles and the summary**
- A lifecycle's side is the sign of the coin's net notional. A net zero with non-flat legs stays open.
- Best unrealised profit is measured on hourly open marks and the final gross. Profit given back is never negative.
- Eras and years are measured on open marks at their boundaries. The accounting residual is the largest hourly equity residual.

## How it was reviewed

Each task got a spec-and-quality review on the diff, and every Important finding went through a fix round and a scoped re-review. Findings the reviews caught:
- the ledger's audit could not see a futures booking error;
- reductions rounded the wrong way;
- the cash clip's first wording;
- a summary could be relabelled to another cell;
- one dead coin flattened the whole book.

A whole-branch review on the most capable model found no Critical issue. It confirmed byte-identical reruns of all eight arms, and exact money conservation from fills through lifecycles to final equity. It asked for:
- this spec amendment;
- reproducibility and conservation tests;
- a fix to profit given back.

The fix wave was re-reviewed clean apart from the funding-status look-ahead above, which was fixed and re-reviewed. Only focused test modules ran on the owner's PC; the full suite runs in CI.

## For reviewers

- **The reserved window.** No test or build step read the real packs. All engine tests use `tests/v4_synthetic.py` worlds.
- **Frozen code.** The frozen directories are unchanged. Engine code imports only the guard-free names on the plan's list. V3 code is called only as a test oracle on pre-2025 data.
- **Spec-level notes for the owner, already decided:**
  - with a winning short, the cash clip often cuts new buys (v4-d18);
  - the allocation can admit an increase that the ceiling then cuts in the same hour (rare, since targets sum to at most 2.7).
- **Deferred Minor findings**, triaged by the whole-branch review as safe to leave:
  - duplicated validators to consolidate;
  - extra loop-level test cases;
  - documentation polish.

  Step 4's rehearsal must include a liquidated, `limit_unrestorable` and `accounting_failure` cell through the CLI. Its verdict must require every cell of the run to carry the same `data` pins and the expected cell.
