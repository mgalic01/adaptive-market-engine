# Paper simulation contract (schema 7)

## Scope and order lifecycle

`PaperSimulator.process(Frame)` processes one timestamped quote with supplied
market signals and candidate metrics. It is a single-symbol, single-quote-currency
experiment, without exchange accounts, credentials or real transfers. The CLI
demo remains a constructed batch test; it does not establish profitability.

The simulator starts in cash, budgeting up to 80% of unprotected cash including
buy fees. Passive initial buys are below both the current bid and the supplied
fair value. The fair-value ceiling prevents a profitable checkpoint from adding
higher buy levels merely because the latest sell quote is higher.

A fully filled buy creates a paired sell. A fully filled paired sell recreates
the buy at the original lower price, subject to funds, fees, precision and minimum
notional checks. A partial sell does not create a full replacement buy. Every
child order waits for a later event; IDs do not grow into an unbounded nested
chain. Other inventory may remain held while a completed level recycles.
`Frame.allow_new_grid=False` disables both new grids and replacement buys, but
allows existing orders to finish. This is how the original synthetic batch demo
continues to close each batch deliberately.

Whenever inventory becomes flat after sales, unused/recreated buys are cancelled
and net portfolio profit is settled before rebuilding. Thus shallow oscillations
do not leave deeper unfilled buys blocking the 50/50 checkpoint forever. Harvesting
remains deferred while inventory is held: profitable legs are not automatically
new net portfolio profit if other holdings have depreciated.

## Execution assumptions

- Prices, quantities, balances, reservations and fees use Decimal. The unused
  float-based exchange stub was removed; it is not a future live adapter contract.
- A buy requires ask strictly below its limit after slippage; a sell requires bid
  strictly above its limit after slippage. Touching a limit is insufficient.
- Limit fills receive the order limit without favourable price improvement.
  Reducing unpaired inventory and forced exits use bid minus slippage, tick-rounded.
- All fills on one side share that event's participation-limited liquidity. A
  later residual sale deducts liquidity already consumed by matched sells.
- Fees are modelled in quote currency on both sides. Actual commission assets,
  base-fee deductions and fee-token discounts require fill-level reconciliation
  before any live adapter; this model is not an exchange commission guarantee.
- Each distinct quote assumes new usable liquidity. Repeated REST snapshots and
  candle volume are not interchangeable with incremental depth/trade events.
- Signals and candidate metrics are supplied fixtures. Quote validity, freshness,
  spread and execution liquidity are checked independently. There is still no
  production news or broad-market signal pipeline.

## Pauses, halts and recovery

| Condition | Response | Recovery |
| --- | --- | --- |
| Stale/future/out-of-order quote or signal, backward receive clock, excessive spread | Cancel buys; retain sells; no fills or marking from this frame | Two distinct, consecutive fresh eligible observations |
| Fresh frame with news/candidate veto | Cancel buys, stop replenishment, allow reduce-only sells | Same confirmation rule after eligibility returns |
| Daily-loss limit or soft drawdown | Cancel buys, manage sells, block new exposure | Risk limits must pass, then confirmed recovery |
| Invalid numeric/model/symbol input (category `integrity`) | Cancel all orders; latch halt; if a position is held, arm the exit so it is sold on the next valid frame | Explicit audited resume with fresh checks, once the liquidation is complete (a residue below the exchange minimum is admitted) |
| Hard drawdown (category `drawdown`) | Cancel orders; latch halt and liquidate using valid event liquidity | **Restarts automatically** 24 hours (`hard_cooloff_seconds`) after the halt began, once the liquidation is complete, the frame is eligible and a rebase of `risk_high` to the current active equity would pass the risk check; journaled as `restart`. A manual resume is refused by the frozen risk check until then. See the note below. |
| Emergency signal (category `emergency`) | Cancel orders; latch halt and liquidate using valid event liquidity | Resumable **only while the drawdown itself is within limits**: the emergency flag is read from the resume frame, so once it clears and every other limit passes, resume succeeds. An emergency raised at or past the hard-drawdown level stays refused (spec v1 amendment 1 states this asymmetry as intended); it never restarts by itself. |
| Active capital exhausted (category `exhaustion`) | Cancel orders; latch halt | **Final.** Active equity is zero, so the drawdown is 1.0. The reserve is protected and resume cannot return it to the active account. |
| Saved accounting invariant failure | Abort the transaction / refuse opening the account | Investigate; resume cannot bypass corruption |

