# Codex → Claude handoff: test provenance and Bob verdict review

- Date: 2026-09-27. Author/reviewer: Codex Desktop.
- Base: `94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a`.
- PR #84 reviewed head: `38a1836a5c4f4476f4e5f74bbfa6b1b7c05acd31`.
- PR #85 reviewed head: `b500e17af3098e8a03866f9829af2261f3fb4ed2`.
- Status: independent review completed; merge remains conditional on current-head
  checks, absence of new blockers and unchanged reviewed heads. Merge SHAs and
  completed gates will be posted on an open follow-up PR. This document does not
  claim either PR has already merged.
- Writer of this record: Codex, branch `codex/pr84-pr85-review-record`, Desktop
  checkout `work/crypto-grid-bot`. Claude retains its implementation branches.

## PR #84: tests must import this checkout

**APPROVE at the head above. No known required fixes in the reviewed scope.**

The pytest `pythonpath = ["src"]` setting places this checkout ahead of an installed
copy. The new guard compares the resolved package directory with this checkout's
source. I read the complete configuration and new test, including the assertion's
inputs. Runtime imports outside pytest are not changed or repaired by this setting.

Independent Windows Python 3.12 verification used a clean `git archive` extraction
of the exact head, outside Claude's working tree, and the existing review venv:

- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 162 files already formatted.
- `python scripts/check_reports.py`: six appendices, zero problems.
- `python -m pytest -p no:cacheprovider`: **389 passed, 2 skipped, 563 subtests
  passed**. Inherited PYTHONPATH and pytest argument/plugin overrides were removed;
  plugin autoload was disabled. This directly tests the pytest setting instead of
  relying on preflight's separate PYTHONPATH override.
- Negative/positive fixture: created an empty dummy `crypto_grid_bot` package in a
  separate temporary directory and exposed it through PYTHONPATH. Running only
  `tests/test_import_provenance.py` with `-o pythonpath=` failed with the other path
  in the assertion, as expected. The identical command without that override passed.
  No installed package, editable-install file or other agent's checkout was changed.

The guard proves the top-level package's location; it is not a general defence
against arbitrary plugins modifying submodule imports. Two Windows skips and the
Linux/other-environment boundary remain limits of this local run. Required GitHub
checks supply separate evidence. No data archive or strategy replay was run.

## PR #85: readable Bob verdicts

**APPROVE at the head above. No known required fixes in the reviewed scope.**

The change replaces the quick review's ambiguous clean verdict with `NO ISSUES`,
requires a full-head verdict and a scope line, and explains that reading a diff is
different from executing tests. Historical `NOTED` records retain their meaning.
The clean verdict is not new merge authority and does not supersede independent
review, checks or protected boundaries. Read all four changed files and their diff.

Independent checks on an archive of the exact head:

- Parsed the workflow YAML and checked the complete Bob run step with Git Bash
  `bash -n`: passed.
- Rendered only the prompt assignment with a minimal environment containing dummy
  repository, PR and commenter values. Confirmed both verdict forms and the scope
  example survive shell expansion. Did not execute the Bob command or supply keys.
- Compared parsed workflows against the base after substituting the old prompt:
  identical. The execution tail, trigger, permissions, credential isolation,
  publishing checks and failure alerts are unchanged.
- `python -m pytest -p no:cacheprovider tests/test_extract_bob_answer.py`:
  **36 passed**. The extractor validates answer structure, not verdict vocabulary.
- `python scripts/check_reports.py`: six appendices, zero problems.

This is a prompt contract, not a parser enforcing verdict grammar. A model can omit
the scope or choose the wrong words; readers must reject inadequate review evidence.
No live Bob run was performed for this review, and no claim is made that the new
format has already been observed from Bob. Current-head CI and the automated Claude
review are separate checks; the full suite was not repeated locally for this
prompt-only change after the focused checks passed.

## Security, compatibility and safe next steps

No new security finding in either reviewed diff. No runtime trading, persisted data,
profit accounting, task authorization or reserved-window policy changes. A source
revert restores the prior test configuration or prompt; no data migration is needed.
Passing checks are not a certification of security or strategy performance.

Codex owns merging #84/#85 once final GitHub checks and discussions confirm readiness,
then posting the merge SHAs and this handoff on an open follow-up. Claude owns #83's
remaining prose correction: the supplied fetcher requests checksums even for cached
archives. Preserve its historical appendix bytes. #74 still needs its named writer
to consolidate the corrected proposal and resolve the index conflict, followed by
all three agents' acknowledgment; it is not adopted here.

The owner explicitly instructed Codex today to continue authorized actionable work
after a status check instead of stopping at a summary. AGENTS.md records that default
with the existing ownership, review and safety gates intact. This grants no new data
access, strategy experiment, monitoring loop or implementation authority.

**Review requested:** Claude or Bob should review this record's exact PR head for
overstated evidence, incorrect scope and consistency of the startup instruction.
Codex will not merge its own record without that external substantive review and
passing required checks. No additional measurement task is requested.
