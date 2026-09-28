# Claude: trading in downtrends — research, owner decisions, and a starting point for Codex

Index: 2026-09-27: Revision 2, corrected after Codex and six Codex Cloud findings. Owner-requested record for continuing with Codex: research on falling markets, narrowed to what each source studied; the owner's verbatim decisions (futures access on Binance and Kraken; one mode-switching bot with strictly defined rules; finish v1 first); a mirrored-grid idea; candidate variables; open questions. Funding for G surveyed, not fetched; bear-only runs are diagnostics, not edge tests. No code, no spec, no live authority. **2026-09-28:** owner's venue decision recorded: Kraken (CySEC/MiFID II) is the planned live venue; Binance holds no MiCA licence, and its public archives stay the research data only. **2026-09-28:** links PR #137's measured v2 research (§3a): shorting confirmed downtrends lost money on 2017–2024 BTC data, funding paid shorts on net 2020–2024, and the bounce harvest is v1's V0-versus-A question; #137's figures are under review, and whether its runs count as trials is put to Codex and Bob. **2026-09-28, pre-merge corrections:** the 2009 momentum-crash loss is about −69% over two months (not −74%); the June 2022 rally figure is unverified; paper-only operation and the vault are binding rules, not assumptions; #137's figures updated to its revision 2.

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
| **2026-09-28, venue update:** after the ledger's Binance finding, record Kraken as the planned live venue? | **"yes please do"**, after the owner asked me to check whether Binance had resolved its EU issues ("if not binance we can use Kraken perhaps") |

**Venue decision, 2026-09-28 (supersedes "Both Binance and Kraken" for live trading).**

- **Kraken is the planned live venue** for the v2 bot:
  - EU spot trading is licensed under MiCA through Ireland;
  - crypto derivatives are offered through Payward Europe Digital Solutions (CY), CySEC licence 342/17, under MiFID II;
  - perpetual futures are open to retail clients after an appropriateness test.
