# Claude: draft spec part 2 — the retrospective trial count, and its uncertainty

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **What this does for the goal.** The deflated Sharpe ratio, adopted in the merged
  [data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md) as the named
  multiple-testing diagnostic, needs an honest count of strategies already tried. If
  that count is understated, any Sharpe ratio from development data looks better than
  it is, and the €100 go/no-go decision rests on an inflated number. The proposal is
  explicit: *"Incomplete historical search information cannot be reset to zero."*
- **Scope.** Part 2 of the draft-spec work. It measures the retrospective count and
  proposes the entries. **It does not create `docs/trials/register.jsonl`**: the
  proposal reserves that for "a separately reviewed trusted process" established before
  the next experiment. Evidence is git history and published reports only; no archive
  was opened and nothing touches the reserved window.

## 1. The count

| | Count | Basis |
| --- | ---: | --- |
| **Point estimate** | **1** | One strategy configuration has been run on development data and inspected: V0, `price-only-v1`, default config. |
| **Strict upper bound** | **3** | Counting every behaviour change made after a result was inspected as a separate configuration. |
| **Lower bound** | **1** | It cannot be zero: V0 was run, and its results are known to everyone designing the next variants. |

Recommendation: register **1** as the retrospective count, record **3** as the
sensitivity bound, and report the diagnostic under both. The proposal requires exactly
this — *"report assumptions, raw count and correlated-candidate sensitivity"* — and an
estimate that is only defensible under one reading should not be presented alone.

## 2. The evidence, in UTC

Every time below is converted to UTC from the commit's own timestamp. One commit is
recorded at `+02:00`, and sorting the raw strings put it in the wrong order; the table
is sorted on the Unix time.

| UTC, 2026-09-24 | Commit | Event |
| --- | --- | --- |
| 00:42:30 | `01ece8e` | `config/default.toml` created with the paper-only decision core |
| **09:35:41** | `fb26f4d` | **`config/default.toml` changed for the last time** |
| 10:21:23 | — | `verify-2024h1` manifest created: the first development dataset exists |
| **10:43:43** | `ee37d2a` | **First inspected result, published as "strategy barely trades"** |
| 11:12:46 | `4c5ac66` | Input-quality veto enforced; regime-bound validation tightened |
| 12:13:03 | `8fe0cf8` | Degenerate-history veto added (Codex replay review R1–R4) |
| 17:58:46 | `98758fe` | Variant E first written into the spec |
| 21:46:04 | `8049962` | Variant G first written into the spec |

