# Owner decisions on the test plan: one batch with V2 and a full stack, two stages, nine data rules

Index: **Owner decisions, 2026-10-05 (test plan).** Everything runs in one batch. V2 joins v1, reversing D20's "outside v1". A registered full stack, C+F+G+H+V2, runs beside every single variant, and E stays alone. V2's two behaviours beyond V0's restrictions become a fourth named exception. Both current windows get daily history from 2020-05. Claude builds the C1–C6 scorer (#167) and Codex reviews it. #156 closes after #165 merges, and its branch is kept. Two stages, with every rule fixed now: a variant must pass C1–C6 in stage 1 (the current windows) and in stage 2 (full-range-2017-2024, judged on its own). The winner is ranked on 2017–2024, and full-range-2019-2024 is reported only. Stage 2 runs on stage 1's strategy code. Only the long-window data handling may land in between, and it must leave every stage-1 result unchanged. All nine data rules are accepted (hour-level masking, compound annualised returns, XRP excluded below the tick limit), together with six readings. Spec v1 and the V2 pre-registration are amended. Docs only.

- **Date and author:** 2026-10-05, written by Claude (session `b9db01ca`).
- **Owner:** answered in Claude's session on 2026-10-05. Approximate times, UTC:
  - about 12:05: test plan, daily data, scorer (decisions 1–3);
  - about 13:15: #156 and the first long-data answer (decisions 4 and 5);
  - about 13:40: two stages and the nine data rules (decisions 5 and 6);
  - about 14:10: V2's exception, how the stages combine, the six readings (decisions 7–9);
  - about 14:25: the code each stage runs on (decision 10).
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
     - the XRP price measurement;
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

## Correction: the warm-up false alarm

Claude's first draft (local commit `216a1d8`, never pushed) said the 2017–2024 window might fail P3's 200-day warm-up. The reason given was the spec's comment that the 2018-05 and 2018-06 daily archives are missing. That was wrong:
- #156's manifest lists all 240 daily entries of the dataset as `ok`, 80 months each for BTC, ETH and XRP, 2018-05 to 2024-12. That includes 2018-05 and 2018-06. The coordinating Claude session checked this, and it was re-counted for this record.
- The real constraint is XRP's listing on 2018-05-04. The manifest's own metadata shows XRPUSDT's 2018-05 daily file starting on that day, with 28 of 31 rows. So `daily_warmup_start` and `warmup_start` must be 2018-06.
- From 2018-06-01 to 2019-01-01 there are 214 completed days, above P3's 200, so the warm-up passes.
- The corrected values are frozen in spec §4, with the listing-hour basket exclusions, and the long-window data PR's specs must match them.

## Still open

- **Three readings from the automated review of #168, open to the owner.** Each is written into the spec as Claude's reading.
  1. The stage-1 identity check leaves out only `code_commit`, `code_sha256` and the new mask-report fields, which must be empty or zero on every stage-1 run (spec §6, "Two stages"). A literal byte-identity could not hold once those fields exist.
  2. XRP's statistic, fixed before Bob measures: XRP is excluded from a window if any 1m low in its warm-up or evaluation span is below 2/15 USDT (about 0.1333). In warm-up months the 1h low is used (spec §5, rule 8).
  3. The 0.25-point tie band applies to the mean compound-annualised return, and a final equity of 0 or less annualises to −100% (spec §6, "Annualised returns" and selection step 2).
- **Stage-2 sensitivity runs.** The owner decides later. They are reported only and decide nothing.
- **The trial count.** The `N_family` floors in spec §6 are working figures, to be settled by the trial register. C7's condition (b) stands, and C7 is not yet binding.
- **For review, not the owner.** How the full stack's parts combine (spec §3) is Claude's reading of the sections and of the code on main. It was not among the six readings, and it is open to Codex's and Bob's review before the freeze.
- **Data work before stage 2, with no owner decision needed:**
  - dataset specs that match spec §4's frozen values;
  - Bob's XRP measurement;
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
- **Code facts cited in the spec,** read at `2f645fe`:
  - an ineligible frame starts a V0 eligibility pause (`runner.py` L721–722);
  - the sixth vote changes the score and the dispersion (`regime.py` L126–135);
  - V2's level filter runs before B's cap (`runner.py` L1112–1139);
  - the incomplete-hour and missing-minute checks are fatal today (`backtest/__main__.py` L62–69);
  - gaps add no outside-range time (`runner.py` L536–564);
  - open and close quotes are two ticks wide on a low-priced pair (`replay.py` `bar_quotes`).
- **Computed by script:**
  - window lengths: 245, 182, 2,192 and 2,011 days;
  - 214 days from 2018-06-01 to 2019-01-01;
  - XRP's limit: 0.0002 ÷ 0.0015 = 2/15 ≈ 0.1333;
  - from the 2017–2024 manifest: 240 daily entries, all `ok`, and XRPUSDT 2018-05 with `first_open_ms` 1525392000000 (2018-05-04), 28 rows and `missing_rows` 3;
  - from both manifests, the first 1h candles: SOLUSDT 2020-08-11T06:00Z, DOGEUSDT 2019-07-05T12:00Z, LINKUSDT 2019-01-16T10:00Z (374 rows, 370 missing in 2019-01), and TRXUSDT 2018-06-11T11:00Z. BNBUSDT and LTCUSDT are complete from both warm-ups, and TRXUSDT is complete from 2019-01;
  - from the 2019–2024 manifest: 78 daily entries (2018-07 to 2024-12), all `ok`.
- **Not checked:**
  - XRP's prices;
  - any mask of the long windows.

  Both need data, which Bob measures in step 4 of the order of work.
