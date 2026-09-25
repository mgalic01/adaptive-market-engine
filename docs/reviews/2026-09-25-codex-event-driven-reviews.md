# Codex → Claude and Bob: event-driven cloud review handoffs

- Date: 2026-09-25. Author: Codex. Recipients: Claude and Bob.
- Base: `bf4959281ee5c9a790517596b0c46a19a84d182d`.
- Branch: `codex/event-driven-review-handoffs`. The PR records the pushed head,
  delivery evidence, checks and eventual merge status.
- Owner request: have Claude/Bob's ready handoffs trigger separate Codex cloud
  reviews instead of frequent repository checks. The owner explicitly accepted
  that these do not resume this desktop conversation.

## Changes and verification

The collaboration guide now specifies one explicit Codex review request per ready
head, with the exact SHA and handoff link, skipping duplicate requests when an
automatic review already exists. It distinguishes a sent request, acknowledgment,
review completion and approval. This documentation change is indexed here.

The official GitHub integration documentation supports PR comments containing
`@codex review`. Existing PR #16 has earlier Codex cloud reviews, establishing that
the repository has used the integration. A new request's delivery is verified on
this PR, rather than inferred from those historical reviews.

Local validation: whitespace/diff and relative Markdown-link checks. Runtime tests
are not necessary for this documentation-only change. GitHub checks and reviewer
results are reported on the PR when completed. No historical replay, exchange
connection or performance experiment is run for this setup.

## Authorization and delivery evidence

Source: the owner's private Codex conversation on 2026-09-25, transcribed by Codex.
This is an agent-recorded owner instruction, not a separate owner-authored GitHub
document. No public link to the private conversation is available in this record.

- Codex asked: "Would you like **Codex cloud reviews triggered by Claude/Bob's
  handoffs**, even though they run separately from this conversation?"
- The owner replied: "yes i would like that".

This authorization covers the handoff protocol, not strategy approval or PR #16's
merge. It is unrelated to Bob's historical strategy proposals flagged in the index.

The official URL `https://developers.openai.com/codex/integrations/github` was
opened on 2026-09-25 and redirected to
`https://learn.chatgpt.com/docs/third-party/github`. Its "Request a Codex review"
section explicitly specifies a PR comment containing `@codex review`, followed by
the eyes reaction and a review. The unfamiliar redirected host is not inferred to
be authoritative merely from its name; it is the destination of the official URL.

Independent operational evidence: on PR #18, the Codex connector bot reacted with
eyes to [the request](https://github.com/mgalic01/crypto-grid-bot/pull/18#issuecomment-5830388266)
at 2026-09-25 09:51:42 UTC. This confirms acknowledgment, not completion or approval.
Quality passed on initial head `df3c67c`. Claude requested source and authorization
provenance; this section answers both without publishing the private conversation.
The PR records subsequent review/check results for the updated head.

Codex cloud completed its review of `df3c67c` and identified a duplicate-request
edge case: an existing request without acknowledgment must also block reposting.
The guide now explicitly checks request comments as well as reviews. This closes
the gap while retaining the instruction to report an unresponsive integration.

## Findings and limits

No known required fixes in the reviewed documentation scope. No new security
finding, credential, dependency, workflow or permission change. No claim is made
that cloud review alone proves correctness or security. Existing merge gates,
paper-only behavior, protected profits and the reserved-data owner gate remain.

Optional improvement: none needed for the selected handoff protocol. It relies on
the author posting the ready-handoff request; it is not an every-push webhook and
does not change account-level automatic-review settings.

## Next steps and compatibility

1. Codex posts the setup PR and records delivery/review evidence there.
2. Claude reviews the protocol and preserves this section/index entry when bringing
   main into PR #16. Bob uses the same protocol for his report PRs.
3. Claude/Bob include the request after their next ready push, unless the same head
   already has a request or pending/completed Codex review. Reply on the setup PR
   for concerns.

No runtime or stored-data migration. Reverting the documentation change restores
the previous instructions without changing balances or repository settings.
