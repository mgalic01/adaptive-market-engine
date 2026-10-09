# Proposed one-run local V3 executor exception

Index: Proposed local historical replay executor exception; owner decision pending, no run authorized by this document.

The frozen spec's section 9 step 6 routes historical runs through the backtest
workflow. The existing owner exception permits local collection only. This
proposal is therefore a new, explicit procedural exception, not an inference
from the earlier collection approval.

Proposed replacement for this one development experiment: Codex Desktop may
execute the externally reviewed, fully registered V3 invocation on the owner's
machine under `E:/adaptive-market-engine/v3`. Bob reviews the execution task and
the resulting evidence. The task must pin the final reviewed code, completing
registration, unchanged strategy configuration and verified data before launch.
No invocation starts merely because this proposal is approved; all named gates
must first pass and the concrete reviewed command must be ready.

Scope: the fixed ten-coin development inventory through 2024-12, raw manifest
`78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a`,
the reviewed candidate calendar (14 test quarters, pending final configuration
review), and exactly the prescribed 168 training plus 21 other attempts if that
calendar is approved. One fresh invocation directory, no automatic retry, no
parameter tuning, no 2025+ data, no credentials, and no live trading.

Benefit: use the verified local archive cache without transferring it to a
temporary GitHub runner or installing a local Bob runtime. Downside: Codex both
implements and executes the experiment, reducing separation of duties; the PC
must remain available and supply CPU, RAM and disk. Bob's independent task/result
review and pinned evidence improve auditability but do not remove this downside.

Record the owner decision explicitly alongside the final execution task and
completing registration. Strategy/data bytes must not be silently rewritten to
change an executor. Whether an additional candidate annotation is required must
be resolved transparently in that reviewed registration PR before dispatch.

Alternative: retain the existing workflow executor and prepare transfer/verification
of the same archive cache there. Either route retains all review, registration,
failed-attempt and reserved-window rules.
