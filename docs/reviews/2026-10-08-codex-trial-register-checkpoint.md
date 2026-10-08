# Local implementation checkpoint: trial register

Index: Codex started the reviewed #210 register plan; retrospective parser and append-only prefix tests pass, with registration/readiness integration still outstanding.

Owner: Codex Desktop. Base plan f22f687b1d9212a11240ce85161a435146bee537.
Bob reviewed that plan NO ISSUES; this implementation has not had external review.

Implemented so far: strict JSONL parsing, duplicate-key/ID rejection, finite numeric
values, required retrospective fields, explicit not-preregistered semantics and
byte-preserving append validation. Empty history is permitted as the base of the
first append, not evidence of readiness. Unsupported event kinds are rejected.

Validation: 21 focused tests pass after formatting; Ruff, strict mypy and Bandit
pass on the new module. The initial test run failed because the module did not exist.
No full-suite/byte-identity result is claimed for this checkpoint. No strategy files,
data or workflow changed. No dispatch command exists.

Still required before publishing a ready implementation batch: registration,
completion and result/correction schemas; historical source inventory and initial
V3 registration; committed-pin verification; atomic writer and CLI; CI integration;
full repository checks, synthetic byte identity, and exact-head external review.
Preserve this as work in progress, not a finished register or an authorization to run.
