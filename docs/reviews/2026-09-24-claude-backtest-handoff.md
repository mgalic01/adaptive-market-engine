# Handoff to Codex: historical replay harness v1 (v0.8.0)

Codex: the owner chose the historical backtest as the next step (plan item 3 of your
first handoff). This is Claude's implementation of the plan's "first deliverable",
on `claude/repo-connection-mqhoss`. Please review it independently before building on
it. The method is in [BACKTEST_METHOD.md](../BACKTEST_METHOD.md) and the first
verification results are in [backtests/verify-2024h1.md](../backtests/verify-2024h1.md).

## Also on this branch since `main` acdca43

1. **Frame cadence (schema 4, v0.6):**
   - `SimulationPolicy.maximum_frame_gap_seconds` (default 180 s) now governs the
     recovery streaks and outside-range time.
   - `maximum_data_age_seconds` is now only a per-frame freshness limit.
   - At the collector's 60 s polling, pauses previously never cleared and range exits
     never fired; 60 s-cadence regressions cover this.
2. **Collector through `HTTPS_PROXY` (v0.7):**
   - The stdlib transport ignored the proxy. It now tunnels via CONNECT to the fixed
     host, still verifying TLS for that host.
   - First real capture: ADAUSDC, 2026-09-24.
3. **Read-only price stream (v0.7):**
   - Public `bookTicker` on `data-stream.binance.vision`, using `websockets==17.1`, the
     first pinned runtime dependency.
   - Limits: at most 10 connects per 5 minutes, capped backoff, 30 s silence watchdog,
     rotation after 23 h, no retry on HTTP 418/429, and prices cleared on disconnect.
   - It is not yet wired into the simulator.
4. **Replay harness (v0.8):** the `backtest` package, a dataset spec plus committed
   manifest, and the engine changes below.

## Engine changes that need your review

- `Frame.epoch`, `LimitOrder.epoch`, `match(..., epoch=...)`: optional and replay-only.
  - An order created while processing a frame with epoch *E* is skipped by `match`
    for every other frame with epoch *E*.
  - The replay gives the four quotes of one 1m bar the same epoch, so a grid buy and
    its child sell (or a sell and its re-entry buy) never both fill on an assumed
    intrabar path.
  - With `epoch=None` behaviour is unchanged: the paper demo output is byte-identical,
    `Frame.payload()` omits the key, and `Account.to_dict()` omits unused order epochs,
    so schema-4 journals and state keep their layout.
- `PaperSimulator.step(account, frame)` is the journal-free in-memory step: the same
  `_step`, the same 50-digit context and the same final `validate`.

## Please challenge

1. **Adapter assumptions:**
   - bid/ask at the high and low (ask = high, bid = low);
   - the 0.05% assumed spread;
   - an even four-way split of taker volume;
   - participation applied per share.
2. **Features `price-only-v1`:**
   - every constant in the method document, especially using hourly ATR for the grid
     range;
   - health signals that only ever vote negative;
   - BTC as the broad-market proxy.
   These were fixed before the first run and not tuned. Changing them is fine, but as a
   new, pre-registered version, not on the verification window.
3. **The proposed acceptance criteria** at the end of the method document. The owner
   has not agreed them yet.
4. **Findings in the verification report**, which look like strategy-design questions
   rather than harness bugs.

## Suggested next steps

- Agree the acceptance criteria with the owner.
- Build a survivorship-aware universe for an untouched window: 10-20 markets, including
  pairs delisted after the window starts, using only months the archive publishes.
- Add a true static-grid baseline. The ungated baseline still re-centres at each flat
  point.
- Make runs faster (about 200 µs per step now), for example by emitting only the close
  quote for bars in which no resting order could cross. Only do this with an
  equivalence test.
- Add spread and path sensitivity to the summary.

No live orders, keys, transfers or deployment were added.
