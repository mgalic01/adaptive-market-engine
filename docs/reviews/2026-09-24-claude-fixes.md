# Claude fixes for review #2: handoff to Codex

Codex: the owner asked me to implement the findings in
[`2026-09-24-claude-review-2.md`](2026-09-24-claude-review-2.md) directly rather than
route them back to you. The work is on `claude/review-2-fixes`, based on `main` `cf9b952`.
Claude wrote this change, so please review it independently before building on it.

## What changed

| Review item | Change | Where |
| --- | --- | --- |
| 1. Regime boundaries | RANGE iff `max(\|score\|/range_score_limit, ADX/range_adx_limit, dispersion/range_dispersion_limit) <= 1`. Range evidence is `1 - (1 - minimum_confidence) * load`, so it equals `minimum_confidence` exactly on the boundary. Directional strength is now `min(1, minimum_confidence * \|score\| / threshold)` times your coherence factor. At the defaults this is identical to your formula, because the old `0.50` equals `bull / minimum_confidence`; it now follows the configured thresholds. | `strategy/regime.py` |
| 1. Input quality | Quality is a veto (`minimum_input_quality`, default 0.70), not a multiplier on the 0.70 gate. Reported confidence is still scaled by `min(1, quality / floor)` so it stays continuous. | `strategy/regime.py` |
| 1. Config | New `[regime]` options `minimum_input_quality = 0.70` and `range_dispersion_limit = 0.50`. `minimum_confidence` must now be below 1.0, because evidence scaling is degenerate at exactly 1.0. `thresholds_from_config()` is shared by the app and the runner. | `config.py`, `config/default.toml` |
| 2. Flapping feed | Outside-range time accumulates in `outside_seconds`/`outside_last`. Only an interval bracketed by two consecutive valid outside frames at most `maximum_data_age_seconds` apart is counted. Transient frames and gaps pause the clock; only a valid inside frame resets it. | `simulation/runner.py::_track_range` |
| 3. Liveness | `SimulationPolicy.recenter_after_exit` (default `True`) plus `recenter_cooldown_seconds` (default 86400). After an exit, the account leaves the exit state once it is flat, risk returns ALLOW and the candidate is eligible, provided that either price is back in the old band or the cooldown has passed. The normal recovery confirmations still apply, and the next grid is centred on the current fair value. The old bounds are cleared when the exit ends. `False` keeps your wait-for-old-band behaviour with an explicit "recentering disabled" reason. | `simulation/runner.py` |
| Invariants | `range_exit` requires `range_exit_since` and vice versa. A non-zero `outside_seconds` requires `outside_last`. `resume` clears stale grid bounds and timers on the flat account. | `simulation/models.py`, `runner.py` |
| Schema | Now 3, because the identity gains new config and policy fields. Schema 1 and 2 databases are rejected, and the resume CLI checks for schema 3. | `runner.py`, `control.py` |
| Nits | Reasons now name the dominant branch and the quality/floor. The hard-coded `0.50` is gone, and `coherence_weight` is a validated `RegimeThresholds` field. Mypy uses `files = ["src"]`, so a local `mypy` matches CI. Version is 0.5.0. | various |

## Evidence

- 121 tests pass (previously 107), plus 269 subtests. Ruff check and format, strict mypy
  and bandit are clean; the self-check and the paper demo both run.
- The paper demo JSON is byte-identical to `main`, so the canonical fixture's behaviour is unchanged.
- `test_flapping_feed_cannot_postpone_outside_range_exit` run against `main` code never
  exits in 390 s of outside observations. On this branch it exits at 110 s, after 100 s of
  valid observation.
- The review #2 table cases (data quality/news risk of 1.0/0.0, 0.95/0.1 and 0.9/0.2 at ADX 15)
  now reach RANGE. At 0.9/0.25 the quality is 0.675, so the regime is vetoed.
- New regime tests sweep the whole configured box at qualities of 0.70-1.0 and check points
  just outside each limit. They also cover the quality-floor veto with continuous confidence,
  the directional boundary under non-default thresholds, and equality with your previous
  directional formula at the defaults.

## Decisions you may want to challenge

1. **Recentering on by default, with a 24 h cooldown.** This was chosen for liveness. It accepts
   the out-of-range exit loss and re-enters at the new level. I added on/off and cooldown
   variants to `BACKTEST_PLAN.md`, so measure the choice rather than accept it.
2. **Quality floor 0.70.** This mirrors `maximum_news_risk = 0.30` at perfect data quality.
   It is a hypothesis.
3. **Dispersion limit 0.50.** This rejects strong votes that cancel out. For example,
   trend +1 with breadth and momentum at -1 gives a score of about 0 but a dispersion of 0.6.
4. **Clock accounting.** An interval spanning one unusable frame is counted when the valid
   frames on either side are within the max-age limit. Accumulated time is kept across long
   gaps, which is conservative because it makes the exit happen sooner.

## Open question found while testing (not changed)

Volatility and liquidity health vote in the directional score. A perfectly quiet, healthy
market `(0, 0, 0, +1, +1)` scores +0.30 and is classified TRANSITION, not RANGE. A quiet,
unhealthy market `(0, 0, 0, -0.9, -0.9)` is also TRANSITION. Should health instead be an
eligibility input rather than a bullish/bearish vote? This decides how often a grid can run at
all, so please settle it with historical data, not fixtures.

## Requests

1. Review this PR independently, especially `_track_range`, the range-exit gate and the
   bounds reset in `resume`.
2. Then build the historical feasibility harness from `BACKTEST_PLAN.md`, including the new
   lifecycle and regime variants. Your items 3-5 from the previous handoff still stand.
3. Reply in a new `docs/reviews/` file.

No live orders, keys, transfers or deployment were added.
