# Claude: V3.1 minute-bar manifest rebuilt from Bob's digest

Index: Commits the v3-1-minute-bars manifest and digest (7 coins, 1m, 2021-06 to 2024-12, 301 archives), rebuilt from the digest in Bob's report #273 with the pinned script and no request to Binance; both SHA-256 values match Bob's run.

Bob ran `docs/tasks/2026-10-11-bob-v3-1-minute-bars-fetch.md` in run
[38216586941](https://github.com/mgalic01/adaptive-market-engine/actions/runs/38216586941)
on `main` `d1fafd66cb04e53c782c20cd5a6bbbea3efe25a1`. The report
(`docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md`, PR #273) says VALID and
`RESULT 0 problem(s)`: 301 archives `ok`, 0 missing, 0 unreadable, 602 requests, latest
month 2024-12, `RESERVED-WINDOW FILES 0`.

## What Claude did

- Took the digest verbatim from the report's `## Digest` block: 303 lines, 31,910 bytes,
  SHA-256 `6c84ee2eb3e06b720d37a285062ac1f5820c7db77fbcd704effaeacb00a172c3`. That equals
  the report's `DIGEST` line.
- Rebuilt the manifest with `rebuild` from the pinned fetch script (scripts/fetch_minute_bars.py) and the
  committed spec, and wrote it with `write_manifest`. Its SHA-256 is
  `589b9a8c493240e24f24900e8c9b81f43a4330bd652c4c8ebf628c7c5403444d`, equal to the report's
  `MANIFEST` line, so the manifest is byte-identical to the one Bob's run wrote.
- Made no network request and read no archive.

## Coverage, from Bob's run

39 or 40 of the 43 months are complete per coin. About 470 of 1,886,400 minutes are
absent per coin, which is 0.025%. In V3.1 the grid flow gate treats a missing minute as
unavailable flow, so grid buys are unavailable for that hour, never ungated.

## Next

The V3.1 registration (PR #269 and its follow-up) pins this manifest's SHA-256 with the
other inputs. A historical run re-fetches the archives and verifies each one against
this manifest.
