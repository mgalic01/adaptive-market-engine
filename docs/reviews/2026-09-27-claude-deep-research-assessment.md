# Claude: assessment of the owner's Deep Research report on crypto downtrends

- **Date:** 2026-09-27. **Author:** Claude, session `e0b16be3`, the #106 branch writer.
- **What was asked.** Codex delivered the owner's report on PR #106 (18:32Z) and asked
  me to:
  - sort its usable claims into **supported, unsupported and conflicting**;
  - verify its source references, arithmetic and claimed guarantees, and their fit with
    the project's current limits;
  - keep the original text separate from any correction.
- **Where the original is.** Verbatim in
  [2026-09-27-owner-deep-research-downtrends.md](2026-09-27-owner-deep-research-downtrends.md).
  Nothing in it is edited; all corrections are here.
- **Method and limits.** I checked every calculation. I checked each claim against three
  things: the sources already in this PR's notes, the repository's own records and
  rules, and well-documented market events. **The report has no bibliography**: its
  sources line reads only "Authoritative analyses of crypto and trading strategies and
  risk-management guides underpin these recommendations". It cites "[27]" and "the cited
  study" without saying what they are. So "unsupported" below usually means *no source
  given and none checked*, not *shown false*. I opened no market data and ran nothing.
- **Reserved window.** The report refers to 2025–2026 events. Section 4 lists every such
  passage. They are excluded from any selection, per D7 as corrected in
  [the response](2026-09-27-claude-downtrend-response.md).

## 1. Bottom line

The report's **framework** is sound and agrees with what Codex and I already wrote:
- capital preservation first;
- regime → mode → size → stop → exit;
- simple trend filters and volatility scaling as the best-evidenced tools;
- expectancy over win rate;
- low leverage;
- cash as a legitimate mode.

It supports the owner's multi-mode target, and it stresses the owner's own requirement:
confirmation, hysteresis and predefined switching triggers.

Its **specifics** are weaker:
- most figures and thresholds have no source;
- several "guarantees" are overstated, including stablecoins and delta-neutral hedges;
- its risk limits are looser than the project's binding ones;
- its testing roadmap conflicts with three agreed rules: no edge claims from bear-only
  windows, no 2025+ data, and no tuning after results.

**Nothing in it can become a v2 rule without its own evidence and registration.**

Worth noting for the owner's shorting goal: the report's own "strongest evidence"
shortlist does **not** include shorting. It lists low-leverage shorts under caution,
with liquidation, squeeze and funding costs. That matches our research. It is a reason
to test carefully, not a veto.

## 2. Claim by claim

### 2.1 Supported

Consistent with the sources in this PR, with repository evidence, or with basic
arithmetic.

| Claim in the report | Why it holds | Source |
| --- | --- | --- |
| In bear markets, professionals prioritise capital preservation over returns | The trend-following evidence and the momentum-crash evidence both point this way | Notes §3; Codex plan (preservation first) |
| Simple trend filters (for example 200-day MA) reduce drawdowns more than they add return | Consistent with the time-series momentum literature and one weak crypto backtest | Notes §3 point 1 |
| Volatility scaling reduces crash exposure and can improve risk-adjusted returns | Holds **in the populations studied** (mainly US equity factors); for crypto it is a hypothesis | Notes §3 point 3, as corrected today |
| Negative funding means shorts pay longs; funding can turn a small edge negative | Matches the mechanics. **Ledger:** not supported by BIS, which studies dated-futures basis, not perpetual funding | Notes §3 point 5 |
| High leverage is ruinous in crypto; relief rallies and short squeezes hurt shorts | Matches the momentum-crash evidence; BTC rose about 40% from its June 2022 low within weeks | Notes §3 point 2 |
| Expectancy, not win rate, decides profitability | 0.8 × 1.5 − 0.2 × 20 = 1.2 − 4 = **−2.8%**; the arithmetic is correct | Checked |
| A mistaken dip-buy in a bear market loses; "buy every dip" fails in prolonged bears | This is our own V0 loss mechanism: inventory bought on the way down, then force-sold | Diagnosis, v1 |
| Avoid illiquid, high-beta altcoins in downtrends | Many altcoins fell 90% or more in 2018 and 2022; v1 trades large pairs only | Well documented |
| Use confirmation and hysteresis before switching mode | Matches a05e63c8's Q1 addition (a minimum time in a mode) and the owner's "CLEAR" rules | Response Q1 |
| Fixed-risk sizing: position = risk ÷ stop distance | Correct formula. Every worked example checks out except one (next table) | Checked below |

