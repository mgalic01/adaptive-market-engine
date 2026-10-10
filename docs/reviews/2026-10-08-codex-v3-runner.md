# V3 continuous runner integration

Index: Continuous synthetic V3 runner connects deferred targets, carried opens,
strict accounting, terminal marks and timestamped equity evidence; data adapter,
excluded-month closures and lifecycle attribution remain outstanding.

Purpose: preserve a faithful continuous account path before evaluating returns.
Branch owner: Codex Desktop. Stacked on the execution PR; never merge into it.

The runner requires consecutive hours, carries the last unmasked open, counts
masked held hours, dispatches pending targets and invokes the frozen hourly order.
Every exception stops the run as an engine failure; invalid strategy outcomes also
stop further processing. Both pre-hour and final-mark accounting audits are exact.
The known -1e-59 residual is explicitly tested as an engine stop, not suppressed.

It retains hourly decision dispatches, marks, audit results, timestamped equity,
running peak/drawdown, 01:00 pre-fill samples and an explicit terminal close sample.
Funding marks retain raw event timestamps; extreme marks are ordered at the final
millisecond of their hour. Finishing accepts supplied last unmasked in-window close
prices, changes no positions and permits no further hours.

Validation: 130 focused synthetic tests pass across runner, execution, pending,
reductions, account, orders, sizing and signals. Ruff and mypy pass. Runner tests
cover masked carry, gap liquidation, consecutive hours, strict audit corruption and
rounding failures, daily samples, peak monotonicity, funding timestamps and terminal
sampling at the 2024 boundary. These are synthetic timestamps, not market reads.

Limitations to resolve before replay:

- The future data adapter must prove complete hours, exclusion eligibility,
  funding completeness and last-close provenance. The current finish API trusts
  its supplied close mapping and does not prove a prescribed window was completed.
- Forced closes before excluded months, decision metadata and lifecycle attribution
  remain absent. This is not yet an experiment entry point.
- In-memory evidence storage will need bounded/streamed serialization for long runs.
- The strict Decimal audit conflict still requires the owner's amendment decision.
  No tolerance is adopted and no historical replay or fetch is authorized here.
- Full CI and independent external review are pending at publication.

No dependency, live exchange integration or frozen strategy change is introduced.
