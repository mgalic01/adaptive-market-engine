# V3 run-report assembly implementation plan

> Use superpowers:executing-plans, inline and test first.

**Goal:** combine the reviewed diagnostics into one serializable futures-run
report without confusing individual run completion with experiment acceptance.

**Architecture:** a supplied ReplayResult is reconciled and classified before
reporting. Completed runs get performance/monthly/volatility diagnostics;
strategy-invalid runs retain available account/trade/exposure/path diagnostics
but no completed-run metrics. Unknown failures raise. The final experiment
report and committed trial/data linkage remain separate, mandatory work.

**Tech stack:** existing Python, dataclasses, Decimal, JSON and pytest.

- [ ] Fail-first synthetic actual replay test for assembled costs, samples,
  decisions, metrics and JSON; reject unknown or unreconciled outcomes.
- [ ] Assemble immutable report fields, including declared m/cost, exact signed
  residual and reason. Cap-day completeness must match the retained hourly days.
- [ ] JSON uses exact Decimal strings, including explicit Infinity; NaN and
  unsupported values fail, and no nonstandard JSON numbers are emitted.
- [ ] Verify focused integration and independent review; publish handoff and
  require current-head full CI plus substantive external review before merge.

No historical dispatch, acceptance verdict, data fetch or strategy changes.
