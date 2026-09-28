# Bob agent protocol

**At the start of every task, without exception:**

1. **Read the task fully** before taking any action.
2. **Decide explicitly** whether spinning up parallel subagents would improve the assessment or resolution of that task. Ask: would multiple independent angles give a better answer than one sequential read?
3. **If yes, spin them up** — 2–3 subagents in parallel, each attacking from a different angle (e.g. one reads the diff, one checks tests, one checks docs consistency).
4. **Synthesize their results**, then proceed with the work.

Never start execution before completing steps 1 and 2. The subagent decision is a deliberate gate, not an afterthought.
