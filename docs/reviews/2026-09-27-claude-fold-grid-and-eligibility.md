# Claude: draft spec part 1 — the fold grid, and how little of it is usable

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **What this does for the goal.** The go/no-go test on the untouched 2025–26 window
  needs parameters chosen by walk-forward on development data. This shows that, as
  currently specified, walk-forward would rest on **six months of test data from a single
  period**, which cannot support the "beats cash robustly across markets" and "the gate
  earns its place" criteria. The decisions that fix it must be taken **before** any
  variant runs, or taking them becomes tuning.
- **Scope.** Part 1 of the draft-spec work: the fold boundaries, and a measured
  eligibility finding. It fixes no policy. It reads only a merged, published report —
  no archive was downloaded or opened, and nothing touches the reserved window.

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

## 3. Why months fail, and where the lever is

The unclean months fall into three roughly equal groups:

| Cause | Share | What it is |
| --- | ---: | --- |
| Parser boundary errors | ~35% | Rows whose open/close time is not on a 1m/1h boundary; many shared across pairs |
| Exchange outages / gaps | ~36% | Genuinely missing minutes or hours |
| Cross-check only | ~29% | The month parses and is complete; some hours fail the hourly/minute cross-check, often one to five |

(Shares, not a total: one month can fall in two groups, so summing them double-counts by
one against the report's 242.)

**The dominant cause is granularity, not data quality.** Eligibility here is decided a
whole month at a time, and a whole fold at a time. A single mismatched hour removes its
month, and that month removes every fold whose 15-month span contains it. The
cross-check-only third are months where the data is *present and complete*, and fail
because of a handful of hours — the same cross-check that produced the open-only class
studied in PR #81 and PR #83, whose sampled hours are consistent with an
opening-price convention rather than corruption. Sampled, not all: that work covered
1,689 of 5,277 hours.

## 4. Decisions required, before any variant runs

None of these is mine to make. All of them must be made **before** results exist,
because making them after seeing which choice helps is exactly the post-hoc tuning the
owner's rules forbid. Listed in order of how much they change the answer.

1. **Mask granularity — the biggest lever.** Keep month-level eligibility, or mask at the
   hour or pair-window level so that one bad hour excludes that hour rather than a
   15-month fold? The comparison mask in `EXPERIMENT_SPEC_V1.md` section 5 already works
   per pair-window. Hour-level masking would very likely recover most of the
   cross-check-only third; how much is unmeasured, and measuring it needs no archive
   access beyond what the inventory already records.
2. **Repair policy for parser boundary errors.** Bob's
   [refined parser rule](2026-09-26-bob-refined-parser-rule.md) makes 99 pair-months
   usable against 82 for the narrow rule, and states that any price tolerance still needs
   a policy decision. Adopting it would change eligibility; how much is unmeasured here.
3. **Outage handling.** Exclude outage months, or model the outage causally — no exchange
   trading during a verified outage — as the data-reuse proposal allows once a causal
   execution/recovery specification exists. Missing archive bars alone prove no cause.
4. **Warm-up interval.** Confirm that warm-up needs valid **daily** bars only. It is
   carrying both usable folds; if it must also be minute-clean, nothing survives.
5. **Fold geometry and the unused months.** Keep 12/3/3, and accept that 2024-11 and
   2024-12 are never tested? A shorter tune, or a final short test window, would change
   both usable folds and coverage. Changing the geometry now is legitimate; changing it
   after results is not.
6. **Or accept the answer.** "Insufficient evidence" is an allowed outcome in
   `EXPERIMENT_SPEC_V1.md`. If the owner prefers not to relax any of the above, the
   honest reading is that development data, as currently gated, cannot choose parameters
   robustly — which bears directly on whether the go/no-go test is worth running yet.

My recommendation, as input rather than decision: settle **1** first, since it is the
largest lever and the only one where the excluded data is known to be present and
complete. Then measure its effect with the appendix method before touching 2, 3 or 5.

## 5. What I checked, and what I could not

- The grid's properties are asserted in code, not inspected: every tune 12 months, every
  test 3 months, a 3-month step, contiguous non-overlapping test windows, none past
  2025-01.
- **The parse is verified against the report's own counts.** A first attempt read only
  some list formats and disagreed with every pair's stated total. The appendix version
  collects every backticked `YYYY-MM` in each pair's section, filters to months at or
  after that pair's first clean month, and **exits with an error unless the count
  matches the report's stated number** for all ten pairs. It does.
- The 18-of-250 figure is exact under month-level cleanliness, not a lower bound: the
  check covers every fold for every pair, not only the longest runs.
- **Could not check:** anything below month resolution. The effect of hour-level masking,
  the repair rule, or outage modelling on eligibility is unmeasured, because the
  inventory reports months, and measuring finer needs either the archives or Bob's
  hourly defect calendar. The regime character of 2024-05..2024-10 is not assessed; I
  claim only that it is a single six-month period.
- This inherits every limit of the inventory it reads, including its strict-parser
  definition of "clean", which is stricter than the `drift-tolerance-v1` rules the
  comparison mask actually uses. That gap is further reason to expect the true usable
  fraction under the real mask to be higher than 7.2%, and further reason to measure
  rather than assume.

## 6. Reproducing

Save the exact appendix source as `data/fold_eligibility.py` and run it from the
repository root. It reads only `docs/reviews/2026-09-25-bob-dev-data-inventory.md`, makes
no network request, and needs no archive:

```
PYTHONPATH=src python data/fold_eligibility.py
```

## Appendix: `data/fold_eligibility.py` source

SHA-256: `382e1b20250f55fec02b8ebae73bba302588c530e1f1cfc2e5db2685481d51d5`

```text
"""Walk-forward fold grid, and which pair-folds strict month cleanliness leaves usable.

Reads only a published, merged report - never an archive, never the reserved window:
docs/reviews/2026-09-25-bob-dev-data-inventory.md, section 2 (unclean months per pair).

Grid rules, from the merged data-reuse proposal section 1: fixed rolling 12-month tune,
3-month test, 3-month step, tune windows never expand, calendar folds, UTC half-open
boundaries, and no test window past DEVELOPMENT_END = "2024-12" (audit.py:36).

Eligibility is month-level: a pair-fold is usable when every month of its tune and test
span is clean (at or after the pair's first clean month and not listed unclean). Warm-up
is not tested here: it needs 200 completed daily bars, and the inventory records daily
bars as intact from 2017-09 even where minute data is rejected.

    PYTHONPATH=src python data/fold_eligibility.py
"""

import re
import sys
from pathlib import Path

INVENTORY = Path("docs/reviews/2026-09-25-bob-dev-data-inventory.md")
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


def unclean_months():
    text = INVENTORY.read_text(encoding="utf-8")
    section = text.split("## 2. Unclean months per pair")[1].split("\n## ")[0]
    pairs = {}
    for chunk in re.split(r"^### ", section, flags=re.M)[1:]:
        head = re.match(r"(\w+) \((\d+) unclean months after (\d{4}-\d{2})\)", chunk)
        pair, claimed, first_clean = head.group(1), int(head.group(2)), head.group(3)
        months = {m for m in re.findall(r"`(\d{4}-\d{2})`", chunk) if m >= first_clean}
        if len(months) != claimed:
            sys.exit(f"{pair}: parsed {len(months)} unclean months, report states {claimed}")
        pairs[pair] = (first_clean, months)
    return pairs


def main():
    grid = folds()
    print(f"{len(grid)} folds; stitched test stream {label(grid[0][1])} .. "
          f"{label(add(grid[-1][2], -1))} inclusive")
    for n, (a, b, c) in enumerate(grid, 1):
        print(f"  fold {n:>2}  tune [{label(a)}, {label(b)})  test [{label(b)}, {label(c)})")
    pairs = unclean_months()
    usable, by_fold = 0, {n: [] for n in range(1, len(grid) + 1)}
    print("\neligible folds per pair (every tune and test month clean):")
    for pair, (first_clean, bad) in pairs.items():
        ok = []
        for n, (a, _, c) in enumerate(grid, 1):
            month, clean = a, True
            while month < c:
                clean &= label(month) >= first_clean and label(month) not in bad
                month = add(month, 1)
            if clean:
                ok.append(n)
                by_fold[n].append(pair)
        usable += len(ok)
        print(f"  {pair:<9} {ok if ok else 'none'}")
    possible = len(grid) * len(pairs)
    print(f"\n{usable} of {possible} pair-folds usable ({100 * usable / possible:.1f}%)")
    two = [n for n, v in by_fold.items() if len(v) >= 2]
    print(f"folds meeting the 2-pair minimum evidence rule: {two if two else 'none'}")


if __name__ == "__main__":
    main()
```
