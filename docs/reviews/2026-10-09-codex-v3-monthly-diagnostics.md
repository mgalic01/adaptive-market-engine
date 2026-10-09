# V3 monthly return and hosting diagnostics

Index: Implemented frozen monthly return rows, inclusive target counts and hosting-capital proxy on supplied samples; synthetic-only, no historical result or acceptance verdict.

The report needs to show whether returns approach the owner's 20–30% monthly
aspiration without treating it as a promised return or a pass criterion. The new
`trend.monthly.monthly_diagnostics` computes section 8's reported-only quantities
from consecutive 01:00 equity samples plus one terminal observation.

Each month's return shares the first next-month 01:00 sample with the following
month. The first month starts at the run's first sample; the last ends at its
terminal sample. A terminal midnight at the following month's start does not
create an extra month. Partial months preserve their actual endpoints.

Typed rows retain month, timestamps, initial/final equity and Decimal return.
The summary retains the arithmetic mean, inclusive counts at 20% and 30%, and
the hosting-capital estimate `5 / mean`, or None if mean is nonpositive. Arithmetic
uses Decimal60 ROUND_HALF_EVEN. The hosting figure treats USDT returns as EUR,
ignores how exchange order filters change the path at other account sizes, and
does not replace the separate minimum-account-size diagnostic. Own-PC hosting
has zero monetary hosting cost; the reported proxy remains the spec's EUR5 case.

The helper rejects nonfinite equity, nonpositive preterminal equity, gaps,
wrong daily hours and a terminal more than one day after the last daily sample.
It is arithmetic on supplied samples: source provenance, complete account paths,
accounting audits and strategy validity must be checked by the enclosing report.
It cannot issue a whole-experiment verdict or authorize historical dispatch.

Ten new tests failed before implementation. The 37 monthly/metrics checks pass,
as do Ruff and mypy. Independent review found no actionable defect, reran those
37 tests, and checked independence from ambient Decimal settings. Full CI and
exact-head external review are pending at this handoff. No data was fetched, no
dependency added, and no frozen acceptance threshold changed.

Codex owns integration into the eventual full experiment report. Full-size hold,
remaining exposure/cost diagnostics, trial linkage and reviewed historical data
remain separate work.
