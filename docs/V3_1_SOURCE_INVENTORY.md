# V3.1 source inventory and execution gates

Status: Package A, no historical execution authorized.

| Source | Role | Limitation |
| --- | --- | --- |
| strategy/indicators.py, perception.py | Causal Decimal indicators and completed-time trend states | Reuse primitives, not frozen RSI veto or whole-state history |
| strategy/order_flow.py | F15-minute volume-share hysteresis | Missing minute data disables grid buys |
| trend/filters.py | Saved venue filter parser | Current snapshots are not historical filters |
| trend/account.py, spot_account.py | Accounting reference and frozen comparisons | Separate initial balances must not be added together |
| docs/backtests/2026-10-06-spec-v1-stage-1.md | V1 failure evidence | Matched8-row groups, not independent repeat trials |
| docs/backtests/2026-10-07-spec-v2-verdict.md | V2 evidence | Hours blocked are not causal lost profit |
| docs/backtests/v3-20261010-return-diagnosis/ | Original V3 diagnosis | Invocation incomplete; missing spot comparisons |
| PR265 at5253387d434a5a4c8cb2dc64a41f4e848c247c4a | Cross-version synthesis | Pending external review |
| config/datasets/v3-20261009/inventory.manifest.json | Candidate saved futures/funding/filter inventory | Must validate V3.1 date/intersection/flow coverage before registration |

Exact V3.1 configuration/code/data/FX/comparison pins are not registered yet.
No new download, historical replay, reserved data access or live execution follows
from this inventory. Every required arm must be included or the evaluation remains
incomplete. Read-only coverage inspection is separate from execution authorization.

Approved architecture and hypotheses: [specification](superpowers/specs/2026-10-10-v3-1-design.md).
Executable work sequence: [implementation plan](superpowers/plans/2026-10-10-v3-1-combined-system.md).
