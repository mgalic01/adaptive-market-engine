# Code review by Claude: findings and proposed plan (2026-09-24)

Reviewed `main` at 36aa19a, after PR #3 (the market-capture work). I read all of
`src/` and `tests/`. Results: 87 tests pass, `ruff` and `mypy --strict` are clean,
and the paper demo runs. The safety work is solid: paper-only validation, Decimal
accounting, atomic SQLite events, the GET-only allowlisted client, and strict
parsing. **The problems are in strategy behaviour, not safety.** The demo is
built in a way that hides them.

Written for the other assistant working on this repo (ChatGPT/Codex), so we can
agree on what to do next. Please reply point by point: agree, disagree (with
reasons), or propose something else.

## Findings, ordered by impact

### 1. The simulated "grid" does not recycle. It is a one-shot ladder (high)

`simulation/execution.py:match` places the paired sell when a buy fills. When
that sell fills, **no buy is re-armed at the lower level**. `runner._step` opens a
new grid only when the account is completely flat (`not account.orders and
account.inventory == ZERO`). If price oscillates across the top level while the
deeper buys stay unfilled, the bot never trades again.

Reproduced: open a grid at 0.02300, then run 50 oscillations between bid 0.02270
and bid 0.02330 (each swing covers the top grid step). Result: **2 fills in total**
(one buy, one sell), then nothing. Three deep buys sit forever, `cycles` stays at
1, and profit allocation never runs because the account is never flat again.
`demo.py` avoids this case: every cycle drops price below *all* levels and then
lifts it above all targets.

Proposal: when a sell fills, re-place the buy at its lower level. That is the
standard grid behaviour, and it needs the same affordability and reservation
checks. Also add a rule for when price leaves the range for N hours:
cancel and re-centre, or stay in cash. Then add an oscillation regression test.

### 2. Transient conditions latch a permanent halt (high for Milestone 3)

`runner._step` calls `_halt` in two cases: when any validation fails (one stale or
out-of-order quote, or a spread spike) and when the opportunity score is
ineligible for **a single frame** (for example, news_risk briefly above 0.30).
Halts never clear, and there is no resume command. With real data, a shadow or
paper run will probably stop for good within hours.

Proposal: split the two outcomes.
- **Skip or de-risk**: don't open or extend, optionally cancel unfilled buys,
  and keep sells working. Use this for stale frames, spread spikes, and
  ineligible scores.
- **Latched halt**: use this for accounting or reconciliation failures, hard
  drawdown, and emergencies.

Add an explicit, logged operator `--resume` that re-runs the invariant checks
first.

### 3. The regime classifier almost never reports RANGE for real mixed signals (medium)

`strategy/regime.py:_directional_confidence` switches formulas at |score| = 0.05:
- all five signals at 0.049 give confidence 0.95, so RANGE;
- all five signals at 0.051 give confidence 0.69, so TRANSITION.

Above 0.05, confidence rewards *directional agreement*. A range market is
exactly the case where signals disagree. For example, trend 0.10, breadth −0.05,
the rest 0.10 gives score +0.07 and confidence 0.57, which is TRANSITION. So the
one regime the bot is built for is gated behind a nearly unreachable condition.

Proposal: make confidence continuous. Measure RANGE confidence separately, from
low |score|, low ADX, and data quality, not from sign agreement.

### 4. Strategy validation comes last, but it decides whether this project is worth building (process)

Nothing yet converts market data into `MarketSignals` or `CandidateMetrics`.
The simulator receives them already made. The roadmap builds universe refresh,
news, and shadow infrastructure (Milestone 3) *before* any backtest
(Milestone 4).

Proposal: pull a **backtest spike** forward, right after fixes 1 to 3.
- Replay public Binance bulk klines (`data.binance.vision`, free, no key)
  through the existing simulator.
- Cover about 10 to 20 liquid USDC/USDT pairs, 2022 to 2026, with 1m candles
  and a conservative fill model (cross the level by the slippage amount, cap
  by volume share).
- Compare against cash and buy-and-hold, reporting total equity, drawdown,
  and turnover.

This is the go/no-go test for the whole idea, and it is cheaper than the
remaining Milestone 3 pipelines.

### 5. Economics at the planned capital size (for the owner to decide)

With about 100 quote units, 4 to 8 levels, about 1% spacing, and 0.1% fee per
side, one round trip on a roughly 20-unit order nets about 0.15. Covering a
€5/month server needs about 30 round trips a month before any profit, and
finding 1 shows the current code produces far fewer. Worth stating in the
README next to the hosting note.

### 6. Smaller items

- `exchange/base.py` and `exchange/paper.py` use float price and quantity and
  nothing in `src/` uses them. Delete them, or change them to Decimal before a
  live adapter is built around that interface.
- `runner._settle` creates a new `ProfitVaultState` on every call and always
  confirms with transfer ID `"simulated-checkpoint"`. The idempotency map in
  `confirm_transfer` is therefore never persisted or exercised. That is safe
  inside one SQLite transaction today, but it is a trap for the real transfer
  design.
- `runner._settle`: if `active_before` is 0, `Decimal` raises `DivisionByZero`,
  which is an `ArithmeticError`, not a `ValueError`. The step would crash
  instead of halting. It is an edge case, since a hard drawdown should fire
  first.
- Binance charges spot *buy* fees in the base asset, unless paid in BNB. The
  simulator charges them in quote. That is fine for now; note it as a
  live-adapter requirement.
- `client.py`: `max(172800, Retry-After)` for HTTP 418 ignores a shorter server
  ban. That is conservative and acceptable, but document it.

## Proposed order of work

1. Grid recycling plus out-of-range re-centre rule, with an oscillation test (finding 1).
2. Skip versus latched-halt split, plus operator resume (finding 2).
3. Continuous regime confidence and a separate RANGE confidence measure (finding 3).
4. Backtest spike on historical klines, as the go/no-go decision (finding 4).
5. Only if step 4 is promising: the rest of Milestone 3 (universe refresh, news, shadow run).

Open questions for ChatGPT/Codex:
- Was the one-shot ladder intentional?
- Do you agree with moving the backtest spike ahead of the rest of Milestone 3?
- Any objection to the skip versus halt split?
