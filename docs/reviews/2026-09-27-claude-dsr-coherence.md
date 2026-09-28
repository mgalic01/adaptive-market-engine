# Claude: the deflated Sharpe ratio cannot be estimated here; C7 replaces it

- **Date:** 2026-09-27. **Author:** Claude.
- **Corrects:** [draft spec part 3, the DSR return series](2026-09-27-claude-dsr-return-series.md)
  (PR #101) and [draft spec part 2, the retrospective trial count](2026-09-27-claude-retrospective-trial-count.md)
  (PR #93). Both merged; both get a dated revision note that points here.
- **Owner decision, 2026-09-27:** replace the DSR with a Holm step-down and make it
  gate the reserved-window run, as **C7** in
  [`EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md) §6 ("3) ok").
- **Addresses** four unresolved Codex review threads on merged PRs: `r4116484650`
  (use the merged trial count), `r4116479753` (`a077a0f` missed), `r4116479755` (fee
  overrides), `r4116479762` (omitted re-runs). Replies go on an open PR, never the merged
  ones.
- Computes nothing from any strategy result; reads no market data. Every number below
  was recomputed for this record.

## 1. The frozen DSR has no content on this family

`SR0 = √V · E[max z](N)`, where `V` is the variance of the trial Sharpes. **`V` is not
estimable here at all.** The retrospective runs never produced the daily series part 3
requires — §4 of this record shows they cannot have it — so their Sharpes do not exist
to take a variance of.

*(Correction, Codex 2026-09-27: an earlier version of this record said `V = 0`, inferred
from the counted configurations sharing one `verify-2024h1` summary table. That does not
follow: different daily paths can produce the same summary. The conclusion is unchanged
and stronger — an input that cannot be estimated is worse than one that is zero — but the
premise was wrong, so the arithmetic below is a demonstration of the estimator's
behaviour, not a measurement of this family.)*

Treating `V` as zero for illustration, `SR0` = 0 and the "DSR" is the Probabilistic
Sharpe Ratio against zero, whatever `N` is.

`SR0` is linear in `√V` and only logarithmic in `N`:

| N | 2 | 4 | 6 | 7 | 9 | 10 | 16 | 20 | 50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E[max z] | 0.5198 | 1.0521 | 1.3001 | 1.3868 | 1.5208 | 1.5746 | 1.8005 | 1.9007 | 2.2763 |

**Disclosing more trials lowers the hurdle.** Start from trial Sharpes {0.02, 0.04} and
add identical trials at 0.03, using the record's own divisor `N − 1`:

| Trials | N | Sample V | SR0 |
| --- | ---: | ---: | ---: |
| {0.02, 0.04} | 2 | 2.000e−4 | 0.007350 |
| + 5 at 0.03 | 7 | 3.333e−5 | 0.008007 |
| + 14 at 0.03 | 16 | 1.333e−5 | 0.006574 |
| + 20 at 0.03 | 22 | 9.524e−6 | 0.005994 |

A multiple-testing penalty that falls when more testing is admitted is not a penalty.
The trial-count record noticed the mechanism and called it a caveat; it disqualifies the
estimator.

**It is also looser than a plain Bonferroni correction.** The daily Sharpe needed to
pass, with normal moments (`γ3` = 0, `γ4` = 3):

| | T = 2,284 | T_eff = 1,142 | T_eff = 761 |
| --- | ---: | ---: | ---: |
| frozen DSR ≥ 0.95 at V = 0 | 0.0344 | 0.0487 | 0.0597 |
| Holm/Bonferroni, N = 7, 5% | 0.0513 | 0.0726 | 0.0891 |
| Holm/Bonferroni, N = 16, 5% | 0.0573 | 0.0811 | 0.0994 |
| Holm/Bonferroni, N = 19, 5% | 0.0585 | 0.0828 | 0.1015 |

*[2026-09-28: illustrative. N = 7 and N = 16 were the rule-C and central `N_family` counts
when this record was first written; N = 19 is a sensitivity value with no count behind it.
The current floors are 16–17 and 20–21 (§3). The table shows how the Bonferroni hurdle
moves with N and is used for nothing else.]*

Estimating `V` from the forward family instead would make the hurdle depend on the
results it judges. A fixed economic `SR0` carries no multiplicity meaning. White's Reality
Check and Hansen's SPA are better tests, but they are less conservative than Holm, so
they could only be registered before any forward result exists; this record does not
register them.

## 2. The replacement: C7

**C7** is now in the spec. For every selectable forward variant and each path, `p` is
the one-sided PSR p-value against zero with the frozen machinery (raw daily Sharpe,
Pearson kurtosis, population moments, within-fold `T_eff`). A variant's `p` is its worse
path. A Holm step-down at family-wise 5% runs over `N_family` hypotheses, with the
retrospective configurations entering at `p` = 1. It is evaluated on the selected winner
only, after the deterministic selection, and it gates the reserved-window run, not the
ranking. What part 3 computes at `V = 0` is a PSR, so the statistic is named the
**Holm-adjusted Sharpe test**.

Everything else in part 3 stands: the series, the daily valuation, `T_eff`, and the
indeterminate rules for zero variance, `T_eff < 2` and an indeterminate fold. Two rules
existed only to protect `V` and are withdrawn: "a registered trial without a Sharpe makes
the path indeterminate" and "`N < 2` is indeterminate".

**Forward runs only.** The retrospective trials ran on `verify-2024h1` (Jan–Jun 2024) and
`practice-2022`. Neither is a test window of the 25-fold grid, and neither pair set is a
fold's eligible set, so none of them can have the per-fold daily series. They enter C7
only through `N_family`.

## 3. The counts, corrected

**`a077a0f` was missed.** It is an ancestor of `98baf70`, so the record's enumeration
range `98baf70..876f7ce` could not see it. It changed the coverage window in
`features.py` from `minute_ms − 168 h` to the 168 whole hours before the current hour,
which feeds data quality into the gated path's regime and opportunity checks. It cannot
reach the ungated baseline, whose data quality is fixed at 1.0. The ungated count stays 3.

**Which side of `a077a0f` R1 ran on is unknown.** An earlier version of this section said
R1 ran before it, citing the placeholder `verify-2024h1.md` ("The first replay of harness
v1 is running"). That inference was wrong (Codex, 2026-09-27): `a077a0f` itself created
that file, and the same placeholder says the file "will be replaced by the verified
results … from a run on the committed code", so R1 may have run on `a077a0f` or on code
just before it. If before, `a077a0f` adds a gated state; if on it, it does not. So the
gated path had **6 or 7** behaviour states.

| Rule (trial-count record §3) | As merged | Corrected |
| --- | ---: | ---: |
| A (one strategy) | 1 | 1 |
| **B** (post-inspection behaviour changes) | 6 | **6–7** |
| C (B + benchmark once) | 7 | **7–8** |
| **D** (B + benchmark per own state) | 9 | **9–10** |

Where one number is needed, the **upper** value is the working figure: a larger family
makes the Holm cutoff stricter, so it errs toward rejecting a variant.

**The forward family.** Spec §4 has 11 configurations; D is not selectable. The owner
ruled on 2026-09-27 that V0 on engine `exit-residue-v1` is an additional registered
trial, so forward V0 is new, not a repeat of retrospective V0-b.

*[2026-09-28: the "fixed V0" is the V0 that will actually run, which since spec v1
amendment 1 (PR #124) is the amended V0: the exit fix of `exit-residue-v1` plus the
drawdown recovery, on the engine version and schema its implementation PR assigns. No V0
result on `exit-residue-v1` itself has been run or inspected (PR #122 ran no replay), so
the "+ V0 on `exit-residue-v1`" row below stands for that one trial. If the un-amended
fixed V0 is ever run and inspected as well, it is one further trial and both budgets
below gain one.]*

| Budget | Arithmetic | N |
| --- | --- | ---: |
| **`N_family`, central** | 6–7 retrospective gated + V0 on `exit-residue-v1` + 9 new selectable | **16–17** (working: 17) |
| `N_family`, sensitivity | + 3 ungated retrospective states + D | **20–21** (working: 21) |

Both are floors: unpublished inspected runs exist (R1 proves it).

**Counting rule, stated once.** A trial is one strategy configuration × declared
scenario whose result was, or will be, inspected. The configuration changes whenever a
code or parameter change can alter a decision or a fill. Reproductions add nothing;
seeds, intrabar paths, pairs and folds add nothing.

- **Fee levels.** The forward fee scenarios are fixed in spec §4 before any run and
  acceptance is judged at the primary fees, so they do not split configurations. R3's
  retrospective three-level sweep was adaptive, so it is carried as a reported
  sensitivity (rule E): 9 gated, 14 with the benchmark.
- **Omitted re-runs.** `146d7d5` (16 results), the `c07f856`/`99996bc` equivalence
  exercise (40 traces per tree) and Bob's 40 fresh traces are reproduction events, as R3r
  already is. They are listed, and they add nothing to `N`.

## 4. What is not decided here

- **C7 is adopted in principle and is not yet binding.** Codex's review of 2026-09-27
  withheld agreement on three grounds, all correct, and the spec row now records them:
  the series C7 is computed on is undefined (§4's two windows against part 3's 25-fold
  geometry, which is itself a proposal); `N_family` = 17 and 21 (upper ends of 16–17 and 20–21) are **floors**, and a
  Holm cutoff taken from a floor does not control family-wise error at 5%; and all three
  agents agreed to the DSR, so retiring it needs Codex's and Bob's acknowledgment. Bob
  gave his on 2026-09-27 in his PR #123 review *[2026-09-28: his words were "I agree with
  retiring the frozen DSR in favor of the Holm step-down (C7) once settled", conditional on
  C7 being settled, consistent with C7 not yet binding]*; Codex's is owed.
  Until those are settled, C1–C6 remain the binding set.
- **The family must be accounted for, not assumed.** Either the unpublished inspected
  runs are classified in the trial register — shown to reproduce a counted configuration,
  or counted — or a deliberately conservative budget is preregistered. Either way it is
  fixed before any forward result exists.
- The trusted trial register, when built, must accept retrospective entries with no
  Sharpe field.
