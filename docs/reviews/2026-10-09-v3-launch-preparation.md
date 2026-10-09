# V3 local development execution task

Index: One local development invocation, owner approved; completing registration and calendar require PR261 full-head review before launch.

## Fixed inputs and scope

Implementation commit `f622d4b1b6ffe6d92aaf31cb6b194919301af30b`, digest
`da7192ac43ac90b1c8b5178bce78418d47728f7cd3146f2579581724d556f6f4`
over 122 source/script/dependency files. PR260 passed Bob review and required CI.
PR258 data delivery passed Bob review at `0446368e39e9d160e95ff34c7b29651772c2679e`.
The manifest and config hashes are in the completing event and execution JSON.
No implementation changes are part of this task.

The ten first-month entries in `config/v3-development-run.json` match the manifest
coverage candidates. First test quarter 2021-07, last 2024-10: 14 quarters,
168 training and 21 other prescribed attempts. SOL's first full futures month is
2020-10 and its 2022-11 funding exclusion remains. Warmup and masking rules govern
actual usable observations. These are planned counts, not results.

## Executor exception and registration

The [owner decision](2026-10-09-owner-v3-local-replay.md) explicitly waives only
section 9 step 6's workflow executor for this one local run. Frozen spec and raw
manifest bytes remain unchanged. The candidate-space-7 registration predates
implementation. Its completing event links this decision and this PR; it does
not pretend the executor waiver predates code or data. No new strategy candidate
is created for an operational executor change. Bob must explicitly assess this
registration treatment before dispatch. The original proposal's pending status
is historical and is superseded by the owner decision.

## One-shot procedure

After latest full-head Bob review and required CI, merge PR261 preserving history.
Record its resulting full main SHA as REVISION. Verify that implementation still
matches the completing pin and that no later commits are included. Refuse if any
of the following fresh paths already exists:

- `E:/adaptive-market-engine/v3/replay-checkout-20261009-01`
- `E:/adaptive-market-engine/v3/replay-20261009-01`
- `E:/adaptive-market-engine/v3/replay-logs-20261009-01`

Create a detached Git worktree at REVISION in that checkout path. Verify full
clean status including untracked files, exact HEAD, Python 3.12.14, free disk,
and no competing replay process. Record all commands, timestamps and outputs.
The interpreter is `E:/adaptive-market-engine/v3/python312/Scripts/python.exe`.
The isolated process disables site packages and bytecode, and ignores PYTHONPATH.

Copy the raw committed [bootstrap](2026-10-09-v3-local-launch.py.txt) to the fresh
log directory as `launch.py`; verify its SHA-256 against the Git blob. Invoke:

```text
E:/adaptive-market-engine/v3/python312/Scripts/python.exe -I -S -B E:/adaptive-market-engine/v3/replay-logs-20261009-01/launch.py REVISION
```

Capture stdout/stderr to exclusive fresh log files, record start/end and exit
code. This is the only invocation. Monitor process and newly written attempt
journals without modifying inputs or treating intermediate metrics as selection.
Do not rerun after failure, interruption or ambiguous publication; retain every
artifact and investigate first. This permission does not authorize a retry.

## Results and validation

Check terminal status and verify the report receipt against the registered
documents. Reconcile expected attempts and preserve failed/invalid/cancelled
outcomes. Export proposed trial events separately; do not silently append them.
Review linkage of run evidence to this invocation before canonical append.
Bob reviews the results, arithmetic and A1-A5 conclusions; the publisher emits
uncertified diagnostics, not automatic approval. Report all results and economic
limitations, including an unfavorable outcome. No tuning, 2025+ market data,
exchange credentials or live orders. No historical replay has yet occurred.