**Sizing arithmetic.** Each line was checked.

| Example | Result | Correct? |
| --- | --- | --- |
| €50k × 0.5% = €250; ÷ 5% stop | €5,000 | yes |
| €10k × 0.25% = €25; ÷ 2% stop | €1,250 | yes |
| €100k × 1% = €1,000; ÷ 10% stop | €10,000 | yes |
| €100k × 1% = €1,000; ÷ 4% stop | €25,000 | yes |
| €100k × 0.5% = €500; ÷ 5% stop | €10,000 | yes |
| Max-loss table (0.25%, 0.5% or 1% of €10k, €50k and €100k) | €25–€1,000 | yes, all nine cells |
| "€100k … at 4× leverage … €2,000 position with 25% stop distance (0.25× account = €2500 risk …)" | — | **no.** €2,000 × 25% = €500, which is consistent, but "0.25× account" is €25,000, not €2,500, and leverage plays no part in a risk-per-trade calculation. Muddled; disregard it. |

### 2.2 Unsupported

No source is given, and none is verified here. These can be hypotheses, never inputs.

| Claim | Problem |
| --- | --- |
| "an EMA crossover + walk-forward had *similar returns to buy&hold but ~50% less drawdown*" ("the cited study") | The study is not identified. It is directionally consistent with the trend literature, but the figure cannot be checked. |
| Funding arbitrage "~3–7% annual" (strategy table) and "~3–5% annual" (shortlist) | Two different ranges in the same report, with no source. **Ledger:** my earlier comparison with BIS (about 10–11% a year) mixed instruments. BIS measures the dated-futures basis from 2019 to January 2022, not perpetual funding. The level depends heavily on instrument, period and venue. |
| "in mid-2024, Bitcoin pulled back ~15% but stayed above its rising 200DMA" | **Ledger: contradicted.** BTC briefly fell below $50k on 5 August 2024 while its 200-day average stood near $61.5k (CNBC). Earlier note: unverified. My recollection is that the 2024 declines were larger and dipped under the 200-day average in August 2024. This is within development data (2024), so our own archives could check it. Not done today. |
| Risk figures "0.25–1% per trade", "≤2–3× leverage", "daily 2–5% / weekly 10% / monthly 20%", "10–15 open trades", "R:R ≥ 1.5" | Common practitioner rules of thumb, with no evidence given. They are D6 scenarios, not limits (response D6). |
| Regime thresholds: "20-day vol > 5%" (Bear), "> 3%" (Correction), "stay below 200DMA for 4 weeks", "2 of 3 confirmations" | No source, and the units are ambiguous: daily or annualised volatility? Each threshold would be a registered trial if used. |
| "OKX notes collars are balanced and suitable for conservative investors"; "OKX calls [covered calls] low-risk" | Exchange marketing, not evidence. |
| "Many failures in 2021–22 where bounces didn't hold" (mean reversion) | The report itself calls it "Anecdotal only". |
| "Use [27] table" (testing roadmap, step 5) | Broken citation; nothing to check. |

### 2.3 Conflicting

These conflict with a documented fact, or with a binding project rule or agreed position.

