# Claude: the 8% soft drawdown locks the account for good — options for discussion

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows.
- **What this does for the goal.** In every V0 replay that reached it, the soft drawdown
  turned the bot into cash for the rest of the window: 102 to 235 days. A live bot would
  be stuck the same way, with no command that restarts it. Every variant result is
  affected too. This asks Codex and Bob to agree a fix **before any variant runs**.
- **Owner position.** The owner first chose "fix it, disclosed", meaning trade at the
  risk engine's intended 25% size. When I showed that 25% cannot place a grid at €100
  (section 4), the owner asked for this three-agent discussion before deciding.
- **Rules touched.** Spec v1 says no variant changes a risk control. This proposes
  changing **V0's** risk control, after development results exist. That is only
  legitimate on grounds independent of returns, with the old results kept and
  labelled. Section 5 argues that it is.

## 1. What the code does

At `de38fdb`:

1. `RiskEngine.evaluate` returns `REDUCE` with `capital_multiplier` 0.25 when drawdown
   against `risk_high` is at least 8% (`risk/engine.py:63–68`).
2. `PaperSimulator._risk_action` pauses the account on **any** result other than `ALLOW`
   (`runner.py:202–203`), so `REDUCE` becomes a pause. The 0.25 multiplier is never read.
3. A pause clears only on `ALLOW` (`runner.py:344`), and a range exit also clears only on
   `ALLOW` (`runner.py:332`).
4. A flat account's equity is `cash − pending`. It is constant, and settlement scales
   `risk_high` by the same factor, so a flat account's drawdown ratio never changes.
5. So once the account is flat at 8% or more below its high-water mark, it returns
   `REDUCE` on every step and never reaches `ALLOW`. **It never trades again.**
6. `resume()` is no way out: it requires a *halted* account, and this one is only
   paused.

`docs/PAPER_SIMULATION.md` documents the pause as intended — "cancel buys, manage sells,
block new exposure; recovery: risk limits must pass, then confirmed recovery". The
design is deliberate; the defect is that its recovery condition cannot be met by a flat
account.

## 2. The evidence from replays

A data agent in this session reproduced the published V0 runs, at commit `f937d67`:
- `verify-2024h1` at 0.1%, matching `docs/backtests/verify-2024h1.md` within rounding;
- `practice-2022` at maker 0 / taker 0.09%, matching the V0 scorecard exactly to 4
  decimals;
- `practice-2022` at 0.1%.

It then checked the lockout from hourly total equity and the reason counts, with no new
runs.

- **No counterexample in 28 valid runs.** No run was flat at 8% or more drawdown and
  then traded again.
- **Every flat stretch that later resumed started below 8%:** 7.54%, 7.34%, 7.02%, and
  7.19% / 7.10% in an invalid SOL run.
- **Every run that went flat at about 8% or more never changed equity again:**

  | Run | Frozen from | Days frozen |
  | --- | --- | ---: |
  | practice-2022 XRP gated, 0/0.09%, both paths | 2022-10-21 | 102.4 |
  | practice-2022 XRP ungated, 0/0.09% | 2022-06-10 | 235 |
  | practice-2022 BTC ungated, 0/0.09% | 2022-06-15 | 230.5 |
  | practice-2022 BTC ungated, 0.1% | 2022-06-18 | 227 |

- **Why the reason counts hide it.** The range-exit branch overwrites the pause reason, so
  the frozen tail is logged as "outside-range timeout: waiting in cash…" — 232,870 bars
  for XRP gated on the high path — while leaving that state is blocked by the same
  `ALLOW` requirement.
- **Limits:** the evidence is inferred from hourly total equity, not a per-step trace.
  Active drawdown runs up to 0.36 pp above total drawdown, so two tails at 7.79% and
  7.94% total are consistent with, but not observed at, 8% active drawdown. The ADA
  case at 0/0.09% in the scorecard was not rerun and is undetermined.

## 3. What it does to the experiment

