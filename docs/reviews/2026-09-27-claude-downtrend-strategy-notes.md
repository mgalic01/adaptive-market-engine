# Claude: trading in downtrends — research, owner decisions, and a starting point for Codex

- **Date:** 2026-09-27. **Author:** Claude (Claude Code desktop session `e0b16be3`).
- **Why this exists.** The owner asked me to write down everything learned in today's
  session about trading in falling markets, so that Codex and I can continue the design
  together. Quotes from the owner are verbatim. Everything else is my research and
  reasoning, with sources, and is **input for discussion, not a decision**.
- **Status.** No code, no spec. The owner decided that the current experiment (spec v1)
  finishes first, and this becomes spec v2 afterwards (section 2). Nothing here authorises
  live trading, API keys, futures orders or access to the reserved 2025-01+ data.
- **Revision 2 (2026-09-27, session `a05e63c8`).** Corrected after Codex's review and six
  Codex Cloud findings. Each correction is marked "Corrected" where it applies. My
  point-by-point reply is in
  [2026-09-27-claude-downtrend-response.md](2026-09-27-claude-downtrend-response.md),
  and Codex's position is in
  [2026-09-27-codex-downtrend-research-plan.md](2026-09-27-codex-downtrend-research-plan.md).
  This revision refers to the owner as "the owner" or "they".

## 1. How the topic came up

