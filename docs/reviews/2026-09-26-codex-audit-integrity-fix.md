# Codex → Claude handoff: PR #70 verified archive boundary

Code and tests checked at `8c42ef8d696e87261c43e2f3203946c444385a27`, including
main `96a2a1662a45cccb82569446ee681e90b7d38f35`. This addresses the P1 finding in
[PR #70](https://github.com/mgalic01/adaptive-market-engine/pull/70#issuecomment-5846313586).
The owner authorized Codex to continue corrections while Claude is unavailable.

## Finding and correction

At the reviewed head `e172a936093a06fcaa4486ea2b066fedd0abcea4`, the audit caught
every `DataError` from `fetch_file` as an ordinary parse failure. A synthetic cached
archive followed by a changed, nonmatching published checksum reproduced the defect:
both parser rules reported the stale local data as usable after verification failed.
Bob and the automated Claude review independently confirmed the failure path.

`fetch_file` now raises `ArchiveParseError`, a `DataError` subclass, only around the
archive-reading/parsing operation after its existing checksum and hash verification.
The audit catches only that subtype. Missing or malformed checksums, missing bodies
and mismatched hashes propagate immediately; the audit never reads the raw cache
after those failures. No error-message classification is used.

Successful return values and manifest fields are unchanged. Existing callers that
catch `DataError` still catch verified parse failures. The original parse message and
cause are preserved. Transport retries remain bounded at four attempts; integrity
errors are not retried. The audit also checks the development-month boundary before
calling `fetch_file`, protecting both network and cache access at that entry point.

## Verification

- Synthetic fresh-cache and stale-cache cases cover changed checksums, malformed
  checksums, an archive published without a checksum, and a checksum without its
  archive body, through both outage and parser-rule runners. Each aborts before raw
  cache reads; request counts and absence of retry sleeps are checked.
- A hash-verified truncated close remains classified as unparsed and is usable under
  both repair rules after their existing checks, with fresh and cached archives.
- Transport exhaustion and eventual recovery exercise the exact four-attempt bound
  and 1/2/4-second retry schedule without sleeping or making network requests.
- A reserved-month request fails before either the fetch function or injected
  transport is called. No reserved market data is opened by this test.
- Independent Windows Python 3.12 suite: **375 passed, 2 skipped, 552 subtests passed**.
  The two skips are the existing Windows symlink-privilege limitations; Linux CI
  retains those checks.
- Ruff lint and format (61 files), mypy (39 source/script files), Bandit, report
  checking (five appendix hashes, zero problems), and `git diff --check` passed.

No real market archives, large replay matrices or paid task runs were used for this
verification. Claude's reported 82/99 parser counts and 14-event/58-hour calendar
were not independently rerun here; they remain separately attributed evidence.

## Scope and next steps

No parser repair policy, outage-fold policy, strategy decision, risk limit or profit
allocation changes. Paper-only execution and protected-profit accounting remain in
place. No additional compatibility issue is known beyond the intended propagation of
integrity errors where the audit previously continued.

Codex owns final current-head review, required CI and merge. Obtain Bob's verdict on
the pushed head; older verdicts do not cover this correction. Claude should read this
handoff when available and use the typed boundary for subsequent audit work. The
owner's parser-policy decisions and PR #33's three-agent research agreement remain
separate pending work.
