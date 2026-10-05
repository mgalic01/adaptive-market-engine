# Owner decisions on the test plan: one batch with V2 and a full stack, two stages, nine data rules

Index: **Owner decisions, 2026-10-05 (test plan).** Everything in one batch: V2 joins v1 (reversing D20's "outside v1"), and a registered full stack, C+F+G+H+V2, runs beside every single variant; E stays alone. Both current windows get daily history from 2020-05. Claude builds the C1–C6 scorer (#167) and Codex reviews it. #156 closes after #165 merges, and its branch is kept. Two stages, with every rule fixed now: stage 1 runs on the current windows; stage 2 runs on full-range-2017-2024 (scored) and full-range-2019-2024 (reported only), on identical frozen code. All nine data rules are accepted (hour-level masking, annualised returns, XRP excluded below the tick limit). How the stages combine is **not settled**: Claude proposes "pass both, rank on 2017–2024". Spec v1 and the V2 pre-registration are amended. Docs only.

- **Date and author:** 2026-10-05, written by Claude (session `b9db01ca`).
- **Owner:** answered in Claude's session on 2026-10-05, about 12:10 UTC (decisions 1–3) and about 13:40 UTC (decisions 4–6), per the session's notes.
- **How:** multiple-choice questions. Claude recommended every chosen option except the first long-data answer, which a later answer superseded.
- **Scope:** this record, the spec v1 amendment (`docs/EXPERIMENT_SPEC_V1.md`, "test-plan amendment") and a dated amendment to `docs/STRUCTURE_PREREGISTRATION.md`. No code, config, dataset spec or manifest changes; separate PRs carry those.
- **Why now:** the project forbids changing parameters or criteria after seeing results. This record fixes the test plan before any result of the coming batch exists. No market data, backtest result or strategy result was read for it, and none of #156's result reports was opened.

## What the owner decided, in the owner's words

1. **Test plan.** Chosen: **"Everything, one batch"**. Option text: "Bring V2 into v1 (reversing D20's 'outside v1') and register one 'full stack' combination before any run: V2 structure plus the trend switch, inventory cap, funding, cycle and order-flow gates. It runs in the same batch beside every single variant, so you see both whether the whole system works and which pieces carry it. About a day of extra work; adds a few registered trials."
   - The full stack is V2 structure (`--structure`) + A (trend switch) + B (inventory cap), which make C, + F (order flow) + G (funding) + H (cycle). E is not in it, because E stands alone.
   - V2 alone, which is V0 with `--structure`, also becomes a registered v1 variant.
2. **Daily data.** Chosen: **"Extend to May 2020"**. Option text: "Both datasets get daily history from 2020-05. H works as designed, and A and V2 see full history from the start. The datasets' fingerprints change, so old results stay recorded but aren't compared directly." The datasets are `practice-2022` and `verify-2024h1`, whose `daily_warmup_start` changes (spec P3, P8).
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

Options the owner did not choose:
- Test plan: "Full stack only", "Build multi-mode first" and "Keep the current plan".
- Daily data: "Keep current history".
- Scorer: "Wait for Codex".
- #156: "Leave it open".
- Long data: "After the batch" (first ask); later "One batch, wait for all" and "Keep them out of v1".
- Data rules: "One by one".

## What follows from each decision

1. **One batch.**
   - V2 and the full stack become registered, selectable v1 variants (spec §3, §4, §6). The full stack is a declared combination, reported as an interaction, like C. E stays a single variant.
   - The V2 pre-registration is amended: D20's "Not part of v1" is reversed. Its frozen rules do not change, so there is no `STRUCTURE_FEATURE_VERSION` bump.
   - Spec §3's common rule allows a variant only to add restrictions, with three named exceptions. V2's frozen rules do more than that, so the amendment names a fourth exception (open item 2).
   - `N_family` gains two forward trials. V2's prior trials now fall inside v1's family (spec §6, "The family after the test-plan amendment").
   - Code, in the full-test-setup PR: a flag for the full stack; V2 and the full stack in the scorer's variant list and simplicity order; `--structure` rows admitted (as #167's description says).
2. **Daily data from 2020-05.**
   - Both specs' `daily_warmup_start` becomes 2020-05, and P8's funding and daily entries are added to their manifests (full-test-setup PR).
   - H3 can use the ATH from the 2020-05-11 halving. Variant A's state machine and V2's daily zones start from 2020-05.
   - The spec hashes and manifests change, so earlier results stay recorded but are not compared directly with new ones.
3. **Scorer.** #167 stays Claude's PR for Codex's review, and it scores the spec as it stood. The full-test-setup PR then adds this amendment to it:
   - V2, the full stack and `--structure` rows;
   - annualised returns in C2 and the selection;
   - the stage rule, once the owner settles it.

   #167's description says the amendment's PR would add the variants. This registration is docs only, so that code goes in the full-test-setup PR.
4. **#156.** It closes when #165 merges, and its branch is kept. Its result reports stay there unread for this record. Its V2 runs were already disclosed as prior trials whose results do not count; they now count toward v1's family size.
5. **Two stages.**
   - The long windows are registered now as part of the final verdict (spec §4, §6).
   - Stage 1 gives an early read and names no winner. Stage 2 runs on identical frozen code.
   - How the stages combine is not settled (open item 1).
   - The freeze waits for the long-window inputs, so that nothing stage 2 uses is chosen after a stage-1 result is seen.
