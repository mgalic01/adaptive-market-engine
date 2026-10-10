# V3 collection failure: spot snapshot exceeded the former ceiling

Index: Failed first local collection preserved; offline 32 MiB snapshot ceiling fix prepared, no retry authorized or performed.

The owner-started collection ended with exit code 1 at
`2026-10-09T15:41:01.344945+00:00`. Its reviewed task head was
`3379058f86214e3b0fa663ea22862ae328f65f80`; the collector was
`5822e0dac8501a0ab0f55ce96827c44782daf2d5`. The local evidence remains under
`E:/adaptive-market-engine/v3/logs-20261009-01/`, including `owner-start.json`,
`fetch-start.json`, `fetch-end.json`, `fetch.stderr.log` and `failure-evidence.json`.
The failed output `E:/adaptive-market-engine/v3/inventory-20261009-01/` contains
only an empty `snapshots/` directory. Neither location was changed by this fix.

The traceback reaches `collect_inventory` -> `spot_filters` -> `V3Transport._get`
at `https://data-api.binance.vision/api/v3/exchangeInfo`. In the pinned collector,
this exception follows the HTTP-200 check and `response.read(8388608 + 1)`.
Consequently, HTTP 200 was received and at least 8,388,609 bytes were available.
The complete body size and JSON validity are unknown. The guard raised before
returning the bytes, so the response was not retained. The futures request and
archive loop were not reached. No snapshot can be reused from this failed attempt.

The limit was repeated in transport, injected collection responses, saved-snapshot
CLI reads, the offline verifier, the inventory loader and the filter parser.
Changing only transport would move the failure downstream. The fix uses one bounded
32 MiB (33,554,432-byte) snapshot ceiling in all these places. Reads remain bounded
to limit + 1, with failures identifying the transport ceiling and endpoint while
stating that the complete response size is unknown. Archive and checksum limits
remain 64 MiB and 1 KiB. Endpoints, JSON/filter checks, hashes, paths, freshness of
output directories and the futures no-retry state remain unchanged.

Synthetic tests cover just over 8 MiB, exactly 32 MiB and one byte over 32 MiB;
collection, reuse CLI, parser and offline loader/verifier are exercised without
network access. Oversized saved inputs fail before transport or output creation;
oversized injected responses fail before snapshot writes and archive requests.
Existing small snapshots remain compatible. This is not proof that the real body
fits 32 MiB or passes parsing, nor authorization to replace or retry the collection.
A rollback would reject newly accepted snapshots over 8 MiB; it must preserve those
files rather than overwrite them.

Queue: diagnosis and offline implementation complete; local validation recorded in
the implementation handoff; parent Codex owns independent review and recovery-task
preparation. The owner must explicitly approve a subsequent collection attempt.
No development replay or reserved-window request is authorized by this note.

## Preserved failure excerpt

```text
collect_inventory: raw = saved if saved is not None else retrieve()
spot_filters: content = self._get(SPOT_FILTER_HOST, "/api/v3/exchangeInfo", 8 * 1024 * 1024)
_get: raise ValueError("public response exceeded size limit")
ValueError: public response exceeded size limit
```

This excerpt is transcribed from the local stderr; it is not the raw log file.

## Complete evidence transcripts

The following are complete UTF-8 transcripts with line endings normalized to LF;
they are not raw-byte copies and no original-file digest is claimed for them:

- [Failure traceback](evidence/2026-10-09-v3-collection-failure/fetch.stderr.log.txt)
- [Start timestamp and exact command](evidence/2026-10-09-v3-collection-failure/fetch-start.json.txt)
- [End timestamp and exit code](evidence/2026-10-09-v3-collection-failure/fetch-end.json.txt)
- [Owner start and one-attempt scope](evidence/2026-10-09-v3-collection-failure/owner-start.json.txt)

## Local verification

On Python 3.14.7, the final stable implementation passed 100 tests across
`test_fetch_v3_data`, `test_v3_inventory_plan`, `test_v3_inventory_cli`,
`test_v3_inventory_build`, `test_v3_inventory_loader`, `test_trend_filters` and
`test_v3_snapshot_limits`. The new boundary module contributes 17 tests. Ruff lint
and format checks, mypy (114 source files), Bandit, append-only trial validation
against the full base commit and `git diff --check` passed. Report validation
reported zero problems, with its pre-existing historical unverifiable-hash notices.

A full-suite attempt started before edits, displayed one unidentified failure at
14%, and was interrupted before a failure traceback/summary was emitted. Because
the tree changed during that attempt, it is not baseline or final-tree evidence.
No complete local suite pass is claimed; independent CI remains necessary. The
first trial-validation invocation used a symbolic base and was rejected; repeating
with the full base commit passed. No dependency audit or Python 3.12 suite was run
in this worktree. No actual collector retry was attempted.
