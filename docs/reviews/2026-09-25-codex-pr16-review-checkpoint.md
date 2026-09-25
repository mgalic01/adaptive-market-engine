# Codex review checkpoint: prerequisites, experiment rules and Bob handoff

- Author / recipients: Codex → Claude and Bob, 2026-09-25.
- Status: review checkpoint, not PR approval, freeze or permission for reserved data.
- PR #16 reviewed runtime: `99bb81af28fd98e9206668de9515966067ebb80a`.
- Later comment/document/test-name delta: `6eca736466745e705d3416117835c6872281f1f4`.
- Reviewed specification clarifications: `5014025437a7614b03bd0d1a4ae646571bc3ddb9`.
- PR #17 reviewed document: `30648a523a57082f5fed7fe1642bb600aa85bbbf`.
- Main observed: `daae24507af8029a1d52f9e1a0db866550d076f7`.

## Independent verification

At runtime head `99bb81a`, the full Windows pytest suite completed with exit 0.
Ruff lint passed, Ruff formatting checked 91 files, and mypy passed 33 source files.
GitHub quality run 36083340386 passed. These checks are software verification, not
strategy-performance evidence. No independent archive replay is claimed here.
The later changes above do not alter executable runtime behavior.

The basket validation now checks all decision inputs, distinguishes documented
untraded/non-proxy absences from unexplained gaps, and rejects duplicates. Its
regression demonstrates that a missing falling voter can change breadth while the
minimum vote count still passes. No known required runtime fix in this reviewed delta.

The `proxy_hours_*` to `series_hours_*` diagnostic rename affects intermediate branch
outputs; it is not a released schema migration. Consumers of those intermediate
outputs must use the current names. No persisted account migration is involved.

## Specification findings and disposition

The original six findings remain documented in the September 24 specification review.
Later proxy validation, strict/versioned volume checks, C6 baseline inclusion and H
phase/timer clarifications have been reviewed. The common-rule contradiction and C5
denominator ambiguity raised in comment 5826447894 were resolved by `5014025`:

- E may extend only the range deadline; H3 may relax only the new-grid score gate.
  Other risk limits, allocation and protected-profit accounting remain unchanged.
- E uses a frozen reference and fixed six-hour interval, makes one decision per
  episode, never moves the twelve-hour deadline and cannot undo an exit already begun.
- C5 averages duration-normalized per-run cycle rates with equal run weights. Its
  owner-selected threshold remains >=1. ISO-week buckets are reporting only.

E deliberately increases exposure time. Existing risk controls do not guarantee a
realized loss ceiling. It is acceptable as a paper/replay hypothesis in principle;
implementation and selection approval require review of the boundary tests and code.
The six-hour price diagnostic is not an executable counterfactual or selection metric.

## Bob tasks and PR #17

Both task files were approved in comment 5823724852 at
`99996bc7a1c521d6f48762c079d4a68d57d87f2e`, against baseline `c07f856`.
They remain pinned there; this review does not request a restart or different scope.
The trace intentionally lacks timestamps and can establish fill sequence/account
paths, not timing equivalence. Bob's equivalence and P8 reports remain outstanding.

PR #17 was reviewed in comment 5826491451 and is not approved. Its current-status
claims need alignment with the later owner-confirmed record: old criteria are
superseded, SOL remains invalid in the primary matrix, and reserved access requires
explicit owner go. Its 2025 date needs correction or historical explanation.
Unsupported research assertions should be qualified as hypotheses or supported with
primary evidence. Different sources alone do not establish statistical independence.

H is architecturally feasible as replay context and variant entry/range decisions,
with completed daily signals and fixed historical halving constants. G fits a
separate public-archive funding parser and manifest path without a trading adapter.
Historical coverage and archive semantics are still subject to Bob's P8 survey.
Neither feasibility assessment approves implementation or proves profitability.

## Security, limits and next steps

No new credential or live-trading surface was identified in the reviewed runtime
delta. This is a scoped review, not a security certification. Paper-only operation,
default risk/allocation and protected profits must remain intact.

Claude retains implementation ownership. Bob should complete the approved tasks and
correct PR #17, replying on the relevant PR with indexed evidence. Codex must review
those reports and finish the full specification review before any merge/freeze
decision. There is no authorization here to fetch, inspect or run reserved data.

Discussion checkpoints: PR #16 comments 5826409485, 5826447894 and 5826493444;
PR #17 comment 5826491451. This document consolidates those already-posted findings.
