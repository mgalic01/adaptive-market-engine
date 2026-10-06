# Owner decisions on the test plan: one batch with V2 and a full stack, two stages, nine data rules

Index: **Owner decisions, 2026-10-05 (test plan).** Everything runs in one batch. V2 joins v1, reversing D20's "outside v1". A registered full stack, C+F+G+H+V2, runs beside every single variant, and E stays alone. V2's two behaviours beyond V0's restrictions become a fourth named exception. Both current windows get daily history from 2020-05. Claude builds the C1–C6 scorer (#167) and Codex reviews it. #156 closes after #165 merges, and its branch is kept. Two stages, with every rule fixed now: a variant must pass C1–C6 in stage 1 (the current windows) and in stage 2 (full-range-2017-2024, judged on its own). The winner is ranked on 2017–2024, and full-range-2019-2024 is reported only. Stage 2 runs on stage 1's strategy code. Only the long-window data handling may land in between, and it must leave every stage-1 result unchanged. All nine data rules are accepted (hour-level masking, compound annualised returns, XRP excluded below the tick limit), together with six readings. Spec v1 and the V2 pre-registration are amended. Docs only.

- **Date and author:** 2026-10-05, written by Claude (session `b9db01ca`).
- **Owner:** answered in Claude's session on 2026-10-05 and 2026-10-06. Approximate times, UTC:
  - about 12:05: test plan, daily data, scorer (decisions 1–3);
  - about 13:15: #156 and the first long-data answer (decisions 4 and 5);
  - about 13:40: two stages and the nine data rules (decisions 5 and 6);
  - about 14:10: V2's exception, how the stages combine, the six readings (decisions 7–9);
  - about 14:25: the code each stage runs on (decision 10);
  - about 18:18, after #168 merged: variant E and the freeze (decisions 11 and 12, under "Later decisions");
  - about 20:33, during #170's review: a traded market proxy's defects (decision 13);
  - about 22:36, during #171's review: amendment 1's owed Codex review and the post-mask expected set (decisions 14 and 15);
  - 2026-10-06, about 07:34 and 07:37: the remaining readings and amendment 1's resume rule (decisions 16–22).
- **How:** multiple-choice questions. Claude recommended every chosen option except the first long-data answer, which a later answer superseded.
- **Scope:** this record, the spec v1 amendment (`docs/EXPERIMENT_SPEC_V1.md`, "test-plan amendment") and a dated amendment to `docs/STRUCTURE_PREREGISTRATION.md`. No code, config, dataset spec or manifest changes; separate PRs carry those.
- **Why now:** the project forbids changing parameters or criteria after seeing results. This record fixes the test plan before any result of the coming batch exists. No market data, backtest result or strategy result was read for it, and none of #156's result reports was opened.

## What the owner decided, in the owner's words

1. **Test plan.** Chosen: **"Everything, one batch"**. Option text: "Bring V2 into v1 (reversing D20's 'outside v1') and register one 'full stack' combination before any run: V2 structure plus the trend switch, inventory cap, funding, cycle and order-flow gates. It runs in the same batch beside every single variant, so you see both whether the whole system works and which pieces carry it. About a day of extra work; adds a few registered trials."
   - The full stack is V2 structure (`--structure`) + A (trend switch) + B (inventory cap), which make C, + F (order flow) + G (funding) + H (cycle). E is not in it, because E stands alone.
   - V2 alone, which is V0 with `--structure`, also becomes a registered v1 variant.
2. **Daily data.** Chosen: **"Extend to May 2020"**. Option text: "Both datasets get daily history from 2020-05. H works as designed, and A and V2 see full history from the start. The datasets' fingerprints change, so old results stay recorded but aren't compared directly."
   - The datasets are `practice-2022` and `verify-2024h1`.
   - Their `daily_warmup_start` changes (spec P3, P8).
