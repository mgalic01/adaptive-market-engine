# Claude: draft spec part 1 — the fold grid, and what makes it usable

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **What this does for the goal.** The go/no-go test on the untouched 2025–26 window
  needs parameters chosen by walk-forward on development data. Under the eligibility
  rule as currently written, that walk-forward would rest on **six months of test data
  from a single period**, which cannot support the "beats cash robustly across markets"
  and "the gate earns its place" criteria. **Two decisions taken together fix it**: with
  hour-level masking *and* the refined repair rule, usable pair-folds rise from 7.2% to
  **79.6%** and the test stream spans **2019-05 to 2024-10**. Both must be taken
  **before** any variant runs, or taking them becomes tuning.
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

**Warm-up is not what fails.** It needs 200 completed daily bars plus 743 hourly bars,
and the inventory records daily bars as intact from 2017-09 even in months the strict
parser rejects for minute defects. Were warm-up required to be minute-clean too, the
shortfall would be total: warm-up, tune and test need about 655 days against a longest
clean run of 639, so **no fold at all** would survive. Treating warm-up as daily-bar-only
is what keeps folds 24 and 25 alive — and that separation is itself a spec decision
(question 4).

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
0.12%. Masking those hours instead of failing their months is clearly right. But it buys
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

## 3a. Measured: what each rule leaves usable

| Rule | Usable pair-folds | Folds with ≥ 2 pairs | Test stream with ≥ 2 pairs |
| --- | ---: | ---: | --- |
| Strict month cleanliness (as written today) | 18 of 250 — **7.2%** | 2 of 25 | 2024-05 .. 2024-10 |
| Hour-level masking alone | 21 of 250 — **8.4%** | 2 of 25 | 2024-05 .. 2024-10 |
| **Hour-level masking + refined repair rule** | **199 of 250 — 79.6%** | **22 of 25** | **2019-05 .. 2024-10** |

Under the third rule every pair has between 13 and 22 usable folds, and all three
stitched streams are contiguous — the appendix checks for gaps rather than printing the
first and last fold, and was tested against a deliberately inserted hole. The stream
that results runs through the 2020 crash, the 2021 peak, the 2022 bear market and the
recovery after it. That is a walk-forward study; the first two rows are not.

**This measures data coverage, never returns.** Choosing a mask because it recovers
present-and-readable data is not tuning; choosing it because of what a strategy earned
on the recovered data would be. That is why these numbers can be measured, and the
decisions taken, before any variant runs.

**79.6% is an upper bound, for three reasons.**

- **Heavily masked months still count as usable.** The rule treats a parseable month as
  usable once its defect hours are masked, however many there are. For most pair-years
  that is a handful. But DOGE had 2,275 defect hours in 2019 (53%) and 1,626 in 2020
  (25%), and LINK 1,281 in 2019 (17%). A month that is half masked may not be tradeable,
  so DOGE's 14 and LINK's 19 usable folds are optimistic. A maximum masked fraction per
  month belongs to decision 1.
- **The repair rule is not yet policy.** Bob's report calls its output "repair-rule
  eligibility, not full replay validity", and says any price tolerance still needs a
  policy decision. The full comparison mask in `EXPERIMENT_SPEC_V1.md` section 5 still
  applies on top.
- **True outages are not in these tables.** Hours missing from *both* archives are
  excluded from the hourly calendar by construction. Bob's
  [outage calendar](2026-09-26-bob-outage-calendar.md) puts them at 58 hours across 14
  basket-wide events, so they are hour-maskable and immaterial to the count — but here
  they are an assumption, not a measurement.

## 4. Decisions required, before any variant runs

None of these is mine to make. All of them must be made **before** results exist,
because making them after seeing which choice helps is exactly the post-hoc tuning the
owner's rules forbid. Decisions 1 and 2 are **only valuable together** — see
section 3a.

1. **Mask granularity.** Mask defect hours rather than failing their month, and set the
   maximum masked fraction a month may carry and still count. Alone it moves the count
   from 18 to 21; its value is as the partner of decision 2, since repaired months still
   carry scattered defect hours.
