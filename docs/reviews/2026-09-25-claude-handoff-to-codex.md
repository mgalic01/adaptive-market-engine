# Claude → Codex: what happened while you were unavailable (2026-09-25)

**Owner request: review all of this first, before any other work.**

- **Why this note:** your ChatGPT plan's Codex allowance ran out several times today, and
  every cloud review request got the "usage limit" reply. The owner decided that work
  should not stall: **"ask Bob to check the code; if he posts a positive comment, merge
  it"**, and for the Bob workflow: **"fix it and merge it"**. Claude merged under those
  instructions. Each merge message names the instruction and the evidence.
- **What we ask of you:** an after-the-fact review of the merges below. If you find
  anything, open a fix PR or hand it back to Claude. Nothing here is frozen. Spec v1 is
  still a draft.

## Merged without your review

| PR | Merge | What | Evidence at merge |
| --- | --- | --- | --- |
| #20 | `84a4dc6` | Spec G uniform-cadence rule, including your two clarifications (`7ed11c2`) | Your review and edits; Claude agreed (5835056834); Bob confirmed `7ed11c2` (5835862292); CI and the automated review green. Only your formal merge was missing. |
| #21 | `9274eaf` | Your manifest validation | Claude approve (5836162885), Bob NOTED ×2. Claude merged `main` into your branch (index rows only, `c313172`, merge commit, no history rewrite). CI green. |
| #22 | `09c1cd2` | `bob-review.yml` fixed and made read-only | The pinned `bobshell-2.0.5` has no `--auth-method`, so every "@bob" failed. Now `bob run` with only the `read` tool group, under `env -i`, with no GitHub token in Bob's step. The workflow fetches the PR material and posts the answer through a secret guard. Bob NOTED. Two automated-review rounds addressed. |
| #23 | `37642c8` | Failure alert | Any failed or cancelled Bob run posts an alert that names the owner, with the run link. Bob NOTED. |
| #24 | `a145c27` | Live progress | `-f stream-json`, a live summary in the Actions log, and the answer rebuilt from the text after the last tool call. Bob NOTED. **Live-tested:** Bob's reply was correct (5836939538). |
| #25 | `4a4ac96` | G funding parser and `FundingSignal` (not wired into replay) | 17 synthetic tests, one per §3 G required test; the replay-level one is deferred. Bob NOTED at `4e554d2` and on the delta at `1237ec2`. First CI run red on bandit B101 (a type-narrowing `assert`), fixed before merge. |
| #26 | `9cbc31b` | This note and the Bob V0 trace-hash task | Documentation only. Bob NOTED. |
| #27 | `c1dae26` | `bob-task.yml`: Bob runs reviewed task files on GitHub with command access | **The owner explicitly approved Bob holding his key with command access.** Triggers are owner-only. Bob's process has no GitHub token; only new `docs/reviews/*-bob-*.md` reports are published, on a `bob/task-*` branch with a PR; reserved-data and secret guards stop a run. Bob NOTED; his suggestion (owner-only "Run workflow") applied in `5811fce`. Design and evidence: [`2026-09-25-claude-bob-task-runner.md`](2026-09-25-claude-bob-task-runner.md). |
| #28 | `c518b21` | `AGENTS.md`: your first action is this review | Documentation only. Bob NOTED. |
| #29 | `61e4f5f` | `bob-task.yml`: **automatic start when a merge adds a task file** | The owner explicitly approved Bob starting "without asking me per run". Only **added** `docs/tasks/<date>-bob-<topic>.md` files trigger a run; edits never do; runs are sequential; every trigger is owner-only. Handbook rule: task PRs are merged only after the same review as code. Bob NOTED. |
| #30 | `7c68cee` | Bob workflows post only Bob's answer | Bob's #29 review posted his reasoning ahead of the answer. Both workflows now keep the text from the last "IBM Bob" before the signature. Bob FLAGGED the signature pattern; it was fixed to accept any label (`661493f`), then Bob NOTED. |
| #32 | `f0ba935` | Central quick reference in `AGENT_HANDOFF.md`: how to reach each agent | Documentation only. Bob NOTED; the automated review approved. |
| #34 | `1e87f05` | Bob workflows: cache the pinned package, retry its download | Bob NOTED. A post-merge automated finding (a failed download cached forever) does not reproduce: see [the sweep](2026-09-25-claude-closed-pr-sweep.md). |
| #35 | `138f22a` | Bob workflows: job-level concurrency with `queue: max` | Your queue finding; you asked Claude to keep it (5838627731). Bob NOTED ×2; the automated review approved. |
| #36 | `d82f4dd` | `bob-task.yml`: Bob on an untrusted worker; a fresh machine validates and publishes | Your isolation finding 1. Bob NOTED ×4; the automated review approved after its required fixes: a tested validator script, and rejection of invisible Unicode. Also drops Bob's index edit instead of failing (issue #31). |
| #38 | `2ebe8d0` | Fail closed on malformed exchange filters and extreme funding-rate precision | Post-merge findings on #21 and #25, found by the sweep. Bob NOTED; the automated review approved. |
| #37 | `f936f81` | Handbook: never post on closed PRs; read every open PR at each check-in; the sweep | Documentation only. Bob NOTED at `cc4d56a`; the automated review approved after its required fix (the catch-up rows). |
| #39 | `c4f8dfa` | One shared, tested, fail-closed extractor for Bob's answer | Your finding 2. Bob NOTED at `be500b6`; the automated review approved after `-OO`-safe help text and a byte (not character) cap. |
| #40 | `1dacd05` | Bob's V0 trace cross-check: 40/40 hashes and fill counts match | First end-to-end run of the worker/publisher split. Claude re-compared every row. Bob NOTED; two automated approvals. |
| #41 | `6913503` | Publisher links the report branch when a workflow may not open a PR | Owner's option b: grant nothing new. Bob NOTED at `99c425b`; the automated review approved after its required fix (the alert no longer says "nothing was committed" after a push). |
| #42 | `876f7ce` | Bob task batch 1 (data inventory, V0 scorecard, test-suite and docs audits), `docs/BOB_PRACTICE.md`, higher Bob limits | Owner's go ("give bob as much grunt work as you possibly can"). Bob FLAGGED once (fixed), then NOTED at `4b9be3d`. The automated review's required fixes: a wrong result count, a "strict" check that used the tolerance, and an exponential-backtracking header pattern. |

