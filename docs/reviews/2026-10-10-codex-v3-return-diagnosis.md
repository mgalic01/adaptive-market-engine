# V3 profit, drawdown and decision-quality diagnosis

Index: Saved primary futures evidence explains costs, turnover, assets, trend proxies and drawdown; proposals are hypotheses, not changes to frozen V3.

## Are we profitable?

In this historical simulation, yes: 10,000 USDT became 13,446.86 USDT from July
2021 through December 2024, a 3,446.86-USDT gain after fees and funding, with
slippage embedded in fills. This is not live earned profit. The terminal wallet
is 11,604.11 USDT and open positions contribute 1,842.75 USDT of unrealized PnL.
Liquidating them would introduce additional costs not represented by that mark.

The return was inadequate for its risk: CAGR 8.82%, maximum drawdown 66.82%,
Sharpe 0.412, trade profit factor 1.235 and Calmar 0.132. Frozen A1â€“A3 are below
their thresholds. The benchmark defect interrupted the overall invocation, so
A5 and the final experiment receipt remain unavailable. Profitability and
passing the experiment are different questions.

Calendar boundaries use saved hourly opening equity at 00:00 UTC on January 1, before that hour’s fills and funding. The first and final periods use the invocation endpoints. Daily 01:00 samples are not calendar boundaries.

| Calendar interval | Net change, USDT | Return on interval opening equity |
| --- | ---: | ---: |
| Julyâ€“December 2021 | +1,039.61 | +10.40% |
| 2022 | -5,218.22 | -47.27% |
| 2023 | +1,155.33 | +19.85% |
| 2024 | +6,470.14 | +92.74% |

The four PnL rows reconcile to total profit. Returns compound; do not add them.
Two of 42 months exceeded 30%, but that does not establish repeatable monthly
20â€“30% profit. The earlier reviewed monthly results remain in PR263.

## Costs, funding and turnover

| Measurement | USDT unless stated |
| --- | ---: |
| Net before explicit fees and net funding, still including slippage | 5,371.37 |
| Trading fees | -442.68 |
| Funding paid | -2,197.12 |
| Funding received | +715.30 |
| Net profit | 3,446.86 |
| Slippage already embedded in fills | 442.68 |
| Gross absolute traded notional | 885,365.21 |
| Fills / position lifecycles | 2,481 / 342 |

Net funding cost is 1,481.82 USDT, approximately 3.35 times trading fees. It is
the larger explicit cost. Gross traded notional is 88.54 times starting equity
over the entire 1,280-day interval; this is turnover, not leverage. Median
lifecycle duration is 204 hours (8.5 days). Mean recorded hourly post-fill gross
leverage is 0.789 and its maximum is 1.809. These are sampled exposure measures,
not peak intrabar leverage or a liquidation-safety guarantee.

The before-cost figure is an accounting decomposition, not a simulated no-cost
strategy. Removing costs would change future sizing and trading. Never deduct
the reported slippage again from net profit.

## Direction, assets and exits

Long lifecycles contribute +7,369.11 USDT; short lifecycles contribute -3,922.24.
Shorts remain negative before explicit fees and funding (-3,845.27 USDT, still
including slippage). Cheap execution alone cannot explain or repair that loss.
Removing shorts would change the path; this is not a long-only counterfactual.

| Asset | Full-window net PnL, USDT |
| --- | ---: |
| BTC | +1,155.56 |
| BNB | +1,093.44 |
| TRX | +1,085.42 |
| SOL | +742.31 |
| XRP | +482.18 |
| ADA | +436.08 |
| ETH | +430.03 |
| DOGE | -406.35 |
| LINK | -440.15 |
| LTC | -1,131.66 |

All assets are retained, including losers. Deleting losing assets after seeing
this table would be selection on the evaluation results.

The 200 lifecycles ending in a direction flip total -4,040.31 USDT; 121 ending
when the signal becomes zero total -3,431.07. Ten ending at a rule change total
+4,302.66; one mandatory excluded-month exit +5.40; ten terminal censored
lifecycles +6,610.17. Each bucket receives the whole lifecycle's PnL, including
earlier partial realizations. The terminal bucket is therefore not identical to
unrealized PnL. Exit labels do not prove that changing an exit would capture the
reported difference.

239 of 245 losing lifecycles had a positive recorded gross favourable excursion.
This supports investigating profit giveback and reversals, but does not prove
that a profitable executable trailing stop existed: excursions use simulated
intrabar extremes, ignore costs in that gross measure, and are known afterwards.

## Regime evidence and its limits

The saved V3 decisions do not contain the requested bull/bear/range/compression
classifier or market-volatility regime labels. We cannot honestly report returns
by those four regimes from this journal alone.

As a descriptive proxy, use each asset's R1 and R2 signs from its latest strictly
earlier daily decision at lifecycle entry. This yields:

| Entry trend proxy | Lifecycles | Full lifecycle net PnL, USDT |
| --- | ---: | ---: |
| Both signals positive | 92 | +3,791.33 |
| Both signals negative | 91 | -788.81 |
| Mixed or neutral | 159 | +444.35 |

