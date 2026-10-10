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
| PR265 at5253387d434a5a4c8cb2dc64a41f4e848c247c4a | Cross-version synthesis | Reviewed and merged; diagnosis does not authorize a new replay |
| config/datasets/v3-20261009/inventory.manifest.json | Candidate saved futures/funding/filter inventory | Must validate V3.1 date/intersection/flow coverage before registration |

Exact V3.1 configuration/code/data/FX/comparison pins are not registered yet.
No new download, historical replay, reserved data access or live execution follows
from this inventory. Every required arm must be included or the evaluation remains
incomplete. Read-only coverage inspection is separate from execution authorization.

Approved architecture and hypotheses: [specification](superpowers/specs/2026-10-10-v3-1-design.md).
Executable work sequence: [implementation plan](superpowers/plans/2026-10-10-v3-1-combined-system.md).

## Frozen baseline adapter constraints

Code inspection on 2026-10-10 identified these constraints before any V3.1 historical
execution. Preserve native result semantics; an adapter must not scale results or
rename observations to make incompatible evidence appear comparable.

| Baseline | Callable | Constraint |
| --- | --- | --- |
| V3 selector | `trend/orchestration.py::run_walk_forward` | Frozen selection and continuous OOS replay; persistent attempt recorder required |
| Six V3 long controls | `trend/replay.py::replay_window` | Explicit R1L through R6L picks; the broader fixed-rule launcher runs twelve rules |
| V3 spot comparator | `trend/spot_benchmark.py::replay_spot_benchmark` | Volatility-sized and rebalanced long exposure, not literal buy-once hold |
| Literal pair hold | `backtest/replay.py::BuyAndHold` | Pair-level minute replay costs and liquidation-value marks; portfolio allocation must be declared |
| V0, V1 grids and V2 | `backtest/replay.py::replay` | Minute bars and version policy; finite baseline membership remains to be registered |
| V1 comparator D | `backtest/trend_benchmark.py::replay_trend` | Separate trend benchmark policy and minute inputs |

The frozen V3 runner constructs a 10,000 USDT account and the frozen spot account
hardcodes that balance. Their public replay APIs do not accept initial capital.
An approximately EUR100 comparison therefore needs a separately identified,
reviewed capital adapter with synthetic parity at 10,000; proportional scaling of
outputs is invalid because venue minimums and sizing are nonlinear. No such
adapter or capital-specific historical result is claimed here.

V3 records open/post-fill and modeled intrabar extrema, rather than a regular
hourly-close series. V0–V2's hourly sample is taken after the first evaluated
minute's path despite carrying that minute's opening timestamp. These observations
cannot simply be relabeled as one common boundary series. The pending
[observation proposal](superpowers/specs/2026-10-10-v3-1-intrabar-proposal.md)
requires real matching observations or an explicitly incomplete comparison.
Native intrabar diagnostics must also remain available and labeled by version.

Exact baseline membership, capital adaptation, common observation evidence and
literal portfolio hold allocation remain registration work, not permission to
launch an experiment or alter frozen implementations.
