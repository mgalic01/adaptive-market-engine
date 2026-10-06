# Codex: OpenTraderWorld companion research evaluation

Index: Offline one-artifact probe; Reddit concerns checked against pinned source. Companion notes feasible; app import and deployment unverified. No engine change.

## Purpose, ownership and decision

Make completed experiment evidence easier to find and understand without changing
the experiment, its results or the criteria that decide whether the bot is worth
building. This is the proposed benefit against the project's small-capital economics;
there is no demonstrated return improvement from a dashboard.

The owner requested a separate branch and two agents while Claude works on v2, then
asked us to include the entire Reddit discussion and other people's feedback.
Codex Desktop is the sole writer on `codex/opentraderworld-evaluation`, isolated in
`C:/Users/Marko/.codex/worktrees/otw-evaluation`. Two read-only subagents examined
upstream integration/security and AME result fidelity, then criticised the probe.
Base: `ecabad046c5585d2473cc37661b2004fba9918ef`.

**Decision: proceed only with a small companion-note evaluation.** The offline
transformation works. There is no reason established here to replace our backtester,
deploy automated writes, or add a maintained integration. Whether the app actually
saves research time remains unmeasured. The prototype is disposable and outside
the installed package and default test discovery.

Current project context is important: v1 has already ended with **no winner**;
[its completed report](../backtests/2026-10-06-spec-v1-stage-1.md) records every
variant failing C2. Spec v2 is now the active experiment. This probe changes neither
spec, any strategy, fees, datasets, scorer, acceptance rules nor workflow.

## What the discussion adds