- **Binance is not a live venue.** As of 2026-09-28 it holds no MiCA licence. It withdrew its Greek application on 2026-06-24, and a French application is pending. It stopped new activity for EU users on 2026-07-01, and serves some existing users under a "reverse solicitation" exemption that ESMA is questioning. HANFA stated on 2026-07-03 that only authorised firms may serve Croatian clients. Sources: [CoinDesk](https://www.coindesk.com/policy/2026/06/26/binance-tells-eu-users-it-will-no-longer-provide-services-after-failing-to-secure-mica-license), [Euronews](https://www.euronews.com/business/2026/06/25/binance-to-halt-crypto-services-across-eu-countries-after-failing-to-secure-mica-approval), [Cryptonomist, 2026-09-08](https://en.cryptonomist.ch/2026/09/08/binance-eu-mica-licensing/), [FinTelegram](https://fintelegram.com/binance-croatia-google-play-mica-app-restrictions/). These are news reports; I found no official Binance statement on EU futures. The owner will check in the app whether new futures positions are still possible, for the record only.
- **Binance's public data stays the research source.** The archives start in 2020-01 (open interest from 2020-09). Using public market history is not trading on the venue.
- **Consequences for v2:**
  1. Kraken's EEA product dates from about 2025, so its own history lies in the reserved window. **Kraken execution is proven by forward paper trading, not by backtest.**
  2. **Leverage:** ESMA's statement of 24 February 2026 says crypto perpetuals offered to retail "likely fall under the CFD category". Where the national regulator applies this, retail leverage is capped at **2×**, with negative-balance protection and a 50% margin close-out. The plan is about 1×, so the cap does not bind. Both protections are welcome. Sources: [ESMA statement](https://www.esma.europa.eu/sites/default/files/2026-02/ESMA35-243228190-8024_-_Public_statement_on_derivatives_in_scope_of_the_CFD_product_intervention_measures.pdf), [Finance Magnates](https://www.financemagnates.com/forex/10x-down-to-2x-has-europe-killed-crypto-perps-even-before-it-started/).
  3. Kraken's fees, minimums and hourly funding (ledger B8–B10) replace Binance's in any v2 cost model for live figures. Backtests on Binance data report both venues' cost assumptions.
  4. The README's "spot only, no futures" rule still needs the owner-approved amendment (D5) before any futures code is written.

**Binding rules, not assumptions (corrected 2026-09-28, after Codex).** Operation
stays paper-only until the owner explicitly approves going live, and the protected
profit (the 50/50 vault) is never traded, in either mode. Both are existing project
rules (`README.md` on the profit split and the protected reserve;
`docs/EXPERIMENT_SPEC_V1.md` §1; `AGENTS.md`), not points awaiting confirmation.

**Assumptions I stated to the owner, not yet confirmed by them:**
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
  decline (spec v1 §7), which biases any short strategy tested on it.

## 3. What the research says

I looked for evidence, not opinions: peer-reviewed work first, then practitioner
research. Industry blogs are marked as weak. **Depth of reading:** I read abstracts
and search summaries, not the full papers, except where a claim is quoted with its
figures. Treat the figures as leads to verify, not as settled facts.

**Revision 3 — checked against the sources.** A research agent read the primary sources,
mostly in full text, and recorded the results in the
[evidence ledger](2026-09-27-claude-evidence-ledger-106.md). The corrections below are marked **"Ledger"**.
**Two sources are withdrawn** because their data lie in the reserved 2025–2026 window.
I checked that point, and the BIS instrument point, myself.

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
   - Crypto studies also find time-series momentum
     ([Le & Ruthbah, Monash](https://www.monash.edu/__data/assets/pdf_file/0011/3744821/Trend-following-Strategies-for-Crypto-Investors.pdf),
     read at abstract depth only).
   - **Ledger:** [arXiv 2602.11708](https://arxiv.org/html/2602.11708v1) is a 70/30
     long/short strategy on 6-hour bars, not long-only. It is a non-reviewed preprint, and
     one of its figures extends into October 2025. The claim "including long-only" now
     rests on Le & Ruthbah alone.
   - **Withdrawn (Ledger).** The public GitHub backtest that "roughly halved the maximum
     drawdown" runs from 2021 to 2026-05, inside the reserved window. It is no longer
     cited, and its figures are not used.
2. **Momentum crashes — the main danger for shorts.** These studies measure
   cross-sectional momentum (winners minus losers, in equities), not the directional
   rule discussed here, but they show the shape of the risk. Such strategies suffer rare,
   severe losses in panic states, *during market rebounds*: a winners-minus-losers
   portfolio lost about two-thirds of its value in two months in 2009: −42% in
   March and −46% in April, about −69% compounded, for a zero-cost long/short US
   equity portfolio
   ([Daniel & Moskowitz](https://www.nber.org/system/files/working_papers/w20439/w20439.pdf)).
   **Corrected (2026-09-28, automated review and Codex Cloud):** the two months compound
   to (1 − 0.423) × (1 − 0.455) − 1 ≈ −68.6%, not the −74% of revision 3, and they do
   not support "three-quarters" (ledger A9).
   **Ledger:** they do not say that volatility scaling "roughly halves" drawdowns. They
   report that *dynamic* scaling roughly doubles the Sharpe ratio, partly by avoiding
   crashes. The claim that risk management "virtually eliminates crashes" is Barroso and
   Santa-Clara's (*Journal of Financial Economics*, 2015).
   Crypto bear markets are full of sharp relief rallies. **Unverified (ledger A26):** BTC
   reportedly rose about 40% from its June 2022 low within about eight weeks. That comes
   from search snippets only; it is checkable from the 2022 development archives.
3. **Volatility targeting.** In the population Moreira and Muir studied — mainly US equity
   factor portfolios (the market, value, momentum, profitability and others) plus a
   currency carry factor, each rescaled monthly by the inverse of the previous month's
   realised variance — taking less
   risk after high volatility raised Sharpe ratios and reduced risk in crises
   ([Moreira & Muir, *Journal of Finance* 2017](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513)).
   **Corrected:** that is not evidence for crypto. Whether it carries over to a
   single-coin crypto strategy, rebalanced daily, is a hypothesis to test, not a finding.
   It remains attractive because crypto downtrends are usually high-volatility. **Spec
   v1 has nothing like it**; B caps inventory, not risk. **Ledger, counter-evidence:**
   Cederburg, O'Doherty, Wang and Yan (*Journal of Financial Economics*, 2020) tested 103
   equity strategies. Realistic out-of-sample volatility management generally did not
   beat the unmanaged portfolios.
4. **Grid trading.** A classic grid has essentially zero expected return without
   directional insight, and in a downtrend it keeps buying into the decline
   ([arXiv 2506.11921](https://arxiv.org/abs/2506.11921)). **Ledger:** that paper
   proves zero expectation only under a symmetric random walk, with no drift and no fees.
   With a 0.08% fee the classic grid's return is negative. It is a non-reviewed preprint,
   with data from 2021-01 to 2024-07. That is exactly the loss mechanism of our V0: forced
   exits of inventory accumulated on the way down.
   **Withdrawn (Ledger), with the exposure recorded.** The 15-minute mean-reversion
   study ([arXiv 2608.21888](https://arxiv.org/abs/2608.21888)) behind "90% of 183
   Binance pairs" and "about 1.3 bp gross" draws its primary sample from **2025-01-01 to
   2026-02-11**, with a holdout from 2026-02-12 to 2026-08-08. That is the reserved
   window. Neither figure is evidence for this project. The same applies to the earlier
   summary at `docs/reviews/2026-09-24-claude-fees-and-strategy-plan.md` line 97, now
   marked there. The point that a grid has no net edge after costs rests instead on the
   fee argument of arXiv 2506.11921 above. The reversal literature also reports that
   daily reversal is mainly an illiquid-coin effect, while large coins show daily
   momentum. **Ledger:** that is Zaremba et al. (*International Review of Financial
   Analysis*, 2021, more than 3,600 coins), confirmed at abstract level; its sample
   period is unknown
   ([*Up or down?*](https://www.sciencedirect.com/science/article/pii/S1057521921002349)).
   The Fairfield paper (Kozlowski et al., 200 coins, 2015–2019) supports only the
   illiquid-coin half.
5. **Funding and carry. Ledger: this point was misattributed.**
   - The BIS study ([*Crypto carry*](https://www.bis.org/publ/work1087.pdf)) measures
     the **basis of dated 1- and 3-month futures** against spot, from 2019 to January
     2022. It does not study perpetual funding.
   - It finds carry averaging about 10% a year. Carry spiked in booms, was sometimes
     negative, and high carry predicted crashes.
   - The mechanism is certain: when the funding rate is negative, shorts pay longs.
     That is a risk for a trend short.
   - **Unverified, and no longer attributed to BIS:** "funding is often negative in bear
     markets", "sharply negative in March 2020", and "extremely negative funding precedes
     relief rallies". All three can be checked from the 2020–2024 Binance funding
     archives once the P8 fetch is approved.
   - **Measured since (PR #137, under review; see §3a).** Binance BTCUSDT funding was
     *net positive* in every year from 2020 to 2024, including the 2022 bear year. A held
     short therefore **received** funding on balance. "Funding is often negative in bear
     markets, so shorts pay" is not supported on this data, and is withdrawn as a
     working assumption. The per-period risk remains: when the rate is negative, a
     short pays. **Corrected:** that is *not* the idea behind v1's variant G. G is a
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

## 3a. Measured on the project's own data: PR #137 (linked, 2026-09-28)

A cloud Claude session (`012TnmLL`), working at the owner's request, published a measured
answer to this topic in
[PR #137](https://github.com/mgalic01/adaptive-market-engine/pull/137),
`docs/reviews/2026-09-28-claude-v2-downtrend-research.md`.
- **Data:** BTCUSDT daily archives 2017-08 to 2024-12, and funding 2020-01 to 2024-12,
  all checksum-verified. The reserved window was never requested.
- **Method:** variant A's own classifier, no look-ahead, and paper costs of 0.28% a
  round trip.

**This file links it rather than copying it:** #137 is the measurement record, and #106
stays the topic hub (owner rule, `AGENT_HANDOFF.md` item 6). What it reports:

1. **Shorting a confirmed downtrend lost money on this data.**
   - Price *rose* in 32 of the 48 Down runs.
   - The compounded gross short over all runs was about −48.1% before fees (#137
     revision 2; revision 1 said −12.2%).
   - Two runs carried everything; the rest was sharp rebounds, the momentum-crash
     shape of §3 point 2.
   - Three published rules, 12-month TSMOM, Donchian 20/10 and dual MA 50/200, **all
     got worse when the short side was added**.
2. **Funding paid the short** in every year from 2020 to 2024, including 2022 (§3
   point 5 above). It was small next to the price moves.
3. **The oscillation inside downtrends is large and needs no futures:** 145 rallies of
   3% or more across 801 Down days. Selling those rallies from spot inventory is what
   the v1 grid already does, so "sell the bounces or step aside?" is **V0 against
   variant A over Down periods**, a comparison spec v1 already schedules.

**#137's recommendation** is the owner's to accept or reject:
- do not build the short/futures engine yet;
- let v1 answer the bounce question;
- if shorts are still wanted, start with a mirrored grid on spot inventory.

**Status and caveats (e0b16be3):**
- **Under review; the arithmetic is settled (updated 2026-09-28).** At `9deb5c3` the
  automated review asked for CHANGES NEEDED on #137's short and cost arithmetic.
  #137's revision 2 (`546f5be`):
  - applied the cost correction (one 0.14% leg per side traded);
  - kept the per-day short factor `2 − S`, which Bob and the automated review both
    confirm is right for a short resized to equity each day;
  - corrected §2's multi-day short ratio, which had flattered shorting. The compounded
    short fell from −12.2% to −48.1%, which strengthens the conclusion.

  The figures quoted here are revision 2's. #137 is not merged, and its PR description
  still carried revision 1's numbers at `546f5be`, so treat them as provisional until
  it merges.
- **One point for Codex and Bob: do these runs count as trials?** #137 says they do not
  count against the trial register. But part 2's rule (PR #93) counts inspected runs,
  and the data-reuse agreement makes agent changes prompted by results registered
  development trials. Six rule variants were run and inspected on development data,
  and they already shape the v2 direction. **I think they count as v2 development
  trials, and should be registered as such.** This is a question, not a finding.
- **It changes the owner's shorting plan.** The owner's brief (§2) wants a bot that can
  also profit in downtrends by shorting. On this data, shorting confirmed downtrends
  destroyed value, and the bounce harvest was the better opportunity. That does not
  settle the plan — one asset, one window, a simplified short model — but it is the
  strongest evidence we have. It should be put to the owner plainly before any v2
  design work.

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
- **Ledger, availability of the Binance BTCUSDT archives:**
  - the perpetual launched on 9 September 2019;
  - klines, funding, mark and index prices start in **2020-01**;
  - trades start in 2019-09;
  - open-interest "metrics" start on **2020-09-01**;
  - **nothing covers 2018.** A perpetual-based test starts in 2020 at the earliest, and
    in 2020-09 if it uses open interest. The 2018 bear market cannot be tested with
    perpetuals from these archives.
- Taker buy volume is a field in Binance klines, including futures klines (Ledger).
- For Kraken, verified separately: its own price, mark and funding history, fees,
  minimums and liquidation rules. Binance evidence does not validate Kraken execution.
- **Ledger, venue facts as of 2026-09-27:**
  - **Kraken EEA:** derivatives through a CySEC-licensed MiFID II entity, open to retail
    clients after an appropriateness test. The BTC perpetual has hourly funding (capped
    at ±0.5% per hour), a 0.0001 BTC minimum lot and at most 10× leverage. Base fees are
    0.02% maker and 0.05% taker.
  - **Timing trap:** Kraken's EEA product dates only from about 2025, so its own history
    lies entirely in the reserved window. Kraken EEA must be verified by forward paper
    trading, or with older Kraken Futures history clearly labelled as a different
    entity.
  - **Binance:** news reports and the Croatian regulator HANFA (3 July 2026) indicate
    that Binance held no EU MiCA licence when the transition ended on 1 July 2026. Only
    licensed or notified firms may now serve clients in Croatia. The owner's "Binance"
    access needs re-checking for new positions. Binance's public archives remain usable
    as research data.

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

**Snapshot as of 2026-09-27, morning.** Since then #92, #93, #99, #101 and #102 have
all merged; each PR records its final state.

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
