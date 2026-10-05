# Experiment specification v1 (DRAFT for review, not yet frozen)

**Status:** draft by Claude. It becomes frozen only when Codex has reviewed it and the
owner has confirmed the acceptance criteria in §6. After that, a change requires a new
version (v2), and results under v1 stay reported. **No strategy code exists for these
variants yet.** This document fixes what will be built and how it will be judged,
*before* any variant is run.

The scope is paper trading and historical replay only. Nothing here authorises live
trading, API keys or withdrawals. The default risk limits (3% daily pause, 8% soft and
12% hard drawdown, amended by the drawdown recovery of **amendment 1** in §3), the 50/50
profit vault and the paper-only boundary are unchanged by every **grid** variant (V0, A, B, C, E, F, G, H, C+G, C+H). The benchmark D is the one
labelled exception (§3 D): it is a replay-only calculation with its own sizing and no
risk controls or vault, and it never touches persisted paper state.

## 1. Question

Starting from `price-only-v1` (V0), do any of the pre-registered mechanisms reduce
forced-exit losses enough to make money after Revolut X fees, with a smaller worst drop
than simply holding? The diagnostic
[fee-levels-2026-09.md](backtests/fee-levels-2026-09.md) motivates the question: resting
grid sells realised gains, and forced marketable exits realised as much or more in
losses.

## 2. Prerequisites (to be implemented and reviewed before any variant run)

These are measurement and data changes, with two qualified exceptions:
- **P4 can change V0 decisions** on formerly invalid SOL runs. Those runs become a
  newly labelled scenario, "SOL with sourced historical filters". Today's filters are
  never backdated as historical ones.
- **P5 changes how invalid CLI input is handled:** an empty fee value is rejected.

**Equivalence requirement:** on every existing valid default run (`verify-2024h1` ADA and
BTC, `practice-2022` BTC and XRP, both paths), V0's fills, returns and accounting must be
identical before and after P1–P7. Valuation sampling (P2) must not change V0's engine
risk logic or fills. It records marks from the same actual quote, after that quote's
fills, for both the strategy and buy-and-hold.

