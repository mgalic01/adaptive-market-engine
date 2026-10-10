# Owner decision: all-invalid quarter closes despite missing spot bars

Index: Owner approved first available futures fill over waiting for a spot bar; no historical run.

On 2026-10-08 Codex asked which rule should prevail when all twelve training
candidates are invalid and the spot decision bar is missing. Options were closing
at the first available futures fill, or waiting for a valid spot bar. The owner
selected: "Close at first available futures fill (Recommended)".

The disclosed downside was a second explicit exception to the missing-spot-bar
rule. The benefit is avoiding continued exposure when no strategy qualified.
Section 4 now states that exception. Futures-hour deferral and profit, loss and
funding before execution remain unchanged. Existing all-invalid zero-target
behavior implements the selected interpretation; no trading code changes here.

This changes spec bytes. The prior registration pin must not be used for dispatch;
an append-only replacement registration and completing event remain required.
No historical V3 market data was fetched or replayed for this decision.
