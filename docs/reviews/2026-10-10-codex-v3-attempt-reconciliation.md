# V3 failed invocation: all-attempt reconciliation

Index: 187 original attempts verified; 186 completed and one failed; proposed result events await independent linkage review and canonical append.

The original invocation at `4d1e37c0637f8401f3903ea56d036f34c3bfd5cd`
failed. Read-only verification of all saved attempt journals completed on
2026-10-10. No historical replay was started or repeated. The proposed events
record 186 completed runs and one failed holding comparison. Two planned holding
comparisons never started and are not fabricated as cancelled attempts.

“Success” in the event schema means a recorded run completed; it does not mean
the strategy passed. There is no final experiment verdict or publication receipt.
The [partial diagnosis](2026-10-10-codex-v3-partial-diagnosis.md) remains limited
to the saved futures evidence, with A5 unavailable.

## Preserved evidence and linkage

- [Proposal index](../backtests/v3-20261010-failed-invocation/result-proposal-index.json)
  retains each run's identity, status, receipt and journal hashes.
- [Proposed events](../backtests/v3-20261010-failed-invocation/result-proposal-events.jsonl)
  reference `v3-candidate-space-7-complete` and the original configuration,
  manifest and implementation pins. These are not appended to the canonical
  register by this change.
- [Exact export script](../backtests/v3-20261010-failed-invocation/result-proposal-extractor.py.txt)
  used the existing read-only exporter and original committed registration.
  Its mutable worktree imports were checked retrospectively: `git diff
  242faacc0041a00571902320cae95315bf8c551f -- src scripts` was empty. This is an
  operator observation, not a runtime source attestation or an enforced guard.
- [Linkage check](../backtests/v3-20261010-failed-invocation/invocation-linkage-check.json)
  and [source](../backtests/v3-20261010-failed-invocation/verify-invocation-linkage.py.txt)
  compare all 122 retained runtime inventory entries with the original start
  hashes and Git blobs, verify start/end identities, and check task/bootstrap
  hashes. They cannot reconstruct past process memory or authenticate the owner.

The exporter verifies artifact bytes, lengths, record counts and recorded
outcomes. The proposal explicitly retains `caller_proposed_unverified` binding:
directory metadata is not authenticated trial provenance. Bob must independently
review this linkage, including the retained start/end records and original task,
before canonical append. Do not edit the index into claiming authentication.

## Remaining work

Codex owns preparing the canonical append after Bob's review. Validate the
append-only register with all 187 events, retain their original status and
provenance, and obtain latest-head review and passing required checks before
merging that append. Bob owns independent result/linkage review. The owner alone
can authorize a second historical invocation under the
[bounded recovery proposal](2026-10-10-proposed-v3-recovery.md).

The first verification attempt stopped on a caller timestamp-format error after
its scan; the second used the required UTC `Z` suffix and a new analysis output
directory. Both were read-only evidence checks, not experiment retries. Original
experiment artifacts were unchanged.
