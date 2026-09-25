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
   already has a pending/completed Codex review. Reply on the setup PR for concerns.

No runtime or stored-data migration. Reverting the documentation change restores
the previous instructions without changing balances or repository settings.