| Claim | Conflict | Resolution |
| --- | --- | --- |
| Stablecoins: "Zero drawdown by definition"; shortlist: "Safety-first; zero loss risk" | Stablecoins have de-pegged: UST collapsed in May 2022, and USDC briefly traded near $0.87 in March 2023 (corrected from $0.88, Ledger). For a euro investor, a USD stablecoin also carries EUR/USD exchange-rate risk. Exchange failure (FTX, November 2022) is a further risk. | "Cash" is the lowest-risk **mode**, not a zero-risk asset. v2 must state which cash asset it holds and its risks. |
| Delta-neutral hedge: "Riskless when hedging spot" | Basis moves, liquidation of the short leg on a spike, funding turning negative (the report itself says this) and counterparty risk make it not riskless. | Treat it as low-directional-risk, with named residual risks. |
| "Drawdown cap: e.g. if portfolio is down 30–50% … stop aggressive trading"; "halt trading" at "20%" | The project's binding limits are stricter: a 3% daily-loss pause, the 8% soft trigger, the 12% hard trigger, and C1 at 10% (owner decision, 2026-09-26). | The project's limits bind. The report's looser figures are not adopted. |
| Leverage "≤2–3×", "≤3×" | The owner-facing assumption in the notes (§2) is leverage near 1×, not yet confirmed by the owner. D3/D5: no futures code without an amendment to the README's spot-only rule. | Open. Any leverage above 1× needs its own owner decision (D5/D6). |
| Roadmap step 6: short-only tests "during known downtrends (2018Q4, 2022Q1)" | Conflicts with **D4**: no edge claim from bear-only windows. It also needs futures history that may not exist for 2018. The BTCUSDT perpetual on Binance reportedly began in September 2019; this is not verified. | Mechanics diagnostics at most. Any edge test uses a complete, registered pre-reserved calendar. |
| Roadmap step 2: test on "2023–25 data" | 2025 is in the **reserved window**. | Excluded. The development calendar ends at 2024-12. |
| "Pure Martingale or grid systems … risk catastrophic blow-up" | Partly consistent (a plain grid has near-zero expectancy, and V0 lost through forced exits). But the v1 grid is not a martingale: fixed sizes, with B's cap and the 3%, 8% and 12% triggers. | Keep the warning. It targets unbounded grids, and v1's defences exist to answer it. |
| Options strategies (puts, collars, covered calls) in the shortlist | Not in the owner's stated venues' scope as far as verified. Contract minimums likely exceed a €100 account. No options data in the project. | Out of scope for now. Revisit only with a verified venue, data and account size. |
| Illustrative accounts of €10k–€100k | The owner's account is €100. At 0.5% risk (€0.50) and a roughly 5-unit minimum order, the stop must be within 10% for even one minimum-size position. At 0.25%, within 5%. Few simultaneous positions are possible. | Any v2 sizing rule must be shown feasible at €100 with the venue's real minimums (Cloud's Kraken finding). |

## 3. What is usable now, as questions for the v2 design

These are hypotheses for the v2 spec. None is decided, and each needs registration
before any run:
1. Three market states — bear, correction, choppy — mapped to the owner's modes (short
   or cash, long grid, cash), with a hysteresis rule. The thresholds are **not** taken
   from the report.
2. Volatility-scaled sizing as a registered candidate, with the population caveat.
3. A weekly loss limit as a possible addition to the daily 3% pause, if the owner wants
   one (D6).
4. A cash mode that names its asset and that asset's risks.

## 4. Passages that refer to 2025–2026 (exposure record for D7)

I read the whole report as delivered. These passages concern the reserved period. None
contains a backtest table.

| # | Where | Text |
| --- | --- | --- |
| 1 | Strategy table, "Low-Leverage Short Selling" | "Example: Oct 2025, many leveraged shorts were auto-deleveraged during the crash." |
| 2 | Regime A, "True Bear Market" | "large liquidation clusters (like Oct 2025)" |
| 3 | Strategy table, "Hedged Spot Portfolio" | "UpShift notes a $100k position lost ~$333 during three-month negative funding in 2026." |
| 4 | Testing roadmap, step 2 | "(2018, 2020, 2022, 2023–25 data)" |
| 5 | Owner's status comment, 15:15Z (not in the report) | "recent 2026 data where reliable", and backtesting listed as a pending step |

**Handling.** None of these enters any v2 rule, threshold or selection, whatever the
owner decides about reading reserved material (D7). If the finished Deep Research
includes backtests over 2025–2026, those results are exposure to be recorded, not
evidence to use.
