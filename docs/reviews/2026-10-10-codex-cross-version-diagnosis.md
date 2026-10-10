# What V0 through V3 teach us about the next strategy

Index: Cross-version saved-evidence diagnosis: grid exit losses, over-restrictive participation, lifetime risk, short-side weakness and selection; V3.1 hypotheses with tradeoffs, not proven improvements.

## Conclusion and scope

We have built reliable mechanisms for measuring trades, but have not established a strategy that combines strong compound returns with the owner's risk budget. The recurring problem is the balance between participation and loss control: the grids collect small gains and surrender them on inventory exits; the mode switcher misses sustained trends; the futures engine participates more but loses heavily through shorts and large portfolio drawdowns.

This analysis reads existing results only. No simulation was restarted, no parameters in a frozen experiment changed, and no 2025+ market data inspected. V3.1 is a new research design, not a retrospective repair of the old verdicts. The owner accepted a 30% portfolio drawdown exit threshold on 10 October; that is a trigger, not a guarantee against overshoot.

Version names need care. V0 is the baseline inside spec v1, whose engine changed over time. The September V0 scorecard is not interchangeable with the October frozen V0 run. V1 is a family of twelve selectable configurations, not one strategy. The structure variant called V2 inside V1 is distinct from the later spec-v2 mode switcher. V3 uses perpetual futures and different dates/capital. Their headline returns are not a fair head-to-head ranking.

## Evidence recovered and checked

Recovered 36 original GitHub Actions result artifacts: 24 V1 files, six scored V2 files, and six later V2 accounting-fix files. Every results.json SHA-256 matches its published manifest. The attached [extractor](../backtests/cross-version-20261010/analyze.py.txt) and [evidence](../backtests/cross-version-20261010/evidence.json) preserve the run identities, row-level contributions and blocking counters. Flat included accounts' grid and exit contributions reconcile to ending profit within 1e-18 using Decimal precision 60. This is arithmetic verification, not a new comprehensive audit of every simulator path.

V1 uses execution `f14451014001b78cf63ac036b5eaad5b126c400c`; scored V2 uses `9a3f9fa0339e012ea5fb242b80ac6602707f57cd`. The later V2 files are retained separately, not pooled as independent evidence. V3 uses the original `4d1e37c0637f8401f3903ea56d036f34c3bfd5cd` execution and the reviewed [partial diagnostics](../backtests/v3-20261010-partial-diagnostics/futures-diagnostics.json) and [return diagnosis](2026-10-10-codex-v3-return-diagnosis.md).

## V0 and V1: small grid wins did not pay for inventory exits

Means across eight included pair/window/path rows per configuration, each starting at 100 quote units. Both intrabar paths are scenarios, not independent market samples. P&L contributions already include the modeled costs: do not subtract the fee column again. These are mean window results, not annual returns or returns of a pooled portfolio.

| Configuration | Net % | Grid sell P&L | Exit P&L | Fees | Time holding inventory % | Completed cycles |
|---|---:|---:|---:|---:|---:|---:|
| V0 | -5.3489 | +19.2170 | -24.5659 | 0.6651 | 11.9777 | 125.125 |
| A trend switch | -5.7596 | +8.7155 | -14.4750 | 0.3449 | 5.9541 | 62.250 |
| B inventory cap | -4.0042 | +13.4884 | -17.4927 | 0.4058 | 11.9777 | 87.125 |
| C combines A+B | -3.9372 | +6.3258 | -10.2630 | 0.2139 | 5.9543 | 43.125 |
| E volume-confirmed exit | -2.8245 | +20.2433 | -23.0678 | 0.5326 | 13.7901 | 128.000 |
| F order-flow entry block | -0.6212 | +14.3138 | -14.9350 | 0.4105 | 10.6133 | 81.250 |
| G funding gate | -5.4503 | +19.0840 | -24.5343 | 0.6643 | 11.9466 | 124.625 |
| H cycle context | -5.2240 | +19.3450 | -24.5690 | 0.6652 | 12.0107 | 126.250 |
| C+G | -4.0525 | +6.1990 | -10.2514 | 0.2137 | 5.9232 | 42.625 |
| C+H | -3.9362 | +6.3268 | -10.2631 | 0.2139 | 5.9571 | 43.125 |
| V2 structure inside V1 | -1.8818 | +19.3353 | -21.2171 | 0.5726 | 12.2117 | 64.250 |
| Full stack | -3.7457 | +5.1292 | -8.8749 | 0.1899 | 5.1154 | 19.000 |

