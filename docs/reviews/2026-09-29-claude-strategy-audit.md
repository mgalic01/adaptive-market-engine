# Claude → the owner, Bob and Codex: strategy audit of v1 at 344f9ae (what holds, what to correct, what you need to decide)

Index: 2026-09-29 strategy audit of `main` at 344f9ae across eight areas, every finding checked by independent verifiers who tried to refute it. **Verified sound:** a completed grid buy-and-sell pair is profitable in both fee scenarios, and the vault, going flat in a downtrend, funding (a signal only) and minimum-notional handling at 100 units all check out. **Three corrections to merged records:** the v2 research's "V0 (always grid)" is really the *ungated* V0, its "Dual MA (variant A's states)" row is not variant A, and resting grid fills cost the maker fee (0% primary), not 0.14% a leg. **18 owner decisions**, each with numbers, options and a recommendation; the ones that change V0 or the scoring must be settled before any variant runs. **Still to build before v1 can finish:** the variant axis (this PR, phase 2), E/F/H and G's wiring, the comparison mask, and a C1–C6 scorer. This PR also adds 14 tests the amendment and variant B require; one is an expected failure that shows a real spec/code mismatch (an exhaustion halt is not refused by the risk check). **Phase 2 (2026-10-04), the V2 code audit, section (g):** the V2 market-structure code merged since 344f9ae read future daily bars and changed V0 for every run without a flag (issue #158). This PR fixes the lookahead, puts all V2 behaviour behind an off-by-default `--structure` switch (V0 proved byte-identical to 344f9ae), labels every result with what produced it, makes variants A, B and C runnable, and makes the CI runner check its data. Results produced since #151 on specs with daily bars are invalid. Three new owner decisions, D19 to D21. **Phase 3 (2026-10-05), section (h):** the owner's decisions of 2026-10-02 (D1–D16, Bob's `65a7eb0`) recorded in the decisions table; D7 (a soft-drawdown episode that has already recovered closes without a rebase, its 92% boundary now worded consistently), amendment 2 (a flat account clears its old band) and amendment 3 (the range-exit clock stands still while halted) implemented as engine `drawdown-recovery-v2`, schema 8. On the synthetic datasets only gated V0 moves, through amendment 2 (three fictitious range exits per run removed), and D is unchanged. On 2026-10-05 the owner confirmed D7's wording and decided D8, D9 and D11–D14 as recommended: D9's separate fill trigger is implemented (default unchanged; the synthetic results stay byte-identical), and the rest are recorded (D8 in spec §8, D11 and D13 as comments, D12 already done in #159, D14 unchanged). Codex's five spec findings on #163 are fixed: V0's engine and schema, `N_family` 17–18 and 21–22, amendment 3's wording at a halt, the economic bar matched to §8, and the missed-fill row.

- **Date:** 2026-09-29. **Author:** Claude (coordinator session `e0b16be3`, strategy slice).
- **Base:** `origin/main` at 344f9ae. Paper-only. No market data was read and no backtest
  ran on real data; every figure below is recomputed from the repository's own formulas
  or quoted from committed result files. **Nothing was tuned:** no config value,
  threshold or strategy constant changes in this PR.
- **This PR (strategy PR, phase 1):** tests and documents only. Phase 2 adds the variant
  axis in code.
- **Phase 2 (2026-10-04, Claude session `b9db01ca`):** the V2 code audit and its fixes,
  stacked on the code-audit PR #159. See section (g).
- **Phase 3 (2026-10-05, Claude session `b9db01ca`):** the owner's decisions of 2026-10-02
  and 2026-10-05, and the engine changes for D7, D9, D15 and D16, on
  `claude/amendments-2026-10` (PR #163), stacked on this PR. See section (h).

## (a) What the audit checked, and how

Eight areas, each examined by its own auditor reading the code and the documents at
344f9ae:

1. **Grid economics:** is a completed buy-and-sell pair profitable after fees, and which
   fee applies to which fill?
2. **Grid admission:** the level count, the spacing floor (spacing at least 3 × the
   round-trip cost) and the opportunity gate.
3. **Sizing at 100 units:** order sizes, concentration, minimum notional and rounding.
4. **Risk controls:** the daily pause, the soft and hard drawdown, and amendment 1's
   rebase, automatic restart and manual resume.
5. **Downtrend behaviour:** does the bot go flat and stay flat, and what variant A adds.
6. **The profit vault:** when profit is set aside, and whether it can be counted twice.
7. **The fill and cost model:** how conservative it is and what sensitivity is owed.
8. **Spec against code:** which v1 variants, matrix cells, masks and criteria exist.

**Adversarial verification.** Every finding was handed to independent verifiers whose
job was to refute it: re-read the code, recompute the arithmetic, reproduce the claim.
A finding survived only if the verifiers could not break it. Findings that did not
survive are listed in (f), each with the reason, so nobody re-raises them.

**What this PR changes (tests and two documents, no engine code):**
- `tests/test_drawdown_recovery.py`: spec amendment 1 lists the tests required before
  any rerun. The code audit flagged three gaps; checking the list against the whole
  suite found **nine** required cases that no test exercised: no restart while the
  day's loss is 3% or more; never a restart for `emergency` or `exhaustion` halts (only
  `integrity` was tested);
  a soft episode closed by a `drawdown` halt, with no rebase after the restart until a
  new episode's own 24 hours, and none after a manual resume; no restart on an
  ineligible frame; a restart that keeps a dust residue held and marked (the existing
  test named "admits dust" actually sells everything, so it never held dust); no
  rebase on a stale-data frame; a halt keeping its identity through five more exit
  frames, and an emergency halt past 12% staying `emergency`; a manual resume refused
  while the emergency flag is set, and an `exhaustion` halt refused by the risk check;
  and C1(a)'s peak surviving a restart (a replay test). Each new test was checked by
  breaking the engine rule it covers in a scratch copy: it failed every time.
- **One is an expected failure, and it is a real spec/code mismatch.** The spec says an
  `exhaustion` halt "is refused for good (drawdown 1.0)" by the manual resume's risk
  check. The engine raises an exhaustion halt only from the harvest step, which runs
  only when the risk check has *not* halted the account, so every exhaustion halt starts
  under 12% drawdown, and a resume can be admitted when it is under 8%. The account is
  still final in practice (the next frame halts it again, which a companion test pins),
  but not for the reason the spec gives. Decision D18 below.
- `tests/test_inventory_cap.py`: two simulator-level tests for variant B's reentry at the
  cap (resized, and capped to zero), through the runner's real wiring and its journal.
  Swapping the price and quantity in that wiring, or unwiring it, used to pass the whole
  suite; now both break these tests.
- `docs/EXPERIMENT_SPEC_V1.md` §3 B: prospective active equity now says "limit ×
  **remaining** quantity" for resting buys (and the proposed buy at its full quantity),
  as the committed-exposure line and the code already do. Wording only.
- `docs/PAPER_SIMULATION.md`: "every manual resume attempt is refused" now carries the
  dust-residue margin the spec already states, and the exhaustion sentence says why that
  halt is final.

## (b) Corrections to merged records

The merged files stay exactly as merged; this section is the correction of record.

