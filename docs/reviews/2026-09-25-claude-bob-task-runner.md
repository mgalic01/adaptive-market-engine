# Claude → Codex and Bob: `bob-task.yml`, Bob runs task files on GitHub

- **Owner approval (2026-09-25):** "yes, I approve Bob running commands on GitHub with his
  key because bob can then work other tasks as well not just the trace-hash reruns".
  The owner accepted, in full knowledge, the risk that Bob can read his own key.
- **Codex:** please review after the fact, with the workflow-security points below.

## Design

- **Trigger:**
  - an owner-account comment `/bob-run docs/tasks/<date>-bob-<topic>.md`, where the path
    is checked against a strict regex and must exist on `main`;
  - or `workflow_dispatch`.

  The keyword is not "@bob", so the read-only reviewer does not fire as well.
- **Bob's step:**
  - Linux (`ubuntu-latest`), Python 3.12 with the project installed from the lock file,
    and the pinned, hash-checked `bobshell-2.0.5`;
  - `env -i` with only `PATH`, `HOME` and the key: no GitHub token and no runner
    credentials;
  - the read, edit and command tool groups are on; MCP, browser, subagents and modes
    are off;
  - at most 300 turns, a 120-minute job timeout, and a live stream-json log of every
    command.
- **After Bob:**
  - no archive for 2025-01 or later may exist, or the run fails;
  - the only accepted change is new `docs/reviews/YYYY-MM-DD-bob-*.md` files;
  - the secret guard runs on the reports and on Bob's summary;
  - the workflow commits to `bob/task-<slug>-<run id>`, opens a PR (created with
    `GITHUB_TOKEN`, so CI does not start on its own) and replies where the run
    started.

  Any failure alerts the owner.
- **Data cache:** `data/` is cached, keyed on `config/datasets/**`.

## Evidence (local)

- Every `run:` script passes `bash -n`.
- **Gate:**
  - the real task path is accepted;
  - `docs/tasks/../../etc/passwd.md` is rejected;
  - "@bob run it" is rejected;
  - a trailing `; rm -rf /` is never executed: only the regex-checked path is kept.
- **Change check, in a scratch repo:**
  - a valid report is accepted;
  - allowed 2024 data is accepted;
  - no report gives no PR;
  - a modified tracked file, a non-Bob review file, a 2025 archive and a secret in
    the report are all rejected.

## Not tested

- **A real run:** the first `/bob-run` is the live test. A good candidate is
  [the V0 trace-hash cross-check](../tasks/2026-09-25-bob-v0-trace-hash-crosscheck.md),
  after Codex's approval or the owner's go.
- **Known limits:**
  - Bob can read his key;
  - network egress is not technically restricted, only by rule and by the reserved-data
    check after the run.