3. **Scorer.** Chosen: **"Claude builds, Codex reviews"**. It is PR #167.
4. **#156.** Chosen: **"Close it, keep branch"**. It closes after PR #165, which rebuilds its variants, merges.
5. **Long datasets.** The first answer was **"In the batch"**. After Claude explained the real scope, the owner chose **"Two stages, rules fixed now"**, which supersedes it. Option text: "Today we fix all the data rules and register the long windows as part of the final verdict. The batch runs on the two current windows as soon as it's ready, as stage 1. The long-window pieces are built in parallel and stage 2 runs on identical frozen code. You get an early read, and nothing is changed after results are seen."
   - The windows are Bob's `full-range-2017-2024` and `full-range-2019-2024`.
   - The scope Claude explained:
     - 10 exchange-outage months fail the strict parser;
     - 7–9 more outage months have exchange-wide missing hours;
     - hour-level masking is required;
     - a Bob re-fetch is needed;
     - about 7–12× the compute.
6. **Data rules.** Chosen: **"Accept all nine"**. Option text: "Hour-level masking for the batch, including incomplete hours. Days with masked hours keep their daily bar. Orders survive a masked gap. Basket coins' repaired hours are masked. Only 2017–2024 is scored (2019–2024 is reported). Returns are annualised for C2 and selection. XRP is excluded where its price breaks the tick limit, if Bob's measurement confirms it. G and H accept having no data in the early years." (On screen the first year read "2017–024", a typo for 2017–2024.) The nine rules, from the investigation behind the question:
   1. **Hour-level masking for the batch, not only for walk-forward folds.** It applies the owner's existing repair rule and the 17% / `Decimal(0)` eligibility rule. An hour enters the replay only if:
      - both archives have it;
      - it has 60 minutes;
      - it matches under `drift-tolerance-v1`, or matches exactly if it holds a repaired row.

      Any other hour is masked: its minutes and its 1h bar are dropped. A pair-month whose real defects exceed 17% of its hours is excluded.
   2. **Incomplete hours** (fewer than 60 minutes) are masked, not kept.
   3. **A day containing a masked hour** is skipped in the 24-hour daily cross-check. Its 1d bar is kept, because A's SMA refuses gaps.
   4. **Orders across a masked span** stay open and can fill on the next bar. Those fills are reported.
   5. **Basket (untraded) symbols' repaired hours** are masked. DOGE 2020-02 is excluded, as the existing record says.
   6. **Only full-range-2017-2024 is scored.** full-range-2019-2024 is run and reported but not scored, because it overlaps 2017–2024.
   7. **Returns are annualised** for C2 and the selection, so windows of different lengths weigh fairly. Raw returns are still reported.
   8. **XRP is excluded** from the windows where its price falls below about $0.1333. Below that level the 0.0001 tick makes a two-tick spread exceed 0.15%. The exclusion applies to every variant, if Bob's measurement confirms it, and leaves BTC and ETH, the 2-pair minimum.
   9. **G and H run with no data in their early years,** as the spec already says. G blocks new grids before the funding archives begin (2020-01). H3 cannot act before the 2020-05-11 halving.
7. **V2's exceptions.** Question: "Spec v1 says a variant may only ADD restrictions to V0 ... V2 breaks that rule in two places. Its extra regime vote can let a grid keep running where V0 would pause it. And a raised sell target widens the price band the 6-hour range exit watches. How should this be handled?"
   - Chosen: **"Name it a 4th exception"**, Claude's recommendation.
   - Option text: "Record both as V2's named exceptions, in the same way as E's and H3's. V2's frozen rules stay exactly as built and tested; the spec simply states openly what V2 is allowed to do."
8. **How the stages combine.** Question: "The two current test windows (2022 and the first half of 2024) also sit inside the long 2017–2024 window. How do stage 1 and stage 2 combine into the final verdict?"
   - Chosen: **"Pass both, rank on long"**, Claude's recommendation.
   - Option text: "A strategy must pass C1–C6 in stage 1 (the current windows) AND in stage 2 (2017–2024, judged on its own). Among those that pass both, the winner is ranked on 2017–2024. Strict, and nothing is counted twice."
9. **Six readings.** Claude put to the owner the six readings in its first draft that went beyond his answers.
   - Chosen: **"Accept all six"**, Claude's recommendation.
   - Option text: "Returns are annualised with compounding. V2 and the full stack rank last in the simplicity tie-break, V2 after E and the full stack last. A coin-month over 17% defects has all its hours masked, and the window is kept. Repaired hours in hourly-only warm-up months are masked. Stage-2 sensitivity runs are decided later. The masking and annualisation rules also bind the one-time 2025–26 run."