`SimulationPolicy.recovery_frames` defaults to 2 and is persisted in account
identity. Duplicate events return their recorded result without advancing the
counter. A new ineligible frame or a gap greater than
`SimulationPolicy.maximum_frame_gap_seconds` resets confirmation. The gap defaults
to 180 seconds, allowing fresh one-minute observations. This is separate from
`risk.maximum_data_age_seconds` (30 seconds), which still limits delivery age for
each quote and its strategy inputs. Slower replays must explicitly set a gap at
least as large as their observation interval; the future replay adapter must
validate that relationship. The read-only collector remains separate from this
simulator. Emergency, exhaustion and integrity halts never clear automatically; a
`drawdown` halt does, below.

**Drawdown recovery (spec v1 amendment 1, `docs/EXPERIMENT_SPEC_V1.md` §3, engine
`drawdown-recovery-v1`, schema 6).** Every halt carries its start (`halt_since`) and one
of four categories (`halt_category`: `drawdown`, `emergency`, `exhaustion`,
`integrity`), captured once on the transition into the halt and never changed by the
later halt calls the runtime makes while it lasts. Two controls recover by themselves:

- **Soft drawdown (option C).** The first `REDUCE` outside an episode opens one
  (`episode_since`) with today's response. On every later valid frame, before any other
  change, the engine counts a confirmation when the frame is eligible and the risk
  engine would `ALLOW` with `risk_high` tentatively set to this frame's active equity
  (`episode_count`; a continuity gap, an unusable frame, an ineligible frame or a
  failing tentative check resets it). Once `soft_cooloff_seconds` (24 h) have passed
  since the episode started and `recovery_frames` confirmations are in a row, the
  rebase is committed: `risk_high` becomes the current active equity, journaled as
  `rebase`. One rebase per episode; a halt of any category ends an open episode; a
  later `REDUCE` starts a new one with its own cool-off. The 8% and 12% triggers are
  then measured from the rebased reference.
- **Hard drawdown (automatic restart).** A `drawdown` halt restarts on the first valid
  frame, after that frame's liquidation attempt, where `hard_cooloff_seconds` (24 h)
  have passed since the halt began, no order rests, the liquidation is complete in
  PR #122's sense (`exit_state` is not `incomplete`; a residue below the exchange
  minimum stays held and marked), the frame is eligible and the tentative rebase would
  `ALLOW` (so the emergency flag blocks it while set). It changes exactly what a manual
  resume changes: clears the halt and its identity, resets the range-exit state, the
  outside-range timers and the grid bounds, rebases `risk_high`, and enters the normal
  recovery pause ("automatic restart after drawdown halt"); the settlement of any held
  residue and a new grid follow on later frames. It never touches the daily baseline,
  the C1 references, the reserves or the vault. Journaled as `restart`. A halt instance
  restarts at most once; a later 12% fall from the rebased reference is a new instance.
  There is no loss floor and no capital threshold, by the owner's decision.

The **C1(b) measurement reference** (`measure_high`) is separate from the breaker's
`risk_high`: it starts with the initial capital, rises at every mark and is scaled at
every settlement by the same factor, in the same statement, but a rebase or a restart
never changes it. In a run without either it equals `risk_high` at every evaluation,
which a test asserts. Replay measures `active_max_drawdown_pct` against it and counts
`soft_drawdown_rebases` and `drawdown_restarts`.

Risk baselines are preserved through recovery; a realised loss is not erased by
issuing resume. UTC daily baselines still carry overnight gaps into the risk check.

**A drawdown halt cannot be resumed by hand; it restarts by itself.** `resume()`
requires the current risk action to be `ALLOW`. Only `_settle` rescales `risk_high`,
and it never runs while halted; for an exactly flat account active equity cannot change
either. The measured drawdown is therefore frozen at the value that triggered the halt,
so a manual resume attempt is refused, and the refusal says so; the automatic restart
above is what clears it, after the cool-off. **The one margin is a dust residue.** The
halt admits a remainder below the exchange minimum as liquidation-complete, and that
remainder stays held and marked to the bid, so it can move the measured drawdown by at
most one minimum notional against `risk_high` (5 quote units on a 100-unit account;
above that it is sellable and the armed liquidation sells it). In that corner case a
halt taken just past 12% whose residue then rallies can pass the risk check and be
resumed by hand before the restart. The spec accepts this margin (spec v1 amendment 1,
"Manual `resume()`"). An "active capital exhausted" halt stays final: even if a manual
resume is admitted (it can be, when a held residue keeps the drawdown under 8%), the
harvest gate that raised it halts the account again on the next frame.

