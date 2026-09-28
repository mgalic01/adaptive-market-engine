# Bob agent protocol

**At the start of every task, without exception:**

1. **Read the task fully** before taking any action.
2. **Decide explicitly** whether spinning up parallel subagents would improve the assessment or resolution of that task. Ask: would multiple independent angles give a better answer than one sequential read?
3. **If yes, spin them up** — 2–3 subagents in parallel, each attacking from a different angle (e.g. one reads the diff, one checks tests, one checks docs consistency).
4. **Synthesize their results**, then proceed with the work.

Never start execution before completing steps 1 and 2. The subagent decision is a deliberate gate, not an afterthought.

**Claims on PRs and issues** (owner request 2026-09-28; rules in `docs/AGENT_HANDOFF.md`, "Claims"). IBM Bob has no pre-command hook, so these three steps are the whole of Bob's enforcement. Follow them every time:

1. **Claim before starting work** on a PR that ends in a push, a merge or a review you are about to write. Post a comment whose first line is `**[Bob]**` and whose second line is `/claim <N>h <what>`, with N from 1 to 24.
2. **Check before every push or merge:** `python scripts/claims.py check <PR> --as "[Bob]"`.
   - Exit 1: another holder has the PR. Do not push or merge; comment on the PR to reach the holder.
   - Exit 2: claims could not be read. Do not merge.
3. **Release when your work is posted:** a comment with `**[Bob]**` on the first line and `/release` on the second.

The session-start hook lists the active claims. A red `claim-guard` status or a `claimed` label on a PR means someone else is working on it.
