# Offline V3 report publication plan

Base: c906216621da0e0f21f7768436b48c086a89a95b.

Goal: preserve the existing uncertified ExperimentReport as JSON and Markdown,
linked to supplied registered identities and a verified snapshot of local attempt
evidence. No runner, serializer, registration or verdict behavior changes.

1. Add synthetic fixtures and failing publication/verification tests (no replay).
2. Add scripts/v3_report_publication.py: validate supplied document pins, retain all
   report prerequisites, inspect journals/artifacts, reject pending/orphan evidence.
3. Exclusively create report/ under existing evidence; write/fsync both report files,
   recheck attempts and files, publish an atomic create-if-absent receipt last.
4. Reader requires a separately retained receipt digest and matching documents;
   validate receipt/files/attempts. Failures retain partial files, never overwrite,
   repair, resume or retry. Root journal JSON namespace remains unchanged.
5. Run stable focused tests and static checks, write indexed handoff, commit locally.

Limits: supplied documents must come from committed registration validation; their
shape/pins alone do not prove provenance. Captured attempts are observed local
history, not all historical attempts or proof that report values derive from them.
Final verdict, scenario reconciliation, runtime checks and access authorization
remain separate. Single-writer cooperative use; no security or power-loss guarantee.
