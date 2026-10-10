# V3 risk diagnostics implementation plan

> For agentic workers: use superpowers:executing-plans for this task.

**Goal:** report frozen section 8 drawdown dates, realized volatility and cap-day share.

**Architecture:** pure supplied-evidence functions in trend/risk_diagnostics.py;
no account mutation, verdict or data access. Use the existing equity path order
and Decimal60 arithmetic. Report full path indices/kinds when peak and trough
share an hourly timestamp. First worst drawdown wins ties; latest equal peak
before that trough identifies its start. No decline means no episode.

**Tech stack:** existing Python/Decimal/pytest, no dependency.

- [ ] Fail-first tests for ordered same-hour drawdowns, path errors, constant and
  variable volatility, and cap-day denominator including flat decisions.
- [ ] Implement immutable diagnostic values, sample-standard-deviation annualized
  by sqrt(365), consistent with Sharpe. Fewer than two returns: unavailable.
- [ ] Validate complete consecutive decision days and explicit cap evidence;
  missing sizing or cap maps must not silently count as uncapped days.
- [ ] Focused checks, lint/types, independent review, handoff, push and external
  full-head review/CI before merge.

Ruling: diagnostic tie conventions above are reporting choices, not new trading
rules. Their downside is selecting one representative date among equal episodes.
Callers still establish source provenance and full run boundaries.
