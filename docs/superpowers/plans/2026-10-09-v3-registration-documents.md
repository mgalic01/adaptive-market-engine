# Committed registration documents

Goal: give the future historical dispatcher the exact committed manifest and
configuration validated by the completing registration, avoiding a second read
from mutable working files. This serves reproducibility, not permission to run.

1. Extend real-Git synthetic registration tests: require completion, return exact
   committed documents and identity, ignore dirty working copies, reject a newer
   unregistered implementation. First observe failure for the missing API.
2. Add a frozen result object and reader after check_ready; read the same full
   revision's Git blobs and retain spec/code/config/manifest identities. No CLI,
   archive read, fetch, execution, registration append or authorization changes.
3. Run register tests, static checks and independent review; send current head to
   Bob with test evidence. Required CI and substantive review precede merge.

Pre-flight: check_ready returns the validated completion; its registration ID
identifies the spec in the same committed register. Git objects use an immutable
full revision. Returned bytes must come from that revision, never Path.read_bytes.

Review focus: wrong revision, mutable checkout reads, losing pin provenance,
mistaking committed-code validation for attestation of a running interpreter.
