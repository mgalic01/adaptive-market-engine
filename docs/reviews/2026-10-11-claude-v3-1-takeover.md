# Claude: V3.1 takeover of PR #269

Index: Claude took over the V3.1 runtime from Codex on 2026-10-11 (owner handoff). Landed the funding boundary and opening fills, the complete strategy replay with exact report evidence, the owner's decision on limits for open positions, the reserved-boundary window end and bounded dashboards. Synthetic verification only; no historical run.

The owner handed PR #269 from Codex to Claude on 2026-10-11, when Codex's remaining
usage ran low (Codex release 6110756253; Claude claim 6110916959). Claude is the
named writer. Codex's ledger and design records stay as they were. This file records
what Claude checked, decided and changed, at full SHAs. Every claim names the head
it was checked at.

## What Claude found at the handoff head `59bca32a690b98da020829bb912e76881ad88545`

- **CI:** `test-and-audit` was cancelled twice at its 10-minute job timeout with pytest
  about half done. The full suite takes 7.5 to 12 minutes on hosted runners, and
  `test_backtest_pool.py::PoolSizeTests::test_a_pool_of_four_writes_the_results_of_one_job`
  alone takes 222 s locally. That test is unchanged by this PR. The timeout is now 20 minutes,
  and a separate task was suggested to speed the test up.
- **Review threads:** all 46 inline threads were unresolved. A triage against the code and
  tests at `59bca32`, with spot checks, found 45 already fixed by Codex's commits. The one
  remaining P2 (malformed outcome records crash `evaluate`) is fixed in `4269c20`. Each thread
  has a reply with its evidence and is resolved.
- **Side finding:** a stale-quote close reason persists while a position is held, and the
  boundary adapter checked that reason rather than the current mark. One stale hour therefore
  blocked every later hourly boundary until the position closed, and a dust position never
  closes. `EngineSnapshot.stale` now names only the symbols stale at the current mark.

## Batch 1, `4269c20831ed5d6db3822a31971ffe2227585b14`

- **Codex's five unpublished files landed:** the opening-fill bridge, the funding boundary
  executor and booked-funding evidence.
- **Funding:** booked only on futures holdings that survived the previous interval, at the
  fixing's own mark. Spot holdings and unheld symbols never pay.
- **Retries:** whole-frame attempts are registered on the engine's account, so neither a new
  executor instance nor corrected inputs can retry a failed boundary or opening.
- **Dust:** verified unsellable dust keeps its close obligation and value, and is reported
  rather than failing the interval. The spec says dust "stays valued and owned".

## Batch 2, `28c081c28f09f30822180beb971e5f460485d4fa`

- **Complete replay:** `strategy_replay.replay_strategy` runs one arm, scenario, capital, cost
  profile and window, once, over complete in-memory inputs. A missing window hour or funding
  settlement refuses the run before it starts.
  - **Order within each hour:** first the previous bar's path at its availability, then
    completed-bar management, then the boundary frame (funding, protective reductions,
    decisions, openings, grid placement).
  - **Grid buys:** resting buys fill at their limit with no gap credit, before that vertex's
    stop, and earn no same-bar target.
- **Report evidence:** `replay_records.strategy_report`.
  - Every engine mark is retained, and each hourly boundary lists all marks at its timestamp.
  - Capital, utilization, daily samples and recovery endpoints bind to observation IDs.
  - Lifecycles attribute every fill and funding payment. Synthetic reports are complete
    with residual 0.
- **Owner decision 2026-10-11, "Risk from entry; trim size":**
  - **Why it was asked:** the first full synthetic replay showed every winning trend trade
    force-closed within an hour. The engine measured per-asset risk from the current mark
    and closed the whole position on any breach, so the trailing stop (which starts at 2R)
    could never engage.
  - **The 0.5% and 3% risk limits:** they now measure entry-to-stop loss.
  - **Breached limits:** they cut holdings back to the limit (`reduce_to`) instead of closing
    them.
  - **Margin stress:** it keeps mark-to-stop loss.
  - **Records:** design spec, Package D.
- **Claude's rulings for reviewers:**
  - **Grid rebuild:** a basket back to no inventory after a completed cycle is withdrawn, so
    the next decision can rebuild it at the current price ("Rebuild only flat").
  - **Cancellations on a breach:** an asset breach cancels that asset's pending increases; an
    aggregate or group breach cancels all of them. Canceling within-limit increases elsewhere
    does not restore any limit.
  - **Full closes and cut-backs:** holdings already required to close do not size other
    holdings' cut-backs, so persistent cut-back targets are not set needlessly.

## Batch 3 (independent critic, Codex at `28c081c`, second owner decision)

- **Owner decision 2026-10-11, "Cut to 90% of the limit":** a cut-back goes to 90% of
  the breached limit (design spec, Package D).
- **Critic B1 (blocker):** a resting grid basket canceled by a routine cap check ended the
  run, because the replay acknowledged its own cancel only afterwards. In a replay this
  process is the only venue, so `PortfolioEngine(simulated_venue=True)` makes a cancel
  final at once, with a recorded finality reference.
- **Critic M1:** an old stop already crossed by the opening quote now executes in that
  boundary frame, after funding on the surviving holding and before any entry.
- **Critic M3:** the minutes are indexed once; each flow lookup reads its fifteen bars.
- **Critic M4:** verified dust no longer blocks new trend openings. An unsellable cut-back
  counts as retained dust. A withdrawn opening or refused grid allocation is recorded as a
  refused `filled` stage.
- **Critic minors:**
  - admission marks outside settlement batches are retained;
  - entries' post-fill obligations drain at the same opening quote;
  - a zero cut-back target closes only its asset;
  - windows must be whole UTC days;
  - booked funding is always attributed;
  - a failed replay is declared in the report (`producer_issues`);
  - only value and arithmetic errors become run failures;
  - grid target sales are attributed as `grid_target`;
  - the report's utilization check is no longer quadratic.
- **Codex findings at `4269c20`/`28c081c`:**
  - continuous caps project pending orders' known entry losses;
  - a gap-filled grid buy is valued at the actual open, while its fill keeps the limit price;
  - grid child fills complete their opportunity funnel;
  - held portfolios follow each day's causal correlation snapshot;
  - funding records after the window are never read;
  - a futures-enabled arm requires futures inputs for every symbol;
  - dashboard benchmarks are compared on the approved hourly schedule.
- **Reserved boundary:** a window may end exactly at 2025-01-01. Its last bar's marks and
  terminal close carry that availability time. No decision, admission, funding or frame sits
  at the boundary, and any input record at or after it is refused.
- **Dashboard sizing:** charts keep each time bucket's first, lowest, highest and last mark.
  Long tables show up to 500 rows with counts, and provenance is summarized per record type.
  The exact JSON is embedded only below 1 MB (`exact_evidence()` returns it in full).

## Not yet done

- frozen V0–V3 baseline adapters: the study is done, and several comparability rulings go to the owner;
- the conformance review against the spec;
- the exact registration;
- a substantive external review of the latest full head, and green required checks.

Historical execution needs the reviewed exact registration and a separate owner go.
No 2025+ data is read; no live trading exists.
