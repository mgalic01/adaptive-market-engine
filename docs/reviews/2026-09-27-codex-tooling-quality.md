# Codex → Claude handoff: restore tooling quality checks

2026-09-27. Writer Codex; isolated branch codex/restore-tooling-quality.
Base main 0bb28574b8554f337bd4128b852d5a4080302c59 introduced the Bob hook and
Superpowers installer directly; their lint, formatting, type and Bandit failures
block subsequent PRs, including the separately reviewed local worker PR #94.

## Finding and repair

P2: reproduce with ruff check ., ruff format --check ., mypy src scripts and
bandit -q -r src scripts. The hook has an unused math import and formatting errors;
the installer lacks a return annotation and formatting. The URL-open finding is a
static-analysis false positive for scheme selection here: the URL is constructed
only from a fixed HTTPS raw.githubusercontent.com template and a literal skill list.
A narrow B310 annotation explains that invariant. No user-provided URL is accepted.

Remove the unused import, format the two files and add the return type. No behavioral
change, new dependency, download, hook execution, trading/data access or accounting
change. Existing installer use of upstream main is unchanged; this quality repair
is not an audit or integrity endorsement of downloaded skills.

## Verification and next owners

Exact full-head results and Claude/Bob review are recorded on the PR before merge.
Codex owns fixes and the deliberate merge decision; Claude/Bob independently review
this narrow diff. No own-work merge until substantive latest-head external feedback,
required checks and any blocking findings are resolved. PR #94 then integrates the
repair and obtains its own current-head review. No automatic merge controller.
