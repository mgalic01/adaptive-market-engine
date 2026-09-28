# Claude: draft spec part 1 — the fold grid, and what makes it usable

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **What this does for the goal.** The go/no-go test on the untouched 2025–26 window
  needs parameters chosen by walk-forward on development data. **The existing inventory
  does not establish that any pair-fold is fully eligible.** Under the eligibility rule
  as written, with the warm-up requirement checked, **no** pair-fold is established.
  Accepting daily files that are intact but were never cross-checked against a parsed
  1h file gives **8 of 250** — all in fold 25, testing one quarter, 2024-08 to 2024-10.
  The 18 that earlier versions of this report called usable pass the test-month check
  only; fold 24's warm-up needs hours from 2023-03, which the strict parser rejects.
- **The owner's chosen direction** (hour-level masking with the refined repair rule,
  2026-09-27) lets 185 of 250 pair-folds through an optimistic metadata screen of the
  tune and test months, 177 with the warm-up check, and 108 if the calendar's listed
  day-level defects stay fatal as `drift-tolerance-v1` makes them today. These are
  ceilings, not counts: hundreds of the months inside those folds are **unknown**, not
  verified. The settings that decide the real count must be fixed **before** any
  variant runs.
- **Scope.** Part 1 of the draft-spec work: the fold boundaries, and eligibility under
  the screens in section 3a. It fixes no policy. It reads only merged, published
  reports — no archive was downloaded or opened, and nothing touches the reserved window.
  Every count below is printed by the appendix script unless it is marked as read from
  a cited report.

## 1. The fold grid (candidate geometry, not settled)

The [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md), section 1, gives
the candidate geometry: rolling **12-month tune, 3-month test, 3-month step**, tune
windows never expand, calendar folds, **UTC half-open** boundaries `[start, end)`. That
document is on `main` but is still a proposal: it states that it freezes no
specification. Fold geometry is an open decision (question 5 below). The development
window starts at the first archive month, 2017-08, and ends at
`DEVELOPMENT_END = "2024-12"` (`src/crypto_grid_bot/backtest/audit.py:36`), so no test
window may reach 2025-01.

This geometry yields **25 folds**. Every boundary falls at `00:00:00Z` on the first of
a month:

| Fold | Tune | Test |
| ---: | --- | --- |
| 1 | `[2017-08, 2018-08)` | `[2018-08, 2018-11)` |
| 2 | `[2017-11, 2018-11)` | `[2018-11, 2019-02)` |
| … | *each step adds three months to all three boundaries* | |
| 23 | `[2023-02, 2024-02)` | `[2024-02, 2024-05)` |
| 24 | `[2023-05, 2024-05)` | `[2024-05, 2024-08)` |
| 25 | `[2023-08, 2024-08)` | `[2024-08, 2024-11)` |

The appendix prints all 25, and its `check_grid()` exits unless: the first tune starts
at the inventory's earliest file month; every tune is 12 months and every test 3;
consecutive folds step 3 months; each test starts where the previous one ended; no test
passes `DEVELOPMENT_END`, which it imports from `audit.py`; and no further fold would
fit. The test windows therefore stitch into one contiguous stream, **2018-08 through
2024-10**, 75 months, each calendar instant scored once.

**Two development months are never tested: 2024-11 and 2024-12.** A 26th fold would
test `[2024-11, 2025-02)`, crossing into the reserved window. That follows from a fixed
3-month test against a hard boundary, and it is a decision, not a bug: see question 5.

## 2. The test-month check: 18 of 250 pair-folds pass

**The denominator is an inventory-wide screen, not a traded universe.** 250 is the ten
inventory symbols — which are also the breadth basket — times 25 folds. The traded
universe for this work is not defined yet; spec v1's development universes hold only
ADA, BTC, XRP and SOL (`EXPERIMENT_SPEC_V1.md:506`). Every "of 250" below is a
screening figure over all ten symbols.

A pair-fold passes the **test-month check** when every month of its 15-month tune and
test span is clean, using the per-pair unclean-month lists in Bob's merged
[development-data inventory](2026-09-25-bob-dev-data-inventory.md), section 2:

| Pair | Folds passing the test-month check |
| --- | --- |
| BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC, TRX | 24 and 25 |
| LINK | none (2023-08 and 2023-09 are unclean) |

**18 of 250 — 7.2% — pass the test-month check. That is not eligibility:** the warm-up
check below removes most of them. Nine of ten pairs have a longest clean run of exactly
21 months, 2023-04 to 2024-12; LINK's is 15 months, 2023-10 to 2024-12. A fold needs 15
consecutive clean months for tune plus test, and on a 3-month step only two fold starts
land inside a 21-month run.

## 2a. Warm-up, checked: none established, 8 at best

The [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md), section 1,
requires, before the first evaluated minute of both tune and test: at least 200
completed valid daily bars, E's 720 completed reference hours, **743 completed hourly
bars** for the V0 feature baseline, BTC proxy and breadth availability, and actual
readiness of every indicator. It forbids padding with pre-listing history.

The appendix checks the **data coverage** part of that, at the tune start and the test
start of every fold:

- the pair's own 743 hourly bars, which contain E's 720 reference hours (spec v1,
  variant E: the pair's last 720 completed 1h bars), and the same 743 for BTCUSDT, the
  market proxy;
- the pair's and BTCUSDT's 200 daily bars;
- 743 hourly bars for every breadth-basket symbol, with months before a symbol's first
  file month exempt as a documented listing absence;
- that no warm-up window reaches the pair's or the proxy's first file month, which is
  normally partial.

An hour counts only if its month is verified; hour-level resolution inside a month is
not available from the reports. A daily bar counts if its month is verified, or — in
every screen except "verified, strict" — if the inventory's section 4 lists the month
as one where the 1d file is intact (0 missing rows, 0 gaps) while 1m and 1h fail to
parse.

Result for the verified screens:

| Screen | Test-month check | + warm-up | + listed day-level defects |
| --- | ---: | ---: | ---: |
| Verified, strict (rule as written) | 18 | **0** | 0 |
| Verified, accepting section-4 daily files | 18 | **8** | 8 |

- **Fold 24 fails for all nine pairs.** Its tune starts at 2023-05-01. The 743 hours
  before it run from 2023-03-31 01:00 to 2023-04-30 23:00: April supplies 720, and the
  other 23 fall in 2023-03, which the strict parser rejects for all ten symbols — the
  pair, the BTC proxy and the whole basket.
- **Fold 25's hourly warm-up passes.** The 743 hours before 2023-08-01 all lie in July
  2023, which has 744 and is verified for all ten symbols. The same holds before its
  test start, in July 2024.
- **Fold 25's daily warm-up decides between 0 and 8.** The 200 days before 2023-08-01
  start at 2023-01-13 and include 2023-03. Its 1d files are intact for all ten symbols
  (inventory section 4), but they were never checked against 1h bars, because the 1h
  files do not parse. Spec v1's comparison mask applies a daily/hourly cross-check, and
  its `practice-2022` evidence shows that check applied to warm-up bars. Read strictly,
  no pair-fold is established. Accepting the intact daily files gives 8.
- **The 8 are fold 25 for BTC, ETH, BNB, XRP, ADA, DOGE, LTC and TRX.** SOL fails because
  its daily warm-up includes 2023-02, an outage month (one missing minute) for which no
  report records the 1d file's state. LINK fails the test-month check. Together they
  test one quarter, **2024-08 to 2024-10**.

**Even the 8 are not established as eligible.** The appendix does not test indicator
readiness, and it does not test breadth completeness over the tune and test span.
Fold 25's tune window contains LINK's 2023-08 and 2023-09. The inventory records each
only as a one-hour cross-check mismatch, which is not positive evidence that every
LINK hour is present, and every pair's breadth feature depends on it.

## 3. Why months fail — and a correction to the first version of this report

The 242 unclean pair-months fall into three groups. The appendix counts each pair's
section-2 list by cause, exits if a month sits under two causes or a stated per-cause
count disagrees, and checks the total against each pair's stated total:

| Cause | Pair-months | Share | What it is |
| --- | ---: | ---: | --- |
| Parser boundary errors | 83 | 34.3% | Rows whose open/close time is not on a 1m/1h boundary; the month will not parse at all |
| Exchange outages / gaps | 88 | 36.4% | Genuinely missing minutes or hours |
| Cross-check only | 71 | 29.3% | The month parses and is complete; some hours fail the hourly/minute cross-check, often one to five |

The groups are disjoint and sum to 242. *(An earlier version said one month fell in two
groups; that was wrong, as Codex Cloud's inline review showed.)*

**The first version of this report called granularity "the dominant cause" and "the
biggest lever". Measured, that is wrong.** Most scattered defect hours really are
trivial. Bob's [hourly defect calendar](2026-09-26-bob-hourly-defect-calendar.md) gives
(report) BTC 11 defect hours in 52,622 from 2018 to 2024 (0.021%), and six of the ten
pairs below 0.12% over the same years. But masking alone buys almost nothing — **21
pair-folds against 18** on the test-month check — because the folds are not being
killed by defect hours.
*[Correction 2026-09-27: both figures came from a table that leaves hours missing from both
archives out of its numerator and its denominator
([measured](2026-09-27-claude-defect-calendar-corrections.md)). Counting them, BTC has 69
defect hours in 52,680 from 2018 to 2024 (0.131%), and **none** of the ten pairs is below
0.12% over those years; the lowest is BTC. The 21-against-18 fold count comes from the
test-month check, not from these rates, and stands. "Most scattered defect hours are
trivial" needs one qualification: twelve of those months also carry a 1–11 hour hole in
every listed pair.]*

**They are being killed by months that will not parse at all, and those are
exchange-wide.** Ten such months — 2018-07, 2019-06, 2020-02, 2020-03, 2020-12, 2021-02,
2021-04, 2021-08, 2021-12 and 2023-03 — each hit 90–100% of listed pairs at once (report),
about one every six months. A 15-month span almost always contains one, and no masking
can rescue a month that cannot be read. The hourly defect calendar excludes these months
by construction, which is why its near-perfect hourly figures sit alongside a 7.2% rate
without contradiction.

Only a **repair rule** reaches them. Bob's
[refined parser rule](2026-09-26-bob-refined-parser-rule.md) leaves just **8 pair-months**
unusable: 2017-12 for BTC, ETH and BNB; 2018-02 for BTC, ETH, BNB and LTC; and DOGE
2020-02. Every other unparseable month becomes readable under that rule, which is not
yet policy.

## 3a. Measured: what each screen lets through

Every listed pair-month is classed as exactly one of **verified** (clean in the
inventory's sense: all three intervals parse with no missing rows or gaps, and the
tolerant hourly cross-check passes), **bad** (known unusable under the screen), or
**unknown** (listed, neither verified nor known bad). From each pair's first file month
to 2024-12:

| Screen | Verified | Bad | Unknown |
| --- | ---: | ---: | ---: |
| Hour-level masking alone | 461 | 106 | 213 |
| Hour-level masking + refined repair | 461 | 8 | 311 |

The appendix recomputes the inventory's section-1 columns — clean months, longest clean
run, months not clean, available months — from section 2 and the start months, and
exits unless all four match for all ten pairs. It also exits unless section 4's 106
intact-daily pair-months are exactly the calendar's unparsed pair-months.

A pair-fold passes a screen when none of its 15 months is bad, unlisted or before the
pair's first clean month, and — in blocks B and C — its warm-up passes as in section 2a,
with the screen's own accepted months. Block C also treats the calendar's 11 listed
day-level defects as fatal for the pair and the BTC proxy, in the span and in the daily
warm-up. **Only the verified rows are positive evidence**; the others let unknown months
through. "All verified" counts pair-folds that also pass the "verified, accepting
section-4 daily files" screen.

| Screen | A. Test months only | B. + warm-up | C. + day-level defects | All verified (B, C) | Unknown months inside (A / B / C) | Folds with ≥ 2 pairs (A / B / C) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Verified, strict | 18 | 0 | 0 | 0 | 0 | 2 / 0 / 0 |
| Verified, accepting section-4 daily files | 18 | 8 | 8 | 8 | 0 | 2 / 1 / 1 |
| Hour-level masking alone | 21 | 11 | 11 | 8 | 7 / 5 / 5 | 2 / 1 / 1 |
| **Hour-level masking + refined repair** | **185** | **177** | **108** | **8** | 1,009 / 915 / 401 | 22 / 22 / 14 |
| … counted from first *file* month | 199 | 183 | 108 | 8 | 1,157 / 976 / 401 | 22 / 22 / 14 |

Test streams with at least two pairs: the verified and masking-alone rows cover
2024-05..2024-10 in A and only 2024-08..2024-10 in B and C (none for "verified,
strict"). The repair rows cover 2019-05..2024-10, contiguous in A and B; in C folds 10
to 17 drop out, leaving a gap in the stream.

**What the rows mean.**

- **The start bound is held constant.** An earlier version compared strict cleanliness,
  which starts at each pair's first *clean* month, with relaxed rules that started at
  its first *file* month; 14 of its 199 came from the start bound, not the repair rule,
  mostly LINK (first clean 19 months after first file) and DOGE (18 months). Every row
  now starts at the first clean month; the 199 row is kept only to show that effect.
- **185 — and 177 with warm-up — are ceilings from metadata, not counts.** Only 8
  consist of verified months with a verified warm-up. Absence from an error list is not
  evidence of a usable month.
- **One day decides most of block C.** On 2021-01-21 the 1d bar's volume differs from
  the 24 summed 1h bars for all ten pairs (report: BTC 2.4%), with prices equal.
  `drift-tolerance-v1` counts only volume differences up to 0.1% as drift, so today this
  day fails the daily/hourly cross-check. It removes every fold whose span or daily
  warm-up contains it: folds 10 to 17 for every pair. DOGE's 2021-10-28 removes DOGE's
  folds 15 to 20. Whether such a day is fatal, masked or repaired under the chosen
  direction is an open setting (decision 1); blocks B and C bracket it.
- The appendix reports gaps in the two-pair stream rather than printing the first and
  last fold; a direct call with a hole inserted at fold 13 reports that gap.

**This measures data coverage, never returns.** Choosing a mask because it recovers
present-and-readable data is not tuning; choosing it because of what a strategy earned
on the recovered data would be. That is why these numbers can be measured, and the
settings fixed, before any variant runs.

**Known reasons the relaxed ceilings will fall further.**

- **Masked fractions inside the passing folds are not measured here.** DOGE's heavily
  masked 2019 and 2020 and LINK's 2019 (report: 53%, 25% and 17% of parsed hours) fall
  before those pairs' first clean months (DOGE 2021-01, LINK 2020-08). They affect only
  the 199 first-file row, not the 185; an earlier version cited them against the 185,
  which was wrong. Among pair-years that overlap the 185 spans, the calendar's highest
  raw rate is ADA 2019, 247 of 8,012 parsed hours (3.08%, report). The calendar does not
  cover the unparsed months at all, so masked fractions of the repaired months are
  unknown. A per-month cap on real defects — 2% is **proposed in #100**, not decided —
  would be applied to the months inside the passing folds, and its effect on these
  counts is not measured by this report.
- **The repair rule is not yet policy.** Bob's report calls its output "repair-rule
  eligibility, not full replay validity", and leaves any price tolerance to a policy
  decision. The full comparison mask in `EXPERIMENT_SPEC_V1.md` section 5 still applies
  on top.
- **Outages in unparsed and repaired months are unknown.** Bob's
  [outage calendar](2026-09-26-bob-outage-calendar.md) found 58 hours in 14 events
  (report), but only in pair-months the strict parser accepted; Codex's correction on
  that report says its unparsed hours are unknown, not evidence of no outages. Outages
  inside the repaired or unknown months are therefore **not shown to be maskable or
  immaterial**.

## 4. Decisions required, before any variant runs

The owner has chosen the direction for 1 and 2 (hour-level masking together with the
refined repair rule, 2026-09-27) and delegated their settings to Claude, Codex and Bob
in writing. Everything below must be fixed **before** results exist, because fixing it
after seeing which choice helps is exactly the post-hoc tuning the owner's rules
forbid. None of it is chosen from strategy results.

1. **Mask settings (direction chosen).** The maximum masked fraction per month and its
   denominator, and a limit on consecutive masked hours. **Proposed in #100** (merged; the values
   remain undecided): 2% of a month's expected hours, counted on real defects only. Also: whether
   a day that fails the daily/hourly cross-check, such as 2021-01-21, is fatal, masked or
   repaired — the difference between blocks B and C.
2. **Repair settings (direction chosen).** The refined rule's price tolerance — DOGE
   2020-02 turns on a one-tick difference — and positive validation of repaired months:
   how a month moves from unknown to verified before it counts. **Proposed in #100**
   (merged; the value remains undecided): no price tolerance, strict `Decimal(0)`.
3. **Behaviour through gaps.** For masked hours and outages alike: what happens to
   resting orders and positions, how risk is sampled, how features are invalidated and
   when they count as recovered, and how accounting treats the gap — with protected
   reserves unchanged. Exclude months where this cannot be defined causally. Missing
   archive bars alone prove no cause.
4. **Warm-up.** The agreed requirement stands (200 daily bars, 743 hourly bars, E's 720
   reference hours, BTC proxy and breadth, every indicator actually ready). Measured in
   section 2a: as written it leaves no pair-fold. What remains to decide is whether an
   intact daily file whose month has no parseable 1h file may serve as warm-up (0
   against 8), and how warm-up in unknown or masked months is treated. Any change to the
   requirement itself needs explicit three-agent agreement before runs.
5. **Fold geometry and the unused months.** Keep 12/3/3, and accept that 2024-11 and
   2024-12 are never tested? A shorter tune, or a final short test window, would change
   both eligible folds and coverage. Changing the geometry now is legitimate; changing
   it after results is not.
6. **Or accept the answer.** "Insufficient evidence" is an allowed outcome in
   `EXPERIMENT_SPEC_V1.md`. If the owner prefers not to relax any of the above, the
   honest reading is that development data, as currently gated, cannot choose
   parameters at all — which bears directly on whether the go/no-go test is worth
   running yet.

**My recommendation, as input rather than decision — corrected three times.** The first
version said to settle masking first; measured, alone it recovers three pair-folds. The
third version called 18 folds usable without checking warm-up; checked, none is
established. Settle **1 to 4 together**, then replace this screen with a positive
count: turn unknown months into verified or bad by replaying them under the adopted
rules, and count only folds whose every month, warm-up and breadth input is verified.
Until then, no pair-fold is established, 8 is the best case on existing evidence, and
177 is a ceiling. If the positive count stays near 8, decision 6 is the honest outcome,
and it is better said before building on one quarter than after. Do not start new
market-data runs on the strength of these ceilings.

## 5. What I checked, and what I could not

Every check below is code in the appendix; each exits with a message when it fails.

- **The grid**, by `check_grid()`, as listed in section 1.
- **The inventory parse.** Each pair's section-2 months must equal its stated total and
  every stated per-cause count, and no month may appear under two causes. Section 1's
  four columns are recomputed from section 2 and must match for all ten pairs — a check
  that depends on *which* months fail, not only how many. The summary table must give
  exactly ten pairs, and section 2 the same pairs and start months.
- **The other reports.** Section 4's rows must match their stated pair counts and the
  106 total, and must be the same pair-months as the calendar's unparsed months. The
  calendar's unparsed rows must match the heading's event count and each row's pair
  count. The day-level defect rows must match the stated 11. The refined rule's
  unusable rows must equal its stated totals (107 − 99 = 8). A missing heading exits,
  naming it, rather than returning an empty set that would silently raise eligibility.
- **Tamper tests at this head**, each on a copy of the reports or the script; each
  exits: a changed section-2 count; a changed longest run; a changed clean-month count;
  a month added under a second cause; a changed per-cause count; a section-4 row and a
  section-4 pair removed; a day-level defect row, an unparsed row and a refined-rule row
  removed; a wrong step in `folds()`; and a moved `END_EXCLUSIVE`, which the section-1
  recount catches before the grid check runs. The two-pair stream reports a gap when
  one is inserted.
- **Checked by hand, independently of the appendix:** the fold-24 and fold-25 warm-up
  windows in section 2a, and the 83 / 88 / 71 cause counts, which Codex Cloud also
  reached from the report.
- **Could not check:** anything finer than these reports record. Hours inside a month
  are not resolved; indicator readiness is not modelled; breadth completeness over the
  tune and test span is not checked; masked fractions are not measured; outages in
  unparsed or repaired months are unknown; whether a repaired month replays validly is
  outside what Bob's refined-rule report claims. The regime character of any period is
  not assessed.
- **Tolerance.** An earlier version said the inventory's definition of clean was
  stricter than the `drift-tolerance-v1` rules the comparison mask uses. That was wrong:
  the inventory's cross-check already applies the same volume-drift tolerance
  ([task file](../tasks/2026-09-25-bob-dev-data-inventory.md), Step 1 `cross_check`
  and the clean-month definition in Step 2), so the mask is not more permissive on that
  point. The inventory is stricter only in its parser, which rejects whole months at a
  boundary row, and the mask adds checks the inventory does not make: the daily/hourly
  cross-check, proxy and breadth completeness, and exchange filters.

## 6. Reproducing

Save the exact appendix source as `data/fold_eligibility.py` and run it from the
repository root. It reads only three merged reports —
`docs/reviews/2026-09-25-bob-dev-data-inventory.md`,
`docs/reviews/2026-09-26-bob-hourly-defect-calendar.md` and
`docs/reviews/2026-09-26-bob-refined-parser-rule.md` — imports `DEVELOPMENT_END` from
`src`, makes no network request and needs no archive:

```
PYTHONPATH=src python data/fold_eligibility.py
```

## 7. Revisions

| Head | Change |
| --- | --- |
| `67a28f0` | First version: 25 folds, 18 of 250 under strict month cleanliness; called granularity the biggest lever. |
| `cf4905b` | Masking measured (21) and the recommendation corrected; the repair rule is what moves the count. |
| `803314b` | Verified / bad / unknown classes; start bound held at the first clean month (185 ceiling); warm-up premise withdrawn. |
| `b689b4c` | Index row only: leads with the 185 ceiling instead of 199. |
| this revision | Answers Codex's audit of `b689b4c`. Warm-up checked at month resolution for the pair, the BTC proxy and the basket: none established as written, 8 at best (fold 25), so the 18 are demoted to a test-month count. Grid and parse checks the text claimed are now in the code. Cause shares corrected (disjoint, 83 / 88 / 71). Tolerance comparison, fold-geometry status, the 250 denominator and the DOGE/LINK examples corrected. Day-level defects measured as block C. #100's proposals cited as proposals. |

## Appendix: `data/fold_eligibility.py` source

SHA-256: `fb61cdd43521065ba7acb16b9d10e42d2d63ccd1142ac55ab47d14233be8feb9`

```text
"""Walk-forward fold grid, what three eligibility screens leave standing, and warm-up.

Reads only merged, published reports - never an archive, never the reserved window:
  - docs/reviews/2026-09-25-bob-dev-data-inventory.md (section 1: first file and first
    clean month, clean-month totals, longest clean run; section 2: unclean months per
    pair and their causes; section 4: months whose 1d file is intact while 1m/1h fail);
  - docs/reviews/2026-09-26-bob-hourly-defect-calendar.md (unparsed months; day-level
    defects, 1h aggregated against 1d);
  - docs/reviews/2026-09-26-bob-refined-parser-rule.md (months still unusable under the
    refined repair rule).

Fold grid: the candidate geometry in the data-reuse proposal section 1 (a proposal, not a
frozen spec): rolling 12-month tune, 3-month test, 3-month step, tune windows never
expand, calendar folds, UTC half-open boundaries. check_grid() exits unless: the first
tune starts at the inventory's earliest file month; every tune is 12 months and every
test 3; consecutive folds step 3 months; each test starts where the previous one ended
(contiguous, no overlap); no test passes DEVELOPMENT_END, imported from
crypto_grid_bot.backtest.audit; and no further fold would fit.

The inventory is validated before use: section 2's per-pair lists must match their
stated totals and per-cause counts, no month may sit under two causes, and section 1's
clean months, longest clean run, months not clean and available months are recomputed
from section 2 and must be equal. Section 4's 1d-intact months must be the same set as
the calendar's unparsed pair-months.

Every listed pair-month is classed as exactly one of:
  verified  clean in the inventory's sense (all three intervals parse with no missing
            rows or gaps, and the tolerant hourly cross-check passes);
  bad       known unusable under the screen being applied;
  unknown   listed, not verified and not known bad - its usability is not established.
Months before a pair's first file month are unlisted and never count.

A pair-fold passes a screen's month check when no month of its 15-month tune and test
span is bad, unlisted, before the pair's first clean month, or (under the two verified
screens) unknown. The warm-up check applies before both the tune start and the test start:
  - the pair's own 743 hourly bars (which contain E's 720 reference hours) and BTCUSDT's
    743 (the market proxy) lie in months the screen accepts;
  - the pair's and BTCUSDT's 200 daily bars lie in months the screen accepts. Every
    screen except "verified, strict" also accepts a section-4 month's daily bars (1d
    intact, 0 missing rows and gaps, but never cross-checked against 1h, which did not
    parse);
  - every breadth-basket symbol's 743 hourly bars lie in accepted months; months before
    a symbol's first file month are a documented listing absence and exempt;
  - no warm-up window of the pair or the proxy reaches its first file month (normally
    partial), so nothing is padded with pre-listing history.
Block C also treats the calendar's listed day-level defects (1h aggregated against 1d)
as fatal for the pair and the proxy, in the span and in the daily warm-up.
Resolution is the month for hours and the day for day-level defects. Nothing here tests
indicator readiness, breadth completeness over the tune and test span, masked
fractions, price tolerance or replay validity.

These measure data coverage, never returns, so choosing among them is not tuning.

    PYTHONPATH=src python data/fold_eligibility.py
"""

import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

INVENTORY = Path("docs/reviews/2026-09-25-bob-dev-data-inventory.md")
CALENDAR = Path("docs/reviews/2026-09-26-bob-hourly-defect-calendar.md")
REFINED = Path("docs/reviews/2026-09-26-bob-refined-parser-rule.md")
PAIRS = 10
PROXY = "BTCUSDT"
TUNE, TEST, STEP = 12, 3, 3
FIRST, END_EXCLUSIVE = (2017, 8), (2025, 1)
WARMUP_HOURS, WARMUP_DAYS = 743, 200


def add(ym, n):
    t = ym[0] * 12 + ym[1] - 1 + n
    return t // 12, t % 12 + 1


def label(ym):
    return f"{ym[0]}-{ym[1]:02d}"


def parse(month):
    year, number = month.split("-")
    return int(year), int(number)


def instant(ym):
    return datetime(ym[0], ym[1], 1, tzinfo=UTC)


def months_between(start, end):
    """Labels of the months overlapping the half-open interval [start, end)."""
    month, last = (start.year, start.month), end - timedelta(microseconds=1)
    while month <= (last.year, last.month):
        yield label(month)
        month = add(month, 1)


def span(a, c):
    return list(months_between(instant(a), instant(c)))


def folds():
    out, start = [], FIRST
    while add(start, TUNE + TEST) <= END_EXCLUSIVE:
        out.append((start, add(start, TUNE), add(start, TUNE + TEST)))
        start = add(start, STEP)
    return out


def check_grid(grid, first_archive_month):
    """Exit unless the grid is exactly the rolling 12/3/3 grid described above."""
    from crypto_grid_bot.backtest.audit import DEVELOPMENT_END

    problems = []
    if END_EXCLUSIVE != add(parse(DEVELOPMENT_END), 1):
        problems.append(f"END_EXCLUSIVE is not the month after DEVELOPMENT_END = {DEVELOPMENT_END}")
    if not grid or label(grid[0][0]) != first_archive_month:
        problems.append(f"the first tune window does not start at the first archive month {first_archive_month}")
    for n, (a, b, c) in enumerate(grid):
        if add(a, TUNE) != b or add(b, TEST) != c:
            problems.append(f"fold {n + 1}: tune or test length is wrong")
        if c > END_EXCLUSIVE:
            problems.append(f"fold {n + 1}: test window passes DEVELOPMENT_END")
        if n and (add(grid[n - 1][0], STEP) != a or grid[n - 1][2] != b):
            problems.append(f"fold {n + 1}: step is not {STEP} months or tests are not contiguous")
    if grid and add(grid[-1][0], STEP + TUNE + TEST) <= END_EXCLUSIVE:
        problems.append("a further fold would fit before DEVELOPMENT_END")
    if problems:
        sys.exit("grid check failed: " + "; ".join(problems))


def section(text, heading, end="\n## "):
    if heading not in text:
        sys.exit(f"heading not found, the report format may have changed: {heading!r}")
    return text.split(heading)[1].split(end)[0]


CAUSES = {"Parser boundary errors": "parser", "Exchange outages": "outage", "Hourly cross-check": "cross-check"}


def inventory():
    text = INVENTORY.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| \*\*(\w+)\*\* \| (\d{4}-\d{2}) \| (\d{4}-\d{2}) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$", text, re.M
    )
    first = {row[0]: row[1] for row in rows}
    first_clean = {row[0]: row[2] for row in rows}
    stated = {row[0]: tuple(int(x) for x in row[3:]) for row in rows}
    if len(rows) != PAIRS or len(first) != PAIRS:
        sys.exit(f"summary table: parsed {len(rows)} rows for {len(first)} pairs, expected {PAIRS}")
    unclean, causes = {}, {}
    for chunk in re.split(r"^### ", section(text, "## 2. Unclean months per pair"), flags=re.M)[1:]:
        head = re.match(r"(\w+) \((\d+) unclean months after (\d{4}-\d{2})\)", chunk)
        if head is None:
            sys.exit(f"unreadable section-2 heading: {chunk[:60]!r}")
        pair, claimed, start = head.group(1), int(head.group(2)), head.group(3)
        if start != first_clean.get(pair):
            sys.exit(f"{pair}: section 2 starts at {start}, summary table says {first_clean.get(pair)}")
        months = set()
        for part in re.split(r"^- \*\*", chunk, flags=re.M)[1:]:
            cause = next((name for key, name in CAUSES.items() if part.startswith(key)), None)
            part = re.sub(r"Note: [^\n]*", "", part)  # XRP: "Note: `2021-12` was clean on XRP!"
            found = {m for m in re.findall(r"`(\d{4}-\d{2})`", part) if m >= start}
            count = re.match(r"[^\n]*?(\d+) months", part)
            if cause is None or found & months or (count and int(count.group(1)) != len(found)):
                sys.exit(f"{pair}: unreadable, overlapping or miscounted cause list: {part[:60]!r}")
            causes[pair, cause] = found
            months |= found
        if len(months) != claimed:
            sys.exit(f"{pair}: parsed {len(months)} unclean months, report states {claimed}")
        unclean[pair] = months
    if set(unclean) != set(first):
        sys.exit(f"section 2 pairs {sorted(unclean)} differ from the summary table {sorted(first)}")
    for pair in first:
        # Recompute section 1's columns from section 2, which the columns do not come from.
        after = span(parse(first_clean[pair]), END_EXCLUSIVE)
        clean = [m not in unclean[pair] for m in after]
        run = longest = 0
        for ok in clean:
            run = run + 1 if ok else 0
            longest = max(longest, run)
        mine = (sum(clean), longest, len(unclean[pair]), len(span(parse(first[pair]), END_EXCLUSIVE)))
        if mine != stated[pair]:
            sys.exit(f"{pair}: recomputed section-1 columns {mine}, report states {stated[pair]}")
    return first, first_clean, unclean, causes


def daily_intact(first):
    """Section 4: pair-months whose 1d file is intact while 1m and 1h fail to parse."""
    text = section(INVENTORY.read_text(encoding="utf-8"), "## 4. Daily data analysis")
    total = re.search(r"There are \*\*(\d+) symbol-months\*\*", text)
    out = set()
    for month, count, names in re.findall(r"^- \*\*(\d{4}-\d{2}):\*\* (\d+) pairs? \(([^)]*)\)$", text, re.M):
        listed = {p for p in first if first[p] <= month}
        if names == "all pairs":
            pairs = listed
        elif names.startswith("all except "):
            pairs = listed - {f"{names[len('all except '):]}USDT"}
        else:
            pairs = {f"{short.strip()}USDT" for short in names.split(",")}
        if len(pairs) != int(count) or not pairs <= listed:
            sys.exit(f"section 4, {month}: pair list does not match its count or the listed pairs")
        out |= {(pair, month) for pair in pairs}
    if total is None or len(out) != int(total.group(1)):
        sys.exit(f"section 4: read {len(out)} pair-months, stated total disagrees")
    return out


def unparsed(pairs):
    text = section(CALENDAR.read_text(encoding="utf-8"), "## Unparsed Months")
    events = re.match(r" \((\d+) Events\)", text)
    rows = re.findall(r"^\| \*\*(\d{4}-\d{2})\*\* \| (\d+)/\d+ \([^)]*\) \| ([A-Z, ]+?) \|", text, re.M)
    if events is None or len(rows) != int(events.group(1)):
        sys.exit(f"unparsed months: read {len(rows)} rows, heading states {events and events.group(1)}")
    out = {}
    for month, affected, names in rows:
        listed = [p.strip() for p in names.split(",")]
        if len(listed) != int(affected) or not set(listed) <= set(pairs):
            sys.exit(f"unparsed month {month}: pair list does not match its count or the universe")
        for pair in listed:
            out.setdefault(pair, set()).add(month)
    return out


def day_defects(pairs):
    text = CALENDAR.read_text(encoding="utf-8")
    total = re.search(r"only \*\*(\d+) pair-days\*\* fail", text)
    table = section(text, "## Day-Level Defects")
    rows = re.findall(r"^\| \*\*(\d{4}-\d{2}-\d{2})\*\* \| (\w+) \| (\d{4}-\d{2}) \|", table, re.M)
    if total is None or len(rows) != int(total.group(1)) or len(set(rows)) != len(rows):
        sys.exit(f"day-level defects: read {len(rows)} rows, stated total disagrees")
    if any(pair not in pairs or not day.startswith(month) for day, pair, month in rows):
        sys.exit("day-level defects: a row names an unknown pair or a day outside its month")
    return {(pair, datetime.fromisoformat(day).replace(tzinfo=UTC)) for day, pair, _ in rows}


def still_unusable(pairs):
    text = REFINED.read_text(encoding="utf-8")
    totals = re.search(r"(\d+) pair-months have at least one file\. Totals: `len\(refined_usable\) = (\d+)`", text)
    table = section(text, "### Unusable pair-months under the refined rule", end="\n---")
    out = {(m.group(2), m.group(1)) for m in re.finditer(r"^\| (\d{4}-\d{2}) \| (\w+)\s*\|", table, re.M)}
    if totals is None or len(out) != int(totals.group(1)) - int(totals.group(2)):
        sys.exit(f"refined rule: read {len(out)} unusable pair-months, totals line disagrees")
    if not {pair for pair, _ in out} <= set(pairs):
        sys.exit("refined rule: an unusable row names a pair outside the universe")
    return out


def classifier(first, first_clean, unclean, known_bad):
    def kind(pair, month):
        if month < first[pair]:
            return "unlisted"
        if month >= first_clean[pair] and month not in unclean[pair]:
            return "verified"
        return "bad" if known_bad(pair, month) else "unknown"

    return kind


def warmup_failures(pair, boundary, kind, accept, first, intact, defects):
    """Why the warm-up before `boundary` fails for `pair`; an empty set means it passes."""
    t = instant(boundary)
    hours, days = t - timedelta(hours=WARMUP_HOURS), t - timedelta(days=WARMUP_DAYS)
    out = set()
    for symbol in dict.fromkeys((pair, PROXY)):
        for start, what in ((hours, "hourly"), (days, "daily")):
            for m in months_between(start, t):
                k = kind(symbol, m)
                if what == "daily" and k != "unlisted" and (symbol, m) in intact:
                    k = "verified"
                if m <= first[symbol] or k not in accept:
                    out.add(f"{symbol} {what} {m} {'first file month' if m == first[symbol] else k}")
        out |= {f"{symbol} daily {d:%Y-%m-%d} day-level defect" for s, d in defects if s == symbol and days <= d < t}
    failing = {}
    for symbol in first:
        for m in months_between(hours, t):
            if m >= first[symbol] and kind(symbol, m) not in accept:
                failing.setdefault(f"{m} {kind(symbol, m)}", []).append(symbol)
    out |= {f"basket hourly {key} for {len(names)} of {len(first)}" for key, names in failing.items()}
    return out


def screen(grid, pairs, kind, accept, warmup=None, defects=frozenset()):
    passing, per_fold, unknown_months, failures = [], [0] * len(grid), 0, {}
    for pair in pairs:
        for n, (a, b, c) in enumerate(grid):
            kinds = [kind(pair, m) for m in span(a, c)]
            if not all(k in accept for k in kinds):
                continue
            why = set()
            if warmup:
                why = warmup(pair, a) | warmup(pair, b)
            why |= {
                f"{s} daily {d:%Y-%m-%d} day-level defect in span"
                for s, d in defects
                if s in (pair, PROXY) and instant(a) <= d < instant(c)
            }
            if why:
                failures[pair, n] = sorted(why)
                continue
            passing.append((pair, n))
            per_fold[n] += 1
            unknown_months += kinds.count("unknown")
    return passing, per_fold, unknown_months, failures


def stream(grid, per_fold):
    two = [n for n, k in enumerate(per_fold) if k >= 2]
    if not two:
        return 0, "none"
    gaps = [n + 1 for n in range(two[0], two[-1] + 1) if n not in two]
    return len(two), (
        f"{label(grid[two[0]][1])} .. {label(add(grid[two[-1]][2], -1))}"
        + (f", gaps at folds {gaps}" if gaps else ", contiguous")
    )


def main():
    first, first_clean, unclean, causes = inventory()
    pairs = sorted(first)
    grid = folds()
    check_grid(grid, min(first.values()))
    print(
        f"{len(grid)} folds; grid check passed; stitched test stream {label(grid[0][1])} .. "
        f"{label(add(grid[-1][2], -1))} inclusive"
    )
    for n, (a, b, c) in enumerate(grid, 1):
        print(f"  fold {n:>2}  tune [{label(a)}, {label(b)})  test [{label(b)}, {label(c)})")
    intact, defects = daily_intact(first), day_defects(pairs)
    bad_parse, repaired_bad = unparsed(pairs), still_unusable(pairs)
    if intact != {(p, m) for p, months in bad_parse.items() for m in months}:
        sys.exit("inventory section 4 and the calendar's unparsed months name different pair-months")
    print(
        "\nsection-1 columns (clean months, longest clean run, months not clean, available months)"
        " recomputed from section 2 and the start months: equal for all ten pairs"
    )
    by_cause = ", ".join(f"{c} {sum(len(causes.get((p, c), ())) for p in pairs)}" for c in CAUSES.values())
    print(f"unclean pair-months by cause: {by_cause}, total {sum(len(unclean[p]) for p in pairs)}, none in two")
    print(f"section-4 1d-intact pair-months: {len(intact)}, the same set as the calendar's unparsed pair-months")
    print(f"day-level defects read: {len(defects)} pair-days")
    mask = classifier(first, first_clean, unclean, lambda p, m: m in bad_parse.get(p, set()))
    repair = classifier(first, first_clean, unclean, lambda p, m: (p, m) in repaired_bad)

    print("\npair-months from each pair's first file month to 2024-12:")
    for name, kind in (("hour-mask", mask), ("hour-mask + repair", repair)):
        tally = {}
        for pair in pairs:
            for m in span(parse(first[pair]), END_EXCLUSIVE):
                tally[kind(pair, m)] = tally.get(kind(pair, m), 0) + 1
        print(f"  {name:<20} " + ", ".join(f"{k} {tally.get(k, 0)}" for k in ("verified", "bad", "unknown")))

    after_clean = lambda kind: lambda p, m: kind(p, m) if m >= first_clean[p] else "before-clean"  # noqa: E731
    relaxed = {"verified", "unknown"}
    rows = [
        ("verified, strict", mask, {"verified"}, True, frozenset()),
        ("verified + 1d files", mask, {"verified"}, True, intact),
        ("hour-mask", mask, relaxed, True, intact),
        ("hour-mask + repair", repair, relaxed, True, intact),
        ("  from first file", repair, relaxed, False, intact),
    ]
    blocks = [
        ("A", "month check only", False, frozenset()),
        ("B", "A + warm-up coverage before tune and test", True, frozenset()),
        ("C", "B + the listed day-level defects, fatal in span and warm-up", True, defects),
    ]
    possible = len(grid) * len(pairs)
    results = {}
    for block, title, with_warmup, fatal_days in blocks:
        print(
            f"\n{block}. {title}\n{'screen':<22}{'pair-folds':>16}  {'all-verified':>12}  {'unknown months':>14}"
            f"  {'folds >=2':>9}  test stream with >=2 pairs"
        )
        measured = []
        for name, kind, accept, bounded, credit in rows:
            warm = None
            if with_warmup:

                def warm(p, x, kind=kind, accept=accept, credit=credit, fatal_days=fatal_days):
                    return warmup_failures(p, x, kind, accept, first, credit, fatal_days)

            passing, per_fold, unknown_months, failures = screen(
                grid, pairs, after_clean(kind) if bounded else kind, accept, warm, fatal_days
            )
            results[name, block] = passing, failures
            measured.append((name, passing, per_fold, unknown_months))
        # "all-verified": every span month verified, and the warm-up passes on verified evidence.
        verified_set = set(results["verified + 1d files", block][0])
        for name, passing, per_fold, unknown_months in measured:
            folds_two, text = stream(grid, per_fold)
            print(
                f"{name:<22}{len(passing):>4} of {possible} ({100 * len(passing) / possible:>4.1f}%)"
                f"  {len(verified_set & set(passing)):>12}  {unknown_months:>14}"
                f"  {folds_two:>3} of {len(grid)}  {text}"
            )

    for name in ("verified, strict", "verified + 1d files"):
        passing, failures = results[name, "C"]
        print(f"\n{name}, block C: why each pair-fold that passes the month check fails")
        for (pair, n), why in sorted(failures.items(), key=lambda item: (item[0][1], item[0][0])):
            print(f"  fold {n + 1:>2} {pair:<9} {'; '.join(why)}")
        print("  passing: " + ", ".join(f"fold {n + 1} {p}" for p, n in sorted(passing, key=lambda x: (x[1], x[0]))))
    for block in "AC":
        passing = results["hour-mask + repair", block][0]
        print(f"\nhour-mask + repair, block {block}: passing folds per pair")
        for pair in pairs:
            print(f"  {pair:<9} " + " ".join(str(n + 1) for p, n in passing if p == pair))


if __name__ == "__main__":
    main()
```