10. **The code each stage runs on.** Question: "Stage 2 must not be tuned after stage 1, so its code has to match stage 1's. But the long windows need data-handling code that isn't built yet: the repair rule and outage masking. Which rule?"
    - Chosen: **"Same strategy code"**, Claude's recommendation.
    - Option text: "Stage 1 runs as soon as the variants and scorer are merged. The masking and repair code lands afterwards. It must follow exactly the rules fixed today, and must leave every stage-1 result byte-identical, which Codex and Bob check. Strategy code is identical in both stages. Early read in about a day."
    - It makes decision 5's "stage 2 runs on identical frozen code" precise.

Options the owner did not choose:
- Test plan: "Full stack only", "Build multi-mode first" and "Keep the current plan".
- Daily data: "Keep current history".
- Scorer: "Wait for Codex".
- #156: "Leave it open".
- Long data: "After the batch" (first ask), and later "One batch, wait for all" and "Keep them out of v1".
- Data rules: "One by one".
- V2's exceptions: "Make V2 only restrict" and "Take V2 out of v1 again".
- How the stages combine: "Pool all windows".
- The code each stage runs on: "Same commit, byte for byte".

## What follows from each decision

1. **One batch.**
   - V2 and the full stack become registered, selectable v1 variants (spec §3, §4, §6).
   - The full stack is a declared combination, reported as an interaction, like C.
   - E stays a single variant.
   - The V2 pre-registration is amended: D20's "Not part of v1" is reversed. Its frozen rules do not change, so there is no `STRUCTURE_FEATURE_VERSION` bump.
   - `N_family` gains two forward trials, and V2's prior trials now fall inside v1's family (spec §6, "The family after the test-plan amendment").
   - The full-test-setup PR adds the code:
     - a flag for the full stack;
     - V2 and the full stack in the scorer's variant list and simplicity order;
     - `--structure` rows admitted, as #167's description says.
2. **Daily data from 2020-05.**
   - Both specs' `daily_warmup_start` becomes 2020-05, and P8's funding and daily entries are added to their manifests (full-test-setup PR).
   - H3 can use the ATH from the 2020-05-11 halving. Variant A's state machine and V2's daily zones start from 2020-05.
   - The spec hashes and manifests change, so earlier results stay recorded but are not compared directly with new ones.
3. **Scorer.** #167 stays Claude's PR for Codex's review, and it scores the spec as it stood. The full-test-setup PR then adds this amendment to it:
   - V2, the full stack and `--structure` rows;
   - annualised returns in C2 and the selection;
   - the two-stage rule (decision 8).

   #167's description says the amendment's PR would add the variants. This registration is docs only, so that code goes in the full-test-setup PR.
4. **#156.**
   - It closes when #165 merges, and its branch is kept.
   - Its result reports stay there, unread for this record.
   - Its V2 runs were already disclosed as prior trials whose results do not count. They now count toward v1's family size.
5. **Two stages.**
   - The long windows are registered now, as part of the final verdict (spec §4, §6).
   - Stage 1 gives an early read and names no winner.
   - Stage 2 runs on stage 1's strategy code (decision 10).
6. **Nine data rules.**
   - The rules are in spec §5 (rules 1–6, 8 and 9) and §6 (rule 7, annualised returns).
   - On the current windows they mask nothing, so stage 1 is unaffected.
   - Code needed:
     - the repair rule in the archive reader;
     - hour-level masking;
     - the masks written into the results;
     - G must run where funding archives do not exist. #165, as described, refuses G unless the manifest lists funding archives for every evaluation month. The long windows cannot meet that before 2020-01. By decision 10 this change is not data handling, so it must land before stage 1.
   - Bob's work:
     - the re-fetch with daily and funding archives;
     - the XRP quote-spread measurement (spec §5, rule 8);
     - the 17% check under these rules, which also count incomplete hours.
