# Owner decisions after spec v2's first read: continue, record decision reasons, and three cases settled

Index: **Owner decisions, 2026-10-07.** After the mode switcher lost money in all 8 sanity-window runs, the owner chose to continue to the scored 2019-2024 window with reporting-only decision-reason instrumentation. Three cases are settled without changing a registered rule: a restart decides at the next valid frame; an empty entry's stop-out keeps starting the pause, as spec v2 §5 says; a window whose market proxy is masked whole fails closed. Decision 14 is an exception on record to a frozen data rule: the daily check skips 2021-01-21, a documented Binance volume defect, and counts the skip.

- **Date and author:** 2026-10-07, written by Claude (session `b9db01ca`).
- **Owner:** gave the choices below in Claude's session on 2026-10-07: decisions 10 to 13 between about 08:00 and 10:00 UTC, and decision 14 later that day, after Bob's fetch of `full-range-2017-2024`.
- **Why a separate record:** [spec v2](../EXPERIMENT_SPEC_V2.md) is frozen, and its status block says that a change requires a new version. Its §11 lists decisions 1 to 9, given up to the freeze. These five come after the freeze, so they are recorded here, numbered on from §11 for reference. None of decisions 10 to 13 changes the spec's text or a registered rule. Decision 14 is an exception on record to a frozen data rule of spec v1, and changes neither spec's text.
- **Context:** the first read ran the mode switcher on spec v2's two sanity windows, `practice-2022` and `verify-2024h1`, at main `552c32c`. It lost money in all 8 runs, so C2 and C6 failed there, and in BTCUSDT's 2024H1 it stayed out of a 61% rise. These windows are reported only (spec v2 §8), so the read decides nothing. The formal verdict comes from `full-range-2017-2024`.

## The decisions

10. **Continue to the scored window, with decision reasons recorded.** Claude offered three options: finish the pre-registered 2019-2024 test, add decision-reason instrumentation first, or stop v2. The owner chose: **"go merge 193 once reviews are clear, add decision-reason instrumentation first"**.
    - Merging #193 started Bob's fetch of `full-range-2017-2024`. Its first run lost its report (#195), and the fix (#196) is merged; the re-run waits on the owner's `/bob-run`.
    - The instrumentation is reporting only. Each mode-switcher row gains `modes.decisions`, which holds:
      - the decisions by mode;
      - every condition that kept Uptrend or Grid out at each hourly decision;
      - the decisions that a single condition kept out;
      - by month, the decisions by mode and the conditions that kept Uptrend out.
    - The instrumentation leaves `select_mode` and every decision as they were. A golden SHA-256 of three mode-switcher replays, recorded on main before the change, still matches. No criterion reads the new block (spec v2 §8, "Reported, not gating").
11. **The first decision after a restart.** Question: "After a halt clears (the bot restarts mid-hour), when should the mode switcher make its first decision?" Chosen: **"At once"**, the behaviour built and recommended.
    - Spec v2 §7 says: "After a restart, the mode is decided afresh at the next decision". The hour's decision was missed while the account was halted, so the next decision is the first valid frame after the restart.
    - A test pins this.
12. **An empty entry's stop-out.** The first question treated this as open: "If an Uptrend entry's stop is hit before it has bought anything (an 'empty' entry), should that start the 24-hour re-entry pause?" The owner chose **"Only if it bought something"**.
    - Spec v2 §5 already settles it, though: "The pause starts even when the entry had bought nothing yet, because the stop was still reached." A task review had said the spec left it open. Claude passed that on without checking the spec.
    - Claude corrected the question: "Correction: frozen spec v2 already says an empty entry's stop-out DOES start the 24-hour pause (§5). Changing it now, after the first read, is a rule change the no-tuning rule allows only as an exception on record. Which do you want?"
    - Chosen: **"Keep the frozen rule"**, over "Grant an exception on record".
    - So §5 stands. The code change made for the first answer was reverted before any run used it.
13. **A window whose market proxy is masked whole.** Question: "If the 17% data rule ever masked every hour of the market proxy or of a basket member, what should happen to that window? No registered window can reach this today." Chosen: **"Fail closed"**, the behaviour built and recommended.
    - Spec v1 §5 says that masked hours, and a month the 17% rule excludes, leave the window standing. It does not address a proxy or a basket member left with no hour at all, so the frozen text does not reach this case.
    - The code fails such a window's integrity check ("no hours compared"), and it is reported as invalid, because a window with no proxy data cannot be judged honestly.
    - No registered window can reach the case: spec v1's eligibility record puts every measured pair-month of `full-range-2017-2024` under 17%.
