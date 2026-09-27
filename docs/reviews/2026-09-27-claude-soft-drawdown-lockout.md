# Claude: a flat account past the 8% soft drawdown never trades again — options for discussion

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** When a V0 replay ended up flat at 8% or more below its
  high-water mark, it sat in cash for the rest of the window: 102 to 235 days. A live bot
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
- **No stretch at 8% or more ever changed equity again.** Leaving aside runs that ended in a hard
  halt (section 6), the not-halted stretches were:

  | Run | Starts | Drawdown at start (total equity) | Length |
  | --- | --- | ---: | ---: |
  | practice 0/0.09%, XRP gated, high-first / low-first | 2022-10-21 13:00 | 8.25% / 7.79% | 2,459 h (102 d) |
  | practice 0/0.09%, XRP ungated, both paths | 2022-06-10 19:00 | 8.97% / 8.96% | 5,645 h (235 d) |
  | practice 0/0.09%, BTC ungated, high-first / low-first | 2022-06-15 11:00 | 7.94% / 8.67% | 5,533 h (231 d) |
  | practice 0.1%, BTC ungated, high-first / low-first | 2022-06-18 13:00 | 8.19% / 8.05% | 5,459 h (227 d) |

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

**C. Rebase the risk reference after a cool-off (the owner's current preference).**
Revision 2 said "not recommended", and I withdraw that: the choice between B, C and D
is the owner's. C is specified below with every clarification Codex and Bob asked for.

1. **Episode start.** As in B: the first `REDUCE` outside an episode cancels resting
   buys, manages sells and pauses. The start time is the quote's `observed_at`, saved in
   the paper state (a schema change).
2. **Rebase conditions, checked in this order in one step, before any change of state:**
   1. at least 24 hours have passed since the episode start (`observed_at`, `>= 24 h`);
   2. the normal recovery confirmations (`recovery_frames`) have passed, counted over
      frames on which **every risk condition other than the soft drawdown** passes: no
      daily-loss `PAUSE`, no `EXIT`, no data-quality or range condition blocking;
   3. the account is not halted.

   Only then is the rebase applied, **atomically**: `risk_high` becomes the current
   active equity. The drawdown becomes 0, the engine returns `ALLOW`, and trading resumes
   at normal size. This answers Bob's ordering question: the confirmations are checked
   *before* the rebase, against every condition except the one the rebase removes, so the
   rebase cannot skip them. It also answers Codex: the rebase never clears a daily-loss
   pause, a data-quality block or a hard halt, because any of them stops step 2.
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
6. **Acceptance is untouched: a separate measurement peak.** C1(a) and C1(b) are
   measured against a high-water mark that is **never rebased and never reset**. It
   still rises with every new peak; it is not a frozen constant (Codex's correction of
   Bob's wording). It starts from the same starting equity as `risk_high`. **Corrected
   in revision 4 (Codex Cloud):** it still receives the same proportional settlement
   adjustment as `risk_high` today (`_settle`, `account.risk_high *= factor`), so moving
   profit into the reserve never appears as a drawdown. It is exempt **only** from the
   new loss rebase. Without that adjustment, option C would create C1 failures after
   every profit settlement. The two C1
   bases stay separate, as today: active equity for C1(b) and reserve-inclusive total
   equity for C1(a). Without this, a rebase would silently weaken C1(b), which today
   reads the runtime `risk_high`.
7. **Hard stop: restart only after the owner reviews.** No automatic restart, and no
   general bypass of `resume()`'s risk check. There is one distinct, explicit command
   with an audited authorisation. **Corrected in revision 4 (Codex Cloud):** it keeps
   every precondition `resume()` has today except the risk check it replaces. The
   account must be halted, flat (no inventory), free of orders, reconciled, and valid
   for the current frame (`runner.py`, `resume`: "resume requires a halted, reconciled
   flat paper account"). While a forced liquidation is still incomplete, the command is
   refused. Test needed: a partially liquidated halted account is rejected. The operator states a reason; the command records the
   reason, the time and the old and new references, then applies the same rebase as step
   2. The automated runner never calls it. **Control boundary:** in paper mode the
   operator is whoever runs the CLI on the owner's machine, and no stronger
   authentication is claimed. A live deployment would need its own authorisation
   design, which is out of scope here.
8. **The daily-loss interaction** follows B's corrected rule: inside a rebased episode
   the drawdown is measured from the new reference, so a later daily pause clears on
   `ALLOW` as today.
9. **Tests needed:** a trigger just before midnight; no rebase before 24 hours; no rebase
   while a daily pause, `EXIT` or data block is active; exactly one rebase per episode;
   restart before and after a rebase; the owner-only resume, with and without a reason;
   the C1 peak unchanged by a rebase and still rising with new highs.

**What C costs, plainly.** C trades at normal size again after every episode. That is
closer to the owner's "what's the point of trading if not trading", but the only loss
limit left is per episode. Only a human decision after a hard stop ends the sequence.

**D. Keep it and document it.** Leave V0 as it is and read every result as "trades until
flat past 8%, then cash". Add only an audited operator resume for soft pauses, so a live
bot cannot be stuck indefinitely without a human decision.

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

**Revision 4: a spec amendment is also required (Codex Cloud P1).** Spec v1 §3 says every
grid variant keeps every V0 control, including the soft-drawdown reduction, and that
"No variant delays, suppresses or clears any of them" (`docs/EXPERIMENT_SPEC_V1.md`,
under §3, before the named exceptions). B and C do exactly that. A waiver of the
no-tuning rule does not change the registered spec. So B or C also needs a scoped
amendment to spec v1, recorded before any rerun. The amendment must state:
1. the changed soft-drawdown control, word for word;
2. that it replaces V0's control **for every grid variant identically** (V0, A, B, C,
   E, F, G, H, C+G, C+H), so no variant gains or loses from it relative to V0;
3. that C6 then compares against the **amended** V0;
4. that the pre-fix V0 results stay published, and that the pre-fix V0 is registered as
   a trial in part 2's count (PR #93, now merged as a proposal). The owner's preference for C is not
that waiver, and none of us will treat it as one.

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
with D too; it does not depend on C.

## 7. What the owner decides (revision 3)

1. **The rule and the spec.** Amend or waive the no-tuning rule for this one change,
   knowingly, **and** approve the scoped spec v1 amendment described in §5? If either
   answer is no, D is the only compliant option.
2. **The option,** if the rule is waived: B (one cool-off, then trade on at the old
   reference) or C (rebase the reference, as specified in section 4). The owner leans to
   C.
3. **The hard stop:** the owner chose "restart after I review", specified in section 4 C
   step 7. It works with any option. Confirm it.
4. **A capital threshold** (C below some amount, D above it)? Codex recommends against:
   it adds another free parameter and does not change the percentage risk. Bob would
   accept one only together with an explicit rule amendment. **I recommend against it**,
   for Codex's reason. A loss budget decided in money terms would be the better tool, and
   that is a separate decision (see PR #106, D6).

No code is proposed in this PR. Code follows only after the owner decides, and it will
come as a separate PR with the tests listed in section 4.

## 8. Positions

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