7. **V2's fourth exception.**
   - Spec §3's common rule now names four exceptions. There were three before.
   - **Eligibility.** V2's sixth regime vote can change whether a frame is eligible. It can keep a grid running where V0 would pause it, or pause where V0 would not. It therefore moves when the recovery confirmations, the soft-drawdown rebase and the automatic restart can happen.
   - **Range-exit band.** A sell target raised above the top level widens the band that the 6-hour range exit watches.
   - The full stack inherits V2's and H3's exceptions, never E's.
   - No V2 rule changes.
8. **Pass both, rank on long.**
   - Spec §6, "Two stages", now states the rule as decided. A variant must pass C1–C6 in stage 1 and, judged on its own, in stage 2. The selection then ranks the variants that pass both, on 2017–2024.
   - If 2017–2024 keeps fewer than 2 included pairs, the outcome is "insufficient evidence".
   - If no variant passes both stages, the outcome is "no winner".
9. **Six readings, now rules in the spec.**
   - **Compound annualisation:** `(final ÷ initial)^(365.25 ÷ d) − 1`, with `d` from C5's window. The option text names compounding; the 365.25-day year and `d` are the details of Claude's reading, as the spec writes them.
   - **Simplicity order:** V0, A, B, F, G, H, E, V2, C, C+G, C+H, C+F+G+H+V2.
   - **A pair-month over 17% real defects** has all its hours masked, and the window is kept.
   - **Repaired hours in hourly-only warm-up months** are masked.
   - **Stage-2 sensitivities:** whether stage 2 also runs the reported-only sensitivities is decided later.
   - **The one-time 2025–26 run** is bound by masking rules 1–5 and by annualisation.
10. **Same strategy code (spec §6, "Two stages").**
    - **Same strategy code.** Stage 2 runs on stage 1's strategy code, config and spec version. Between the stages, the only code that may land is the long-window data handling: the repair rule moved into the reader, and the hour-level masking.
    - **Data-handling conditions.** That code must implement exactly the registered §5 rules, and it must leave every stage-1 result unchanged. Codex and Bob verify this before stage 2 runs.
      - Re-running stage 1's windows on stage 2's code must reproduce the whole of stage 1's `results.json`, every metric, trade and order included.
      - The comparison leaves out only `code_commit`, `code_sha256` and the new mask-report fields. The long-window data PR names those fields, and they must be empty or zero on every stage-1 run.
      - Any other new or renamed field breaks the identity.
      - This comparison rule is a reading (see "Still open").
    - **Datasets.** The long windows' definitions are frozen in spec §4 now, and the long-window data PR's dataset specs must match them exactly. The manifests record Bob's fetch. Both are in place before stage 2 runs, and they need not exist before stage 1.
    - **Consequence.** Anything else the long windows need must be in stage 1's code. That includes G running where no funding archive exists before 2020-01.

## Order of work

1. This registration.
2. #165 (variants E–H) and #167 (the scorer).
3. The full-test-setup code: the full-stack flag, V2 and the full stack in the scorer, annualised returns and the stage rule, G running where funding archives are absent, the P8 manifests, and daily history from 2020-05.
4. The spec v1 freeze, after Codex's review.
5. Stage 1, as soon as the variants and the scorer are merged and the spec is frozen. This is the early read.
6. Between the stages, possibly in parallel with stage 1:
   - the long-window data code (the repair rule in the reader, and hour-level masking), which Codex and Bob verify leaves every stage-1 result unchanged, as spec §6 defines it;
   - Bob's fetch and measurements;
   - the long dataset specs, which must match the values frozen in spec §4, and the manifests from Bob's fetch, in place before stage 2.
7. Stage 2, on stage 1's strategy code.

## Changes after review on #168

- **Automated review:** three readings, listed under "Still open".
- **Codex, P1.** The long windows' definitions are now frozen in spec §4: dates, warm-ups, pairs, proxy, basket, pricing inputs and every basket exclusion, ending at the listing hours from #156's manifests.
  - The permission to change a window after today is removed.
  - After stage 1, only the mechanical application of registered rules may happen. Any other change is a registration change, allowed only before any stage-1 result exists.