2. **Repair policy for parser boundary errors — the decision that moves the number.**
   Adopting Bob's [refined parser rule](2026-09-26-bob-refined-parser-rule.md), together
   with decision 1, takes usable pair-folds from 18 to 199. Its open question — any price
   tolerance — has to be settled with it.
3. **Outage handling.** Exclude outage months, or model the outage causally — no exchange
   trading during a verified outage — as the data-reuse proposal allows once a causal
   execution/recovery specification exists. Missing archive bars alone prove no cause.
4. **Warm-up interval.** Confirm that warm-up needs valid **daily** bars only. Under
   strict cleanliness it carries both usable folds; if it must also be minute-clean,
   nothing survives under any of the three rules.
5. **Fold geometry and the unused months.** Keep 12/3/3, and accept that 2024-11 and
   2024-12 are never tested? A shorter tune, or a final short test window, would change
   both usable folds and coverage. Changing the geometry now is legitimate; changing it
   after results is not.
6. **Or accept the answer.** "Insufficient evidence" is an allowed outcome in
   `EXPERIMENT_SPEC_V1.md`. If the owner prefers not to relax any of the above, the
   honest reading is that development data, as currently gated, cannot choose parameters
   robustly — which bears directly on whether the go/no-go test is worth running yet.

**My recommendation, as input rather than decision — corrected.** The first version of
this report said to settle decision 1 first, as "the largest lever". Measured, it is not:
alone it recovers three pair-folds. Settle **decisions 1 and 2 together**, including the
refined rule's price-tolerance question and a maximum masked fraction per month, then
re-run the appendix under the adopted rule for the real count before touching 3 or 5. If
the owner declines decision 2, decision 6 — "insufficient evidence" — is the honest
outcome, and it is better said now than after building on six months.

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
- All three figures are exact under their stated rule, not lower bounds: every fold is
  checked for every pair.
- The "test stream" column reports gaps rather than assuming contiguity; checked against
  a deliberately inserted hole, which it reports.
- **Could not check:** anything finer than these reports record. The maximum masked
  fraction a month can carry is unset, so heavily masked pair-years count in full; true
  outages are taken from the outage calendar rather than measured here; and whether a
  repaired month replays validly is outside what Bob's refined-rule report claims. The
  regime character of any period is not assessed.
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

SHA-256: `3b7cb5aed60b98b4f104e57f34fa0561e746bbbec68ba5614661bd9e453f9d6d`