**The failure mechanism:** realized grid gains are an incomplete success metric. V0's average +19.22 grid gains were outweighed by -24.57 inventory-exit losses. Removing fees alone cannot explain that gap. A grid can have many completed profitable cycles while losing on the accumulated inventory left when the range fails.

**What helped in these windows:** F reduced the loss by about 4.73 percentage points relative to V0; structure by 3.47; E by 2.52. None became profitable on average. F uses taker-buy volume from the preceding fifteen completed one-minute bars, with hysteresis; it is not a real order-book imbalance detector. Its improvement is a lead for testing entry quality, not proof that the same threshold works in futures or on daily signals.

**What did not earn its complexity here:** G slightly worsened mean return; H barely changed it. The full stack reduced inventory time and cycles sharply, and was worse than F alone. Combining plausible filters is not automatically additive. A cut entries roughly in half while producing a worse net mean than V0. F and the full stack passed the drawdown criterion, but all selectable configurations failed profitability.

The September V0 scorecard also failed C1 and C2, but its reported mean -4.4309% belongs to an earlier engine/configuration context. It must not be spliced into this matched October comparison. Earlier speculation that ADA inactivity was caused by the cost filter is not established by an individual trade log; it remains a hypothesis.

## V2 mode switcher: too little productive participation, yet excessive cumulative loss

On the scored 2019–2024 window, BTC returned 30.13% and ETH 36.08% on high-first. Cash mode occupied 70.28% and 71.85%; Grid only 2.90% and 2.36%; Uptrend 26.82% and 25.79%. These are mode occupancy, not exact capital exposure. Grid cycles were only 31 and 43 in six years.

BTC's 38,579 decisions while not holding an uptrend position included 140 Uptrend selections; only 48 completed uptrend trades were reported. These are different measures: selections can repeat, fail risk/size checks or execute later. The records do not identify every selected-but-unfilled event, so the difference is not proof of an execution bug.

The actual selector requires daily and four-hour Up states, daily RSI below 75 and other conditions. Grid additionally requires four consecutive RANGE decisions, low ADX, a bounded RSI, narrow width and compatible higher timeframes. At the scored commit, these conditions appear in `src/crypto_grid_bot/strategy/mode_selector.py`. This explains why an otherwise usable price pattern can be denied entry by another layer.

**A concrete missed participation episode:** BTC February 2024 had 696 hourly decisions, zero Uptrend selections and no hours skipped for an existing uptrend holding. RSI alone blocked 260 decisions; daily direction alone blocked 143; four-hour direction alone blocked 120. A strong trend and an overbought reading can coexist. The system treated overbought as an unconditional veto. The evidence establishes blocked participation, not the profit of hypothetical trades. Repeated blocked hours are not 260 independent opportunities.

**The grid accounting remained weak:** BTC grid sells +4.88 plus range exits -9.57 gives about -4.69; ETH +8.27 and -13.15 gives -4.88. This is attribution, not a separately capitalized mode return. BTC stops/fades/range exits together lost 40.33, and ETH 24.06. Removing stops would be unjustified: some may have prevented larger losses.