- **Codex, P2.** The sensitivity family now counts the forward ungated V0 baselines (spec §6, and "The trial count" below).
- **Codex, two more P1s,** from its review of `78647ad`. Both are Claude's readings, open to the owner.
  - **Masking first, then the checks** (spec §5, "The post-mask expected set").
    - Every hour masked under rules 1, 2 and 5, and every hour of a pair-month excluded under the 17% rule, leaves the expected set of every comparison-mask check: completeness, the hourly/minute cross-check and the daily cross-check.
    - So a maskable defect never fails a check or excludes a pair-window. A defect that masking does not cover fails as before.
    - This holds in every window. The current windows have no masked hours.
  - **XRP's statistic is the engine's own rejection condition** (spec §5, rule 8).
    - XRP is excluded from a window if any quote that `bar_quotes` synthesizes from the window's replayed 1m bars has a spread above 0.15%. Only the replayed span counts, and one quote is enough.
    - It replaces the earlier "any 1m low below 2/15 USDT" reading. That reading was stronger than the owner's rule: a bar with open and close at 0.14 and a low of 0.13 passes the spread check.
    - The thresholds (about 0.13323 for open/close quotes, about 0.0667 for high/low quotes) are consequences, not the rule.
- **Codex, three findings at `fc2b833`.** All are Claude's readings, open to the owner.
  - **V2 also loosens an entry gate** (P2; spec §3 H, §3 V2 and the common rule).
    - §3 H no longer calls H3 the only gate-loosening mechanism. V2's regime vote, under its fourth exception, is the second.
    - V2's loosening has no separate report, unlike H3's. Its effect shows only in V2's and the full stack's results beside V0's and the ungated baseline's, in the same runs.
  - **Unique bars in an admitted hour** (P2; spec §5, rule 1).
    - Admission needs exactly one 1h bar and exactly one 1m bar at each of the 60 expected minute timestamps. A duplicate, a missing timestamp or an extra timestamp masks the hour.
    - The strict parser now rejects a whole archive on duplicated or out-of-order rows. The long-window data PR's reader must instead report those hours for masking.
  - **The 1h-only branch covers untraded symbols only** (P1; spec §5, rules 1 and 5).
    - That means basket members the window does not trade, and an untraded proxy, which no registered window has. It also covers the traded pairs' hourly warm-up months, as the owner accepted.
    - Traded pairs' evaluation months always have minutes and follow rule 1's conditions.

## Correction: the warm-up false alarm

Claude's first draft (local commit `216a1d8`, never pushed) said the 2017–2024 window might fail P3's 200-day warm-up. The reason given was the spec's comment that the 2018-05 and 2018-06 daily archives are missing. That was wrong:
- #156's manifest lists all 240 daily entries of the dataset as `ok`, 80 months each for BTC, ETH and XRP, 2018-05 to 2024-12. That includes 2018-05 and 2018-06. The coordinating Claude session checked this, and it was re-counted for this record.
- The real constraint is XRP's listing on 2018-05-04. The manifest's own metadata shows XRPUSDT's 2018-05 daily file starting on that day, with 28 of 31 rows. So `daily_warmup_start` and `warmup_start` must be 2018-06.
- From 2018-06-01 to 2019-01-01 there are 214 completed days, above P3's 200, so the warm-up passes.
- The corrected values are frozen in spec §4, with the listing-hour basket exclusions, and the long-window data PR's specs must match them.

## Later decisions

After #168 merged, the owner answered twelve more questions in Claude's session:
- decisions 11 and 12 on 2026-10-05 at about 18:18 UTC;
- decision 13 on 2026-10-05 at about 20:33 UTC, during #170's review;
- decisions 14–22 during #171's review: 14 and 15 on 2026-10-05 at about 22:36 UTC, 16–19 on 2026-10-06 at about 07:34 UTC, and 20–22 at about 07:37 UTC.

Claude recommended every chosen option.

