# Claude: V3.1 extra-window minute-bar manifest rebuilt from Bob's digest

Index: Commits the v3-1-minute-bars-2020-2021 manifest and digest (5 coins, 1m, 2020-02 to 2021-05, 80 archives), rebuilt from the digest in Bob's report #277 with the pinned script and no request to Binance; both SHA-256 values match Bob's run.

Bob ran `docs/tasks/2026-10-12-bob-v3-1-minute-bars-2020-fetch.md` in run
[38267478452](https://github.com/mgalic01/adaptive-market-engine/actions/runs/38267478452)
on `main` `89564d890909240f611e4e8ca7eab3c23edf935e`. The report
(`docs/reviews/2026-10-12-bob-v3-1-minute-bars-2020-fetch.md`, PR #277) says VALID and
`RESULT 0 problem(s)`: 80 archives `ok`, 0 missing, 0 unreadable, 161 requests (160 plus
one retry after an HTTP 503), latest month 2021-05, `RESERVED-WINDOW FILES 0`.

## What Claude did

- Took the digest verbatim from the report's `## Digest` block: 82 lines, 9,154 bytes,
  SHA-256 `c1973d2a18d33a3b5e3e9fc553f7bc5a46fd9492c966f193f51212ec5736f5b8`. That equals
  the report's `DIGEST` line.
- Rebuilt the manifest with `rebuild` from the pinned fetch script (scripts/fetch_minute_bars.py) and the
  committed spec `config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.toml`, and
  wrote it with `write_manifest`. Its SHA-256 is
  `c2582815d56b3eec2fd3468002c0e3fe6c09914fb967ac7faba31392b109966a`, equal to the report's
  `MANIFEST` line, so the manifest is byte-identical to the one Bob's run wrote.
- Made no network request and read no archive.

## Coverage, from Bob's run

7 of the 16 months are complete per coin. About 1,856 of 699,840 minutes are absent per
coin, which is 0.27%, with the same count on every coin, so the gaps are exchange-wide. In
V3.1 the grid flow gate treats a missing minute as unavailable flow, so grid buys are
unavailable for that hour, never ungated. These months feed only the reported-only W0
window (2020-03-01 onward); none of them is inside the pass/fail window W1.

## Next

The V3.1 registration (PR #269 and its follow-up) pins this manifest's SHA-256 with the
other inputs. A historical run re-fetches the archives and verifies each one against
this manifest.