**Risk recovery hid neither the loss nor the measurement, but permitted further risk:** BTC rebased its runtime reference ten times; ETH nine. Lifetime drawdown still reached 21.91% and 11.02%, exceeding the frozen 10% criterion. Zero hard halts did not mean the lifetime budget was protected. BTC's peak-to-trough episode stretched from February 2021 to November 2024: a slow deterioration can matter as much as a crash.

Fees of 3.38 and 2.68 units over six years and zero recorded blocked-exit frames do not support fees or stuck exits as the dominant explanation. The tiny accounting residual in unscored comparator rows was a reporting defect, not the source of strategy losses.

## V3: directional exposure improved profit but revealed weak shorts and selection

Primary equity rose from 10,000 to 13,446.86 USDT over July 2021–December 2024. CAGR was 8.82%, maximum drawdown 66.82%, Sharpe 0.412. Long lifecycle attribution was +7,369.11, shorts -3,922.24; shorts also lost before explicit fees and funding. Corrected calendar returns: 2022 -47.27%, 2023 +19.85%, 2024 +92.74%. Year returns combine both directions; they do not prove that shorts caused the whole 2022 loss.

The registered fixed-rule comparisons provide stronger evidence than simply deleting losing trades from the primary account:

| Rule | Long/short CAGR % | Long-only CAGR % | Long/short max DD % | Long-only max DD % |
|---|---:|---:|---:|---:|
| R1 | 9.66 | 28.64 | 58.08 | 53.59 |
| R2 | -13.92 | 26.86 | 75.66 | 50.97 |
| R3 | -0.97 | 19.05 | 65.30 | 53.28 |
| R4 | 31.10 | 34.90 | 45.31 | 46.46 |
| R5 | 11.74 | 21.16 | 50.01 | 55.87 |
| R6 | 1.84 | 21.51 | 63.64 | 54.02 |

Every long-only twin had higher CAGR; some had worse drawdown. Even the strongest hindsight candidate missed the new 30% budget. Picking R4L now is selection on observed outcomes, not evidence of a deployable winner. The quarterly selector's primary CAGR was below several fixed rules; whether instability or weak training-score predictiveness caused this requires quarter-level attribution.

Exposure sensitivities also reject a simple leverage solution: multiplier 1 produced 6.81% CAGR/40.29% drawdown; primary multiplier 2 gave 8.82%/66.82%; multiplier 3 gave 6.79%/82.78%. Doubling costs at multiplier 3 left only 1.15% CAGR. The higher setting worsened compounded return despite larger risk.

Net funding was 1,481.82 USDT versus trading fees 442.68. During the worst drawdown, explicit fees and net funding explained only about 6.11% of the equity decline; price exposure dominated. Funding deserves admission checks, but it does not explain away the risk problem.

Flip exits and zero-signal exits had negative lifecycle attribution. However, 239 of 245 losing lifecycles once had positive favorable excursion: that is not a promise that a trailing stop could harvest those marks. Excursions can be tiny, intrabar, before costs or followed by a gap. The largest winners must be retained, not indiscriminately clipped.

## Patterns missed, recognized but blocked, and still unknowable

| Pattern | Supported observation | Next design question |
|---|---|---|
| Range breakdown and stranded inventory | Grid sells positive, net inventory exits more negative in V0/V1 | Can entry quality and inventory allocation reduce the tail loss without starving cycles? |
| Sustained strong trend with high RSI | V2 February 2024 trend participation vetoed | Should strong-trend continuation have its own admission rule rather than a universal RSI ceiling? |
| Slow portfolio deterioration | V2 repeated recovery and long drawdown | Enforce a never-rebased lifetime budget separately from recovery |
| Bear rallies and false breakdowns | V3 shorts lose across all paired comparisons | Test asymmetric short qualification and abstention; exact squeeze events are not yet attributed |
| Correlated asset losses | All ten assets negative between V3's worst endpoints | Cap aggregate and correlated stop risk, not merely individual coins |
| Winners returning gains before exit | Losing lifecycles often had positive excursion | Test executable, lagged trails with costs and winner-retention metrics |
| Rule choice failing to retain an edge | Several fixed V3 rules beat selected primary | Diagnose training-score stability and quarterly contribution before changing selector |