14. **An exception for 2021-01-21's daily bars.** Bob's fetch of `full-range-2017-2024` completed, and `verify` reported `daily_days_mismatched=1` for each of BTCUSDT, ETHUSDT and XRPUSDT. Question: "Bob's 2017-2024 fetch is complete, but one known Binance defect blocks scoring. On 2021-01-21 every pair's official daily bar has ~2.4% less volume than its 24 hourly bars, while the prices match exactly (Bob documented it on Sep 26). The frozen rule allows 0.1% volume drift, so BTC and ETH fail their daily check, and XRP is excluded by its quote test anyway. Under the frozen rules no pair is left, so v2 would end with 'insufficient evidence'. What do you want?" Chosen: **"Exception for that day"**. The option said: "Recorded on file: the daily check skips 2021-01-21 and counts the skip, as it already does for a day with a masked hour. It is a data defect documented before any 2019-2024 result existed, and the mode switcher never reads daily volume. BTC and ETH stay in, XRP stays excluded by its quote test, and v2 gets its pass/fail verdict on two pairs."
    - **This is an exception to a frozen data rule**: spec v1 §5 rule 3 and P3, the daily/hourly cross-check. The owner granted it on record after Bob's fetch and before any 2019-2024 result existed.
    - **The defect.** Bob's [defect calendar](2026-09-26-bob-hourly-defect-calendar.md), section "Day-Level Defects", found the day on 2026-09-26. On 2021-01-21 every pair's official 1d bar has about 2.4% less volume than the sum of its 24 official 1h bars, while the prices agree exactly (BTCUSDT: 131803.182926 against 135004.076658).
      - The daily check's volume tolerance is 0.1% (`drift-tolerance-v1`), so the day fails each pair's daily check, and each failure excludes that pair.
      - BTCUSDT is also the market proxy, and a 1d bar that disagrees with its hours is one of the proxy failures that reach every pair (`PROXY_HOURLY_FIELDS`), so `verify` and `run` would stop before any replay. Either way, no pair is left for v2's verdict.
    - **What changes.** The daily check skips 2021-01-21 in its 24-hour comparison, for every symbol, and counts the skip in `daily_days_skipped_documented`. That is exactly how it treats a day holding a masked hour (rule 3).
      - The day's official 1d bar is kept. The presence checks over the whole daily window still apply to it, so a missing or duplicated bar that day still fails.
      - The skip is by date, as rule 3's is. The day is not compared at all, so a price difference there would go unseen too. Bob's calendar verified that the prices of 2021-01-21 agree exactly.
      - The count is not an integrity failure, and neither scorer reads it.
    - **Nothing is hidden.** `verify` reported counts, not dates, so the day was inferred from Bob's calendar. A record with a mismatch now names its days in `daily_mismatched_days`. The next `verify` on the real data shows whether 2021-01-21 was the only bad day. If another day mismatches, the check still fails and names it.
    - **What does not change.** No strategy rule changes. Spec v1 and spec v2 stay frozen and untouched. XRPUSDT stays excluded by its quote test (rule 8). Stage 1's windows hold the day only in their daily window, never in their hourly one, so it is never compared there and their records are unchanged.

## What changed in the repository

- **Decision 10:** the instrumentation (`strategy/mode_selector.py`'s `explain_mode`, the runner's report, `backtest/replay.py`'s `modes.decisions`), its tests and `docs/BACKTEST_METHOD.md`, in the same PR as this record.
- **Decision 11:** one test, and no code change.
- **Decision 12:** none in net terms. The change and its revert are both in that PR's history.
- **Decision 13:** none; the behaviour was already built this way.
- **Decision 14:** `backtest/replay.py`'s `DOCUMENTED_DAILY_DEFECTS` and `cross_check_daily` (the skip, `daily_days_skipped_documented` and `daily_mismatched_days`), their tests, and `docs/BACKTEST_METHOD.md`. The scorers are unchanged; tests show that both read a record carrying the new keys as before.
