# Claude: V4 step 4a, the remaining arms (build record)

Index: 2026-10-24. V4 step 4a adds the four arms the registered run needs beyond step 3's eight: `v4_btc200_shorts` and `v4_confirm3` (owner decision v4-d22), `hold_btc_trend` (v4-d20) and `v3_as_built`. With them the run has 12 arms and 48 cells. V3's input pack is built on GitHub and pinned to V3.1's digest. The step was built subagent-driven in 7 tasks, each reviewed; then came a whole-branch review, one fix wave and its re-review. The two v4-d22 arms are not run on real data before the registered run. The one owner question (below) was answered A, owner decision v4-d23.

Written by Claude Code (session f7f187df). The plan is `docs/superpowers/plans/2026-10-23-v4-step4a-arms.md`. The spec, `docs/superpowers/specs/2026-10-17-v4-design.md`, carries this step's amendment, "Amended in the V4 step-4a PR". Step 4 is split in two (Delivery item 4): 4a, this PR, and 4b, the pipeline, the verdict step and the rehearsal.

## What it builds

| Piece | Where | What |
|---|---|---|
| The arm registry | `v4/engine/arms.py` | 12 arms in the spec's order; `ArmSpec.short_filter` and `confirm_readings`; family `v3`; `DIAGNOSTIC_ARMS`, the 8 step-3 arms the diagnostic workflow may run |
| `v4_btc200_shorts` | `v4/engine/run.py` | shorts only while BTCUSDT's latest daily slow vote is -1 (close below its SMA200), from its own feed and never later than the decided day. While not allowed, every signal is clamped to `max(s, 0)` before sizing |
| `v4_confirm3` | `v4/engine/run.py` | a coin's new direction takes effect only after 3 consecutive daily readings (R1); a size change within one direction follows at once |
| `hold_btc_trend` | `v4/engine/hold.py` | spot BTC with 0.99 x equity while BTC's slow vote is +1, else cash; it orders only on a state change |
| `v3_as_built` | `v4/engine/v3_as_built.py`, `scripts/v4_v3_cell.py` | V3's frozen selector through V3.1's reviewed runner, unchanged. V3's own open marks become V4-format records and a `v4-summary-v3-1` summary that verifies itself. V3 stops and failed V3 accounting are incomplete, never a pass |
| V3's input pack | `scripts/v4_v3_pack.py` | V3's pinned archives fetched, then V3's own loader and assembly. The result must equal V3.1's registered `v3_pack_sha256` (in `config/v3_1_run_manifest.json`), or nothing is uploaded |
| The v3 workflow | `.github/workflows/v4-v3.yml` | pack, then picks, then 4 cells, each under GNU time; artifacts kept 1 day; counts-only logs |

The other arms' results do not change. Tests pin v4_main's summary (without `receipt_sha256`), its records (apart from the new null keys), and nine hold cells' summaries and records against their base values. Nothing under `simulation/`, `trend/`, `strategy/`, `backtest/` or `combined/` was edited.

## Reviews

- **Every task** had a spec-and-quality review. Tasks 1-5 and 7 were clean the first time. Task 6 (`v3_as_built`) needed one fix round: the summary builder must check V3's accounting flags for every complete or liquidated outcome.
- **The whole-branch review** (most capable model) found no correctness bug and three Important items:
  - I1, the open owner question below;
  - I2, "longs are unchanged" was wrong: the clamp acts before sizing, so the book's common volatility scale and caps can change long sizes;
  - I3, the spec amendment did not state every rule the code applies.
  The fix wave fixed I2, I3 and five minors, and its re-review found everything addressed.