While discussing the 8% soft-drawdown lockout (PR #102), the owner said:

> "I mean what's the point of trading if not trading ...what do we gain by holding money
> in the account that just sits there"

The owner then asked (via the brainstorming skill):

> "we need to see what our options are when we trade in a falling (bear market) , im not
> really sure how to call it because even bull parts of the market have some downtrends...
> right ? can we perhaps check what are the legit and best options for trading in a
> downtrend market ? im sure there are some strategies that PRO traders use to make
> decisions, that kind of knowledge is precious and we should try to find it or at least
> try to logically come to good conclusions how to profit from and in a downtrend market."

After my first summary, which put shorting aside for now:

> "yes but if shorting is an option then that if done right can provide us with a
> profitable product in a downtrend market. ...."

## 2. Owner decisions, 2026-09-27

| Question I asked | Owner's answer |
| --- | --- |
| Can you trade crypto futures or margin (bet on falls) where you live? | **"Yes, I have access"** |
| Which exchange would the real bot use? | **"Both Binance and Kraken."** |
| How should shorting fit into the bot? | **Option 1, one bot that switches mode** (grid when sideways or up, trend short in clear downtrends, cash otherwise), with: *"the boot really needs to have CLEAR and excellently defined rules on when to switch when to stay out if the rules are not met etc..."* |
| How does this relate to the current experiment (spec v1)? | **"Finish v1, then design v2"** |

**Assumptions I stated to the owner, not yet confirmed by them:**
- paper-only until the owner explicitly approves going live;
- leverage near 1x;
- trend rules fixed in advance on a stated timescale, with volatility-based sizing, a hard
  exit on a trend reversal and a per-trade loss limit;
- building and testing on Binance data, then checking against Kraken's rules before any
  live use. **Corrected:** the funding archives for variant G have been surveyed, not
  fetched. The P8 fetch and manifest are still pending
  (`docs/reviews/2026-09-25-claude-g-funding-signal.md`, "Not yet done"). Checking
  Kraken's rules is not enough either. Each venue needs its own historical data,
  mechanics and paper verification before we can claim it is supported;
- the normal process: a written spec, Codex and Bob review, and registered trials.
  **Corrected:** testing only on the 2018 and 2022 bear markets would select on the
  outcome (section 5, question 5);
- **disclosing** that we already know the reserved 2025–26 window contains a roughly 50%
  decline (spec v1 §7), which biases any short strategy tested on it;
- the protected profit (the 50/50 vault) is never traded, in either mode.

## 3. What the research says

I looked for evidence, not opinions: peer-reviewed work first, then practitioner
research. Industry blogs are marked as weak. **Depth of reading:** I read abstracts
and search summaries, not the full papers, except where a claim is quoted with its
figures. Treat the figures as leads to verify, not as settled facts.

1. **Trend-following / time-series momentum — the strongest evidence.**
   - In **traditional diversified futures** (not crypto, and not a short-only rule):
     positive returns in every decade since 1880 across 67 markets, and good performance
     in 8 of the 10 largest crises
     ([Hurst, Ooi & Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026)).
   - Documented in all 58 liquid futures studied; performs best in extreme markets
     ([Moskowitz, Ooi & Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)).
   - **Corrected (narrowed).** In those futures studies, the crisis performance comes
     from long/short trend portfolios. That makes shorting worth investigating. It is not
     evidence that a crypto short rule would earn it.
   - Crypto studies also find time-series momentum, including long-only
     ([Le & Ruthbah, Monash](https://www.monash.edu/__data/assets/pdf_file/0011/3744821/Trend-following-Strategies-for-Crypto-Investors.pdf);
     [arXiv 2602.11708](https://arxiv.org/html/2602.11708v1)).
   - A simple rule — stay in coins only while BTC is above its 200-day average — roughly
     halved the maximum drawdown in one public backtest. That is a weak, non-reviewed
     source ([GitHub](https://github.com/IsaacDodds/crypto-momentum-backtest)), and it
     shows the rule controls drawdown rather than adding return.
2. **Momentum crashes — the main danger for shorts.** These studies measure
   cross-sectional momentum (winners minus losers, in equities), not the directional
   rule discussed here, but they show the shape of the risk. Such strategies suffer rare,
   severe losses in panic states, *during market rebounds*: a winners-minus-losers
   portfolio lost about three-quarters of its value in a few months in 2009. Volatility
   scaling roughly halves the worst drawdowns
   ([Daniel & Moskowitz](https://www.nber.org/system/files/working_papers/w20439/w20439.pdf)).
   Crypto bear markets are full of sharp relief rallies; BTC rose about 40% from its
   June 2022 low within weeks.
3. **Volatility targeting.** In the population Moreira and Muir studied — mainly US equity
   factor portfolios (the market, value, momentum, profitability and others) plus a
   currency carry factor, each rescaled monthly by the inverse of the previous month's
   realised variance — taking less
   risk after high volatility raised Sharpe ratios and reduced risk in crises
   ([Moreira & Muir, *Journal of Finance* 2017](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513)).
   **Corrected:** that is not evidence for crypto. Whether it carries over to a
   single-coin crypto strategy, rebalanced daily, is a hypothesis to test, not a finding.
   It remains attractive because crypto downtrends are usually high-volatility. **Spec
   v1 has nothing like it**; B caps inventory, not risk.
4. **Grid trading.** A classic grid has essentially zero expected return without
   directional insight, and in a downtrend it keeps buying into the decline
   ([arXiv 2506.11921](https://arxiv.org/abs/2506.11921)). That is exactly the loss
   mechanism of our V0: forced exits of inventory accumulated on the way down.
   Short-horizon mean reversion is real in crypto: at 15-minute horizons it is
   significant on 90% of 183 Binance pairs
   ([arXiv 2608.21888](https://arxiv.org/abs/2608.21888)). **Corrected: the cost caveat.**
   The repository's earlier summary of this study puts the effect at about 1.3 bp gross
   per trade, below realistic costs and adverse selection
   (`docs/reviews/2026-09-24-claude-fees-and-strategy-plan.md`, line 97). Statistical
   significance is not a net, tradable edge. It gives no economic support to the grid or
   to the mirrored grid. The reversal literature also reports that
   daily reversal is mainly an illiquid-coin effect, while large coins show daily
   momentum. That is from search summaries only
   ([Fairfield](https://digitalcommons.fairfield.edu/cgi/viewcontent.cgi?article=1249&context=business-facultypubs),
   [*Up or down?*](https://www.sciencedirect.com/science/article/pii/S1057521921002349));
   verify before relying on it.
5. **Funding and carry.** Cash-and-carry (long spot, short perpetual) earns positive
   funding, mostly in bull markets
   ([BIS, *Crypto carry*](https://www.bis.org/publ/work1087.pdf)). **In bear markets
   funding is often negative, which means shorts pay longs.** It was sharply negative in
   March 2020, so a trend short can bleed funding exactly when it is right. Some sources
   report that extremely negative funding tends to precede relief rallies; this is
   unverified here. **Corrected:** that is *not* the idea behind v1's variant G. G is a
   long-crowding gate. It blocks new grids only when the newest three funding rates are
   all above +0.0005, and low or negative funding never blocks
   (`docs/EXPERIMENT_SPEC_V1.md` §3 G). A negative-funding squeeze rule would be a
   separate, unapproved hypothesis.
6. **Dollar-cost averaging in bears.** It lowers drawdowns and the average entry price
   for a long-term accumulator, but lump-sum wins most of the time. The evidence is
   mostly industry analysis
   ([Amdax](https://medium.com/amdax-asset-management/lump-sum-or-dollar-cost-averaging-42c8f5bb9938),
   [MarketVector](https://www.marketvector.com/insights/mvis-onehundred/buying-bitcoin-after-a-50percent-crash-rarely-works)).
   It is not a trading edge.

**Conclusion I gave the owner.**
- Spot-only, the professional answer to a downtrend is to lose far less (step aside,
  size by volatility, cap inventory) and to be ready for the turn.
- Profiting *from* the fall needs negative exposure. **Corrected (Codex):** shorting is
  not the only instrument. A fully paid long put cannot lose more than its premium, but
  its cost, expiry and execution may make it unsuitable. Puts stay a comparison option;
  they add no scope.
- Shorting done right is where the best "crisis" evidence lives. It must survive relief
  rallies and negative funding.

**Not used:** Daloopa. It covers listed-company financials, not crypto trading, and it
is not authorised in this session.

## 4. The side question: downtrends are not straight lines

The owner asked:

> "downtrends are usually not 100% down ... we can see sell pressures rise and fall even
> in a downtrend, we see some green candles on hourly or daily charts as well... how good
> of an algorithm and what variables would be a good for this kind of downtrend trading?"

The owner is right, and the answer shapes the whole design.

### 4.1 Two timescales, decided in advance

- **A slow timescale decides the mode.** Is this a downtrend at all? Only here may the
  bot be short.
- **A fast timescale decides entries and exits inside that mode.** One *hypothesis*:
  short into bounces (the green candles and relief rallies) and cover into dips.
  **Corrected:** "never chase the lows" was withdrawn as a requirement (response, Q5).
  Entry timing is a separate, pre-registered hypothesis, not a rule.
- The slow rule must be **fixed before testing**, including its lookback. A 12-month
  lookback ignores a two-week dip inside a bull market; a 1-month lookback catches it
  but switches more often and pays more fees. There is no free choice: each lookback is
  a trial.

### 4.2 A natural fit for this codebase: the mirrored grid

Our grid buys dips and sells rallies inside a range. In a **confirmed** downtrend, the
mirror image would:
- **sell (open short) into rallies** at levels above the price;
- **buy back (cover) on dips** at levels below;
- harvest exactly the bounces the owner describes, while the trend works in its favour.

Its failure mode is the mirror of V0's: a relief rally leaves it holding short inventory
opened at lower prices. It therefore needs mirrored versions of the defences already
specified:
- a **short-inventory cap** (the mirror of variant B);
- a **hard exit when the slow trend flips** (the mirror of A's Down sequence);
- an **account-level stop** like today's 12% trigger;
- **volatility-scaled level spacing and size** (section 3, point 3).

### 4.3 Candidate variables

To choose **before** results, and to keep few: every extra variable is another trial,
and another chance to fit noise.

| Purpose | Candidate inputs | Notes |
| --- | --- | --- |
| **Mode: is it a downtrend?** | Daily close vs 50- and 200-day SMA (as in variant A); 3- or 12-month return sign; a structure of lower highs and lower lows | The strongest evidence is for the simple return sign or moving averages; structure rules are harder to define without ambiguity |
| **Entry: is this a bounce worth selling?** | Distance above the 20-day SMA or VWAP; RSI or another short-horizon overbought measure; a rally of *k* × ATR from the last low | This is where the grid levels would sit; weak academic evidence, so test with few variants |
| **Selling pressure** | Taker buy versus sell volume (in Binance klines); volume on up days vs down days | Rising taker-sell share into a rally supports the short; heavy buying warns of a reversal |
| **Crowding and squeeze risk** | Funding rate (archives surveyed for G, fetch pending); open-interest changes | Deeply negative funding means crowded shorts that pay to hold, so no new shorts; positive funding during a bear rally is a better entry |
| **Size and stops** | ATR or realised volatility | Volatility-scaled size (section 3, point 3); stops and trailing exits in ATR multiples |
| **Exit: trend over?** | Close back above the 50-day SMA, or a positive 1-month return; a time stop | A hard, pre-written exit, per the owner's "CLEAR and excellently defined rules" |

**My current view.** Start from the simplest thing the evidence supports: a slow trend
switch plus volatility-scaled sizing. Add the mirrored grid only as a clearly separate,
pre-registered variant. Most of the entry-timing variables have weak evidence, and they
are where overfitting would come from.

### 4.4 Data we would need, and what we already have

- Binance **futures** klines and funding archives. **Corrected:** funding was surveyed
  for variant G, but the P8 fetch and a checksum-pinned manifest are still pending.
  Futures klines would be new.
- Taker buy volume is already a field in Binance klines.
- Open interest may be in Binance's public futures metrics files. **To verify**; not
  checked today.
- For Kraken, verified separately: its own price, mark and funding history, fees,
  minimums and liquidation rules. Binance evidence does not validate Kraken execution.

## 5. Open questions for Codex (and later Bob)

1. **Mode rules.** Which slow trend definition, fixed now? How many modes: grid / short /
   cash, or also "reduce"? What exactly happens at a mode change to open orders and
   inventory?
2. **Short mechanics in the simulator.** Margin, 1x leverage, a liquidation model,
   funding payments, and futures fees. **Corrected:** the funding cadence is data, set
   per venue, instrument and date, not a fixed 8 hours. Spec v1 G already accepts
   intervals of 1, 2, 4 and 8 hours. Is the existing `Account` extendable,
   or does it need a separate engine?
3. **Honesty.** How do we test a short strategy fairly when we know the reserved window
   contains a big decline? Options: count the knowledge as a disclosed bias; hold out
   another period; or rely on 2018 and 2022 only for development and treat the reserved
   run as confirmatory with a stated caveat.
4. **Acceptance.** Do C1–C6 carry over unchanged? C3, "safer than holding", means little
   for a short; what replaces it?
5. **Sequencing inside v2.** First a **paper research test** of trend-shorts on 2018 and
   2022 to see whether the idea has any edge, before designing the full multi-mode bot?
   **Corrected:** a test limited to known bear years cannot show an edge, because even an
   always-short rule looks good there. Such a run only checks the mechanics, given a
   bear market. An edge test needs a preregistered, complete pre-reserved calendar.
   The owner chose the full bot as the target, but a cheap test first could save a lot
   of work.

## 6. Where v1 stands today, for context

- **PR #99:** variant B (the inventory cap) as code, off by default; V0 replay
  byte-identical. Bob found no issues; the automated review approved.
- **PR #92** (fold eligibility, part 1), **PR #93** (trial count, part 2) and **PR #101**
  (DSR return series, part 3): under review.
- **PR #102:** the 8% soft-drawdown lockout.
  - The owner **leans to option C**: reset the peak after a 24-hour cool-off. They want
    a restart after their own review following a 12% stop, and said: *"100 is not a life
    changing amount... 2000 can be but 100 is not"*.
  - Whether to make an exception to their no-changes-after-results rule, the owner will
    "decide after Codex/Bob".
  - **Corrected:** both positions are now posted. Bob gave NO ISSUES on C, with
    clarifications.
    [Codex](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5856718186)
    agrees with changes to drafting C, which does not waive the no-tuning rule.
- The owner's point that trading capital should trade, and that protected profit is never
  touched, carries into v2. I confirmed in `portfolio/profit_vault.py` that half of each
  new profit above the previous high is set aside, can never fund orders, and moves to
  the secured reserve once it reaches the configured `minimum_transfer_quote`.
  **Corrected:** 10 is only the value in `config/default.toml`. Any positive value is
  valid, and tests use 0.1 and 1, so a small-account v2 scenario must state its own.
