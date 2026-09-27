# Claude: draft spec part 2 — the retrospective trial count, and its uncertainty

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **Revised 2026-09-27** after Codex's independent review of the first version found it
  undercounted, overclaimed and paired results with configurations that never ran. The
  withdrawn claims are listed in [section 8](#8-withdrawn-claims) rather than quietly
  replaced. Every finding in that review was checked at source before this revision.
- **What this does for the goal.** The deflated Sharpe ratio adopted in the merged
  [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md) as the named
  multiple-testing diagnostic needs an honest count of strategies already tried. If that
  count is understated, any Sharpe ratio from development data looks better than it is,
  and the €100 go/no-go decision rests on an inflated number. The proposal is explicit:
  *"Incomplete historical search information cannot be reset to zero."*
- **Scope.** It inventories the runs that actually happened, states the count under
  explicit counting rules, and proposes entries. **It does not create
  `docs/trials/register.jsonl`**: the proposal reserves that for a separately reviewed
  trusted process. Evidence is git history and published reports; no archive was opened
  and nothing touches the reserved window.

## 1. The runs that actually happened

Each row is one inspected result, bound to the code, data and report it came from. A
row exists only where a published record says the run happened.

| Run | Code | Data | Strategies | Result record |
| --- | --- | --- | --- | --- |
| R1 | earlier than `98baf70`; exact SHA **not recorded** | `verify-2024h1` | as R2 | [verify-2024h1.md](../backtests/verify-2024h1.md) line 29: *"reproduced … exactly"* by R2 |
| R2 | `98baf70` | `verify-2024h1` (ADA, BTC; Jan–Jun 2024) | **gated grid `price-only-v1`** and **ungated grid baseline**, both intrabar paths | same file, published `ee37d2a`; gated V0 barely trades, ungated trades more and loses more |
| R3 | `e57439a`; practice runs also `927e1a7` | `verify-2024h1` and `practice-2022` | gated grid `price-only-v1` at three fee levels | [fee-levels-2026-09.md](../backtests/fee-levels-2026-09.md) |
| R4 | `876f7ce9d3a32b4a31bc558a0eb038a462c1472e` | `verify-2024h1` and `practice-2022` | gated grid `price-only-v1` and ungated grid baseline | [Bob's V0 scorecard](2026-09-25-bob-v0-dev-scorecard.md) |

R1 is known only because R2's report mentions it. It is the clearest sign that the
recorded history is incomplete: runs that were looked at but not published leave no
other trace.

## 2. Which configurations those runs used, and what changed between them

Times are UTC on 2026-09-24, converted from Unix commit time.

| UTC | Commit | Effect on the gated grid's behaviour, read from the diff |
| --- | --- | --- |
| 09:35:41 | `fb26f4d` | last change to `config/default.toml` |
| 10:24:15 | `c2d787b` | replay harness and the `verify-2024h1` spec |
| 10:31:39 | `98baf70` | replay metrics and reporting; R1 and R2 agree exactly, so no behavioural difference between them |
| 11:12:46 | `4c5ac66` | **behaviour change**: a new `SimulationPolicy.maximum_frame_gap_seconds` (default 180) governs when outside-range time accumulates and when recovery resets (`simulation/runner.py`); the input-quality veto is enforced; regime bounds validated |
| 12:13:03 | `8fe0cf8` | **behaviour change**: degenerate-history veto, depth bound, integrity gates |
| 14:31:30 | `e57439a` | maker/taker fee split — a cost model, but round-trip cost feeds the opportunity check, so it **can** change which grids open |
| 14:44:28 | `4d7f506` | `practice-2022` spec first exists |
| 14:59:07 | `927e1a7` | profit attribution — reporting |
| 15:29:02 | `f136773` | range-exit counting from account state — reporting per its title and the fee diagnostic's note; not independently verified as behaviour-neutral |

So the gated grid appears in the record in **two behaviourally different
configurations**:

- **V0-a** — code up to `98baf70`: runs R1 and R2, on `verify-2024h1` only.
- **V0-b** — code from `e57439a` on, after both behaviour changes: runs R3 and R4, on
  both datasets. The commits between R3 and R4 are reporting or measurement-only.

**Never observed in any published run:** the state after `4c5ac66` but before
`8fe0cf8`, and the state after `8fe0cf8` but before `e57439a`. They are code states, not
trials, and are not registered as trials.

The ungated grid baseline appears at `98baf70` (R2) and at `876f7ce` (R4).

## 3. The count, under explicit rules

Two counting questions are genuinely open, and the answer depends on both:

1. Is a behaviour-changing code change made after a result was inspected a **new
   configuration**? The data-reuse proposal counts *"adaptively inspected strategy or
   parameter changes"*; both changes above followed an inspected result.
2. Does the **ungated baseline** count? It is the C6 comparator, not a selectable
   variant — but its result was inspected alongside V0's, and a comparison can inform a
   search as much as a candidate can.

| Rule | Counted | N |
| --- | --- | ---: |
| A | one strategy; code fixes are not new configurations; benchmark excluded | 1 |
| **B** | **post-inspection behaviour changes are new configurations; benchmark excluded** | **2** |
| C | as B, and the benchmark counted once | 3 |
| D | as B, and the benchmark counted per code version | 4 |
| — | **true upper bound** | **unknown** |

**Recommendation: register rule B, N = 2, as the central count, and report the
diagnostic under rule D, N = 4, as the sensitivity.** Rule A is shown only to make
visible why it should not be used: it treats two behaviour-changing commits, both made
after a result was seen, as if they never happened.

**Even N = 4 is a floor on true search, not a ceiling.** R1 proves that runs happened
and were inspected without being published. Anything run locally and discarded leaves
no trace, which is exactly why the proposal forbids resetting the count to zero. The
diagnostic has to be reported as conditional on the count, not as a clean pass.

I cannot establish intent from git, and none of this claims any. Whether the two
behaviour changes were chosen *because* of the results is unknown. Section 3's rules
exist so that the answer does not depend on intent.

## 4. What does not count as a trial

Under the proposal's own rule that *"seeds and paths are not independent strategy
trials"*:

- the **two intrabar paths**, high-first and low-first;
- the **two datasets**, as separate trials of one configuration;
- the **three fee levels within R3**: one configuration evaluated under different cost
  assumptions, where the Revolut X figures are the venue's published fees;
- **reproducibility work**: R1's reproduction by R2, the V0 equivalence re-run and the
  40-trace cross-check re-ran existing configurations and chose nothing.

The fee **model** change in `e57439a` is different from comparing fee **levels**: it is
code that can change decisions, and it is counted as part of the V0-a to V0-b
transition in section 2.

## 5. The part that matters for the next experiment

**The forward family was chosen after V0's first result was seen.** V0's first
inspected result is R1, some time up to 10:31:39 UTC, published as R2 at 10:43:43.
Variant E was first written into the spec at 17:58:46 (`98758fe`) and variant G at
21:46:04 (`8049962`) — hours after. Neither has been run, so neither is a retrospective
trial. But the decision *which* variants to test was made knowing the baseline barely
traded.

That search is what the deflated Sharpe ratio exists to charge for, and it is invisible
in a count of runs. I recommend recording it as a family-level note on the first
registration, so that the effective count for variants A–H is argued in advance rather
than discovered afterwards. What the adjustment should be, I do not know, and it
should not be settled by me.

## 6. Proposed retrospective entries

For the trusted registration process to validate and append once it exists. Every
entry is **retrospective and not preregistered**, and each names only an observed run.

| Entry | Configuration | Run(s) | Code | Data | Result record |
| --- | --- | --- | --- | --- | --- |
| `retro-v0a` | gated grid `price-only-v1`, default config | R1, R2 | ≤ `98baf70` | `verify-2024h1` | verify-2024h1.md |
| `retro-v0b` | gated grid `price-only-v1`, default config | R3, R4 | `e57439a`, `927e1a7`, `876f7ce` | `verify-2024h1`, `practice-2022` | fee-levels-2026-09.md; Bob's V0 scorecard |
| `retro-ungated-a` | ungated grid baseline (C6 comparator) | R2 | `98baf70` | `verify-2024h1` | verify-2024h1.md |
| `retro-ungated-b` | ungated grid baseline (C6 comparator) | R4 | `876f7ce` | `verify-2024h1`, `practice-2022` | Bob's V0 scorecard |

The two ungated entries are recorded as history either way; whether they count toward
N is question 2 in section 3. R1's code SHA is unknown and must be entered as unknown,
not guessed.

## 7. Decisions required

1. **The counting rule** — A, B, C or D in section 3, or another. My recommendation is B
   as the central count with D as the sensitivity.
2. **How to treat the forward family's selection effect** from section 5.
3. **Who creates the register, and through which reviewed process**, before the next
   experiment. The proposal forbids widening an untrusted worker's write rights to do it.

## 8. Withdrawn claims

The first version of this report made five claims that do not survive checking. They
are withdrawn, not reworded:

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
3. **"Both post-result changes only reduce trading."** `4c5ac66` adds a frame-gap
   threshold that changes outside-range accumulation and recovery resets; its direction
   of effect on trading is not established. And even a pure veto can *raise* measured
   performance by removing losing trades, so "it only adds vetoes" is not evidence
   against performance selection in the first place.
4. **"Of the modules changed after the first result, four touch decision logic and all
   four are these two commits."** I read `4c5ac66` filtered to `strategy/` and
   `config.py`, and never read its `simulation/runner.py` change — the one that matters.
5. **"3 is a strict upper bound," and the three proposed register entries.** Three was
   a count of changes I had identified; the true upper bound is unknown. And the entries
   attached both datasets and the C1/C2 outcome to configurations that never ran on
   them: `practice-2022` did not exist until 14:44:28, after both behaviour changes, and
   no published run used the state between `4c5ac66` and `8fe0cf8`.

## 9. What I checked, and what I could not

- **Checked at source:** each run's code, data and strategies from its own report; the
  full diff of `4c5ac66`, not a path-filtered one; `fetch_dataset`'s ordering; the first
  commit of each dataset spec; the time order in UTC from Unix time.
- **Checked:** every commit touching strategy, simulation, features, config or domain
  code between `98baf70` and `876f7ce` — `4c5ac66`, `8fe0cf8`, `e57439a`, `146d7d5`
  (measurement only) and a merge commit.
- **Could not check:** anything never committed or published — R1 is the proof that such
  runs exist; R1's exact code; intent behind either behaviour change; whether
  `f136773` is fully behaviour-neutral beyond its title and the fee diagnostic's note.

## 10. Reproducing

From a clone with full history, no data needed:

```
git log -1 --format='%h %at %s' fb26f4d c2d787b 98baf70 ee37d2a 4c5ac66 8fe0cf8 e57439a 4d7f506 927e1a7 f136773
git log --reverse --format='%h %at' -- config/datasets/practice-2022.toml
git show 4c5ac66 --stat
git show 4c5ac66 -- src/crypto_grid_bot/simulation/runner.py src/crypto_grid_bot/domain.py
git log --format='%h %s' 98baf70..876f7ce -- src/crypto_grid_bot/strategy src/crypto_grid_bot/simulation src/crypto_grid_bot/backtest/features.py src/crypto_grid_bot/config.py src/crypto_grid_bot/domain.py config/default.toml
```

Convert `%at` (Unix seconds) to UTC before sorting; do not sort `%ad` strings, which
carry mixed timezone suffixes. Read commits whole, not filtered to the paths you expect
to matter.
