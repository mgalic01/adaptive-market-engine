# Claude: a flat account past the 8% soft drawdown never trades again — options for discussion

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** When a V0 replay ended up flat at 8% or more below its
  high-water mark, it sat in cash for the rest of the window: at least 102 to 235 days,
  and in every case until the data ended (section 2). A live bot
  in the same state would stay stopped with no command that restarts it. This asks for a
  decision **before any variant runs**.
- **Owner position.** The owner first chose "fix it, disclosed", meaning trade at the
  risk engine's intended 25% size. When I showed that 25% cannot place a grid in the
  100-USDT replay (section 4; live EUR minimums are unverified), the owner asked for this three-agent discussion before deciding. **The
  policy decision is the owner's.**
- **Revision 2 (same day)** answers the Codex local worker's six required fixes and Codex
  Cloud's five inline findings. Section 9 maps each finding to its change.
- **Revision 3 (same day, session `a05e63c8`).** After revision 2, the owner saw a worked
  EUR 100 example and **leaned to option C**. They chose "restart after I review" for the
  hard stop, and asked for Codex's and Bob's views first. Both have answered (section 8).
  Section 4 now specifies C fully, with every clarification they asked for, and closes the
  open items from revision 2. **The owner has not decided yet.** Two decisions remain
  theirs, and section 7 states both.
- **Revision 5 (same day, session `a05e63c8`): the owner has decided.** At about 20:00
  UTC the owner chose **option C**, granted the no-tuning exception **on record**, chose a
  **fully automatic restart after a 12% hard stop**, and declined a capital threshold
  (section 7). This revision turns those answers into a precise specification (§4 C) and
  the required content of the spec amendment (§5). It also closes Codex's five changes,
  Bob's two concerns, Codex Cloud's four findings and the full audit's three findings on
  revision 4 (section 9). **Next:** the scoped spec v1 amendment, as its own PR, then the
  code with the tests in §4 C step 9. No code is in this PR.
- **Revision 4 (same day, session `a05e63c8`)** answers Codex Cloud's four findings on
  revision 3. The most important one: B and C also need a **scoped amendment of spec v1**,
  not only a waiver of the no-tuning rule (§5, §7). Section 9 maps each finding to its
  change.

## 1. What the code does

At `de38fdb` (identical in `src/` and `config/` to `f937d67`, where the replays below
ran):

1. `RiskEngine.evaluate` returns `REDUCE` with `capital_multiplier` 0.25 when drawdown
   against `risk_high` is at least 8% (`risk/engine.py:63–68`).
2. `PaperSimulator._risk_action` pauses the account on any result other than `ALLOW` or
   `EXIT` (`runner.py:202–203`), so `REDUCE` becomes a pause. The 0.25 multiplier is never
   read.
3. A pause clears only on `ALLOW` (`runner.py:344`), and a range exit also clears only on
   `ALLOW` (`runner.py:332`).
4. A **flat** account's equity is `cash − pending`. It is constant, and settlement scales
   `risk_high` by the same factor, so a flat account's drawdown ratio does not change.
5. **So once the account is flat and still at 8% or more below `risk_high`, it gets
   `REDUCE` on every step, never reaches `ALLOW`, and never trades again.** This needs
   both conditions. Reaching 8% while holding inventory does not by itself lock the
   account: sells keep being managed, so equity can recover before the account is flat.
6. `resume()` cannot help: it requires a halted account, and this one is only paused.

`docs/PAPER_SIMULATION.md:55` documents the pause as intended: "cancel buys, manage sells,
block new exposure; recovery: risk limits must pass, then confirmed recovery". That
recovery condition cannot be met by a flat account past the threshold. Whether
indefinite stopping was *intended* in that state, the code does not say. The documents
describe a recoverable pause; the code produces an absorbing state. That mismatch is
what needs a decision.

## 2. The evidence from replays — reproducible from the appendix

A data agent in this session reproduced the published V0 runs at `f937d67`. They
matched `docs/backtests/verify-2024h1.md` and the V0 scorecard within rounding. I then
re-ran the appendix script myself over its three `results.json` files; it reads only
those files, and no new run or market data is involved. Inputs, by SHA-256:

