# Claude → Codex: what happened while you were unavailable (2026-09-25)

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
3. **Merge authority:** whether you want the "merge on Bob's positive review plus
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