**1. The v2 downtrend research (PR #137) names the wrong "keep gridding" arm.** Its
section 6 says the bounce question is "V0 (always grid) against variant A". The spec's
V0 is **gated**: its opportunity score is capped by a regime factor of 0.20 in BEAR and
0.35 in TRANSITION bars, below the 0.70 entry minimum, so **gated V0 can never open a grid
in those bars.** In `verify-2024h1` those two labels covered 57% of bars, and the gate
kept V0 paused for a low score in 84–93% of bars (the published run, at 0.1% fees).
Gated V0 did trade the 2022 bear window at the primary fees (98–101 BTC grids; resting
sells +11.5 to +12.6 USDT against forced exits −9.6 to −10.3), but only in bars the
market detector called RANGE. **The true always-grid arm is the ungated V0**, the §4
baseline that already runs everywhere V0 runs and is never selectable. Read recommendation 2 of that record as "**ungated V0** (with gated V0
alongside) against A, over Down periods". Decision D3 turns this into a preregistered
readout.

**2. The same record's "Dual MA 50/200 (variant A's states)" row is not variant A.** Its
script goes long on a single day with close above SMA200 **and** SMA50 above SMA200;
variant A's Up needs **two consecutive** closes above SMA200 and never compares SMA50 with
SMA200. Only the Down side matches (the row's 840 short days equal section 2's 840 Down
days), so the conclusion against shorting stands. But the long-only figures (+593%, 56%
drawdown, 1,156 days long, 31 switches) must **not** be read as "variant A, long-only",
and the line "standing aside is the published edge; F3 is the rule working" leans on
that row. Measuring A's real states long-only would be a new research measurement,
subject to the open trial-count question.

**3. The audit briefing's cost premise was wrong.** The briefing assumed every grid leg
costs taker 0.09% + slippage 0.05% = 0.14%, so 0.28% a round trip. In the engine, **a
resting grid fill pays the maker fee (0% in the primary Revolut X scenario, 0.1% in the
sensitivity one) at its limit price, and slippage there is only a stricter fill trigger,
never a cash cost.** The 0.14% per leg applies only to marketable exits (range exit,
drain, liquidation, trend exit), to the equity mark and to buy-and-hold. The 2022 fee
diagnostic agrees: under 0.5 USDT of fees in eight months, while forced exits realised
−9.6 to −22.3 USDT. **Improvement work should target forced-exit losses and grid
admission, not fee drag.** Codex's fee-measurement review had already confirmed this
routing.

## (c) Verified clean

- **Pair economics at the 3× floor.** The minimum spacing is 0.45% at primary fees and
  1.05% at the sensitivity fees. A completed pair breaks even at 0% (primary) or 0.20%
  (sensitivity), and even if both legs paid 0.14% (break-even 0.28%) the floor keeps a
  1.6× margin. A completed 20-unit pair at the floor earns about +0.09 (primary) or
  +0.17 (sensitivity); reentries keep the pair's prices.
- **Vault timing.** It sets aside only realised, after-fee profit, only when the account
  is flat with no orders; the high-water mark stops the same profit being set aside
  twice and makes losses be recovered first; transfers cannot be booked twice.
- **Going flat in a downtrend.** An ineligible frame cancels buys, stops reentries and
  sells unpaired coins; paired coins leave through their own sells or the 6-hour range
  exit; a new grid needs two confirming frames and a fresh opening decision (caveat:
  D8).
- **Funding is a signal only.** Variant G's funding rates only block new grids; no
  funding cash flow is booked, which is right for a spot-only bot with no perpetual
  position.
- **Minimum notional at 100 units.** All four dataset pairs have a 5.00 minimum; orders
  are 11.43–80 units, so lot rounding loses at most one step and stays at least twice the
  minimum. A buy rounded to zero by the cap is skipped and recorded. (Latent only: V0
  refuses the whole grid where B would skip one level; it matters only at a 10-unit
  minimum.)
- **Also checked:** the soft-drawdown pause and variant B's cap cannot conflict (the
  pause is a full stop and drain; the cap only shrinks new buys).

## (d) Decisions for the owner

None of these can be applied quietly. The project's rules say a parameter, a criterion or
V0's behaviour changes only by a recorded owner decision **before** the results it could
affect are seen (no tuning; pre-registration). Where I recommend something, it is only a
recommendation.

