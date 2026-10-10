# Codex: verify Bob's requested revision against main activity

Index: Prepared PR194 follow-up: manual Bob triggers require the exact requested SHA as a recorded main push/merge head before the trigger; unavailable evidence fails closed. Offline fixtures precede any separately authorized workflow trial. Bob review and owner merge go remain required.

Purpose: preserve the reviewed inputs of a queued run. This integrates PR194 head
`897645c1d7ede32e52fea4f81467afdaa3448d8a` with main
`5fd961cace769bdfda9eed2fb5c86316247648e7`, on a separate Codex branch. It does not
modify Claude's branch or dispatch a task.

The older proposal's unresolved first-parent question is answered with positive API
evidence. A fast-forward A to C may contain intermediate B; B's ancestry is insufficient.
Manual requests require `after == requested SHA`, `ref == refs/heads/main`, an activity
type of `push` or `pr_merge`, and a timestamp no later than the trigger. Comment creation
is in the event; dispatch creation comes from validated workflow-run metadata. Nothing
substitutes a nearby merge or current main. Human approval remains separate.

Resolve checks out `github.workflow_sha`, so its verifier is from the executing workflow,
not from a potentially old requested task. Only that separate runner gets the read token
and activity responses. Resolve adds `actions: read` solely to read dispatch metadata.
The existing worker keeps `contents: read`, no persistent credentials, pinned checkout,
first-parent/task checks and object purge. Publisher remains on a fresh current-main
checkout, publishing one validated report. No new task file is introduced.

The lookup validates the entire current page and its Link, including records after a
match, then accepts positive evidence without fetching unrelated older pages. Thus a
recent proven head does not fail merely because the repository has a long history.
This is not a global history audit. It rejects duplicate JSON keys, malformed data,
failed requests, redirects, foreign pagination, cycles and unproven evidence beyond
20 pages of 100 records. Each request has a 10-second timeout and 2 MB body cap. API
retention is not assumed: an unprovable old revision is refused. There is no automatic
retry. Resolve rejection is a failed Actions job, without a worker, publisher or comment.

Fixture `tests/fixtures/bob-main-activity.json` records the first two entries observed on
2026-10-10 from `GET /repos/mgalic01/adaptive-market-engine/activity` with main ref and
page size two. It retains evidence fields and omits unused actor metadata. The API's next
Link used its canonical `/repositories/1384347674/activity` path and an opaque `after`
cursor; both that repository-id path and this repository's named path are supported.
Synthetic mutations of this fixture are explicitly test cases, not recorded events.

Offline tests cover the real Git fast-forward counterexample, exact merge/push acceptance,
future/wrong-ref/before-only rejection, pagination, unavailable pages and malformed rows,
limits, HTTP failures and redirect refusal. Workflow tests preserve the pinned checkout
and purge behavior. Exact verification results and final SHA belong in the handoff.

No live workflow trial has been performed. Before any such trial, obtain the required
latest-head independent review and the owner's explicit go for a trivial test task.
The existing owner merge-go condition on PR194 is not waived by this follow-up.

Local verification: Python 3.12.14 on Windows, with Git Bash and official jq 1.8.2.
Focused preflight passed lint, formatting (539 files), types (120 source files), Bandit,
report checks (0 problems), and all 67 tests in the activity/workflow files (40 + 27).
Command: `python -B scripts/preflight.py --tests tests/test_bob_revision_activity.py
tests/test_bob_task_workflow.py`. No network is used by these tests.

Full-suite status is **not a pass**. One superseded run loaded earlier tests before the
pagination review correction and showed two failures during mixed-revision execution;
it was interrupted without a final failure trace. A replacement broad run was stopped
at the coordinator's instruction to use stable focused evidence locally and the full
CI suite on the immutable published commit. Neither incomplete run is completion
evidence. The final focused run above used the unchanged final implementation.
