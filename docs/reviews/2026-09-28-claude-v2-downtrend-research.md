# Claude → the owner, Bob and Codex: what a confirmed downtrend is actually worth (spec v2 research)

Index: 2026-09-28 research for spec v2, measured on BTCUSDT development months (daily 2017-08 to 2024-12, funding 2020-01 to 2024-12, all checksum-verified through the project's own fetchers). Three findings that change the v2 plan: **(1) shorting a confirmed downtrend lost money on this data** — price ROSE in 32 of 48 Down runs and the compounded gross short over every run is -12.2% before costs, and adding the short side to each of three published trend rules cut returns and raised drawdown; **(2) funding is a tailwind for a short, not a cost** — Binance BTCUSDT funding was net positive every year 2020 to 2024, including the 2022 bear year, correcting the assumption recorded in PR #106; **(3) the oscillation inside downtrends is large and real** — 1,960% of travel across 801 Down days, 145 rallies of 3% or more, and it can be harvested on spot without futures at all, which makes the owner's "sell the bounces" idea a v1 question the existing V0-versus-variant-A comparison already answers. Recommendation: do not build a short engine yet. No strategy is adopted, no parameter is tuned, and no result here is a registered trial.

- **Date:** 2026-09-28. **Author:** Claude (session `012TnmLL`). **Requested by** the owner
  the same day: "lets start with this", on the three research questions Claude proposed
  (how funding and borrowing are modelled in a paper short; how much of 2018 and 2022 a
  confirmed-downtrend rule catches; what the published trend rules look like as exact code).
- **Owner's framing, verbatim:** "there are two ways to trade downtrends, you can short or
  you can try to catch short bounces and sell in those small mini 'tops' ... What i need
  boot to do is be realy great in discovering and recognizing patterns, and to know the
  trading philosophy that best traders in the world apply depending on the situation."
- **Status: research, not a proposal.** Nothing here changes spec v1, any parameter, any
  acceptance criterion or any dataset. It is evidence for the v2 decisions in
  [the downtrend notes](2026-09-27-claude-downtrend-strategy-notes.md) (PR #106), whose
  §5 questions it partly answers.
- **Data.** BTCUSDT daily archives 2017-08 to 2024-12 (89 months, every one verified
  against Binance's published SHA-256 by `fetch_file`) and BTCUSDT USDⓈ-M funding archives
  2020-01 to 2024-12 (60 months, through `fetch_funding_file`, PR #113). **The reserved
  window was never requested**: the script's month list stops at 2024-12 and
  `development_month` refuses anything later in three independent places.
- **Method.** The classifier is the project's own `simulation.trend_switch.classify_days`,
  so "a confirmed downtrend" means exactly what variant A trades on. No lookahead: a
  signal from the close of day d is acted on at the close of day d+1. Costs are the paper
  defaults (taker 0.09%, slippage 0.05%), so a round trip is 0.28%. The appendix pins the
  script; every table below is its output.

## 1. How much of a bear market the rule catches

| Year | up | recovering | middle | down | unavailable | year close move |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | 7 | 2 | 81 | 213 | 0 | -67.8% |
| 2019 | 188 | 2 | 59 | 116 | 0 | +89.5% |
| 2020 | 281 | 3 | 35 | 47 | 0 | +301.7% |
| 2021 | 249 | 9 | 19 | 88 | 0 | +57.6% |
| 2022 | 0 | 0 | 82 | 283 | 0 | -65.3% |
| 2023 | 291 | 3 | 28 | 43 | 0 | +154.5% |
| 2024 | 288 | 5 | 23 | 50 | 0 | +111.8% |

The rule identifies the two bear years clearly: 213 of 303 classified days in 2018 and 283
of 365 in 2022 are Down, and 2022 has **no** Up day at all. So the answer to "how much of
2018 and 2022 would it catch" is: most of them. The detection is not the problem.

## 2. Shorting those downtrends loses money

Each Down run is traded as a short entered at the close of the day after the run's first
Down day (the first price a live bot could reach) and covered at the close of the day after
its last. 48 runs, 840 Down days, 33.7% of the window.

| Run | Days | Price move | Short gross | Funding | Net |
| --- | --- | --- | --- | --- | --- |
| 2018-03-14..2018-04-19 | 36 | +7.5% | -7.0% | n/a | -7.0% |
| 2018-05-21..2018-07-16 | 56 | -8.3% | +9.0% | n/a | +9.0% |
| 2018-08-07..2018-08-27 | 20 | +12.6% | -11.2% | n/a | -11.2% |
| 2018-11-08..2019-01-05 | 58 | -37.9% | +61.0% | n/a | +61.0% |
| 2019-09-26..2019-10-25 | 29 | +12.9% | -11.4% | n/a | -11.4% |
| 2019-11-15..2020-01-04 | 50 | -13.3% | +15.4% | n/a | +15.4% |
| 2020-03-08..2020-04-15 | 38 | -10.4% | +11.7% | -1.20% | +10.5% |
| 2021-05-21..2021-07-24 | 64 | -5.5% | +5.8% | +0.24% | +6.1% |
| 2021-12-28..2022-02-06 | 40 | -5.6% | +6.0% | +0.63% | +6.6% |
| 2022-04-11..2022-07-18 | 98 | -41.6% | +71.3% | +0.99% | +72.3% |
| 2022-08-19..2022-09-11 | 23 | +5.9% | -5.6% | +0.05% | -5.6% |
| 2022-11-08..2023-01-03 | 56 | +5.8% | -5.5% | +0.17% | -5.3% |
| 2023-08-30..2023-09-18 | 19 | +4.9% | -4.7% | +0.07% | -4.6% |
| 2024-08-03..2024-08-22 | 19 | +10.1% | -9.2% | +0.01% | -9.2% |

Runs under 15 days are omitted from the table; the script prints them all.

**Price rose in 32 of the 48 Down runs.** The compounded gross short across every run is
**-12.2%, before a single fee**. Two runs carry everything: 2018-11 (+61.0%) and 2022-04
(+71.3%). Everything else is a slow bleed of small losses, which is exactly the shape
Daniel and Moskowitz describe: the losses arrive as sharp rebounds inside the decline, and
a short is maximally exposed to them.

This is not an artefact of the 50/200 rule. Section 5 repeats it with two other published
rules and the result is the same in both.

## 3. Funding pays the short, it does not charge it

| Year | Days | Mean daily | Sum over the year | Days the short pays |
| --- | --- | --- | --- | --- |
| 2020 | 366 | +0.0471% | +17.2% | 51 (13%) |
| 2021 | 365 | +0.0839% | +30.6% | 29 (7%) |
| 2022 | 365 | +0.0114% | +4.2% | 72 (19%) |
| 2023 | 365 | +0.0215% | +7.9% | 28 (7%) |
| 2024 | 366 | +0.0327% | +12.0% | 24 (6%) |

Binance's sign convention: a positive rate means longs pay shorts. BTCUSDT funding was
**net positive in every year, including the 2022 bear year**, so a held short *received*
roughly 4% to 31% a year. Even in 2022 only 19% of settlements went the other way.

**This corrects the downtrend notes** (PR #106), which recorded "negative funding in bear
markets, where shorts pay longs" as a reason to expect a tailwind from shorting. The
tailwind exists but points the other way round from the note's reasoning, and it is far too
small to matter: over the Down runs themselves, funding contributed between -1.20% and
+0.99%, against price moves of tens of percent. **Funding is not why a short wins or loses
here.** A paper short would still need it modelled, because it is real money at every
8-hour settlement, but no short strategy is rescued by it.

What this research does *not* cover, and a paper short would still need: the borrow or
margin interest on the position, the liquidation price and maintenance margin, and the fact
that a short's loss is unbounded. None of those are in the archives; all three are engine
work.

## 4. The oscillation inside downtrends is large

"Travel" is the sum of absolute day-to-day close moves inside a run; "net" is the run's
total move. A ratio above 1 means price moved back and forth more than it finally fell.

| Run | Days | Net | Travel | Travel / net | Rallies >=3% | Biggest rally |
| --- | --- | --- | --- | --- | --- | --- |
| 2018-03-14..2018-04-19 | 37 | +7.5% | 125% | 16.7 | 10 | 16.8% |
| 2018-11-08..2019-01-05 | 59 | -37.9% | 205% | 5.4 | 11 | 10.9% |
| 2020-03-08..2020-04-15 | 39 | -10.4% | 184% | 17.6 | 11 | 16.2% |
| 2021-05-21..2021-07-24 | 65 | -5.5% | 222% | 40.2 | 14 | 12.0% |
| 2022-04-11..2022-07-18 | 99 | -41.6% | 282% | 6.8 | 18 | 10.8% |
| 2022-09-13..2022-10-03 | 21 | +0.5% | 38% | 68.4 | 4 | 5.1% |
| 2022-11-08..2023-01-03 | 57 | +5.8% | 76% | 13.0 | 5 | 10.5% |

Across all 28 runs of five days or more: **801 days, 1,960% of travel, 145 rallies of 3% or
more**, and a mean "biggest rally inside the run" of 9.2%. Even the worst decline in the
window, 2022-04 to 2022-07, travelled 282% to fall 41.6%, with 18 separate rallies of 3% or
more.

So the owner's second instinct is the one the data supports: **the raw material for
harvesting bounces is abundant, while the raw material for riding the decline is two events
in seven years.**

## 5. The published rules, written exactly and run on our data

Three rules, each acted on one day late, each paying 0.28% a switch, funding applied to
short days from 2020. Window 2018-08-18 to 2024-12-31, 2,328 traded days.

| Rule | Short? | Total return | Max drawdown | Switches | Days long | Days short |
| --- | --- | --- | --- | --- | --- | --- |
| Buy and hold | n/a | +1321% | 77% | 1 | 2328 | 0 |
| Time-series momentum, 12-month sign | no | +1374% | 63% | 23 | 1584 | 0 |
| Time-series momentum, 12-month sign | yes | +699% | 80% | 23 | 1584 | 743 |
| Donchian 20/10 (Turtle) | no | +2397% | 61% | 67 | 1253 | 0 |
| Donchian 20/10 (Turtle) | yes | +307% | 74% | 125 | 1253 | 734 |
| Dual MA 50/200 (variant A's states) | no | +564% | 57% | 31 | 1156 | 0 |
| Dual MA 50/200 (variant A's states) | yes | +40% | 74% | 104 | 1156 | 840 |

The rules as published, and what each one is:

1. **Time-series momentum** (Moskowitz, Ooi and Pedersen, 2012): hold the asset when its
   own trailing 12-month return is positive. Written exactly: `1 if close[d] >
   close[d-365] else -1`. The published version also scales the position by inverse
   volatility, which is not applied here; that is a sizing rule, and it changes the size
   of the numbers above but not the sign of the long-versus-short comparison.
2. **Donchian channel breakout** (the Turtle rules, Dennis and Eckhardt, made public by
   Faith): go long when the close exceeds the highest high of the previous 20 days, go
   short when it falls below the lowest low; leave on the opposite 10-day extreme. The
   channel must exclude the current bar, or the breakout is unreachable: an earlier draft
   of this script included it and produced zero trades, which is recorded here because it
   is the kind of error that silently reads as "the rule does not work".
3. **Dual moving average**: the 50/200 pair variant A already computes.

**Every rule loses by adding the short side, and every rule's drawdown gets worse.** Two of
the three long-only versions beat buy-and-hold on return (Donchian by a wide margin) and
all three beat it on drawdown. That is the honest summary of "what the best trend traders
do", applied here: *the edge is in when to stand aside, not in when to bet against.*

These are six comparisons on one asset over one window, with no volatility targeting and
no portfolio. They are a map, not a result, and none of them is a registered trial.

## 6. The bounce harvest needs no futures at all

A crude spot band harvest inside each Down run: start half in coin and half in cash, sell a
tenth of the coin whenever price is one band above the last trade, buy back a tenth of the
cash whenever it is one band below, paying 0.14% a trade.

| Band | Harvest, summed | Half-and-half | Trades | Runs beating half-and-half |
| --- | --- | --- | --- | --- |
| 3% | +18% | +3% | 258 | 18 of 28 |
| 5% | +12% | +3% | 132 | 16 of 28 |
| 10% | +5% | +3% | 46 | 9 of 28 |

**Read this weakly.** The sum is positive and the tighter band earns more, which is what
the travel numbers predict. But the 3% band beats its baseline in only 18 of 28 runs, so
the total is carried by a minority; a daily-close band is not a grid; and the real engine's
minimum notional, participation limit and partial fills are all absent. It says the
oscillation is *plausibly* harvestable net of costs. It does not say a grid harvests it.

The structural point matters more than the number. **Selling rallies inside a downtrend, on
spot, means holding inventory and selling it higher, then buying it back lower. That is
exactly what the existing grid does when it is allowed to keep running.** It needs no
futures, no borrow, no liquidation price. In spec v1's terms the question "should the bot
sell the bounces or step aside?" is precisely **V0 (always grid) against variant A (exit to
cash in Down)** over the Down periods. That comparison is already specified, already
implemented and already scheduled. The owner's second idea is a v1 question wearing a v2
hat.

## 7. What this changes

| Before this research | After |
| --- | --- |
| Two ways to trade downtrends, short or harvest bounces; both need v2 | Shorting is the weaker of the two on this data; harvesting is testable in v1 with no new engine |
| Shorting needs a futures engine, so schedule it after v1 | Shorting needs a futures engine **and** evidence it earns anything; the evidence is currently against it |
| Funding is a tailwind for bear-market shorts (PR #106) | Funding pays the short in every year measured, but is too small to matter; the note's reasoning is corrected |
| Variant A's F3 (idle in cash through a downtrend) is a cost to confirm | Standing aside *is* the published edge; F3 is the rule working, not a flaw |

**Recommendation, for the owner to accept or reject.**

1. **Do not build the short or futures engine yet.** It is the largest piece of v2 work and
   the evidence for its payoff is two events in seven years against 32 losing runs.
2. **Let v1 answer the bounce question.** The registered V0-versus-variant-A comparison,
   read over Down periods specifically, is the honest test of "trade the chop or step
   aside", with the real engine, the real filters and the real costs.
3. **Confirm variant A's F3 reading as intended** (a market already in Down at first
   provisioning opens no grid). This research says that idleness is the mechanism, not an
   accident.
4. **If the owner still wants shorts tested**, the cheapest honest version is a *mirrored
   grid on spot inventory*, not a directional short: it needs no margin model and reuses
   the existing engine, and section 6 is the reason to try it before anything with a
   liquidation price.

## 8. What I could not check, and where I could be wrong

- **One asset, one window.** BTCUSDT, 2018-03 to 2024-12. Every number would change on
  another pair or another period, and the two winning shorts are single events: drop
  2022-04 and the case against shorting gets stronger, drop nothing and it is still
  negative. A four-pair repeat is cheap and is the obvious next measurement.
- **Daily closes only.** The bounce structure inside a day is invisible here, and that is
  where a grid actually trades. Hourly or minute data would measure it properly; this is
  the single biggest gap in section 6.
- **No volatility targeting and no position sizing.** The published rules are run at full
  size. Sizing changes returns and drawdowns materially and is the part of the literature
  most likely to change the numbers, though not the long-versus-short sign.
- **The short model is arithmetic, not an engine.** It mirrors the price move and applies
  funding. No borrow interest, no margin call, no liquidation, no fill model. A real paper
  short would be worse than these numbers, not better, which strengthens the conclusion
  rather than weakening it.
- **Survivorship and regime.** Seven years containing two large bull markets is a sample
  that flatters long-only rules. The honest statement is that shorting failed *in this
  sample*, not that shorting cannot work.
- **Not a registered trial.** Nothing here is run through the backtest CLI, nothing
  produces a `results.json`, and nothing counts against the trial register. These are
  exploratory measurements on the development window and they must not later be presented
  as out-of-sample evidence for anything.

## Appendix: `data/v2_downtrend_research.py` source

SHA-256: `0197b817b087cca8d8916b6dd339e821f371197da245928f26f12b5864d8fcbd`

Run it from the repository root with the project installed:
`python data/v2_downtrend_research.py data`. It fetches what it needs through the project's
own verified fetchers and prints every table above.

```text
"""Spec v2 research: what a confirmed downtrend is worth, on BTCUSDT development months.

Record: docs/reviews/2026-09-28-claude-v2-downtrend-research.md. Run from the repository
root with the project installed:

    python data/v2_downtrend_research.py data

Development window only: daily archives 2017-08..2024-12 and funding archives
2020-01..2024-12, fetched through the project's own checksum-verified fetchers. Nothing
after 2024-12 is requested; ``development_month`` refuses it in three places anyway.

No lookahead anywhere: a signal computed from the close of day d is acted on at the
close of day d+1, the first price a live bot could reach. Costs use the paper defaults
in config/default.toml (taker 0.09%, slippage 0.05%).
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.dataset import (
    archive_get,
    fetch_file,
    fetch_funding_file,
    funding_local_path,
    local_path,
)
from crypto_grid_bot.backtest.funding import read_funding_archive
from crypto_grid_bot.backtest.klines import read_archive
from crypto_grid_bot.simulation.trend_switch import DOWN, classify_days

FIRST_DAILY, FIRST_FUNDING, LAST = "2017-08", "2020-01", "2024-12"
TAKER, SLIP = D("0.0009"), D("0.0005")
COST = TAKER + SLIP
ROUND_TRIP = COST * 2


def months(first: str) -> list[str]:
    out = [f"{y}-{m:02d}" for y in range(2017, 2025) for m in range(1, 13)]
    chosen = [m for m in out if first <= m <= LAST]
    if max(chosen) > LAST:  # unreachable; the reserved window is never requested
        raise SystemExit(f"refusing a month after {LAST}")
    return chosen


def load(data: Path) -> tuple[list, dict[str, D], dict[str, D]]:
    bars = []
    for m in months(FIRST_DAILY):
        fetch_file(data, "BTCUSDT", "1d", m, archive_get)
        rows, _ = read_archive(local_path(data, "BTCUSDT", "1d", m), "BTCUSDT", "1d", m)
        bars.extend(rows)
    bars.sort(key=lambda b: b.open_ms)
    funding: dict[str, D] = {}
    for m in months(FIRST_FUNDING):
        fetch_funding_file(data, "BTCUSDT", m, archive_get)
        for r in read_funding_archive(funding_local_path(data, "BTCUSDT", m), "BTCUSDT", m):
            day = datetime.fromtimestamp(r.calc_time_ms / 1000, UTC).date().isoformat()
            funding[day] = funding.get(day, D(0)) + r.rate
    close = {
        datetime.fromtimestamp(b.open_ms / 1000, UTC).date().isoformat(): b.close for b in bars
    }
    return bars, close, funding


def down_runs(bars: list) -> tuple[list[tuple[str, str]], list[str], dict]:
    by_day = {c.day: c for c in classify_days(bars)}
    days = sorted(by_day)
    runs, start = [], None
    for i, d in enumerate(days):
        if by_day[d].state == DOWN and start is None:
            start = d
        elif by_day[d].state != DOWN and start is not None:
            runs.append((start, days[i - 1]))
            start = None
    if start is not None:
        runs.append((start, days[-1]))
    return runs, days, by_day


def section_states(days: list[str], by_day: dict, close: dict[str, D]) -> None:
    from collections import Counter

    print("\n## 1. Days by state and year (variant A's own classifier)\n")
    print("| Year | up | recovering | middle | down | unavailable | year close move |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for y in sorted({d[:4] for d in days}):
        ds = [d for d in days if d.startswith(y)]
        c = Counter(by_day[d].state for d in ds)
        move = (close[ds[-1]] / close[ds[0]] - 1) * 100
        print(
            f"| {y} | {c['up']} | {c['recovering']} | {c['middle']} | {c['down']} "
            f"| {c['unavailable']} | {move:+.1f}% |"
        )


def section_short(runs, days, close, funding) -> None:
    print("\n## 2. Shorting each Down run, gross and after funding\n")
    print("| Run | Days | Price move | Short gross | Funding | Net |")
    print("| --- | --- | --- | --- | --- | --- |")
    compounded, losers = D(1), 0
    for a, b in runs:
        i, j = days.index(a) + 1, days.index(b) + 1
        if j >= len(days) or days[i] not in close or days[j] not in close:
            continue
        ea, eb = days[i], days[j]
        move = (close[eb] / close[ea] - 1) * 100
        gross = (close[ea] / close[eb] - 1) * 100
        fund = sum((funding.get(d, D(0)) for d in days[i:j]), D(0)) * 100
        compounded *= close[ea] / close[eb]
        losers += move > 0
        if (j - i) >= 15:
            print(
                f"| {a}..{b} | {j - i} | {move:+.1f}% | {gross:+.1f}% | {fund:+.2f}% "
                f"| {gross + fund:+.1f}% |"
            )
    print(f"\nRuns: {len(runs)}; price ROSE in {losers} of them (a short lost).")
    print(
        f"Compounded gross short over every Down run: {(compounded - 1) * 100:+.1f}% before costs."
    )


def section_funding(funding: dict[str, D]) -> None:
    print("\n## 3. Funding by year: a positive rate pays the short\n")
    print("| Year | Days | Mean daily | Sum over the year | Days the short pays |")
    print("| --- | --- | --- | --- | --- |")
    for y in sorted({d[:4] for d in funding}):
        ds = [v for d, v in funding.items() if d.startswith(y)]
        neg = sum(1 for v in ds if v < 0)
        print(
            f"| {y} | {len(ds)} | {sum(ds) / len(ds) * 100:+.4f}% | {sum(ds) * 100:+.1f}% "
            f"| {neg} ({100 * neg // len(ds)}%) |"
        )


def section_oscillation(runs, days, close) -> None:
    print("\n## 4. Oscillation inside Down runs\n")
    print("| Run | Days | Net | Travel | Travel / |net| | Rallies >=3% | Biggest rally |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    n = travel_all = rallies_all = 0
    for a, b in runs:
        i, j = days.index(a) + 1, days.index(b) + 1
        window = [days[k] for k in range(i, min(j + 1, len(days))) if days[k] in close]
        if len(window) < 5:
            continue
        prices = [close[d] for d in window]
        net = (prices[-1] / prices[0] - 1) * 100
        travel = sum(abs(prices[k + 1] / prices[k] - 1) for k in range(len(prices) - 1)) * 100
        rallies, biggest, low = 0, D(0), prices[0]
        for p in prices[1:]:
            if p < low:
                low = p
            else:
                gain = (p / low - 1) * 100
                biggest = max(biggest, gain)
                if gain >= 3:
                    rallies += 1
                    low = p
        n += len(window)
        travel_all += travel
        rallies_all += rallies
        if len(window) >= 20:
            ratio = f"{travel / abs(net):.1f}" if net else "n/a"
            print(
                f"| {a}..{b} | {len(window)} | {net:+.1f}% | {travel:.0f}% | {ratio} "
                f"| {rallies} | {biggest:.1f}% |"
            )
    print(f"\nAll runs of 5+ days: {n} days, travel {travel_all:.0f}%, rallies >=3% {rallies_all}.")


def section_rules(bars: list, funding: dict[str, D]) -> None:
    day = [datetime.fromtimestamp(b.open_ms / 1000, UTC).date().isoformat() for b in bars]
    close = [b.close for b in bars]
    high, low = [b.high for b in bars], [b.low for b in bars]

    def sma(n: int, i: int):
        return sum(close[i - n + 1 : i + 1]) / n if i >= n - 1 else None

    def tsmom(i: int, _state: int):
        return None if i < 365 else (1 if close[i] > close[i - 365] else -1)

    def donchian(i: int, state: int):
        # The channel is the PREVIOUS bars, never today's: including today makes a
        # breakout unreachable, since today's high is inside the maximum compared with.
        if i < 20:
            return None
        if close[i] >= max(high[i - 20 : i]):
            return 1
        if close[i] <= min(low[i - 20 : i]):
            return -1
        if state == 1 and close[i] <= min(low[i - 10 : i]):
            return 0
        if state == -1 and close[i] >= max(high[i - 10 : i]):
            return 0
        return state

    def dual_ma(i: int, _state: int):
        short, long = sma(50, i), sma(200, i)
        if long is None or short is None:
            return None
        if close[i] > long and short > long:
            return 1
        return -1 if close[i] < long and close[i] < short else 0

    def run(signal, allow_short: bool):
        equity, state, switches, peak, mdd, dl, ds = D(1), 0, 0, D(1), D(0), 0, 0
        for i in range(1, len(close) - 1):
            want = signal(i - 1, state)
            if want is None:
                continue
            if not allow_short and want == -1:
                want = 0
            if want != state:
                equity *= 1 - ROUND_TRIP if (state or want) else D(1)
                switches += 1
                state = want
            step = close[i + 1] / close[i]
            if state == 1:
                equity *= step
                dl += 1
            elif state == -1:
                equity *= 2 - step
                equity *= 1 + funding.get(day[i + 1], D(0))
                ds += 1
            peak = max(peak, equity)
            mdd = max(mdd, (peak - equity) / peak)
        return equity, switches, mdd, dl, ds

    equity, peak, mdd = D(1), D(0), D(0)
    for i in range(365, len(close) - 1):
        equity *= close[i + 1] / close[i]
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak)

    print(f"\n## 5. Published trend rules on BTCUSDT, {day[366]} .. {day[-1]}\n")
    print(f"Round trip {ROUND_TRIP * 100:.2f}%. Funding applied to short days from 2020.\n")
    print("| Rule | Short? | Total return | Max drawdown | Switches | Days long | Days short |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    print(
        f"| Buy and hold | n/a | {(equity - 1) * 100:+.0f}% | {mdd * 100:.0f}% | 1 "
        f"| {len(close) - 366} | 0 |"
    )
    for fn, short, name in (
        (tsmom, False, "Time-series momentum, 12-month sign"),
        (tsmom, True, "Time-series momentum, 12-month sign"),
        (donchian, False, "Donchian 20/10 (Turtle)"),
        (donchian, True, "Donchian 20/10 (Turtle)"),
        (dual_ma, False, "Dual MA 50/200 (variant A's states)"),
        (dual_ma, True, "Dual MA 50/200 (variant A's states)"),
    ):
        eq, sw, dd, dl, ds = run(fn, short)
        print(
            f"| {name} | {'yes' if short else 'no'} | {(eq - 1) * 100:+.0f}% | {dd * 100:.0f}% "
            f"| {sw} | {dl} | {ds} |"
        )


def section_harvest(runs, days, close) -> None:
    print("\n## 6. A crude spot band harvest inside Down runs\n")
    print("Half the capital in coin and half in cash at each run's start; a tenth of the")
    print("side is traded whenever price is one band from the last trade. Each trade pays")
    print(f"{COST * 100:.2f}%. This is not the grid engine and is not a result.\n")
    print("| Band | Harvest, summed | Half-and-half | Trades | Runs beating half-and-half |")
    print("| --- | --- | --- | --- | --- |")
    for band in (D("0.03"), D("0.05"), D("0.10")):
        harvest = baseline = D(0)
        trades = wins = counted = 0
        for a, b in runs:
            i, j = days.index(a) + 1, days.index(b) + 1
            window = [days[k] for k in range(i, min(j + 1, len(days))) if days[k] in close]
            if len(window) < 5:
                continue
            prices = [close[d] for d in window]
            coin, cash, anchor = D("0.5") / prices[0], D("0.5"), prices[0]
            for p in prices[1:]:
                if p >= anchor * (1 + band) and coin > 0:
                    q = coin / 10
                    cash += q * p * (1 - COST)
                    coin -= q
                    anchor, trades = p, trades + 1
                elif p <= anchor * (1 - band) and cash > 0:
                    spend = cash / 10
                    coin += spend / p * (1 - COST)
                    cash -= spend
                    anchor, trades = p, trades + 1
            end = coin * prices[-1] + cash
            half = (1 + prices[-1] / prices[0]) / 2
            harvest += end - 1
            baseline += half - 1
            wins += end > half
            counted += 1
        print(
            f"| {band * 100:.0f}% | {harvest * 100:+.0f}% | {baseline * 100:+.0f}% | {trades} "
            f"| {wins} of {counted} |"
        )


def main() -> int:
    data = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    bars, close, funding = load(data)
    runs, days, by_day = down_runs(bars)
    print(f"Daily bars {len(bars)}; classified days {len(days)} ({days[0]} .. {days[-1]}).")
    print(f"Funding days {len(funding)}. Down runs {len(runs)}.")
    section_states(days, by_day, close)
    section_short(runs, days, close, funding)
    section_funding(funding)
    section_oscillation(runs, days, close)
    section_rules(bars, funding)
    section_harvest(runs, days, close)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
