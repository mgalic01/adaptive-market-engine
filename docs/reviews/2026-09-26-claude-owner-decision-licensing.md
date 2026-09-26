# Owner decision: no GPL or AGPL code in this project

- **Date:** 2026-09-26. **Recorded by:** Claude. **Decided by:** the owner.
- **Question.** [`docs/START_HERE.md`](../START_HERE.md) step 1 lists "No GPL or AGPL
  code" among the rules that override everything, but no file recorded where that rule
  came from. The automated review of PR #68 raised it: unlike the other step-1 rules
  (paper-only, the reserved window, no tuning after results), it had no source in the
  repository. It came from the owner's standing instructions to Claude's session, which
  the repository could not show.
- **What was checked before asking.** Claude read the declared licence metadata of the
  41 packages installed from `requirements-dev.lock`. None declared GPL or AGPL. The
  only runtime dependency is `websockets` (BSD-3-Clause); the rest are development
  tools declaring MIT, Apache-2.0, BSD or PSF, with two declaring MPL-2.0 (`certifi`,
  `pathspec`). On that basis the rule constrains nothing today.
  **Limits of that check:** it read each package's own declared metadata at one point
  in time. It is not a licence audit: it did not inspect bundled or vendored code,
  transitive native components, or files whose headers differ from the package
  declaration, and Codex did not independently reproduce it (PR #80 review). Treat it
  as a screen, not a certification.
- **Options put to the owner:**
  1. keep the rule and record it;
  2. drop it, allowing agents to reuse GPL or AGPL code.
- **Decision:** option 1, keep the rule.
- **Why the owner keeps it.** GPL and AGPL are copyleft licences: they can attach
  source-availability obligations to software that incorporates them. The two differ
  in what sets those obligations off — broadly, conveying the software for the GPL,
  and additionally remote network interaction under AGPL section 13. Whether any
  obligation arises at all, and what exactly it covers, depends on the specific
  licence, on what counts as a combined or covered work, and on how the software is
  conveyed or offered.
  - The owner's preference is to **avoid acquiring future copyleft obligations and to
    preserve commercial flexibility**, rather than to analyse those conditions case by
    case later.
  - Running the bot privately for oneself is not the situation the rule guards against;
    the rule protects the options that come later, such as distributing it or offering
    it to others.
  - Removing copyleft code after the fact is expensive: the affected parts have to be
    found and rewritten cleanly, and the problem is usually noticed too late.
  - **This record is not legal analysis** and does not attempt to state the obligations
    of any licence. It records a risk preference. See the
    [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html) and
    [AGPL-3.0 section 13](https://www.gnu.org/licenses/agpl-3.0.html) for the actual
    terms; a real licensing question goes to a person, not to this file.
- **What it means:**
  - the step-1 rule in `START_HERE.md` stands, and now has this record as its source;
  - a new dependency or any reused code must not be under the GPL or the AGPL. That
    is the whole of what was decided. The licences already in the tree (MIT,
    Apache-2.0, BSD, PSF, and MPL-2.0 for two development tools) all satisfy it;
  - no change to code, configuration, the spec or the reserved window follows from
    this decision.
- **Not decided here.** Licences that are neither permissive nor GPL/AGPL — the LGPL
  and the EPL are the ones likely to come up — are **not** covered by this decision.
  An earlier draft of this record listed an allowed set of licences, which would have
  excluded them by implication; the automated review of PR #80 caught that it stated a
  stricter rule than the owner gave. If such a dependency is ever proposed, it is a new
  question for the owner, not something this record settles.
- **Not decided here.** The project has **no `LICENSE` file**, so no publishing
  licence has been chosen for it. That is a separate matter from the repository's
  visibility setting, which this record does not describe, and it does not resolve the
  ownership of any third-party material. Choosing a licence to publish under is a
  separate decision, and this record does not pre-empt it.