An **emergency** halt is different, and the row above says so: the emergency flag comes
from the frame passed to `resume()`, not from a frozen baseline, so a halt raised only
by that flag clears once the flag does. It is final only when the account is also at or
past the drawdown limit. Do not read "latched" as "unrecoverable" for this one case.

Pausing cancels the remainder of a partially filled buy. Its unpaired inventory
is sold conservatively on a usable frame, sharing remaining bid capacity with
other sells. Existing paired sell orders are retained, but replenishment stays
disabled until the interrupted grid has drained. Sub-minimum dust remains visible
in `unreserved_inventory`; it is not rounded away or funded using protected money.
A dust-resolution policy is still required for production operation.

Because that residue cannot be sold at all — no later frame at the same price can
satisfy the exchange's step and minimum-notional filters — no lifecycle step waits for
it. Profit settlement, opening the next grid and leaving a range exit require instead
that nothing *sellable* is held: flat, or holding only such a residue, with no resting
sell reserving it.

**`resume()` uses the same criterion** (spec v1 amendment 1, reversing PR #122's
exact-zero rule): it is refused while the liquidation is incomplete and admitted with a
residue below the exchange minimum, which stays held and marked and is drained or
settled exactly as after any resume. The risk check is what keeps the final halts final:
a held residue marked to the bid can move the measured drawdown by at most one minimum
notional against `risk_high`, a margin the amendment accepts, since the same account
without the emergency flag restarts after 24 hours on a full rebase anyway.

The residue is never written off and never invented:
it stays in `inventory`, in `unreserved_inventory` and in the equity mark, and it is
excluded from the settlement base, which understates profit rather than overstating it.
Waiting for exact zero instead made a healthy account stop trading for good after any
partial fill smaller than one minimum notional.

A stored grid accumulates observed outside-range time (`outside_seconds`). Only an
interval bracketed by two consecutive valid outside-range frames no more than
`maximum_frame_gap_seconds` apart is counted. Larger gaps do not count and do not
erase time already observed. An unusable frame itself advances nothing; the
interval between valid observations on either side still counts if within the gap
limit. Only a valid frame inside the range resets the clock.
(Schema 2 reset the clock on every unusable frame, so a flapping feed
could postpone the exit indefinitely.) After six hours of accumulated time
(`SimulationPolicy.outside_range_seconds`), orders are cancelled and inventory
exits to cash with bounded liquidity.

`maximum_frame_gap_seconds` is a cadence limit (how far apart observations may be),
separate from `maximum_data_age_seconds` (how old one observation may be). Schema 3
used the 30 s freshness limit for both, so at the collector's 60 s minimum polling
interval pauses never cleared and the out-of-range exit never fired. The gap limit
must exceed the polling interval used in a run.

After the exit the account waits in cash. It leaves that state once flat, risk
limits pass and the candidate is eligible, and either price is back inside the old
band or, with `recenter_after_exit=True` (default), `recenter_cooldown_seconds`
(default 24 h) have passed since the exit. The normal recovery confirmations then
apply, and the next grid is built around the current fair value. With
`recenter_after_exit=False` the account deliberately waits until price re-enters the
old band. That can mean waiting indefinitely after a genuine breakout; the report
reason says "recentering disabled". Both settings are hypotheses to measure in
[BACKTEST_PLAN.md](BACKTEST_PLAN.md), not validated choices.

If risk triggers after normal matching, liquidation waits for a later usable
frame. Stale data never authorizes an exit. The same holds for the exit armed by a
validation halt: the invalid frame returns before the liquidation branch, so the sale
can only ever use a later frame that passed every freshness, ordering and quote check. An offline runner has no independent
watchdog: feed-loss handling for real resting orders remains separate work.

## Explicit paper resume

