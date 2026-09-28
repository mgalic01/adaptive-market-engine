# Owner-supplied Deep Research report: crypto downtrends (verbatim record)

Index: 2026-09-27: The owner's report as Codex delivered it on PR #106, extracted verbatim with its SHA-256 recorded. Research input only; unverified; never edited. Corrections are in the assessment.

- **What this file is.** The owner's Deep Research report on trading in downtrends, which
  the owner described as "Codex deep research data". It is reproduced **verbatim** below
  the line, exactly as Codex posted it on PR #106
  ([comment 5858596990](https://github.com/mgalic01/adaptive-market-engine/pull/106#issuecomment-5858596990),
  2026-09-27T18:32Z). It was extracted programmatically from that comment, not retyped.
  - SHA-256 of the verbatim part, from its first heading to the end of the file:
    `6c59b23c633596b548d6cbc0277b2e08428b617d68612533e728b1628af6e434`.
- **Status.** Research input only. Its sources, figures and recommendations have **not**
  been verified by Codex, and are assessed claim by claim in
  [the assessment](2026-09-27-claude-deep-research-assessment.md). It is not a
  specification, not approved risk limits and not a merge verdict. Corrections live in
  the assessment; the text below is never edited.
- **Reserved window.** The report refers to 2025–2026 events. Those passages are listed in
  section 4 of the assessment, and none of them enters any strategy selection (D7).

---

# Professional Approach to Crypto Downtrends

Professional and systematic traders prioritize risk control and adapt their tactics to market regimes. In sustained bear markets, the focus shifts to **capital preservation** – often by reducing exposure or hedging – rather than chasing returns. For example, studies of the COVID-19 crash show Bitcoin fell in lockstep with stocks, providing *no safe haven*. Thus, seasoned traders treat crypto like any risky asset: they may stay on the sidelines (cash/stablecoins) or use protective hedges. During milder corrections in a bull market, they might opportunistically buy dips or use low-risk mean-reversion tactics, but always with strict stops and position limits. Key principles include fixed risk-per-trade (often ≤0.5–1% of equity), capped leverage, and **volatility-based sizing**. Volatility-targeted portfolios maintain roughly constant risk by scaling down exposure in high-vol markets, which empirically improves risk-adjusted returns and reduces crash risk. In short, successful downtrend strategies are rule-based, evidence-driven, and emphasize loss control (e.g. stop-losses, small position sizes, and defensive hedges) over high returns. They accept that “the biggest edge may be knowing when *not* to trade”.

# Strategies Comparison

| Strategy                            | Regime(s)        | Setup & Logic | Entry / Exit | Position Sizing          | Evidence & Trade-offs |
|-------------------------------------|------------------|---------------|--------------|-------------------------|-----------------------|
| **Cash/Stablecoins**                | Any (esp. bear)  | Move to cash or stablecoins when market structure breaks (e.g. below 200-day MA, lower lows) to avoid volatility.  | Enter on sustained trend breakdown (e.g. 50% drawdown); stay until signs of recovery. Exit back to spot when trend reverses.  | 0% risk (all in cash). Treat as no-trade mode. | Simplest “do nothing” approach. Outperforms volatile crypto in strong crashes (March 2020, 2022). Zero drawdown by definition. Downsides: no upside capture, inflation risk. |
| **Reduce Exposure / DCA Slowly**    | Deteriorating or choppy | Gradually scale out of spot, or dollar-cost average (DCA) into large-caps only. No leverage. Distinguish *investing* (long-term BTC HODL via DCA) from *trading*. | Partial sell-offs when technicals weaken (e.g. 50DMA crosses 200DMA). Re-enter on rally confirmation. | Risk per trade ~0.5%; limit total crypto exposure (e.g. ≤20–50% in bear). | Maintains some exposure for rebounds. More conservative than full sell. Empirical studies show DCA beats lump-sum by reducing timing risk, though underperforms bull market buy-hold. |
| **Trend-Following (TA)**            | Bear markets      | Follow downward trend by shorting or staying out. Use moving-average (MA) filters. Common rule: go long only if price > 200-day MA; otherwise stay neutral or short.  | E.g. entry = price crosses below 200DMA (go neutral/short), exit = crosses back above 200DMA. Or use 20/50-day MA cross (short when 20<50). | Use low leverage (e.g. ≤2×). Risk ~0.5% per trade. | Academic tests show simple MA rules on crypto often yield similar returns to buy-hold but with lower drawdowns. The cited study found an EMA crossover + walk-forward had *similar returns to buy&hold but ~50% less drawdown*. Advantage: easy rules, reduced drawdown. Failure: whipsaws in choppy markets, large occasional losses if trend reverses. |
| **Moving-Average Filters**         | All regimes      | Only trade (long or short) when price is above/below certain MAs (e.g. 100- or 200-day) or when trend *slope* is positive/negative. Filters reduce false signals. | Example: Only buy Bitcoin when above 200DMA; else stay in cash/stablecoin (or switch to defensive mode). Exit when crossing below MA again. | Conservative leverage (0–1×). Risk <1%/trade. | Empirical evidence (stocks and futures) indicates MA filters capture big moves while avoiding choppiness. In crypto, an MA filter would have kept most position out of 2018 and 2022 crashes. However, it may miss sharp reversals and incur whipsaws in sideways periods. |
| **Volatility Targeting / Scaling**  | All, esp. high vol | Adjust position size to target a fixed volatility (e.g. 10% annual). If realized ATR/vol rises, reduce position size. If vol falls, cautiously increase.  | No specific entry/exit; always on (scaling exposures). Could be applied to any long/short strategy. Exit = reduce position if vol surges. | Position size = (target vol / current vol) × (desired risk). For example, if target vol is 15% but current 30%, half position size. | Improves Sharpe ratio by avoiding oversized bets in volatile crashes. Proven in equities (Moreira & Muir 2017) and risk parity. Drawback: performance drags in quickly rising markets, and target vol choice is arbitrary. |
| **Low-Leverage Short Selling**      | Confirmed downtrends (Bear mode)  | Short assets with minimal leverage (e.g. 2–3× max). Emphasize high-liquidity (BTC/ETH only). Keep tight stops.  | Entry = breakdown below support (e.g. head-and-shoulders or trendline breach). Stop = small cross above resistance. Take-profit = previous support or volatility target.  | Risk per trade 0.25–0.5%. Max leverage ≤3× (preferably ≤2×). | Allows profit from bear moves. But crypto shorts incur heavy costs: **liquidation risk** (tops can spike due to FOMO), **short squeezes** (crowded shorts can get flushed), and adverse funding (negative funding means shorts pay). Example: Oct 2025, many leveraged shorts were auto-deleveraged during the crash. Low leverage mitigates blowouts but can still lose if funding flips or market gaps. No long-side benefit. |
| **Futures/Perpetual Shorting**    | Bear or sharp pullbacks | Short futures with fixed (low) leverage, ideally in a hedged manner. E.g. if long spot portfolio, hedge via futures.  | Regime: strong downtrend (lower highs/lows, negative momentum). Entry: e.g. EMA cross down, RSI oversold relief rally. Stop: above recent swing high or volatility-based band.  | Keep leverage ≤3×; consider *one-sided hedges* rather than large new bets. Risk <1%. | Riskless when hedging spot: the spot gains offset the short. When directional, small bets avoid wipeouts. Funding can hurt: if funding turns negative, holding a short costs money. Must monitor funding and roll contracts. Gaps are limited (no market closures) but sharp moves can liquidate if not sized conservatively. |
| **Hedged Spot Portfolio (Delta-Neutral)** | Any uncertain market  | Hold core crypto (BTC/ETH) but also hold offsetting derivatives to neutralize directional risk. E.g. long 1 BTC spot and short 1 BTC futures.  | Always market neutral (entry=port achieved, re-balance as needed). Exit when conditions improve (remove hedge). | Use whatever position maintains delta-neutral. Risk ~ funding costs. | Eliminates directional volatility (only earns yield). E.g. funding-rate arbitrage (short perp, long spot) historically ~3–7% annual when funding positive. Loss if market suddenly moves and funding flips, or if liquidation occurs. UpShift notes a $100k position lost ~$333 during three-month negative funding in 2026. Best for institutional desks with capital and risk controls. |
| **Protective Puts & Collars**      | Bears, crashes, high-risk | Buy put options on holdings to cap downside. Collars: also sell call to offset put cost. Conservative portfolios (like BTC+ETH long) often use collars.  | Enter when expecting a drop or unsure: e.g. after bull-peak or during steep sell-off. Exit = when market recovers or options expire. Stop = structured by option.  | Limited risk = premium paid + (if collar, + giving up some upside). Position = full spot position size (hedge 100%). | Puts guarantee a floor, valuable in tail risk events. However, crypto options are expensive (volatility high) and often suffer liquidity/spread issues. Collar strategy (long + put, short call) caps both down and up, yielding a known “trading range”. OKX notes collars are *balanced and suitable for conservative investors*. Drawback: complexity, margin for calls, and potential assignments. No academic evidence in crypto (yet), but option theory dictates payoff structure. |
| **Covered Calls (Income)**         | Sideways or mild bull | Hold crypto and sell call options to earn premium, reducing net long cost.  | Best when expecting flat or moderate rise. Entry: buy asset and sell ATM/OOTM call. Exit: buy back call if large move, or let assignment. Stop: if underlying drops, losses cushioned by premium.  | Limit upside by call strike. Risk = downturn beyond premium covered. Position = max one covered call per held asset. | Conservative income strategy: premium offsets losses and no margin risk. OKX calls it *low-risk, conservative*. Works in range-bound markets but severely underperforms in strong rallies (gains capped). Also needs liquid options market. |
| **Mean Reversion (Bear Rallies)**  | Bear-market rallies | Trade short-term bounces (oversold rebounds) within a bear trend. E.g. when RSI oversold and price hits lower Bollinger Band or key support.  | Entry: after sharp drop with oversold signal. Exit: at short-term resistance or fixed target. Stop: cut quick if failure (e.g. 1.5× ATR above entry).  | Very small sizes (risk 0.25%). High frequency possible.  | If well-timed, can eke gains from doomed rallies. But risks: catching knives is dangerous in strong downtrends. Many failures in 2021–22 where bounces didn’t hold. Suitable only for day-traders with stops. Anecdotal only; rarely published quantitatively. |
| **Dip-Buying (Bull Corrections)**  | Bull-market corrections | During healthy bull markets, buy oversold dips on strong assets (e.g. BTC support levels, long-term uptrend intact). Use low-size or staggered entries.  | Entry: bounce off long-term trendline/support (e.g. 50DMA), or RSI <30 in bull context. Exit: next resistance or overbought. Stop: just below support.  | Manage exposure (maybe 2–5 buys per correction), risk ~0.5% each. | Aimed at positive expectancy in bull phases. Historical bull markets show buying after ~20% pullbacks often profitable, but not always. Must ensure bull trend (higher highs). When mistaken for bear, can lead to losses. |
| **Strategy DCA (Investing)**       | Bull or bear with long view | Regularly buy fixed amounts (e.g. weekly) regardless of price, for accumulating positions over time. Distinguished from active trading.  | Periodic (weekly/monthly). No stop. Add small buys more in corrections, less near peaks. | Risk is full allocation; each trade risk ~0.5%. | Good for patient investors. Historically, DCA into BTC over several years yields positive returns, smoothing out volatility. However, during prolonged bear (2018-2019), it underperformed staying in cash. Use selectively – e.g. if belief in long-term bull resumes. |
| **Stop/Trailing/Time Stops**      | All trades        | Always pair entries with stops: fixed stop-loss (e.g. X% of price), trailing stops on wins, or time-stop (exit if target not met by certain time).  | Set at entry. E.g. 1.5× ATR trailing stop. Time-stop: exit after N days without profit.  | Stop defines risk. Trailing lock profit.  | Essential risk control. Studies show rigid stop policies can reduce losses, but too-tight stops can whipsaw. Time-stops prevent stagnation. No direct crypto data, but trading literature (Equity/FX) supports disciplined stops. |
| **Avoid High-Volatility Altcoins** | Any             | Stay concentrated in large-cap, liquid coins during downtrends. High-beta alts often crash hardest.  | No entries in small alts when regime is uncertain/negative.  | 0% (avoid entirely or tiny hedge). | Emphasized by pros: reduce idiosyncratic risk. Many altcoins fell 90%+ in 2018/2022. Unless using market-neutral pairs, best skipped for conservative play.

Each strategy’s **position-sizing** must fit a strict risk framework. For example, risking 0.5% of account per trade with a fixed stop loss limits any one trade’s loss. In a €50k account, 0.5% risk = €250; if setting a stop 5% away, position = €250/0.05 = €5,000 notional. Conservative traders often use ≤2× leverage if any, and maintain a maximum of, say, 10–15 open trades to avoid correlation blows.

**Fees and Slippage:** All quantitative results must account for costs. Deribit and CME fees, exchange spreads, and funding carry (especially for perpetuals) can turn small edges negative. For instance, UpShift finds that funding arbitrage’s return (~3–7% annual) can be wiped out by fees or idle capital during negative-funding stretches. Similarly, covered-call premiums might not offset downward moves if large declines occur.

**Summary:** Robust evidence favors *passive risk control* (staying in cash/hedge) over active bets in downtrends. The most consistently profitable approaches historically have been simple trend filters and volatility scaling – they kept drawdowns small compared to buy-hold. Strategies promising very high win-rates (e.g. “buy the dip” methods) often fail when drawdowns occur. Remember:

> **Expectancy = Win% × AvgWin – Loss% × AvgLoss.**

A system can win 80% of trades yet lose money if its few losses are huge. For example, an 80% win-rate strategy with AvgWin = +1.5% but AvgLoss = –20% has expectancy 0.8×1.5 – 0.2×20 = 1.2 – 4 = –2.8% per trade (unprofitable). Thus, *reward-to-risk per trade matters more than win rate*. This reinforces conservative sizing and strict stops.

# Regime Classification

**A. True Bear Market (Prolonged Downtrend):** Characterized by sustained lower lows and highs, with price below long-term MAs (e.g. 200-day MA trending down). Indicators: the 200DMA is falling and price sits well below it; drawdown from ATH >30–50%; high realized volatility and negative funding rates (more shorts paying longs); large liquidation clusters (like Oct 2025). Confirm with macro signals (e.g. tightened liquidity, crypto market cap breadth weak). Signal example: BTC below its 200DMA and the 200DMA slope negative for weeks. False signals: brief relief rallies can mislead trend traders – require confirmation (e.g. weekly close below MA).

**B. Bull-Market Correction / Downtrend (within Bull):** Short-term declines in an overall uptrend. Price may still be above a rising 200DMA, and higher lows may hold. Indicators: periodic lower highs but still above key MAs (e.g. 50DMA > 200DMA); drawdowns ~10–30%. Volatility spikes moderate. Funding might be high (crowded longs) as markets are still bullish. Use RSI or Bollinger bands to spot oversold dips. Example: in mid-2024, Bitcoin pulled back ~15% but stayed above its rising 200DMA, indicating correction rather than new bear.

**C. Uncertain / Choppy Market:** No clear directional bias. Price oscillates around MAs; higher highs/lows and lower highs/lows alternate. Moving averages flatten. Volatility is moderate but unpredictable, funding near zero. Indicators conflict (e.g. RSI swings mid-range, MACD flat). This demands caution: best to use minimal position sizing or stay in cash/stablecoins. This regime often precedes major moves, so prevent whipsaw by requiring multi-timeframe confirmation and avoiding grid-lock trading.

No single metric suffices: combine several (e.g. 200DMA, volatility, breadth metrics). For instance, one might define “Bear” only when **(Price<200DMA and 200DMA slope<0 and 20-day vol > 5%)**, “Bull Correction” if **(Price>200DMA and 20-day vol > 3%)**, else “Choppy” if conflicting signals. Always beware false signals: for example, a temporary dip below 200DMA might occur during a healthy correction – avoid quickly switching to bear mode on a single signal. Use *hysteresis*: e.g. require price to stay below 200DMA for 4 weeks before declaring bear, or use multiple confirmation indicators.

# Conservative Risk Management

Conservative traders quantify risk strictly. Common rules:
- **Risk per trade:** Typically 0.25–1% of portfolio per setup. For example, risking 0.5% on a €50k account = €250 max loss. A larger trade might use 0.25% if volatility is high.
- **Max portfolio exposure:** Limit total crypto exposure, especially in downtrends (often <50% in bear). E.g. only 20% in altcoins, 30% in BTC/ETH.
- **Max leverage:** Very low. Often none, or at most 2–3× on well-hedged positions. High leverage (10×+) is ruinous if you’re correct but small volatile moves hit stops.
- **Stop-loss limits:** Set hard limits: e.g. *daily loss limit* of 2–5%, *weekly* of 10%, *monthly* of 20%. These stop further trading and force risk review.
- **Drawdown cap:** E.g. if portfolio is down 30–50% (depending on base wealth), stop aggressive trading, shift to shelter mode.
- **Volatility-based sizing:** In high-volatility conditions (crypto often 60–100% annualized), reduce trade size (e.g. by ATR). As noted, ATR-based stops can normalize risk.
- **Reward-to-risk:** Only take trades with at least ~1.5:1 expected R:R (or positive expectancy factor in backtests). This discourages strategies with tiny wins and occasional blowouts.
- **Simultaneous positions:** Limit number of open trades (e.g. ≤10) to avoid systemic exposure.
- **Stay-out conditions:** If too many stop-outs in a row, withdraw from market (drawdown stops). In ultra-tight choppiness (e.g. funding ≈0, indicators flat), prefer stablecoins.

Quantitatively: For a €100k account, 0.5% risk/trade = €500; at 4× leverage that might allow €2,000 position with 25% stop distance (0.25× account = €2500 risk, so this is a bit high; better lower leverage or smaller position). Use `position = (AccountRisk% × Equity) / (stop distance%)`. Example: 0.5% of €100k = €500, stop 5% away ⇒ max position €10k.

# Mode-Switching Decision Tree

1. **Identify Regime (Trend Filter):**
   - If **Bear conditions** (long-term MA down, breakdown confirmed, volatility high) → Enter **Bear Mode**.
   - Else if **Bull Correction signs** (uptrend intact, oversold dip) → Enter **Correction Mode**.
   - Else (mixed signals) → **Choppy/No-Trade Mode**.
   - Use *confirmation rules*: e.g. require 2 of 3 (price<200DMA, negative momentum, negative funding) for Bear mode; require RSI<30+above-200DMA for a dip buy.
2. **Allocate & Strategy:**
   - **Bear Mode**: Minimize spot. Hedge (market-neutral vaults, futures). Trend-follow (short if strict conditions, or stay in stablecoins). Use high stop discipline.
   - **Correction Mode**: Moderate long positions (BTC/ETH). Look for oversold triggers. Buy with stops. Possibly partial hedges.
   - **Choppy Mode**: Largely cash/stable. If trading, focus on mean-reversion or tight-range strategies only. Use very small positions.
3. **Entry Conditions:** Defined per strategy (see table). Must align with current mode. For example, in Bear Mode, only short after a clear breakdown (e.g. weekly close below support) with stop above last high. In Correction Mode, only buy on clear oversold bounce signals.
4. **Stop / Invalidation:** Predefine invalidation points (e.g. if price crosses back through a MA, or a certain volatility breach). On hitting stop, exit and reassess regime. If too many stops triggered, consider switching to choppy or bear mode.
5. **Take-Profit / Exit:** Based on objectives: e.g. for a short, exit at measured move from support; for a buy-the-dip, exit when RSI >50 or after 5–10% gain. Alternatively, use risk-reward (e.g. aim 2× risk). In volatile markets, partial profits may be taken at 1× risk.
6. **Risk Monitoring:** Continuously track drawdowns and max position exposure. If overall portfolio drawdown exceeds limit (e.g. 20%), halt trading and move to conservative posture.
7. **Switching Conditions:** Only switch mode when *predefined triggers* occur. E.g. move from Bear to Choppy only after price rises above 200DMA for 2 weeks and volatility contracts. Use multi-timeframe checks (daily + weekly). Employ cooldown: avoid flipping modes on short-term noise.
8. **Loop:** Re-evaluate regime indicators daily/weekly and adjust mode accordingly.

# Example Position Sizing and Risk

- **Account €10,000, 0.25% risk/trade:** €25 risk. If a trade’s stop-loss is 2%, position = €25/0.02 = €1,250 notional.
- **€50,000, 0.5% risk:** €250 risk. With 5% stop, position = €5,000.
- **€100,000, 1% risk:** €1,000 risk. With 10% stop, position = €10,000.

This illustrates how a fixed **risk percent** translates into trade size depending on stop distance.

**Max Euro Loss per Trade:**
- At 0.25% risk/trade, max loss = €25 per €10k, €125 per €50k, €250 per €100k.
- At 0.5% risk: €50, €250, €500 respectively.
- At 1% risk: €100, €500, €1000 respectively.

These figures guide sizing: e.g. on a €100k account risking 1%, a stop at 4% means max size €25k (since €25k * 4% = €1k).

# Testing Roadmap

To build this conservatively, test ideas in this order:

1. **Passive Benchmarks:** First, assess BTC buy-hold and all-cash returns in each regime period. (Provide baseline drawdown, expectancy=1).
2. **Trend-Filtering:** Test a simple 200DMA rule (long when above, cash when below) on BTC, ETH (2018, 2020, 2022, 2023–25 data). Include slippage. Likely improves drawdown.
3. **MA Crossovers:** Run e.g. 20/50-day EMA cross strategy (with stops) to compare. Use out-of-sample or walk-forward (as in). Validate expectancy formula.
4. **Volatility Targeting:** Apply fixed-vol strategy (e.g. target 10% annual) vs constant exposure. Measure Sharpe and drawdown.
5. **Protected Delta-Neutral (Funding Arb):** Simulate funding arbitrage (long spot, short perp). Compare returns vs flat, include funding history (e.g. use [27] table). Evaluate stability across regimes.
6. **Short-only Strategy:** Small scale tests of low-leverage short (with stops) during known downtrends (2018Q4, 2022Q1). Expect limited use and some wins.
7. **Options Strategies (theoretical):** If data available, model a collar (long 1 BTC, short 0.1 BTC call, long 0.1 BTC put) at 2021 highs. Estimate PnL vs price paths. Understand cost vs protection.
8. **Mean-Reversion:** Backtest RSI/BBands within bear markets for small bounce trades. Use strict filters.
9. **Combine & Regime-Switch:** Finally, simulate a mode-switch system that combines above (e.g. if Bear: use trend-only/hedge; if Correction: buy-dips; if Choppy: cash). Compare equity curves.

At each step, compute **expectancy, max drawdown, Sharpe, profit factor**. Ensure look-ahead bias is avoided (only use data that would have been available at each decision point).

# Strategy Shortlists

**Strongest Evidence / Best Fit (Conservative):**
- **Stablecoins / Cash Positioning:** (Safety-first; zero loss risk).
- **Moving-Average Trend Filter:** (Simple, lowers drawdowns).
- **Volatility-Targeted Sizing:** (Proven to reduce drawdowns and improve Sharpe).
- **Delta-Neutral Funding Arbitrage:** (Good for steady yield if funding high; historically ~3–5% annual).
- **Protective Collars (options):** (Limits losses with small cost; noted as *conservative* strategy).

**Attractive-sounding but Caution / Avoid:**
- **High-Leverage Shorts:** (Very dangerous in crypto’s volatile, 24/7 market – few traders survive without ruin).
- **Unconditional Mean-Reversion:** (“Buy every dip” leads to huge losses in prolonged bear).
- **High-frequency Altcoin trading:** (Small coins spike liquidations and spreads; not for conservative funds).
- **Pure Martingale or grid systems:** (May boast high win-rates but risk catastrophic blow-up).

# Conclusion

A conservative downtrend trading framework is: **(Regime Detection) → (Strategy Selection)** (cash vs hedge vs small long vs small short) → **(Position Sizing)** (small, vol-adjusted) → **(Entry/Stop/Exit rules)** → **(Risk Monitoring)** → **(Mode Re-evaluation)**. Key is *capital preservation*: accept modest returns at best, avoid large drawdowns. Often the best trade is “no trade” (cash) during chaos. Every strategy should be tested for positive expectancy in bad regimes; if not, default to cash.

**Sources:** Authoritative analyses of crypto and trading strategies and risk-management guides underpin these recommendations.  This is Codex deep research data
