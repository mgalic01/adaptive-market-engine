# Codex: PR #20 uniform-cadence specification review

- Author: Codex; recipients: Claude and Bob; date: 2026-09-25.
- PR: https://github.com/mgalic01/adaptive-market-engine/pull/20
- Base: `3862864d8c87aaf1f2ddb43b8254a4c6dbf69d3d`.
- Reviewed author head: `93986f41b6e22455c947c50c8fb84518efa5c2ae`.
- Status: draft-spec review, final checks and acknowledgment tracked on the PR.

## Findings and disposition

The uniform-cadence convention is acceptable as a declared model, not a claim
about exchange publication or the meaning of future interval fields. Bob explicitly
agreed at [the reviewed head](https://github.com/mgalic01/adaptive-market-engine/pull/20#issuecomment-5834901842).
Claude's earlier startup and duplicate-grace findings are fixed: zero to two
records are unavailable, and every deadline includes the allowance exactly once.
Invalid newest records must not be skipped. Recovery uses the same full predicate.

Codex's final corrections:

1. Require finite rates on all three records. Previously only the newest record
   explicitly rejected non-finite rates; checking older intervals is insufficient.
   Require invalid-rate tests in both older positions, with no substitution.
2. Replace the absolute "never open" statement with the actual detection limit.
   For old settlements at 00:00, 08:00 and 16:00, all carrying interval 8, an
   unobserved change to interval 4 with the 20:00 record missing cannot be detected
   from that history at 21:00. The convention still permits availability until
   00:01 the next day. This agrees with the PR's between-deadline test; it must
   not be described as knowledge of the missing 20:00 record. Add an explicit
   synthetic case. The 4-to-8 case blocks at the earlier old deadline.

## Verification and limits

Independently read the full G section and traced constant cadence, mixed windows,
startup, gaps, invalid records, publication equality, overdue equality and recovery.
The change is confined to draft G text and this indexed review. `git diff --check`
was run before committing. The PR comments record final GitHub quality results;
baseline runtime tests do not establish correctness of an unimplemented strategy.
No runtime implementation or reserved-window data was used in this review.

No known required fixes remain in the reviewed text after these corrections.
No new security findings in this documentation scope; no runtime security audit.
Paper-only scope, risk controls, exits and protected-profit accounting are unchanged.
Rollback is a documentation revert with no migration.

## Next steps

Claude and Bob: confirm the finite-rate symmetry and the explicit detection limit
on this PR. Claude owns implementation and synthetic tests in a subsequent scoped
PR; all boundary cases here must be tested before this feature can be frozen or
used in reserved evaluation. Codex reviews that implementation independently.
This draft-spec merge is neither a full v1 freeze nor permission for reserved data.
Optional improvement: use explicit units and shared predicate names in future
implementation tests to prevent deadline drift.
