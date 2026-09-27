# Claude: draft spec part 2 — the retrospective trial count, and its uncertainty

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **Revised twice on 2026-09-27**, see [section 11](#11-revisions). The first version
  undercounted, overclaimed and paired results with configurations that never ran. The
  second still missed four observed runs and R3's ungated results. The withdrawn claims
  are listed in [section 8](#8-withdrawn-claims) rather than quietly replaced. Every
  finding was checked at source before each revision.
- **What this does for the goal.** The deflated Sharpe ratio adopted in the merged
  [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md) as the named
  multiple-testing diagnostic needs an honest count of strategies already tried. If that
  count is understated, any Sharpe ratio from development data looks better than it is,
  and the €100 go/no-go decision rests on an inflated number. The proposal is explicit:
  *"Incomplete historical search information cannot be reset to zero."*
- **Scope.** It inventories the runs that actually happened, states the count under
  explicit counting rules, and proposes entries. **It does not create
  `docs/trials/register.jsonl`**: the proposal reserves that for a separately reviewed
  trusted process. Evidence is git history, published reports and PR comments; no
  archive was opened and nothing touches the reserved window.

## 1. The runs that actually happened

Each row is one inspected result set, bound to the code, data and record it came from.
A row exists only where a published record says the run happened. Every run set
replays both strategies, the gated grid `price-only-v1` and the ungated grid baseline,
on both intrabar paths.

| Run | Code | Data | Fees | Results | Result record |
| --- | --- | --- | --- | --- | --- |
| R1 | after `c2d787b` (the harness), before `98baf70`; exact SHA **not recorded** | `verify-2024h1` | 0.1% | as R2; its count, 8, is inferred | [verify-2024h1.md](../backtests/verify-2024h1.md) line 29: *"reproduced … exactly"* by R2 |
| R2 | `98baf70` | `verify-2024h1` (ADA, BTC; Jan–Jun 2024) | 0.1% | 8, all valid | same file, published `ee37d2a` at 10:43:43; gated V0 barely trades, ungated trades more and loses more |
| R2a | `dfbc3bf` | `verify-2024h1` | 0.1% | 8; table identical to R2 | [PR #9 comment, 11:32:13](https://github.com/mgalic01/adaptive-market-engine/pull/9#issuecomment-5813233511) |
| R2b | `e7e8bc5` | `verify-2024h1` | 0.1% | 8; table identical to R2 | [PR #9 comment, 11:40:30](https://github.com/mgalic01/adaptive-market-engine/pull/9#issuecomment-5813372307); verify-2024h1.md line 24; [PR #9 fixes](2026-09-24-claude-pr9-review-fixes.md) line 34 |
| R2c | `8fe0cf8` | `verify-2024h1` | 0.1% | 8, marked valid; identical to R2 | [PR #12 description](https://github.com/mgalic01/adaptive-market-engine/pull/12); `8fe0cf8`'s commit message |
| R2d | `cc1f57a` | `verify-2024h1` | 0.1% | 8, marked valid; identical to R2 | [PR #12 comment, 12:25:42](https://github.com/mgalic01/adaptive-market-engine/pull/12#issuecomment-5814059002) and [12:28:02](https://github.com/mgalic01/adaptive-market-engine/pull/12#issuecomment-5814097727) |
| R3 | `e57439a`; practice runs at 0.075% and 0%/0.09% also `927e1a7` | `verify-2024h1` and `practice-2022` (BTC, SOL, XRP) | 0.1%, 0.075%, 0%/0.09% | 60: `verify-2024h1` 24, all valid, the 0.1% runs identical to R2; `practice-2022` 36, of which the **12 SOL results are invalid** | [fee-levels-2026-09.md](../backtests/fee-levels-2026-09.md), both tables, gated **and ungated** |
| R3r | `021899b` | from R3's 0%/0.09% runs; which four is not recorded | 0%/0.09% | 4 re-run; identical returns | same file, finding 5; `021899b`'s commit message |
| R4 | `876f7ce9d3a32b4a31bc558a0eb038a462c1472e` | `verify-2024h1` and `practice-2022` | 0%/0.09% and 0.1% | 40, of which the **8 SOL results are invalid** | [Bob's V0 scorecard](2026-09-25-bob-v0-dev-scorecard.md); its 16 valid 0%/0.09% returns equal R3's to two decimals |

**Totals, recomputed by the script in [section 10](#10-reproducing), not by hand:** 8
run sets plus one partial re-run; 152 replay results, of which 8 are R1's inferred
count; **20 invalid results, all kept** in the ledger. An invalid result is still an
inspected result.

R1 is known only because R2's report mentions it. It is the clearest sign that the
recorded history is incomplete: runs that were looked at but not published leave no
other trace.

## 2. Which configurations those runs used, and what changed between them

Times are UTC on 2026-09-24, converted from Unix commit time. Every commit that
`git log 98baf70..876f7ce -- src/ config/` lists up to `021899b` is in the table; later
ones are summarised below it.

| UTC | Commit | Effect, read from the diff against the code the previous run used |
| --- | --- | --- |
| 09:35:41 | `fb26f4d` | last change to `config/default.toml` |
| 09:46:07 | `f748e5b` | 180-second `maximum_frame_gap_seconds` on the run branch — before the harness existed, so it is in **every** run |
| 10:24:15 | `c2d787b` | replay harness and the `verify-2024h1` spec |
| 10:31:39 | `98baf70` | replay metrics and reporting; R2. R1 and R2 agree exactly |
| 11:12:46 | `4c5ac66` | on `main`, not the run branch: the input-quality veto, regime-bound validation, and the same 180-second frame gap again |
| 11:16:25 | `dfbc3bf` | merges `4c5ac66` into the run branch. **Gated: behaviour change** — the input-quality veto (`strategy/opportunity.py`, `strategy/regime.py`). Ungated: none; its signals carry data quality 1.0, so the veto cannot fire. R2a |
| 11:40:18 | `e7e8bc5` | **Gated: behaviour change** — the order size behind `depth_multiple` becomes 80% of capital over `maximum_levels // 2` instead of all levels (`backtest/__main__.py`). Depth halves, and depth feeds the opportunity veto against `minimum_depth_multiple` = 50. Ungated: none; it passes a fixed depth of 1e9. R2b |
| 12:13:03 | `8fe0cf8` | **Behaviour change, both**: depth bounded per bar by the largest order the account can place (gated); degenerate history vetoes entries through zero data quality (gated and ungated); bar extremes rounded outward to the tick (both); runs failing integrity gates are marked invalid. R2c |
| 12:25:30 | `cc1f57a` | **Gated: behaviour change** — depth recomputed before every quote against cash a step can release (`backtest/replay.py`). Ungated: none. R2d |
| 14:31:30 | `e57439a` | maker/taker fee split — a cost model, but round-trip cost feeds the gated opportunity check, and each fill's fee now depends on its type, so it **can** change behaviour of both. At 0.1%/0.1% R3 reproduces R2 exactly. R3 |
| 14:44:28 | `4d7f506` | `practice-2022` spec first exists |
| 14:59:07 | `927e1a7` | profit attribution — reporting |
| 15:29:02 | `f136773` | range-exit counting from account state — reporting per its title and the fee diagnostic's note; not independently verified as behaviour-neutral |
| 15:53:24 | `021899b` | order requests counted per book operation — reported only (`DAILY_REQUEST_BUDGET` feeds `days_over_request_budget`, not a veto); NaN specs rejected first. R3r |

From `021899b` to R4 (`876f7ce`, 2026-09-26) the `src/` commits are measurement,
validation or new unused code by their titles. That is supported, not proven: R4's 16
valid 0%/0.09% returns equal R3's to two decimals, and the V0 equivalence re-run found
40 of 40 fill traces identical between `c07f856` and `99996bc`. It was not checked
commit by commit.

So the record holds **six gated configurations** and **three ungated ones**:

| Gated | Code | Runs | | Ungated | Code | Runs |
| --- | --- | --- | --- | --- | --- | --- |
| V0-a | up to `98baf70` | R1, R2 | | U-a | up to `e7e8bc5` | R1, R2, R2a, R2b |
| V0-a1 | `dfbc3bf` | R2a | | U-a3 | `8fe0cf8`, `cc1f57a` | R2c, R2d |
| V0-a2 | `e7e8bc5` | R2b | | U-b | from `e57439a` | R3, R4 |
| V0-a3 | `8fe0cf8` | R2c | | | | |
| V0-a4 | `cc1f57a` | R2d | | | | |
| V0-b | from `e57439a` | R3, R3r, R4 | | | | |

Every behaviour state after R2 on the run branch was observed at least once, all on
`verify-2024h1` at 0.1%. Each ungated state is named after the gated state in which it
first appears. **As far as the records state, all nine produced the same
`verify-2024h1` table at 0.1%**; only V0-b and U-b ever ran on `practice-2022` or at
other fees.

## 3. The count, under explicit rules

Two counting questions are genuinely open, and the answer depends on both:

1. Is a behaviour-changing code change made after a result was inspected a **new
   configuration**? The data-reuse proposal counts *"adaptively inspected strategy or
   parameter changes"*; all five changes above followed an inspected result.
2. Does the **ungated baseline** count? It is the C6 comparator, not a selectable
   variant — but its result was inspected alongside V0's in every run set, and a
   comparison can inform a search as much as a candidate can.

| Rule | Counted | N |
| --- | --- | ---: |
| A | one strategy; code fixes are not new configurations; benchmark excluded | 1 |
| **B** | **post-inspection behaviour changes are new configurations; benchmark excluded** | **6** |
| C | as B, and the benchmark counted once | 7 |
| D | as B, and the benchmark counted once per behaviour state of its own | 9 |
| — | **true upper bound** | **unknown** |

**Recommendation: register rule B, N = 6, as the central count, and report the
diagnostic under rule D, N = 9, as the sensitivity.** Rule A is shown only to make
visible why it should not be used: it treats five behaviour-changing commits, all made
after a result was seen, as if they never happened.

**Even N = 9 is a floor on true search, not a ceiling.** R1 proves that runs happened
and were inspected without being published. Anything run locally and discarded leaves
no trace, which is exactly why the proposal forbids resetting the count to zero. The
diagnostic has to be reported as conditional on the count, not as a clean pass.

I cannot establish intent from git, and none of this claims any. Whether any of the
five changes was chosen *because* of the results is unknown. The rules exist so that
the answer does not depend on intent.

### Reading the sensitivity

- **These are raw counts.** The nine configurations gave one identical table on
  `verify-2024h1` at 0.1%, so there they are as correlated as trials can be. In the
  deflated Sharpe ratio the benchmark Sharpe grows with N and with the variance of
  Sharpe ratios across trials. If that variance were estimated from these trials,
  adding identical ones would raise N and shrink the variance together. N and the
  variance must therefore come from the same agreed set of trials. Whether an
  effective count may be reported **beside** the raw one is decision 4 in section 7.
  It cannot replace the raw count in the register.
- **The benchmark's results fed a selection.** R3 reported the ungated baseline at all
  three fee levels on both datasets. Its finding 3 compares how gated and ungated runs
  respond to fees. The report then names the next step from those results: a
  trend/cycle filter, an inventory cap and volume-confirmed exits. That is the case for
  rules C and D as the sensitivity, and R3 belongs in `retro-ungated-b` beside R4.
- **Invalid results are kept, and no count depends on dropping them.** The 20 invalid
  SOL results in R3 and R4 were produced and inspected. The counts above are of
  configurations, so excluding SOL from scoring, as the scorecard's mask does, lowers
  none of them.

## 4. What does not count as a trial

Under the proposal's own rule that *"seeds and paths are not independent strategy
trials"*:

- the **two intrabar paths**, high-first and low-first;
- the **two datasets**, as separate trials of one configuration;
- the **three fee levels within R3**: one configuration evaluated under different cost
  assumptions. The Revolut X link is in
  [EXPERIMENT_SPEC_V1.md](../EXPERIMENT_SPEC_V1.md) section 9; this report did not
  re-check the page. As Codex noted, a published fee shows that a cost is realistic,
  not that the venue or tier was chosen without regard to results;
- **reproducibility work on one configuration**: R1's reproduction by R2, R3r's four
  re-runs, the V0 equivalence re-run (`c07f856` against `99996bc`, 40 traces each) and
  Bob's 40-trace cross-check at `c07f856`. None chose anything, and all fall inside
  V0-b, or V0-a for R1.

The fee **model** change in `e57439a` is different from comparing fee **levels**: it is
code that can change decisions, and it is counted as the V0-a4 to V0-b transition in
section 2.

## 5. The part that matters for the next experiment

**The forward family was chosen after V0's first result was seen.** V0's first
inspected result is R1, some time up to 10:31:39 UTC, published as R2 at 10:43:43.
Variant E was first written into the spec at 17:58:46 (`98758fe`) and variant G at
21:46:04 (`8049962`) — hours after, and after R3's report (first committed at 15:43:20,
`545c31a`) had named a trend/cycle filter, an inventory cap and volume-confirmed exits
as the next step. Neither variant has been run, so neither is a retrospective trial.
But the decision *which* variants to test was made knowing the baseline barely traded.

That search is what the deflated Sharpe ratio exists to charge for, and it is invisible
in a count of runs. I recommend recording it as a family-level note on the first
registration, so that the effective count for variants A–H is argued in advance rather
than discovered afterwards. What the adjustment should be, I do not know, and it
should not be settled by me.

## 6. Proposed retrospective entries

For the trusted registration process to validate and append once it exists. Every
entry is **retrospective and not preregistered**, and each names only observed runs.
This table is staging material: it is not a registered count until the trusted process
writes it to `docs/trials/register.jsonl`.

| Entry | Configuration | Run(s) | Code | Data | Result record |
| --- | --- | --- | --- | --- | --- |
| `retro-v0a` | gated grid `price-only-v1`, default config | R1, R2 | R1 unknown; `98baf70` | `verify-2024h1` | verify-2024h1.md |
| `retro-v0a1` | as above, plus the input-quality veto | R2a | `dfbc3bf` | `verify-2024h1` | PR #9 comment, 11:32:13 |
| `retro-v0a2` | as above, depth sized over half the levels | R2b | `e7e8bc5` | `verify-2024h1` | PR #9 comment, 11:40:30; verify-2024h1.md line 24 |
| `retro-v0a3` | as above, per-bar depth bound, degenerate-history veto, outward tick rounding | R2c | `8fe0cf8` | `verify-2024h1` | PR #12 description |
| `retro-v0a4` | as above, depth recomputed per quote | R2d | `cc1f57a` | `verify-2024h1` | PR #12 comments, 12:25:42 and 12:28:02 |
| `retro-v0b` | as above, maker/taker fee split | R3, R3r, R4 | `e57439a`, `927e1a7`, `021899b`, `876f7ce` | `verify-2024h1`, `practice-2022`; SOL results invalid, kept | fee-levels-2026-09.md; Bob's V0 scorecard |
| `retro-ungated-a` | ungated grid baseline (C6 comparator) | R1, R2, R2a, R2b | R1 unknown; `98baf70`, `dfbc3bf`, `e7e8bc5` | `verify-2024h1` | verify-2024h1.md; PR #9 comments |
| `retro-ungated-a3` | ungated baseline, degenerate-history veto, outward tick rounding | R2c, R2d | `8fe0cf8`, `cc1f57a` | `verify-2024h1` | PR #12 description and comments |
| `retro-ungated-b` | ungated baseline, maker/taker fee split | **R3**, R4 | `e57439a`, `927e1a7`, `876f7ce` | `verify-2024h1`, `practice-2022`; SOL results invalid, kept | **fee-levels-2026-09.md**; Bob's V0 scorecard |

The three ungated entries are recorded as history either way; whether they count toward
N is question 2 in section 3. R1's code SHA is unknown and must be entered as unknown,
not guessed.

## 7. Decisions required

1. **The counting rule** — A, B, C or D in section 3, or another. My recommendation is B
   as the central count with D as the sensitivity.
2. **How to treat the forward family's selection effect** from section 5.
3. **Who creates the register, and through which reviewed process**, before the next
   experiment. The proposal forbids widening an untrusted worker's write rights to do it.
4. **Whether an effective count may be reported beside the raw count**, given that the
   nine configurations are identical on `verify-2024h1`, and from which trial set the
   cross-trial variance is taken. This has to be settled before any result it would
   affect.

**Related, outside this PR.** The deflated Sharpe ratio's other input, the return series
it is computed on, was undefined. The cloud Claude review of this PR
([comment](https://github.com/mgalic01/adaptive-market-engine/pull/93#issuecomment-5855509843))
raised it; Claude took it as draft spec part 3, now
[PR #101](https://github.com/mgalic01/adaptive-market-engine/pull/101). Decision 4 above
touches the same formula and should be read with it.

## 8. Withdrawn claims

Earlier versions of this report made claims that do not survive checking. They are
withdrawn, not reworded. Items 1 to 5 were withdrawn in revision 2, items 6 to 8 in
revision 3.

1. **"V0's configured parameters were fixed 46 minutes before any development data
   existed, so they cannot have been fitted to it."** The manifest's `created_at` is
   written only after every archive has been downloaded and parsed —
   `fetch_dataset` takes `fetched_at = now()` after its fetch loop — so 10:21:23 marks
   the *end* of fetching, not first access. The `verify-2024h1` spec was committed at
   10:24:15, after that timestamp, so the data was local before it was committed at all.
   Nothing in the record dates first data access. **What survives:** `config/default.toml`
   did not change after any recorded result.
2. **"The first inspected result was at 10:43:43."** R2's own report says it reproduced
   an earlier run, R1.
3. **"Both post-result changes only reduce trading."** Even a pure veto can *raise*
   measured performance by removing losing trades, so "it only adds vetoes" is not
   evidence against performance selection in the first place. *Revision 3:* revision 2
   also gave a second reason, that `4c5ac66` adds a frame-gap threshold. That reason is
   wrong about the code the runs used: the same threshold was on the run branch from
   `f748e5b`, before the harness existed. The withdrawal stands on the first reason.
4. **"Of the modules changed after the first result, four touch decision logic and all
   four are these two commits."** I read `4c5ac66` filtered to `strategy/` and
   `config.py`, and never read its `simulation/runner.py` change.
5. **"3 is a strict upper bound," and the three proposed register entries.** Three was
   a count of changes I had identified; the true upper bound is unknown. And the entries
   attached both datasets and the C1/C2 outcome to configurations that never ran on
   them: `practice-2022` did not exist until 14:44:28, after the behaviour changes.
   *Revision 3:* this item also said that no published run used the state between
   `4c5ac66` and `8fe0cf8`. That is false; see item 6.
6. **"The gated grid appears in two behaviourally different configurations"**, and
   **"the states after `4c5ac66` but before `8fe0cf8`, and after `8fe0cf8` but before
   `e57439a`, were never observed in any published run"**, with **N = 2 central and
   N = 4 sensitivity** built on them. Four more replays on `verify-2024h1` were reported,
   at `dfbc3bf`, `e7e8bc5`, `8fe0cf8` and `cc1f57a`. Codex's Cloud review found
   `e7e8bc5`; the other three came to light in checking it.
7. **"Every commit touching strategy, simulation, features, config or domain code between
   `98baf70` and `876f7ce` is `4c5ac66`, `8fe0cf8`, `e57439a`, `146d7d5` and a merge."**
   The path filter left out `backtest/__main__.py` and `backtest/replay.py`, which compute
   the gated grid's depth input, so it missed `e7e8bc5` and `cc1f57a`. It is the same
   error as item 4: a path filter chosen in advance decided what I saw.
8. **"R3: gated grid `price-only-v1` at three fee levels."** R3 also ran and reported the
   ungated baseline on both datasets at all three fee levels, and 12 of its results were
   invalid. The ungated entry cited only R4.

## 9. What I checked, and what I could not

- **Checked at source:** each run's code, data, strategies and validity from its own
  record, including PR #9 and PR #12 comments; every `src/` commit from `98baf70` to
  `021899b`, read whole; that `f748e5b` is an ancestor of `98baf70` and `c2d787b`
  follows it; that the ungated baseline passes data quality 1.0 and depth 1e9, so the
  quality veto and the depth changes cannot reach it; that `DAILY_REQUEST_BUDGET` is
  reported, not enforced; the full diff of `4c5ac66`; `fetch_dataset`'s ordering; the
  first commit of each dataset spec and result report; the time order in UTC from Unix
  time.
- **Recomputed by script:** every count in sections 1 and 3, and R4's 16 valid
  0%/0.09% returns against R3's, parsed from both reports; see section 10.
- **Could not check:** anything never committed or published — R1 is the proof that such
  runs exist; R1's exact code; which four runs R3r repeated; intent behind any
  behaviour change; whether `f136773` and the `src/` commits from `021899b` to
  `876f7ce` are behaviour-neutral beyond their titles, R4's agreement with R3 and the
  equivalence re-run; whether the replays reported as identical agreed beyond the
  published table's precision.

## 10. Reproducing

From a clone with full history, no data needed:

```
git log -1 --format='%h %at %s' fb26f4d f748e5b c2d787b 98baf70 ee37d2a 4c5ac66 dfbc3bf e7e8bc5 8fe0cf8 cc1f57a e57439a 4d7f506 927e1a7 f136773 021899b
git log --reverse --format='%h %at %s' 98baf70..876f7ce -- src/ config/
git merge-base --is-ancestor f748e5b 98baf70 && echo "frame gap was in R2's code"
git diff 98baf70 dfbc3bf -- src/
git show e7e8bc5 -- src/crypto_grid_bot/backtest/__main__.py
git show cc1f57a -- src/crypto_grid_bot/backtest/replay.py
git show 8fe0cf8:src/crypto_grid_bot/backtest/replay.py | grep -n -A3 "if not gated"
git log --reverse --format='%h %at %s' -- config/datasets/practice-2022.toml docs/backtests/fee-levels-2026-09.md
```

Convert `%at` (Unix seconds) to UTC before sorting; do not sort `%ad` strings, which
carry mixed timezone suffixes. Read commits whole, not filtered to the paths you expect
to matter.

The counts were computed with this script, run from the repository root as
`python count.py .`:

```python
import re, sys
from pathlib import Path

V, VP = {"verify-2024h1": 2}, {"verify-2024h1": 2, "practice-2022": 3}
SOL = {"practice-2022": 1}  # one pair per practice run set is invalid
RUNS = [  # run, gated state, ungated state, datasets, fee levels, invalid pairs
    ("R1", "V0-a", "U-a", V, 1, {}),
    ("R2", "V0-a", "U-a", V, 1, {}),
    ("R2a", "V0-a1", "U-a", V, 1, {}),
    ("R2b", "V0-a2", "U-a", V, 1, {}),
    ("R2c", "V0-a3", "U-a3", V, 1, {}),
    ("R2d", "V0-a4", "U-a3", V, 1, {}),
    ("R3", "V0-b", "U-b", VP, 3, SOL),
    ("R4", "V0-b", "U-b", VP, 2, SOL),
]
R3R = 4  # four re-run results at 021899b
n = lambda pairs, fees: sum(pairs.values()) * 2 * 2 * fees  # x 2 paths x 2 strategies
gated = {g for _, g, *_ in RUNS}
ungated = {u for _, _, u, *_ in RUNS}
print("results", sum(n(d, f) for *_, d, f, _ in RUNS) + R3R, "R1 inferred", n(V, 1))
print("invalid", sum(n(b, f) for *_, f, b in RUNS))
print("A", 1, "B", len(gated), "C", len(gated) + 1, "D", len(gated) + len(ungated))

# R4's valid 0%/0.09% returns against R3's 0%/0.09% column, to two decimals.
root = Path(sys.argv[1])
num = lambda s: float(s.split("(")[0].replace("−", "-").strip("*+ "))
r3, ds = {}, None
for line in (root / "docs/backtests/fee-levels-2026-09.md").read_text("utf-8").splitlines():
    ds = ("practice-2022" if "practice" in line else "verify-2024h1") if line[:4] == "### " else ds
    m = re.match(r"\| (\w+) \| (\w+) grid \| .*\| (.+) \|$", line)
    if m and ds:
        for path, v in zip(("high_first", "low_first"), m.group(3).split(" / ")):
            r3[ds, m.group(1), m.group(2), path] = num(v)
card = (root / "docs/reviews/2026-09-25-bob-v0-dev-scorecard.md").read_text("utf-8")
g_part, u_part = card.split("## 5.")[1].split("## 6.")[0].split("Ungated baseline")
r4 = {}
for part, strat, col in ((g_part, "gated", 4), (u_part, "ungated", 3)):
    for line in part.splitlines():
        c = [x.strip() for x in line.strip("|").split("|")]
        if c[0] in VP and "EXCLUDED" not in line:
            r4[c[0], c[1][:-4], strat, c[2]] = num(c[col])
print("R4 v R3 compared", len(r4), "mismatches", [k for k in r4 if round(r4[k], 2) != r3[k]])
```

Output at this revision:

```
results 152 R1 inferred 8
invalid 20
A 1 B 6 C 7 D 9
R4 v R3 compared 16 mismatches []
```

The run table in the script is the ledger of section 1, typed in by hand; the script
checks the arithmetic, not the ledger. Bob's reading of the ledger against the records
is the check on that.

## 11. Revisions

| Revision | Head | What changed |
| --- | --- | --- |
| 1 | `813d251` | First version: N = 1, "strict upper bound" 3, three proposed entries. |
| 2 | `2b6aea1` | Rebuilt from the runs that actually happened after Codex's review: R1–R4, ungated baseline inventoried, N = 2 central and N = 4 sensitivity, true upper bound unknown; claims 1–5 withdrawn. |
| 3 | this head | Codex's audit and Cloud findings: added the observed intermediate runs at `dfbc3bf`, `e7e8bc5`, `8fe0cf8` and `cc1f57a` (R2a–R2d) and R3's ungated and invalid results; R3r listed; counts recomputed by script to **N = 6 central, N = 9 sensitivity**, true upper bound still unknown; frame-gap reason corrected (it was in every run); sensitivity reading, decision 4 and the link to part 3 (#101) added; Revolut X fee source linked; claims 6–8 withdrawn. |
