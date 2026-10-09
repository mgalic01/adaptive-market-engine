# Owner decisions: V3 storage and full-size hold purchase timing

Index: Owner selected E: storage and next available first-purchase bar; no download start was authorized.

On 2026-10-09 the owner answered the clickable questions:

- "Where should we store the historical market-data archives? Selecting a drive
  does not start the download." Answer: **"E: drive (Recommended)"**.
- "If the buy-and-hold comparison's first scheduled purchase bar is missing,
  what should happen? Buying at the next available bar changes entry timing and
  approves that exception to the frozen rule." Answer:
  **"Buy at the next available bar (Recommended)"**.

## Storage

Use a dedicated root `E:/adaptive-market-engine/v3` for retained V3 archives and
delivery metadata, with separate fresh attempt directories. This is a selected
location, not a fetch command. No download, historical replay, reserved-window
access or change of executor was authorized by this answer. The reviewed data
task still requires owner start and confirmation that its executor can access E:.
The owner retains and backs up the local data; Git holds its provenance and pins.

## Full-size hold diagnostic

Amend the frozen section 8 purchase timing for this reported-only comparison:
for each coin in the portfolio at the first test quarter's start, buy at the first
available unmasked spot hour at or after its scheduled 01:00 purchase. Preserve
that coin's original equal share of starting cash, including fees, while waiting;
do not redistribute it or add later-joining coins. Record scheduled and actual
purchase timestamps. Never use a 2025-or-later bar. If there is no purchase bar
before the experiment ends, report the diagnostic unavailable with the coin and
reason; never invent a price or silently omit the coin.

Disclosed downside: entry times can differ across coins, changing the comparison's
exposure and return. This changes only the reported full-size hold timing, not
the risk-matched benchmark, futures strategy, A1-A5 or the reserved-data gate.

Commit the amended spec and a replacement candidate registration before its
implementation. No historical V3 data or results were inspected for this ruling.