**V0's configured parameters were fixed 46 minutes before the first development dataset
existed**, and `config/default.toml` has not changed since. They cannot have been fitted
to development data. Every recorded development run — `verify-2024h1`,
[the fee-level diagnostic](../backtests/fee-levels-2026-09.md) and
[Bob's V0 scorecard](2026-09-25-bob-v0-dev-scorecard.md) — used `price-only-v1` with
that default config, and the latter two state *"No parameter was tuned on these
results."*

## 3. Why the upper bound is 3, and why I still recommend 1

Two changes to V0's decision logic landed **after** the first result was inspected, at
29 and 89 minutes. A strict reading must count them: V0 as first run, V0 with the
input-quality veto, V0 with the degenerate-history veto are three distinct
configurations whose behaviour differs, and the first was seen before the others
existed.

The evidence against treating them as performance-seeking is specific, and it is the
reason for the point estimate of 1:

- **Direction.** Both *add* vetoes, so V0 trades **less** after them — in bad-input
  conditions and on flat or zero-volume history. The first result said the strategy
  barely traded. A change made to chase that result would push the other way.
- **Provenance.** `8fe0cf8` is titled as a fix for Codex's replay review items R1–R4;
  `4c5ac66` enforces an input-quality veto the regime code already reported but
  `opportunity.py` did not act on, and tightens validation bounds that only reject
  invalid configurations.
- **No tunable parameter moved.** Neither touches `config/default.toml`, and the
  `config.py` change in `4c5ac66` alters validation of values, not any default.
- **No re-run chosen for a better answer** follows either change in the record.

I cannot prove motive from git history. That is exactly why 3 is recorded as the
sensitivity bound rather than discarded.

## 4. What does not count as a trial

Under the proposal's own rule — *"seeds and paths are not independent strategy
trials"* — none of these adds to the count:

- the **three fee levels** in the fee diagnostic (Binance 0.1%, 0.075%, Revolut X 0% maker
  / 0.09% taker): the same strategy under different cost assumptions, and the Revolut X
  figures are the venue's published fees rather than a value chosen from results;
- the **two datasets**, `verify-2024h1` and `practice-2022`;
- the **two intrabar paths**, high-first and low-first;
- **reproducibility work**: the V0 equivalence re-run and the 40-trace cross-check
  re-ran an existing configuration to confirm it, and chose nothing.

## 5. The part that matters for the next experiment

**The forward family was chosen after V0's first result was seen.** Variant E entered
the spec at 17:58:46 UTC and variant G at 21:46:04, seven and eleven hours after "strategy
barely trades". Neither has been run, so neither is a retrospective trial. But the
decision *which* variants to test was made by people who knew the baseline barely
traded.

That is the kind of search the deflated Sharpe ratio is meant to charge for, and it is
invisible in a count of runs. I recommend the register record it explicitly as a
family-level note on the first registration, so that the effective trial count for
variants A–H is argued about in advance rather than discovered afterwards. What the
right adjustment is, I do not know, and it should not be settled by me.

## 6. Proposed retrospective entries

For the trusted registration process to append once it exists. Each is labelled **not
preregistered**, as the proposal requires.

| Trial | Configuration | Data | Result inspected | Label |
| --- | --- | --- | --- | --- |
| `retro-001` | V0 `price-only-v1`, default config at `fb26f4d` | `verify-2024h1`, `practice-2022` | "strategy barely trades"; V0 fails C1 and C2 at primary fees | retrospective, not preregistered |
| `retro-001a` | as `retro-001` plus the input-quality veto, `4c5ac66` | same | via later runs | sensitivity only: counted in the upper bound of 3 |
| `retro-001b` | as `retro-001a` plus the degenerate-history veto, `8fe0cf8` | same | via later runs | sensitivity only: counted in the upper bound of 3 |

## 7. Decisions required

1. **Which count feeds the diagnostic** — 1, or 3, or both with the result reported as
   conditional on the assumption. My recommendation is both.
2. **How to treat the forward family's selection effect** from section 5.
3. **Who creates the register**, and through which reviewed process, before the next
   experiment. The proposal forbids widening an untrusted worker's write rights to do it.

## 8. What I checked, and what I could not

- **Checked:** the full history of `config/default.toml`, and every `src/` module changed
  after the first inspected result. Of eighteen changed modules, four touch decision
  logic — `strategy/regime.py`, `strategy/opportunity.py`, `config.py` and
  `backtest/features.py` — and all four changes are the two commits in section 3. The
  `simulation/` and `domain.py` changes are the maker/taker fee split `e57439a` (a cost
  model, not a decision, and the reason section 4 does not count fee levels),
  measurement-only prerequisites `146d7d5`, part of `4c5ac66`, and a merge commit. The
  remainder is replay harness, dataset, audit and streaming code.
- **Checked:** the time order in UTC, after catching a timezone sorting error in my own
  first pass.
- **Could not check:** anything never committed. A configuration someone ran locally,
  looked at, and discarded leaves no trace in git. The count is a count of *recorded*
  search, which is why it is a lower bound on true search, and why the proposal forbids
  resetting it to zero rather than asking anyone to prove it complete.
- **Could not check:** intent. Section 3's argument for the point estimate is from
  direction and provenance, not from anyone's stated reasons.

## 9. Reproducing

From a clone with full history, no data needed:

```
git log --format='%h %at %s' -- config/default.toml
git log -1 --format='%h %at %s' ee37d2a
git log --format= --name-only ee37d2a..bb76659 -- src/ | sort | uniq -c | sort -rn
git show 4c5ac66 -- src/crypto_grid_bot/strategy/ src/crypto_grid_bot/config.py
git show 8fe0cf8 -- src/crypto_grid_bot/backtest/features.py
```

Convert `%at` (Unix seconds) to UTC before sorting; do not sort the `%ad` strings, which
carry mixed timezone suffixes.
