# Owner direction: market structure perception layer (v2 requirement)

Index: 2026-09-29: The owner's requirement — the bot must be able to read and analyse
market structure independently, across hourly, daily and weekly timeframes, before it
can make sound grid placement decisions. Recorded from a conversation with Bob
(owner's desktop session) and from a friend's analysis (Luka Hranjec Jeri, 2026-09-29).

- **Recorded by:** Bob (owner's desktop IBM Bob session), 2026-09-29.
- **Status:** Owner requirement. Design and implementation planned in this session.
  Implementation: `src/crypto_grid_bot/strategy/structure.py` (new module).
  Agent report: `docs/reviews/2026-09-29-bob-market-structure-implementation.md`.

## Owner's words

> "I need the bot to be able to analyse the market structure on its own and to get the
> data and from it analyse the market. I am surprised that was not already done, because
> how do you even trade if you can't see and analyse the market structure (on hourly,
> daily, weekly etc.)?"

External input from Luka Hranjec Jeri (friend, 2026-09-29):
> "nedes na % nego na FTA (first trouble area) aka resistance (u downtrendu support)"
> "ne znam ti kak pomoc ali sam vidio da neki ljudi koriste onda ATR ili kaj vec,
> average daily range. ocekujes da ce se asset pomaknuti npr 2% prek dana"
> "i to se vjerojatno tak radi kad je price u konsolidaciji, tj. range-u
> (70% range, 30% trend)"

Translation: Don't target a fixed %, target the FTA (First Trouble Area) — the nearest
resistance above (or support below in a downtrend). Use ATR to estimate how far price
will travel in a day. This works especially in consolidation (roughly 70% of the time).

## What exists today

The bot has a rich execution and classification layer:

- `features.py`: computes ATR14, ADX14, SMA20/50, breadth, momentum, er20 (efficiency
  ratio), drawdown from hourly candles. Feeds `RegimeClassifier`.
- `trend_switch.py`: classifies daily bars as UP/DOWN/MIDDLE/RECOVERING using SMA50 +
  SMA200. Used by variant A.
- `regime.py`: classifies broad-market state as RANGE/BULL/BEAR/TRANSITION/STRESS.
- `grid.py`: builds geometric grids sized by ATR. Spacing is fixed at grid-open time.

**What is missing:** the bot cannot identify *where* price has structural significance —
swing highs, swing lows, support zones, resistance zones. It does not know the FTA for
a sell target, it does not know whether the current price is near a structure level,
and it has no multi-timeframe structural view.

## The three things needed

### 1. Swing point detection
A swing high is a bar whose high is higher than N bars on each side. A swing low is a
bar whose low is lower than N bars on each side. These are the structural pivots from
which support/resistance is derived.

### 2. Support and resistance levels
Cluster nearby swing points (within one ATR) into zones. Recent zones (last K swings)
carry more weight. A zone is "strong" if price has tested it multiple times.

### 3. Multi-timeframe structural state
On each timeframe (hourly, daily, weekly):
- Is price making higher highs and higher lows? (bullish structure)
- Is price making lower highs and lower lows? (bearish structure)
- Is price oscillating between two levels? (range structure)

Alignment across timeframes increases confidence. Weekly bullish + daily bullish +
hourly bullish = high-confidence bull. Weekly bullish + daily bearish = correction
within a bull — different grid behaviour.

## How this connects to the FTA sell-target idea

Currently sell targets are placed at the next geometric grid level: `buy_price × ratio`.
With structure awareness, the sell target should be placed just below the nearest
resistance zone above the buy price. If the nearest resistance is at $0.355 and the
geometric level is at $0.342, the FTA-aware target is $0.354 (just below $0.355).

If no resistance is within range, fall back to the geometric level. Never set a target
above a strong resistance without the bot knowing it is trying to break through.

## What this PR implements

See `src/crypto_grid_bot/strategy/structure.py` and
`docs/reviews/2026-09-29-bob-market-structure-implementation.md` for the full
implementation and mathematical decisions.

— IBM Bob (owner's desktop session)