6. **Nine data rules.**
   - The rules are in spec §5 (rules 1–6, 8, 9) and §6 (rule 7, annualised returns).
   - On the current windows they mask nothing, so stage 1 is unaffected.
   - Code needed:
     - the repair rule in the archive reader;
     - hour-level masking;
     - the masks written into the results;
     - G must run where funding archives do not exist. #165, as described, refuses G unless the manifest lists funding archives for every evaluation month, which the long windows cannot meet before 2020-01.
   - Bob's work:
     - the re-fetch with daily and funding archives;
     - the XRP price measurement;
     - the 17% check under these rules, which also count incomplete hours.

## Order of work

1. This registration.
2. #165 (variants E–H) and #167 (the scorer).
3. The full-test-setup code: the full-stack flag, V2 and the full stack in the scorer, annualised returns, the P8 manifests and daily history from 2020-05.
4. The long-window data code, then Bob's fetch and measurements, then the long dataset specs and manifests.
5. The spec v1 freeze: Codex's review, and the owner's answers to the open items below.
6. Stage 1, then stage 2, on the frozen code.

## Still open, for the owner before the freeze

Items 1–5 and 7 are Claude's readings or proposals, item 6 is a data question, and item 8 is a consequence to note. All must be settled before any stage-1 result is seen.

1. **How the stages combine.** The owner's answers do not settle it. The current windows lie inside 2017–2024's evaluation period (2019-01 to 2024-12).
   - **Proposal:** a variant is selected only if it passes C1–C6 in stage 1 and in stage 2, where stage 2 means 2017–2024 scored on its own, not pooled with the current windows. The selection steps then rank the variants that pass both stages, on 2017–2024.
   - **Alternative:** pool all scored windows into one evaluation. This double-counts 2022 and 2024H1.
2. **V2's exception to spec §3's common rule.** V2's sixth regime vote can change whether a frame is eligible, in either direction. So V2 can skip an eligibility pause that V0 would start. A sell target raised above the top level widens the band the range exit watches. Bringing V2 in unchanged requires naming this. The alternatives are to re-register V2 with changed rules, which bumps its version, or to take V2 out of v1 again.
3. **What "annualised" means.** Compound: (final ÷ initial)^(365.25 ÷ days) − 1, with days counted over C5's window. The alternative is simple scaling. The two agree closely on the short windows and differ on the long one.
4. **The simplicity order:** V0, A, B, F, G, H, E, V2, C, C+G, C+H, C+F+G+H+V2.
5. **Two readings of the data rules:**
   - "Excluded" for a pair-month over 17% means that all of its hours are masked and the window stays, as rule 5 uses the word.
   - A repaired hour with no minutes to check it against is masked. The owner said this for basket symbols. By the same reason, Claude applies it to the traded pairs' hourly warm-up months.
6. **The 2017–2024 window's daily warm-up.** Its spec, on #156's branch, says the 2018-05 and 2018-06 daily archives are missing.
   - Daily bars from 2018-07-01 give 184 completed days before 2019-01-01, short of P3's 200. P3 makes that fatal for every pair.
   - If confirmed, the start or the daily history must change. That change must be decided from archive availability alone, before the freeze.
   - The spec's comments also say its evaluation starts 2018-11, while its `start` value is 2019-01.
7. **Sensitivities in stage 2.** They are reported only and decide nothing. Claude suggests stage 1 only, given the 7–12× compute.
8. **The reserved window.** §7 applies "the §5 rules" there, so masking rules 1–5, and rule 7's annualised returns, bind the reserved run as well. They are fixed now, before its data is fetched, as §7 requires.

The trial count is in spec §6. It is 19–20 central and 23–24 sensitivity with V2 and the full stack. With V2's prior trials it is at least 21–22 and 25–26. All are floors.

## What Claude checked

- **Read:**
  - spec v1 in full;
  - the coherence record (counting rules);
  - the V2 pre-registration;
  - the eligibility record and Bob's repair-rule task and report;
  - `START_HERE.md` §0–§1;
  - the D17–D21 record;
  - the #165 and #167 descriptions;
  - the dataset specs: `full-range-2019-2024.toml` on main `2f645fe`, and `full-range-2017-2024.toml` on #156's branch `65a7eb0` (configuration only).
- **Code facts cited in the spec,** read at `2f645fe`:
  - an ineligible frame starts a V0 eligibility pause (`runner.py` L721–722);
  - the sixth vote changes the score and the dispersion (`regime.py` L126–135);
  - V2's level filter runs before B's cap (`runner.py` L1112–1139);
  - the incomplete-hour and missing-minute checks are fatal today (`backtest/__main__.py` L62–69);
  - gaps add no outside-range time (`runner.py` L536–564);
  - open and close quotes are two ticks wide on a low-priced pair (`replay.py` `bar_quotes`).
- **Computed by script:**
  - window lengths: 245, 182, 2,192 and 2,011 days;
  - 184 days from 2018-07-01 to 2019-01-01;
  - XRP's limit: 0.0002 ÷ 0.0015 = 2/15 ≈ 0.1333.
- **Not checked:**
  - whether the 2018-05/06 daily archives are really missing;
  - XRP's prices;
  - any mask of the long windows.

  All three need data, which Bob measures in step 4.
