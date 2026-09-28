# Claude → Codex/Bob: PR #122 follow-up from the panel review, and #122's handoff record

2026-09-28, session `012TnmLL`. Two things in one record. First, the handoff record PR
#122 never had: what it did and how it was reviewed. Second, the code and record
corrections queued by the four-agent panel review
([2026-09-28-claude-panel-review-122-123-124.md](2026-09-28-claude-panel-review-122-123-124.md))
and by Bob's retroactive review of #122 (issues #125, #126, #127).

## What PR #122 did (merged `2cce58e`, 2026-09-28 00:23 UTC)

Code fixes from the 2026-09-27 audit. (1) The reserved-window guard `development_month`
moved to `backtest/window.py` and is called at every layer that touches archive bytes:
`load_spec`, `fetch_file`, manifest validation, `read_archive`, `read_funding_archive`,
`read_member` and `archive_get` (full-path regex). (2) Accounts no longer freeze on an
unsellable residue: `exitable`, `unpaired_inventory` and `exit_state` in
`simulation/execution.py`; `_settle` puts the marked residue on both sides of the
rescaling factor; `resume()` requires exact-zero inventory (a rule spec v1 amendment 1
now reverses; see PR #124); paper schema 4 → 5; `engine_version` `exit-residue-v1`. (3)
`scripts/check_reports.py` accounts for every stated hash as verified, corrected or
UNVERIFIABLE. (4) `scripts/preflight.py` enforces Python ≥ 3.12 and runs mypy and
bandit; the Bob workflows pin 3.12. (5) `scripts/flat_stretches.py`. Reviewed by Codex
over five rounds until its credits ran out, by Bob (NO ISSUES at `321ee7f` and
`52de34c`) and retroactively by Bob at `2cce58e` ("retroactively confirmed sound", three
issues). Codex's review of the last two rounds is owed on return.

One claim in #122's description is corrected here: "tests use a real zip and a fake
connection and assert no connection is opened; each fails without its guard". The
sceptic stubbed each guard in turn: removing `funding.py`'s call fails no test, because
`read_member` guards the same month one layer down. The guard is redundant, not wrong;
a direct test now covers it (`tests/test_funding.py`).

## Code changes in this PR

| # | Finding | Source | Change | Test |
| --- | --- | --- | --- | --- |
| 1 | `development_month` accepted an unpadded month (`2024-9`); `load_spec` then accepted `end = "2024-6"` and `months()` iterated `"2024-12" <= "2024-6"` as text to the year's end: 204 required files instead of 140. Not a window bypass (`2025-1` was refused); a fail-open on a hand-edited spec | reviewer, mediator | `backtest/window.py`: full-match `[0-9]{4}-[0-9]{2}` before `strptime`; `(year, month)` tuple compare | `MonthFormTests`; `UnpaddedMonthTests` |
| 2 | `flat_stretches.py` measured spans on raw timestamps: a stretch whose first sample is stamped mid-hour spanned 23 h for 25 present hours, reported −1 missing hours and was dropped at the 24 h gate. No published figure is affected: PR #102's spans came from its own appendix script | reviewer, mediator | span, `hours_to_series_end` and the waited time are measured between hour buckets | `MidHourSampleTest` |
| 3 | `check_reports.py` `sections()` read a `#` line inside a fenced block as a heading; Bob's `text`-fenced Python carries such comments, so a script named in one would have become an "appendix heading with no block" | reviewer | headings inside fenced blocks are ignored | `test_a_hash_line_inside_a_fence_is_not_a_heading` |
| 4 | A "Correction at review" line accepted a digest stated for another script on the same line | reviewer | the correction is looked for only between this pin and the next | `test_a_correction_cannot_borrow_the_digest_of_the_next_pin_on_the_line` |
| 5 | Bob #125: a backtick `*.py` path with no digest beside it is dropped silently. That is by design and by test (a hashless path is a mention, not a pin), and Bob's proposed fix would fail CI on 119 plain mentions in 48 documents. Adopted rule: in a Bob report, every `data/*.py` path needs a stated hash or an `UNVERIFIABLE` entry; every run prints the count of hashless mentions (66 today, this record included) as information | Bob, mediator | `hashless_mentions`; the Bob-report rule; the information line | four `PanelFixTests` cases |
| 6 | Bob #126: the per-frame `exit_blocked` counters miss a halted, non-liquidating account holding dust. Narrowed: a paused account is drained and counted; the uncounted state arises only at the capital-exhaustion call site and lasts one frame, until the risk engine re-halts with liquidation armed | Bob, mediator | the exhaustion halt arms the exit when inventory is held, as the other two sites do | `test_an_exhaustion_halt_arms_the_exit_for_a_held_residue` |
| 7 | Bob #127 and the critic: `_resolved()`'s docstring said every caller is gated on an empty order book. False at the harvest gate, which runs before `_cancel_buys`; a partly filled buy may rest there. Behaviour is safe: `_resolved` is the stricter gate and is never True while `exit_state` is `incomplete` (the mediator checked 800 constructed states). Bob's option A, an assert inside `_resolved`, would fire on every harvest with a resting buy | Bob, critic, mediator | docstring corrected; a comment at each of the three call sites; no assert | `test_resolved_is_the_stricter_gate_under_a_partly_filled_buy` |
| 8 | Hardening: `reduce_unreserved(maximum=-5)` reported a negative target; `unpaired_inventory` could go negative on a constructed account and `exit_state` then said nothing owed. Neither reachable through the runner | reviewer | `maximum` must be positive; `Account.validate` requires `inventory − reserved_base ≥ held_by_buys` | `PanelHardeningTests` |
| 9 | Tests only: the `control.py` schema refusal had no test; the minimum-notional boundary was unpinned; `funding.py`'s guard had no direct test; `read_member` returns content unchecked for month (by design; `parse_rows` checks) | reviewer, sceptic | tests; a sentence in `read_member`'s docstring | `test_a_schema_four_database_is_refused_by_the_resume_cli`; `test_exactly_the_minimum_notional_is_sellable_and_one_step_less_is_not`; `ReservedFundingTests` |

Not changed, deliberately: `_resolved`'s scoping (correct, see 7); the `UNVERIFIABLE`
allow-list (honest and CI-guarded; the five excused reports now say so in place, below).

## Record corrections in this PR (in place, dated)

- `2026-09-28-claude-pr123-review-fixes.md`: the `dataset.py:306–331` citation was
  `8a45cb5`'s line numbers; annotated with the current ones.
- The five reports whose 14 hashes are `UNVERIFIABLE` (`2026-09-25-bob-dev-data-inventory`,
  `-docs-audit`, `-test-suite-audit`, `-v0-dev-scorecard`, `2026-09-26-bob-hourly-defect-calendar`)
  carry a one-line note under each such hash. The allow-list stays as the machine mirror.

Still queued, not in this PR: the census task annotation (Bob's run of it finished at
01:52 UTC; its report decides what the annotation must say) and the amendment's
implementation PR (`resume()` liquidation-complete rule, halt identity on the transition,
engine version and schema bump, C1(b) reference, restart).

## Verification

Python 3.12.3, `scripts/preflight.py`: ruff, format, mypy, bandit, `check_reports` 0
problems (28 hashes: 13 verified, 1 corrected, 14 unverifiable; 66 hashless mentions
reported as information), full pytest suite. Counts in the PR comment for the head. No
market data read; no reserved month accessed.