11. **Variant E.**
    - Question: "Variant E (the longer range exit on low volume) may only be picked as the winner 'after Codex has reviewed its implementation and the boundary tests'. Codex reviewed exactly that across #165's five rounds, ending with no findings. Make E selectable?"
    - Chosen: **"Yes, make E selectable"**. Option text: "The freeze PR records that #165's Codex reviews cover E, and switches the scorer's E flag on. E competes like every other variant."
    - Where it landed: in #170 instead of the freeze PR, because Codex's review of #170 asked for E to be enabled before the freeze. The substance is unchanged: spec §3 E records the review, and the scorer's `E_ELIGIBLE` is on.
12. **Freezing spec v1.**
    - Question: "Freezing spec v1: its header says it becomes frozen 'only when Codex has reviewed it and the owner has confirmed the acceptance criteria in §6'. Codex has reviewed every amendment, ending clean on #168, and you confirmed C1–C6 on 2026-09-24 and amended C2 today. Freeze it once the full-test-setup PR merges, before stage 1?"
    - Chosen: **"Yes, freeze then"**. Option text: "I open a small PR that marks spec v1 frozen with today's date and replaces the stale 'no strategy code exists' line. From then on any rule change needs a new spec version, and stage 1 runs on the frozen rules."
13. **A traded market proxy's defects.**
    - Context: Codex's review of #170 asked that a BTC daily defect exclude BTC alone. The automated review then asked that an unchecked BTC hour reach every pair, and that the owner confirm the split before stage 1.
    - Question: "BTC is both a traded pair and the 'market proxy' whose hourly bars every other pair reads. When BTC's data has a defect in a test window, which pairs should be excluded from scoring?"
    - Chosen: **"Split by data"**. Option text: "A defect in BTC's hourly bars, or one that leaves them unchecked, excludes every pair (they all read those bars). A defect only in BTC's daily or minute data excludes just BTC; the other pairs still run. This is what #170 now does."
    - The other option was "Any BTC defect: all pairs". Option text: "The previous behaviour: any BTC data defect, even daily-only, excludes every pair in that window. Simpler and stricter, but a BTC daily-bar problem would throw away valid ADA/XRP/SOL results."
    - Where it landed: spec §5, "Failures that reach every pair-window", and `scoped_failures` in #170. It applies to whichever symbol is the traded proxy; BTCUSDT is the proxy in every registered window.