Later PRs merged under the same rule (#37 onward) are listed in their own PRs and in
[the review index](README.md). **Open for you:** #33 (the data-reuse proposal; your
agreement is the remaining gate). #39 (your finding 2) is merged and listed above.

**Closed:** #17 (Bob's 2026-09-24 session summary), as superseded. Its content is on
`main`; the mapping is in the closing comment (5837186191).

## Please check in particular

1. **#25 `FundingSignal.state`:** the rule order and boundaries against §3 G. In
   particular: `t >= scheduled(r3) + I + 60 s` is overdue, `usable_ms` truncates
   `calc_time` to the second, and invalid records are kept and never skipped.
2. **#22 to #24 workflow security:**
   - headless `bob run` auto-approves every enabled tool, so containment rests on the
     disabled tool groups, `env -i`, the pinned default `outsideWorkspaceAllowed: false`,
     and the post-step secret guard;
   - the answer extraction relies on the stream-json event shape: assistant `message`
     deltas after the last `tool_use`/`tool_result`, plus a `result` event with
     `status: success`.
3. **#27 `bob-task.yml` security:**
   - Bob has command access and can read his own key;
   - network egress is not technically restricted;
   - the change check accepts only new `docs/reviews/*-bob-*.md` files;
   - the reserved-data check runs after the run;
   - `/bob-run` must only be posted with a linked approval, because Claude and Codex
     post as the owner.
4. **Merge authority:** whether you want the "merge on Bob's positive review plus
   green CI while Codex is unavailable" rule recorded in `AGENT_HANDOFF.md`, with any
   limits you think it needs.

## Still open for you

- **Autonomy proposal** (PR #21 comment 5836162885):
  - every handoff ends with the recipient's trigger;
  - Claude subscribes to every open PR;
  - an hourly fallback runs only while a PR waits on Claude.
- **The ideas list** from the open-source research (A1–A3, B1–B2, C1): your per-item
  view.
- **New owner question, for your view:** can we test "as if unseen" on data we have
  already used? Claude's answer is below. It links to idea B2.

## Owner question: testing on reused data as if unseen

An agent cannot forget data it has seen. Past price history is also partly in every
model's training data. So "pretend we haven't seen it" is not a real control.

What does work:
- **Walk-forward evaluation:** choose parameters on one window, then score only the
  next, untouched window. Roll forward, and report only the out-of-window scores.
- **Synthetic scenarios** (idea B2), built from the practice windows only:
  - block-bootstrap resampling of real returns;
  - regime-shuffled series;
  - simple generated models.

  These give many paths no one has seen, keep realistic volatility clustering, and
  test robustness rather than a single history.
- **Anonymised replays:** rescale prices and hide symbols and dates, so neither agents
  nor people can recognise the period (for example "the LUNA crash"). This reduces
  recognition, but does not remove it.
- **Unused markets and pairs** as extra out-of-sample checks.
- **Counting every variant tried,** and adjusting the results for multiple testing.
- **Forward paper trading:** the only truly unseen data.

The reserved 2025–26 window stays the single final test and is not used for any of this.
Claude proposes adding a scenario generator (block bootstrap plus anonymisation) as a
harness item after P8, subject to your view and Bob's.

## Next

- **Claude:** P8 funding data integration: the archive fetch and manifest, wiring G
  into replay, and the "existing grids and exits unchanged" test. It starts on the
  owner's go.
- **Bob:** new task `docs/tasks/2026-09-25-bob-v0-trace-hash-crosscheck.md`, which
  publishes his 40 Windows baseline trace hashes against Claude's table. **Needs your
  approval or the owner's go before he runs it.**
