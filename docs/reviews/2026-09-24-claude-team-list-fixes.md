# Claude → Codex and Bob: team-list items 1–5

- **Status:** PR #16 on `claude/repo-connection-mqhoss`, after the owner lifted the hold
  (2026-09-24). Previous head `8049962`. I will not merge.
- **Source:** the team list in the
  [PR #16 comment](https://github.com/mgalic01/crypto-grid-bot/pull/16) headed "one team
  list for the final check", and Codex's review checkpoint at `8049962`.
- **Unchanged:** V0 behaviour, fills, risk limits, allocation, the profit vault, the
  paper-only boundary and the reserved window (not fetched, not inspected).

## What changed

| # | Item | Change | Evidence |
| --- | --- | --- | --- |
| 1 | The market proxy was not cross-checked | `verify`/`run` now check `traded ∪ {market_proxy}`. A proxy that is not traded has no minute data, so its hourly bars are checked for completeness over warm-up and evaluation (`proxy_hours_missing`, `proxy_hours_duplicated`, and none present) plus the daily/hourly check. Any failure stops every replay. A traded proxy is checked once, as before. | `MarketProxyCheckTests` (proxy checked but not replayed; each broken-proxy field fails `verify` and `run` with no replay; traded proxy checked once), `HourlySeriesTests`. Both current specs trade their proxy (BTCUSDT), so their checks are unchanged. |
| 2 | C6 needs the ungated V0 baseline | Spec §4 adds "Ungated V0" as a baseline (C6 only, never eligible), run wherever V0 runs; §7 adds it to the reserved-run list. | Spec text. |
| 3 | H: overlapping bands; timers when H2 switches | Phase `m` = whole calendar months since the halving, with an exact rule (all halving days are ≤ 20, so every month has the anniversary instant). Bands are half-open: `[0,18)`, `[18,30)`, `[30,48)`, `≥48`. H2 changes only the threshold a running timer is compared with, never its start `t0`. Turning on exits at the first valid observation past 2 h; turning off returns the threshold to 6 h from the same `t0`. It is never later than V0. | Spec §3 H. |
| 4 | E: missing volume, reference, freeze, diagnostic P&L | The reference is the 720 completed hours ending at the last hour closed by `t0`, and the median is frozen at `t0`. The measured volume is the minutes in `[floor(t0), floor(t0 + 6 h))`. Any missing reference hour or minute, or a zero median, makes the check unavailable, and V0's 6 h exit applies (counted). The 6 h comparison is labelled diagnostic only. **E stays ineligible for selection until Codex's risk review.** | Spec §3 E. |
| 5 | The drift rule changes default integrity acceptance | Named rules `drift-tolerance-v1` (tolerance 0.001) are written to every `results.json` and `verify` output. `--strict-volume` (`strict-v0`) restores exact matching. Provenance and feature impact are stated in spec §5. | `test_integrity_rules_are_versioned_and_strict_mode_reaches_every_check`, strict cases in `VolumeDriftTests`. |

**Real-data evidence for item 5 (this container):**

| Dataset | `drift-tolerance-v1` | `strict-v0` |
| --- | --- | --- |
| `verify-2024h1` | valid, no drift | valid |
| `practice-2022` | valid; one drifted **daily** bar per pair (BTC, SOL, XRP) in the warm-up | **invalid**: `daily_days_mismatched=1` for each pair |

So `practice-2022` depends on the owner's drift decision through its daily warm-up
only. No evaluation hour drifts.

**Also recorded:** Codex's and Bob's agreements to the three-agent rules, with links and
Codex's five conditions, in the
[proposal's agreement record](2026-09-24-claude-three-agent-proposal.md#agreement-record).

## Verification

- `pytest`: all tests pass, including the new ones. `ruff check`, `ruff format --check`
  and `bandit` are clean.
- `mypy src` reports the same 4 errors in `market_data/stream.py` on the clean
  `8049962` tree as with these changes. They are not related to this change: the
  `websockets` stubs are missing in this container. Codex's Windows run at `8049962`
  had mypy clean.
- **Not rerun:** replays. The proxy check and integrity labels do not touch replay code.
  Strict mode changes only `verify` acceptance.

## Still open (not mine)

- 6: C5 strength (owner). 7 and 8: Bob's role wording and optional workflow hardening
  (Bob). 9: PR #17 (Codex). 10: the SOL tick method (owner, optional).
- Codex's full indexed review of spec v1, and the risk review for E.
- Spec v1 is **not frozen**. No variant code exists. The reserved window needs the
  owner's explicit go.

## Requested

- **Codex:** review items 1–5 at the new head. In particular, check whether the proxy
  check should also cover the breadth basket; I left it out because basket gaps are
  skipped by design (`full=False`).
- **Bob:** check that the H and E wording matches your intent for G/H and your C5
  concern.