```text
"""Walk-forward fold grid, and how many pair-folds three eligibility rules leave usable.

Reads only merged, published reports - never an archive, never the reserved window:
  - docs/reviews/2026-09-25-bob-dev-data-inventory.md (first file month; section 2,
    unclean months per pair);
  - docs/reviews/2026-09-26-bob-hourly-defect-calendar.md (unparsed months);
  - docs/reviews/2026-09-26-bob-refined-parser-rule.md (months still unusable under the
    refined repair rule).

Grid rules, from the merged data-reuse proposal section 1: fixed rolling 12-month tune,
3-month test, 3-month step, tune windows never expand, calendar folds, UTC half-open
boundaries, and no test window past DEVELOPMENT_END = "2024-12" (audit.py:36).

A pair-fold is usable when every month of its 15-month tune and test span passes the
rule. Warm-up is not tested: it needs 200 completed daily bars, which the inventory
records as intact from 2017-09 even where minute data is rejected.

  strict       every month clean in the inventory's strict-parser sense;
  hour-mask    every month parseable, with its defect hours masked rather than failing it;
  hour-mask +  as hour-mask, plus the refined repair rule for parser boundary errors.
  repair

These measure data coverage, never returns, so choosing among them is not tuning.

    PYTHONPATH=src python data/fold_eligibility.py
"""

import re
import sys
from pathlib import Path

INVENTORY = Path("docs/reviews/2026-09-25-bob-dev-data-inventory.md")
CALENDAR = Path("docs/reviews/2026-09-26-bob-hourly-defect-calendar.md")
REFINED = Path("docs/reviews/2026-09-26-bob-refined-parser-rule.md")
TUNE, TEST, STEP = 12, 3, 3
FIRST, END_EXCLUSIVE = (2017, 8), (2025, 1)


def add(ym, n):
    t = ym[0] * 12 + ym[1] - 1 + n
    return t // 12, t % 12 + 1


def label(ym):
    return f"{ym[0]}-{ym[1]:02d}"


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
    first = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^\| \*\*(\w+)\*\* \| (\d{4}-\d{2}) \|", text, re.M)
    }
    unclean = {}
    for chunk in re.split(r"^### ", section(text, "## 2. Unclean months per pair"), flags=re.M)[1:]:
        head = re.match(r"(\w+) \((\d+) unclean months after (\d{4}-\d{2})\)", chunk)
        pair, claimed, first_clean = head.group(1), int(head.group(2)), head.group(3)
        months = {m for m in re.findall(r"`(\d{4}-\d{2})`", chunk) if m >= first_clean}
        if len(months) != claimed:
            sys.exit(f"{pair}: parsed {len(months)} unclean months, report states {claimed}")
        unclean[pair] = (first_clean, months)
    return first, unclean


def unparsed():
    text = section(CALENDAR.read_text(encoding="utf-8"), "## Unparsed Months")
    out = {}
    for m in re.finditer(r"^\| \*\*(\d{4}-\d{2})\*\* \|[^|]*\| ([A-Z, ]+?) \|", text, re.M):
        for pair in (p.strip() for p in m.group(2).split(",")):
            out.setdefault(pair, set()).add(m.group(1))
    if not out:
        sys.exit("no unparsed months read from the defect calendar")
    return out


def still_unusable():
    text = section(REFINED.read_text(encoding="utf-8"),
                   "### Unusable pair-months under the refined rule", end="\n---")
    out = {(m.group(2), m.group(1)) for m in re.finditer(r"^\| (\d{4}-\d{2}) \| (\w+)\s*\|", text, re.M)}
    if not out:
        sys.exit("no unusable pair-months read from the refined-rule report")
    return out


def count(grid, pairs, usable):
    total, per_fold = 0, [0] * len(grid)
    for pair in pairs:
        for n, (a, _, c) in enumerate(grid):
            month, ok = a, True
            while month < c:
                ok &= usable(pair, label(month))
                month = add(month, 1)
            if ok:
                total += 1
                per_fold[n] += 1
    return total, per_fold


def main():
    grid = folds()
    print(f"{len(grid)} folds; stitched test stream {label(grid[0][1])} .. "
          f"{label(add(grid[-1][2], -1))} inclusive")
    for n, (a, b, c) in enumerate(grid, 1):
        print(f"  fold {n:>2}  tune [{label(a)}, {label(b)})  test [{label(b)}, {label(c)})")
    first, unclean = inventory()
    bad_parse, repaired_bad = unparsed(), still_unusable()
    rules = {
        "strict": lambda p, m: m >= unclean[p][0] and m not in unclean[p][1],
        "hour-mask": lambda p, m: m >= first[p] and m not in bad_parse.get(p, set()),
        "hour-mask + repair": lambda p, m: m >= first[p] and (p, m) not in repaired_bad,
    }
    possible = len(grid) * len(first)
    print(f"\n{'rule':<20} {'usable pair-folds':>18}  folds with >=2 pairs  test stream with >=2 pairs")
    for name, rule in rules.items():
        total, per_fold = count(grid, sorted(first), rule)
        two = [n for n, k in enumerate(per_fold) if k >= 2]
        gaps = [n + 1 for n in range(two[0], two[-1] + 1) if n not in two] if two else []
        span = (f"{label(grid[two[0]][1])} .. {label(add(grid[two[-1]][2], -1))}"
                + (f", gaps at folds {gaps}" if gaps else ", contiguous")
                if two else "none")
        print(f"{name:<20} {total:>4} of {possible} ({100 * total / possible:>4.1f}%)"
              f"  {len(two):>2} of {len(grid)}               {span}")


if __name__ == "__main__":
    main()
```
