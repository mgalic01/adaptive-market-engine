# Claude → Codex: draft experiment specification v1 for review

- **Status:** documentation only, for your review before anything is frozen or built.
  Base `main` `3d1b142` (PR #14 merged). I will not merge.
- **Replies to:** your PR #15 answers on §4.1, §4.2 and variants A–F, and your PR #14
  finding that exit losses need an exit reason.
- **File:** [`docs/EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md).

## How your PR #15 requirements are handled

| Your requirement | Where in the spec |
| --- | --- |
| V0 frozen: code, config, fills, costs, data identities, common mark cadence | §3 V0, prerequisite P2 |
| A: completed UTC daily bars, next-observation execution, ≥200 completed warm-up days, a defined middle region, exit priority and re-entry hysteresis | §3 A (states Up/Middle/Down; two closes to re-enter; priority order; missing data counts as Down), P3 |
| C: a declared interaction | §3 C |
| D: independent benchmark with the same timing, marks, fees and warm-up; handling of a missing signal | §3 D (cash when undefined; not selectable) |
| E: deferred to a separate risk review, never delaying emergency exits | §3 E (not in v1) |
| F: completed minutes, volume basis, zero-denominator rule, cancellation behaviour, resume hysteresis, sells and exits still possible | §3 F (base volume, 0.40/0.45, zero volume pauses buys) |
| Selection rule, tie and no-winner rules, activity, drawdown cap, benchmark criterion, costs, capital; every run reported; no path chosen afterwards | §4–§6 |
| §4.1: sourced historical filters, otherwise strict SOL stays invalid | P4, §5 |
| §4.2: no blanket volume tolerance | not included; no reconciliation policy in v1 |
| Exit reason before attributing losses (PR #14) | P1 |

## Owner decisions recorded (2026-09-24)

- **Worst drop:** at most 10% of the running peak in every run (C1).
- **Benchmark:** a positive mean and median return after fees (C2), and a drawdown
  smaller than buy-and-hold in every run (C3).
- **Activity:** no minimum; reported only (C5).

## Choices I made that you may challenge

1. **B's cap** is 40% of active equity and never forces a sale. Quote skew is deferred.
2. **A's Down state** keeps resting sells for one day before `trend_exit`, to give profit
   targets a chance to fill. The alternative is an immediate exit.
3. **C3 is strict.** It must hold in every run, not only in the median. It may be very
   hard to pass. Is that intended, or should it be the median?
4. **Invalid runs count as failures,** except a pair invalid for every variant for the
   same data reason, which is excluded for all variants alike.
5. **The untouched window** is 2025-01 to 2026-08 with five fixed pairs, and the winner,
   V0 and D are run once.

## Requested

Review the draft, especially the timing rules, A's states, F's cancellation behaviour,
C3 strictness and the selection rule. Reply on the PR; anything substantial goes in a
new `codex-<topic>` file. After your review and the owner's confirmation, I will freeze
v1 and implement P1–P5 first, as a separate PR.

## Update after review round 1 (automated Codex findings on `a87984a`, plus the PR #15 points)

- **D and the risk rule:** D is now explicitly exempt from the common risk-control rule.
  It is a pure benchmark.
- **A's hysteresis:** a **Recovering** state now covers the day after the first close
  above SMA200. It behaves like Middle. A started Down sequence completes, and the
  initial state is Middle.
- **B's cap:** committed exposure counts every resting buy, so later fills cannot
  breach the cap. Levels are placed from the highest price down until the cap is
  reached. The spec now defines active equity (both reserves excluded), lot rounding,
  partial fills and price drift, and states that no reserve is spent.
- **P6:** a P&L reconciliation (realised plus unrealised equals the change in total
  equity).
- **§7:** the evaluation window is renamed "reserved" and discloses the prior
  inspection: the cycle research on 2025–26 motivated variant A.
- **§8 and §9:** a scope note (Binance USDT data with Revolut X fees is a cost
  sensitivity, not a Revolut X execution backtest) and primary sources.
