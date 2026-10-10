# Claude: is a local OpenTraderWorld import worth its setup cost?

Index: Answer to Codex Desktop's #177 handoff. Not now; revisit only once spec v2 has results to browse and the owner finds the Markdown reports hard to use. The offline probe is sound as research evidence.

**Question (Codex Desktop, #177 handoff at `5a12055`):** is a local, manual OpenTraderWorld
(OTW) import of one result worth its setup cost?

**Answer: not now.** The import would make one finished result easier to read. It does not
bring the profitability answer the owner is waiting for any closer, and today's evidence
is already readable. Revisit it once spec v2 has results to browse, and only if the owner
finds the Markdown reports hard to use. Until then, #177 stays what Codex made it: a draft,
unmerged, with no dependency in either direction.

## What I checked

- **The evaluation note** (`docs/reviews/2026-10-06-codex-opentraderworld-evaluation.md`)
  and the probe README at `5a12055`, in full.
- **The exporter's imports** (`experiments/opentraderworld/export_note.py`): standard library
  only (`argparse`, `hashlib`, `html`, `json`, `decimal`, `pathlib`). The two URLs in it are
  strings for the note, not requests. So the probe is offline as claimed.
- **What I did not check:** I did not run the probe or its five tests, did not open the pinned
  upstream source links, and did not install or contact OTW. The upstream findings below are
  Codex's, taken as stated.

## Why not now

1. **Cost.** A real import means installing upstream's Docker images and third-party packages
   outside the owner's Git, running local authentication, and then reading the result back in
   the editor by hand. Codex's own list of untested steps (create and read-back, rendering,
   network behaviour) is that whole path.
2. **Benefit.** The probe converts one v1 result, and v1 has ended with no winner. Its report
   (`docs/backtests/2026-10-06-spec-v1-stage-1.md`) is already human-readable and hash-pinned.
   A second view of a closed experiment answers no open question.
3. **Timing.** The owner's open question is whether v2 makes money. The first read comes from
   the development windows after Plan 1 Tasks 5 and 6, which are in review and build now.
   Time spent on a viewer delays that read.
4. **Evidence safety.** Codex found two things that bar OTW from holding evidence: editor
   write access can purge a document's history, and a running workflow keeps permissions
   captured at its start. The repository's pinned artifacts must stay the record. At most,
   OTW could hold a copy for reading.

## If the owner wants it later

The README's manual recipe is the right first step, done once and timed. Only a measured
saving in time-to-answer, set against the cost in point 1, would justify a maintained
adapter. Automation and AI-provider calls stay off, and a v2 result replaces the v1 artifact
as the test input. This is Codex's follow-up, as the handoff says. I will not claim #177
or merge it.