Read the [post and expanded newest-first replies](https://www.reddit.com/r/ai_trading/comments/1wvlmtc/how_i_automated_strategy_research_and_discovery/?sort=new&limit=500),
including the visible nested replies. Deleted/moderated text is unavailable; this
is not a claim to have recovered it or future comments.

- **Immutable inputs:** leroylabs asks for code, indicator, data and fee hashes;
  the author acknowledges the gap in that reply. We retain our own pinned artifact.
- **Research history:** QuanTradin argues for preserving earlier beliefs and marking
  notes before/after results. The author describes optional versioning. Our note is
  explicitly post-result, with the original preserved outside the app.
- **Permissions:** CODE_HEIST asks about privilege separation, revocation during
  queued work, and approvals surviving strategy edits. These become concrete
  source-review questions below.
- **Backtest credibility:** commenters describe late-discovered bugs, costs,
  survivorship and attractive dashboards without convincing performance. Those
  anecdotes motivate tests; they do not establish a defect in this repository.
- Positive feedback concerns organization and modular agents; some comments also
  promote other products. None supplies independent performance or security evidence.

## Source inspection, pinned to avoid roadmap claims

Upstream inspected: **`a3383baff1b5bb6d78c349437c45fbbe32cd4836`**, labelled v0.0.15.
Source was read, not installed or executed. No vendor registration, credentials,
Docker deployment, browser login, AI provider or market connector was configured.

| Area | Evidence and implication |
| --- | --- |
| Import | [Document request bodies](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/documents.rs#L16-L106) support creating a page and patching Tiptap content. No native AME results import was established. Our request bodies are prepared, not sent. |
| Agent access | [Editor catalog](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/mcp/catalog.rs#L582-L601) exposes document operations through module-scoped permissions. A later research reader needs editor read only. Import by a human session is separate. |
| History | Current source already has optional versioning, so the Reddit future-release statement is stale. However, editor `rw` can invoke the per-document versioning POST with `enabled:false,purge:true`; [handler](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/versioning_api.rs#L175-L214). This is not append-only evidence storage. The global toggle uses a different, no-purge body. |
| Revocation | [Workflow startup](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/automator/engine.rs#L67-L71) loads permissions; [later nodes](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/automator/engine.rs#L156-L168) reuse that snapshot. Source indicates revocation does not remove permissions already captured by a running workflow. This is a source finding, not a reproduced runtime exploit; queued-but-not-started work is a different case. Keep automation disabled pending a controlled test. |
| Backtest provenance | [SavedRun](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-store/src/backtest.rs#L14-L43) stores settings, statistics, identifiers and engine semantics, but that schema does not establish content-addressed snapshots of every input. AME's evidence remains authoritative. |
| Local deployment | [Compose bindings](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/deploy/docker-compose.yml#L33-L66) default to loopback but can be overridden. Local authentication exists. No vendor account is different from no local account. This is not a security certification or network audit. |
| Privacy | A selected remote model provider receives the content sent in model requests. Self-hosting alone is not proof that research stays local. No model calls occurred in this probe. |
| License | [FSL-1.1-MIT](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/LICENSE) explicitly permits internal use, restricts competing commercial uses, and grants MIT after each version's second anniversary. We copied no implementation or dependencies into AME. Commercial redistribution would need its own assessment. |

The [documented backtester](https://g-otw.github.io/OpenTraderWorld/modules/market-data)
also uses different execution assumptions, including opening-price improvement for
some limits and a constant annual funding-rate estimate. It cannot be substituted
for our official replay or establish V3 futures realism through this evaluation.

## Executed probe and actual evidence

Dependency boundary, answering the owner's follow-up: the probe's runtime needs only
local Python and its standard library. Tests use the repository's existing pytest.
No new package or service dependency was added. The historical input was in the
owner's GitHub Actions artifact storage, not Git history; a local exact copy is now
preserved. Upstream source was read in a separate scratch clone, not vendored. A real
OTW installation would introduce upstream Docker images and third-party packages
outside the owner's Git; that installation was not performed.

The [probe instructions](../../experiments/opentraderworld/README.md) describe the
deliberately single-artifact scope. It has no HTTP client, credentials, model calls,
engine imports, strategy execution or performance recalculation.

Downloaded GitHub Actions artifact **11402944133** from
[workflow 37441444046](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37441444046).
Listed its ZIP members and read only
`20261006T095243Z-m0-t0.0009/results.json`. No archive of market candles was opened.
The SHA-256 matched the committed report's independent pin:
`a78ea9282cb01f451cab73dfc02d254c9eaaf7115ff5439be0506f92404d89a2`.

The source records `practice-2022`, code commit
`f14451014001b78cf63ac036b5eaad5b126c400c`, source hash
`c207dfbe979fec711f7694841b2dc441b8b80f4a3a6145da4614f3e042af7132`, fees, and separate
spec/manifest/config hashes. Its 12 rows include both paths, baselines and D.
SOLUSDT's exclusion is retained. Integrity-valid is visibly distinguished from
passing C1–C6, and the no-winner conclusion stays visible.

The generated bundle includes original bytes, a readable overview, all metadata and
row diagnostics, two unsent API bodies, and hashes of each view. Only hourly-equity
arrays are omitted from the note; the original retains them. A new output directory
is required, so the exporter does not overwrite an earlier bundle. Local hashes are
not signatures or immutable storage: preserve the trusted report pin separately.

Independent agent checks compared all metadata and every result row against the
original and recomputed bundle hashes. Decimal numbers in the note are exact text,
with no new rounding. A byte change to the source is rejected before output is made.
Untrusted text is escaped in the HTML preview and stays literal text in the API body.

## Verification and remaining boundary

Five focused tests cover evidence preservation, invalid results and exclusions,
literal-text payload/HTML escaping, source tampering, existing-output refusal, and
bundle hashes. Tests ran on Python 3.14.7; they are not Python 3.12 CI evidence.
Exporter lint, format check, mypy and Bandit passed. The repository's focused
preflight (`python scripts/preflight.py --tests tests/test_check_reports.py`) passed:
repository lint/format, types (59 files), security scan, report checker (0 problems),
and 61 report-checker tests with 33 subtests. The five probe tests are run separately
because `experiments/` is outside default discovery. No full strategy suite or
strategy-return test was run or claimed. An initial Bandit heuristic interpreted
the note's prose as SQL; rewording that prose cleared it without disabling the check.

**Not tested:** actual OTW create/read-back, UI rendering/persistence, an installation's
network behavior, token revocation during execution, or whether people find the
result more useful. The 40-plus-KB multiline note uses one text paragraph; usable
line breaks in the actual editor still need observation. Do not call this a deployed
integration or a completed end-to-end import.

Next owner is Codex: if the owner chooses to continue after reviewing this result,
run the manual local application test in the probe README, verify the returned
content and visual display, and compare time-to-answer with our existing report.
Only a demonstrated benefit justifies a maintained adapter. Claude's v2 work has no
dependency on this branch. Leave this experimental branch/PR unmerged pending that
decision and independent review; discarding it has no runtime compatibility impact.
