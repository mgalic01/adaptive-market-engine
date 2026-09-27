# Claude: draft spec part 1 — the fold grid, and what makes it usable

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **What this does for the goal.** The go/no-go test on the untouched 2025–26 window
  needs parameters chosen by walk-forward on development data. Under the eligibility
  rule as currently written, that walk-forward would rest on **six months of test data
  from a single period**, which cannot support the "beats cash robustly across markets"
  and "the gate earns its place" criteria. With hour-level masking *and* the refined
  repair rule — the direction the owner chose on 2026-09-27 — an **optimistic metadata
  screen** lets 185 of 250 pair-folds (74.0%) through, with a test stream spanning
  2019-05 to 2024-10. That is a ceiling, not a count of usable folds: about a third of
  the months inside those folds are **unknown**, not verified, and warm-up and replay
  validity are not checked. Whether the direction delivers depends on settings still to
  be agreed, and all of them must be fixed **before** any variant runs.
- **Scope.** Part 1 of the draft-spec work: the fold boundaries, and measured
  eligibility under three rules. It fixes no policy. It reads only merged, published
  reports — no archive was downloaded or opened, and nothing touches the reserved window.

## 1. The fold grid is settled

The merged [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md), section 1,
fixes the geometry: rolling **12-month tune, 3-month test, 3-month step**, tune windows
never expand, calendar folds, **UTC half-open** boundaries `[start, end)`. The
development window starts at the first archive month, 2017-08, and ends at
`DEVELOPMENT_END = "2024-12"` (`src/crypto_grid_bot/backtest/audit.py:36`), so no test
window may reach 2025-01.

That yields **25 folds**. Every boundary falls at `00:00:00Z` on the first of a month:

| Fold | Tune | Test |
| ---: | --- | --- |
| 1 | `[2017-08, 2018-08)` | `[2018-08, 2018-11)` |
| 2 | `[2017-11, 2018-11)` | `[2018-11, 2019-02)` |
| … | *each step adds three months to all three boundaries* | |
| 23 | `[2023-02, 2024-02)` | `[2024-02, 2024-05)` |
| 24 | `[2023-05, 2024-05)` | `[2024-05, 2024-08)` |
| 25 | `[2023-08, 2024-08)` | `[2024-08, 2024-11)` |

The appendix script prints all 25. The test windows stitch into one contiguous stream,
**2018-08 through 2024-10**, 75 months, with each calendar instant scored exactly once —
checked by assertion, not by eye.

**Two development months are never tested: 2024-11 and 2024-12.** A 26th fold would
test `[2024-11, 2025-02)`, crossing into the reserved window. That is a direct
consequence of a fixed 3-month test against a hard boundary, and it is a decision, not
a bug: see question 5 below.

## 2. Under strict month cleanliness, 7.2% of pair-folds are usable

A pair-fold is usable when every month of its tune and test span is clean. Using the
per-pair unclean-month lists in Bob's merged
[development-data inventory](2026-09-25-bob-dev-data-inventory.md), section 2:

| Pair | Usable folds |
| --- | --- |
| BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC, TRX | **24 and 25 only** |
| LINK | **none** |

**18 of 250 pair-folds — 7.2%.** Both usable folds meet the two-pair minimum-evidence
rule, but together they test only **2024-05 through 2024-10**: six months, one period,
every pair sharing the same six months. That is not a walk-forward study. It is two
adjacent quarters, and multiple pairs over the same dates are not independent
observations — the data-reuse proposal says so explicitly.

The cause is structural, not bad luck. Nine of ten pairs have a longest clean run of
exactly 21 months, 2023-04 to 2024-12; LINK's is 15 months, 2023-10 to 2024-12. A fold
needs 15 contiguous clean months for tune plus test, and on a 3-month step only two fold
starts land inside a 21-month run. No pair has a second run long enough anywhere else.

