# Claude → Codex and Bob: bob-review.yml fixed (read-only Bob)

- **Status:** separate PR, merged by Claude at the owner's explicit instruction
  ("you should fix it and merge it", 2026-09-25). Codex: please review after the fact.
- **Symptom:** every "@bob" call since the version pin failed within a second:
  `error: unknown option '--auth-method'` (run 36155268937, PR #20).
- **Cause:** the old install script fetched the newest Bob Shell, which had
  `--auth-method`. The pinned `bobshell-2.0.5` does not; it reads `BOBSHELL_API_KEY`
  from the environment by itself.

## Change

- `bob run` (headless) replaces `bob -p`; `--auth-method` is removed.
- **Bob is read-only.** In 2.0.5, headless mode auto-approves every enabled tool, so
  the old design would have given Bob a shell holding `GITHUB_TOKEN` while reading
  comment text. Now:
  - every tool group except `read` is disabled (`edit`, `execute`, `browser`, `mcp`,
    `skill`, `subagent`, …), with `--disable-mcp` and `--disable-subagents`;
  - Bob's step has no GitHub token in its environment;
  - a previous step (with the token, without Bob) writes the request, the PR metadata
    and the diff into `.bob-input/`;
  - a following step posts Bob's final message (`-f json`, `type: result`,
    `last_message`) as one comment with `GITHUB_TOKEN`, which triggers no new runs.
    No answer → the step fails and nothing is posted.
- Unchanged: the whole-word `@bob` gate, OWNER/MEMBER/COLLABORATOR only, the pinned
  package and its SHA-256, `--ignore-scripts`, the comment as data only.

## Evidence

- Pinned package unpacked (SHA-256 `eff232eb…f566` matches): `bob run --help` lists every
  option used; tool groups are `read, edit, execute, browser, mcp, skill, todo, artifact,
  subtask, subagent, mode`, and unknown names are ignored, not rejected.
- The full command line with a dummy key parses (no option error) and then waits on the
  network; this container cannot reach IBM's service. **The first real "@bob" call is
  the live test.**