| Run folder (under the data directory's `backtests/`) | `results.json` SHA-256 |
| --- | --- |
| `verify-2024h1/20260927T112224Z-m0.001-t0.001` | `32629224a8806303966a8455da1ab05da8b0fb609185661778ee848ac8213c0d` |
| `practice-2022/20260927T120713Z-m0-t0.0009` | `c8dfa273065e89f5e6f5f871acb49db5f9dfea6b781abf1ad4d9dabdab2401f3` |
| `practice-2022/20260927T123547Z-m0.001-t0.001` | `ef9b608fee679f285fd742e684c82996feee0e03de2749ad08c7a3fc659921d8` |

The first file is byte-identical to the one the V0 check on PR #99 produced
independently. Anyone can regenerate all three with the unchanged CLI:
`run --spec config/datasets/<name>.toml`, with `--maker-fee 0 --taker-fee 0.0009` for
the second. On Windows it currently needs the launcher described on PR #99, which PR
#103 fixes.

Run it from the directory holding the run folders as
`python data/flat_stretches.py 7 <the three results.json paths>`. The script lists every stretch of **at least 24 hours of constant hourly total equity**
at a drawdown of at least 7% from its running peak, and whether equity ever changed
again. **Corrected in revision 4 (Codex Cloud):** the script counts consecutive **hourly
samples**, not elapsed hours. "At least 24 hours" means at least 24 consecutive samples
with equal equity, which is at least 23 hours between the first and last sample. The
script does not check that the samples are one hour apart, so a stretch can span a
missing hour. The reported lengths (for example "5,645 h (235 d)") are sample counts, and
the day figures are those counts divided by 24. The real elapsed time can differ in
either direction, by one hour at the ends and by any missing hours inside a stretch. The
conclusion (months in cash) does not depend on that precision, but the exact figures do.
A rerun that measures the time between the first and last timestamp is owed. Owner:
Claude, when the three `results.json` inputs are next available; they are not in this
checkout. **Corrected in revision 3 (Codex Cloud):** the script's word "RESUMED" means only
that a later hourly total equity differs. It does not inspect the pause state, orders,
fills or new grids, so it shows that **equity changed**, not that trading resumed. Below,
"equity changed" is used; a claim about trading needs the instrumented trace at the end
of this section. Results with the threshold at 7%:

- **Every stretch whose equity later changed started below 8%:** 7.54% and 7.34% (verify, BTC
  high-first ungated), 7.02% (practice 0/0.09%, BTC low-first ungated), and 7.19% and
  7.10% (practice 0/0.09%, SOL gated — invalid runs).
- **Every stretch at 8% or more lasted until the data ended (revision 5, full audit).**
  Each one's last sample is 2023-01-31 23:00, the last bar of `practice-2022`, so every
  one is **right-censored**: none was seen to change equity, but none could have been.
  The appendix's "never resumed" only means "the series ended while still flat". The
  lengths below are lower bounds from timestamps (samples minus one hour); I checked each
  end time by arithmetic. Leaving aside runs that ended in a hard halt (section 6):

  | Run | Starts | Drawdown at start (total equity) | Flat for at least |
  | --- | --- | ---: | ---: |
  | practice 0/0.09%, XRP gated, high-first / low-first | 2022-10-21 13:00 | 8.25% / 7.79% | 2,458 h (102.4 d), censored at 2023-01-31 23:00 |
  | practice 0/0.09%, XRP ungated, both paths | 2022-06-10 19:00 | 8.97% / 8.96% | 5,644 h (235.2 d), censored at 2023-01-31 23:00 |
  | practice 0/0.09%, BTC ungated, high-first / low-first | 2022-06-15 11:00 | 7.94% / 8.67% | 5,532 h (230.5 d), censored at 2023-01-31 23:00 |
  | practice 0.1%, BTC ungated, high-first / low-first | 2022-06-18 13:00 | 8.19% / 8.05% | 5,458 h (227.4 d), censored at 2023-01-31 23:00 |

  No finite replay window can show how long such a stretch lasts. Section 1's code
  argument is the real basis for acting; the replays only fail to contradict it.
  **Withdrawn:** "No stretch at 8% or more ever changed equity again", which read
  censoring as evidence. The owner was shown "235 days in cash" when deciding; read it
  as "at least until the data ran out".
- **A second cause is possible (revision 5, full audit).** An unsellable remainder below
  the exchange's minimum order also froze accounts, with no halt and no pause. PR #122
  fixes it (engine `exit-residue-v1`). Any frozen tail above could be that rather than the
  8% lock. Comparing each run's `final_inventory` with `min_notional` settles it without a
  rerun. **Not done:** the three `results.json` files are not in this checkout. Owner:
  Claude, together with the timestamp rerun; the corrected script
  (`scripts/flat_stretches.py`, which labels each stretch CHANGED or CENSORED and measures
  span from timestamps) is in PR #122.

**What this does and does not show.**
- Constant hourly total equity is consistent with a flat account and no trades. It
  does not prove either: an account holding inventory whose mark never moved would
  look the same, which is implausible over months but not excluded by this data.
- The engine tests **active** drawdown against `risk_high`, while the script measures
  **total** equity, reserves included, against its own peak. Two stretches start below
  8% on this measure (7.94% and 7.79%). They are consistent with active drawdown at 8%
  or more, but that is not observed here.
- The run reports log the frozen tail mostly as "outside-range timeout: waiting in
  cash…", because the range-exit branch overwrites the pause reason. For example,
  232,870 bars for XRP gated high-first.
- A per-step instrumented trace would settle all three points. It needs no new market
  data, only a replay with logging.

## 3. What it does to the experiment

- **Grid variants only.** Every grid variant (V0, A, B, C, E, F, G, H, C+G, C+H) keeps
  V0's soft-drawdown control (spec v1 §3). Benchmark D is exempt from all risk controls
  (spec §3 D), so it is unaffected. My first version wrongly said "every variant".
- **Returns after the account is flat past 8% are cash returns**, whatever the market
  did. C2 (returns on the worse path) and C5 (activity) are then partly scored on months
  in which the bot could not trade. Comparisons between grid variants partly measure
  which one reaches that state first.
- **For a live €100 bot:** once it is flat past 8%, it stops trading and waits
  indefinitely, with no operator command to restart it.

## 4. The options

**A. Trade at 25% size (the engine's multiplier). Infeasible in the 100-unit replay.** A
prototype is on branch `claude/soft-drawdown-reduces` (`5dec062`, not proposed for
merge). A grid needs at least 6 levels (`config/default.toml`, `minimum_levels = 6`),
each at least the minimum notional plus the fee (about 5 units). A quarter of the normal
80% budget at 100 is 20, against about 30 needed, so the account sits in cash exactly as
before. Three of the prototype's tests fail for that reason. It works only once equity is
roughly 150 or more. **Corrected in revision 3 (Codex Cloud):** these are **USDT quote
units** from the Binance instrument manifests used by the replay, which does no EUR
conversion (`docs/BACKTEST_METHOD.md`). They show that A is infeasible for the current
100-USDT replay. They do not establish a live EUR venue's minimums, which are unverified.

**B. One cool-off per drawdown episode, then trade at normal size. This is a relaxation
of the soft limit, not a restoration.** My first version called B a restoration of the
documented recovery. Codex is right that it is not. At the end of the cool-off the
account is still past 8%, so the engine still says `REDUCE`, which the documented
contract treats as "limits not passing". B lets the bot trade at normal size anyway.
That is a new, looser risk policy, and it needs the owner's explicit approval as one.

Fully specified, B would be:

1. **Episode start.** The first `REDUCE` outside an episode starts an episode. Resting
   buys are cancelled, sells are managed, and the account pauses — as today. The start
   time is saved in the paper state (a new field, so a schema change). **The clock is the
   quote's `observed_at`** (Bob). Elapsed time is `observed_at` of the current frame
   minus the saved start, compared as `>= 24 h` with no rounding.
2. **Cool-off.** The pause may clear only after **at least 24 hours** from the episode
   start, *and* after the normal recovery confirmations (`recovery_frames`), *and* only
   while the risk result is not `PAUSE` or `EXIT`. My first version said "the next UTC
   day", which could mean seconds for a trigger just before midnight. 24 hours avoids
   that; it is a number, and section 5 deals with that.
3. **After release, inside the episode.** `REDUCE` no longer pauses and no longer
   shrinks orders; the bot trades at normal size. The daily-loss pause (`PAUSE`) and the
   12% trigger (`EXIT`) still act exactly as today.
4. **Re-arming.** The episode ends at the first risk result of `ALLOW`, meaning drawdown
   has come back under 8%. A later fall past 8% starts a new episode with a new cool-off.
   An episode therefore gives exactly one cool-off, however long it lasts.
5. **Interactions.**
   - A range exit may clear while released, on the same terms as step 3.
   - **Corrected in revision 3 (Codex Cloud):** a daily-loss pause during an
     **already-released** episode clears after the normal recovery confirmations when
     the risk result is `REDUCE`, not only on `ALLOW`. At the next UTC day the result
     goes from `PAUSE` to `REDUCE`, and requiring `ALLOW` would lock the account again.
     The initial cool-off is unaffected. A daily-loss pause neither starts nor ends an
     episode.
   - On restart, the saved episode start is restored with the rest of the paper state.
6. **Tests needed:** a trigger just before midnight; release after 24 hours; no re-pause
   while released; re-arming after `ALLOW`; a daily-loss pause inside an episode; a range
   exit inside an episode; restart in each state.

**What B preserves, stated precisely.** B keeps the 12% **emergency trigger** and its
accounting-adjusted reference: `risk_high` is still scaled at settlement and still
excludes the protected profit. B does **not** keep or guarantee any loss bound:
- The 12% trigger starts a liquidation; it does not cap the loss at 12%. Frames arrive
  at intervals, liquidation is limited by bid depth, and slippage applies, so the final
  loss can exceed 12%.
- It says nothing about C1, the separate 10% acceptance limit (owner decision,
  2026-09-26). Trading on past 8% makes a C1 failure more likely, not less.
- "About 4 percentage points of peak equity before the trigger" is a distance to a
  trigger, not a remaining loss allowance.

**C. Rebase the risk reference after a cool-off — chosen by the owner, 2026-09-27.**
Revision 2 said "not recommended", and I withdrew that; the owner has chosen C (section
7). C is specified below with every clarification Codex and Bob asked for. It is the
basis for the spec amendment (§5), not yet that amendment.

1. **Episode start.** As in B: the first `REDUCE` outside an episode cancels resting
   buys, manages sells and pauses. The start time is the quote's `observed_at`, saved in
   the paper state (a schema change).
2. **Rebase conditions.** On each valid frame of an open episode, in this order, before
   any state changes:
   1. at least 24 hours have passed since the episode start (`observed_at`, `>= 24 h`);
   2. the normal recovery confirmations (`recovery_frames`) have passed, counted over
      consecutive valid frames on which every condition other than drawdown passes:
      daily loss under 3%, no emergency flag, the frame and data checks, and the
      eligibility check (`scorer.score(...).eligible`);
   3. the account is not halted (a halted account follows step 7 instead).

   A range exit that is waiting in cash does **not** block these checks (see below).
   If all three hold, the rebase is computed **tentatively**: `risk_high` is set to the
   current active equity and the risk engine evaluates again. The rebase is committed only
   if that evaluation returns `ALLOW`; otherwise nothing changes and the check repeats on
   the next frame. So the rebase replaces only the drawdown failure. It never clears a
   daily-loss pause, an emergency, a data block or a halt (Codex Cloud P1 on revision 3).

   **The range-exit deadlock (Codex Cloud P1 on revision 4).** Today a range exit clears
   only when the account is flat, the risk result is `ALLOW`, the frame is eligible, and
   the price is back inside the range or the recenter cooldown has passed (`runner.py`,
   range-exit branch of `_step`). Revision 4 made the rebase wait for the range
   condition, while the range exit waited for `ALLOW`, which only the rebase can produce.
   Since most frozen tails were logged as range-exit waits, C would have left the main
   lockout in place. Revision 5 breaks the cycle by order: the rebase check runs first in
   the step and ignores the range-exit wait. After a committed rebase the risk result is
   `ALLOW`, so the existing range-exit rule applies unchanged, in the same frame or a
   later one. The pause then clears after the usual `recovery_frames`, as after any range
   exit today.
3. **One reference moves.** The 8% and the 12% triggers are both measured from the
   rebased `risk_high`. There is no separate hard-stop reference (Bob's structural note).
4. **Losses are not bounded across episodes.** Each episode can lose about 12% of its own
   starting equity before the trigger, and more through gaps, bid depth and slippage.
   Example: EUR 105 peak, flat at EUR 96, rebase, next 12% trigger near EUR 84.50.
5. **Recording, restart and repeats.** Each rebase is recorded in the paper state and the
   report: time, old and new reference, and the episode start. The episode ends at the
   rebase, so an episode has at most one rebase. On restart, the saved episode start is
   restored, and the cool-off continues from it rather than starting again. Evaluating
   the same frame twice cannot rebase twice, because the second evaluation finds no open
   episode.
6. **Acceptance is untouched: two measurement peaks, neither rebased (revision 5,
   Codex).** C1 has two bases, and each keeps today's definition:
   - **C1(b), active equity:** measured against a separate reference that follows
     `risk_high` exactly as today, including the proportional settlement adjustment in
     `_settle` (`account.risk_high *= factor`), and rises with every new active high. It
     is exempt only from the loss rebase.
   - **C1(a), reserve-inclusive total equity:** measured against the running peak
     `max(old_peak, total_equity)` that `replay.py` tracks today. It is **never** scaled
     at settlement, because moving profit into the protected reserve does not lower total
     equity. Example: total peak 120; settlement moves 10 into the reserve, so active
     capital falls to 110 while total equity stays 120, and the peak stays 120. Scaling it
     to 110 would hide a later fall of total equity to 115.

   Neither peak is ever reset by a rebase or by a restart after a hard stop. Revision 4
   wrongly applied the settlement adjustment to both.
7. **Hard stop: automatic restart after a cool-off (owner decision, 2026-09-27).** The
   owner chose "fully automatic": no operator command and no overall loss floor. This
   replaces revision 4's owner-audited command.
   1. **Which halts.** Only a halt caused by the 12% hard drawdown. Every other halt
      stays latched and manual, as today: the emergency flag; capital exhaustion, where
      there is no active equity to rebase to (PR #122 makes it final); and, as a
      **proposal** from session e0b16be3 not yet confirmed by Codex, Bob or the owner,
      integrity halts (invalid data, an unexpected symbol, an accounting invariant
      failure). The halt reason is recorded when the halt starts, so the restart can tell
      them apart.
   2. **Cool-off.** At least H hours of `observed_at` since the halt started. H is a new
      parameter that the spec amendment must fix before any rerun. **Proposal: H = 24
      hours**, the same number as the soft cool-off, so the fix adds one parameter, not
      two.
   3. **Liquidation finished, and every existing precondition kept.** Named explicitly
      (Bob, Codex): the account is halted, flat (no inventory), has no open orders,
      reconciles (`account.validate`), the frame is valid (`_validate_frame`), and the
      **eligibility check** (`scorer.score(frame.candidate, regime).eligible`) passes.
      While a forced liquidation is incomplete, nothing happens.
   4. **Tentative rebase, then `ALLOW`.** As in step 2: `risk_high` is set to the current
      active equity and the risk engine evaluates again. Only if the result is `ALLOW`
      (daily loss under 3%, no emergency flag) is the halt cleared (Codex Cloud P1).
      Otherwise nothing changes and the check repeats.
   5. **On restart** the halt clears as `resume()` clears it today: grid bounds and range
      timers are reset, and the normal recovery confirmations apply before a new grid.
      The event is recorded: halt start, halt reason, restart time, old and new reference.
      A halt restarts at most once; a new halt is a new event.
   6. **What the owner accepted, knowingly.** Cumulative losses have no floor. The owner
      saw a EUR 100 chain (peak 105, then 96, then 12% triggers near 84.50, 74.30, 65.40
      and onwards) and declined a floor: "the bot will be able to pick a good strategy
      and continue working on his own". C1's 10% limit still judges every run.

   This contradicts two current rules, which the amendment must supersede for drawdown
   halts only: spec v1 calls the hard-drawdown halt latched, and
   `docs/PAPER_SIMULATION.md` says it never clears automatically. PR #122 (open) makes
   the manual `resume()` state that drawdown halts are final. The automatic path is
   separate from `resume()` and does not reopen that command.
8. **The daily-loss interaction** follows B's corrected rule: inside a rebased episode
   the drawdown is measured from the new reference, so a later daily pause clears on
   `ALLOW` as today.
9. **Tests needed:** a trigger just before midnight; no rebase before 24 hours; no rebase
   while a daily pause, an emergency or a data block is active; a rebase whose
   re-evaluation is not `ALLOW` is not committed; exactly one rebase per episode; a
   process restart before and after a rebase; **a range exit waiting in cash is released
   by the rebase** (the deadlock case); C1(b) scaled at settlement, C1(a) not, and neither
   reset by a rebase or a hard-stop restart. For the automatic hard-stop restart: not
   before H hours; not while partially liquidated; not on an ineligible frame; not while
   the daily loss is 3% or more or the emergency flag is set; never after an emergency,
   capital-exhaustion or integrity halt; at most once per halt.

**What C costs, plainly.** C trades at normal size again after every episode. That is
closer to the owner's "what's the point of trading if not trading", but the only loss
limit left is per episode. With the owner's automatic restart, nothing ends the
sequence; only C1 judges the result.

**D. Keep it and document it (not chosen).** Leave V0 as it is and read every result as
"trades until flat past 8%, then cash". **Corrected in revision 5 (Codex, Codex Cloud
P1):** only "leave as is" changes no trading behaviour. The operator resume that earlier
revisions attached to D was a separate change: clearing the pause alone re-pauses on the
next `REDUCE`, and an effective resume would rebase, which is option C by hand. It would
have needed its own decision, and D with it was not free of the rule question.

## 5. Is fixing it now post-hoc tuning? My answer, qualified

My first version concluded that a disclosed fix is not tuning. Codex's objection stands:
disclosure and registering another trial are **safeguards, not proof** that a change
complies with the owner's rule. The honest position:

- **In favour of acting now:** the absorbing state is visible in the code without any
  backtest (section 1). The replays confirmed it rather than prompting it. The
  documented contract promises a recovery that cannot happen, so doing nothing is also a
  choice with consequences (section 3).
- **Against treating it as neutral:** we have seen development results, including that
  V0 loses money and spends months in cash. Any option that lets the bot trade again
  (A at larger capital, B, C) changes V0's results, and we cannot un-know which way we
  hoped they would move. B's 24-hour cool-off is a number chosen after seeing results,
  however principled it looks.
- **What limits the damage whatever is chosen:**
  1. choose on the arguments, before any rerun, and never rerun V0 under several
     options to pick the best;
  2. keep the old V0 results published and labelled as the pre-fix behaviour;
  3. register the fixed V0 as an additional trial in part 2's count (PR #93);
  4. report both V0 versions side by side in any comparison.

Only D changes no trading behaviour. So D is the one option that is plainly not tuning,
and it leaves the experiment measuring a bot that stops for good after one bad episode.

**Revision 3, stated as a rule question (Codex Cloud P1).** B and C each contain a number
chosen after seeing development results: the 24-hour cool-off. The safeguards above
reduce the damage, but they do not make B or C comply with the rule as written. So B or C
requires the owner to **amend or waive the no-tuning rule for this one change,
knowingly and in writing**. D requires nothing.

**The owner's decision (2026-09-27, about 20:00 UTC).** The owner granted the
exception on record: "Yes, fix it (on record)". The no-tuning rule is waived for this one
change, with the pre-change results kept side by side and the fixed V0 counted as an extra
trial. Because the owner also chose a fully automatic restart after a hard stop (§4 C
step 7), the exception covers **two** controls: the soft-drawdown control and the
hard-drawdown halt. Session e0b16be3 told the owner so and asked them to say if they
meant otherwise.

**A spec amendment is also required (Codex Cloud P1 on revision 3; completed in revision
5).** A waiver does not change the registered spec. Before any code or rerun, a scoped
amendment to spec v1 must:
1. state both changed controls word for word, the soft-drawdown rebase (§4 C steps 1–6
   and 8) and the automatic restart after a drawdown halt (§4 C step 7), with every
   parameter fixed: the 24-hour soft cool-off and the hard-stop cool-off H;
2. apply them to **every grid variant identically** (V0, A, B, C, E, F, G, H, C+G, C+H).
   That makes the defined control and the baseline the same for every comparison. It
   does **not** make the effect equal: inventory paths and episode timing differ, so a
   variant's result relative to V0 can change, and the amendment says so (Codex);
3. make C6 compare against the **amended** V0;
4. keep the pre-change V0 results published, and register **both** V0 versions as trials
   in part 2's count (PR #93);
5. **supersede**, for these two controls only, spec v1 §3's "No variant delays,
   suppresses or clears any of them" and the statement that the hard-drawdown halt is
   latched, and update `docs/PAPER_SIMULATION.md` to match (Bob, Codex);
6. name the halts that stay latched and manual: emergency, capital exhaustion, and
   integrity halts if that proposal is confirmed.

The owner's decision sets the policy and grants the exception. The amendment is the
precise text, and it needs Codex's and Bob's review like any spec change.

## 6. Resuming after a hard halt — the same trap, conditionally

`resume()` requires the current risk result to be `ALLOW` (`runner.py:440`). That needs
drawdown under 8% and a daily loss under 3%. After a 12% trigger, the account is
liquidated. Whether it can ever be resumed depends on where liquidation ends:
- **If the account ends flat at 8% or more below `risk_high`, `resume()` can never
  pass.** In all five halted runs in section 2's data, the account ended between 11.50%
  and 12.63% below its peak on total equity, and never resumed.
- **If liquidation is slow and the price recovers first,** the account can end flat
  under 8%. Liquidation is bounded by `bid_size × participation` per frame
  (`execution.py`, `reduce_unreserved`). After the daily baseline rolls over, `resume()`
  can then pass. Codex Cloud raised this; my first version wrongly called the trap
  certain, and Bob's review repeated that.

Whether a hard halt should be final is a policy question for the owner. If it should be
final, the docs should say so and `resume()` should report it plainly. If an operator
should be able to restart after review, that needs a designed rule. **Codex disagrees
with Bob's suggestion of a privileged risk-check bypass as a routine remedy:** it could
defeat the emergency protection. I agree with Codex. **Revision 3:** the owner chose
"restart after I review". Section 4 C step 7 specifies that as an explicit, audited
command, not a bypass. Codex and Bob both accept that form. It can be adopted with B or
with D too; it does not depend on C. **Revision 5:** the owner then chose a fully
automatic restart instead (§4 C step 7). That closes this trap for drawdown halts through
the automatic path. The manual `resume()` stays as it is; PR #122 makes it state plainly
that drawdown halts are final for that command.

## 7. The owner's decisions (2026-09-27, about 20:00 UTC)

The owner answered in session e0b16be3, which explained each question with worked
examples and relayed the answers verbatim on this PR
([comment](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5859397628)).

| Question | Owner's answer |
| --- | --- |
| 1. Exception to the no-tuning rule, plus the spec amendment | **"Yes, fix it (on record)"**: fix the lockout, with the old and new results side by side and the fixed V0 as an extra trial |
| 2. B or C | **"C: reset the peak"** |
| 3. Restart after a 12% hard stop | **"B: fully automatic"**: restart on its own after a cool-off with a rebased peak; no overall floor, no owner involvement |
| 4. Capital threshold | **"No, one rule for all"** |

The owner's reasoning on the restart: "We are building this strategy with real data and
testing it, i'm kind of leaning to a stance that the bot will be able to pick a good
strategy and continue working on his own."

**Still open, and not the owner's decisions yet:**
1. The hard-stop cool-off H. Proposed: 24 hours (§4 C step 7.2). It is fixed in the
   amendment.
2. Whether integrity halts stay manual. Proposed by session e0b16be3, to be confirmed by
   Codex and Bob, then put to the owner.
3. The spec amendment text itself (§5). Owner: Claude, as a separate PR reviewed by
   Codex and Bob.

No code is proposed in this PR. The code follows the amendment, as its own PR with the
tests in §4 C step 9.

## 8. Positions

**On revision 4 (`15c5f37`, 19:00–21:40 UTC):**
- **Bob:** FLAGGED at `15c5f37` with two concerns: the amendment must supersede spec §3's
  prohibition, and the restart must name the eligibility check. Both are fixed (§5 item 5
  and §4 C step 7.3).
- **Codex desktop:** AGREE WITH CHANGES, with five changes, all taken (section 9).
- **Codex Cloud:** three P1s (the restart must keep the non-drawdown checks, the D
  resume, and the range-exit deadlock) and one P2 (the index duration). All are taken.
- **Automated review:** APPROVE, with two nits. The script is now committed in PR #122.
  Line citations: this revision cites code by function name instead of line number.
- **Full audit (session e0b16be3, 21:40 UTC):** censoring, a second cause, and the
  restart exclusions. All are taken (§2 and §4 C step 7).

**On revision 2 and the owner's preference for C (2026-09-27, 13:51–14:28 UTC):**
- **Bob** (FLAGGED at `339e25f`, one concern: name the clock for the 24 hours. This is
  fixed in §4 B step 1). On C, Bob asked for three things, each fixed in §4 C: define the
  rebase ordering (step 2); keep the C1 peak separate (step 6); make the owner-only
  resume audited (step 7). On a capital threshold: acceptable only with an explicit rule
  amendment.
- **Codex** ([14:28 UTC](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5856718186)):
  AGREE WITH CHANGES to drafting C as a paper-only proposal. This is not approval to
  implement or to waive the rule. Codex asked for four things, each done in §4 C: an
  explicit order before an atomic rebase that clears nothing else, plus restart and
  repeat behaviour (steps 2 and 5); a measurement peak that never resets but keeps
  rising (step 6); an audited owner-only resume with a clear control boundary (step 7);
  and no capital threshold (§7 question 4).
- **Codex Cloud** on revision 2: one P1 (the rule question, §5) and three P2s (the
  daily-loss recovery, "equity changed" versus trading, and USDT versus EUR). All four are
  in §9.
- **Automated Claude review:** APPROVE at `339e25f`, with two nits. It counts bars, not
  hours, which is disclosed in §9. The input hashes need re-hashing by whoever relies on
  them.

**On revision 1, at head `35231c9`:**
- **Bob:** a defect, and B. Bob considered the no-tuning argument sound provided the old
  results stay published and the fixed V0 is registered as a trial. Bob also called the
  hard-halt trap certain; section 6 now shows it is conditional.
- **Codex local worker:** the flat-account conditions imply an absorbing state that
  warrants investigation. They do not prove indefinite stopping was unintended, or
  uniquely select B. It endorses no option on the first version's specification, which
  this revision addresses. Disclosure is not proof of compliance with the no-tuning
  rule. It disagrees with a routine privileged bypass for hard halts. Verdict: BLOCKED
  pending the corrections below.
- **Codex Cloud:** five findings, all in section 9.
- **Automated Claude review:** approve, with a provenance nit, now addressed by the
  appendix.

## 9. Changes in revision 2

| Finding | Change |
| --- | --- |
| Local worker 1, Cloud: B is a relaxation, not a restoration | §4 B relabelled and argued as a relaxation; §5 no longer claims B is "restoring" anything |
| Local worker 2: recovery transition underspecified | §4 B specified: episode start, 24-hour cool-off, release, re-arm on `ALLOW`, interactions, restart, tests needed |
| Local worker 3, Cloud: 12% trigger is not a loss bound, and not C1 | §4 B: B preserves the trigger and its adjusted reference; no loss bound; C1 separate |
| Local worker 4: lockout claims exceed the premises | §1 step 5 and §3 require flat *and* past 8%; §6 made conditional |
| Cloud: delayed liquidation before declaring hard halts terminal | §6: conditional on where liquidation ends; the slow-liquidation path described |
| Local worker 5, Cloud: benchmark D is exempt | §3 limits the claim to grid variants |
| Local worker 6, Cloud: provenance for replay figures | §2 reproduced by me with the appendix script; input hashes and regeneration commands given; limits stated; `f937d67` and `de38fdb` shown identical in `src/` and `config/` |
| Local worker: no-tuning conclusion too categorical | §5 rewritten: safeguards, not proof; only D changes no trading behaviour |

**Changes in revision 3**

| Finding | Change |
| --- | --- |
| Owner: leans to C; hard stop "restart after I review" | §4 C fully specified; §6 and §7 updated; C no longer "not recommended" |
| Bob: name the clock for the 24 hours | §4 B step 1 and §4 C step 1: the quote's `observed_at`, `>= 24 h` |
| Bob, Codex: rebase ordering; never clear other conditions | §4 C step 2: checked before an atomic rebase; any other block prevents it |
| Codex: measurement peak never resets but keeps rising | §4 C step 6 |
| Codex, Bob: audited owner-only resume, control boundary | §4 C step 7 |
| Codex: restart and repeated calls | §4 C step 5 |
| Bob: one reference for both 8% and 12% | §4 C step 3 |
| Codex Cloud P1: 24 h chosen after results | §5: B and C need an explicit rule amendment or waiver; §7 question 1 |
| Codex Cloud P2: daily-loss pause inside a released episode | §4 B step 5: clears on `REDUCE` after confirmations |
| Codex Cloud P2: "resumed" means only equity changed | §2 relabelled; the script is unchanged, so its hash is unchanged |
| Codex Cloud P2: USDT replay minimums, not EUR | §4 A |
| Automated review nit: bars, not hours | Disclosed. The revision-3 wording ("a missing hour would shorten the reported length, never lengthen it") was incomplete. Revision 4 replaces it in §2 |
| Codex: capital threshold | §7 question 4: not recommended |

**Changes in revision 5**

| Finding | Change |
| --- | --- |
| Owner decisions, 2026-09-27 | §7 rewritten as a record; §4 C marked chosen; step 7 made automatic; §5 records the exception for two controls |
| Codex 1: two measurement peaks | §4 C step 6: C1(b) scaled at settlement, C1(a) never scaled; neither rebased |
| Codex 2, Bob: name the eligibility check | §4 C step 7.3, and a test |
| Codex 3, Bob: supersede spec §3's prohibition | §5 item 5, including the "latched" statement and `PAPER_SIMULATION.md` |
| Codex 4: the same control does not mean the same effect | §5 item 2 |
| Codex 5, Codex Cloud P1: D's resume changes behaviour | §4 D corrected |
| Codex Cloud P1: keep the non-drawdown checks on restart | §4 C steps 2 and 7.4: tentative rebase, committed only on `ALLOW` |
| Codex Cloud P1: range-exit deadlock | §4 C step 2: rebase first, range-exit wait does not block; test added |
| Codex Cloud P2: durations in the index | Index row: "at least", "censored" |
| Audit 1: every stretch is right-censored | §2 table: lower bounds from timestamps, censored at 2023-01-31 23:00; one sentence withdrawn |
| Audit 2: the exit-residue freeze is a possible second cause | §2: disclosed; the check is owed |
| Audit 3: the restart excludes capital exhaustion and integrity halts | §4 C step 7.1 |
| Revision 4 text fault | The §5 sentence about the owner's preference was spliced into item 4; replaced by the decision record |

**Changes in revision 4**

| Finding (Codex Cloud, on `36e1593`) | Change |
| --- | --- |
| P1: B and C violate spec v1 §3 ("No variant delays, suppresses or clears"); a waiver alone is not enough | §5: a scoped spec amendment with four required contents; §7 question 1 now asks for both |
| P1: the owner restart must keep liquidation and reconciliation preconditions | §4 C step 7: every existing `resume()` precondition except the risk check; test for partial liquidation |
| P2: the C1 watermark must stay reserve-adjusted | §4 C step 6: proportional settlement adjustment kept; exempt only from the loss rebase |
| P2: EUR feasibility claim left in the summary | Header: the 100-USDT replay; live EUR minimums unverified |
| P2: durations are sample counts, gaps not checked | §2: disclosed precisely; timestamp-based rerun owed; revision-3 claim corrected |

## Appendix: `data/flat_stretches.py` source

SHA-256: `543e58c53f9e99d04b9cd611ca100282fa761249182f08d97b49be1ae70e9be2`

```text
"""Counterexample search: flat (constant hourly total equity) stretches >= 24 h at a
total-equity drawdown >= THRESH%, and whether equity ever changed again afterwards."""
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal

THRESH = Decimal(sys.argv[1])
t = lambda ms: datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")
for path in sys.argv[2:]:
    doc = json.load(open(path, encoding="utf-8"))
    print(f"== {doc['dataset']} {doc['fees']['maker']}/{doc['fees']['taker']}")
    for r in doc["results"]:
        he = [(ms, Decimal(v)) for ms, v, _ in r["hourly_equity"]]
        peak, i, found = Decimal(0), 0, []
        peaks = []
        for ms, eq in he:
            peak = max(peak, eq)
            peaks.append(peak)
        while i < len(he):
            j = i
            while j + 1 < len(he) and he[j + 1][1] == he[i][1]:
                j += 1
            hours = j - i + 1
            dd = (peaks[i] - he[i][1]) / peaks[i] * 100
            if hours >= 24 and dd >= THRESH:
                resumed = j + 1 < len(he)
                found.append(f"{t(he[i][0])} {hours}h dd={dd:.2f}% -> {'RESUMED ' + t(he[j + 1][0]) if resumed else 'never resumed'}")
            i = j + 1
        name = f"{r['symbol']} {r['path_mode']} {'gated' if r['strategy'].startswith('gated') else 'ungated'}"
        print(f"  {name}: " + ("; ".join(found) if found else "none"))
```
