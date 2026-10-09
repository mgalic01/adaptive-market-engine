# Frozen V3 criterion checks

Index: Implemented A1-A5 checks on reconciled matched-size accounts with complete matching rule schedules; no whole-experiment verdict or historical run.

A1-A4 use the main m=2 base-cost account's Sharpe >=1, trade profit factor
>=1.3, Calmar >=0.5 and CAGR >=0.08. A5 compares base-cost m=1 strategy Sharpe
strictly above the risk-matched spot hold account on identical samples.
All three accounts must start with 10000 USDT. Existing account reconciliation,
completed metrics and spot audit checks run before scoring. Main and m=1 daily
rule schedules must be complete against retained hours and match one another.

Immutable rows preserve each observed value, threshold, strictness and result.
Legitimate positive infinite trade profit factor or Calmar remains supported.
Invalid account outcomes are not assigned fabricated scores; the enclosing
experiment report must classify them. This calculator does not certify full
experiment dates, committed registration, source provenance, or accounting and
coverage of all other required training/sensitivity/fixed-rule accounts.

Nine missing-API tests failed before implementation. All 41 focused acceptance,
benchmark-comparison and metrics tests pass, including actual flat accounts,
threshold equality/below-boundary cases, infinite ratios and mismatched account
settings or rule evidence. Independent read-only review reran those 41 and found
no actionable defect. Ruff, mypy and Bandit pass. Full CI and substantive external
review at the exact head remain required before merge.

No criterion, strategy, dependency or data-access change. Codex owns the remaining
experiment assembly and registration. No historical performance claim is made.

Codex Cloud found that an arbitrary completed cash SpotRunner could be supplied
as the benchmark. An explicit regression reproduced that acceptance. The API now
requires the supplied daily spot source and first-portfolio months; it rebuilds
both strategy and hold decisions from that same source, with separate futures
exclusions and their union with spot exclusions for hold. Universes and complete
retained decisions must match. A nonempty synthetic hold with actual fills is
accepted; an arbitrary cash runner, altered signal or altered spot exclusion
calendar is rejected. All 43 focused checks pass. Data provenance remains an
upstream obligation; it is not inferred from this source-consistency check.

A second independent review reproduced a cash-only account carrying copied valid
hold metadata. Decision metadata alone therefore did not close the issue. The
regression failed before the execution-link fix. SpotRunner now retains immutable
snapshots of the targets/reasons actually submitted at every execution hour;
acceptance compares them to the reconstructed frozen hold decisions. Evidence
artifacts persist these snapshots as spot_input rows. This adds no replay.

The cash-only/copied-metadata regression now passes. All 43 acceptance, benchmark,
spot-engine and evidence-writer tests pass, including snapshot immutability and
persisted exact inputs. Independent review found no remaining concrete defect.
Source provenance and deliberate private-state manipulation are not certified.

Further Cloud review identified two comparison mismatches. Spec section 2 applies
spot exclusions to futures decisions too: both decision sources now use the union
of futures and spot exclusions. Main and m=1 accounts must also use identical
futures filter snapshots; the hold retains its separate spot filters. Two failing
regressions reproduced the prior behavior, then passed with these fixes. All 44
focused acceptance/comparison/spot/evidence checks pass, plus lint/types/Bandit.
