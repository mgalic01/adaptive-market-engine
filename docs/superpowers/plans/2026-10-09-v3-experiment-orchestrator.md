# V3 supplied-input experiment orchestration

Purpose: connect the frozen replay menu to durable evidence and the existing
comparison report so the experiment can eventually produce an auditable answer.

Scope: supplied, prevalidated in-memory inputs only. No CLI, data access,
registration claim, historical dispatch, final verdict or full-size hold behavior.
The frozen V3 spec governs; existing registration and owner data gates remain.

1. Test menu wiring, same picks, market-specific filters/hourly inputs, exclusion
   union, recording, and immediate abort on component failure.
2. Implement one runner using the existing walk-forward, sensitivity, fixed-rule,
   recorded spot and report APIs. Use a fresh evidence directory per experiment;
   retain it on failure and never retry automatically.
3. Run focused checks and static checks, then full suite on a stable checkout.
   Request independent review and current-head Bob review before merging.

Review focus: accidental retraining, missing evidence, mixed market inputs,
partial report publication, reused evidence directories and false certification.

Pre-flight: all replay functions accept a shared DailyDecisions and recorder;
spot replay takes its own HoldDecisions, filters and hourly bars. Both decision
sources and the report require the same union of market exclusions.