These mutually exclusive groups reconcile to total PnL. They are not four-state
market regimes, do not distinguish ranging from compression, and attribute an
entire trade to its entry state even if conditions later change. No new signal
was used to select or replay trades. They support a trend-quality hypothesis,
not a validated entry filter.

## Drawdown episode

The largest episode peaks at 13,896.72 USDT on **7 September 2021, 06:59:59.999 UTC**
and bottoms at 4,611.07 on **26 April 2023, 19:59:59.999 UTC**: a 9,285.65-USDT
decline over 596.54 days. The path first recovers that peak on **3 December 2024,
16:59:59.999 UTC**, then incurs a separate 18.12% drawdown before the end. Ending
equity is below the old September peak again. A statement that the peak was never
recovered during the test would be incorrect.

These timestamps use the frozen favourable/adverse intrabar mark convention,
not observed simultaneous tradable portfolio ticks. The episode's decline is
reconciled by reconstructing signed positions from recorded fills and marking
them at the recorded endpoint prices; this does not independently validate fills.

Every asset contributed negatively between these endpoints. The largest changes
were TRX -1,607.11, LINK -1,434.49, XRP -1,240.45 and DOGE -1,178.42 USDT.
The detailed JSON includes all ten contributions, which sum to the decline.
TRX's full-window profit therefore does not make it a drawdown diversifier.

Fees during this episode were 215.65 USDT and net funding 351.81: together 567.46,
about 6.11% of the decline. The remaining 8,718.19 USDT is the net price-PnL change
under the recorded executions, including embedded slippage. Thus the drawdown
was mainly exposure/price performance, not explicit charges.

## What to improve, and why

These are priorities for a separately designed experiment, not claims that they
will improve returns, and not tuned changes to the frozen V3 run.

1. **Separate short-entry qualification from long entry.** Shorts are the clear
   negative direction in this account even before explicit costs. Test distinct
   bearish persistence/breakdown conditions and an abstain state. Do not simply
   choose the profitable historical long-only rule after seeing the table.
2. **Add portfolio drawdown and exposure controls before raising leverage.** All
   ten assets lose in the worst episode. Test aggregate and correlated exposure
   limits, a daily loss breaker, volatility-based reduction and margin-buffer
   de-risking. Tradeoff: they can miss rebounds or lock in losses; they need a
   declared budget and gap/slippage tests, not a claim to prevent all ruin.
3. **Test reversal hysteresis and protective exits.** Flip/zero-signal buckets
   motivate testing conviction thresholds, transition persistence and volatility
   stops/trails. Tradeoff: fewer false flips can mean slower real reversals, and
   tight trails can cut the rare large winners on which trend systems depend.
4. **Make expected funding part of net opportunity assessment.** Net funding is
   materially larger than trading fees. Use only information available at the
   decision time; distinguish funding forecasts from future realized rates.
   Rejecting crowded trades may also reject strong trends.
5. **Improve selection stability and measure decision quality explicitly.** The
   journal has 1,280 daily decisions and 10 changes of selected rule. Several
   fixed comparisons outperformed the selection, but they are hindsight
   comparisons. Test a small declared selection procedure with nested training,
   turnover/cost penalties and transition diagnostics; avoid an unlimited search.

## Faster decisions versus better decisions

The current model makes daily target decisions and schedules hourly execution;
its candidate selection is quarterly. That is a strategy cadence, not evidence
of slow CPU, network or API handling. The journal contains no measurements that
can establish compute latency as a cause of losses.

For the next design, separate a faster event-driven risk loop from slower entry
signals. Risk checks should react to fresh prices, fills, funding and margin
events; signals should update incrementally from completed information, with
stale-input checks and no lookahead. Benchmark latency before optimizing compute.
Changing the entry timeframe is a new experiment, not a free speed improvement.

IOC, post-only and bounded limit-chasing need explicit acknowledgement, partial
fill, timeout, cancel/replace and duplicate-event handling. Maker orders can miss
fills or face adverse selection. The existing candle evidence cannot validate
historical queue position. Test realistic fill assumptions and stress costs;
do not promise that faster decisions or more features automatically add profit.

## Evidence and verification

Base inspected: main `807ed6dfa8c1c88ea0a5778f21a058efbe1f13e7`. Original execution:
`4d1e37c0637f8401f3903ea56d036f34c3bfd5cd`. Primary run ID:
`a16aa7a730c6476da353dc48ad7e9d81-out-of-sample-m2`.

[Detailed calculations](../backtests/v3-20261010-return-diagnosis/diagnosis.json)
and [standalone extractor](../backtests/v3-20261010-return-diagnosis/diagnose.py.txt)
read only that saved journal, verify its receipt hash/bytes/records, reconcile
lifecycles, fees, funding, each grouping, calendar PnL and both drawdown endpoints
to within 1e-18 USDT using Decimal precision 60. It imports no project code.
Copy the extractor into a scratch directory before running: it writes
`diagnosis.json` beside itself. The original journal remains on E:.

No historical strategy invocation, retuning, fresh market-data fetch or reserved
window access occurred. Raw observed results are preserved. This extension has
not yet received independent review at publication; PR263's review does not
automatically cover new calculations.