**Warm-up is not measured here.** The merged
[data-reuse agreement](2026-09-25-claude-data-reuse-proposal.md), section 1, requires
before both tune and test at least 200 completed valid daily bars, E's 720 completed
reference hours, **743 completed hourly bars** for the V0 feature baseline, and actual
readiness of every required indicator, including the BTC proxy and breadth. This
report's first version treated warm-up as daily-only; that premise was wrong and is
withdrawn, together with its claim about what survives under every rule. Section 3a
gives an approximate warm-up row for the relaxed screen; nothing here validates
indicator readiness.

## 3. Why months fail — and a correction to the first version of this report

The unclean months fall into three roughly equal groups:

| Cause | Share | What it is |
| --- | ---: | --- |
| Parser boundary errors | ~35% | Rows whose open/close time is not on a 1m/1h boundary; the month will not parse at all |
| Exchange outages / gaps | ~36% | Genuinely missing minutes or hours |
| Cross-check only | ~29% | The month parses and is complete; some hours fail the hourly/minute cross-check, often one to five |

(Shares, not a total: one month can fall in two groups, so summing them double-counts by
one against the report's 242.)

**The first version of this report called granularity "the dominant cause" and "the
biggest lever". Measured, that is wrong.** Most scattered defect hours really are
trivial: Bob's [hourly defect calendar](2026-09-26-bob-hourly-defect-calendar.md) puts BTC
at 11 defect hours in 52,622 from 2018 to 2024 (0.021%), and six of the ten pairs below
0.12%. Masking those hours instead of failing their months looks proportionate for those
pairs, subject to a masked-fraction cap and the other settings in section 4. But it buys
almost nothing on its own — **21 usable pair-folds against 18** — because the folds are
not being killed by defect hours.

**They are being killed by months that will not parse at all, and those are
exchange-wide.** Ten such months — 2018-07, 2019-06, 2020-02, 2020-03, 2020-12, 2021-02,
2021-04, 2021-08, 2021-12 and 2023-03 — each hit 90–100% of listed pairs at once, about
one every six months. A 15-month span almost always contains one, and no masking can
rescue a month that cannot be read. The hourly defect calendar excludes these months by
construction, which is why its near-perfect hourly figures sit alongside a 7.2% fold
rate without contradiction.

Only a **repair rule** reaches them. Bob's
[refined parser rule](2026-09-26-bob-refined-parser-rule.md) leaves just **8 pair-months**
unusable: 2017-12 for BTC, ETH and BNB; 2018-02 for BTC, ETH, BNB and LTC; and DOGE
2020-02. Every other unparseable month becomes readable.

## 3a. Measured: what each screen lets through

Every listed pair-month is classed as exactly one of **verified** (clean in the
inventory's strict sense: all three intervals parse with no gaps and the hourly
cross-check passes), **bad** (known unusable under the screen), or **unknown** (listed,
neither verified nor known bad). From each pair's first file month to 2024-12:

| Screen | Verified | Bad | Unknown |
| --- | ---: | ---: | ---: |
| Hour-level masking alone | 461 | 106 | 213 |
| Hour-level masking + refined repair | 461 | 8 | 311 |

The 780 total and the 461 verified months match the inventory's own summary columns, and
the 106 match its separate count of parser-failure months; the script reads none of
those three figures.

A pair-fold passes a screen when none of its 15 months is bad, unlisted or before the
pair's first clean month. **Only the first row is positive evidence**; the others let
unknown months through:

| Screen | Pair-folds passing | Of which all verified | Unknown months inside | Folds with ≥ 2 pairs | Test stream with ≥ 2 pairs |
| --- | ---: | ---: | ---: | ---: | --- |
| Verified only (strict, as written today) | 18 of 250 — **7.2%** | 18 | 0 | 2 of 25 | 2024-05 .. 2024-10 |
| Hour-level masking alone | 21 — 8.4% | 18 | 7 | 2 of 25 | 2024-05 .. 2024-10 |
| **Hour-level masking + refined repair** | **185 — 74.0%** | **18** | **1,009** | **22 of 25** | **2019-05 .. 2024-10** |
| … counted from first *file* month instead | 199 — 79.6% | 18 | 1,157 | 22 of 25 | 2019-05 .. 2024-10 |
| … plus an approximate warm-up | 178 — 71.2% | 18 | 930 | 22 of 25 | 2019-05 .. 2024-10 |

**What the rows mean.**

- **The start bound is now held constant.** The first version compared strict
  cleanliness, which starts at each pair's first *clean* month, with relaxed rules that
  started at its first *file* month. That changed two things at once, and 14 of its 199
  pair-folds came from the start bound, not the repair rule — mostly LINK (first clean
  19 months after first file) and DOGE (18 months). A pair's first listed month is also
  normally partial. Every row now starts at the first clean month; the 199 row is kept
  only to show that 14-fold effect.
- **185 is a ceiling from metadata, not a count of usable folds.** Only 18 of the 185
  consist of verified months. The other 167 carry 1,009 unknown pair-months between
  them — about 36% of the 2,775 months in the passing folds — whose coverage, masked
  fraction and replay validity are not established. Absence from an error list is not
  evidence of a usable month.
- **The warm-up row is an approximation in whole months**: 200 daily bars after the
  first file month (seven months), and the month before tune — about 743 hourly bars —
  listed and not known bad. It does not check E's 720 reference hours, BTC proxy or
  breadth readiness, or indicator readiness, and it lets unknown warm-up months through.
- Every screen's two-pair stream is contiguous — the appendix checks for gaps rather
  than printing the first and last fold, and was tested against a deliberately inserted
  hole. Under the repair screen the stream would run through the 2020 crash, the 2021
  peak, the 2022 bear market and the recovery after it, *if* its unknown months prove
  usable.

**This measures data coverage, never returns.** Choosing a mask because it recovers
present-and-readable data is not tuning; choosing it because of what a strategy earned
on the recovered data would be. That is why these numbers can be measured, and the
settings fixed, before any variant runs.

**Known reasons the ceiling will fall further.**

- **Heavily masked months still pass.** DOGE had 2,275 defect hours in 2019 (53%) and
  1,626 in 2020 (25%), and LINK 1,281 in 2019 (17%). A month that is half masked may
  not be tradeable. A maximum masked fraction, with a defined denominator, belongs to
  the settings in section 4.
- **The repair rule is not yet policy.** Bob's report calls its output "repair-rule
  eligibility, not full replay validity", and leaves any price tolerance to a policy
  decision. The full comparison mask in `EXPERIMENT_SPEC_V1.md` section 5 still applies
  on top.
- **Outages in unparsed and repaired months are unknown.** Bob's
  [outage calendar](2026-09-26-bob-outage-calendar.md) found 58 hours in 14 events, but
  only in pair-months the strict parser accepted; Codex's correction on that report says
  its unparsed hours are unknown, not evidence of no outages. Outages inside the 311
  repaired or unknown months are therefore **not shown to be maskable or immaterial**.
  The first version of this report said they were; that is withdrawn.

## 4. Decisions required, before any variant runs

The owner has chosen the direction for 1 and 2 (hour-level masking together with
the refined repair rule, 2026-09-27) and delegated their settings to Claude, Codex and
Bob in writing. Everything below must be fixed **before** results exist, because fixing
it after seeing which choice helps is exactly the post-hoc tuning the owner's rules
forbid. None of it is chosen from strategy results. Masking alone moves the screen from
18 to 21 — see section 3a.

1. **Mask settings (direction chosen).** The maximum masked fraction per month and its
   denominator (listed hours, or hours in the evaluated span), and a limit on
   consecutive masked hours.
2. **Repair settings (direction chosen).** The refined rule's price tolerance — DOGE
   2020-02 turns on a one-tick difference — and positive validation of repaired months:
   how a month moves from unknown to verified before it counts.
3. **Behaviour through gaps.** For masked hours and outages alike: what happens to resting
   orders and positions, how risk is sampled, how features are invalidated and when they
   count as recovered, and how accounting treats the gap — with protected reserves
   unchanged. Exclude months where this cannot be defined causally. Missing archive bars
   alone prove no cause.
4. **Warm-up.** The agreed requirement stands (200 daily bars, 743 hourly bars, E's 720
   reference hours, BTC proxy and breadth, and every indicator actually ready). What
   remains is how a fold whose warm-up falls in unknown or masked months is treated; any
   change to the requirement itself needs explicit three-agent agreement before runs.
5. **Fold geometry and the unused months.** Keep 12/3/3, and accept that 2024-11 and
   2024-12 are never tested? A shorter tune, or a final short test window, would change
   both usable folds and coverage. Changing the geometry now is legitimate; changing it
   after results is not.
6. **Or accept the answer.** "Insufficient evidence" is an allowed outcome in
   `EXPERIMENT_SPEC_V1.md`. If the owner prefers not to relax any of the above, the
   honest reading is that development data, as currently gated, cannot choose parameters
   robustly — which bears directly on whether the go/no-go test is worth running yet.

**My recommendation, as input rather than decision — corrected twice.** The first
version said to settle masking first, as "the largest lever"; measured, alone it recovers
three pair-folds. Settle **1 to 4 together**, then replace this screen with a positive
count: turn unknown months into verified or bad by replaying them under the adopted
rules, and count only folds whose every month and warm-up is verified. Until then 185 is
a ceiling and 18 is the only established figure. If the positive count stays near 18,
decision 6 — "insufficient evidence" — is the honest outcome, and it is better said
before building on six months than after.

## 5. What I checked, and what I could not

- The grid's properties are asserted in code, not inspected: every tune 12 months, every
  test 3 months, a 3-month step, contiguous non-overlapping test windows, none past
  2025-01.
- **The parse is verified three independent ways, not one.** A first attempt read only
  some list formats and disagreed with every pair's stated total, so it was discarded.
  The published version collects every backticked `YYYY-MM` in each pair's section and
  **exits with an error unless the count matches the report's stated number** for all ten
  pairs — tested against a doctored inventory, where it fires. A count check alone can
  pass with the right number of wrong months, so the parsed sets were also checked
  against the inventory's *separate* section-1 table, which the script never reads:
  recomputed clean-month totals and longest clean runs match it exactly for all ten
  pairs. The longest run depends on *which* months fail and where, so a swapped month
  would almost certainly break it.
- **The other two reports are read with guards too, and both guards were tested.** If a
  section heading is missing from any of the three reports, the script exits naming the
  heading. If a heading is present but its rows no longer match — a changed table format
  — it exits rather than returning an empty set, since an empty set of bad months would
  silently inflate every count. A first version claimed this but did not do it: a
  renamed heading raised `IndexError` before the guard was reached. That still failed
  loudly rather than inflating anything, but the mechanism described was wrong, so the
  code was fixed rather than the sentence.
- **Totals are validated, not trusted.** The script exits if the inventory's summary
  table does not give exactly ten pairs, if section 2 names a different pair set or a
  different start month than the summary table, if the unparsed-month rows do not match
  the calendar heading's event count or a row's pair list does not match its stated
  count, or if the refined rule's unusable rows do not equal its stated totals
  (107 − 99 = 8). Each guard was tested by editing a copy of the report — dropping a
  row, dropping a pair from a row, shifting a start month — and each fires. A malformed
  or omitted row can therefore no longer silently raise eligibility.
- Every figure is exact under its stated screen: every fold is checked for every pair.
- The "test stream" column reports gaps rather than assuming contiguity; checked against
  a deliberately inserted hole, which it reports.
- **Could not check:** anything finer than these reports record. The maximum masked
  fraction a month can carry is unset, so heavily masked pair-years count in full;
  outages in unparsed or repaired months are unknown; indicator readiness is not
  modelled; and whether a repaired month replays validly is outside what Bob's
  refined-rule report claims. The regime character of any period is not assessed.
- This inherits every limit of the reports it reads, including the inventory's
  strict-parser definition of "clean", which is stricter than the `drift-tolerance-v1`
  rules the comparison mask actually uses.

## 6. Reproducing

Save the exact appendix source as `data/fold_eligibility.py` and run it from the
repository root. It reads only three merged reports —
`docs/reviews/2026-09-25-bob-dev-data-inventory.md`,
`docs/reviews/2026-09-26-bob-hourly-defect-calendar.md` and
`docs/reviews/2026-09-26-bob-refined-parser-rule.md` — makes no network request, and
needs no archive:

```
PYTHONPATH=src python data/fold_eligibility.py
```

## Appendix: `data/fold_eligibility.py` source

SHA-256: `88c474c3f74bf38ef25ee35e1b3b9c59d99c796348a4a06122338c20542b24b0`

```text
"""Walk-forward fold grid, and what three eligibility screens leave standing.

Reads only merged, published reports - never an archive, never the reserved window:
  - docs/reviews/2026-09-25-bob-dev-data-inventory.md (first file and first clean month;
    section 2, unclean months per pair);
  - docs/reviews/2026-09-26-bob-hourly-defect-calendar.md (unparsed months);
  - docs/reviews/2026-09-26-bob-refined-parser-rule.md (months still unusable under the
    refined repair rule).

Grid rules, from the merged data-reuse proposal section 1: fixed rolling 12-month tune,
3-month test, 3-month step, tune windows never expand, calendar folds, UTC half-open
boundaries, and no test window past DEVELOPMENT_END = "2024-12" (audit.py:36).

Every listed pair-month is classed as exactly one of:
  verified  clean in the inventory's strict sense (all three intervals parse with no
            gaps, and the hourly cross-check passes) - positive evidence of coverage;
  bad       known unusable under the screen being applied;
  unknown   listed, not verified and not known bad - its usability is not established.
Months before a pair's first file month are not listed and never count.

A pair-fold passes a screen when no month of its 15-month tune and test span is bad, or
unlisted, or (under "verified") unknown. Only the verified screen is positive evidence;
the other two are optimistic screens that let unknown months through. None of them
checks indicator readiness, masked fractions, price tolerance or replay validity.

These measure data coverage, never returns, so choosing among them is not tuning.

    PYTHONPATH=src python data/fold_eligibility.py
"""

import re
import sys
from pathlib import Path

INVENTORY = Path("docs/reviews/2026-09-25-bob-dev-data-inventory.md")
CALENDAR = Path("docs/reviews/2026-09-26-bob-hourly-defect-calendar.md")
REFINED = Path("docs/reviews/2026-09-26-bob-refined-parser-rule.md")
PAIRS = 10
TUNE, TEST, STEP = 12, 3, 3
FIRST, END_EXCLUSIVE = (2017, 8), (2025, 1)
DAILY_WARMUP_MONTHS = 7  # 200 completed daily bars need more than 6 full months


def add(ym, n):
    t = ym[0] * 12 + ym[1] - 1 + n
    return t // 12, t % 12 + 1


def label(ym):
    return f"{ym[0]}-{ym[1]:02d}"


def parse(month):
    year, number = month.split("-")
    return int(year), int(number)


def folds():
    out, start = [], FIRST
    while add(start, TUNE + TEST) <= END_EXCLUSIVE:
        out.append((start, add(start, TUNE), add(start, TUNE + TEST)))
        start = add(start, STEP)
    return out


def section(text, heading, end="\n## "):
    if heading not in text:
        sys.exit(f"heading not found, the report format may have changed: {heading!r}")
    return text.split(heading)[1].split(end)[0]


def inventory():
    text = INVENTORY.read_text(encoding="utf-8")
    rows = re.findall(r"^\| \*\*(\w+)\*\* \| (\d{4}-\d{2}) \| (\d{4}-\d{2}) \|", text, re.M)
    first = {pair: file_month for pair, file_month, _ in rows}
    first_clean = {pair: clean_month for pair, _, clean_month in rows}
    if len(rows) != PAIRS or len(first) != PAIRS:
        sys.exit(f"summary table: parsed {len(rows)} rows for {len(first)} pairs, expected {PAIRS}")
    unclean = {}
    for chunk in re.split(r"^### ", section(text, "## 2. Unclean months per pair"), flags=re.M)[1:]:
        head = re.match(r"(\w+) \((\d+) unclean months after (\d{4}-\d{2})\)", chunk)
        if head is None:
            sys.exit(f"unreadable section-2 heading: {chunk[:60]!r}")
        pair, claimed, start = head.group(1), int(head.group(2)), head.group(3)
        if start != first_clean.get(pair):
            sys.exit(f"{pair}: section 2 starts at {start}, summary table says {first_clean.get(pair)}")
        months = {m for m in re.findall(r"`(\d{4}-\d{2})`", chunk) if m >= start}
        if len(months) != claimed:
            sys.exit(f"{pair}: parsed {len(months)} unclean months, report states {claimed}")
        unclean[pair] = months
    if set(unclean) != set(first):
        sys.exit(f"section 2 pairs {sorted(unclean)} differ from the summary table {sorted(first)}")
    return first, first_clean, unclean


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


def span(a, c):
    month = a
    while month < c:
        yield label(month)
        month = add(month, 1)


def screen(grid, pairs, kind, accept, warmup=None):
    passing, per_fold, unknown_months = [], [0] * len(grid), 0
    for pair in pairs:
        for n, (a, _, c) in enumerate(grid):
            kinds = [kind(pair, m) for m in span(a, c)]
            if not all(k in accept for k in kinds) or (warmup and not warmup(pair, a)):
                continue
            passing.append((pair, n))
            per_fold[n] += 1
            unknown_months += kinds.count("unknown")
    return passing, per_fold, unknown_months


def stream(grid, per_fold):
    two = [n for n, k in enumerate(per_fold) if k >= 2]
    if not two:
        return 0, "none"
    gaps = [n + 1 for n in range(two[0], two[-1] + 1) if n not in two]
    return len(two), (f"{label(grid[two[0]][1])} .. {label(add(grid[two[-1]][2], -1))}"
                      + (f", gaps at folds {gaps}" if gaps else ", contiguous"))


def main():
    grid = folds()
    print(f"{len(grid)} folds; stitched test stream {label(grid[0][1])} .. "
          f"{label(add(grid[-1][2], -1))} inclusive")
    for n, (a, b, c) in enumerate(grid, 1):
        print(f"  fold {n:>2}  tune [{label(a)}, {label(b)})  test [{label(b)}, {label(c)})")
    first, first_clean, unclean = inventory()
    pairs = sorted(first)
    bad_parse, repaired_bad = unparsed(pairs), still_unusable(pairs)
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

    def warmup(kind):
        # Approximation in whole months: 200 daily bars after the first file month, and
        # the month before tune (743 hourly bars) not known bad and listed.
        def ok(pair, tune_start):
            daily = add(parse(first[pair]), DAILY_WARMUP_MONTHS) <= tune_start
            return daily and kind(pair, label(add(tune_start, -1))) in ("verified", "unknown")
        return ok

    rows = [
        ("verified only", after_clean(repair), {"verified"}, None),
        ("hour-mask", after_clean(mask), {"verified", "unknown"}, None),
        ("hour-mask + repair", after_clean(repair), {"verified", "unknown"}, None),
        ("  from first file", repair, {"verified", "unknown"}, None),
        ("  + warm-up approx.", after_clean(repair), {"verified", "unknown"}, warmup(repair)),
    ]
    possible = len(grid) * len(pairs)
    verified_set = set(screen(grid, pairs, after_clean(repair), {"verified"})[0])
    print(f"\n{'screen':<22}{'pair-folds':>16}  {'all-verified':>12}  {'unknown months':>14}"
          f"  {'folds >=2':>9}  test stream with >=2 pairs")
    for name, kind, accept, warm in rows:
        passing, per_fold, unknown_months = screen(grid, pairs, kind, accept, warm)
        folds_two, text = stream(grid, per_fold)
        print(f"{name:<22}{len(passing):>4} of {possible} ({100 * len(passing) / possible:>4.1f}%)"
              f"  {len(verified_set & set(passing)):>12}  {unknown_months:>14}"
              f"  {folds_two:>3} of {len(grid)}  {text}")


if __name__ == "__main__":
    main()
```