**Context for decisions 14–22.** Codex's review of #171 at `2b69c5c` found two gaps.
- First, the freeze question (decision 12) said "Codex has reviewed every amendment". That was wrong: amendment 1 (#124, merged as `c8cddc2` while Codex's allowance was exhausted) never had its Codex review, which #134 lists as owed.
- Second, several rules that decide which runs count and who wins were still marked as Claude's readings, open to the owner.

Claude told the owner both, and asked these questions. Where a question allowed several answers, every unselected option was put to the owner again.

14. **Amendment 1's owed Codex review.**
    - Question: "Amendment 1 (drawdown recovery: the 24 h cool-off rebase, the automatic restart after a hard-drawdown halt, and the manual-resume change) was merged while Codex was out, and its Codex review is still owed. How should the freeze handle that?"
    - Chosen: **"Get Codex's review first"**. Option text: "I ask Codex to review amendment 1 now (on the freeze PR and the tracking issue #134) and record its verdict. The freeze, and so stage 1, waits until it comes back clean. You may need to nudge Codex Desktop if Codex online doesn't answer clearly."
    - The other option was "Freeze now, record the gap".
15. **The post-mask expected set (spec §5).**
    - Question: "Four rules in the spec are still marked as my reading, open to you. Which do you accept exactly as written? Select every one you accept; any you leave out, I'll come back to before the freeze."
    - Selected: **"Checks after masking"**. Option text: "Stage 2: an hour hidden by the masking rules never fails an integrity check. Defects masking can't hide (a missing daily bar, short warm-up, bad checksum, missing exchange filter) still fail, as before."
    - The other three options were not selected, so Claude put each to the owner again, with its alternatives (decisions 16–18).
16. **XRP's statistic (spec §5, rule 8).**
    - Question: "XRP's price tick is 0.0001 USDT. When XRP trades below about 0.133 USDT, the replay's simulated quotes get too wide (over the engine's 0.15% bad-data limit) and its runs become invalid. Bob measures this before stage 2. Which test should exclude XRP from a window?"
    - Chosen: **"Actual quotes"**. Option text: "Exclude XRP from a window only if a quote the replay would really use breaks the 0.15% limit. Matches exactly when XRP's runs would fail; keeps XRP whenever it can run cleanly. Stage-1 windows unaffected."
    - The other options were "Stricter price test" (any 1m low below 2/15 USDT) and "Drop XRP from stage 2".
17. **The tie band and annualising (spec §6).**
    - Question: "Selection treats variants within 0.25 points of the best mean return as tied, and the simpler one wins. Returns are now annualised. What should that 0.25-point band be measured on?"
    - Chosen: **"Annualised returns"**. Option text: "Band on the mean annualised return (and a run ending at zero equity counts as -100%/year). Keeps the band about as wide, per year, as on the short windows it was designed for, so the simplicity tie-break still works on the 6-year window."
    - The other option was "Raw total returns".
18. **The stage-1 identity check (spec §6, "Two stages").**
    - Question: "Your rule: the stage-2 data code must leave every stage-1 result byte-identical. Literally that is impossible, because any code change alters the code-fingerprint fields every result records. How strict should the check be?"
    - Chosen: **"Fingerprints + mask fields"**. Option text: "Identical except the two code-fingerprint fields and the new mask-report fields, which must be empty/zero on every stage-1 run. Any other difference fails. Lets the data PR record its mask report inside the results."
    - The other option was "Fingerprints only".
19. **Amendment 1's manual-resume rule (spec §3).**
    - Question: "Amendment 1 changed manual resume(): it is refused while a forced sale (liquidation) is still incomplete, and allowed when only unsellable 'dust' is left, which stays held and is settled as usual. The old rule (#122) required exactly zero inventory, which unsellable dust could block forever. Accept the change?"
    - Chosen: **"Accept the change"**. Option text: "Keep amendment 1's rule: resume waits for the liquidation to finish, but a few cents of unsellable dust no longer block it. Bob reviewed it; Codex's review is the one being requested now."
    - The other option was "Back to exactly zero".
20. **The unique-bars condition of hour masking (spec §5, rule 1).**
    - Question: "Stage-2 masking: an hour of a traded pair is used only if its data is clean. My reading: the hour is masked (left out) if the 1-hour archive doesn't hold exactly one bar for it, or the 1-minute archive has a duplicate, missing or extra minute timestamp inside it. Accept?"
    - Chosen: **"Accept as written"**. Option text: "Every hour used is backed by exactly one bar per expected timestamp; anything ambiguous is left out, like a missing hour. Masked hours count toward the 17% coin-month rule. Simplest and strictest."
    - The other option was "Drop exact duplicates".
21. **V2's gate-loosening report (spec §3, V2).**
    - Question: "V2's sixth regime vote can let a grid open where V0 would pause. My reading: v1 needs no separate count of those extra grids; their effect shows in V2's results next to V0's. This affects reporting only, never a result. Accept?"
    - Chosen: **"Accept, no extra count"**. Option text: "Nothing to build; stage 1 is not delayed. V2's effect is visible by comparing its results with V0's in the same runs."
    - The other option was "Add the count".
22. **An untraded proxy's repaired hours (spec §5, rule 1, "Hours with no minute data").**
    - Question: "If a window's market proxy were not traded, my reading masks its repaired hours (as for basket coins). No registered window has an untraded proxy (BTC is traded in all), so this cannot change any v1 result. Accept, to close the last open item?"
    - Chosen: **"Accept"**. Option text: "Same treatment as untraded basket coins. Inert for every registered window; it only matters for a future dataset."
    - The other option was "Leave it open".

## Still open

- **Decided since (2026-10-05 and 2026-10-06, decisions 13–22 above):**
  - the three readings from the automated review of #168, which this section listed: the stage-1 identity check (decision 18), XRP's statistic (decision 16), and the tie band with a final equity of 0 or less annualising to −100% (decision 17);
  - every other reading the spec left open to the owner (decisions 15 and 19–22);
  - how the full stack's parts combine (spec §3), which was open to Codex's and Bob's review: they reviewed it on #168 and #170 and raised nothing against it.
- **Amendment 1's Codex review** (decision 14): requested on #171 and #134. The freeze waits for it.
- **Stage-2 sensitivity runs.** The owner decides later. They are reported only and decide nothing.
- **The trial count.** The `N_family` floors in spec §6 are working figures, to be settled by the trial register. C7's condition (b) stands, and C7 is not yet binding.
- **Data work before stage 2, with no owner decision needed:**
  - dataset specs that match spec §4's frozen values;
  - Bob's XRP quote-spread measurement;
  - the long windows' masks and the 17% check under these rules.

## The trial count

Spec §6 shows the arithmetic, under the coherence record's rules:
- **Before:** 6–7 retrospective gated states + V0 on `drawdown-recovery-v1` + V0 on `drawdown-recovery-v2` + 9 forward = 17–18 central. Adding 3 ungated states and D gave 21–22 sensitivity.
- **With the forward ungated V0 baselines** (Codex on #168): every forward run inspects one. The baseline on `drawdown-recovery-v2` is certain. The one on `drawdown-recovery-v1` counts if its pre-amendment-2 result is inspected. Sensitivity becomes 22–24.
- **With V2 and the full stack:** 19–20 central and 24–26 sensitivity. Their ungated rows are the ungated V0 baseline, so they add no ungated configuration.
- **With at least two of V2's prior configurations:** at least 21–22 and 26–28. These are Bob's 2026-10-01 runs of V2 and of V2 with variant A.

The working figures are 22 and 28. All figures are floors, to be settled by the trial register.

## What Claude checked

- **Read:**
  - spec v1 in full;
  - the coherence record (counting rules);
  - the V2 pre-registration;
  - the eligibility record and Bob's repair-rule task and report;
  - `START_HERE.md` §0–§1;
  - the D17–D21 record;
  - the #165 and #167 descriptions;
  - the dataset specs and manifests of both full-range windows on #156's branch `65a7eb0`, and `full-range-2019-2024.toml` on main `2f645fe` (configuration and metadata only).
- **Code facts cited in the spec,** read at `2f645fe`. #165 and #167 have since merged into main and moved these lines, so the spec now cites the methods instead: `PaperSimulator._step`'s eligibility branch, `_open_grid`, `_track_range` and `_validate_frame`. On main `396041f` the eligibility pause goes through #165's `_entry_eligible`, and the claim holds. The facts, with their line numbers at `2f645fe`:
  - an ineligible frame starts a V0 eligibility pause (`runner.py` L721–722);
  - the sixth vote changes the score and the dispersion (`regime.py` L126–135);
  - V2's level filter runs before B's cap (`runner.py` L1112–1139);
  - the incomplete-hour and missing-minute checks are fatal today (`backtest/__main__.py` L62–69);
  - gaps add no outside-range time (`runner.py` L536–564);
  - open and close quotes are two ticks wide on a low-priced pair (`replay.py` `bar_quotes`).
- **Computed by script:**
  - window lengths: 245, 182, 2,192 and 2,011 days;
  - 214 days from 2018-06-01 to 2019-01-01;
  - XRP's quote bounds for prices on the 0.0001 grid: open/close quotes fail below 2/15 − 0.0001 ≈ 0.13323, high quotes below 1/15 ≈ 0.0667, and low quotes below about 0.06657;
  - from the 2017–2024 manifest: 240 daily entries, all `ok`, and XRPUSDT 2018-05 with `first_open_ms` 1525392000000 (2018-05-04), 28 rows and `missing_rows` 3;
  - from both manifests, the first 1h candles: SOLUSDT 2020-08-11T06:00Z, DOGEUSDT 2019-07-05T12:00Z, LINKUSDT 2019-01-16T10:00Z (374 rows, 370 missing in 2019-01), and TRXUSDT 2018-06-11T11:00Z. BNBUSDT and LTCUSDT are complete from both warm-ups, and TRXUSDT is complete from 2019-01;
  - from the 2019–2024 manifest: 78 daily entries (2018-07 to 2024-12), all `ok`.
- **Not checked:**
  - XRP's prices;
  - any mask of the long windows.

  Both need data, which Bob measures in step 4 of the order of work.
