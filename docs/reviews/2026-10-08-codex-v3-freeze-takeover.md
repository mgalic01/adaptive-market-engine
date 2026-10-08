# Codex: V3 freeze takeover and startup-guide corrections

Index: Owner asked Codex Desktop to continue while Claude lacks credits; addresses #209's two Codex P1 startup-guide findings and its P2 freeze-provenance pointer without changing the frozen spec.

Base reviewed: `c7b38186851d3e5512cd807ca36b7c52758a7aa0` (#209).
Named writer for these corrections: Codex Desktop, announced on the open PR.

The review findings are valid. START_HERE still described v1/v2's post-pass shadow
proposal and C1–C6 as current work priorities after introducing v3. Those passages
now distinguish historical rules from v3's A1–A5 and reserved-confirmation gate.
The dispatch summary now requires the completing event, including reviewed manifest
and code pins; an initial candidate-space registration is insufficient. ROADMAP and
START_HERE distinguish reviewed draft #207 from freezing PR #209.

Validation: inspect the complete documentation diff; report checker; whitespace
check; verify the spec file is byte-identical to #209's previous head. No runtime,
configuration, risk rule, dataset or dependency changes. No market data fetched and
no strategy run. No new concrete security finding or compatibility risk.

Next owner: Codex Desktop prepares the trial-register implementation plan and first
register batch after the freeze corrections clear external review. Bob is the
available external reviewer while Claude is unavailable. No freeze-rule changes,
data dispatch, reserved-window access or automatic merge is implied by this handoff.
