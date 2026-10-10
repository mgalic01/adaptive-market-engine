# Proposed single V3 recovery invocation

Index: Owner decision needed for one full unchanged-menu recovery run after reviewed registration; no execution authorized by this proposal.

## Decision requested

**Updated after recovering partial futures diagnostics:** defer the full repeat
while reviewing the [saved-run diagnosis](2026-10-10-codex-v3-partial-diagnosis.md).
The primary account's recovered Sharpe, trade profit factor and Calmar miss
A1–A3. Another unchanged invocation could complete the missing comparisons and
report, but does not improve the strategy. The decision below therefore concerns
report completeness and cost, not an expectation of a passing result. No owner
approval has been inferred from the earlier pending question.

Approve one additional local V3 development invocation on E:, after the corrected
implementation and its new registration/task have passed external review and
required checks. This explicitly extends the local-executor waiver to one recovery
invocation. It does not permit automatic retries after that invocation.

The original permission allows exactly one fresh invocation and no automatic retry:
[owner record](2026-10-09-owner-v3-local-replay.md). That invocation failed. The
standing permission to finish tests and results does not override that narrower
execution boundary.

## Fixed scope

The implementation is main commit
`242faacc0041a00571902320cae95315bf8c551f`, merging
[PR #262](https://github.com/mgalic01/adaptive-market-engine/pull/262).
The correction accepts the zero spot market minimum already allowed by the
snapshot parser and preserves explicit refusal reasons. Its full PR head
`e9fbe0eb058676cf2368fcaaf27bf4ea7387ca5a` received Bob's NO ISSUES and passing
test-and-audit/claim-guard checks. There are 68 passing focused local tests;
the original broader local suite's two harness failures passed separately under
stable-checkout/Git-Bash conditions. See the
[failure diagnosis](2026-10-10-codex-v3-spot-failure.md).

Use the same frozen strategy, 12 candidates, folds, selection, sizing, costs,
thresholds, random seeds, evaluation and A1–A5 rules. Repeat the same complete
189-attempt menu; no outcome is discarded or retuned. Use the existing collected
manifest with SHA-256
`78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a`
and configuration `config/v3-development-run.json` with SHA-256
`49378c3dbce9ad7f29f6fa13ed3714b59d89176ab48881c1633cf7df28f3bdd2`.
Both must match the failed invocation, not merely a new registration's pins.
Use the existing local archives, ending at 2024-12. No fresh market download,
2025+ market-data access, credentials or live trading.

Proposed fresh output: `E:/adaptive-market-engine/v3/replay-20261010-02`.
Proposed fresh logs: `E:/adaptive-market-engine/v3/replay-logs-20261010-02`.
The launcher must refuse pre-existing output and record the reviewed execution
revision, code digest, task/config hashes and runtime inventory before work starts.
These names reserve no run and do not authorize creating another invocation now.

## Why repeat the complete menu

The dispatcher deliberately has no resume path. A partial continuation would need
new reconstruction, provenance and publication logic for combining execution
identities after seeing results. A complete unchanged-menu repetition uses the
reviewed dispatcher and yields one coherent report invocation. Keep the original
failed invocation and all 187 recorded attempts; do not relabel it successful.

Downside: this repeats 186 completed futures calculations. The original invocation
took about 7 hours 12 minutes before failure; the remaining comparisons and
statistics were not timed, so recovery may take longer. The PC must stay awake and
available. Another defect may surface; this proposal does not promise success or
authorize repeated retries. A future resumable runner might save computation, but
building one now adds implementation and audit work before obtaining results.

## Before launch and after completion

1. Finish verification and recording of the original failed invocation. Keep its
   original files and identities; proposed result events require reviewed linkage
   before any canonical-register append.
2. Record the owner's explicit recovery decision. Use a new trial ID; never add a
   second completion to `v3-candidate-space-7`. Commit its registration first
   (commit R), explicitly disclosing known original results and the unchanged
   frozen menu. Then make a later code-pin commit P whose first parent contains
   that identical registration. P inherits the corrected implementation from
   `242faacc0041a00571902320cae95315bf8c551f`; record that unchanged inheritance
   in a documentation marker and verify the full code inventory/digest matches
   that base. P is a new pinning commit, not a claim that the implementation was
   developed after R. Finally commit the new completion and execution task,
   referencing P and the exact manifest/configuration pins above. Validate the
   append-only register and run `check-ready` on the final execution revision.
   Do not directly use the already-merged base as this new trial's code pin:
   its parent cannot contain R. This is disclosed post-failure recovery, not
   preregistration before the original results. Bob must independently review
   this registration treatment, execution task and latest full head before
   launch, as required by the local-executor waiver. Claude review may supplement
   but cannot replace Bob. Required checks must also pass.
3. Run once in a fresh pinned checkout/output with the original isolated launch
   protections. Do not change inputs during execution or retry automatically.
4. Verify receipts and all outcomes; report returns, drawdown, costs, benchmark
   comparisons, A1–A5 and limitations. Generate result events for every started
   recovery run, including failed, invalid or cancelled runs, referencing its new
   completing registration. Obtain Bob's independent review of the results,
   provenance and proposed events; append the reviewed events to the canonical
   trial register and validate it before calling recovery complete. The read-only
   exporter does not perform this append. Obtain required latest-head external
   review and passing checks for the final report/register changes.
   A further engine failure is retained and diagnosed without automatic retry.

Approval of this proposal is approval of the one bounded execution after those
gates; it need not be requested again merely because routine registration and
review preparation finishes later. It grants no reserved-window or live-trading
permission.
