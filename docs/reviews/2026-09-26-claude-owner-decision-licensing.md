# Owner decision: no GPL or AGPL code in this project

- **Date:** 2026-09-26. **Recorded by:** Claude. **Decided by:** the owner.
- **Question.** [`docs/START_HERE.md`](../START_HERE.md) step 1 lists "No GPL or AGPL
  code" among the rules that override everything, but no file recorded where that rule
  came from. The automated review of PR #68 raised it: unlike the other step-1 rules
  (paper-only, the reserved window, no tuning after results), it had no source in the
  repository. It came from the owner's standing instructions to Claude's session, which
  the repository could not show.
- **What was checked before asking.** Claude listed the licence of all 41 packages the
  project installs. None is GPL or AGPL. The only runtime dependency is `websockets`
  (BSD-3-Clause); the rest are development tools under MIT, Apache-2.0, BSD or PSF,
  with two under MPL-2.0 (`certifi`, `pathspec`). MPL-2.0 is a file-level copyleft and
  does not reach this project's own code. So the rule constrains nothing today.
- **Options put to the owner:**
  1. keep the rule and record it;
  2. drop it, allowing agents to reuse GPL or AGPL code.
- **Decision:** option 1, keep the rule.
- **Why it matters, in the owner's terms.** GPL and AGPL are copyleft licences: the
  code is free to use, but passing the program on obliges you to release your whole
  program's source under the same licence. GPL triggers on distribution (giving away
  or selling a copy); AGPL also triggers on letting other people use it over a network.
  - While the bot stays private and is run only by its owner, copyleft code would cost
    nothing: running it yourself is not distribution.
  - The rule is about keeping later options open. With GPL or AGPL code built in,
    selling a copy, sharing it, or running it as a service for others would each force
    a full source release under that licence, and licensing it on the owner's own terms
    would not be possible at all.
  - Removing copyleft code after the fact is expensive: the affected parts have to be
    found and rewritten cleanly, and the problem is usually noticed too late.
- **What it means:**
  - the step-1 rule in `START_HERE.md` stands, and now has this record as its source;
  - a new dependency or any reused code must be under a permissive licence (MIT,
    Apache-2.0, BSD, PSF) or a weak file-level copyleft such as MPL-2.0;
  - no change to code, configuration, the spec or the reserved window follows from
    this decision.
- **Not decided here.** The project itself still has no `LICENSE` file, so it is
  private and all rights stay with the owner. Choosing a licence to publish under is a
  separate decision, and this record does not pre-empt it.
