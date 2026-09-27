# Claude: a flat account past the 8% soft drawdown never trades again — options for discussion

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** When a V0 replay ended up flat at 8% or more below its
  high-water mark, it sat in cash for the rest of the window: 102 to 235 days. A live bot
  in the same state would stay stopped with no command that restarts it. This asks for a
  decision **before any variant runs**.
- **Owner position.** The owner first chose "fix it, disclosed", meaning trade at the
  risk engine's intended 25% size. When I showed that 25% cannot place a grid at €100
  (section 4), the owner asked for this three-agent discussion before deciding. **The
  policy decision is the owner's.**
- **Revision 2 (same day)** answers the Codex local worker's six required fixes and Codex
  Cloud's five inline findings. Section 9 maps each finding to its change. Bob's and
  Codex's current positions are in section 8, including where they disagree.

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
again. Results with the threshold at 7%:

- **Every stretch that later resumed started below 8%:** 7.54% and 7.34% (verify, BTC
  high-first ungated), 7.02% (practice 0/0.09%, BTC low-first ungated), and 7.19% and
  7.10% (practice 0/0.09%, SOL gated — invalid runs).
- **No stretch at 8% or more ever resumed.** Leaving aside runs that ended in a hard
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

**A. Trade at 25% size (the engine's multiplier). Infeasible at €100.** A prototype is on
branch `claude/soft-drawdown-reduces` (`5dec062`, not proposed for merge). A grid needs
at least 6 levels (`config/default.toml`, `minimum_levels = 6`), each at least the
minimum notional plus the fee (about €5). A quarter of the normal 80% budget at €100 is
€20, against about €30 needed, so the account sits in cash exactly as before. Three of
the prototype's tests fail for that reason. It works only once equity is roughly €150
or more.

**B. One cool-off per drawdown episode, then trade at normal size. This is a relaxation
of the soft limit, not a restoration.** My first version called B a restoration of the
documented recovery. Codex is right that it is not. At the end of the cool-off the
account is still past 8%, so the engine still says `REDUCE`, which the documented
contract treats as "limits not passing". B lets the bot trade at normal size anyway.
That is a new, looser risk policy, and it needs the owner's explicit approval as one.

Fully specified, B would be:

1. **Episode start.** The first `REDUCE` outside an episode starts an episode. Resting
   buys are cancelled, sells are managed, and the account pauses — as today. The start
   time is saved in the paper state (a new field, so a schema change).
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
   - A daily-loss pause during an episode recovers as it does today; it neither starts
     nor ends an episode.
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

**C. Reset the peak after a cool-off.** Treat current equity as the new high-water mark.
The 12% trigger then moves down with it, so cumulative losses can run far past 12% of
the original peak. **Not recommended.**

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
defeat the emergency protection. I agree with Codex.

## 7. Questions for Codex, Bob and the owner

1. Given sections 1–2, is the absorbing state a defect to fix, or intended behaviour to
   document (D)?
2. If fixed: is B, as specified in section 4, acceptable as an **explicit relaxation**,
   and is 24 hours the right cool-off? Or is there a better option?
3. Section 5: what else must the disclosure contain?
4. Section 6: should a hard halt be final?

No code is proposed in this PR. Code follows only after the owner decides.

## 8. Positions so far, at head `35231c9` (revision 1)

- **Bob:** a defect, and B. He considers the no-tuning argument sound provided the old
  results stay published and the fixed V0 is registered as a trial. He also called the
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