- **Local checks:** only focused test modules ran (owner rule: no heavy work on the owner's PC), plus ruff format and check, mypy strict and bandit, all clean. The full suite runs in CI.

## Rulings made where the spec or plan was silent

Each ruling with its cost if wrong.

1. **"Unchanged" tests (F1).** The other arms' summaries without `receipt_sha256` must equal their values at each task's base, and their records may differ only by the new keys. Cost: one test's form.
2. **The v3 page (F2).** `v3_as_built.py` writes its own page with the same escaping, and `summary.py` is not changed for v3. Cost: a second small renderer.
3. **Temporary refusals (Task 1).** Until each arm's task landed, its runner refused it before the loop, so no cell could be mislabelled. Cost: none after Task 4.
4. **Placement of the "main arm unchanged" pins (Task 2).** They live in `tests/test_v4_cell_cli.py`, on the CLI's own world. Cost: placement only.
5. **A held short with no bar (Task 2).** A held short on a coin with no daily bar on the day the filter turns "not allowed" keeps its position until that coin's next bar. That is V4's no-bar rule, the same as for any signal change. Cost: at most the no-bar span.
6. **`hold_btc_trend`'s cash clip (Task 4).** The clip can never cut its buy, so its test asserts the parts that can happen. Cost: none.
7. **`hold_btc_trend`'s unfilled orders (Task 4).** An order that never fills is not made again until the vote changes ("it trades only when that state changes"). Cost: it may stay in cash after a refused buy; the arm is reported only.
8. **No extra month guard in `v4-v3.yml` (Task 5).** `fetch_entries` refuses any 2025+ entry before any request. Cost: one guard line later.
9. **V3's terminal mark (Task 6).** It is an `event` of type `terminal`; `records.KINDS` is unchanged. Cost: readers look up the event type.
10. **A completed V3 run with unexplained accounting (Task 6)** becomes `engine_error` / `V3Accounting`, so it is incomplete. Cost: a v3 cell could be incomplete where V3.1 accepted it.
11. **`no_selector_pick` (Task 6)** gets a direct test (`V3Stop`). Cost: none.
12. **A liquidated V3 run with unexplained accounting (Task 6)** is also `V3Accounting`. Cost: such a cell is incomplete.
13. **`V3Accounting`'s `hour_ms` (Task 6)** is the terminal stamp for a completed run; it is informational. Cost: one field's meaning.
14. **Picks and pack pairing (Task 6).** The picks file does not name its pack; the workflow pairs them through both pins. Cost: a mispairing is caught only by the pins.
15. **The pack pin (Task 7)** is a workflow constant tested against the manifest, not the pack job's own output, which would make the check circular. Cost: none.
16. **I1 goes to the owner (final).** The rule is his v4-d22 definition and must be fixed before any result is seen. The code and spec kept R1 until he answered; he chose A, so R1 stands (v4-d23). Cost: none.
17. **Fix-wave scope (final).** I2, I3, M1, M2, M3 and M8 were fixed; the other minors wait for 4b. Cost: polish deferred.

## Owner question I1 (answered: A, v4-d23)

`v4_btc200_shorts`: when BTC rises back above its 200-day average, should every open short close at the next decision (A, as built: a plain market filter with no shorts while BTC is in an uptrend), or should only new shorts be blocked, so open ones run until their own coin's signal ends them (B)? The owner was asked on 2026-10-24 and answered A at 00:41 Zagreb time, before any result of the arm was seen. The code and the spec's rule R1 are unchanged; the spec records the answer as owner decision v4-d23.

## CI: a dependency advisory

CI's `pip-audit` flagged `filelock` 4.0.3 in `requirements-dev.lock` under three new advisories (CVE-2026-112907, CVE-2026-112913, CVE-2026-112940), all fixed in 4.2.1. It is unrelated to the engine and would fail every head, so the lock is bumped here, as `certifi` was in step 3. All 7,460 tests had passed at the earlier head.

## Deferred to step 4b (non-blocking)

- **The engine:**
  - the BTC daily feed exists three times, so one shared helper;
  - the unreachable `reading.day_ms <= day` conjunct in `_btc_shorts_allowed` should become an assertion;
  - an `ArmSpec` with both `long_only` and `confirm_readings` should be refused;
  - `_sign` exists three times, so one shared helper;
  - `SHORT_FILTER_COIN` duplicates `HOLD_BTC_COIN`;
  - several stale docstrings.
- **Tests:**
  - a v4_confirm3 direction on a spot-only coin;
  - BTC both decided and crossing its SMA;
  - the no-bar held short;
  - hold_btc_trend after a dead-market close, and a deferred buy superseded by a sale;
  - CLI runs of the three new arms (4b's rehearsal runs all 48 cells through both CLIs);
  - the V3Stop-with-terminal and `ReplayExecutionError` paths;
  - the fetch 404, rerun and existing-output paths, and the manifest layout assertion;
  - the opaque digest pins, which should each carry a re-capture note.
- **v3_as_built:**
  - `_full` repeats `summary.py`'s period, drawdown and return rules, so 4b adds a test that both builders agree on one path;
  - the V3Stop checks are lighter than the others;
  - the page head is copied from `summary.py`;
  - a failed write leaves a partial `records.jsonl`;
  - the module is about 790 lines.
- **4b's verdict:**
  - it requires every v3 summary's `v3_pack_sha256` to be the expected pin and one shared `picks_sha256`;
  - it reads both summary formats;
  - condition 2's path starts at 2021-07-01 00:00;
  - the run summary discloses the 1,000 USDT capital adapter (the v3 summary now carries `disclosures`).

## After merge (operational)

1. Dispatch `v4-v3.yml` from main. Check that the pack's pin equals V3.1's (R4), that all four v3 cells are `complete`, and how many of their hours are incomplete. A `V3Accounting` there would leave condition 2 incomplete for good, so it must be resolved before registration. Measure the picks and cell times (R5).
2. Download to E: and check the GitHub digests; offer the owner the deletion of the GitHub copies.
3. Write the step-4b plan.
