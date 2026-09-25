# Claude Code: start here

Read [the shared collaboration guide](docs/AGENT_HANDOFF.md), starting with its quick
reference on how to reach each agent, and
[the handoff index](docs/reviews/README.md) at the start of each session.
Then fetch the current branch state and read the relevant PR's Conversation,
inline review threads and checks. Local review files may refer to older commits.

Codex leaves messages in `docs/reviews/` and cross-links them in PR comments
headed **Codex → Claude handoff**. After each push, check the reviewed head SHA;
after merge, check the final merge SHA and outstanding items.

Reply in a new dated `claude-<topic>` review file and link it from the same PR.
State what you checked, what you agree or disagree with, and the evidence.
Posting a message does not establish that the other agent read it.

Closed and merged PRs are not watched: never post there, and at every check-in sweep
all PRs and issues, open or closed, for comments since the last sweep (quick
reference, "Never post on a closed or merged PR").
