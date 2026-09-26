# Claude: what the open-only class actually compares, and the provenance it still owes

- **Date:** 2026-09-26. **Author:** Claude. **Run:** Claude cloud session, Python 3.12.
- **Scope.** One residual accuracy defect in
  [the open-only report](2026-09-26-claude-open-mismatch-explained.md), fixed in this PR,
  and the honest provenance status of Claude's exact-volume measurements. Code reading
  only: no archive was downloaded, opened or measured, and no integrity rule, parser,
  spec, mask or config changes.
- **Why this file exists.** The finding was reviewed at PR #82 head
  `0b550469d053b3e49c5a33cf684e19e0eb3fed71` and posted there as comment 5850581120 at
  about 22:44 UTC. PR #82 had already merged at **22:42:28 UTC** as
  `94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a`, so that comment sits on a merged PR that
  nobody is notified about. This indexed note on `main` is the durable record instead.

## The defect: "volume fields", plural, overstates the comparison

PR #82 correctly replaced "volume agree by definition of this class" with a drift-tolerance
statement. The replacement then said "the volume **fields** pass the configured drift
tolerance", and the "What follows" bullet said "passing volume **tolerances**". Both plurals
claim more than the code does.

`compare_bars` (`src/crypto_grid_bot/backtest/replay.py:577`) compares exactly five values:

- four prices — `open`, `high`, `low`, `close` — for exact equality; and
- **one** volume field, `ours.volume` against `theirs.volume`, against the **single**
  `VOLUME_DRIFT_TOLERANCE` (`replay.py:572`, `Decimal("0.001")`).

`quote_volume` and `taker_buy_base` are never compared on this path. They appear only as
values carried through by `_with_prices_of` (`src/crypto_grid_bot/backtest/audit.py:145`),
which substitutes the reference prices so `differing_fields` can decide whether volume
alone would fail the tolerance. Nothing reads them for agreement.

So the open-only class establishes: three prices equal, `volume` within 0.1%, and
**nothing whatever** about the other two volume fields. The plural invited the opposite
reading. Fixed in this PR to the singular, naming the two uncompared fields explicitly.

## Provenance of Claude's exact-volume measurements: still owed

At PR #80 comment 5850528551 Claude reported that `volume`, `quote_volume` and
`taker_buy_base` were all **exactly** equal across all 1,689 sampled hours. Codex
correctly recorded that as a newly reported measurement, not reproduced evidence, and
assigned Claude a separate indexed follow-up carrying its source.

**That source is not published here, and this session could not produce it.** `data/` does
not exist in this container: the cached archives did not survive, so the measurement
cannot be rerun and no hash-pinned appendix can be verified against real output.
Re-downloading archives was not authorized for this session, and the measurement script
has no built-in reserved-window guard.

Status, stated plainly:

| Claim | Standing |
| --- | --- |
| `compare_bars` compares four prices and one volume field | **Verified here** by reading `replay.py:577` and `audit.py:145`. No data needed. |
| All three volume fields exactly equal across 1,689 hours | **Unverified historical claim.** Reported at PR #80 comment 5850528551, source not published, not reproducible in this container. |

The conclusion of the open-only report does not rest on the second row, which is why its
absence blocks nothing. The debt stays open: a hash-pinned appendix and rerun output are
owed whenever archives are available again, and until then the claim must not be cited as
reproduced evidence for any reclassification.

## What I checked, and what I could not

- Verified at merged `main` `94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a`: `compare_bars`
  and `differing_fields` bodies, `VOLUME_DRIFT_TOLERANCE`, and that no other call site
  compares `quote_volume` or `taker_buy_base` for archive agreement.
- Re-ran `python scripts/check_reports.py` after these edits: six appendix scripts
  hash-checked, zero problems. The open-only appendix bytes are untouched by this PR.
- Independently confirmed, during the PR #82 review, that `features.py:57` stores
  `c.open_ms` (timestamps) and that `__main__.py:77,81,84` build `SeriesFeatures` from
  `load_hourly` for pair, market proxy and every breadth member.
- **Could not check:** any archive measurement, including the 1,689-hour counts and the
  1,023/1,024 previous-close statistic. Both remain preserved historical numbers.

## Owners

- Claude owns the outstanding measurement source once archives are available.
- Codex and the owner still own whether to reclassify the open-only class; nothing here
  advances that decision, and no acceptance condition is proposed or changed.
