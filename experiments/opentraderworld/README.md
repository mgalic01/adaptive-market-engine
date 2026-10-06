# OpenTraderWorld: disposable feasibility probe

This is an offline experiment, not an installed integration, a general importer or
part of the bot. It prepares one **historical development result** as an external
research note. No OpenTraderWorld code is copied, no new dependency is required,
and the exporter performs no network requests or engine calls.

## Reproduce

Obtain only `results.json` from the `backtest-practice-2022` artifact of
[workflow 37441444046](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37441444046).
The exact source SHA-256 is
`a78ea9282cb01f451cab73dfc02d254c9eaaf7115ff5439be0506f92404d89a2`, independently
pinned in the [committed stage-1 report](../../docs/backtests/2026-10-06-spec-v1-stage-1.md).
Artifact retention is limited; expiry is not permission to replace it with another run.

```powershell
python experiments/opentraderworld/export_note.py <results.json> <new-output-folder>
python -m pytest experiments/opentraderworld/test_export_note.py -o addopts= -q
```

The source must match that exact hash. Output folders must not already exist.
Keep generated bundles outside the repository; the historical source is several MB.
The source file stays unchanged, and the bundle contains a byte-identical copy.

Outputs:

- `preview.html`: offline readable row overview and expandable full diagnostics;
- `note.txt`: viewing copy with source references, every metadata field and result row;
- `create-page.json`, `update-page.json`: **unsent** document API request bodies;
- `results.json`: exact original evidence, including hourly equity arrays;
- `bundle.json`: hashes of the above files and the pinned upstream revision.

Only hourly-equity arrays are omitted from the note. JSON numeric decimals become
exact strings in its excerpts; the original file preserves the original types and
bytes. No returns are recomputed. Integrity-valid does not mean the experiment
passed; v1 ended with no winner. All gated/ungated/benchmark rows remain present.

The fixed run is deliberate: changing the hash to accept another run requires a
new evidence review. This is throwaway proof of transport feasibility, not a
supported adapter API. No files are sent to the public demo.

## Later local application test — not performed

The source-reviewed API contract at upstream
`a3383baff1b5bb6d78c349437c45fbbe32cd4836` is:

1. With a local authenticated session, `POST /api/documents` using `create-page.json`.
2. Read `document.id`; `PATCH /api/documents/<id>` using `update-page.json`.
3. `GET /api/documents/<id>` and compare the returned document content with the payload.
4. Inspect the UI, especially the multiline text, negative returns, exclusions,
   benchmark label and no-winner warning. Reload and compare again.

These are a manual verification recipe, not commands this exporter executes.
Only count the local test as passed after successful persistence, read-back and
visual inspection. Plain text in one paragraph may need structural paragraphs to
render line breaks usefully; that remains unverified.

Do not enable workflows, market-data connectors, AI providers or trading for this
test. Any later agent gets editor read permission only. The original evidence and
its trusted hash remain outside OTW: its editable history is not an immutable archive.
Our bundle checksums detect differences against a retained trusted manifest; they
are not cryptographic signatures or tamper-proof storage.

See the [evaluation and source findings](../../docs/reviews/2026-10-06-codex-opentraderworld-evaluation.md).