| # | Change | Why |
| --- | --- | --- |
| P1 | **Record the exit reason** on every `exit/` fill: `range_exit`, `drain` (the engine's `draining` state), `liquidation` (halt or emergency) and, for variant A, `trend_exit`. Report the realised P&L per reason. | Codex (PR #14): losses cannot be attributed to range exits without it. |
| P2 | **Common drawdown sampling:** strategy total equity and buy-and-hold equity are sampled on the same schedule: every quote of every bar, after that quote's fills. For C1(b), active equity, the reserve-adjusted `risk_high` and the C1(b) measurement reference (amendment 1) are also recorded at every pre-fill and post-fill risk evaluation the engine performs, together with any hard-drawdown halt. | Criterion C3 compares the two drawdowns; they must be measured the same way. |
| P3 | **Daily history:** dataset specs gain `daily_warmup_start`. Binance `1d` archives are fetched from that month and checksummed. Over the overlap, every expected day must be present exactly once and contiguous, and must match the aggregation of its 24 unique contiguous `1h` bars, not just an aggregate OHLCV match. | Variants A and D need at least 200 completed daily bars before the evaluation starts. |
| P4 | **Historical exchange filters for SOL:** use dated, sourced point-in-time tick and step sizes if available. If they cannot be sourced, SOL runs stay invalid for every variant (§5). No synthetic spread model in the primary comparison. **Result (2026-09-24):** no dated official spot filter history was found. The archives themselves show that every SOLUSDT open, high, low and close from 2022-06 to 2023-01 has at most 2 decimals (lowest price 8.00), which is consistent with today's 0.01 tick. The invalidity therefore comes from the adapter's assumed spread with outward rounding at low prices (2 ticks ≈ 0.25% > 0.15%), not from a wrong filter. **SOL stays invalid in the primary comparison.** A one-tick spread model may only ever be a separately labelled sensitivity scenario; it is not part of v1. | Codex §4.1 answer on PR #15. |
| P5 | Carried nits: `--maker-fee`/`--taker-fee` use `is not None`, so an empty value is rejected; `replay()` asserts the order book is empty before wrapping it for request counting. | Automated reviews on PR #14. |
| P6 | **P&L reconciliation:** realised P&L by sell type, plus unrealised P&L of the remaining inventory at the final mark, must equal the final total equity minus the initial capital. | Codex (PR #15): attribution must reconcile with the account. |
| P7 | **Completed-cycle count (for C5):** a completed cycle is a grid sell (a child `…/sell` order placed when its buy filled completely) that itself fills completely. It is reported per run and per week. It is a count only, independent of the P1 P&L-by-exit-reason and the average-cost resting-sell attribution, and neither of those counts cycles. | Codex (PR #16): the metric must be defined before it is promised. |
| P8 | **Data for G and H:** BTCUSDT funding-rate archives (checksummed, in the manifest), and daily history from the month of the most recent halving before each window (P3 extended: 2020-05 for both development windows, 2024-04 for the reserved window). The halving timestamps are fixed constants in §3 H. | Needed by G and H. |

## 3. Variants

Every variant is V0 plus exactly the mechanism described. They are selected by config
flags that default to off, so V0 and existing paper accounts are unaffected. Timing rules
common to all:
- Signals use **completed** bars only.
- A daily signal computed from the UTC day ending at 00:00 takes effect at the **first
  valid replay observation at or after 00:00:00 UTC** of the next day, never within the
  bar that produced it. A rejected or stale frame never executes a signal; the next
  valid observation does.
- For every grid variant (V0, A, B, C, E, F, G, H, C+G, C+H), every existing V0 control keeps its trigger
  and deadline: emergency exit, hard-drawdown halt, daily-loss pause, soft-drawdown
  reduction, range exit (6 h), drain and eligibility pauses. **No variant delays,
  suppresses or clears any of them**, and none changes a risk limit, the allocation
  policy or the profit vault. A variant can only add restrictions (fewer buys, an
  earlier exit) or add an exit with its own deadline. There are exactly **three named
  exceptions**, each confined to the one control stated:
  - **E** may delay the **range exit only**, from 6 h to at most 12 h after `t0`, under
    the rules in §3 E. It never delays any other control.
  - **H3** may lower the **opportunity-score minimum for new grids only**, from 0.70 to
    0.60, under the rules in §3 H. Every other entry check still applies.
  - **D** is a benchmark without these controls (§3 D).

  A declared combination (C+G, C+H) inherits only the exceptions of its parts: C+H
  inherits H3's, and no combination inherits E's.

  **Amendment 1 supersedes this rule for two controls only:** the soft-drawdown
  reduction and the hard-drawdown halt. Their recovery is changed in **V0 itself**
  ("Drawdown recovery", below), so every grid variant inherits the changed controls
  identically, and the rule above applies to the controls as amended: no variant delays,
  suppresses or clears them further. Every other control, including the latched halt for
  emergency, capital exhaustion and integrity failures, is unchanged.

- **Entry regime gate (owner decision 2026-10-02, D2):** the opportunity score is
  multiplied by a regime factor before being checked against the 0.70 entry minimum.
  The factors are: RANGE 1.00, BULL 0.80, TRANSITION 0.35, BEAR 0.20, STRESS 0.00.
  Because TRANSITION (0.35) and BEAR (0.20) produce a maximum scaled score below 0.70
  regardless of the pair's quality, **no new grid can open in TRANSITION or BEAR in
  practice**. BULL requires a near-perfect base score (≥ 0.875) to clear the minimum.
  This is the intended behaviour — grid entries are effectively RANGE-only — and it is
  stated here so that variant results are interpreted correctly:
  - H3's score relaxation (0.70 → 0.60) applies only to new grids, but 0.60 > 0.35 and
    0.60 > 0.20, so **H3 can only act in RANGE** (or an almost-perfect BULL bar). It
    cannot open grids in TRANSITION or BEAR regardless of cycle phase.
  - Scoring a variant idle during TRANSITION or BEAR periods on C5 (activity) or C2
    (makes money) correctly reflects the variant's whole-window behaviour; the
    Down-period readout (D3) answers the narrower bounce question separately.
  - This is not a code change. The factors are config values and have not changed.

### V0: baseline (`price-only-v1`)
- **Code:** the commit that merges the prerequisites; it is recorded in every
  `results.json`.
- **Unchanged:** default config, fills, costs, data identities and the common mark
  cadence (P2).
- **Versions (amendment 1 and the owner's decisions of 2026-10-02).** "V0" means the
  amended V0: the drawdown recovery of amendment 1 below, with D7 in its step 3, and
  amendments 2 and 3. It runs on engine `drawdown-recovery-v2` and paper schema 8, which
  refuses schemas 1–7, because these changes move replay results and the meaning of saved
  state (`replay.py`'s bump rule; `PAPER_SIMULATION.md`). Each earlier V0 keeps its
  results and is a registered trial (the
  [coherence record](reviews/2026-09-27-claude-dsr-coherence.md) §3, which superseded
  part 2's count): the pre-amendment V0 (drawdown lockout), whose published results
  (`docs/backtests/verify-2024h1.md` and `fee-levels-2026-09.md`) predate
  `engine_version` and will be labelled pre-amendment when amended results are published
  beside them; and V0 on `drawdown-recovery-v1` (amendment 1 alone, schema 6, assigned
  2026-09-28), the "fixed V0" of the owner's 2026-09-27 decision and the one extra trial
  the coherence record counts, whose results are labelled pre-amendment-2. V0 on
  `drawdown-recovery-v2` is one further registered trial (amendment 2), which C7's
  `N_family` includes. `exit-residue-v1` names the exit fix alone (PR #122); no V0
  result on it has been run or inspected. Running the un-amended fixed V0 is not planned,
  a choice made here and open to review; if it is ever run and inspected it is one
  further trial and `N_family` gains one more.

### Range-exit clock paused during halts (amendment 3, owner decision 2026-10-02, D16)

**Rule:** the 6-hour outside-range timer (`outside_seconds`) does not advance while the
account is halted (any halt category): it stands still. Nothing carries over the halt,
though. A halt clears only on a flat account with no orders (the automatic restart and
the manual resume both require it), and there the grid bounds and the clock are
cleared: by amendment 2 once the halted account is flat, and by amendment 1's
halt-clearing rule, the restart's field list, which a manual resume shares. A range exit
that was already triggered before the halt completes normally; this rule only stops the
accumulation of outside-range time that would trigger a new exit. *(Wording made exact
2026-10-05: the decision text said the clock "resumes from where it stopped when the
halt clears", which no engine path can do, since both ways a halt clears leave the clock
at zero; Codex's review of #163.)*

**Why.** A halted account is not trading. Time spent outside the band during a halt is
not meaningful outside-range exposure — the bot cannot act on it. Counting it inflates
the `range_exits` metric in `results.json` by approximately one per halt (a halted
account sitting below its band for 6+ hours records a spurious exit). With Amendment 1
allowing multiple automatic restarts per run, this over-count compounds. The range-exit
count is a primary diagnostic for how hostile a window is to the strategy and directly
feeds the meta-strategy calibration; an inflated count produces the wrong signal.

**Engine impact.** No trading behaviour changes. The reported `range_exits` count
decreases on runs with halts. Requires an engine version bump so existing results are
correctly labelled pre-amendment-3 (assigned, together with amendment 2 and D7: engine
`drawdown-recovery-v2`, paper schema 8). No reruns of already-valid results are required
unless the corrected count would change a C4 verdict (it cannot — C4 is an integrity
check, not a range-exit threshold).

### Flat-account bounds clearing (amendment 2, owner decision 2026-10-02, D15)

**Rule:** when the account becomes flat (no inventory the exchange would accept, and no
open orders) and no range-exit is pending, the grid bounds (`grid_lower`, `grid_upper`) and all outside-range timers
(`range_exit`, `range_exit_since`, `outside_seconds`, `outside_last`) are cleared
immediately. A new grid may open at the very next eligible observation without waiting
for the stale band's 6-hour outside-range timer or the 24-hour recentre cooldown.
A residue below the exchange minimum, which no order could sell, counts as flat, as it
does everywhere else in the engine since PR #122 *(owner decision 2026-10-05: such dust
cannot be protected or exited, and keeping its stale band would bring back the empty-
account range exit this amendment removes)*.

**Why.** When a grid sells out completely and no new grid opens (spacing too tight,
gate closed, pause active), the account previously kept the old band. If price had
moved away, the empty account would record a spurious range exit and wait up to 30 hours
before the next grid — with nothing at risk. In one reproduction the next grid opened
after 1,382 minutes; with this fix it opens after 1 minute.

**Preserved intent.** The no-chase cooldown still applies to a genuine range exit: when
inventory was actually forced out of a band, the full 6-hour outside-range timer and
24-hour recentre cooldown run as before. This fix applies only to the case where the
account is flat with no grid and no pending exit — i.e. there is nothing to protect and
no range was actually exited.

**Engine impact.** This changes V0 results (fewer idle periods, more grids on choppy
windows). It requires an engine version bump and a schema bump if the cleared state
differs from what an existing persisted account holds (assigned, together with
amendment 3 and D7: engine `drawdown-recovery-v2`, paper schema 8). All V0 results
produced before this amendment are labelled pre-amendment-2 and stay published for
reference. This amendment is counted as one further registered trial in `N_family` (C7).

### Drawdown recovery (amendment 1, owner decision 2026-09-27)

**Why and on what authority.** A flat account at 8% or more below its reference could
never trade again: the soft-drawdown pause clears only on a passing risk check, which
such an account cannot reach, and a hard-drawdown halt could never be resumed from 8% or
more below it. The analysis, the replay evidence (all of it right-censored) and the
review record are in `docs/reviews/2026-09-27-claude-soft-drawdown-lockout.md`
(PR #102). On 2026-09-27 the owner chose option C, chose a fully automatic restart after
a hard-drawdown halt, declined a loss floor and a capital threshold, and granted an
exception to the no-tuning rule **on record** for these two controls. The 24-hour values
below were chosen after development results had been seen; that is disclosed here, and
the pre-amendment results stay published beside the amended ones.

**State.** The paper state gains: the start of an open drawdown episode (`observed_at`);
the start and the **category** of a halt; and the C1(b) measurement reference. The halt
category is a structured field, set where the halt is raised, with exactly four values:
`drawdown` (the 12% hard drawdown), `emergency` (the emergency flag), `exhaustion`
(active capital exhausted) and `integrity` (any other halt: an invalid frame, rejected
by the frame or account validation and raised through `_step`'s `ValueError` handler; a
saved-accounting invariant failure is not a halt, since the store rolls the event back
and re-raises). It is never inferred from the halt's text. If the emergency flag and the
hard drawdown are true together, the category is `emergency`, as the risk engine already
checks the flag first.

The halt start, category and reason are captured **once, on the transition from not
halted to halted** (`account.halt` empty before the call). The runtime calls `_halt`
again on every later valid frame while the risk engine keeps returning `EXIT` (a halted
flat account past 12% does so on every frame) and on every invalid frame during a halt;
none of those later calls changes the start, the category or the reason. They may still
clear orders and arm liquidation, as today. So an `integrity` or `emergency` halt on an
account past 12% is never re-categorised as `drawdown` on the next frame; a `drawdown`
halt whose later frame carries the emergency flag stays `drawdown`, and the flag blocks
its restart through precondition 3 for as long as it is set; and an invalid frame during
a `drawdown` halt does not turn it into an `integrity` halt. A **halt instance** is the
halted span from that transition to the restart or resume that clears it.

**The C1(b) measurement reference, defined on its own.** It is a `Decimal` in the paper
state, updated at exactly three points and nowhere else:
1. **At account creation** it equals the initial active capital, the value `risk_high`
   starts with (`Account.start`).
2. **At every mark,** where `risk_high = max(risk_high, last_equity)` runs today
   (`_mark`), it becomes `max(reference, last_equity)`.
3. **At every settlement,** it is multiplied by the same factor as `risk_high`, whatever
   `_settle` computes at the time. Since PR #122 (engine `exit-residue-v1`) that is
   `factor = (active capital after allocation + marked residue) / (active capital before
   + marked residue)`, where the marked residue is any unsellable remainder valued as
   `Account.equity` values it; with no residue it reduces to the plain ratio. The
   reference is scaled in the same statement as `risk_high`, never by a second formula.

A rebase or an automatic restart never changes it. So in any run without a rebase or a
restart it equals `risk_high` at every evaluation. That equality is a required test,
and it catches any later change to `risk_high`'s formula that is not mirrored here.

**Soft drawdown (option C).**
1. The first `REDUCE` outside an episode starts an episode, with today's response:
   cancel resting buys, manage sells, pause.
2. On each valid frame of an open episode, before any state changes, the engine checks:
   (a) at least **24 hours** of `observed_at` since the episode start; (b) the normal
   `recovery_frames` confirmations: a valid, eligible frame counts as one when the risk
   engine, evaluated with `risk_high` tentatively set to this frame's active equity,
   returns `ALLOW`, which by construction tests the daily loss, the emergency flag and the
   input checks and nothing about drawdown; the count resets on the events that reset
   `recovery_count` today (a frame gap over `maximum_frame_gap_seconds`, a
   `TransientFrame`, an ineligible frame); (c) the account is not halted. A range exit
   waiting in cash does not block this check.
3. If all hold, it checks whether the account has already recovered: if the current
   active equity is strictly above 92% of the existing `risk_high`, that is, its
   drawdown is below the 8% soft limit as the risk engine measures it (a drawdown of
   exactly 8% is a soft drawdown), the episode is **closed without rebasing** —
   `risk_high` stays at its current value and is not lowered. This prevents the
   heal-then-rebase ratchet: repeated partial recoveries can no longer silently erode the
   reference without the 12% halt ever firing. **(Owner decision 2026-10-02, D7.)** If
   the drawdown is still at or above 8%, the rebase proceeds: it sets `risk_high` to the
   current active equity **tentatively** and evaluates the risk engine again. The rebase
   is committed only if the result is `ALLOW`; otherwise nothing changes and the check
   repeats on the next frame. *(Wording made consistent 2026-10-05: the decision text said
   "at or above 92% … (i.e. the drawdown is already under 8%)", and the two halves
   disagree at exactly 92%. The risk engine treats a drawdown of exactly 8% as soft
   (`loss >= limit`), so closing there would start a new episode at once, on the same
   frame; the close therefore needs strictly above 92%. No other change to the decision.)*
4. The rebase check runs first in the step. After a committed rebase or a no-rebase
   close, the range-exit and pause recovery rules apply unchanged.
5. The episode ends at its rebase or its no-rebase close, so it has at most one of
   either. **It also ends when the account is halted, for any category:** the halt
   supersedes it, and its start time is cleared. After a restart or a manual resume no
   episode is open, so a later `REDUCE` starts a new episode with its own 24-hour
   cool-off and `recovery_frames` confirmations. A restart of the process restores the
   saved episode start. The 8% and 12% triggers are both measured from the (possibly
   unchanged) `risk_high`. Each rebase is recorded: time, old and new reference, episode
   start. A no-rebase close is also recorded: time, equity at close, episode start.

**Hard drawdown (automatic restart).** Only a halt of category `drawdown` restarts
automatically. `emergency` and `integrity` halts stay latched until an explicit audited
resume, and `exhaustion` is final (its drawdown is pinned at 1.0), as today. **Stated
asymmetry, intended:** an `emergency` halt raised at or past 12% stays refused by the
risk check after the flag clears, while the same account without the flag restarts after
H. The owner's decision covers the hard-drawdown halt only; the emergency flag is a
per-frame paper signal that replay never sets (`replay.py`, `emergency=False`); extending
the restart to cleared emergency halts would be a further owner decision. A `drawdown`
halt restarts when, on one valid frame:
1. at least **24 hours** (H) of `observed_at` have passed since the halt started;
2. every precondition of today's `resume()` holds except its risk check: halted, no open
   orders, `account.validate` passes, the frame is valid, and the eligibility check
   passes. **"Flat" means the forced liquidation is complete in the sense of PR #122:** no
   inventory is left that the market would still accept (`exit_state` is not
   `incomplete`). A remainder below the exchange minimum (`dust`) does not block the
   restart; it stays held and marked, as the owner accepted for trading and settlement on
   2026-09-27, and its marked value is part of the active equity the tentative rebase
   uses. While the liquidation is incomplete, nothing happens. The manual `resume()`
   adopts the same criterion ("Manual `resume()`", below), so no halt of any category can
   be locked by a residue that no exchange will buy. The exact-zero rule of PR #122
   protected nothing that the risk check does not already protect (an `exhaustion` halt
   has drawdown 1.0 against the frozen `risk_high` whatever is held), and for `integrity`
   and `emergency` halts, which are resumable by design, it reproduced the lockout this
   amendment removes;
3. a tentative rebase of `risk_high` to the current active equity (`last_equity` after
   this step's mark) makes the risk result `ALLOW` (daily loss under 3%, no emergency
   flag).

On a halted frame the runtime first attempts the liquidation, as today; the restart
preconditions are evaluated on the account after that attempt, so a restart can happen on
the frame that completes the liquidation, and `exit_state` is read after the fill.

The restart then changes exactly these fields, the ones today's `resume()` changes, and
no others (beyond the observation timestamps and the mark that every valid step already
records):
- `halt` is cleared and `liquidating` is set to false;
- range-exit state (`range_exit`, `range_exit_since`), the outside-range timers
  (`outside_seconds`, `outside_last`) and the grid bounds (`grid_lower`, `grid_upper`) are
  reset, since the account is flat with no grid;
- `risk_high` takes the committed rebase value;
- the halt start and category are cleared (any soft-drawdown episode was already closed
  when the halt began, so none is open after the restart);
- the account enters a pause exactly as `_pause` does today: `pause` = "automatic restart
  after drawdown halt: awaiting confirmed eligible data", `recovery_count` = 0 and
  `draining` = true (there are no buys to cancel), so the normal `recovery_frames`
  confirmations apply before a new grid and a held dust residue takes the drain-and-
  settlement path a resumed account takes today.

It does **not** touch the daily baseline (`day`, `day_start`), which changes only at the
normal UTC day roll; that roll runs at the top of the step before the risk check, so
unlike `resume()` the restart itself never rolls it. It does not touch either C1 reference, the reserves or the vault.
The emergency flag is a per-frame signal, not account state, so nothing can clear it.
The event is recorded: halt start, category, restart time, and the old and new
reference. A halt instance restarts at most once; after a restart, a later 12% fall from
the rebased reference is a new instance with its own H. There is **no overall loss
floor**: cumulative losses across episodes are unbounded by the owner's choice, and C1
still judges every run.

**Manual `resume()` (all categories).** The implementation PR changes `resume()`'s
inventory precondition from exact zero (PR #122) to the liquidation-complete criterion of
precondition 2: refused while `exit_state` is `incomplete`, admitted with a `dust`
remainder, which stays held and marked and is drained or settled exactly as after today's
resume. Its risk check is unchanged and is what keeps the final halts final: an
`exhaustion` halt is refused for good (drawdown 1.0); an `emergency` halt is refused while
its flag is set and, once the flag clears, resumes only if the frozen drawdown is within
limits. A held residue is marked to the bid, so it can move the measured drawdown by at
most one minimum notional against `risk_high` (5 quote units on a 100-unit account; above
that the residue is sellable and the armed liquidation sells it). That margin is
accepted: the same account without the flag restarts after 24 hours on a full rebase.
The refusal text still names the inventory held when the liquidation is incomplete.
**This reverses a rule PR #122 merged on 2026-09-28 and is a design decision made in this
amendment, open to the owner's, Bob's and Codex's review.**

**Same control, not same effect.** Every grid variant runs these controls identically,
so the defined control and the baseline are the same in every comparison. Inventory paths
and episode timing still differ, so a variant's result relative to V0 can change because
of the amendment, and results are read with that in mind. C6 compares against the
amended ungated V0.

**Parameters.** Soft cool-off 24 h; hard-stop cool-off H = 24 h (proposed in PR #102;
Bob found it acceptable, and Codex could not review it before this amendment). Both are
config values, persisted in the account identity, and fixed for all v1 runs.

**Tests required before any rerun.**
- Soft drawdown: a trigger just before midnight; no rebase before 24 hours; no rebase
  while a daily pause, an emergency or a data block is active; a tentative rebase that
  does not yield `ALLOW` is not committed; one rebase per episode; a process restart
  before and after a rebase; a range exit waiting in cash is released after the rebase.
- Measurement peaks: C1(b)'s reference is scaled at settlement and never rebased; C1(a)'s
  peak is never scaled and never rebased; **in a run with no rebase or restart, C1(b)'s
  reference equals `risk_high` at every evaluation.**
- Restart side effects: an automatic restart changes only the fields listed above; the
  daily baseline, both C1 references and the reserves are unchanged by it.
- Hard drawdown: no restart before H; no restart while partially liquidated (exitable
  inventory remains); a restart with only a dust residue held, which stays marked; no restart
  on an ineligible frame; no restart while the daily loss is 3% or more or the emergency
  flag is set; never for categories `emergency`, `exhaustion` or `integrity`; one restart
  per halt instance; the halt start, category and reason are captured at every call site
  on the transition into the halt and are not changed by later `_halt` calls while halted
  (a `drawdown` halt keeps its start after five more `EXIT` frames; an `integrity` or
  `emergency` halt on an account past 12% is not re-categorised on the next frame; an
  invalid frame during a `drawdown` halt does not make it `integrity`).
- Manual resume: refused while `exit_state` is `incomplete`; admitted with a `dust`
  remainder, which stays held and marked; an `exhaustion` halt is refused by the risk check
  alone; an `emergency` halt is refused while its flag is set.
- Identity: `ENGINE_VERSION` and `SCHEMA` are bumped; a schema-5 database is refused by the
  store and by the resume CLI.
- Episode across a halt: a soft episode open when a hard halt starts is closed by the
  halt. After the automatic restart the account cannot rebase until a new episode's own
  24 hours and `recovery_frames` confirmations have passed. The same holds after a manual
  resume from any other halt category.

### A: trend/cycle switch (daily SMA50 and SMA200)
Inputs are the completed daily close `C`, `SMA50` and `SMA200` of the traded pair. The
state machine runs over the whole daily history from the first day on which SMA200 is
defined, including the warm-up. The state at the first evaluated minute is therefore
already determined. The initial state, before the first classified day, is Middle.

The state is updated once per completed daily bar, from the previous state and `C`:

| State | Entered when | Behaviour |
| --- | --- | --- |
| **Up** | From Up: `C > SMA200`. From Recovering: a second consecutive `C > SMA200`. | Grids allowed, as in V0. |
| **Recovering** | From Middle, Down or Unavailable: the first `C > SMA200`. | Same as Middle. |
| **Middle** | From any state: `C ≤ SMA200` and `C > SMA50`. | No new grid. An existing grid keeps running: its sells, reentries within the grid and range exit behave as in V0. Reentries are allowed deliberately: they only rebuy levels the grid already sold, inside its existing range, and B's cap bounds the exposure in C. |
| **Down** | From any state: `C ≤ SMA200` and `C ≤ SMA50`. | No new grid, and a **Down sequence** starts unless one is already running (see below). |
| **Unavailable** | A daily bar is missing or SMA50/SMA200 is undefined. | Same as Middle: no new grid, and no fill is forced. The two-close count restarts. |

**When SMA50/SMA200 is undefined (owner decision 2026-10-02, D6):** SMA200 requires
200 consecutive completed daily bars with no gaps. A single missing bar makes SMA200
undefined for the next 200 days — the window must rebuild from scratch. This is the
strict rule and it is intentional: averaging over gaps would mean trading on an
incomplete signal, which is unacceptable for a live feed where a missing bar usually
indicates a data-source problem. Consequences:

- In registered backtests this cannot happen: the dataset integrity check (P3, §2)
  rejects any spec whose daily archive has gaps before accepting the run.
- In a live or paper feed there is no such guard. A single dropped daily bar silences
  Variant A for up to 200 days. This is the correct fail-closed behaviour: when the
  signal is uncertain, the bot stays in the Middle state (no new grid, existing grid
  continues) until the window is clean again.
- The 200-day consequence is written here so it is not treated as a bug when observed
  in live operation.

**Down sequence:**
- **Start:** it starts at the effective time of the first Down classification (`T0`).
  Resting buys are cancelled at `T0`, and resting sells stay in place.
- **Deadline:** the trend deadline is `T0 + 24 h`. Further Down days do **not** reset
  it.
- **Existing exits are not postponed:** the deadline is only an **additional upper
  bound**. A range exit, drain, halt or emergency exit that falls due earlier happens on
  its own V0 schedule; the sequence then ends early if the account is flat.
- **At the deadline:** remaining sells are cancelled, then the remaining inventory is
  liquidated with marketable `trend_exit` sells. These are bounded by the same bid-size
  participation limit as V0's liquidation. Unfilled residuals are retried at each
  following valid observation under the same limits until the account is flat.
- **A started sequence completes** even if a later close moves the state to Recovering,
  Middle or Up. A new grid requires both the Up state and no running Down sequence.

**Other rules:**
- **Hysteresis:** Up is reached only through Recovering, so it takes two consecutive
  completed closes above SMA200. Leaving Up takes one close at or below SMA200.
- **Same-step labelling:** if several exits are due at the same observation, the fills
  take the label of the highest-ranked one: halt/emergency `liquidation` >
  daily-loss/soft-drawdown actions (as in V0) > `range_exit` > `drain` > `trend_exit`.
  The ranking changes labels only, never timing.
- **Warm-up:** at least 200 completed daily bars before the first evaluated minute (P3).

### B: inventory cap
- **Definitions:**
  - **Active equity** = cash − pending reserve + inventory × mark. The secured reserve is
    already outside cash, so both reserves are excluded.
  - **Mark** = bid × (1 − slippage) × (1 − taker).
  - **Committed exposure** = inventory × mark + Σ over **every** resting buy of
    (limit price × remaining quantity × (1 + maker fee)) + the proposed buy, valued the
    same way. Resting buys are valued at their cost including the maker fee. This is
    conservative relative to ignoring pending commitments; together with the
    prospective-equity deduction below, it charges each pending buy its full cash cost.
  - **Prospective active equity** = active equity − Σ over every resting buy of
    (limit × remaining quantity × [(1 + maker) − (1 − slippage)(1 − taker)]) − the
    proposed buy, valued the same way at its full proposed quantity. This is the equity
    left if all of them filled at their limits and were immediately marked at the limit
    price with the exit haircut, so it deducts their fees and haircuts. A partly filled
    buy's filled part is already in active equity, so only its remainder is deducted.
    *(Wording clarified 2026-09-29: "remaining quantity", as in committed exposure above,
    the partial-fill rule below and the code; no rule change.)*
- **Cap:** committed exposure (including the proposed buy) ≤ **40% of prospective active
  equity**.
  - The rule bounds new commitments under this stated valuation.
  - It is **not** a guarantee that the ratio holds afterwards: price moves after a
    fill, or a fill at a better price, can still lift the measured ratio.
- **Placement order:** a new grid places its buy levels from the highest price down.
  - The first level that does not fit completely is **resized** to the largest quantity
    that fits, floored to the lot step.
  - If the resized quantity is below the minimum notional, that level is skipped.
  - Either way, every **lower** level is skipped. Resized and skipped levels are recorded
    in the report.
  - Reentry buys pass the same check when they are created, with the same resize or skip
    rule.
- **Rounding and fills:**
  - A capped quantity is floored to the lot step. If it is then below the minimum
    notional, the buy is not placed.
  - Partial fills do not change the check: the unfilled remainder is still counted.
  - Sell targets are unchanged, and no reserve is ever spent.
- **Price drift:** if rising prices push committed exposure above 40%, this is allowed.
  There is no forced sale, but no new buy is placed until exposure is below the cap
  again.
- **What it does not do:** it never forces a sale and never delays a sell. The cap
  constrains new buy commitments; it does not guarantee the ratio at all times.
- **40% is an experiment parameter,** not a new default, and it gives no authority to
  use protected funds.
- **Required tests:** the prospective-equity arithmetic with fees; the resize-then-skip
  boundary; concurrent resting buys that each fit alone but not together;
  reentry creation at the cap; a partial fill followed by a new buy; a price-driven
  breach (no sale, no new buy, then resumption below the cap); lot flooring below the
  minimum notional.
- **Deferred:** quote skewing by inventory (Avellaneda–Stoikov style) is not in v1. It
  would need its own spec.

### C: A + B, a declared interaction
- **Mechanism:** both mechanisms at once, with A's priority rules.
- **Reporting:** C is reported as an interaction. It is not claimed as a single
  mechanism.

### D: trend benchmark (not a grid)
- **Signal:** each traded pair is held while its completed daily close is above its
  SMA50, and cash is held otherwise. Missing, undefined, zero or negative values mean
  cash.
- **Sizing:** at each entry, all of the run's cash goes into the pair. The quantity is
  floored to the lot step, and a buy is skipped if it is below the minimum notional.
  D keeps no profit vault or reserves: all equity is one pot.
- **Execution:** entries and exits are marketable at the next valid observation, at
  ask × (1 + slippage) for buys and bid × (1 − slippage) for sells, paying the taker
  fee. Each observation fills at most the ask- or bid-size participation limit (10%),
  as V0's liquidation does.
  - **Entry residual = the remaining quote budget, not a fixed base quantity.** At each
    observation, D buys the smallest of (1) the participation limit and (2) the
    remaining cash ÷ (ask × (1 + slippage) × (1 + taker)), floored to the lot step. The
    entry ends when that quantity is below the minimum notional. So a retry can never
    spend more cash than is left.
  - **Exit residual = the fixed base quantity held.** Each observation sells up to the
    participation limit. An unsold remainder below the minimum notional stays as
    reported dust.
  - **Signal reversal while filling:** at the effective observation of a reversal, the
    unfinished side is abandoned and the new side starts at that same observation. An
    entry in progress stops, and the quantity already bought is exited. An exit in
    progress stops; the unsold inventory stays held and marked, and the new entry adds
    to it using the cash on hand.
- **Unchanged from A:** capital, marks, warm-up, timing and fees.
- **Risk controls:** D is **exempt** from the common rule in §3. It has no daily-loss
  pause, soft or hard drawdown halt or emergency exit; it only follows its signal. Its
  return and drawdown are reported as they are, clearly labelled as a benchmark with a
  different risk policy.
- **State:** D is a replay-only calculation and never writes shared or persisted paper
  state.
- **C1 for D:** D has one pot with no reserves, so its active equity equals its total
  equity, and C1(b) reduces to C1(a) measured against its own peak. D has no halts, so
  the hard-halt veto cannot trigger.

### E: volume-confirmed exit (included by the owner, 2026-09-24)
- **Mechanism:** when V0's 6-hour outside-range timer expires, E compares the base
  volume of the **completed** minutes since the first outside observation with
  2 × (the median completed 1h base volume over the previous 720 hours) × 6.
  - At or above that level, the range exit happens exactly as in V0.
  - Below it, the timer is extended **once** to 12 hours in total. At 12 hours the
    range exit happens unconditionally.
- **Reference, frozen at the timer start:** the 720 hours are the completed 1h bars
  whose open times are the 720 hours ending at the last hour that closed at or before
  the first outside observation `t0`. The median is computed once, at `t0`, and is not
  updated during the timer.
- **Measured volume:** the 1m bars with open time in `[floor_minute(t0), floor_minute(t0
  + 6 h))`, i.e. the completed minutes of the 6-hour span. A zero-volume minute is valid
  input.
- **Unavailable means V0:** if any of the 720 reference hours or any of the measured
  minutes is missing, or the reference median is zero, the comparison is
  **unavailable** and the range exit happens at 6 hours exactly as in V0. E never
  extends on missing data. Unavailable checks are counted and reported.
- **Never delayed:** emergency exits, hard-drawdown halts, the daily-loss pause, the
  soft-drawdown reduction and drain are never delayed; the §3 common rule still applies.
- **Extension ends early:** if price returns inside the range during the extension, V0's
  normal reset applies.
- **Boundary rules** (fixed before implementation; Codex, PR #16):
  - **Threshold:** measured volume **≥** the threshold means exit as V0; strictly **<**
    means extend. Equality exits.
  - **One decision per episode:** the comparison is made once, at the first valid
    observation at or after `t0 + 6 h`. A delayed observation still uses the fixed
    interval `[floor_minute(t0), floor_minute(t0 + 6 h))`, never a later one. The
    12-hour deadline is always `t0 + 12 h`, measured from the original `t0`; it is never
    moved.
  - **New episode:** after a return inside the range resets the timer, a later exit
    from the range starts a new episode with a new `t0`, a newly frozen reference and
    its own single extension.
  - **Other risk actions win:** if a halt, emergency exit, daily-loss pause,
    soft-drawdown reduction or drain acts during the extension, it acts exactly as in
    V0. The extension never delays or blocks it.
  - **An exit, once started, stays started:** when the range exit begins (at 6 h, or at
    12 h), it is latched. Remaining quantity keeps being sold under the existing
    participation limits until done, even if price returns inside the range or the
    volume changes. No extension decision can cancel, pause or restart an exit that
    has already begun.
  - **Required tests:** volume below, equal to and above the threshold; a missing
    reference hour, a missing measured minute and a zero-median reference (each exits at
    6 h); a delayed first observation after 6 h (same interval, same deadline); return
    inside the range then a new episode; a halt, emergency exit and drain during the
    extension; a partial range exit at 12 h that stays latched across a return inside
    the range.
- **Reported:** the number of extensions and unavailable checks, the extra hours outside
  the range, and the P&L of extended exits next to the bid at the 6-hour mark. That
  6-hour comparison is a **diagnostic only**: it is not an executable counterfactual
  (it ignores fees, liquidity and residual inventory) and is never used for selection.
- **Risk review:** E increases exposure time by up to 6 hours per exit. The unchanged
  halt, emergency, daily-loss, soft-drawdown and drain controls bound it but do not
  guarantee a realised-loss ceiling. **Codex (2026-09-25, PR #16):** acceptable as a
  paper/replay hypothesis in principle. It is not yet approved for implementation or
  selection. E becomes eligible for selection only after Codex has reviewed its
  implementation and the boundary tests above; until then it is run and reported but
  **not eligible**.

### F: order-flow entry block
F blocks new buys only. It is **not** a V0 pause: it never sets `draining`, never
market-sells inventory and never clears or delays any other pause, halt or exit.
- **Signal:** `share` = taker-buy **base** volume ÷ base volume over the last 15
  **completed, consecutive** one-minute bars.
  - `share` is **unavailable** if any of those 15 bars is missing, which is not the
    same as a zero-volume bar, or if the aggregate base volume over the 15 bars is
    zero.
  - A single zero-volume minute inside an otherwise complete window is valid input.
- **Block:** F's own flag `flow_block` turns on when `share < 0.40` (strict) or `share`
  is unavailable.
  - While it is on, resting buys are cancelled, and no new grid or reentry buy is placed.
  - A buy cancelled after a partial fill leaves its filled quantity unpaired. That
    quantity gets a resting grid sell at the cancelled buy's target, exactly as a
    complete fill would, so it pays the maker fee and needs no drain.
  - **Fragments below the minimum notional** at their target cannot be placed as a
    sell. They are **accumulated per target price**. When the accumulated quantity at a
    target reaches the minimum notional, one resting sell is placed for it.
  - Until then, the fragments are held unreserved and marked in equity like any other
    inventory. They remain subject to V0's range exit, liquidation and, in variants
    combining A, `trend_exit`.
  - Anything still below the minimum at the end of a run is reported as dust, as V0
    already does.
  - When the originating grid ends (range exit or re-centre), its buckets are handled
    like other unreserved inventory: they go through that exit, and only a remainder
    below the minimum becomes dust.
- **Unblock:** `flow_block` turns off when `share ≥ 0.45` (inclusive). Turning it off
  only lifts F's own restriction. Any other active pause, halt, drain or eligibility
  veto stays in force.
- **Startup:** `flow_block` starts on, so it fails closed. A start inside the
  0.40–0.45 band stays blocked until `share ≥ 0.45`.
- **Unaffected:** resting sells, range exits, drain and every risk exit continue as in
  V0.
- **Request budget:** cancellations count against it. The per-day request maximum is
  reported for F specifically.
- **Required tests:**
  - cancellation counts;
  - a partial fill then a block (the resting sell for the unpaired quantity);
  - a below-minimum fragment, then accumulation to the minimum, then a single sell;
  - threshold equalities at exactly 0.40 and 0.45;
  - a missing minute versus a zero-volume minute;
  - an F unblock while a V0 eligibility pause is active (the pause must remain);
  - overlapping F and range-exit states.

### G: funding-rate gate (owner proposal via Bob, included 2026-09-24)
- **Data:** BTCUSDT USDⓈ-M perpetual funding rates from the public archive
  `data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/`. These are monthly
  zips with published checksums, fetched and verified like the klines (manifest,
  SHA-256).
  - The replay never calls a futures API.
  - The live-host rule (public data hosts only) is unchanged.
- **Records and uniqueness:** each record is one settlement: `calc_time` (truncated to
  the second), the funding interval in hours and the rate. Its **scheduled time** is
  `calc_time` floored to the whole UTC hour. Two records with the same scheduled time
  are a data-integrity failure for the window (§5), never collapsed or chosen between.
- **Cadence from the source:** the expected interval comes from each record's own
  interval field in the archive, not from a universal 8-hour assumption. Accepted
  values are 1, 2, 4 and 8 hours; any other value, or a missing field, makes that
  record's successor unknown, so G is unavailable (below) until three consecutive
  valid records exist again.
- **Pending P8 evidence (G cannot be frozen until resolved):**
  - **Interval meaning: resolved by convention (2026-09-25, PR #19 discussion).** The
    archives cannot tell whether a record's interval is the interval **to its next**
    settlement or the interval **ending at** it. G therefore uses the
    **uniform-cadence rule** below. It gives the same decision under both readings
    whenever the latest three records agree, and it is unavailable otherwise.
  - **Missing field:** if some archive months have no interval field, the spec is
    amended before freeze; nothing is assumed.
  - **Modelling conventions, not verified facts:** flooring `calc_time` to the hour
    and the 60-second publication allowance are **assumptions**. Bob's report is
    assessed against them before freeze.
  - **Bob's P8 survey (2026-09-25, `bob/p8-data-survey` `761b2ee`):**
    - Funding archives exist for all 60 months, 2020-01 to 2024-12, with no errors.
    - One sampled month (2022-06) has the header
      `calc_time,funding_interval_hours,last_funding_rate`, millisecond times, interval
      8 and three settlements per day.
    - Some times are a few milliseconds past the hour (for example `+11 ms`), which
      supports flooring to the hour.
    - **Cadence over all months (Bob, 2026-09-25, PR #19 `fe60ec4`):**
      - All 60 months (2020-01 to 2024-12) have the header
        `calc_time,funding_interval_hours,last_funding_rate`.
      - All 5,481 records have interval 8.
      - Every step is exactly 8 hours, with no missing and no duplicate settlements.
      - The largest offset past the hour is 47 ms. Flooring to the hour reconstructs
        the scheduled slots in this sample, but it discards the raw offsets, which are
        kept for provenance. It says nothing about publication time.
      - **Consequence:** in both development windows, the meaning of the interval field
        (next or ending) cannot change any G decision, so these rules apply as written.
        A cadence change, if one ever occurs, needs a documented rule and its test
        before the reserved run. The reserved window's data is not examined until the
        owner's go.
    - The 60-second publication allowance cannot be verified from archives. It stays a
      labelled assumption.
- **Timing:** a record becomes usable at `calc_time + 60 s` (a fixed publication
  allowance, an **assumption** pending P8), at the first valid observation at or after
  that instant.
- **Uniform-cadence rule (latest three):** at an observation at time `t`, take the
  newest usable record `r3` and the two usable records before it, `r1` and `r2`.
  - **Insufficient history:** if fewer than three usable records exist, including at
    replay start before enough funding history has accumulated, the signal is
    unavailable. G fails closed by default.
  - **Invalid newest record:** `r3` is the newest usable record whatever its content.
    If it is invalid (missing or unaccepted interval, non-finite rate), the signal is
    unavailable. It is never filtered out in favour of three older valid records.
  - **Available** only if all of these hold:
    - **Finite rates:** all three records carry finite rates. An invalid rate on
      `r1` or `r2` makes the signal unavailable just as it does on `r3`; invalid
      records are never skipped to substitute older valid records.
    - **Uniform interval:** `r1`, `r2` and `r3` all carry the **same** accepted
      interval `I`.
    - **Exact steps:** `scheduled(r2) − scheduled(r1) = I` and
      `scheduled(r3) − scheduled(r2) = I`.
    - **Not overdue:** `t < scheduled(r3) + I + 60 s`. A settlement that is due and
      absent makes the signal unavailable, and an older record is never substituted
      for it.
  - **Why uniform:** with a constant cadence, the "next" and "ending" readings agree
    on every step, so the decision does not depend on which one is true. Mixed
    intervals make the signal unavailable. This also rejects a hidden gap such as
    (4 h record, missing record, 8 h record), whose 8-hour step the "ending" reading
    would otherwise accept.
  - **Successor = `I` is a modelling convention, not a guaranteed fact.** Uniform past
    records cannot show that the *next* interval has not already changed before its
    first record becomes usable. Until then, the overdue deadline uses `I`:
    - the signal becomes unavailable as soon as either the first record carrying
      the new interval becomes usable (the three are then mixed), or the old
      deadline `scheduled(r3) + I + 60 s` passes without a newer usable record,
      whichever comes first;
    - under the "next" reading the first case happens at the last old-cadence
      settlement; under the "ending" reading it happens at the first new-cadence
      settlement, or the old deadline passes first when the cadence lengthens.

    G blocks on detected disagreement or the convention's overdue deadline.
    It cannot detect an unseen shorter cadence before either condition occurs:
    if the first changed record is absent, three old uniform records can remain
    available until the old deadline. This is a limitation of the convention,
    not a guarantee against every missing settlement under an unknown cadence.
  - **Recovery condition:** after a cadence change, a gap or an invalid record, the
    signal becomes available again at the first observation at which the three newest
    usable records again satisfy all of the conditions above, including the same
    overdue deadline `scheduled(r3) + I + 60 s`; no separate boundary is defined. How long that takes
    depends on the new cadence and on when observations occur; it is not a fixed
    time.
- **Rule:** no new grid while the signal is **unavailable**, or while it is available
  and all three rates are **> +0.0005** (+0.05% per settlement; strict). Otherwise G
  does not block.
  - Negative or low funding never blocks.
  - Existing grids, sells and exits are unaffected, whatever G's state.
- **Required tests** (synthetic series; no reserved-window data):
  - **Constant cadence:** 8 h, available.
  - **Cadence change 8 → 4 h:** the windows (8, 8, 4) and (8, 4, 4) are unavailable,
    and the first (4, 4, 4) with 4-hour steps is available.
  - **Cadence change 4 → 8 h:** the windows (4, 4, 8) and (4, 8, 8) are unavailable,
    and the first (8, 8, 8) with 8-hour steps is available.
  - **Observations between the old and new deadlines, in both directions:**
    - **8 → 4 h:** before the first 4-hour record becomes usable, available until the
      old overdue deadline `scheduled(r3) + 8 h + 60 s`; after it becomes usable,
      unavailable because the window is mixed.
    - **4 → 8 h:** unavailable once the old overdue deadline
      `scheduled(r3) + 4 h + 60 s` passes, until uniform 8-hour records exist.
  - **The first changed record's publication boundary:** exactly at its
    `calc_time + 60 s`, and one second before it.
  - **Hidden gap:** (4 h, missing, 8 h) is unavailable.
  - **Missing newest record:** unavailable from the overdue deadline
    `scheduled(r3) + I + 60 s` on, while the three older records are still within
    `4 × I` (32 hours for an 8-hour series).
  - **Invalid newest record** (interval 0, 3, 12 or empty; non-finite rate): unavailable,
    never falling back to three older valid records.
  - **Insufficient history:** zero, one and two usable records, including at replay
    start, are all unavailable.
  - **Invalid older record:** an unaccepted interval on `r1` or `r2` makes the signal
    unavailable through the uniform-interval check. A non-finite rate on either
    older record also makes it unavailable, without substituting another record.
  - **Unseen shortening with missing changed record:** three valid 8-hour records
    remain available after the unknown 4-hour deadline and before the old
    `scheduled(r3) + 8 h + 60 s` deadline; at the old deadline they are unavailable.
    This explicitly tests the convention's detection limitation.
  - **Duplicate scheduled times:** an integrity failure.
  - **Rate boundary:** exactly +0.0005 does not count as above.
  - **Usability boundary:** exactly at `calc_time + 60 s`, and one second before it.
  - **Overdue boundary:** exactly at `scheduled(r3) + I + 60 s` (unavailable), and one
    second before it (available).
  - **Recovery:** after a gap and after a transition, the exact first observation at
    which the signal is available again.
  - **Existing grids and exits:** unchanged in every unavailable state.
- **Runs:** G on its own (V0 + G), and **C + G** as a declared interaction.
- **Reported:** the number of grids blocked, the hours blocked, and the lag between
  settlement and effect.

### H: Bitcoin cycle context (owner proposal via Bob, included 2026-09-24)
- **Halving constants:** the dates are historical facts, so they are fixed in the spec:
  - block 420,000 at 2016-07-09 16:46:13 UTC;
  - block 630,000 at 2020-05-11 19:23:43 UTC;
  - block 840,000 at 2024-04-20 00:09:27 UTC.

  The phase `m` is the number of **whole calendar months** since the most recent halving
  at or before the observation: `(year − year_h) × 12 + (month − month_h)`, minus 1 if
  the observation's day-of-month and time of day are earlier than the halving's. All
  three halving days are ≤ 20, so every month contains the anniversary instant. Phase
  bands are half-open: `[0, 18)`, `[18, 30)`, `[30, 48)` and `≥ 48`.
- **Data:** each traded pair's own completed **daily closes** (P3), with its SMA200.
  **ATH** is the highest completed daily close since the most recent halving, which
  requires daily data from that halving onward (P3 extended accordingly).
  - **Incomplete history:** if a pair's daily data does not reach back to the halving,
    for example because it was listed after it, its ATH is **unavailable** and H3 never
    relaxes entry for that pair. H2 does not use ATH and applies as normal. An ATH
    counted from the listing date is never substituted. Unavailability is reported.
  - **P8 evidence (Bob, 2026-09-25):** SOLUSDT daily data starts on 2020-08-11, three
    months after the 2020-05-11 halving, so SOL's H3 is unavailable until the 2024
    halving. This affects only `practice-2022` SOL, which is already outside the
    primary comparison (P4). BTC, ETH, XRP and ADA daily data is complete from 2020-01,
    and all five pairs have it for 2024-04 to 2024-12 (the surveyed range; 2025 onward was not examined).
- **H2, overextension guard:** for `m` in **[18, 30)**, if `C > 1.60 × SMA200`:
  - no new grid;
  - existing grids use a **2-hour** outside-range threshold instead of 6 hours.

  This is stricter, so it is allowed under the §3 rule.
  - **Running timers:** H2 changes only the *threshold* a running outside-range timer
    is compared with, never its start time `t0`. If H2 turns on while a timer runs,
    the exit happens at the first valid observation with elapsed time ≥ 2 h (at once
    if already past it). If H2 turns off, the threshold returns to 6 h from the same
    `t0`. A timer is never reset, restarted or extended beyond V0's 6 h by H2.
- **H3, deep-discount relaxation:** for `m` in **[30, 48)**, if `C < 0.50 × ATH`, the
  opportunity score minimum is lowered by 0.10 (0.70 → 0.60) for **new grids only**.
  - Every other regime, eligibility, liquidity, spread and risk check still applies.
  - H3 never changes a risk limit.
  - It is the only mechanism in v1 that loosens an entry gate, and it is reported
    separately (grids opened only because of H3, and their P&L).
- **`m` in [0, 18) or ≥ 48:** no change from V0.
- **Runs:** H on its own (V0 + H), and **C + H** as a declared interaction.
- **Reported:** the phase of every evaluated bar, and the H2 and H3 activations.

## 4. Matrix

| Axis | Values |
| --- | --- |
| Variants | V0, A, B, C, D, E, F, G, C+G, H, C+H |
| Baselines | **Ungated V0** (the replay's `strategy: "ungated"`: V0 without the opportunity gate), for C6 only. It is run everywhere V0 runs and is never eligible for selection. |
| Fees | **Primary:** Revolut X, maker 0 / taker 0.0009. **Sensitivity** (reported, not used for acceptance): 0.001 / 0.001. **Kraken scenario** (reported only, not used for acceptance, owner decision 2026-10-02, D5): maker 0.0025 / taker 0.0040 (Kraken lowest public tier; fee schedule to be verified before first run). Moving to Kraken as the live venue reopens acceptance from scratch under the applicable fee scenario — v1's verdict does not carry over to a different exchange. |
| Windows and pairs | `verify-2024h1` (ADA, BTC) and `practice-2022` (BTC, XRP, SOL), each extended with daily warm-up (P3). |
| Intrabar paths | `high_first` and `low_first`, both always reported. No path is chosen after seeing results. |
| Capital | 100 quote units per run, independent per pair. |

- **Unchanged inputs:** slippage 0.05%, assumed spread 0.05% and participation 10%.
- **Reporting:** every attempted run is reported, including invalid runs, halts and zero
  trades.

**Sensitivity schedule (owner decision 2026-10-02, D10 — reported only, not used for
acceptance):** the following sweeps are pre-registered with their values fixed here,
before any C1–C6 result is seen. Each sweep varies exactly one parameter from the
primary run; all other inputs stay at their primary values. Results are reported
alongside the primary but never used for variant selection or acceptance decisions.
Choosing these values after seeing results would be tuning; they are fixed now.

| Sensitivity | Parameter | Primary value | Sweep values |
| --- | --- | --- | --- |
| Spread | Assumed quoted spread | 0.05% | 0.10%, 0.20% |
| Participation | Volume participation cap | 10% | 5%, 20% |
| Missed-fill | Fill trigger: how far a quote must cross a resting limit (`fill_trigger_rate`, D9) | 0.05%, equal to the slippage | 0.02%, 0.10% |
| Timing | Bar offset (decision delay) | 0 bars | +1 bar, +5 bars |

The fill-trigger setting exists only for this labelled sweep (owner decision 2026-10-05,
D9): `--fill-trigger` sets it, and `results.json` and the output directory name record
it. Exits, marks and costs keep the slippage, and every other run leaves the setting
unset, so its resting fills use the slippage as before.

The fee sensitivity (0.001 / 0.001) and the Kraken scenario are already registered
above. Together these cover: cost drag (fees, spread), fill realism (participation,
missed-fill), and execution delay (timing). The path sensitivity (`high_first` /
`low_first`) is already part of every primary run and requires no separate sweep.

## 5. Validity and the comparison mask

**Comparison mask, fixed before any variant runs.** For each pair-window, the following
variant-independent checks are run first:
- the manifest and checksums;
- the hourly/minute and daily/hourly cross-checks, and, when the market proxy is not a
  traded pair, the completeness of its hourly bars over warm-up and evaluation (every
  hour exactly once) plus its daily/hourly cross-check;
- the same hourly completeness for every untraded **breadth-basket** symbol. The feature
  engine skips a stale basket member and still counts the remaining votes, so an
  unexplained gap would silently change breadth. Only an absence documented in the
  dataset spec's `[[basket_exclusions]]` (symbol, `from` inclusive, `to` exclusive, whole
  UTC hours, a non-empty reason such as a listing date) is exempt. The proxy and traded
  pairs cannot be exempted. Neither current dataset needs an exclusion: all basket
  symbols are complete over warm-up and evaluation (checked 2026-09-25);
- **integrity rules `drift-tolerance-v1`** (owner decision via Bob, 2026-09-24): a bar
  whose open, high, low and close match exactly and whose volume differs by at most
  0.1% of Binance's figure is counted as volume drift, not as a failure. Every other
  difference, and every missing or duplicated bar, stays fatal. The rules' name and
  tolerance are written to every `results.json`; `--strict-volume` (`strict-v0`, exact
  volume) stays available as a check. Features read Binance's 1h archive as published,
  so a drifted hour feeds its archive volume (within 0.1% of the minute sum) to the
  volume features; prices are identical, and fills use the minutes. Evidence
  (2026-09-24): `verify-2024h1` is valid in both modes; `practice-2022` is valid under
  `drift-tolerance-v1` and invalid under `strict-v0` because of one drifted daily bar
  per pair in its warm-up;
- warm-up sufficiency;
- the availability of sourced exchange filters (P4).

A pair-window that fails any of them is **excluded for every variant alike** and listed
with the reason. Exclusion is per pair-window: a pair can be excluded from one window
and kept in another. The mask is written to the results before scoring and cannot
change afterwards. Every current `practice-2022` SOL pair-window fails the filter check
unless P4 sources historical filters
([fee-levels-2026-09.md](backtests/fee-levels-2026-09.md), tick-size mismatch).

**Minimum evidence:** each development window must keep at least 2 included pairs.
Otherwise the outcome is "insufficient evidence", not a winner.

**Run validity:** a run in the mask is valid when:
- there are zero accounting problems, including the P6 reconciliation;
- there are zero rejected frames.

An invalid run **fails its variant** (C4). A failure in one variant never removes the
pair for the other variants.

## 6. Acceptance and selection (owner decisions, 2026-09-24)

**Economic bar (owner note, 2026-10-02):** passing C1–C6 is a necessary condition, not
a sufficient one. A return of ~5% over 6 years is approximately 0.8% annualised — worse
than a savings account and not worth the operational overhead of running a bot. The
variants need to demonstrate meaningfully positive annualised returns (target: well above
5% per year) across the binding windows. C1–C6 set the floor for scientific validity;
economic viability is a separate, higher bar that the owner will assess from the R1
metric and the raw return figures. Passing both justifies at most the step §8 allows, a
proposal for paper trading against live Revolut X prices; it never justifies live
capital directly. A development winner that barely clears C1–C6 is not automatically a
green light. *(Wording made consistent with §8 on 2026-10-05: the note said passing would
"justify live deployment" and let the owner decide whether to "proceed to a live pilot",
which §8 does not allow. The owner's bar itself is unchanged; Codex's review of #163.)*

The owner compared his criteria from this conversation with Bob's proposal
(`2025-09-25-owner-acceptance-criteria.md`) and chose this combined set. Acceptance is
judged at the primary fees. A variant passes when **all** of C1–C6 hold across its
included runs (every included pair, window and path):

| # | Criterion | Source |
| --- | --- | --- |
| C1 | **Worst drop,** on two bases in every run. **(a)** The max drawdown of **total equity** (active equity per `Account.equity` plus both reserves) is ≤ **10%** of its running peak. **(b)** The drawdown of **active equity** against the **C1(b) measurement reference** is ≤ **10%**. That reference follows the runtime's reserve-adjusted `risk_high` exactly, including the proportional settlement adjustment and every new active high, but it is never rebased (amendment 1, §3); before amendment 1 the two were the same value. C1(a)'s total-equity peak is a running maximum that is never scaled and never rebased. It is sampled at every pre-fill and post-fill risk evaluation, and **any hard-drawdown halt fails**. Both are measured from peaks, so after growth 10% can exceed 10 quote units. | Owner |
| C2 | **Makes money on the worse path:** for **each** intrabar path separately, the median return across included runs is > 0 after fees; **and** the mean return across all included runs is > 0. All runs have equal weight, and the median of an even count is the mean of the two middle values. | Owner, with Bob's worse-path rule |
| C3 | **Safer than holding:** in every included run, max total-equity drawdown < that run's buy-and-hold max drawdown (common sampling, P2). A run where buy-and-hold has zero drawdown fails. | Owner (strict) |
| C4 | **Integrity:** every included run is valid (§5). | Both |
| C5 | **Minimum activity:** for each included run, its rate = completed cycles (P7) ÷ (evaluation window length in days ÷ 7). The window is `[start of the start month, end of the end month)` in UTC, the same for every run in a dataset, whether or not the run halted. C5 = the arithmetic mean of the per-run rates over all included runs (equal weight), computed exactly (no rounding), and must be **≥ 1**. The ISO-week counter is reported, not scored. The share of bars holding inventory is reported. **C5 and C2 are unchanged for trend-gated variants (owner decision 2026-10-02, D4):** a variant that is idle during downtrends correctly scores zero activity and zero return on those runs; the Down-period readout (D3, above) answers the bounce question separately and is the right diagnostic for that period, not a relaxed criterion. | Owner's compromise on Bob's 10%-invested rule |
| C6 | **The gate earns its place:** in at least **60%** of included runs, the variant's return ÷ max(max drawdown, 0.1 percentage points) exceeds that of the **ungated V0 baseline** in the same pair, window and path. | Bob |
| C7 | **Survives the family — adopted in principle, not yet binding.** The owner decided on 2026-09-27 to replace the deflated Sharpe ratio, which has no content on this family ([why](reviews/2026-09-27-claude-dsr-coherence.md)), with a Holm step-down over the disclosed family at family-wise 5%, evaluated on the selected winner only and gating the reserved-window run. The statistic is the one-sided p-value `p = 1 − Φ( SR · √(T_eff − 1) / √(1 − γ3·SR + (γ4 − 1)/4 · SR²) )` on each variant's worse path, using the series, moment conventions and `T_eff` of [draft spec part 3](reviews/2026-09-27-claude-dsr-return-series.md) §8 with `SR0` = 0. **C7 does not gate anything until all three of the following are settled and recorded here** (Codex, 2026-09-27): (a) the return series C7 is computed on — §4 defines two windows, while part 3 requires 25 walk-forward folds whose geometry is still a proposal, and the two give different `T`, `SR` and `T_eff`; (b) the family, since `N_family` = 17–18 and 21–22 (18 and 22 used as working figures, since R1's code state is unknown; the coherence record's 16–17 and 20–21 plus V0 on `drawdown-recovery-v2`, which amendment 2 counts as one further registered trial) are **floors** (unpublished inspected runs are known to exist), and a Holm cutoff from a floor does not control the stated error rate — either the missing trials are accounted for in the register or a conservative budget is preregistered; (c) Codex's and Bob's acknowledgment, since all three agents agreed to the DSR (Bob, PR #123 review, 2026-09-27: "I agree with retiring the frozen DSR in favor of the Holm step-down (C7) once settled", an acknowledgment conditional on C7 being settled; Codex's is owed). **Until C7 is settled and acknowledged, or the owner explicitly waives it in writing, nothing runs on the reserved window.** The owner's decision was that a multiple-testing test gates that run, so an unresolved C7 is a hold on the run, not permission to proceed under six criteria. C1–C6 remain the binding set for development selection in the meantime. | Owner in principle; specification open |
| R1 | **Economics, reported only:** the capital at which the mean monthly return would cover €5/month of hosting (5 ÷ mean monthly return fraction), or "not reachable" if the mean return is ≤ 0. Running on the owner's own PC costs €0 in hosting. | Bob, as information |

*Note on units (added 2026-09-27, clarification only; no criterion changes).* Every
replay result is in USDT quote units with no EUR conversion
([BACKTEST_METHOD](BACKTEST_METHOD.md), "Currency"), and capital is 100 quote units per
pair (§4). R1's hosting cost is in euros. R1's arithmetic is sound because a monthly
return *fraction* has no unit, but it assumes the USDT return equals the EUR return,
i.e. it ignores EUR/USDT exchange-rate movement over the month.

**Down-period readout (owner decision 2026-10-02, D3 — reported only, not scored):**

Before any variant result is inspected, the following slice is pre-registered. It is
computed from the same replay data as C1–C6 and reported alongside the scored results,
but it does not change any criterion, any ranking or any acceptance decision.

- **Purpose:** answer the owner's question "in downtrends, does stepping aside outperform
  staying in and collecting bounces?"
- **Days counted:** calendar days on which Variant A's own daily classifier assigns the
  Down state to the traded pair, per pair separately. Days outside the evaluation window
  are excluded. Middle, Up, Recovering and Unavailable days are not counted.
- **Arms compared** (three, per pair and window):
  - *Ungated V0* — the always-grid baseline (the true "keep gridding" arm; see correction
    1 in the strategy audit 2026-09-29).
  - *Gated V0* — V0 with the regime gate active, reported alongside for context.
  - *Variant A* — the step-aside arm.
- **Measures reported on Down days only:**
  - Cumulative return (mark-to-market, fees included) over those days.
  - Forced-exit P&L broken down by exit reason (`trend_exit`, `range_exit`, `drain`).
  - Completed buy-and-sell cycles whose sell filled on a Down day.
  - Regime-label mix (RANGE / BULL / BEAR / TRANSITION / STRESS share) on those days,
    showing whether Down-state days were also classified as BEAR by the regime detector.
- **What this readout cannot do:** it is conditioned on the same data used for variant
  selection and therefore cannot serve as acceptance evidence or change C1–C6 verdicts.
  It answers the strategic question; it does not add a trial to the family count.

**Selection (deterministic):**
1. The **eligible set** is the passing variants among V0, A, B, C, E (only after Codex's
   implementation review, §3 E), F, G, C+G, H and C+H. D is excluded
   before ranking.
2. Let `M` be the highest mean return in the eligible set, in percentage points rounded
   to 6 decimals. The **tie set** is every eligible variant with mean return ≥ `M − 0.25`
   (inclusive).
3. Within the tie set, pick the lowest mean total-equity max drawdown, rounded the same
   way.
4. If still tied, pick the first in the fixed simplicity order V0, A, B, F, G, H, E, C,
   C+G, C+H.
5. D **cannot be selected.** C1–C6 are still computed and reported for D, for
   information only, next to the winner.
6. **C7** selects nothing and does not change the ranking. Once settled it is evaluated
   after steps 1–5 on the selected winner only. While it is unsettled, steps 1–5 still
   produce a development winner, but the reserved window stays closed (see its row).

**No winner:** if no variant passes C1–C6, v1 ends with "no winner". Nothing runs on the
reserved window, and the report says so. A development winner that passes C1–C6 does not
by itself open the reserved window: C7 must first be settled and passed, or explicitly
waived by the owner (see its row).

## 7. Reserved evaluation (run exactly once)

**What "untouched" means here:** no replay has been run on this window. It is **not** an
unseen regime:
- While researching the Bitcoin cycle with the owner (2026-09-24), Claude read reports
  of the peak on 2025-10-06, the roughly 50% decline and the June 2026 low. That
  knowledge motivated variant A.
- The window is therefore a prospectively reserved replay window, and its result is
  weaker evidence than a truly unseen period.
- Failures on it are recorded as they are. No variant is retuned and rerun on the same
  window, and a failed attempt is never replaced or reused as a fresh evaluation.

**Prior exposure record (as of this draft):**
- **Seen in chat:** Claude read public reports of the 2025–26 BTC regime (the peak on
  2025-10-06, the roughly 50% decline and the June 2026 low).
- **Not done:** no 2025–26 archive data has been downloaded, and no 2025–26 replay,
  feature or statistic has been computed.
- **Outside the window:** the live-stream and Revolut X order-book checks of September
  2026 fall after it.

Any later exposure before the run is added to this record.

**Frozen before access:** the following are frozen and recorded before the window's data
is fetched:
- the code commit, config, spec version and dataset spec;
- the universe (the pairs listed below);
- the comparison-mask rules (§5);
- the scoring (§6);
- the execution conventions.

Fetching and verifying the data are part of the run and happen only after the owner's
go. The manifest hashes are recorded at that moment and are then fixed.

**Technical reruns:**
- **Allowed** only when a run is invalid because of a harness defect that does not
  change strategy, parameters or data. The fix must be reviewed by Codex, and both the
  failed and the rerun artifacts are kept.
- **Not allowed** for data invalidity: that pair-window is excluded under §5.
- **Not allowed** for a strategy result the owner dislikes.

**Holdout mask:** the §5 rules apply. If fewer than 3 of the 5 pairs are included, the
outcome is "insufficient evidence", not a pass. There is no silent averaging over the
surviving pairs, and every exclusion is listed.

**Owner gate:** this run starts only after the owner explicitly says go in the
conversation. That go is recorded in the report with its date. Finishing §2–§6 does not
start it automatically. Before asking, Claude reports:
- the practice-matrix results;
- the winner, or that there is none;
- the exact code commit, config, dataset specs and manifests to be used, all frozen.

- **Window:** 2025-01 to 2026-08. This is the latest complete month before this spec. It
  includes the October 2025 peak and the decline that followed.
- **Pairs:** BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT and ADAUSDT as Binance proxies for the
  Revolut X EUR pairs, fixed now. The daily warm-up starts in 2024-04.
  - The set is wider than the development windows on purpose: it is the five
    EUR-quoted coins the owner is likely to trade on Revolut X.
  - ETH is absent from the development windows only because of archive defects in
    `practice-2022` (see that spec).
  - **Robustness set (reported, not deciding):** DOGEUSDT, LTCUSDT, LINKUSDT, AVAXUSDT
    and DOTUSDT, plus every pair that was in Binance's top 30 USDT spot pairs by quote
    volume in 2024-12 and was delisted before 2026-09. That list is determined from the
    2024-12 archives and Binance's delisting announcements, and frozen before the window
    is fetched.
  - This answers Bob's survivorship concern without letting coins that cannot be traded
    on Revolut X decide the result.
- **Runs:** the winner, V0, ungated V0 (the C6 baseline) and D, at the primary fees, on
  both paths.
- **Data problems:** a pair that fails integrity is reported as invalid and is **not**
  replaced by another pair.
- **Judging:** the result is judged against C1–C6 on the five deciding pairs and
  reported whether it passes or not. R1 and the robustness set are reported alongside.
  A pass does not authorise live trading; it only justifies the next step, a proposal
  for paper trading on live Revolut X prices, which needs its own review.

## 8. Scope of the evidence

- The simulation replays **Binance USDT** market data with **Revolut X fees**. It is a
  cost-sensitivity experiment, not a backtest of Revolut X EUR execution: Revolut X
  prices, spreads, queue positions, depth and post-only behaviour are not simulated.
- A pass justifies at most a proposal for paper trading against live Revolut X prices.
- **Wide-spread frames (owner decision 2026-10-05, D8).** A frame whose quoted spread is
  above the 0.15% eligibility limit is rejected as bad data, and on it the engine runs no
  risk check, no outside-range clock, no drain and no retry of a halt's liquidation.
  This stays for v1, and replay cannot reach it: it assumes a constant 0.05% spread. A
  live or forward paper feed can hold wide spreads for long stretches, keeping falling
  coins with no exit path, so whether to run the risk checks and forced exits on such
  frames must be decided before any live or forward paper run.

## 9. Sources

Venue terms and research claims that motivated this spec. They were checked on
2026-09-24 and may change.
- Revolut X fees: <https://www.revolut.com/legal/crypto-exchange-fees/>
- Revolut X API, including post-only orders and rate limits:
  <https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api>,
  <https://developer.revolut.com/docs/x-api/place-order>
- Inventory-aware market making (Avellaneda–Stoikov):
  <https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/>
- Short-horizon crypto mean reversion (about 1.3 bp gross per trade):
  <https://arxiv.org/abs/2608.21888>
- Trend following in crypto: <https://arxiv.org/pdf/2009.12155>,
  <https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals>
- Bitcoin four-year cycle, 2025 peak and 2026 status:
  <https://www.fidelity.com/learning-center/trading-investing/four-year-bitcoin-and-crypto-cycles>,
  <https://coinmarketcap.com/academy/article/%20bitcoin-4-year-cycle-october-2026>

## 10. Not decided in v1

These stay open; each needs its own specification:
- the policy after a large loss (cool-off or permanent stop);
- quote skewing;
- a Revolut X price feed;
- any live-trading work;
- a README change to the "Binance spot only" operating rule. Revolut X is named here
  only as the fee scenario and as the venue for a possible later paper-trading
  proposal, which needs its own review.
