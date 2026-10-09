# V3 registered invocation composition

Index: One-shot registered invocation composes reviewed runtime, input, runner, evidence and publication APIs; 26 synthetic tests passed, no historical execution.

Goal: connect the already implemented frozen experiment to reviewed local inputs
without permitting accidental wrong-code dispatch, retries or incomplete results
to masquerade as a finished experiment.

`scripts/v3_dispatch.py` adds `dispatch_registered`, imported only after the
documented explicit-file runtime bootstrap in a fresh `-I -S -B` interpreter.
It rechecks runtime provenance, reads committed registration documents and checks
a hash-pinned committed execution-task JSON against trial/code/config/manifest
and absolute input/output paths before opening any archive. Approval references
are inspectable operator assertions, not authenticated authorization; the operator
must separately establish the reviewed execution task and owner go.

The API exclusively creates one invocation root outside both checkout and
inventory, preserves task bytes/runtime identities, loads and binds inputs, and
calls the existing runner exactly once. The unmasked full-size-hold stream remains
distinct. It reconciles the exact scenario menu/training scores, saves bindings,
rechecks runtime, publishes unchanged uncertified diagnostics and saves the receipt
pin in terminal metadata after a final runtime check. Attempt records live in
`attempts/`, separate from invocation metadata.

Failures and KeyboardInterrupt preserve the output root and available evidence.
No retry or resume is provided. An exception after publication may leave a receipt;
inspect existing evidence rather than restarting. A failed terminal write may leave
partial metadata, which is deliberately not overwritten. Directory durability after
power loss and hostile mutation are not guaranteed. Result proposal/canonical
register append remains a separate reviewed step, including failed/interrupted
invocations. Exit/success of this API is never an A1–A5 verdict.

Validation: 13 initial tests failed because the module was absent. Implementation
exposed and fixed a missing digest-length argument. The final **26 synthetic tests
passed**, covering exact one-call field mapping, hash-matching but wrong task
identities, wrong/missing registration/runtime rejection before archive access,
existing/overlapping output rejection, load/replay/reconciliation/publication
failures, interruption, post-publication drift and partial terminal writes.
The suite includes a fresh Python **3.12.14 -I -S -B** subprocess over a synthetic
Git registration containing the real project sources: preflight, dispatcher import
and origin recheck passed without third-party site initialization or market input.
The pytest driver was Python 3.14.7. No historical replay was performed.

Dependencies: runtime PR255, publication PR256 and reconciliation PR259. Existing
engines and strategy parameters are unchanged. Full CI and Bob review of this
integration remain required. Next: reviewed calendar/configuration, final code pin,
committed completing registration, and a concrete reviewed execution task before
one historical invocation. No execution-task approval or trial completion is
created by this code PR.
