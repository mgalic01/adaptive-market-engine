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
cannot simply be relabeled as one common boundary series. The owner-approved
[observation proposal](superpowers/specs/2026-10-10-v3-1-intrabar-proposal.md)
requires real matching observations or an explicitly incomplete comparison.
Native intrabar diagnostics must also remain available and labeled by version.

Exact baseline membership, capital adaptation, common observation evidence and
literal portfolio hold allocation remain registration work, not permission to
launch an experiment or alter frozen implementations.

## Owner decisions on baselines, 2026-10-11

Asked by Claude after a read-only study of the frozen callables (synthetic probes
only, no market data); the owner chose the recommended option each time:

- **Membership ("V3 family, hold, V0–V2 and D").** The full combined arm must beat,
  on compounded net return and on return/maximum drawdown, every one of: the
  unchanged V3 selector, V3's six fixed long-only rules (R1L–R6L), a literal hold,
  the V0, V1 and V2 grids, and comparator D. Each native path mode of a minute-based
  baseline is its own arm. V0–V2 use a read-only recorder around the frozen
  simulator (no trading logic changes; parity with the frozen outputs is tested).
  The frozen V0–V2 evidence ran 100 USDT per coin, so 10,000 USDT and ~EUR100 runs
  of them are new evidence.
- **~EUR100 capital ("Reviewed capital adapter").** The unchanged V3 code runs with a
  small subclass that only sets the starting capital, tested to give identical
  results at 10,000 USDT. Exchange minimums then apply naturally at ~EUR100. The
  other baselines take capital as a setting. Outputs are never scaled.
- **Hold ("Equal cash per coin at start").** The starting capital is split equally
  across the registered coins at the window's first hour, bought once with entry
  costs and held. A coin whose share is below the exchange minimum stays in cash,
  and that is disclosed.
- **Timing ("Accept, disclosed").** V3 books funding a few milliseconds after the
  hour, after that hour's fills, so its hourly state shows that funding one hour
  later; minute-based baselines have no mark exactly at the window end, so the
  final minute's close is their window-end value. Both are labelled native timing
  in the report; nothing is moved or invented.

## Owner decisions after the conformance review, 2026-10-11

Asked by Claude after the spec-conformance review of `0677969` (synthetic probes and
committed dataset manifests only, no market prices); the owner chose the recommended
option each time:

- **Data gaps ("Skip them for everyone").** The committed inventory shows hours with no
  bar inside the candidate window: about ten spot hours on every coin (2021-08, 2021-09,
  2021-12, 2023-03) and 120 futures hours on LTC, SOL, TRX and XRP (2022-02, 2022-04).
  The common comparison schedule is every window hour at which every registered price
  source has its bar. An hour missing from any source is skipped for every arm and
  baseline alike and listed in the report. The 30% drawdown gate still uses every
  available mark. Nothing is interpolated.
- **Baseline that stops early ("Count it as a finished result").** A baseline that ends
  under its own native rules (liquidation, no tradable position, leverage not restored)
  is a finished result, not an incomplete comparison. Its equity is frozen at the stop
  for the rest of the schedule, labelled as frozen, and the full arm must still beat it.
- **Futures fallback ("Only when the minimum is the cause").** A futures long replaces a
  spot entry only when the spot size allowed by the risk and size limits, before any
  cash or capacity already committed, is below the venue minimum. A spot order that is
  too small only because cash or capacity is committed is refused, not moved to futures.
- **Minute bars for the grid ("Fetch it via Bob").** Spot one-minute bars for ADA, BNB,
  DOGE, LINK, LTC, SOL and TRX, 2021-06 to 2024-12, are fetched from Binance's public
  archives through an owner-started Bob task, checksummed, with no 2025+ month. The grid
  component then runs on all ten coins. Until they are registered, a grid run without a
  coin's minute input is incomplete.
