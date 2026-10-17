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

*Update, 2026-10-17:* the exact V3.1 pins were registered on 2026-10-15 (trial
`v3-1-registered-1`; [registration review](reviews/2026-10-15-claude-v3-1-registration.md)).
The one registered run, 38703911852, has finished. Verdict: **FAIL**
([verdict record](reviews/2026-10-17-claude-v3-1-verdict.md)). Its result files are kept
on the owner's PC ([run archive](RUN_ARCHIVE.md)). The paragraph below is the
pre-registration state, kept as history.

Exact V3.1 configuration/code/data/FX/comparison pins were not registered yet.
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
*(Note, 2026-10-14: the comparisons below 10,000 USDT are now the `medium` 1,000 and
`small` 100 USDT capitals, which replaced approximately EUR100; see "Owner decision on
the capitals, 2026-10-14".)*

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
  of them are new evidence. *(Note, 2026-10-14: the runs are now at 10,000, 1,000 and
  100 USDT, all new evidence.)*
- **~EUR100 capital ("Reviewed capital adapter").** The unchanged V3 code runs with a
  small subclass that only sets the starting capital, tested to give identical
  results at 10,000 USDT. Exchange minimums then apply naturally at ~EUR100. The
  other baselines take capital as a setting. Outputs are never scaled.
  *(Note, 2026-10-14: the adapter now serves the `medium` 1,000 and `small` 100 USDT
  capitals, which replaced ~EUR100.)*
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

## Owner decisions, 2026-10-12

In chat, after the final review, the owner set the priority: "we do not care about the
fairness... we need a strategy that will make money in the real world... Do what you
think would help us in a real world trading situation, save us money from loss." Claude
decided the two open questions on that basis:

- **Data gaps: keep the protective rule.** A held coin without a price bar is closed at
  its next available bar, and no new entry opens while a holding has no price. This is
  what a live bot does when it loses sight of the market, so the test checks the bot that
  would actually run.
- **Baselines stopped by missing data (narrows the 2026-10-11 decision above).** Only a
  real market event, `liquidation`, is a finished baseline result: frozen at its stop,
  labelled, and it must still be beaten. V3's `no_tradable_position` and
  `leverage_not_restored` arise from masked or untradable coins, and frozen V3 calls them
  terminal invalid-run outcomes. They make that comparison incomplete, so V3.1 can never
  pass by beating a baseline that a data artefact stopped.

## Owner decisions on the test plan, 2026-10-12

Asked by Claude after the second conformance pass, from
`docs/superpowers/specs/2026-10-11-v3-1-registration-proposal.md`; the owner chose:

- **Period.** The owner asked whether the test could start in 2017. Claude explained
  three limits:
  - Binance futures began in September 2019, and on most of the ten coins in 2020.
  - SOL, DOGE and LINK were not listed on Binance in 2017.
  - The V3 selector baseline has picks only from 2021-Q3.

  The owner then chose **pass/fail W1 = 2021-07-01 to 2025-01-01 on ten coins**, plus a
  **reported-only extra window W0**. It starts 2020-03-01, on the eight coins with futures
  then (BTC, ETH, BNB, XRP, ADA, LINK, LTC, TRX), and runs only the `combined` arm, with no
  acceptance. It covers the March 2020 crash.
- **FX pin ("Official end-2024 rate").** The ECB euro reference rate for 2024-12-31 is
  copied from the ECB's publication at registration, with USDT taken at par.
  *(Replaced on 2026-10-14: no capital is in euros any more, so no FX pin is used; see
  "Owner decision on the capitals, 2026-10-14" below.)*
- **V1 hurdles ("All 9 variants").** V3.1 must beat every spec-v1 grid variant, pinned as
  `a b c e f g cg h ch`, each in both path modes.
- **Costs ("Binance standard + double-cost check").** Spot fee 0.10% and futures fee
  0.05%, with 0.05% slippage each, and every run repeated at double costs.
- **Data for W0.** Spot one-minute bars for ADA, BNB, LINK, LTC and TRX, 2020-02 to
  2021-05, are fetched through a second owner-approved Bob task (80 archives). BTC, ETH
  and XRP already have minute bars from 2019-01.

## Owner decision on the capitals, 2026-10-14

Before the code is locked for the run, the owner decided that the one historical run
tests **three starting capitals, all in USDT: 100, 1,000 and 10,000 USDT**. This
replaces the two capitals approved earlier: `research` at 10,000 USDT, and EUR 100
converted at the ECB rate for 2024-12-31 with a pinned FX record ("replaces EUR 100 at
the ECB rate").

- **Capitals.** `research` 10,000 USDT, `medium` 1,000 USDT and `small` 100 USDT, each
  opening at exactly its amount. Within each cost multiple the cells run research, medium,
  then small. Reports label them `research_10000_usdt`, `medium_1000_usdt` and
  `small_100_usdt`.
- **No euro conversion.** No capital uses FX: the FX pin of 2026-10-12 above, its FX
  record and the registration's FX fields are dropped. A registration whose capital names
  an FX rate or record is refused.
- **Still one run.** It is one registration, not three experiments: every cell runs once
  per capital, as it did with two. The run has 324 cells instead of 216 (in all: 120
  V3.1 cells in W1 and 12 in W0, 42 V3, 6 hold and 144 minute cells).
- **Unchanged.** The prepare config, the windows, the coins, the arms and the cost
  multiples.