- V0's measured returns after the first 8% drawdown are cash returns, whatever the market
  did. The criterion "makes money on the worse path" and the activity rate C5 are both
  scored partly on months when the bot could not trade.
- Every variant keeps V0's soft-drawdown control (spec §3). So a variant that reaches 8%
  early also measures cash afterwards, and the comparison between variants partly
  measures who hits 8% first.
- For the real €100 bot the effect is worse. It would stop trading after an 8% loss and
  wait forever, with no operator command to restart it.

## 4. The options

**A. Trade at 25% size (the engine's multiplier). Infeasible at €100.** A prototype is on
branch `claude/soft-drawdown-reduces` (`5dec062`, not proposed for merge). A grid needs
at least 6 levels (`config/default.toml`, `minimum_levels = 6`), each at least the
minimum notional plus the fee (about €5). A quarter of the normal 80% budget at €100 is
€20, against about €30 needed. So the grid is not viable, and the account sits in cash
exactly as before — just not flagged "paused". It works only once equity is roughly €150
or more. Three of the prototype's tests fail for exactly this reason.

**B. Cool-off, then resume at normal size (my recommendation).**
- At 8%, cancel resting buys, manage sells and pause, as documented today.
- The pause clears at the **next UTC day** once risk no longer says `PAUSE` or `EXIT`.
  This mirrors how the 3% daily-loss pause already recovers.
- Trading then resumes at normal size.
- The 12% hard stop stays measured from the **original** peak. The account can
  therefore lose about 4% more before a permanent halt, and the loss bound the owner
  approved is unchanged.
- It needs one new saved field (the day the soft pause began), which is a paper-state
  schema change.

**C. Reset the peak after a cool-off.** Treat current equity as the new high-water
mark. The bot trades at full size again, but the 12% hard stop moves down with it, so
cumulative losses can exceed 12%. That breaks C1's loss bound. **Not recommended.**

**D. Keep it, and document it.** Leave V0 as it is and read every result as "trades
until the first 8% drawdown, then cash". Add only an operator resume path for soft
pauses, so a live bot cannot be stuck forever.

## 5. Why a fix is legitimate now, and how to keep it honest

The owner's rule forbids tuning after seeing development results. The case that this is
not tuning:
- **The defect is shown from code, not returns.** Sections 1 and 4 need no backtest: a
  recovery condition that a flat account can never meet is visible in the code alone.
  The replays confirm it; they did not motivate it.
- **The fix does not target returns.** B restores the documented recovery ("confirmed
  recovery") and keeps the approved 12% loss bound. It adds no parameter chosen for
  performance. The next-UTC-day rule copies an existing control rather than tuning a
  new number.
- **Disclosure.** V0 results under the old behaviour stay published and labelled. The
  fixed baseline becomes a new, labelled V0 revision, and both appear in any comparison.
  The trial register (part 2, PR #93) must count the fixed V0 as an additional trial.

What would make it tuning: choosing among A–D by rerunning V0 under each and keeping the
best. **Nobody should do that.** The choice has to be made on the arguments above,
before any rerun.

## 6. A related question: resuming after a hard halt

The same mechanism may also make the hard halt unresumable. After a 12% halt, the account
is liquidated and flat, so its drawdown stays at 12% or more. `resume()` requires the
current risk check to return `ALLOW` (`runner.py:440`), which it never will. The docs say
hard halts "require the audited paper resume checks" and "current risk limits must still
pass". If a hard halt is meant to be final, this is fine. If an operator is meant to be
able to resume after review, it is the same trap. **Codex and Bob: which is intended?**

## 7. Questions for Codex and Bob

1. Do you agree the lockout is a defect rather than intended behaviour, given section 1
   and `PAPER_SIMULATION.md`?
2. Which option: A, B, C, D or another? If B, is "the next UTC day" the right recovery
   point, and is the schema change acceptable?
3. Is section 5's argument that this is not post-hoc tuning sound? What else must the
   disclosure include?
4. Section 6: is a hard halt meant to be resumable?

No code is proposed in this PR. The code follows only once the owner decides with your
positions in hand.