**The owner's decisions.** The last column records them. Those of 2026-10-02 are as Bob
wrote them into the spec in `65a7eb0` (PR #156), which the owner confirmed on 2026-10-04;
that commit is cherry-picked onto `claude/amendments-2026-10` (section (h)), and it also
adds the owner's economic-bar note to §6, which Bob's handoff (#162) lists under D5. On
2026-10-05 the owner confirmed D7's wording and decided D8, D9 and D11–D14, each as
recommended. D17–D21 are still open.

| # | Question, short | Recommendation | Decide before | Owner's decision |
| --- | --- | --- | --- | --- |
| D1 | Try 7 or 6 grid levels before giving up? | Not in V0; pre-register for v2 | first variant run | Keep 8-or-nothing for v1, option (a), as Bob's handoff (#162) states; the spec needs no change for it |
| D2 | Say that entries happen in RANGE only? | Yes, write it down | first variant run | (a): written into §3's common rules; entries are RANGE-only in practice, and H3 can act only in RANGE |
| D3 | Preregister a Down-period readout? | Yes, reported only | any variant result is seen | (a): preregistered in §6, reported only: ungated V0, gated V0 and A over A's own Down days |
| D4 | Keep C5/C2 although they score A's idleness as 0? | Keep; D3 answers the bounce question | any variant result is seen | (a): C5 and C2 unchanged for trend-gated variants; D3 answers the bounce question |
| D5 | Add a Kraken-fee scenario? | Yes, reported only, after checking the fees | first variant run | (a) and (b): a Kraken scenario (0.0025 / 0.0040), reported only, its fees checked before the first run; a move to Kraken reopens acceptance |
| D6 | What does "SMA undefined" mean for A? | Keep the strict rule; write it down | A's first run | (a): the strict rule, with its 200-day consequence, written into §3 A |
| D7 | Stop the heal-then-rebase ratchet? | Yes | first variant run | (a), 2026-10-02: amendment 1, step 3. Its wording at exactly 92% (strictly above closes) **confirmed by the owner 2026-10-05**. **Implemented** (h) |
| D8 | Keep risk checks off on wide-spread frames? | Keep for v1, record it | any live or forward paper run | **Owner decision 2026-10-05:** (a), kept for v1; the exposure is recorded in spec §8, to be decided before any live or forward paper run |
| D9 | A separate fill-trigger setting for sensitivity? | Yes, default unchanged | sensitivity runs | **Owner decision 2026-10-05:** (a), a separate fill trigger, default unchanged. **Implemented** (h) |
| D10 | Schedule the promised sensitivity runs? | Yes, values fixed in advance | results count as acceptance evidence | (a): scheduled in §4 with fixed values: spread 0.10% and 0.20%, participation 5% and 20%, missed fill 0.02% and 0.10%, timing +1 and +5 bars |
| D11 | Rotation and universe settings that do nothing | Keep inert, comment them | no deadline | **Owner decision 2026-10-05:** (b), kept inert with values unchanged, removed with the first schema change after v1; noted in the rotation module (h) |
| D12 | The unused "25%" on a soft drawdown | Remove it | no deadline | **Owner decision 2026-10-05:** (a), removed; already done in #159 |
| D13 | Two SMA helpers with opposite gap rules | Comment only | no deadline | **Owner decision 2026-10-05:** a one-line comment at each helper (h) |
| D14 | V0 can put 80% of the account in one buy | No change; that is what B tests | variant selection | **Owner decision 2026-10-05:** no change; variant B tests it |
| D15 | Old grid bounds kept after going flat (disputed) | Clear them, with a version bump | first variant run | (a): spec amendment 2. **Implemented** (h) |
| D16 | Range-exit counter inflated during halts | Stop the clock while halted | first variant run | (a): spec amendment 3. **Implemented** (h) |
| D17 | Halts at 8–12% can never be resumed by hand | Allow a resume with a rebase | any forward paper run | Open |
| D18 | Exhaustion halt: refused, or final in effect? | Refuse it by category | any forward paper run | Open |
| D19 | The FTA cap is a hidden entry veto: redefine it? | An explicit, registered veto, or levels re-spaced below the FTA | any V2 run | Open |
| D20 | The RANGE-only FTA rule was chosen after seeing results | V2 under a spec v2 with registered trials, parameters frozen first | any V2 rerun | Open |
| D21 | Equal highs (double tops) are invisible to swing detection | Decide on purpose; no change without your decision | any V2 run | Open |

### D1. Should a grid try fewer levels before giving up?

- **Question.** Today a grid has exactly 8 levels at 100 units, and if 8 levels are too
  tight for the costs, no grid opens, even though 7 or 6 levels would pass.
- **Numbers.** The band is fair value ± 2 × hourly ATR. At primary fees the spacing must
  be at least 0.45%, which needs ATR of at least **0.7857%** of price with 8 levels,
  **0.6734%** with 7 and **0.5612%** with 6. BTC's median hourly ATR in `verify-2024h1`
  was 0.70%: the median hour **fails at 8** levels (spacing 0.40%) **but passes at 7 and
  6**. At the sensitivity fees, 8 levels need ATR ≥ 1.83%, which is why BTC allowed a
  grid in only 1.8% of hours there. The config already has a minimum of 6 levels.
- **Options.** (a) Keep 8-or-nothing. (b) Step down 8 → 7 → 6 until the spacing passes,
  as a change to V0. (c) Pre-register "fewer levels" as its own variant.
- **Recommendation.** (a) for v1, and pre-register (c) for v2. More grids also means
  more forced exits: the fee diagnostic found that cheaper costs admitted more grids and
  more of them ended in a loss-making exit.
- **Why not quietly.** It changes which grids open, so it changes every V0 result (the
  control). `verify-2024h1` already named "fewer levels" as a candidate after seeing
  results; adopting it now would be tuning. As a v1 variant it would add a trial to the
  family.

### D2. The regime factor is a hidden veto: say so?

- **Question.** The opportunity score is multiplied by a regime factor, and the entry
  minimum is 0.70. Do you accept that this means "no new grids outside RANGE", in
  practice?
- **Numbers.** Factors: RANGE 1.00, BULL 0.80, TRANSITION 0.35, BEAR 0.20, STRESS 0. So
  TRANSITION and BEAR **can never** pass 0.70, whatever the pair's quality, and BULL
  needs a near-perfect base score (0.875). In `verify-2024h1`, TRANSITION + BEAR were
  57.4% of bars. Variant H3 lowers the minimum to 0.60 in deep-discount phases, which is
  still above 0.35 and 0.20, so **H3 can only act in RANGE** (or an almost perfect BULL).
- **Options.** (a) Record in the spec that entries are RANGE-only in practice and that H3
  cannot act in TRANSITION or BEAR. (b) Replace the factor with an explicit, registered
  regime rule.
- **Recommendation.** (a) now (no behaviour change); consider (b) for v2.
- **Why not quietly.** Any number changed here changes V0 and every gated variant.

### D3. Preregister a Down-period readout (your bounce question)

- **Question.** The research said "sell the bounces or step aside?" is answered by
  comparing the gridding arm with variant A **over Down periods**. The spec scores only
  whole windows, so v1 as written will not answer your question.
- **Numbers.** No Down-conditioned metric exists in the spec or the method document. The
  data will exist (exit P&L by reason, the trend state at every step).
- **Options.** (a) Add a **reported-only** readout before any variant result is looked
  at: which days count (Down only, or Down plus Middle, per traded pair, from A's own
  classifier), which arm is "keep gridding" (ungated V0, with gated V0 alongside, per
  correction 1), the measures (return, forced-exit P&L by reason, completed cycles on
  those days) and the regime-label mix on those days. (b) Leave it, and accept that v1
  does not answer the question.
- **Recommendation.** (a). It adds no variant and no trial.
- **Why not quietly.** Slicing results by regime **after** seeing variant runs is an
  adaptive analysis under the project's data-reuse rule; defined in advance it is not.

### D4. C5 and C2 score variant A's idleness as a failure

- **Question.** A stands aside in downtrends by design. The minimum-activity rule (C5)
  and the "makes money" rule (C2) count that idleness against it. Keep them as they are?
- **Numbers.** On A's own classifier BTC had **no** Up day in 2022, and `practice-2022`
  evaluates 2022-06 to 2023-01, so A's practice runs have close to zero completed cycles.
  With SOL excluded there are 8 included runs; if the 4 practice runs are about 0, the 4
  `verify-2024h1` runs must average about **2 completed cycles a week** (about 52 per
  26-week run) for C5's mean to reach 1, twice what C5 asks of the family overall. For
  C2, with two of four runs per path at 0, A passes only if both bull-window runs make
  money.
- **Options.** (a) Keep C5 and C2, and record that A's verdicts on them do not answer the
  bounce question (D3 does). (b) Amend C5 for trend-gated variants, for example a rate
  over grid-eligible days.
- **Recommendation.** (a): the criteria stay fixed, and the question gets its own
  readout.
- **Why not quietly.** A criteria change prompted by development measurements must be
  your recorded decision before variant results are seen, disclosed as amendment 1 was.

### D5. Add a Kraken-fee scenario?

- **Question.** v2 names Binance and Kraken, but v1 tests only Revolut X fees (0 / 0.09%)
  and one 0.1% / 0.1% sensitivity. Will v1's verdict carry over?
- **Numbers.** At Kraken's lowest public tier (about 0.25% maker / 0.40% taker; to be
  checked before use) the round-trip cost is 0.65%, so grids need **1.95%** spacing
  instead of 0.45%: a different strategy. Results already flip sign between fee levels:
  XRP gated +5.60/+5.83% at 0.1% but −4.15/−2.87% at primary; BTC gated −1.20% at 0.1%
  but +1.22/+2.98% at primary.
- **Options.** (a) Add one reported-only Kraken-tier scenario (for example 0.0025 /
  0.0040) to the §4 matrix now, fixed before any variant run, never used for acceptance.
  (b) Record in the spec that a move to Kraken reopens acceptance from scratch.
- **Recommendation.** (a), after the fee schedule is checked; it costs compute, not
  trials. (b) holds either way.
- **Why not quietly.** Fees are parameters; adding a scenario after seeing results would
  be choosing the test after the answer.

### D6. When is variant A's moving average "undefined"?

- **Question.** The spec says A has no new grids when SMA50 or SMA200 is undefined, but not
  when that is.
- **Numbers.** Today one missing daily bar makes SMA200 undefined for the next **200
  days**, so A sits out that long (confirmed: one gap at day 250 of 400 made all 150 later
  days unavailable). Registered backtests cannot hit this (a missing day fails the
  dataset check), but a live or paper feed has no such guard, and a 200-bar warm-up with
  a gap does not guarantee a defined SMA200.
- **Options.** (a) Keep the strict rule (any missing day undefines it) and write it, with
  the 200-day consequence, into §3 A. (b) Average over the days that exist.
- **Recommendation.** (a): fail-closed, and no change to any registered run.
- **Why not quietly.** Either choice changes A's behaviour on gapped data.

### D7. Stop the heal-then-rebase ratchet

- **Question.** After an 8% dip opens a soft-drawdown episode, the reference is lowered
  24 hours later **even if the account has already recovered**. Stop that?
- **Numbers.** Peak 100, a dip to 91.9 opens an episode, price recovers to 98 and trading
  resumes; 24 hours after the dip the rebase still happens and the reference drops from
  100 to 98, so the 8% and 12% limits are now measured from 98. Repeated dips with partial
  recoveries keep lowering the reference without the 12% halt ever firing. C1 is
  unaffected (its reference is never rebased). A new test here shows such an episode
  staying open at 6.6% below the reference.
- **Options.** (a) Close an episode without rebasing if, when the rebase would commit,
  the drawdown is already under 8%. (b) Keep it and state it in the spec as accepted.
- **Recommendation.** (a). Every lockout it was built to relieve still gets relief.
- **Why not quietly.** It changes a risk control (a spec amendment and an engine version
  bump), and V0 results with healed dips move.

### D8. Risk checks are off while the quoted spread is wide

- **Question.** A frame whose spread is above 0.15% is rejected as bad data, and on those
  frames the bot runs no risk check, no range-exit clock, no drain and no retry of a halt
  liquidation. Keep that?
- **Numbers.** Replay never produces such frames (it assumes a constant 0.05% spread); the
  only historical case was the SOL tick artefact (5.9% of frames). Live downtrends on
  small pairs can hold wide spreads for long stretches, holding falling coins with no
  exit path.
- **Options.** (a) Keep "fail closed on bad data" and record the exposure in §8. (b) Run
  risk checks and forced exits on wide-spread frames, marking at the observed bid.
- **Recommendation.** (a) for v1 (replay cannot reach it); decide (b) before any live or
  forward paper run.
- **Why not quietly.** It changes a risk control, which needs a spec amendment.

### D9. One setting does two jobs (fill trigger and exit cost)

- **Question.** The 0.05% slippage both makes resting fills harder (a price must cross the
  limit by it) and is the cash cost of marketable exits and marks. Split them for testing?
- **Numbers.** With the spread, a resting fill needs about 0.10% of price penetration per
  leg, about 22% of the 0.45% minimum spacing. Sweeping the one setting to test missed
  fills would also change exit costs and buy-and-hold, so the results could not be read.
- **Options.** (a) Add a separate fill-trigger setting that defaults to the slippage
  (current results unchanged), used only in labelled sensitivity runs. (b) Keep one
  setting and accept blurred sensitivity results.
- **Recommendation.** (a), decided together with D10.
- **Why not quietly.** It is a new parameter, and the values to sweep must be fixed in
  advance.

### D10. Schedule the sensitivity runs the method promises

- **Question.** The method document says spread, participation, path, missed-fill and
  timing sensitivity must be reported before any result counts as acceptance evidence.
  Only the fee diagnostic exists. Schedule the rest?
- **Numbers.** The fill model is deliberately strict (about 0.10% penetration per leg, no
  price improvement, 10% of a quarter-bar's volume per quote), but queue position at a 0%
  maker venue is not modelled and the method says the model is "not proven conservative".
- **Options.** (a) Schedule them, with their values fixed now, before C1–C6 results count.
  (b) Amend the method document to defer them explicitly.
- **Recommendation.** (a).
- **Why not quietly.** Choosing sweep values after seeing results is tuning.

### D11. Rotation and universe settings that do nothing

- **Question.** The rotation module and the `[rotation]` and `[universe]` settings (top
  100 plus NIGHT, up to 5 grids) have no effect on trading; the engine trades one pair.
  The universe check can still refuse to start. Remove them or keep them?
- **Numbers.** Zero rotations happen today. If rotation were wired as written, nothing
  computes the "expected improvement" or "switching cost" it relies on, and confirmations
  count calls, not time.
- **Options.** (a) Remove them until multi-market work starts. (b) Keep them, marked as
  reserved and inert, and before any wiring pre-register a dwell time per confirmation, a
  cooldown that also covers the first rotation, and how improvement and switching cost
  (the full 0.28% round trip plus rebuild exposure) are measured.
- **Recommendation.** (b) for now: the settings are part of every saved paper account's
  identity, so removing them would make existing accounts refuse to open. Remove them
  with the next schema change.
- **Why not quietly.** Config values are parameters, and removal changes account identity.

### D12. The unused "25%" on a soft drawdown

- **Question.** The risk engine returns a 25% capital multiplier with a soft-drawdown
  signal, but nothing reads it: a soft drawdown is a full pause and drain. Remove it?
- **Options.** (a) Remove it. (b) Keep it with a comment that the paper engine ignores it.
- **Recommendation.** (a), in the code-cleanup PR; no behaviour changes.
- **Why not quietly.** Using it (partial sizing on a soft drawdown) would be a new risk
  rule the spec does not authorise; removing it just stops anyone reviving it by accident.

### D13. Two moving-average helpers with opposite gap rules

- **Question.** The hourly SMA50 (used by V0's regime) skips gaps; A's daily SMA refuses
  them. Both are right for their own purpose. Merge them?
- **Recommendation.** No; add a one-line comment at each saying why they differ.
- **Why not quietly.** Changing either gap rule changes V0's regime or A's states.

### D14. V0 can put up to 80% of the account into one buy

- **Question.** Context for choosing variants, not a change.
- **Numbers.** V0 spends 80 of 100 units across the levels below the price. With one
  level left below the price, one buy takes all 80 units. `verify-2024h1` saw unsold coins
  average 38–70% of the portfolio while invested.
- **Options and recommendation.** No change in v1: variant B's 40% cap is the
  pre-registered treatment for exactly this. Read B's results with it in mind.
- **Why not quietly.** Changing V0's sizing would change the control.

### D15. Old grid bounds are kept after the bot goes flat (disputed)

- **Question.** When a grid sells out and no new grid opens (a pause, a closed gate, too
  little spacing), the account keeps the old band. If price then stays outside that band
  for 6 hours, the empty account records a range exit and waits up to 24 hours before a
  new grid. Is that a bug?
- **Numbers.** In the reproduction, the next grid opened after **1,382 minutes**; with the
  bounds cleared it opened after **1 minute**. Each such event is also counted in
  `range_exits`.
- **View 1 (the code audit's critic): a defect.** No grid exists, so the "range exit" is
  fictitious; it delays re-entry and inflates the range-exit count. Codex already treated
  the same mechanism as a defect in variant A (PR #114), and the fix there clears the
  bounds only when a Down sequence ends, so A and V0 now differ in one case, which blurs
  the A-versus-V0 comparison.
- **View 2 (a verifier): intended.** It is V0's "do not chase price" rule: after running
  away from the old band, the bot waits (6 hours outside, then the 24-hour recenter
  cooldown) instead of rebuilding at once around the new price.
- **Options.** (a) Clear the bounds whenever the account is flat with no grid and no
  range exit pending (V0 results move; engine version bump; a V0 regression test). (b)
  Keep it, document it as intended, and make A behave the same way so both share one
  control.
- **Recommendation.** (a): a flat account with no orders has no grid to protect, and
  the no-chase rule still applies to a grid that actually left its band. Either way,
  decide before the first variant run, because it changes V0.
- **Why not quietly.** It changes V0's results, the control every variant is measured
  against.

### D16. The range-exit count is inflated during halts

- **Question.** The 6-hour outside-range clock keeps running on a halted account, so
  almost every hard-drawdown halt (price below the band for its 24-hour cool-off) also
  records a range exit. Fix the count?
- **Numbers.** Trading is unaffected (restart and resume reset the state), but
  `results.json` and the summary's "Range exits" column over-count by about one per
  drawdown halt, and amendment 1 allows several halts per run.
- **Options.** (a) Stop the clock while halted. (b) Keep it and footnote the column.
- **Recommendation.** (a).
- **Why not quietly.** It changes a reported metric, so the engine version and how
  existing results are read both change.

### D17. A halt taken 8–12% below the reference can never be resumed by hand

- **Question.** An `integrity` or `emergency` halt that happens while the account is 8–12%
  below its reference is refused on every manual resume, forever. Amendment 1 was written
  to remove exactly this kind of lockout. Allow a resume?
- **Numbers.** Reproduced: an integrity halt at 8.28% below the reference was refused on
  day 6, day 30 and day 365. Replay is unaffected (it never raises an emergency, and an
  integrity halt invalidates a run); a paper account is bricked by one bad feed frame at
  the wrong moment.
- **Options.** (a) Let a manual resume that is refused only by the soft drawdown do what
  the automatic restart does: require the tentative ALLOW, rebase the breaker reference to
  current equity (never C1's), and record the rebase. (b) State in the spec and in the
  refusal text that such a halt is final.
- **Recommendation.** (a), matching your principle that after a loss the bot pauses at
  most a day and then trades again.
- **Why not quietly.** It changes a risk control, so it needs a spec amendment and a test.

### D18. An exhaustion halt is final, but not for the spec's reason

- **Question.** Found while adding the required tests. The spec says an "active capital
  exhausted" halt is refused by the manual resume's risk check because its drawdown is
  pinned at 1.0. It is not: the halt is raised only on a frame the risk check allowed,
  so a resume can be admitted when the drawdown is under 8%. The next frame halts it again,
  so it never trades. Which should change, the code or the spec?
- **Options.** (a) Make the manual resume refuse the `exhaustion` category outright (a
  small code change; the expected-failure test then passes and its marker is removed).
  (b) Change the spec's wording: final because the harvest step halts it again.
- **Recommendation.** (a): it matches the spec's intent literally and is simpler to
  audit.
- **Why not quietly.** The spec's text and its required-test list say otherwise; one of
  the two must change on the record.

### D19. The FTA cap is a hidden entry veto (V2)

- **Question.** V2's "first trouble area" (FTA) cap was meant to keep a grid's sell
  targets just below the nearest resistance. In practice it never moves a sell target
  that is actually placed: it either does nothing or stops the grid from opening. Which
  do you want it to be?
- **Numbers.** The engine places buy-and-sell pairs only *below* fair value: with 8
  levels, the highest sell target placed is the first level above fair value. The FTA is
  always *above* fair value. When the cap reaches that first level, it also reaches every
  level above it; they all collapse to the same price, and the engine refuses the grid
  with the message "no distinct, passive buy levels after tick rounding", which names the
  wrong cause. The same happens whenever the cap reaches two or more levels, placed or
  not. In a synthetic sweep of FTA positions between fair value and the top of the band,
  a grid could open in only **24 to 29%** of positions (27% at an ATR of 2% of price),
  and in those the cap changed only the top level, where no order is placed.
- **Options.** (a) Redefine it as what it does: an explicit, registered entry veto ("no
  new grid while resistance sits within X of fair value"), with its own reason message.
  (b) Make it a real sell-target cap: re-space the levels so all of them fit below the
  FTA (a different grid, which needs its own pre-registration). (c) Drop it.
- **Recommendation.** (a) or (b), registered as a V2 trial under a spec v2 (D20) before
  any V2 run. Not a quiet fix: either option changes which grids open.
- **Why not quietly.** It changes V2's results, and V2's results have already been looked
  at (D20).

### D20. The RANGE-only FTA rule was added after looking at results (V2)

- **Question.** The FTA cap applies only when the market is classified RANGE. That rule
  was added after viewing development backtest results (the code cites the 2026-09-30
  comparison, section 8.4, as its diagnosis). The no-tuning rule says a rule chosen after
  seeing results is a trial, and must be counted as one.
- **Options.** (a) Put V2 under a spec v2: list every V2 rule and parameter (swing size,
  zone merge distance, the 500-hour window, the 0.10 vote weight, the 0.999 buffer, the
  RANGE-only gate) as registered trials, freeze them, then run. (b) Treat V2 as
  exploratory only and never as evidence.
- **Recommendation.** (a). Freeze the parameters before any rerun; until then V2 runs are
  exploration.
- **Why not quietly.** Choosing among rules after seeing their results is exactly what
  pre-registration forbids.

### D21. Equal highs are invisible to swing detection (V2)

- **Question.** A bar counts as a swing high only if its high is strictly above the 3
  bars on each side. Two equal highs, a classic "double top", therefore produce no swing
  at all, so no resistance zone forms there. The same holds for equal lows. Is that
  intended?
- **Numbers.** On data with exact repeats (a price that tops out twice at the same tick)
  the zone a chart reader would draw is absent. The test suite's regular synthetic hourly
  series repeats its daily highs exactly, so it shows no hourly swings at all; this
  audit's chronology test needed hand-made daily bars partly for that reason.
- **Options.** (a) Keep strict inequality and write the rule down. (b) Allow ties on one
  side (for example "at least as high as the bars before, strictly higher than the bars
  after"), registered under D20.
- **Recommendation.** Your decision; this PR does not change it, as you asked. Any change
  belongs in D20's registered set.
- **Why not quietly.** It changes which zones exist, so it changes the FTA and the
  structure vote.

## (e) What v1 still needs built before it can finish

These are the spec-versus-code gaps that block the experiment itself:

- **Variants A, B and C cannot be run.** The engine has them, but the backtest command
  offers no way to choose them; it runs only V0, ungated V0 and D. *Done in phase 2:*
  `--variant-a`, `--variant-b` (inventory cap 0.40, section 3 B) and `--variant-c` (A and
  B), in the CLI, `scripts/run_nopool.py` and the backtest workflow. Each row names its
  variant, and the results record the policy and the code commit.
- **E, F and H do not exist in the code, and G is not connected.** G's funding signal is
  implemented, but every replay frame allows a new grid unconditionally, so nothing can
  block one. E and H2 also need a variable outside-range time in the engine.
- **No scorer.** Nothing computes C1–C6 or the §6 selection (rounding, tie rule,
  simplicity order). Scoring by hand after results are visible is exactly the flexibility
  pre-registration forbids.
- **No comparison mask.** Any integrity failure aborts the whole dataset instead of
  excluding one pair-window, and the filter-availability check (P4) is enforced nowhere,
  so SOL would be scored if nothing else stopped it.
- **C7's machinery exists only in review documents** (moment conventions, the fold grid,
  a walk-forward runner, a machine-readable trial register). C7 is not settled and gates
  only the reserved window, which stays closed.

**Order of work:**
1. Variant axis for A, B and C (this PR, phase 2).
2. Comparison mask, as a variant-independent pass written into the results before any
   replay, with the 2-included-pairs minimum.
3. A reviewed, tested C1–C6 scorer with the §6 selection, merged before the first variant
   run.
4. Your decisions that must precede any run or any look at results: D1–D7, D15 and D16,
   and D10's schedule. *Decided on 2026-10-02; D7, D15 and D16 are implemented in
   phase 3 (section (h)).*
5. Connect G to the entry gate, with the spec's boundary tests.
6. Build E, F and H with their required tests; E also needs Codex's implementation
   review before it is selectable.
7. C7's machinery, once C7's three open items are settled.

Steps 1–4 come before the first variant run; steps 5–6 before the §6 selection, because
the §4 matrix includes E, F, G and H; step 7 before the reserved window.

## (f) Refuted strategy findings

Each was checked by the verifiers and did not survive; listed so nobody re-raises it.

- **"Half of the 8-level band never holds an order"**: it is 3 of 8 levels, by design
  (first buys sit below both the price and fair value), and the claimed spacing and
  recentering costs did not hold when recomputed with the repository's own grid builder.
- **"The vault's 10-unit transfer threshold drags on a 100-unit account"**: the pending
  reserve is outside active capital before and after the transfer, so the threshold
  changes no grid budget in the paper engine.
- **"The 24-hour restart loop needs a backoff"**: the mechanics are right, but the claimed
  loss per cycle did not survive recomputation, and unbounded cumulative loss is already
  your recorded choice (amendment 1, no overall loss floor).
- **"The restart's field list omits the Down-sequence field"**: the manual resume clears
  it the same way and a restartable account is flat, so any Down sequence has already
  ended; the test's allowed set lists it openly.
- **"A capped grid records the full planned band"**: the facts are right, but the
  range-exit consequence argued from them does not follow; no decision is needed.
- **"Benchmark D's entry ends for good on one thin observation"**: the code does what the
  spec's entry rule says; not a mismatch, and the size of the effect was unsupported.
- **"The daily end-of-day equity series for C7 is not recorded"**: true that none is
  recorded, but C7 is unsettled and gates only the reserved window; it is part of the C7
  work in (e), not a defect today.
- **"Buy-and-hold's drawdown peak starts at the initial capital, flattering the
  strategy"**: the mechanics are right, but recomputed there is no bias in the strategy's
  favour.
- **"The evidence does not support a 'wider grids in Down' variant, so no new variant is
  needed"**: the citations are accurate, but the argument built on them does not hold;
  whether to add any variant remains your decision, not a finding.

## (g) Phase 2: audit of the V2 code (2026-10-04)

Between 344f9ae and the code-audit PR #159, main gained "V2": market-structure features
(swing points, support and resistance zones, a first trouble area), a sixth vote in the
regime classifier and an FTA cap on grid levels (#147, #148, #150, #151, #154). This
phase audited that code; issue #158 has the short version. In plain words:

| Finding | What it means | What this PR did |
| --- | --- | --- |
| **Lookahead** (critical) | The daily structure read *every* daily bar in the dataset, including the decision's own unfinished day and all later days. A backtest decision could see the future. | **Fixed.** Only days that closed at or before the decision minute are read (the same rule as variant A). The caches now refresh when a day closes. A new test changes and adds daily bars after the decision and checks that nothing changes; it fails on the old code. |
| **V0 changed without a flag** (critical) | V2 changed the baseline for everyone: the trend vote's weight fell from 0.35 to 0.25, a sixth vote was added (for the live paper bot too), and the FTA cap applied to every backtest. The spec requires new behaviour behind a switch that is off by default. | **Gated.** All V2 behaviour now sits behind `--structure` (`SimulationPolicy.structure`), off by default. With it off, V0 is restored: its `results.json` is byte for byte the same as at 344f9ae on synthetic data (below). With it on, V2 runs as on main, minus the lookahead. |
| **Labels** (major) | V2 results carried the same version labels as V0 results, and no code commit, so nobody could tell them apart. | **Fixed.** A structure run is labelled `price-only-v1+structure-v1` in the results and in every row. A variant or structure run records its policy, its variant and the code commit, and says so in its folder name. V0 output keeps its exact layout (`--record-commit` adds the commit on request). |
| **FTA cap is a hidden veto** (major) | It either does nothing or blocks the grid, with a misleading reason. | **Your decision, D19.** Unchanged, and now off by default. |
| **RANGE-only FTA rule chosen after seeing results** | A question under the no-tuning rule. | **Your decision, D20.** |
| **Equal highs make no swing** | Double tops and double bottoms are invisible. | **Your decision, D21.** Unchanged, as you asked. |
| **CI runner skipped the data checks** | `scripts/run_nopool.py` (used by the backtest workflow) skipped the dataset verification and the hourly and daily cross-checks, hard-coded the fees, and still wrote `"valid": true`. | **Fixed.** It is now the CLI's own `run` with `--jobs 1` (no process pool): every check runs first, fees come from the spec, and "valid" means every check passed. The workflow gains variant and structure choices. |
| **Small errors in `structure.py`** | Docstrings that disagreed with the code (the zone-strength formula; the ATR is a simple mean, not Wilder's), an import inside a loop, a garbled character. Zone strength is read by nothing outside the module and its tests. | **Fixed,** with results unchanged. Swing detection is untouched (D21). |

**Results that are invalid as evidence.** Every V0 or V2 backtest produced on main since
#151 on a spec with daily bars (practice-2022, verify-2024h1, long-bull-bear-2022 and
long-recovery-2023-2024) used future daily bars, and every V0 run since #150 used the
changed vote. That includes `docs/reviews/2026-09-30-bob-v2-backtest-comparison.md` and
the "V2 corrected baseline" in PR #156. None of them may be used for decisions. V0
results from before #150, such as the stored drawdown-recovery-v1 runs, are not affected.
Bob's P8 data task is not affected either: it fetches and verifies archives and runs no
replay.

**How V0 was proved unchanged.** Synthetic datasets (fixed-seed random walks: one traded
pair, five basket pairs, two months of hourly warm-up, 245 days of daily warm-up, a whole
month of minute bars; one flat, one falling, one without daily bars) were built through
the pinned dataset code. The real backtest command ran on them at 344f9ae and on this
branch with the switch off, and the `results.json` files were compared byte for byte.
Variants A, B and C were run for all four path and gating cases (at 344f9ae through the
replay itself, which its command could not select); their sorted-key JSON was compared
the same way, without the branch's new "variant" row label. No market data was read and
no backtest ran on real data.

| Run (synthetic) | 344f9ae SHA-256 | This branch, switch off |
| --- | --- | --- |
| Flat: V0 gated, V0 ungated and D (`results.json`) | `eaf29a0a4df9d3f27e3f46629d276c8817dbf47e9101bf16251c2646f96a8a5a` | identical |
| Falling: V0 gated, V0 ungated and D (`results.json`) | `18b76b74511613559fb0da092395a15a6cf4808d5fb460aaa0178bdf3b74d2c1` | identical |
| No daily bars: V0 gated and ungated (`results.json`) | `e4c413c030b551a4a27ad1453e5828b5bc0628b1a9798fce83041a32523e831a` | identical |
| Flat: variant B | `4fe47896e88c56a6e60269f2a532741376afb79e0318463102636f09c497baff` | identical |
| Falling: variant A | `fcc9f5cca9e26c6902a40414080694d69aa3ff608a913a9dcda7a036b367810b` | identical |
| Falling: variant C | `fe0b7fd5ebd071038227a7cef97ce97bb292d83b29fe1d126fa827e29793de91` | identical |

The same data show the switch matters: the code before this PR (d500e75, the head of
the code-audit PR) gives different V0 files
(flat `7e2d66d9…`, falling `ea25f90d…`, no daily bars `aaa4e5bc…`). With the switch on
and no daily bars (so no lookahead to remove), this branch gives main's results exactly,
once the new labels are set aside. With daily bars, removing the lookahead moved V2's
gated return on the flat data from 22.9% to 18.5%.

**What is still owed for V2.** D19 to D21, then a spec v2 with V2's parameters frozen
(D20), before any V2 run counts.

## (h) Phase 3 (2026-10-05): the owner's decisions, and D7, amendments 2 and 3 and D9 in the engine

Branch `claude/amendments-2026-10`, stacked on this PR. Paper-only: synthetic data only,
no market data read, nothing tuned beyond the three rules.

**Spec.** Bob's `65a7eb0` (PR #156) is cherry-picked unchanged. It applied cleanly, and
this PR's own spec edit (§3 B, "remaining quantity") survives. Two additions:
- **A wording fix the owner should see (D7).** Amendment 1's step 3 said "at or above 92%
  of the existing `risk_high` (i.e. the drawdown is already under 8%)", and the two halves
  disagree at exactly 92%. The risk engine counts a drawdown of exactly 8% as soft
  (`loss >= limit`), so a close there would start a new episode on the same frame. The
  step now says "strictly above 92%, that is, below the 8% soft limit as the risk engine
  measures it", with a note. The decision is otherwise unchanged.
- Amendments 2 and 3 now name the engine and schema assigned to them.

**Engine** (`runner.py`, and `replay.py` for the label and one count): engine
`drawdown-recovery-v2`, paper schema 9 (renumbered from 8 on 2026-10-05, when #159 and #160
took 7 and 8), so a schema-8 database is refused by the store and by the resume command.
- **D7.** When an open episode's rebase falls due, the risk engine is asked once more,
  against the unchanged `risk_high`. The tentative check has already passed on that frame,
  so only the drawdown can deny `ALLOW`, by the engine's own exact comparison. If it
  allows, the episode closes and `risk_high` stays: the journal records `episode_closed`
  (episode start, time, equity, reference) and results count `soft_drawdown_closes`, a new
  field beside `soft_drawdown_rebases`. Otherwise the rebase is committed as before.
- **Amendment 2.** At the end of every valid frame, after its fills, exits, settlement and
  any new grid, so it cannot fire while anything is left to settle: an account with
  nothing sellable left (flat, or holding only a residue below the exchange minimum), no
  orders and no exit pending has its bounds and outside-range clock cleared, journaled as
  `bounds_cleared`. Variant A's bound clearing at the end of a Down sequence (Codex,
  PR #114) was a special case of it and is folded in. `range_exit` and
  `range_exit_since` are already clear in that state; a genuine exit keeps its band and
  its cooldown.
- **Amendment 3.** The outside-range clock does nothing while the account is halted: it
  neither advances nor resets (only amendment 2 clears it, once the halted account is
  flat), and `outside_last` keeps the last observation before the halt, so the halted
  span is never counted. An exit already triggered is unaffected.
- **A judgement call.** Amendment 3 also says the clock "resumes from where it stopped
  when the halt clears". No engine path can show it: a restart and a manual resume both
  need a flat account, whose clock amendment 2 and amendment 1's restart field list
  already clear. The test pins the freeze end to end, and pins the resumption by ending
  the halt in the saved state.
- **One existing test changed its scenario.** The replay test that rejected frames do not
  inflate the range-exit count took its one exit from a 20% fall, which halts the
  account; the exit it counted was the flat, halted account timing out of its old band
  six hours later, which is the artefact D15 and D16 describe. It now falls 10%, and its
  one exit is genuine (82.5 units held, not halted).

**Tests.** Each test of a new behaviour fails on this PR's head (`ac012a4`) and passes on
the branch. The guard tests pass on both by construction; each was checked against a
deliberately broken copy, where it fails.

| Test | Rule | On `ac012a4` |
| --- | --- | --- |
| `test_an_episode_healed_under_the_soft_limit_closes_without_a_rebase` | D7 | fails: the rebase commits, to 93.36 |
| `test_partial_recoveries_no_longer_ratchet_the_reference_down` | D7 | fails: the first heal rebases |
| `test_exactly_8_percent_down_still_rebases_and_a_hair_less_closes` | D7 | fails at 7.999999999% (rebases); exactly 8% passes on both, and fails if the close uses "at or above 92%" |
| `test_an_episode_still_8_percent_or_more_down_rebases_as_before` | D7, guard | passes; fails if a close replaces every rebase |
| `test_a_flat_account_with_no_exit_pending_clears_its_bounds_and_regrids_at_once` | Amendment 2 | fails: nothing is cleared |
| `test_a_process_restart_keeps_the_cleared_state` | Amendment 2 | fails: the reopened account still has its old band |
| `test_a_genuine_range_exit_keeps_its_bounds_and_full_cooldown` | Amendment 2, guard | passes; fails if amendment 2 ignores a pending exit |
| `test_the_clock_stands_still_while_halted_and_never_counts_the_halt` | Amendment 3 | fails: the clock runs on through the halt |
| `test_a_range_exit_triggered_before_a_halt_completes_through_it` | Amendment 3, guard | passes; fails if amendment 2 ignores a pending exit, or if a halt drops it |

**Evidence (synthetic data only).** The harness of section (g) ran the backtest command on
its three synthetic datasets, for `ac012a4` (an export of that commit reproduced the
hashes below) and for the branch:

| Run (synthetic) | `ac012a4` SHA-256 | Branch SHA-256 |
| --- | --- | --- |
| Flat, with D (`results.json`) | `eaf29a0a4df9d3f27e3f46629d276c8817dbf47e9101bf16251c2646f96a8a5a` | `d83ee9b0a43f6dde0717e984787c0ce6faee3c2503571f2707383e72e4c2a611` |
| Falling, with D (`results.json`) | `18b76b74511613559fb0da092395a15a6cf4808d5fb460aaa0178bdf3b74d2c1` | `c6c4aab833dff7e7d5990f2d8515e1cfb64e14303354fc76741f5b0dcd196611` |
| No daily bars (`results.json`) | `e4c413c030b551a4a27ad1453e5828b5bc0628b1a9798fce83041a32523e831a` | `09f6abe1e1018bf991c80aabe399e7e0cc9fa3130f90918b82fc1cb9a1fb9627` |

Every difference, field by field:
- **Everywhere:** the `engine_version` label, and the new `soft_drawdown_closes` field (0
  in every run).
- **D:** its rows are identical in both datasets that run it; only the document's
  `engine_version` label changed.
- **Falling:** nothing else. Gated V0 opens no grid there, and ungated V0 never keeps a
  stale band, since it opens a new grid whenever it is flat.
- **Flat, and no daily bars** (V0 reads no daily bars, so these two give the same V0 rows):
  the gated rows only. Counted from the step journal, per gated run:

| Gated V0 | `high_first`: `ac012a4` → branch | `low_first`: `ac012a4` → branch |
| --- | --- | --- |
| Range exits, genuine (inventory or orders held) | 4 → 4 | 4 → 4 |
| Range exits on an empty account (flat, no orders: a stale band) | 3 → 0 | 3 → 0 |
| Bounds cleared by amendment 2 | – → 41 | – → 46 |
| Grids opened | 82 → 71 | 71 → 84 |
| Completed cycles | 75 → 60 | 59 → 74 |
| Return | 12.83% → 6.99% | 7.68% → 13.54% |
| Rebases, no-rebase closes, halts, restarts | 0 → 0 each | 0 → 0 each |

**Attribution.** Copies of the branch that keep one rule each and revert the other two
were run the same way: D7 alone and amendment 3 alone reproduce `ac012a4` exactly, and
amendment 2 alone reproduces the branch exactly. No run on these datasets has a
soft-drawdown episode or a halt, so D7 and amendment 3 cannot act there; every
difference comes from amendment 2 removing the three empty-account exits per gated run.
In `ac012a4` the first of them fired at 2024-01-02 06:56, on an account that had held
nothing since its grid sold out, and its next grid opened 2,703 minutes later. On the
branch that account opened a grid at 21:00 the same day, as soon as its gate allowed
one. From there the two runs trade different grids, so later results move both ways
(−5.85 points on `high_first`, +5.86 on `low_first`): path dependence, not a cost or a
gain of the rule itself.

**Replay probes for the two rules these datasets cannot reach** (constructed minute paths
through the replay test fixtures, synthetic):
- **D7.** A fall in daily steps, each under the 3% daily limit, opens an episode at 8.9%
  below the reference, and the price recovers to 6.05% below before the rebase falls
  due. `ac012a4` rebases to 93.95, then falls to 12.19% below the original reference
  (C1(b)'s measure) and never halts. The branch closes the episode
  (`soft_drawdown_closes` 1), keeps 100, and halts at 12.17%; D7 alone does the same.
- **A halt below the band.** The replay test's former 20% fall halts the account, flat,
  at 09:00. `ac012a4` counts a range exit at 15:00 on the halted account. Amendment 2
  alone clears the old band at 09:00:09, amendment 3 alone freezes the clock, and either
  removes the exit.

**The owner's decisions of 2026-10-05**, each the recommendation in (d), recorded in the
table above:
- **D7.** The wording is confirmed: an episode closes without a rebase only when equity is
  strictly above 92% of `risk_high`.
- **D9, implemented.** `MarketRules.fill_trigger_rate` (unset, it is the slippage) is how
  far a quote must cross a resting limit before it fills. The resting-fill test in
  `execution.py`'s `match` is its only use; exit prices, marks, the settlement residue,
  the inventory cap's exit value, the grid's round-trip cost and buy-and-hold's price all
  keep the slippage. The account identity omits it when unset, and the resume command
  decodes it. `--fill-trigger RATE` reaches every grid replay; the run records
  `fill_trigger` and the code commit in `results.json`, and `-fill<RATE>` in its directory
  name. D places no resting order, so the setting cannot change it. Spec §4's missed-fill
  row now varies this setting, primary 0.05%, equal to the slippage.
  - Tests, each failing on `8251c01`:
    `test_unset_it_is_the_slippage_and_the_identity_omits_it`,
    `test_it_alone_decides_whether_a_resting_order_fills`,
    `test_exits_and_marks_keep_the_slippage`,
    `test_fill_trigger_defaults_to_the_slippage_and_is_carried_when_set`,
    `test_resume_cli_restores_a_separate_fill_trigger`,
    `test_a_fill_trigger_reaches_every_replay_and_is_recorded`,
    `test_out_of_range_fill_trigger_is_rejected` and
    `test_the_fill_trigger_defaults_to_the_slippage_and_only_moves_resting_fills`.
  - Evidence: with the default, the harness gives the same `results.json`, byte for byte,
    as `8251c01` (both run from exports of the commit):

| Run (synthetic) | `8251c01` SHA-256 | With D9, default |
| --- | --- | --- |
| Flat, with D | `fda0c6f6e8d7140b7fa7d921a5e2297878ac05bbd9f2348a4bd832a5ab4cd548` | identical |
| Falling, with D | `cd117ef444ba26684c0a6cc43f77816d66ecee269beb52ded35e075e654ecf38` | identical |
| No daily bars | `09f6abe1e1018bf991c80aabe399e7e0cc9fa3130f90918b82fc1cb9a1fb9627` | identical |

  (The first two differ from this section's earlier table only by the label
  `"code_commit": "unknown"`: since #160's round 3 a run with D records its commit, and
  outside a git checkout that is "unknown".) With `--fill-trigger 0.001` on the flat
  data, every V0 run misses a few resting fills (gated buys 73 → 71 and 87 → 85, ungated
  110 → 107 and 131 → 128), and every row's rules still give the slippage as 0.0005.
- **D8, recorded.** Spec §8 states the exposure: risk checks and forced exits stay off on
  frames wider than the 0.15% spread limit for v1; replay cannot reach such frames; it is
  to be decided before any live or forward paper run.
- **D11, recorded.** The note is in the rotation module's docstring only, not in
  `config/default.toml`: `results.json`'s `config_sha256` is the SHA-256 of that file's
  bytes, so even a comment there would change every result's identity.
- **D12.** Already done in #159: its sim-core audit removed `RiskDecision`'s unused
  capital multiplier. Nothing further.
- **D13, recorded.** One comment line at each SMA helper says why its gap rule differs.
- **D14.** No change; variant B is the registered treatment.

**Codex's review of #163 (at `8251c01`): five spec findings, fixed.**
- **The economic bar (§6), a wording fix the owner should see.** It said that passing
  would "justify live deployment" and let the owner decide whether to "proceed to a live
  pilot", but §8 allows at most a proposal for paper trading against live Revolut X
  prices. It now says so, with a dated note. The owner's bar is unchanged: about 5% over
  six years is not enough, and the target is well above 5% a year.
- **§3's V0 paragraph** now names engine `drawdown-recovery-v2`, paper schema 8 (refusing
  1–7; schema 9, refusing 1–8, since #159 and #160 took 7 and 8) and the decisions of 2026-10-02 (D7, amendments 2 and 3), and lists V0 on
  `drawdown-recovery-v1` among the earlier versions, each a registered trial. No other
  engine or schema pin in the spec disagrees.
- **`N_family` (C7)** is 17–18 and 21–22, with working figures 18 and 22: the coherence
  record's 16–17 and 20–21 plus V0 on `drawdown-recovery-v2`, as amendment 2 says. The
  record's own rule agrees: another inspected version of the fixed V0 is one further
  trial in both budgets. No trial register exists yet to add it to; it is part of C7's
  unbuilt machinery, section (e).
- **The missed-fill row (§4)** names the new fill-trigger setting (D9, above).
- **Amendment 3** now says what the engine does: the clock stands still while halted, and
  nothing carries over the halt, since a halt clears only on a flat account with no
  orders, whose bounds and clock amendment 2 and amendment 1's halt-clearing rule clear.
  It carries a dated note too, as its decision text changed.

**Still open, or for the owner.**
- D17–D21 are open. D18's strict expected failure is unchanged and still fails as
  expected.