The public engine method is `PaperSimulator.resume(frame, event_id=..., reason=...)`.
It requires a halted, flat account with no orders, fresh valid observations,
eligible signals and passing risk limits. It logs the prior halt and operator
reason in the same transactional journal, places no order, and waits for the
normal recovery confirmations. Repeating the same command ID/payload is idempotent;
changing its payload is rejected. Inventory or outstanding liquidation must be
resolved before resume; it cannot override loss limits or restore reserve funds. A
refusal names which precondition failed, including the total inventory still held when
the liquidation is incomplete, and says plainly when a halt is final or restarts by
itself.

The operator CLI reopens the saved rules/policy and additionally checks freshness
against the real UTC clock. `fresh-frame.json` must contain `Frame.payload()` with
Decimal values encoded as strings and full quote/signal/candidate inputs:

```bash
PYTHONPATH=src python -m crypto_grid_bot.app --config config/default.toml \
  --resume-paper --database data/paper-v2.db --resume-frame fresh-frame.json \
  --event-id incident-001 --reason "Verified incident resolved"
```

This is a paper control for exceptional incidents, not a normal per-trade approval
step. The project still lacks a production source for the complete input frame.

## Accounting and persistence

`available_quote = cash - pending_reserve - fee_inclusive_buy_reservations`.
Sell reservations never exceed inventory. Active equity marks inventory at bid
less slippage/sell fees and excludes pending savings; total equity includes both
pending and secured savings. Neither reserve category can fund new orders.

At a flat checkpoint, the high-water-mark ledger allocates only new net profit
50/50 and batches simulated transfers. Recovering a loss does not create new
profit. Earmarks adjust risk/daily baselines proportionally. An exhausted active
account is guarded before division; no settlement can divide by zero.

Each simulated transfer has a unique checkpoint ID. The confirmation map persists
in account state and must sum to secured reserve. Events, orders, fills, allocations,
confirmation IDs and account state commit atomically using SQLite WAL/FULL and
`BEGIN IMMEDIATE`. Failures roll back the complete event. This does not solve real
asynchronous transfer reconciliation: live transfers will need durable intents,
exchange IDs, statuses and recovery after uncertain responses.

Saved identity includes schema, policy, configuration, market assumptions and
initial cash. **Only schema 7 databases are accepted; schema 1-6 are rejected, with no
implicit migration or reset.** Schema 5 (engine `exit-residue-v1`, PR #122) changed the
exit lifecycle; schema 6 (engine `drawdown-recovery-v1`, spec v1 amendment 1) added the
halt identity, the episode, the C1(b) reference and the two cool-offs to the saved
state and identity, and made a `drawdown` halt restart. Schema 7 (strategy audit, #160)
made V2 market structure a policy flag that is off by default: schema 6 was written both
by V0 code and by code that ran every account with structure on, and its identity cannot
tell them apart. An older database is refused rather than silently reinterpreted.
Preserve old experiments with the old code, or start a clearly separate schema 7
experiment. Never edit identity/state to bypass risk history.
The frame-gap policy (added in 0.5.1/0.6) is part of saved identity, so experiments
without that setting are rejected. Use a new database for the new policy; retain
the original database and matching code for reviewing the old experiment.

Broad-market input quality has a separate eligibility veto. Low-quality inputs
remain reported as `TRANSITION`, but `RegimeAssessment.input_quality_ok=False`
blocks entries regardless of the configured opportunity score threshold. Healthy
transition markets retain their existing score-based eligibility.

## Verification

The original batch demo still works. New regressions exercise 50 shallow price
oscillations, recycling while other inventory remains, partial sells, reserve
isolation, invalid-frame pauses, recovery confirmation and replay, out-of-range
exit/timer gaps, audited resume, persistent transfer IDs and guarded settlement.
Version 0.5 adds a flapping-feed exit regression (it never exits on schema 2 code),
gap/inside-reset accounting and recentering with and without the cooldown.
Version 0.6 adds 60 s-cadence regressions for pause recovery, out-of-range exit and
recentering; both fail on schema 3 code.
Version 0.5.1 covers one-minute recovery, six-hour exits and 24-hour recentering,
frame-gap boundaries, persisted-policy compatibility, low-score quality vetoes,
and invalid regime configuration endpoints.
The shallow fixture produced 2 fills on the reviewed code and 100 on the corrected
code. This is a behavioural regression result, not a return forecast or backtest.

Historical strategy validation is now the next gate, ahead of universe/news
integration. See [the plan](BACKTEST_PLAN.md) and [the Claude handoff](reviews/2026-09-24-codex-response.md).