Exact missed trades cannot be recovered from aggregate V0–V2 counters. There is no complete timestamped rejection-to-fill history in those artifacts. They also lack trustworthy order-book queues, liquidation-flow signals and compute/network latency. Do not manufacture those features from candles or classify every hindsight rally as a trade the bot should have taken.

## Changes to take into V3.1, in order

1. **A coherent risk contract:** retain the owner's 30% never-rebased portfolio exit trigger, report overshoot, constrain concurrent stop risk and correlated exposure, and ensure every entry halt still admits protective reductions. Downside: exits can crystallize losses and miss rebounds. Recovery/reentry must be explicit rather than an unnoticed reset.
2. **Separate long and short admission:** keep spot long/grid and futures shorts distinct. Test a short persistence/breakdown gate and an abstain state against a long-only control. Downside: confirmation delays entries and can miss fast crashes. Do not assume a symmetric indicator sign reversal creates a short edge.
3. **Avoid repeating V2's filter pile-up:** the current V3.1 draft's two-day confirmation is a hypothesis, not an established improvement. Compare confirmation with a narrowly specified continuation entry. Record signal available, qualified, risk-approved, order-admissible, submitted and filled as separate stages. Downside: broader admission raises false breakouts; more telemetry costs storage.
4. **Protect profit without suppressing trend winners:** test volatility-based initial stops and lagged ratcheting trails, alongside unchanged exits. Measure net expectancy, tail losses, favorable excursion retained, stop-outs followed by recovery and subsequent missed gains. Downside: tighter exits can destroy positive skew.
5. **Price expected carrying costs into admission:** use only already-published funding observations for forecasts; report forecast errors. Downside: crowded but persistent trends can still pay and may be wrongly rejected.
6. **Make selection earn its place:** compare a frozen simple baseline, each fixed rule and a small preregistered selector. Report training-to-forward rank decay, changes of rule, switch-related exposure and net costs. Downside: switch hysteresis can retain a deteriorating incumbent.
7. **Return to spot grid only with evidence:** preserve F as a useful hypothesis, price spacing against complete round-trip costs, and evaluate inventory liquidation losses together with cycle gains. Do not add a spot grid to V3.1 merely to increase strategy count. Downside: wider spacing reduces fills; tighter caps can remove the small positive edge.

Faster risk response and faster entry signals are separate changes. A price/fill/funding-driven risk loop is appropriate to implement and test synthetically. Faster entry cadence is an experiment requiring adequate historical resolution; neither extra indicators nor AI-generated decisions establish an edge.

## Verification and remaining work

The saved-evidence comparison above is complete at the aggregate level. Event-level causal attribution remains incomplete where old logs never recorded it. No professional-level profit is demonstrated. New rules must be specified before evaluating them, with limited ablations, stress costs, execution constraints and the 30% risk objective. The previously inspected development years can guide research but cannot serve as untouched confirmation.

Next deliverable is a revised V3.1 written design that incorporates these tradeoffs, followed by owner design review, implementation and synthetic tests, external review, and separately authorized historical evaluation. No unregistered parameter sweep or historical retry is authorized by this report. The existing V3 benchmark failure remains a separate incomplete comparison.

Sources: [V1 frozen results](../backtests/2026-10-06-spec-v1-stage-1.md), [V2 verdict and input hashes](../backtests/2026-10-07-spec-v2-verdict.md), [Claude's independent V2 diagnosis checks](2026-10-08-claude-v2-diagnosis-reply.md), [V3 reviewed diagnosis](2026-10-10-codex-v3-return-diagnosis.md). The attached 36-file hash manifest and extractor provide the fresh arithmetic check for V1/V2. This new cross-version report still requires independent review; prior reviews do not cover it automatically.
