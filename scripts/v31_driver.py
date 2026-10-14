"""The V3.1 run driver's command line (Task 10a): ``plan``, ``dispatch-check``,
``prepare``, ``picks``, ``run-cell``, ``aggregate``, ``smoke``, ``rehearsal-world``,
``timing`` and ``timing-close``.

Every subcommand but ``smoke``, ``rehearsal-world``, ``dispatch-check`` and
``timing-close`` passes its gate before it reads any input beyond the registration, then
calls the driver library (``crypto_grid_bot.combined.driver``); ``dispatch-check`` reads
only the environment and GitHub's REST API, and ``timing-close`` only what its timing step
wrote. Each prints one canonical JSON document on stdout (sorted keys, no spaces, ASCII,
one newline). Logs go to stderr; a refusal is one stderr
line and exit status 1. Only ``prepare`` (prepare-only and registered) and ``timing``
fetch data, and only from data.binance.vision through the guarded transports
(``fetch_v3_data.V3Transport`` for the inventory, ``v31_fetch.LegacyTransport`` for the
legacy archives), each archive verified against its committed SHA-256 before it is kept.
``dispatch-check`` and a registered ``aggregate`` read this workflow's runs and their
jobs from GitHub's REST API (``dispatch_check``), and nothing else. Every write is an
exclusive create through the library or here: nothing deletes or replaces an earlier
attempt's output, and no attempt is retried (a transport failure is, inside
``fetch_entries``, Ruling P6; so is a transient read of GitHub's API, ``github_retry``).
Nothing at or after 2025-01 is fetched, opened or read.

The dispatch ref (Ruling F6): a registered run and a timing run are dispatched from a ref
whose tree is the code pin plus the registration artifacts only (``config/v3_1_*.json``,
the FX record, ``docs/trials/register.jsonl``, ``docs/reviews/**``, ``docs/tasks/**``).
Every gated job checks it (``job_gate``: nothing but those changed since the code pin;
timing and prepare-only: the checkout is the dispatched ``--code-commit``, clean), and the
plan job checks it first, so a wrong ref fails in the first job.

The V3.1 trial (Rulings R4-1, R5-1): ``job_gate`` (registered prepare, plan, picks,
aggregate) and run-cell, before it reads any pack, require the trial register as the head
commits it to hold exactly one ``spec-v3.1`` completion pinning
``config/v3_1_registration.json`` at the registration's SHA-256; that completion's trial
must pass ``trial_register.check_ready`` at the head, and the completion must pin the
registration's code pin and ``config/v3_1_run_manifest.json`` at the registered pin
(``trial_errors``). Other ``spec-v3.1`` trials, earlier, corrected or superseded, do not
block it. check_ready requires the registration event to precede the implementation
commit, so the code pin is a commit whose first parent already holds the V3.1 registration
event. A rehearsal's world carries a synthetic trial laid out the same way, so a rehearsal
runs this gate too.

One dispatch per registration (Ruling R4-2): the workflow names each run ``v31-run <mode>
<registration_sha256>``. In a registered run, ``dispatch-check`` (the plan job's first
driver step) and ``aggregate`` list this workflow's runs through GitHub's REST API with
the job's token: another run of the same registered title, created before this one or at
the same time, queued, running or finished, fails the plan and leaves the verdict
incomplete, and so does any failure of the check itself (``dispatch_check``). A run
created a second or more later never counts against an earlier one, but two created in
the same second void each other, and one created while an earlier run's check pages
through the runs can make that listing inconsistent, which fails that plan or leaves that
verdict incomplete (fail closed). The operating rule in the workflow's header forbids
both.

Owner decision v31-d21 adds three layers. L1: a transient read failure (no reply, a
timeout, a connection error, a reply cut short, HTTP 5xx or 429, a rate-limited 403, the
current run not yet listed) is retried, five attempts in all over about five minutes
(``github_retry``); anything else fails at once, as before. The whole check has one
deadline: 20 minutes from its start (``DISPATCH_DEADLINE``), and in the plan job no later
than 25 minutes after the job started (``PLAN_JOB_BUDGET``, from ``V31_JOB_STARTED``, which
the job's first step records), five inside its 30: when it passes the check stops and
fails, so the plan job fails, which does not count, instead of being cancelled at its
timeout, which would. L2: an earlier launch does not count when
GitHub's records show it stopped at the plan job with nothing run: completed, its plan job
failed and every later job skipped in every attempt (``launch_reason``); the plan's output
and the verdict still name it. L3: a rehearsal's plan job runs ``dispatch-check
--report-only`` on its own title, which decides as a registered check would, prints the
decision and fails only when GitHub cannot be read, so access, permissions and paging are
proven before a registered run; it also reads its own run's job listing and checks every
record's shape, so even a first rehearsal, with no earlier launch, proves the jobs
endpoint.

Modes (Ruling F3): ``--mode registered`` runs on the repository's own registration;
``--mode rehearsal`` runs the same subcommands on a synthetic rehearsal world built
in-job (``rehearsal-world``), a git repository whose code pin commits
``v31_smoke.REHEARSAL_MARKER``. Only a rehearsal runs the smoke's stand-ins
(``v31_smoke.STAND_INS``), and only on such a world; a registered run, prepare-only and
timing refuse a checkout holding the marker (``world_gate``). A rehearsal fetches
nothing: its every input is the world's.

The owner's plan: the real modes (``registered``, ``prepare-only`` and ``timing``) refuse,
before anything is fetched or replayed, any prepare config or registration other than the
owner's windows, dates, coin sets and FX reference date (``plan_gate``,
``owner_plan.owner_plan_errors``). The rehearsal and the smoke keep their synthetic plans:
``plan_gate`` exempts the rehearsal mode by name, and the smoke calls no gate.

``plan --mode registered|rehearsal [--cells N]``
    ``job_gate`` and ``world_gate``, then the cells the workflow's two matrices run: the
    four ``unchanged_v3_selector`` cells, which need the picks job (``v3_cells``), and
    every other cell (``main_cells``, the six long-only V3 rules included: they read no
    picks), each at most 256. A rehearsal may plan only the first ``N`` cells (at least
    6: one W1 cell of each kind, the selector and a long-only V3 rule both, and one W0
    cell first); a registered run plans them all.
``dispatch-check --registration-sha256 S [--report-only]`` (the plan job, Ruling R4-2)
    Refuses, naming the first and why it counts, another run of this workflow titled
    ``v31-run registered S`` and created before the current run (``GITHUB_RUN_ID``) or at
    the same time, as GitHub's REST API lists them with ``GITHUB_TOKEN``
    (``dispatch_check``), except a launch stopped at the plan job with nothing run, which
    it names as not counted (``launch_reason``); a missing variable, any failure of the
    API, after the retries of a transient one, and the check's deadline passing refuse
    too. ``--report-only`` (a rehearsal's, whose ``S`` may be empty) looks for ``v31-run
    rehearsal S`` instead, prints the decision on every earlier launch and refuses only
    when GitHub cannot be read (a launch deleted since the listing, its jobs answering
    404, is listed as gone instead); it also reads this run's own job listing, and
    refuses unless every record has the shape the check reads.
``prepare --mode prepare-only|registered|rehearsal --work W --out O`` (Ruling P1)
    The gate: in ``prepare-only``, the checkout is ``--code-commit`` with no uncommitted
    change and ``config/v3_1_prepare.json`` hashes to ``--prepare-sha256``; no
    registration exists yet. In ``registered``, the registration and run-manifest load,
    the registration hashes to ``--registration-sha256``, nothing but the registration
    artifacts changed since its code pin, the V3.1 trial authorizes it (``job_gate``), and
    the prepare config, data manifests, snapshots and windows are the ones the
    run-manifest pins. Then it plans every archive
    (refusing any month at or after 2025-01), fetches and verifies them under ``W``
    (``inventory/``, ``legacy/``, ``minutes/``), verifies the legacy dataset
    (``verify_dataset``), builds each window pack (W1's skipped hours joined by the
    minute baselines' masked hours and the hours whose opening quote XRP's rule 8
    rejects, Rulings P16/P17)
    and the V3 input pack (V3's own loader and assembly, bound to V3's registered
    inventory manifest and calendar), writes them under ``O/staging/``, and, in
    ``registered``, refuses unless every pack pin and every window's skipped hours equal
    the registered ones. Only then does ``O/staging/`` become ``O/packs/``; ``O`` and
    ``W`` are scanned for any file name naming a year from 2025 on, and the document
    (``prepare_document``) is written to ``O/prepare.json`` and printed. In
    ``rehearsal`` the gates are the registered ones on the world, nothing is fetched:
    ``W/legacy`` is the world's synthetic dataset (``verify_dataset`` checks it), and the
    packs are the smoke's synthetic coins (``build_smoke_packs``), which must reproduce
    the world's registration like a registered prepare.
``picks --mode M --packs P --attempt-id ID --out O``
    The gate's code, config and run-manifest checks (``job_gate``), then V3's selector
    picks from the V3 input pack read against its pin: ``O/v3_picks/``. Prints the
    SHA-256 of the picks job's completion marker ``O/v3_picks/outcome.json``.
``run-cell --mode M --cell C --packs P --attempt-id ID --out O [--picks D] [--legacy-data L]``
    ``execution_gate`` with the repo head, the changes since the code pin and the adapter
    pins at the head, on the cell's window pack read against the same pin the gate
    checks; then the cell by its kind: ``O/<cell_id>/``. A minute or V3 cell drops the
    window pack once the gate has checked it (Ruling F8). The V3 selector takes the whole
    ``v3_picks/`` directory of the same workflow run (``--picks``, required); a fixed
    long-only V3 rule reads no picks and refuses ``--picks``; a minute cell takes the
    legacy dataset (``--legacy-data``), verified first.
``aggregate --mode M --cells D --attempt-id ID --out O``
    ``job_gate``, then the verdict and summary: ``O/summary/``. ``ID`` is the workflow's
    ``<run_id>-attempt-<run_attempt>``; a W1 cell or the picks job from another artifact
    attempt than 1 or another run makes the verdict incomplete (re-run detected). In a
    registered run, so does another dispatch of the registration that counts, or a
    dispatch check that cannot rule one out (``dispatch_reasons``); one stopped at the
    plan job with nothing run is named in the verdict and changes nothing.
``smoke --out O [--cells N]``
    No gate and no network: a synthetic world (``v31_smoke``) with all 42 arms and 216
    cells on three-day windows, its packs, the picks job, every cell (or the first ``N``,
    one of each kind first) and the aggregate, through the same functions as the
    subcommands, to a verdict.
``rehearsal-world --out W``
    No network: the rehearsal's synthetic world under ``W`` (``W/repo``, a git repository,
    and ``W/legacy``, its legacy dataset). Its code pin commits the smoke world, every
    module of this checkout's package (so the adapter pins read real blobs) and the
    rehearsal marker, on top of a synthetic V3.1 trial's spec and registration event; a
    commit on top of it adds the registration of its packs (all 216 cells) and the trial's
    completion, as Task 11 registers the real run. Prints the registration's SHA-256.
``timing --part prepare|picks|cell --code-commit C --prepare-sha256 S --scratch X --out O``
    Measures the registered run's heavy steps before registration (Ruling F4), gated like
    prepare-only (``prepare_only_gate``; no registration), fetching only what each part
    needs: ``prepare`` runs the whole prepare-only prepare; ``picks`` fetches the
    inventory, builds the real V3 input pack and runs V3's real walk-forward; ``cell``
    fetches the legacy dataset and runs one real W1 minute cell (``TIMING_CELL``) under a
    throwaway registration. Everything a part computes goes to a temporary directory
    under ``X`` and is deleted: ``O`` gets only elapsed times, peak memory (RSS) and,
    for ``picks``, V3's attempt bookkeeping without any result (``O/<part>.timing.jsonl``
    streamed, ``O/<part>.json`` at the end, ``O/picks.attempts.jsonl``). Nothing printed
    or written holds an outcome, report or equity value; a strategy step's error is named
    by its type alone.
``timing-close --part P --step-outcome R --step-timeout-minutes M --out O``
    After a timing step, finished or killed at its step timeout: ``O/<part>.close.json``,
    the step's outcome, whether the part finished and the elapsed time and peak memory so
    far.

Attempt ids: the workflow passes ``--attempt-id <run_id>-attempt-<run_attempt>``, the same
for every job of a run. Each job derives and records its own id from it
(``job_attempt_id``): ``<run_id>-<cell_id>-attempt-<run_attempt>`` for a cell and
``<run_id>-v3_picks-attempt-<run_attempt>`` for the picks job. Acceptance
(``experiment.evaluate``) refuses one attempt id on two outcomes, and the id still ends in
the artifact folder's ``-attempt-<n>``, which aggregation checks.
"""

import argparse
import contextlib
import hashlib
import importlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import BadStatusLine, HTTPException, HTTPMessage, IncompleteRead
from pathlib import Path
from typing import IO, Any, BinaryIO

import v31_smoke
from fetch_v3_data import V3Transport
from trial_register import _parse, check_ready
from v31_fetch import ARCHIVE_PREFIX, ArchiveTransport, LegacyTransport, entries_for, fetch_entries
from v31_v3_pack import build_v3_pack

from crypto_grid_bot.backtest.dataset import load_manifest, load_spec, verify_dataset
from crypto_grid_bot.backtest.jobs import manifest_path, quote_limits, quoted, replayed_minutes
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.backtest.masking import QUOTE_TESTED_SYMBOL, quote_spreads_pct
from crypto_grid_bot.combined.baseline_v3 import SELECTOR, selector_picks
from crypto_grid_bot.combined.driver.aggregate import VERDICT_FILE, _extended, aggregate
from crypto_grid_bot.combined.driver.decode import (
    DecodedV31Month,
    decode_minute_month,
    decode_month,
)
from crypto_grid_bot.combined.driver.owner_plan import owner_plan_errors
from crypto_grid_bot.combined.driver.packs import (
    CoinInputs,
    WindowPack,
    build_coin_inputs,
    build_window_pack,
    minute_months,
    read_pack,
    skipped_hour_sources,
    write_pack,
)
from crypto_grid_bot.combined.driver.registration import (
    ACCEPTANCE_WINDOW,
    MENU_PATH,
    REPORTED_WINDOW,
    Cell,
    DriverRegistration,
    FilePin,
    PrepareConfig,
    PrepareWindow,
    adapter_pins,
    check_registration,
    load_prepare_config,
    load_registration,
)
from crypto_grid_bot.combined.driver.run_baselines import (
    MINUTE_CONFIG_PATH,
    MINUTE_MANIFEST_PATH,
    MINUTE_PAIRS,
    MINUTE_SPEC_PATH,
    OUTCOME_FILE,
    PICKS_FILE,
    V3_PICKS,
    _AttemptLog,
    compute_v3_picks,
    minute_masks,
    run_hold_cell,
    run_minute_cell,
    run_v3_cell,
)
from crypto_grid_bot.combined.driver.run_cell import (
    _git,
    _path_errors,
    changed_since,
    execution_gate,
    head_commit,
    run_v31_cell,
)
from crypto_grid_bot.combined.driver.v3_pack import read_v3_pack, write_v3_pack
from crypto_grid_bot.combined.driver.venues import venue_rules
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.trend.filters import MAX_SNAPSHOT_BYTES
from crypto_grid_bot.trend.orchestration import Attempt

PREPARE_CONFIG = "config/v3_1_prepare.json"
REGISTRATION = "config/v3_1_registration.json"
RUN_MANIFEST = "config/v3_1_run_manifest.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"
V3_FAMILY = "spec-v3"  # V3's registered trial, whose completion pins its inventory and calendar
V31_FAMILY = "spec-v3.1"  # the V3.1 trial, whose completion authorizes the registration
PACKS_DIR = "packs"
STAGING_DIR = "staging"
PREPARE_FILE = "prepare.json"
V3_PACK_FILE = "v3-input.pack.json.gz"
INVENTORY_DIR = "inventory"  # V3's collection layout: the manifest, snapshots/, archives/
LEGACY_DIR = "legacy"  # the legacy dataset, as backtest reads it: legacy/binance/data/...
MINUTES_DIR = "minutes"  # the V3.1 minute manifests' other archives: minutes/binance/data/...
PREPARE_OUTPUT_SCHEMA = "v3.1-prepare-output-1"
SMOKE_SCHEMA = "v3.1-smoke-1"
PLAN_SCHEMA = "v3.1-plan-1"
REHEARSAL_WORLD_SCHEMA = "v3.1-rehearsal-world-1"
TIMING_SCHEMA = "v3.1-timing-1"
TIMING_CLOSE_SCHEMA = "v3.1-timing-close-1"
DISPATCH_CHECK_SCHEMA = "v3.1-dispatch-check-1"
# The dispatch check (Ruling R4-2): GitHub's REST API, this workflow's file name, a timeout
# per request, the page size it asks for and the most pages and bytes it reads.
GITHUB_API = "https://api.github.com"
WORKFLOW_FILE = "v31-run.yml"
GITHUB_TIMEOUT = 30  # seconds
RUNS_PER_PAGE = 100
JOBS_PER_PAGE = 100
MAX_RUN_PAGES = 100  # 10,000 runs (or jobs of one run): more is no listing this check can trust
MAX_GITHUB_BYTES = 32 * 1024 * 1024
# A transient read failure is retried (owner decision v31-d21, layer L1): five attempts in
# all, the waits before attempts 2 to 5 (about five minutes with the reads), a longer
# Retry-After honoured up to the cap.
GITHUB_ATTEMPTS = 5
GITHUB_BACKOFF = (15, 30, 60, 120)  # seconds
MAX_GITHUB_WAIT = 120  # seconds
SECONDARY_LIMIT_WAIT = 60  # seconds: GitHub asks for a minute after its secondary rate limit
# One deadline for the whole check, every read and wait together: well inside the plan
# job's 30 minutes, so a long outage fails the plan job (not counted, L2) instead of
# running into its timeout, which GitHub cancels (a cancelled plan counts).
DISPATCH_DEADLINE = 20 * 60  # seconds
# And no later than its job's budget, counted from the job's start (V31_JOB_STARTED, which
# each checking job's first step records): five minutes inside the job's timeout-minutes
# (plan 30, aggregate 360), however long the checkout, setup and installs before it took.
JOB_STARTED = "V31_JOB_STARTED"
PLAN_JOB_BUDGET = 25 * 60  # seconds
AGGREGATE_JOB_BUDGET = 355 * 60  # seconds
# The workflow's jobs, as GitHub's jobs listing names them (L2): the plan job, the status
# job that always runs, and every other job, which a launch stopped at the plan job skips.
# A matrix job is named "<job> (<matrix values>)", or "<job>" when skipped before its
# matrix expanded.
PLAN_JOB = "plan"
STATUS_JOB = "status"
SKIPPED_JOBS = ("smoke", "prepare", "picks", "aggregate")
SKIPPED_MATRIX_JOBS = ("run-main", "run-v3", "timing")
RUN_MODES = ("registered", "rehearsal")  # the registered job graph, on the repo or a world
REAL_MODES = ("registered", "prepare-only", "timing")  # held to the owner's plan (plan_gate)
MAX_MATRIX = 256  # GitHub's limit on the jobs of one matrix
# smoke_cells' firsts: one W1 cell of each kind (the selector and a fixed long-only V3 rule
# both) and one W0 cell, so a reduced rehearsal exercises every matrix's every cell path.
MIN_REHEARSAL_CELLS = 6
TIMING_PARTS = ("prepare", "picks", "cell")
# The timing cell: V2's grid, the heaviest minute arm (Task 8b measured it highest in
# memory, and its mode switch evaluates the grid, trend and flat paths at every minute);
# both path modes play four quotes a minute (backtest.replay.bar_quotes), so neither is
# slower by construction. Research capital at base cost, as a registered minute cell.
TIMING_CELL = "w1.matched_v2_grid_high_first.native.c1.research"
STEP_OUTCOMES = ("success", "failure", "cancelled", "skipped")
# Every key a timing file or a timing document may hold: times, memory, counts and names,
# never an outcome, report or equity value (Ruling F4).
TIMING_KEYS = frozenset(
    {
        "schema",
        "part",
        "event",
        "phase",
        "seconds",
        "elapsed_s",
        "started_at",
        "peak_rss_kib",
        "code_commit",
        "finished",
        "phases",
        "count",
        "archives",
        "cell",
        "attempt_records",
        "seq",
        "run",
        "state",
        "rule",
        "start_ms",
        "end_ms_exclusive",
        "multiple",
        "cost_multiple",
        "error_type",
        "has_result",
        "step_outcome",
        "step_timeout_minutes",
        "timed_out",
        "elapsed_s_until_close",
        "last_event",
        "last_event_elapsed_s",
        "peak_rss_kib_seen",
    }
)
FIRST_RESERVED_MONTH = "2025-01"
INVENTORY_KINDS = ("spot", "futures", "funding")
LEGACY_KINDS = ("1m", "1h", "1d", "fundingRate")
HOUR = 3_600_000
DAY = 24 * HOUR
HISTORY = 365 * DAY  # the longest spot history a pack holds (Ruling P7)
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ATTEMPT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)-attempt-([1-9][0-9]*)")
_YEAR = re.compile(r"-(?=([0-9]{4})-)")  # every "-YYYY-" in a name, overlapping ones too
_REPO_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*(?:/[A-Za-z0-9_][A-Za-z0-9._-]*)*")
_GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9-]+/(?!\.\.?$)[A-Za-z0-9_.-]+")  # <owner>/<repo>
_RUN_ID = re.compile(r"[1-9][0-9]*")
_CREATED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

Log = Callable[[str], None]
V3PackBuilder = Callable[[Path, str, Mapping[str, str], Path], str]
GitHubOpener = Callable[..., Any]  # urllib.request.OpenerDirector.open: (request, timeout=)


def log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def canonical(document: object) -> bytes:
    """``document`` as canonical JSON: sorted keys, no spaces, ASCII, one newline."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode("ascii")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def window_pack_file(window_id: str) -> str:
    return f"window-{window_id}.pack.json.gz"


def job_attempt_id(attempt_id: object, job: str) -> str:
    """The attempt id job ``job`` (a cell id or ``v3_picks``) records, from the
    workflow's ``<run>-attempt-<n>``: ``<run>-<job>-attempt-<n>``. It ends in the
    artifact folder's attempt number, as aggregation checks, and is unique per cell, as
    acceptance requires. Refuses any other shape, an ``<n>`` that is not a positive
    integer without leading zeros included."""
    match = _ATTEMPT.fullmatch(attempt_id) if type(attempt_id) is str else None
    if match is None:
        raise ValueError(
            f"attempt id {attempt_id!r}: <run>-attempt-<n> required, <n> a positive integer "
            "without leading zeros (the workflow passes <run_id>-attempt-<run_attempt>)"
        )
    return f"{match.group(1)}-{job}-attempt-{match.group(2)}"


# --- 2025 and later ---------------------------------------------------------------------


def refuse_reserved_months(months: Iterable[object], what: str) -> None:
    """Refuse any month at or after 2025-01 (and any that is not ``YYYY-MM`` text)."""
    for month in months:
        if not isinstance(month, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}", month) is None:
            raise ValueError(f"{what}: month {month!r} is not YYYY-MM")
        if month >= FIRST_RESERVED_MONTH:
            raise ValueError(
                f"{what}: month {month} is at or after {FIRST_RESERVED_MONTH}; nothing from "
                "2025 on is fetched, opened or read"
            )


def refuse_sealed_names(root: Path) -> None:
    """Refuse any file or directory under ``root`` whose name holds ``-YYYY-`` for a year
    from 2025 on."""
    for path in sorted(root.rglob("*")):
        for match in _YEAR.finditer(path.name):
            if int(match.group(1)) >= 2025:
                raise ValueError(
                    f"{path}: the name holds -{match.group(1)}-; nothing from 2025 on may be "
                    "prepared"
                )


def month_of(stamp: int) -> str:
    return datetime.fromtimestamp(stamp / 1000, UTC).strftime("%Y-%m")


def months_between(first: int, end: int) -> tuple[str, ...]:
    """The calendar months overlapping ``[first, end)``, oldest first."""
    months: list[str] = []
    while first < end:
        months.append(month_of(first))
        first = month_bounds_ms(months[-1])[1]
    return tuple(months)


@dataclass(frozen=True, slots=True)
class WindowMonths:
    """The months a window's pack reads: spot from its longest history (365 days before
    the start, Ruling P7), futures and funding from the month before the start's, and the
    minute months covering ``[start - 15 min, end)``; each through the end's month."""

    spot: tuple[str, ...]
    futures: tuple[str, ...]
    minutes: tuple[str, ...]


def window_months(window: PrepareWindow) -> WindowMonths:
    """``WindowMonths`` of ``window``; refuses any month at or after 2025-01 before
    anything else reads it."""
    start, end = window.start_ms, window.end_ms
    spot = months_between(start - HISTORY, end)
    futures = months_between(
        month_bounds_ms(month_of(month_bounds_ms(month_of(start))[0] - 1))[0], end
    )
    refuse_reserved_months((*spot, *futures), f"window {window.id}")
    minutes = minute_months(start, end)
    refuse_reserved_months(minutes, f"window {window.id} minutes")
    return WindowMonths(spot, futures, minutes)


# --- strict reading ---------------------------------------------------------------------


def strict_json(raw: bytes, what: str) -> Any:
    """``raw`` parsed as UTF-8 JSON, refusing a duplicate key (as ``trend/filters.py``
    reads a snapshot)."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{what}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{what}: not UTF-8 ({exc})") from exc


def read_pinned(repo: Path, pin: FilePin, what: str, limit: int) -> bytes:
    """The bytes of the repository file ``pin`` names, once they hash to its SHA-256."""
    with (repo / pin.path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{what} {pin.path}: larger than {limit} bytes")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != pin.sha256:
        raise ValueError(
            f"{what} {pin.path} has SHA-256 {actual}; the prepare config pins {pin.sha256}"
        )
    return raw


def load_snapshot(repo: Path, pin: FilePin, market: str) -> tuple[bytes, dict[str, Any]]:
    """A filter snapshot's bytes, verified against the pin, and its document, read with a
    duplicate-key-refusing hook (Task 3's note)."""
    raw = read_pinned(repo, pin, f"{market} filter snapshot", MAX_SNAPSHOT_BYTES)
    document = strict_json(raw, f"{market} filter snapshot {pin.path}")
    if not isinstance(document, dict):
        raise ValueError(f"{market} filter snapshot {pin.path}: a JSON object required")
    return raw, document


def _repo_path(value: object, what: str) -> str:
    if (
        not isinstance(value, str)
        or _REPO_PATH.fullmatch(value) is None
        or ".." in value.split("/")
    ):
        raise ValueError(f"{what}: a canonical repository path required, got {value!r}")
    return value


def _sha(value: object, what: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{what}: a SHA-256 of 64 lowercase hex required")
    return value


def v3_registered_inputs(
    repo: Path, head: str, pins: Mapping[str, str]
) -> tuple[str, str, dict[str, str]]:
    """V3's registered inventory manifest (path and SHA-256) and calendar (``first_months``)
    for its input pack (Rulings P9, P15).

    Both come from the one completion event of V3's registered trial (family ``spec-v3``)
    in the trial register as the head commits it. The manifest must be pinned by the
    prepare config (``pins``) at the same SHA-256, so V3's loader binds the registered
    collection; the calendar file is read as the head commits it (its bytes do not depend
    on the checkout's line endings) and must hash to the completion's pin, with exactly
    the schema V3's ``bind_registered_inputs`` accepts."""
    raw = _git(repo, "show", f"{head}:{TRIAL_REGISTER}")
    completions = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if line.strip():
            event = strict_json(line.encode("utf-8"), f"{TRIAL_REGISTER} line {number}")
            if (
                isinstance(event, dict)
                and event.get("event_type") == "completion"
                and event.get("family") == V3_FAMILY
            ):
                completions.append(event)
    if len(completions) != 1:
        raise ValueError(
            f"{TRIAL_REGISTER}: one {V3_FAMILY} completion required, found {len(completions)}"
        )
    payload = completions[0].get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{TRIAL_REGISTER}: the {V3_FAMILY} completion has no payload")
    pinned = {}
    for key in ("manifest", "config"):
        pin = payload.get(key)
        if not isinstance(pin, dict):
            raise ValueError(f"{TRIAL_REGISTER}: the {V3_FAMILY} completion pins no {key}")
        what = f"V3's registered {key}"
        pinned[key] = (_repo_path(pin.get("path"), what), _sha(pin.get("sha256"), what))
    manifest_path_, manifest_sha = pinned["manifest"]
    if pins.get(manifest_path_) != manifest_sha:
        raise ValueError(
            f"the prepare config must pin V3's registered inventory manifest {manifest_path_} "
            f"at {manifest_sha}, as V3's completion does"
        )
    config_path, config_sha = pinned["config"]
    config_raw = _git(repo, "show", f"{head}:{config_path}")
    actual = hashlib.sha256(config_raw).hexdigest()
    if actual != config_sha:
        raise ValueError(
            f"{config_path} is {actual} at the head; V3's completion pins {config_sha}"
        )
    config = strict_json(config_raw, config_path)
    first = config.get("first_months") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "experiment", "first_months"}
        or config["schema_version"] != 1
        or config["experiment"] != "v3"
        or not isinstance(first, dict)
        or any(type(value) is not str for value in first.values())
    ):
        raise ValueError(f"{config_path}: not V3's registered run configuration")
    return manifest_path_, manifest_sha, dict(first)


# --- the plan ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plan:
    """Every archive prepare fetches and how the packs read them, decided before any
    request: the inventory (all its present archives, which V3's loader re-verifies), the
    legacy dataset (all its present files, which ``verify_dataset`` requires) and the other
    V3.1 minute archives the flow schedules read, each minute month by its source."""

    prepare: PrepareConfig
    inventory_path: str
    inventory_sha: str
    inventory_raw: bytes
    first_months: dict[str, str]
    snapshots: dict[str, tuple[bytes, dict[str, Any]]]
    inventory_entries: tuple[dict[str, Any], ...]
    legacy_entries: tuple[dict[str, Any], ...]
    minute_entries: tuple[dict[str, Any], ...]
    by_identity: dict[tuple[str, str, str], dict[str, Any]]
    minute_sources: dict[tuple[str, str], tuple[dict[str, Any], str]]


def present_entries(
    manifest: Mapping[str, Any], path: str, kinds: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    """Every entry of ``manifest`` that is not ``missing``, selected with ``entries_for``
    by ``kinds``; refuses a month at or after 2025-01 anywhere in the manifest and a
    present archive of another kind."""
    listed = manifest.get("entries", manifest.get("files"))
    if not isinstance(listed, list) or not all(isinstance(entry, dict) for entry in listed):
        raise ValueError(f"{path}: a list of entries required")
    refuse_reserved_months((entry.get("month") for entry in listed), path)
    present = [entry for entry in listed if entry.get("status") != "missing"]
    if not present:
        return ()
    months = sorted(str(entry["month"]) for entry in present)
    symbols = {str(entry.get("symbol")) for entry in present}
    selected = [
        entry
        for entry in entries_for(
            manifest, symbols=symbols, kinds=kinds, start_month=months[0], end_month=months[-1]
        )
        if entry.get("status") != "missing"
    ]
    if len(selected) != len(present):
        raise ValueError(
            f"{path}: {len(present) - len(selected)} present archive(s) are not of the kinds "
            f"{', '.join(kinds)}"
        )
    return tuple(selected)


def minute_sources(
    manifests: Mapping[str, Mapping[str, Any]], windows: Sequence[PrepareWindow]
) -> dict[tuple[str, str], tuple[dict[str, Any], str]]:
    """Each window coin's minute months by (symbol, month): the one ``ok`` 1m archive the
    pinned legacy-format manifests list, and its family (``legacy`` for the legacy
    dataset's, ``minutes`` for another manifest's). A month no manifest lists as ``ok``
    refuses the window (a left-out month would skip its every hour), and so do two
    manifests that disagree on a month's archive."""
    index: dict[tuple[str, str], list[tuple[dict[str, Any], str]]] = {}
    for path, manifest in manifests.items():
        for entry in manifest.get("files", ()):
            if isinstance(entry, dict) and entry.get("interval") == "1m":
                key = (str(entry.get("symbol")), str(entry.get("month")))
                index.setdefault(key, []).append((entry, path))
    sources: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    for window in windows:
        for symbol in window.symbols:
            for month in window_months(window).minutes:
                found = [
                    (e, p) for e, p in index.get((symbol, month), []) if e.get("status") == "ok"
                ]
                if not found:
                    raise ValueError(
                        f"window {window.id}: no ok 1m archive of {symbol} {month} in the pinned "
                        "minute manifests; a minute month left out would skip its every hour"
                    )
                if len({entry.get("sha256") for entry, _ in found}) != 1:
                    raise ValueError(
                        f"{symbol} {month}: the pinned manifests disagree on its 1m archive"
                    )
                entry, path = min(found, key=lambda pair: pair[1] != MINUTE_MANIFEST_PATH)
                sources[(symbol, month)] = (
                    entry,
                    "legacy" if path == MINUTE_MANIFEST_PATH else "minutes",
                )
    return sources


def plan_prepare(repo: Path, head: str, prepare: PrepareConfig) -> Plan:
    """The ``Plan`` of ``prepare``, from the repository's pinned files; no network.

    Every data manifest and both snapshots must hash to their pins. The inventory is V3's
    registered one (``v3_registered_inputs``), with the snapshots the prepare config pins;
    the legacy dataset's manifest (``MINUTE_MANIFEST_PATH``) must be pinned. Refuses any
    month at or after 2025-01 in a window or in any pinned manifest, before anything is
    fetched."""
    for window in prepare.windows:
        window_months(window)
    manifests: dict[str, dict[str, Any]] = {}
    raws: dict[str, bytes] = {}
    for pin in prepare.data_manifests:
        raws[pin.path] = read_pinned(repo, pin, "data manifest", MAX_MANIFEST_BYTES)
        document = strict_json(raws[pin.path], pin.path)
        if not isinstance(document, dict) or ("entries" in document) == ("files" in document):
            raise ValueError(
                f"{pin.path}: an inventory (entries) or legacy (files) manifest required"
            )
        listed = document.get("entries", document.get("files"))
        if not isinstance(listed, list) or not all(isinstance(entry, dict) for entry in listed):
            raise ValueError(f"{pin.path}: a list of entries required")
        refuse_reserved_months((entry.get("month") for entry in listed), pin.path)
        manifests[pin.path] = document
    snapshots = {
        "spot": load_snapshot(repo, prepare.spot_filters, "spot"),
        "futures": load_snapshot(repo, prepare.futures_filters, "futures"),
    }
    pins = {pin.path: pin.sha256 for pin in prepare.data_manifests}
    inventory_path, inventory_sha, first_months = v3_registered_inputs(repo, head, pins)
    inventory = manifests[inventory_path]
    if "entries" not in inventory:
        raise ValueError(f"{inventory_path}: V3's inventory manifest (entries) required")
    for market, (raw, _) in snapshots.items():
        recorded = inventory.get("snapshots", {}).get(market, {}).get("sha256")
        if recorded != hashlib.sha256(raw).hexdigest():
            raise ValueError(
                f"the {market} filter snapshot the prepare config pins is not the one "
                f"{inventory_path} records ({recorded})"
            )
    if "files" not in manifests.get(MINUTE_MANIFEST_PATH, {}):
        raise ValueError(f"the prepare config must pin the legacy dataset {MINUTE_MANIFEST_PATH}")
    legacy = {path: manifest for path, manifest in manifests.items() if "files" in manifest}
    sources = minute_sources(legacy, prepare.windows)
    inventory_entries = present_entries(inventory, inventory_path, INVENTORY_KINDS)
    legacy_entries = present_entries(
        manifests[MINUTE_MANIFEST_PATH], MINUTE_MANIFEST_PATH, LEGACY_KINDS
    )
    others: dict[str, dict[str, Any]] = {}
    for entry, family in sources.values():
        if family == "minutes":
            others.setdefault(_archive_path(entry), entry)
    refuse_reserved_months((entry.get("month") for entry in others.values()), "minute archives")
    return Plan(
        prepare,
        inventory_path,
        inventory_sha,
        raws[inventory_path],
        first_months,
        snapshots,
        inventory_entries,
        legacy_entries,
        tuple(others[path] for path in sorted(others)),
        {(e["kind"], e["symbol"], e["month"]): e for e in inventory_entries},
        sources,
    )


def _archive_path(entry: Mapping[str, Any]) -> str:
    """The archive's data.binance.vision path (an inventory entry's ``path`` or a legacy
    file's ``url`` less the host)."""
    path = entry.get("path")
    if path is None:
        url = str(entry.get("url"))
        if not url.startswith(ARCHIVE_PREFIX + "/"):
            raise ValueError(f"{url}: not a {ARCHIVE_PREFIX} url")
        path = url[len(ARCHIVE_PREFIX) :]
    return str(path)


def _cached(root: Path, entry: Mapping[str, Any]) -> bytes:
    """An archive's bytes from the cache ``fetch_entries`` filled under ``root``; the
    decoders verify them against the entry's SHA-256 again."""
    return root.joinpath(*_archive_path(entry).strip("/").split("/")).read_bytes()


# --- fetching ---------------------------------------------------------------------------


def fetch_all(
    plan: Plan,
    work: Path,
    *,
    inventory_transport: ArchiveTransport,
    legacy_transport: ArchiveTransport,
    sleep: Callable[[float], None],
    log: Log,
    families: tuple[str, ...] = ("inventory", "legacy", "minutes"),
) -> None:
    """Fetch and verify every planned archive of ``families`` (by default all) into the
    cache under ``work``, one ``fetch_entries`` call per archive family and cache, each
    with its own transport (the legacy transport serves the legacy dataset and the other
    minute archives, both from the same host layout). Retries of a transport failure are
    ``fetch_entries``' (Ruling P6), each logged; every verified archive is logged too."""
    unknown = set(families) - {"inventory", "legacy", "minutes"}
    if unknown:
        raise ValueError(f"unknown archive families {sorted(unknown)}")
    planned: tuple[tuple[str, tuple[dict[str, Any], ...], Path, ArchiveTransport], ...] = (
        (
            "inventory",
            plan.inventory_entries,
            work / INVENTORY_DIR / "archives",
            inventory_transport,
        ),
        ("legacy", plan.legacy_entries, work / LEGACY_DIR / "binance", legacy_transport),
        ("minutes", plan.minute_entries, work / MINUTES_DIR / "binance", legacy_transport),
    )
    for family, entries, cache, transport in planned:
        if family not in families:
            continue
        count = 0
        for entry, _ in fetch_entries(entries, cache, transport=transport, sleep=sleep, log=log):
            count += 1
            log(f"VERIFIED {family} {_archive_path(entry)}")
        log(f"{family}: {count} archive(s) verified against their pinned SHA-256")


def verify_legacy(repo: Path, data_dir: Path) -> None:
    """``backtest.dataset.verify_dataset`` on the legacy dataset at ``data_dir``, against
    the repository's frozen spec and the manifest beside it."""
    spec_path = repo / MINUTE_SPEC_PATH
    verify_dataset(load_spec(spec_path), load_manifest(manifest_path(spec_path)), data_dir)


def place(path: Path, data: bytes) -> None:
    """Write ``data`` to a new file at ``path``; an existing one must hold exactly it."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"{path} exists with other bytes")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)


def place_inventory(plan: Plan, work: Path) -> Path:
    """V3's collection layout under ``work/inventory`` for its own loader: the inventory
    manifest's pinned bytes and both snapshots beside the fetched archives."""
    root = work / INVENTORY_DIR
    place(root / "inventory.manifest.json", plan.inventory_raw)
    for market, (raw, _) in plan.snapshots.items():
        place(root / "snapshots" / f"{market}.json", raw)
    return root


# --- packs ------------------------------------------------------------------------------


def quote_test_hours(
    minutes: Iterable[Kline],
    symbol: str,
    spread: Any,
    tick: Any,
    limit: Any,
    start_ms: int,
    end_ms: int,
) -> tuple[int, ...]:
    """The hours of ``[start, end)`` whose boundary quote the frozen engine rejects under
    spec v1 rule 8 (Ruling P17): those hours have no minute-baseline boundary.

    An hour's boundary is the grid account after the quote stamped exactly at the hour
    (``baseline_minute.recorded_frames``: ``stamp % HOUR == 0`` and an event id ending in
    ``/0``). That quote is the open point, index 0 at offset 0 s, of the replayed minute
    that opens the hour (``backtest.replay.bar_quotes``; both path modes put the open
    first). The engine rejects a quote whose spread in percent is above
    ``maximum_spread_pct`` (``PaperSimulator._validate_frame``), and a rejected frame is
    never marked, so no boundary is recorded. So an hour is kept here exactly when the open
    quote of its opening minute is over ``limit``. It is computed with the frozen rule-8
    arithmetic (``masking.quote_spreads_pct``, the first quote it yields). A breach at
    another minute of the hour, or at that minute's extremes or close, leaves the boundary
    in place."""
    hours = []
    for minute in minutes:
        if start_ms <= minute.open_ms < end_ms and minute.open_ms % HOUR == 0:
            opening = next(iter(quote_spreads_pct((minute,), symbol, spread, tick)))
            if opening > limit:  # the engine's own rejection condition: above, not at
                hours.append(minute.open_ms)
    return tuple(sorted(set(hours)))


def window_extras(
    repo: Path, legacy_dir: Path, start_ms: int, end_ms: int
) -> dict[str, tuple[int, ...]]:
    """W1's extra missing-hour sources (Rulings P16, P17), by label: each frozen pair's
    masked hours inside the window (``minute_masks`` on the verified legacy dataset, as the
    minute cells compute them), ``minute_mask:<pair>``, and the hours whose opening quote
    XRP's rule 8 rejects, over the minutes the replay plays (``quote_test_hours``),
    ``quote_test:XRPUSDT``."""
    spec_path = repo / MINUTE_SPEC_PATH
    spec = load_spec(spec_path)
    if spec.traded != MINUTE_PAIRS:
        raise ValueError(
            f"the legacy spec trades {spec.traded}, not the frozen pairs {MINUTE_PAIRS}"
        )
    masks = minute_masks(spec_path, legacy_dir)
    extras = {
        f"minute_mask:{pair}": tuple(
            sorted(hour for hour in masks.get(pair) or () if start_ms <= hour < end_ms)
        )
        for pair in MINUTE_PAIRS
    }
    symbol = QUOTE_TESTED_SYMBOL
    if quoted(spec, symbol):
        manifest = load_manifest(manifest_path(spec_path))
        spread, tick, limit = quote_limits(spec, manifest, repo / MINUTE_CONFIG_PATH, symbol)
        replayed = replayed_minutes(spec, manifest, legacy_dir, symbol, masks.get(symbol))
        hours = quote_test_hours(replayed, symbol, spread, tick, limit, start_ms, end_ms)
        extras[f"quote_test:{symbol}"] = hours
    return extras


def _minute_stream(plan: Plan, work: Path, symbol: str, months: Sequence[str]) -> Iterator[Kline]:
    """The coin's minutes month by month, each archive read and decoded only when the
    flow schedule reaches it (one month held at a time)."""
    for month in months:
        entry, family = plan.minute_sources[(symbol, month)]
        root = work / (LEGACY_DIR if family == "legacy" else MINUTES_DIR) / "binance"
        yield from decode_minute_month(entry, _cached(root, entry))


def build_coin(plan: Plan, work: Path, window: PrepareWindow, symbol: str) -> CoinInputs:
    """One window coin's inputs from its decoded inventory months, its minute stream and
    its venue rules (every V3.1 window coin trades futures: the spec's W1 and W0 coins)."""
    months = window_months(window)
    archives = work / INVENTORY_DIR / "archives"

    def decoded(kind: str, wanted: Sequence[str]) -> list[DecodedV31Month]:
        entries = [plan.by_identity.get((kind, symbol, month)) for month in wanted]
        return [decode_month(entry, _cached(archives, entry)) for entry in entries if entry]

    return build_coin_inputs(
        symbol,
        start_ms=window.start_ms,
        end_ms=window.end_ms,
        spot_months=decoded("spot", months.spot),
        futures_months=decoded("futures", months.futures),
        funding_months=decoded("funding", months.futures),
        minutes=_minute_stream(plan, work, symbol, months.minutes),
        spot_rules=venue_rules(plan.snapshots["spot"][1], symbol, "spot"),
        futures_rules=venue_rules(plan.snapshots["futures"][1], symbol, "futures"),
    )


def skipped_document(pack: WindowPack) -> dict[str, object]:
    """A window's skipped hours and each labelled source of them (``skipped_hour_sources``)."""
    return {
        "hours": list(pack.skipped_hours),
        "sources": {label: list(hours) for label, hours in skipped_hour_sources(pack)},
    }


def prepare_document(
    mode: str,
    head: str,
    prepare: PrepareConfig,
    skipped: Mapping[str, Mapping[str, object]],
    pins: Mapping[str, str],
    v3_pin: str,
    registration_sha256: str | None,
) -> dict[str, object]:
    """Prepare's output, the document Task 11 copies into the run-manifest (the pack pins)
    and the registration (each window's skipped hours)."""
    return {
        "schema": PREPARE_OUTPUT_SCHEMA,
        "mode": mode,
        "code_commit": head,
        "prepare_sha256": prepare.sha256,
        "registration_sha256": registration_sha256,
        "data_manifests": {pin.path: pin.sha256 for pin in prepare.data_manifests},
        "filter_snapshots": {
            pin.path: pin.sha256 for pin in (prepare.spot_filters, prepare.futures_filters)
        },
        "window_packs": dict(sorted(pins.items())),
        "v3_pack_sha256": v3_pin,
        "skipped_hours": {wid: dict(skipped[wid]) for wid in sorted(skipped)},
        "pack_files": {
            **{wid: f"{PACKS_DIR}/{window_pack_file(wid)}" for wid in sorted(pins)},
            "v3": f"{PACKS_DIR}/{V3_PACK_FILE}",
        },
    }


# --- gates ------------------------------------------------------------------------------


def prepare_only_gate(
    repo: Path, head: str, prepare: PrepareConfig, *, code_commit: object, prepare_sha256: object
) -> None:
    """Prepare's gate before a registration exists (Ruling P1): the checkout's head is
    ``code_commit`` with no uncommitted change, and the prepare config hashes to
    ``prepare_sha256``. One ``ValueError`` names every mismatch."""
    errors = []
    if not isinstance(code_commit, str) or _COMMIT.fullmatch(code_commit) is None:
        errors.append(f"--code-commit {code_commit!r}: 40 lowercase hex required")
    elif code_commit != head:
        errors.append(f"the checkout's head {head} is not the code commit {code_commit}")
    if changed := changed_since(repo, head):
        errors.append(f"the checkout has uncommitted changes: {', '.join(changed)}")
    if prepare_sha256 != prepare.sha256:
        errors.append(
            f"{PREPARE_CONFIG} has SHA-256 {prepare.sha256}, not the expected {prepare_sha256!r}"
        )
    if errors:
        raise ValueError("prepare gate refused:\n- " + "\n- ".join(errors))


def _committed(repo: Path, commit: str, path: str) -> bytes | None:
    """The bytes of ``path`` as ``commit`` holds it, or None when it holds no such file."""
    listed = _git(repo, "ls-tree", "-z", "--name-only", f"{commit}^{{commit}}", "--", path)
    if listed.rstrip(b"\0") != path.encode("utf-8"):
        return None
    return _git(repo, "show", f"{commit}:{path}")


def trial_errors(
    repo: Path, head: str, *, code_pin: str, config_sha256: str, manifest_sha256: str
) -> list[str]:
    """How the V3.1 trial's committed completion fails to authorize a registration
    (Rulings R4-1, R5-1); empty when it authorizes it.

    The trial is picked by its completion's pins: among the ``completion`` events of
    family ``V31_FAMILY`` in the trial register as ``head`` commits it, exactly one must pin
    its config as ``REGISTRATION`` at ``config_sha256`` (none, or more than one, refuses,
    naming the count). Its trial must pass ``trial_register.check_ready`` at ``head``,
    whose checks are its own: one committed completion and no correction, the
    registration event already in the code commit's first parent, the code commit and the
    spec commit ancestors of the head, the spec, config and manifest blobs at the head
    matching their pins, and the code at the code commit and at the head matching the
    completion's inventory and digest. The completion must then bind this registration:
    its code commit is ``code_pin``, its config ``REGISTRATION`` at ``config_sha256`` and
    its manifest ``RUN_MANIFEST`` at ``manifest_sha256``. Any other V3.1 trial, earlier,
    corrected or superseded, is not read: a corrected trial needs a new registration
    (check_ready refuses it), and that new trial's completion pins the new registration.

    So the registration's code pin is a commit whose first parent already holds the V3.1
    registration event (check_ready's "registration precedes the implementation commit"):
    Task 11 commits that event first, the code pin on top of it, and the registration
    artifacts with the completion after both."""
    raw = _committed(repo, head, TRIAL_REGISTER)
    if raw is None:
        return [f"the head {head} commits no {TRIAL_REGISTER}"]
    try:
        events = _parse(raw)
    except ValueError as exc:
        return [f"{TRIAL_REGISTER} at the head {head} is not a valid trial register: {exc}"]
    pin = {"path": REGISTRATION, "sha256": config_sha256}
    # The register's validation holds a completion's family to its registration's, and
    # allows each trial one completion.
    trials = [
        event["trial_id"]
        for event in events
        if event["event_type"] == "completion"
        and event["family"] == V31_FAMILY
        and event["payload"]["config"] == pin
    ]
    if len(trials) != 1:
        named = f" ({', '.join(trials)})" if trials else ""
        return [
            f"{TRIAL_REGISTER} at the head {head} must hold one {V31_FAMILY} completion "
            f"pinning {REGISTRATION} at {config_sha256}, found {len(trials)}{named}"
        ]
    (trial,) = trials
    try:
        payload = check_ready(repo, trial, head)["payload"]
    except ValueError as exc:
        return [f"the {V31_FAMILY} trial {trial} is not ready at the head {head}: {exc}"]
    errors = []
    if payload["code_commit"] != code_pin:
        errors.append(
            f"the {V31_FAMILY} completion pins code commit {payload['code_commit']}, not the "
            f"registration's code pin {code_pin}"
        )
    for key, path, sha in (
        ("config", REGISTRATION, config_sha256),
        ("manifest", RUN_MANIFEST, manifest_sha256),
    ):
        pinned = payload[key]
        if pinned != {"path": path, "sha256": sha}:
            errors.append(
                f"the {V31_FAMILY} completion pins its {key} {pinned['path']} at "
                f"{pinned['sha256']}, not {path} at {sha}"
            )
    return errors


def world_gate(repo: Path, mode: str, code_pin: str) -> None:
    """The checkout is of ``mode``'s kind (Ruling F3), or one ``ValueError`` says why.

    A rehearsal world commits ``v31_smoke.REHEARSAL_MARKER`` at its code pin, byte for byte
    ``v31_smoke.rehearsal_marker()``, and holds it unchanged: only then may ``rehearsal``
    run, and with it the smoke's stand-ins. ``registered``, ``prepare-only`` and
    ``timing`` refuse a checkout holding the marker anywhere: in the working tree, at the
    head or at ``code_pin``. So a stand-in never runs on the repository's own data, and a
    registered run never runs on a world built for a rehearsal."""
    marker = v31_smoke.REHEARSAL_MARKER
    held = {
        "the working tree": (repo / marker).read_bytes() if (repo / marker).is_file() else None,
        "the head": _committed(repo, "HEAD", marker),
        "the code pin": _committed(repo, code_pin, marker),
    }
    if mode == "rehearsal":
        expected = v31_smoke.rehearsal_marker()
        wrong = [where for where in ("the code pin", "the working tree") if held[where] != expected]
        if wrong:
            raise ValueError(
                f"rehearsal refused: {marker} is not the rehearsal marker at "
                f"{' and '.join(wrong)}; a rehearsal runs only on a synthetic world built "
                "in-job (rehearsal-world), never on the repository's own registration or data"
            )
    elif mode in REAL_MODES:
        found = [where for where, raw in held.items() if raw is not None]
        if found:
            raise ValueError(
                f"{mode} run refused: the checkout is a rehearsal world ({marker} in "
                f"{', '.join(found)}); a registered, prepare-only or timing run never runs "
                "on a world or registration built for a rehearsal"
            )
    else:
        raise ValueError(f"unknown mode {mode!r}")


def stand_ins_for(mode: str) -> contextlib.AbstractContextManager[None]:
    """The smoke's stand-ins for a rehearsal (whose world ``world_gate`` has passed),
    nothing for any other mode."""
    return v31_smoke.stand_ins() if mode == "rehearsal" else contextlib.nullcontext()


def plan_gate(
    mode: str, prepare: PrepareConfig | Path, reg: DriverRegistration | None = None
) -> None:
    """A real run carries the owner's plan, or one ``ValueError`` names every difference.

    In a real mode (``REAL_MODES``: registered, prepare-only, timing) the prepare config
    (given, or read from the path given) must hold exactly the owner's windows, dates and
    coin sets, and a registered run's registration, whose prepare pin must be that
    config's, the owner's windows and FX reference date (``owner_plan.owner_plan_errors``).
    Each caller runs it before anything is fetched, read or replayed: prepare, timing,
    plan, picks and aggregate after their other gates; run-cell after its world gate,
    before its trial gate and before it reads the cell's pack for ``execution_gate``.
    ``rehearsal`` is exempt, and reads nothing here: its synthetic world's plan is the
    point, and ``world_gate`` admits that mode only on a world committing the rehearsal
    marker. The smoke never calls a gate. Any other mode is refused."""
    if mode == "rehearsal":
        return
    if mode not in REAL_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    config = load_prepare_config(prepare) if isinstance(prepare, Path) else prepare
    errors = []
    if reg is not None and config.sha256 != reg.prepare_pin:
        errors.append(
            f"the prepare config has SHA-256 {config.sha256}; the registration pins "
            f"{reg.prepare_pin}"
        )
    errors.extend(owner_plan_errors(config, reg))
    if errors:
        raise ValueError(f"{mode} run refused, not the owner's plan:\n- " + "\n- ".join(errors))


def load_registered(repo: Path, args: argparse.Namespace) -> tuple[DriverRegistration, str]:
    """The registration and the run-manifest file's own SHA-256."""
    manifest_file = repo / args.run_manifest
    reg = load_registration(repo / args.registration, manifest_file, repo_root=repo)
    return reg, file_sha256(manifest_file)


def job_gate(
    reg: DriverRegistration, repo: Path, *, registration_sha256: object, manifest_sha256: str
) -> str:
    """The execution gate's code, config and run-manifest checks, for a job that runs no
    single cell (picks, aggregate, registered prepare); returns the repo head.

    The registration must pass ``check_registration`` and hash to ``registration_sha256``
    (the dispatch's pin), the run-manifest file to the registered pin, every change since
    the code pin must be a registration artifact (Ruling P10c), and the V3.1 trial's
    committed completion must authorize this registration at the head (``trial_errors``,
    Rulings R4-1, R5-1). One ``ValueError`` names every mismatch."""
    head = head_commit(repo)
    errors = []
    try:
        check_registration(reg)
    except ValueError as exc:
        errors.append(str(exc))
    if registration_sha256 != reg.registration.config_pin:
        errors.append(
            f"the registration's SHA-256 {reg.registration.config_pin} is not the expected "
            f"{registration_sha256!r}"
        )
    if manifest_sha256 != reg.run_manifest_pin:
        errors.append(
            f"the run-manifest's SHA-256 {manifest_sha256} differs from the registered "
            f"{reg.run_manifest_pin}"
        )
    errors.extend(_path_errors(changed_since(repo, reg.registration.code_pin), reg.fx_record_paths))
    errors.extend(
        trial_errors(
            repo,
            head,
            code_pin=reg.registration.code_pin,
            config_sha256=reg.registration.config_pin,
            manifest_sha256=reg.run_manifest_pin,
        )
    )
    if errors:
        raise ValueError("job gate refused:\n- " + "\n- ".join(errors))
    return head


def prepare_pins_gate(reg: DriverRegistration, prepare: PrepareConfig) -> None:
    """A registered prepare's inputs are the registered ones: the prepare config's
    SHA-256, its data manifests, snapshots and windows equal the registration's and
    run-manifest's."""
    errors = []
    if prepare.sha256 != reg.prepare_pin:
        errors.append(
            f"{PREPARE_CONFIG} has SHA-256 {prepare.sha256}; the registration pins "
            f"{reg.prepare_pin}"
        )
    if prepare.data_manifests != reg.run_manifest.data_manifests:
        errors.append("the prepare config's data manifests differ from the run-manifest's")
    snapshots = tuple(
        sorted((prepare.spot_filters, prepare.futures_filters), key=lambda pin: pin.path)
    )
    if snapshots != reg.run_manifest.filter_snapshots:
        errors.append("the prepare config's filter snapshots differ from the run-manifest's")
    registered = {
        w.id: (w.start_ms, w.end_ms) for w in (*reg.registration.windows, *reg.reported_windows)
    }
    if {w.id: (w.start_ms, w.end_ms) for w in prepare.windows} != registered:
        errors.append("the prepare config's windows differ from the registered windows")
    if errors:
        raise ValueError("registered prepare refused:\n- " + "\n- ".join(errors))


def registered_errors(reg: DriverRegistration, document: Mapping[str, Any]) -> list[str]:
    """How a registered prepare's packs and skipped hours differ from the registration's
    pins; empty when every one is reproduced."""
    errors = []
    pinned = dict(reg.run_manifest.window_packs)
    derived: Mapping[str, str] = document["window_packs"]
    for wid in sorted(set(pinned) | set(derived)):
        if derived.get(wid) != pinned.get(wid):
            errors.append(
                f"window {wid}: pack SHA-256 {derived.get(wid)} differs from the pinned "
                f"{pinned.get(wid)}"
            )
    if document["v3_pack_sha256"] != reg.run_manifest.v3_pack:
        errors.append(
            f"V3 input pack SHA-256 {document['v3_pack_sha256']} differs from the pinned "
            f"{reg.run_manifest.v3_pack}"
        )
    windows = {
        w.id: list(w.skipped_hours) for w in (*reg.registration.windows, *reg.reported_windows)
    }
    skipped: Mapping[str, Mapping[str, Any]] = document["skipped_hours"]
    for wid in sorted(set(windows) | set(skipped)):
        hours = skipped.get(wid, {}).get("hours")
        if hours != windows.get(wid):
            extra = sorted(set(hours or ()) - set(windows.get(wid) or ()))
            lost = sorted(set(windows.get(wid) or ()) - set(hours or ()))
            errors.append(
                f"window {wid}: the derived skipped hours differ from the registered ones "
                f"(derived only: {extra[:5]}{'...' if len(extra) > 5 else ''}; registered only: "
                f"{lost[:5]}{'...' if len(lost) > 5 else ''})"
            )
    return errors


# --- one dispatch per registration (Ruling R4-2) ----------------------------------------


class TransientGitHubError(ValueError):
    """A read of GitHub's API that may succeed when repeated (owner decision v31-d21, layer
    L1): no reply, a timeout or a connection error, a reply cut short (an incomplete or
    unreadable status line or body, a TLS failure while reading it, a body shorter than
    its Content-Length), HTTP 5xx or 429, a 403 of GitHub's rate limits (``Retry-After``,
    ``x-ratelimit-remaining: 0``, or a body naming the secondary rate limit), or the
    current run not yet listed. ``retry_after`` is
    the wait in seconds GitHub asked for, if it gave one. A ``ValueError``, so whatever
    does not retry it fails closed on it."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CurrentRunMissing(TransientGitHubError):
    """The current run is not among the listed runs: GitHub's listing can lag a run just
    created, so the listing is read again."""


class GitHubNotFound(ValueError):
    """HTTP 404: permanent, never retried. Of an earlier launch's jobs it means the run was
    deleted after the listing (``EarlierLaunch.gone``)."""


class DeadlineExpired(ValueError):
    """The dispatch check's overall deadline (``DISPATCH_DEADLINE``) passed: it stops,
    retrying nothing more, and fails closed."""


@dataclass(frozen=True, slots=True)
class _Deadline:
    """The dispatch check's one deadline: ``end`` on ``clock`` (``time.monotonic``, or a
    test's), ``seconds`` after the check began; ``why`` says what set it, when its job's
    budget did."""

    clock: Callable[[], float]
    end: float
    seconds: float
    why: str

    @classmethod
    def start(
        cls, clock: Callable[[], float], job_elapsed: float | None, job_budget: int
    ) -> "_Deadline":
        """``DISPATCH_DEADLINE`` from now, or less: what is left of ``job_budget`` when the
        job started ``job_elapsed`` seconds ago (None: no job start known, a local run).
        The elapsed time is taken once, here, from the wall clock, and the deadline then
        runs on the monotonic ``clock``."""
        now = clock()
        seconds, why = float(DISPATCH_DEADLINE), ""
        if job_elapsed is not None and job_budget - job_elapsed < seconds:
            seconds = job_budget - job_elapsed
            why = (
                f" (what was left of its job's {job_budget} s budget: the job started "
                f"{job_elapsed:.0f} s before the check)"
            )
        return cls(clock, now + seconds, seconds, why)

    def left(self) -> float:
        return self.end - self.clock()

    def expired(self, when: str) -> DeadlineExpired:
        return DeadlineExpired(
            f"the dispatch check stopped at its deadline of {max(self.seconds, 0):.0f} s"
            f"{self.why} {when} (fail closed: the job fails rather than run into its own "
            "timeout)"
        )


@dataclass(frozen=True, slots=True)
class EarlierLaunch:
    """Another run of the same title created before or with the current one (Ruling
    R4-2), and the decision on it (L2): ``reason``, why it counts, or None when it stopped
    at the plan job with nothing run. ``unreadable``: its jobs could not be read (it
    counts); ``gone``: they could not because GitHub answered 404, the run deleted since
    the listing (it counts all the same; a report-only check lists it as gone)."""

    run_id: int
    reason: str | None
    unreadable: bool = False
    gone: bool = False

    @property
    def counts(self) -> bool:
        return self.reason is not None


def registered_title(registration_sha256: str) -> str:
    """The title GitHub gives a registered dispatch of the registration: the workflow's
    ``run-name``, ``v31-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}``."""
    return f"v31-run registered {registration_sha256}"


def run_titles(mode: str, registration_sha256: str) -> tuple[str, ...]:
    """The titles a run of ``mode`` dispatched with the ``registration_sha256`` input may
    have: the workflow's ``run-name``. A registered run's input is a SHA-256, so its title is
    ``registered_title``. A rehearsal's input is a SHA-256 or empty (it builds its own
    registration in-job), and with an empty one the run-name ends in a space that GitHub
    may keep or trim, so both spellings are that rehearsal's titles."""
    if mode == "registered":
        return (registered_title(registration_sha256),)
    if registration_sha256:
        return (f"v31-run {mode} {registration_sha256}",)
    return (f"v31-run {mode} ", f"v31-run {mode}")


def _run_fields(run: object, what: str) -> tuple[int, str, datetime]:
    """A workflow run's id, display title and creation time, as GitHub's REST API gives
    them, or one ``ValueError`` naming the field that is missing or malformed."""
    if not isinstance(run, dict):
        raise ValueError(f"{what}: a JSON object required")
    run_id, title, created = run.get("id"), run.get("display_title"), run.get("created_at")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError(f"{what}: id {run_id!r}, a positive integer required")
    if type(title) is not str:
        raise ValueError(f"{what} (run {run_id}): display_title {title!r}, a string required")
    if type(created) is not str or _CREATED_AT.fullmatch(created) is None:
        raise ValueError(
            f"{what} (run {run_id}): created_at {created!r}, YYYY-MM-DDTHH:MM:SSZ required"
        )
    try:
        stamp = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{what} (run {run_id}): created_at {created!r} is not a date") from exc
    return run_id, title, stamp


def other_dispatches(
    runs: Sequence[object],
    current: object,
    registration_sha256: str,
    *,
    mode: str = "registered",
) -> tuple[int, ...]:
    """The ids, ascending, of this workflow's other runs that dispatched the registration
    no later than the current run (Ruling R4-2): a pure decision on what the API listed.
    Each is an earlier launch that ``launch_reason`` then judges (L2): it counts unless
    GitHub's records show it stopped at the plan job with nothing run.

    A run is listed when its id is not the current run's, its display title is exactly
    ``registered_title(registration_sha256)`` (``mode`` "rehearsal": one of the rehearsal's
    ``run_titles``, for a report-only check) and it was created before the current run or
    in the same second (a tie counts). Its status and conclusion do not matter here:
    queued, in progress, failed, cancelled or successful, it launched the registration. A
    run created a second or more later never counts against the current one, but one
    created in the same second does (each of the two then counts the other), and one
    created while ``workflow_runs`` pages can make the listing inconsistent, which it
    refuses. Refuses (one ``ValueError``) any run, the current one included, without a
    positive integer id, a string display title and a ``created_at`` of GitHub's form; a
    run id listed twice; and a current run titled otherwise, as a later dispatch could
    then not find it. A current run missing from the list is ``CurrentRunMissing``, which
    the caller retries (GitHub's listing can lag a run just created)."""
    titles = run_titles(mode, registration_sha256)
    current_id, current_title, current_created = _run_fields(current, "the current run")
    if current_title not in titles:
        wanted = " or ".join(repr(title) for title in titles)
        raise ValueError(
            f"the current run {current_id} is titled {current_title!r}, not {wanted} (the "
            "workflow's run-name): a later dispatch could not find this one"
        )
    seen: set[int] = set()
    found = []
    for index, run in enumerate(runs, start=1):
        run_id, run_title, created = _run_fields(run, f"workflow run {index} of {len(runs)}")
        if run_id in seen:
            raise ValueError(f"workflow run {run_id} is listed twice: the pages disagree")
        seen.add(run_id)
        if run_id != current_id and run_title in titles and created <= current_created:
            found.append(run_id)
    if current_id not in seen:
        raise CurrentRunMissing(
            f"the current run {current_id} is not among this workflow's runs (GitHub's "
            "listing can lag a run just created)"
        )
    return tuple(sorted(found))


def _job_kind(name: str) -> str | None:
    """Which of the workflow's jobs a job record named ``name`` is (``PLAN_JOB``,
    ``STATUS_JOB``, one of ``SKIPPED_JOBS`` or ``SKIPPED_MATRIX_JOBS``), or None for a name
    this workflow does not give a job."""
    if name in (PLAN_JOB, STATUS_JOB, *SKIPPED_JOBS):
        return name
    for job in SKIPPED_MATRIX_JOBS:
        if name == job or (name.startswith(f"{job} (") and name.endswith(")")):
            return job
    return None


def _job_fields_error(
    job: Mapping[str, Any], index: int, run_id: object, attempts: int, ids: set[int]
) -> str | None:
    """Why job record ``index`` (an object) lacks the shape ``launch_decision`` reads, or
    None: a positive integer ``id`` not already in ``ids`` (which it then joins), the run's
    ``run_id``, a ``run_attempt`` from 1 to ``attempts``, a string ``name`` and ``status``,
    and a string or null ``conclusion``."""
    job_id, name, conclusion = job.get("id"), job.get("name"), job.get("conclusion")
    if type(job_id) is not int or job_id <= 0:
        return f"its job record {index} has id {job_id!r}, not a positive integer"
    if job_id in ids:
        return f"its job {job_id} is listed twice"
    ids.add(job_id)
    if type(job.get("run_id")) is not int or job["run_id"] != run_id:
        return f"its job {job_id} has run_id {job.get('run_id')!r}, not {run_id}"
    attempt = job.get("run_attempt")
    if type(attempt) is not int or not 1 <= attempt <= attempts:
        return f"its job {job_id} has run_attempt {attempt!r}, not 1 to {attempts}"
    if type(name) is not str or type(job.get("status")) is not str:
        return f"its job {job_id} has no string name and status"
    if conclusion is not None and type(conclusion) is not str:
        return f"its job {job_id} has conclusion {conclusion!r}, not a string or null"
    return None


def job_listing_error(run: object, jobs: object) -> str | None:
    """Why the current run's own job listing lacks the shape ``launch_decision`` reads, or
    None (a report-only check's probe of the jobs endpoint, layer L3): the run's
    ``run_attempt`` a positive integer, the jobs a list of at least one record (this run's
    own plan job is running), and every record well formed (``_job_fields_error``: fields
    and types, this run's id, an attempt from 1 to the run's, no id twice). No L2 decision
    is taken on it: the run is in progress, and its plan job is the one running."""
    if not isinstance(run, dict):
        return "its run record is not a JSON object"
    attempts = run.get("run_attempt")
    if type(attempts) is not int or attempts < 1:
        return f"its run_attempt is {attempts!r}, not a positive integer"
    if not isinstance(jobs, list | tuple):
        return "its jobs are not a list"
    if not jobs:
        return "it lists no job record, though its own plan job is running"
    ids: set[int] = set()
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            return f"its job record {index} is not a JSON object"
        error = _job_fields_error(job, index, run.get("id"), attempts, ids)
        if error is not None:
            return error
    return None


def launch_decision(run: object, jobs: object) -> tuple[str | None, bool]:
    """Why an earlier launch of the same title counts as an execution of the registration
    (owner decision v31-d21, layer L2), or None when GitHub's records show it provably did
    nothing; and whether it counts because those records are malformed. In the owner's
    words: "a launch that fetched no data and produced no result is not an execution under
    'execute once, keep every outcome'".

    A pure decision on ``run`` (the run as the workflow-runs listing gives it) and ``jobs``
    (every job record of every attempt, as ``run_jobs`` lists them). The launch does not
    count only when all of these hold:

    - the run's ``status`` is ``completed`` and its ``run_attempt`` a positive integer;
    - every job record is an object with a positive integer ``id`` (no id twice), the
      run's ``run_id``, a ``run_attempt`` from 1 to the run's, a string ``name`` and
      ``status`` and a string or null ``conclusion``;
    - every attempt from 1 to the run's ``run_attempt`` lists a job named ``plan``, and
      every ``plan`` job listed ended ``failure``;
    - every other job, except the always-running ``status`` job, ended ``skipped``:
      ``smoke``, ``prepare``, ``picks``, the ``run-main``, ``run-v3`` and ``timing``
      matrix jobs (``<job>`` or ``<job> (<matrix values>)``) and ``aggregate``.

    Anything else counts: a run queued or still running, an attempt whose plan succeeded,
    was cancelled or is not listed, any later job that ran or failed, a job of an unknown
    name, a malformed run or job record, or no listing at all.

    The second value, ``malformed``, is True when the launch counts because the records
    lack the shape the rule reads: a run or job record that is not an object, a field
    missing or of another type, a job of another run or of an attempt the run does not
    have, a job id listed twice, the jobs not a list, or an attempt with no job record at
    all. A report-only check fails on it (layer L3: the API's shape is what a rehearsal
    proves); a registered check counts the launch, as on any reason. A run queued or
    running, an unknown job name and an unexpected conclusion are decisions, not
    malformed records."""
    if not isinstance(run, dict):
        return "its run record is not a JSON object", True
    run_id, status, attempts = run.get("id"), run.get("status"), run.get("run_attempt")
    if status != "completed":
        reason = f"its status is {status!r}, not completed: queued or running, it may still run"
        return reason, type(status) is not str
    if type(attempts) is not int or attempts < 1:
        return f"its run_attempt is {attempts!r}, not a positive integer", True
    if not isinstance(jobs, list | tuple):
        return "its jobs are not a list", True
    ids: set[int] = set()
    listed: set[int] = set()
    planned: set[int] = set()  # the attempts that list a plan job (each one failed)
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            return f"its job record {index} is not a JSON object", True
        error = _job_fields_error(job, index, run_id, attempts, ids)
        if error is not None:
            return error, True
        job_id, name, conclusion = job["id"], job["name"], job.get("conclusion")
        attempt = job["run_attempt"]
        listed.add(attempt)
        kind = _job_kind(name)
        where = f"{name!r} (job {job_id}, attempt {attempt})"
        if kind is None:
            return f"its job {where} is not a job of this workflow", False
        if kind == PLAN_JOB:
            if conclusion != "failure":
                return f"its plan job {where} ended {conclusion!r}, not failure", False
            planned.add(attempt)
        elif kind != STATUS_JOB and conclusion != "skipped":
            return f"its job {where} ended {conclusion!r}, not skipped: it ran", False
    every = range(1, attempts + 1)
    unlisted = [attempt for attempt in every if attempt not in listed]
    if unlisted:
        return f"no job is listed for its attempt(s) {', '.join(map(str, unlisted))}", True
    unplanned = [attempt for attempt in every if attempt not in planned]
    if unplanned:
        return f"no plan job is listed for its attempt(s) {', '.join(map(str, unplanned))}", False
    return None, False


def launch_reason(run: object, jobs: object) -> str | None:
    """``launch_decision``'s reason alone: why the launch counts, or None when it does
    not."""
    return launch_decision(run, jobs)[0]


def uncounted_line(run_id: int) -> str:
    """How the plan's output and the aggregate name an earlier launch that does not count."""
    return f"earlier launch {run_id} stopped at the plan job with nothing run; not counted"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Builds no request for a redirect, so urllib raises it as an HTTP error: the token's
    request never follows one to another address."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _header(headers: object, name: str) -> str | None:
    """The value of the header ``name`` in an HTTP error's headers, or None."""
    get = getattr(headers, "get", None)
    value = get(name) if callable(get) else None
    return value.strip() if isinstance(value, str) else None


def _secondary_rate_limit(error: urllib.error.HTTPError) -> bool:
    """Whether an HTTP error's body, read up to ``MAX_GITHUB_BYTES``, is a JSON object
    whose ``message`` names GitHub's secondary rate limit (any case); False for any other
    body, or one that cannot be read."""
    try:
        raw = error.read(MAX_GITHUB_BYTES + 1)
    except (OSError, HTTPException, ValueError):
        return False
    if not isinstance(raw, bytes) or len(raw) > MAX_GITHUB_BYTES:
        return False
    try:
        document = strict_json(raw, "GitHub's error body")
    except ValueError:
        return False
    message = document.get("message") if isinstance(document, dict) else None
    return isinstance(message, str) and "secondary rate limit" in message.lower()


def github_json(path: str, token: str, opener: GitHubOpener) -> Any:
    """The JSON document at ``GITHUB_API + path``, read with ``token``. Any failure is one
    ``ValueError`` naming the path, never the token: an HTTP error (a redirect included), a
    transport failure or a timeout, a status other than 200, a body larger than
    ``MAX_GITHUB_BYTES`` and a body that is not JSON; HTTP 404 is ``GitHubNotFound``. The
    failures a repeated read may not meet (L1) are ``TransientGitHubError``: no reply, a
    timeout or a connection error (``URLError``, ``TimeoutError``, ``ConnectionError``), a
    reply cut short (``IncompleteRead``, ``BadStatusLine``, an ``ssl.SSLError`` such as
    ``SSLEOFError``, or a body shorter than its Content-Length), HTTP 5xx, HTTP 429, and an
    HTTP 403 that carries ``Retry-After`` or ``x-ratelimit-remaining: 0`` (GitHub's rate
    limits), with GitHub's ``Retry-After`` seconds when it gives them, or whose JSON body's
    ``message`` names the secondary rate limit, which GitHub may send without either
    header (waited at least ``SECONDARY_LIMIT_WAIT``). Any other 403 is permanent."""
    # The URL is the fixed https://api.github.com origin and a path the callers build from
    # the validated GITHUB_REPOSITORY and GITHUB_RUN_ID: no other scheme or host is opened.
    request = urllib.request.Request(
        GITHUB_API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "v31-driver",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=GITHUB_TIMEOUT) as response:
            status = getattr(response, "status", None)
            length = _header(getattr(response, "headers", None), "Content-Length")
            raw = response.read(MAX_GITHUB_BYTES + 1)
    except urllib.error.HTTPError as exc:
        retry_after = _header(exc.headers, "Retry-After")
        message = f"GitHub API {path}: HTTP {exc.code}"
        if retry_after is not None:
            message += f" (Retry-After {retry_after!r})"
        limited = exc.code == 403 and (
            retry_after is not None or _header(exc.headers, "x-ratelimit-remaining") == "0"
        )
        if 500 <= exc.code <= 599 or exc.code == 429 or limited:
            seconds = None
            if retry_after is not None and re.fullmatch(r"[0-9]{1,9}", retry_after):
                seconds = int(retry_after)
            raise TransientGitHubError(message, seconds) from exc
        if exc.code == 403 and _secondary_rate_limit(exc):
            # GitHub's secondary rate limit may answer without either header, and asks
            # for a wait of at least a minute.
            message += " (secondary rate limit)"
            raise TransientGitHubError(message, SECONDARY_LIMIT_WAIT) from exc
        if exc.code == 404:
            raise GitHubNotFound(message) from exc
        raise ValueError(message) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        IncompleteRead,
        BadStatusLine,
        ssl.SSLError,
    ) as exc:  # no reply, or one cut short
        raise TransientGitHubError(f"GitHub API {path}: {type(exc).__name__}: {exc}") from exc
    except (OSError, HTTPException) as exc:  # any other transport failure: permanent
        raise ValueError(f"GitHub API {path}: {type(exc).__name__}: {exc}") from exc
    if status != 200:
        raise ValueError(f"GitHub API {path}: HTTP {status}, not 200")
    if len(raw) > MAX_GITHUB_BYTES:
        raise ValueError(f"GitHub API {path}: the response is larger than {MAX_GITHUB_BYTES} bytes")
    if length is not None and re.fullmatch(r"[0-9]{1,12}", length) and len(raw) < int(length):
        raise TransientGitHubError(
            f"GitHub API {path}: the reply ended after {len(raw)} of its {length} bytes "
            "(Content-Length)"
        )
    try:
        return strict_json(raw, f"GitHub API {path}")
    except ValueError as exc:
        raise ValueError(f"GitHub API {path}: not JSON ({exc})") from exc


def _listing(
    path: str, key: str, noun: str, lister: str, per_page: int, token: str, opener: GitHubOpener
) -> list[object]:
    """Every item of one of GitHub's paged listings: page ``n`` is ``path`` with
    ``per_page=<per_page>&page=<n>`` added to its query, ``key`` the list each page holds,
    ``noun`` an item and ``lister`` what lists them (for messages). Refuses a malformed page
    and any pagination inconsistency: a total_count that changes between pages, a page
    larger than asked for, pages that end before the total or list more items than it, and
    more than ``MAX_RUN_PAGES`` pages."""
    items: list[object] = []
    total: int | None = None
    for number in range(1, MAX_RUN_PAGES + 1):
        page = f"{path}{'&' if '?' in path else '?'}per_page={per_page}&page={number}"
        document = github_json(page, token, opener)
        count = document.get("total_count") if isinstance(document, dict) else None
        listed = document.get(key) if isinstance(document, dict) else None
        if type(count) is not int or count < 0 or not isinstance(listed, list):
            raise ValueError(f"GitHub API {page}: total_count and {key} required")
        if total is not None and count != total:
            raise ValueError(f"GitHub API {page}: total_count changed from {total} to {count}")
        total = count
        if len(listed) > per_page:
            raise ValueError(f"GitHub API {page}: a page of more than {per_page} {noun}s")
        items.extend(listed)
        if len(items) > total:
            raise ValueError(
                f"GitHub API {page}: {len(items)} {noun}s listed, more than total_count {total}"
            )
        if len(items) == total or len(listed) < per_page:
            if len(items) != total:
                raise ValueError(
                    f"GitHub API {page}: the pages end after {len(items)} {noun}(s) listed, "
                    f"total_count {total}"
                )
            return items
    raise ValueError(f"{lister} lists more than {MAX_RUN_PAGES} pages of {noun}s")


def workflow_runs(repository: str, token: str, opener: GitHubOpener) -> list[object]:
    """Every run of this workflow (``WORKFLOW_FILE``), all pages of ``RUNS_PER_PAGE``,
    refusing a malformed page and any pagination inconsistency (``_listing``)."""
    path = f"/repos/{repository}/actions/workflows/{WORKFLOW_FILE}/runs"
    return _listing(path, "workflow_runs", "run", "this workflow", RUNS_PER_PAGE, token, opener)


def run_jobs(repository: str, token: str, opener: GitHubOpener, run_id: int) -> list[object]:
    """Every job record of run ``run_id``, of every attempt (``filter=all``), all pages of
    ``JOBS_PER_PAGE``: the same strict pagination as ``workflow_runs`` (``_listing``), and
    a job id listed twice is refused too (the pages disagree). The records themselves are
    ``launch_reason``'s to judge."""
    path = f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=all"
    jobs = _listing(path, "jobs", "job", f"run {run_id}", JOBS_PER_PAGE, token, opener)
    seen: set[int] = set()
    for job in jobs:
        job_id = job.get("id") if isinstance(job, dict) else None
        if type(job_id) is int:
            if job_id in seen:
                raise ValueError(f"run {run_id}: job {job_id} is listed twice: the pages disagree")
            seen.add(job_id)
    return jobs


def github_retry[T](
    read: Callable[[], T],
    what: str,
    *,
    sleep: Callable[[float], None],
    log: Log,
    deadline: _Deadline,
) -> T:
    """``read()``, attempted up to ``GITHUB_ATTEMPTS`` times in all while it fails with a
    ``TransientGitHubError`` (owner decision v31-d21, layer L1). Before each next attempt
    it logs the attempt number and the reason to ``log`` and waits ``GITHUB_BACKOFF``'s
    next delay, or GitHub's longer ``Retry-After``, at most ``MAX_GITHUB_WAIT`` seconds,
    through ``sleep`` (tests pass their own, so none waits). Any other ``ValueError`` (a
    permanent error, or a decision) is raised at once, never retried; a transient failure
    still there at the last attempt is one ``ValueError`` naming it. A wait that would end
    at or past ``deadline`` is not taken: ``DeadlineExpired``, naming the last error."""
    attempt = 1
    while True:
        try:
            return read()
        except TransientGitHubError as exc:
            if attempt >= GITHUB_ATTEMPTS:
                raise ValueError(f"{exc} (still failing after {GITHUB_ATTEMPTS} attempts)") from exc
            wait = min(max(GITHUB_BACKOFF[attempt - 1], exc.retry_after or 0), MAX_GITHUB_WAIT)
            if wait >= deadline.left():
                raise deadline.expired(
                    f"before attempt {attempt + 1} of {what} (the last error: {exc})"
                ) from exc
            log(
                f"dispatch check: {what}: attempt {attempt} of {GITHUB_ATTEMPTS} failed "
                f"({exc}); retrying in {wait} s"
            )
            sleep(wait)
            attempt += 1


def _judge(
    run: Mapping[str, Any],
    repository: str,
    token: str,
    opener: GitHubOpener,
    *,
    sleep: Callable[[float], None],
    log: Log,
    deadline: _Deadline,
) -> EarlierLaunch:
    """The decision on one earlier launch (L2): one queued or running counts without its
    jobs; a completed one is judged on its jobs (``run_jobs``, retried as L1 says), and
    counts, ``unreadable``, when they cannot be read (``gone`` too when GitHub answered
    404), or, ``unreadable`` too, when a record lacks the shape the rule reads
    (``launch_decision``). The deadline passing is no decision on the launch: it stops the
    whole check."""
    # ``run`` is the listed run as other_dispatches validated it: an object with a positive
    # integer id, a string title and a created_at of GitHub's form (its status is read here).
    run_id: int = run["id"]
    if run.get("status") != "completed":
        reason, malformed = launch_decision(run, ())
        return EarlierLaunch(run_id, reason, unreadable=malformed)
    try:
        jobs = github_retry(
            lambda: run_jobs(repository, token, opener, run_id),
            f"the jobs of run {run_id}",
            sleep=sleep,
            log=log,
            deadline=deadline,
        )
    except DeadlineExpired:
        raise
    except GitHubNotFound as exc:
        reason = f"gone (404): its jobs could not be read: {exc}"
        return EarlierLaunch(run_id, reason, unreadable=True, gone=True)
    except ValueError as exc:
        return EarlierLaunch(run_id, f"its jobs could not be read: {exc}", unreadable=True)
    reason, malformed = launch_decision(run, jobs)
    return EarlierLaunch(run_id, reason, unreadable=malformed)


def dispatch_check(
    registration_sha256: object,
    opener: GitHubOpener | None = None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
    job_budget: int = PLAN_JOB_BUDGET,
    log: Log = log,
    report_only: bool = False,
    judge_all: bool = False,
) -> tuple[EarlierLaunch, ...]:
    """The earlier launches of this run's title, ascending, and whether each counts
    (Ruling R4-2; owner decision v31-d21), from GitHub's REST API: the current run and this
    workflow's runs (``workflow_runs``) name the launches (``other_dispatches``), and each
    completed one's jobs (``run_jobs``) decide it (``launch_reason``); one queued or
    running counts without them. Read with the job's ``GITHUB_TOKEN`` (only the checking
    step's env passes ``github.token``) for the runner's own ``GITHUB_REPOSITORY`` and
    ``GITHUB_RUN_ID``. ``opener`` replaces urllib's (tests); by default urllib's,
    following no redirect, with ``GITHUB_TIMEOUT`` per request.

    A registered check (the default) looks for ``registered_title`` and judges the
    launches up to the first that counts, which already decides a refusal, unless
    ``judge_all`` (the aggregate's, whose verdict names every earlier launch); a
    report-only one (a rehearsal's, layer L3) looks for the rehearsal's own
    ``run_titles``, whose input is a SHA-256 or empty, and judges every launch exactly as
    a registered check would. A report-only check also reads the current run's own job
    listing (``run_jobs``, retried and within the deadline like every read) and refuses
    unless every record has the shape the rule reads (``job_listing_error``), so even a
    first rehearsal, with no earlier launch, proves the jobs endpoint; a registered check
    makes no such request.

    Each read is retried on a transient failure (``github_retry``, L1): the current run,
    whose id must be ``GITHUB_RUN_ID`` before anything else is read; the whole runs
    listing, which must hold the current run; one run's whole jobs listing. The whole
    check, every read and wait, has one deadline on ``clock``: ``DISPATCH_DEADLINE`` from
    its start, or earlier, ``job_budget`` from its job's start when ``V31_JOB_STARTED``
    gives it (the epoch second the job's first step recorded; ``PLAN_JOB_BUDGET`` for the
    plan job, ``AGGREGATE_JOB_BUDGET`` for the aggregate's). The time the job has already
    run is taken once, at the start, from the wall clock ``wall``. No request starts after
    the deadline (none is given a timeout past it), and no wait is taken that would end at
    or after it. A missing or malformed variable (``V31_JOB_STARTED``, when set, must be a
    positive integer epoch not in the future; all before any request), a permanent
    failure, a transient one that outlasts the retries and the deadline passing
    (``DeadlineExpired``) are one ``ValueError``: the caller fails closed. A launch whose
    jobs cannot be read, or whose records are malformed, counts (``unreadable``)."""
    mode = "rehearsal" if report_only else "registered"
    if report_only and registration_sha256 == "":
        sha = ""
    else:
        what = "--registration-sha256" + (" (a rehearsal's may be empty)" if report_only else "")
        sha = _sha(registration_sha256, what)
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    errors = []
    if not token:
        errors.append("GITHUB_TOKEN is not set (the checking step's env passes github.token)")
    if _GITHUB_REPOSITORY.fullmatch(repository) is None:
        errors.append(f"GITHUB_REPOSITORY {repository!r}: <owner>/<repository> required")
    if _RUN_ID.fullmatch(run_id) is None:
        errors.append(f"GITHUB_RUN_ID {run_id!r}: a positive integer required")
    started = os.environ.get(JOB_STARTED)
    now = wall()
    if started is not None and (
        re.fullmatch(r"[1-9][0-9]{0,11}", started) is None or int(started) > now
    ):
        errors.append(
            f"{JOB_STARTED} {started!r}: the job's start, a positive integer epoch second "
            "not in the future, required (the job's first step records it)"
        )
    if errors:
        raise ValueError("the dispatch check cannot run: " + "; ".join(errors))
    elapsed = None if started is None else now - int(started)
    deadline = _Deadline.start(clock, elapsed, job_budget)
    if deadline.left() <= 0:
        raise deadline.expired("before its first request")
    base: GitHubOpener = urllib.request.build_opener(_NoRedirect).open if opener is None else opener

    def read(request: urllib.request.Request, timeout: float) -> Any:
        left = deadline.left()
        if left <= 0:
            raise deadline.expired(f"before GET {request.full_url.removeprefix(GITHUB_API)}")
        return base(request, timeout=min(timeout, left))

    path = f"/repos/{repository}/actions/runs/{run_id}"
    current = github_retry(
        lambda: github_json(path, token, read),
        "the current run",
        sleep=sleep,
        log=log,
        deadline=deadline,
    )
    current_id = _run_fields(current, "the current run")[0]
    if current_id != int(run_id):
        raise ValueError(
            f"GitHub API {path}: the current run's id is {current_id}, not GITHUB_RUN_ID "
            f"{run_id}: this is not the run that asked"
        )
    if report_only:
        # The probe (L3): even a first rehearsal, with no earlier launch to judge, reads a
        # job listing, its own, and checks every record's shape, so the jobs endpoint's
        # access, paging and schema are proven before a registered run needs them.
        own = github_retry(
            lambda: run_jobs(repository, token, read, current_id),
            "this run's own jobs",
            sleep=sleep,
            log=log,
            deadline=deadline,
        )
        problem = job_listing_error(current, own)
        if problem is not None:
            raise ValueError(
                f"the jobs endpoint, checked on this run ({current_id}), does not have the "
                f"shape the check reads: {problem}"
            )
        log(
            f"dispatch check (report-only): jobs endpoint checked on this run: {len(own)} "
            "job records, shape valid"
        )

    def launches() -> tuple[list[object], tuple[int, ...]]:
        runs = workflow_runs(repository, token, read)
        return runs, other_dispatches(runs, current, sha, mode=mode)

    runs, found = github_retry(
        launches, "this workflow's runs", sleep=sleep, log=log, deadline=deadline
    )
    # other_dispatches has checked every listed run: an object with a unique positive id.
    records = {run["id"]: run for run in runs if isinstance(run, dict)}
    judged = []
    for found_id in found:
        launch = _judge(
            records[found_id], repository, token, read, sleep=sleep, log=log, deadline=deadline
        )
        judged.append(launch)
        if launch.counts and not (report_only or judge_all):
            break  # a registered check refuses on it: no later launch changes that
    return tuple(judged)


def dispatch_reasons(
    registration_sha256: str,
    opener: GitHubOpener | None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
    log: Log = log,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What a registered aggregate hands ``aggregate`` (Ruling R4-2): first every earlier
    launch of the registration that counts, with why, or why none could be ruled out (a
    failure of the check, its deadline passing among them), either of which leaves the
    verdict incomplete (fail closed); then every earlier launch that stopped at the plan
    job with nothing run (L2), which the verdict names and which changes nothing. Unlike
    the plan's check it judges every launch (``judge_all``): the verdict names them all."""
    try:
        launches = dispatch_check(
            registration_sha256,
            opener,
            sleep=sleep,
            clock=clock,
            wall=wall,
            job_budget=AGGREGATE_JOB_BUDGET,
            log=log,
            judge_all=True,
        )
    except ValueError as exc:
        return (f"another dispatch of this registration could not be ruled out: {exc}",), ()
    counted = tuple(
        f"another dispatch of this registration: run {launch.run_id} ({launch.reason})"
        for launch in launches
        if launch.counts
    )
    return counted, tuple(uncounted_line(launch.run_id) for launch in launches if not launch.counts)


# --- the subcommands --------------------------------------------------------------------


def prepare(
    args: argparse.Namespace,
    *,
    inventory_transport: ArchiveTransport,
    legacy_transport: ArchiveTransport,
    sleep: Callable[[float], None],
    log: Log,
    v3_pack_builder: V3PackBuilder,
) -> dict[str, object]:
    """``prepare`` (the module docstring): the gate, the plan, the fetch, the packs; in a
    rehearsal, the gate and the world's synthetic packs, with nothing fetched."""
    repo, work, out = Path(args.repo), Path(args.work), Path(args.out)
    if out.exists():
        raise FileExistsError(f"{out} exists; a prepare output is written once")
    config = load_prepare_config(repo / args.prepare_config)
    head = head_commit(repo)
    reg: DriverRegistration | None = None
    if args.mode == "prepare-only":
        prepare_only_gate(
            repo, head, config, code_commit=args.code_commit, prepare_sha256=args.prepare_sha256
        )
        world_gate(repo, args.mode, head)
    else:
        reg, manifest_sha = load_registered(repo, args)
        job_gate(
            reg, repo, registration_sha256=args.registration_sha256, manifest_sha256=manifest_sha
        )
        world_gate(repo, args.mode, reg.registration.code_pin)
        prepare_pins_gate(reg, config)
    plan_gate(args.mode, config, reg)  # prepare-only and registered; a rehearsal is exempt
    if args.mode == "rehearsal" and reg is not None:
        # The world's synthetic legacy dataset lies beside its repository, as a fetch would
        # leave it; nothing is fetched, and the transports are never used.
        legacy = work / LEGACY_DIR
        verify_legacy(repo, legacy)
        out.mkdir(parents=True, exist_ok=False)
        staging = out / STAGING_DIR
        with v31_smoke.stand_ins():
            document = build_smoke_packs(
                repo,
                legacy,
                config,
                head,
                staging,
                mode=args.mode,
                registration_sha256=reg.registration.config_pin,
                log=log,
            )
        return finish_prepare(reg, document, out, work, staging)
    plan = plan_prepare(repo, head, config)
    fetch_all(
        plan,
        work,
        inventory_transport=inventory_transport,
        legacy_transport=legacy_transport,
        sleep=sleep,
        log=log,
    )
    legacy = work / LEGACY_DIR
    verify_legacy(repo, legacy)
    inventory_root = place_inventory(plan, work)
    out.mkdir(parents=True, exist_ok=False)
    staging = out / STAGING_DIR
    staging.mkdir()
    pins: dict[str, str] = {}
    skipped: dict[str, dict[str, object]] = {}
    sources = [(pin.path, pin.sha256) for pin in config.data_manifests]
    for window in config.windows:
        extras: dict[str, tuple[int, ...]] = {}
        if window.id == ACCEPTANCE_WINDOW:  # the minute baselines run in W1 alone
            extras = window_extras(repo, legacy, window.start_ms, window.end_ms)
        coins = [build_coin(plan, work, window, symbol) for symbol in window.symbols]
        pack = build_window_pack(
            window.id, window.start_ms, window.end_ms, coins, sources, extra_missing_hours=extras
        )
        pins[window.id] = write_pack(pack, staging / window_pack_file(window.id))
        skipped[window.id] = skipped_document(pack)
        log(f"window {window.id}: pack {pins[window.id]}, {len(pack.skipped_hours)} skipped hours")
        del pack, coins
    v3_pin = v3_pack_builder(
        inventory_root, plan.inventory_sha, plan.first_months, staging / V3_PACK_FILE
    )
    log(f"V3 input pack {v3_pin}")
    sha = reg.registration.config_pin if reg is not None else None
    document = prepare_document(args.mode, head, config, skipped, pins, v3_pin, sha)
    return finish_prepare(reg, document, out, work, staging)


def finish_prepare(
    reg: DriverRegistration | None,
    document: dict[str, object],
    out: Path,
    work: Path,
    staging: Path,
) -> dict[str, object]:
    """A prepare's last steps: a registered (or rehearsal) prepare must reproduce every
    registered pin and skipped hour; then ``staging`` becomes ``out/packs``, ``out`` and
    ``work`` are scanned for names from 2025 on, and ``out/prepare.json`` is written."""
    if reg is not None and (errors := registered_errors(reg, document)):
        raise ValueError(
            "registered prepare did not reproduce the registration; nothing final was "
            f"written ({staging} keeps what it built):\n- " + "\n- ".join(errors)
        )
    final = out / PACKS_DIR
    if final.exists():
        raise FileExistsError(f"{final} exists")
    staging.rename(final)
    refuse_sealed_names(out)
    refuse_sealed_names(work)
    with open(out / PREPARE_FILE, "xb") as handle:
        handle.write(canonical(document))
    return document


def run_picks(
    reg: DriverRegistration, packs_dir: Path, out: Path, *, attempt_id: str, repo_head: str
) -> Path:
    """V3's selector picks from the V3 input pack read against the run-manifest's pin:
    ``out/v3_picks/``, returned."""
    inputs = read_v3_pack(packs_dir / V3_PACK_FILE, reg.run_manifest.v3_pack)
    out.mkdir(parents=True, exist_ok=True)
    picks = compute_v3_picks(inputs, reg, out, attempt_id=attempt_id, repo_head=repo_head)
    return picks.parent


def run_cell_job(
    cell: Cell,
    pack: WindowPack | None,
    reg: DriverRegistration,
    out: Path,
    *,
    attempt_id: str,
    repo_head: str,
    repo: Path,
    packs_dir: Path,
    picks_dir: Path | None,
    legacy_dir: Path | None,
) -> Path:
    """Run the gated ``cell`` by its kind into ``out/<cell_id>/`` and return that directory.

    ``pack`` is the cell's window pack as the gate checked it; a V3.1 or hold cell replays
    it, while a minute or V3 cell reads none, so its caller may pass None once the gate is
    done (Ruling F8). A V3 cell reads the V3 input pack against its pin; the selector also
    the whole ``v3_picks/`` directory ``picks_dir`` (required), and a fixed long-only rule
    no picks (``picks_dir`` refused: run-main passes none). A minute cell reads the legacy
    dataset ``legacy_dir``, verified with ``verify_dataset`` first."""
    options = {"attempt_id": attempt_id, "repo_head": repo_head}
    if cell.kind == "v3" and needs_picks(cell.arm):
        if picks_dir is None or Path(picks_dir).name != V3_PICKS:
            raise ValueError(
                f"cell {cell.cell_id}: the V3 selector needs --picks, the {V3_PICKS}/ directory"
            )
    elif cell.kind == "v3" and picks_dir is not None:
        raise ValueError(
            f"cell {cell.cell_id}: a fixed long-only V3 rule reads no picks; --picks refused"
        )
    if cell.kind == "minute" and legacy_dir is None:
        raise ValueError(f"cell {cell.cell_id}: a minute cell needs --legacy-data")
    if cell.kind in ("v31", "hold") and pack is None:
        raise ValueError(f"cell {cell.cell_id}: a {cell.kind} cell replays its window pack")
    out.mkdir(parents=True, exist_ok=True)
    if cell.kind == "v31" and pack is not None:
        return run_v31_cell(cell, pack, reg, out, **options)
    if cell.kind == "hold" and pack is not None:
        return run_hold_cell(cell, pack, reg, out, **options)
    if cell.kind == "v3":
        inputs = read_v3_pack(packs_dir / V3_PACK_FILE, reg.run_manifest.v3_pack)
        picks_file = None if picks_dir is None else Path(picks_dir) / PICKS_FILE
        return run_v3_cell(cell, inputs, picks_file, reg, out, **options)
    if cell.kind == "minute" and legacy_dir is not None:
        verify_legacy(repo, Path(legacy_dir))
        return run_minute_cell(cell, Path(legacy_dir), reg, out, repo_root=repo, **options)
    raise ValueError(f"cell {cell.cell_id}: unknown kind {cell.kind!r}")


def needs_picks(arm: str) -> bool:
    """Whether a cell of ``arm`` reads the picks job's output: the V3 selector alone (the
    six fixed long-only V3 rules replay their own rule)."""
    return arm == SELECTOR


def registered_job(args: argparse.Namespace) -> tuple[Path, DriverRegistration, str, str]:
    """A registered job's gate, in either run mode: the registration and run-manifest
    load, ``job_gate`` passes, the checkout is of the mode's kind (``world_gate``) and, in
    a registered run, the repository's prepare config and the registration carry the
    owner's plan (``plan_gate``). Returns the repository, the registration, the
    run-manifest's SHA-256 and the head."""
    repo = Path(args.repo)
    reg, manifest_sha = load_registered(repo, args)
    head = job_gate(
        reg, repo, registration_sha256=args.registration_sha256, manifest_sha256=manifest_sha
    )
    world_gate(repo, args.mode, reg.registration.code_pin)
    plan_gate(args.mode, repo / PREPARE_CONFIG, reg)
    return repo, reg, manifest_sha, head


def plan(args: argparse.Namespace) -> dict[str, object]:
    """``plan`` (the module docstring): the gates, then the two matrices' cells."""
    _, reg, _, head = registered_job(args)
    if args.cells is not None and args.mode != "rehearsal":
        raise ValueError("--cells: a registered run runs every registered cell")
    if args.cells is not None and args.cells < MIN_REHEARSAL_CELLS:
        raise ValueError(
            f"--cells: at least {MIN_REHEARSAL_CELLS} (one W1 cell of each kind, the selector "
            "and a long-only V3 rule both, and one W0 cell), so that every matrix and every "
            "cell path runs"
        )
    cells = smoke_cells(reg, args.cells)
    # Only the selector reads the picks (Ruling F7); the six long-only V3 rules replay
    # their fixed rule, so they run with every other cell and never wait for the picks job.
    v3_cells = [cell.cell_id for cell in cells if needs_picks(cell.arm)]
    main_cells = [cell.cell_id for cell in cells if not needs_picks(cell.arm)]
    for name, listed in (("v3_cells", v3_cells), ("main_cells", main_cells)):
        if not 0 < len(listed) <= MAX_MATRIX:
            raise ValueError(f"{name}: {len(listed)} cells; a matrix takes 1 to {MAX_MATRIX}")
    return {
        "schema": PLAN_SCHEMA,
        "mode": args.mode,
        "registration_sha256": reg.registration.config_pin,
        "code_pin": reg.registration.code_pin,
        "repo_head": head,
        "cells_registered": len(reg.cells),
        "cells_planned": len(cells),
        "v3_cells": v3_cells,
        "main_cells": main_cells,
    }


def picks(args: argparse.Namespace) -> dict[str, object]:
    attempt_id = job_attempt_id(args.attempt_id, V3_PICKS)
    _, reg, _, head = registered_job(args)
    with stand_ins_for(args.mode):
        directory = run_picks(
            reg, Path(args.packs), Path(args.out), attempt_id=attempt_id, repo_head=head
        )
    return {
        "job": V3_PICKS,
        "attempt_id": attempt_id,
        "repo_head": head,
        "directory": str(directory),
        "outcome_sha256": file_sha256(directory / OUTCOME_FILE),
    }


def run_cell(args: argparse.Namespace) -> dict[str, object]:
    repo = Path(args.repo)
    reg, manifest_sha = load_registered(repo, args)
    attempt_id = job_attempt_id(args.attempt_id, args.cell)
    cells = {cell.cell_id: cell for cell in reg.cells}
    if args.cell not in cells:
        raise ValueError(f"execution gate refused cell {args.cell!r}: not a registered cell")
    cell = cells[args.cell]
    head = head_commit(repo)
    changed = changed_since(repo, reg.registration.code_pin)
    pins_now = adapter_pins(repo, head)
    world_gate(repo, args.mode, reg.registration.code_pin)
    plan_gate(args.mode, repo / PREPARE_CONFIG, reg)  # before the pack is read or replayed
    trial = trial_errors(  # likewise: the V3.1 trial's completion authorizes this registration
        repo,
        head,
        code_pin=reg.registration.code_pin,
        config_sha256=reg.registration.config_pin,
        manifest_sha256=reg.run_manifest_pin,
    )
    if trial:
        raise ValueError(f"trial gate refused cell {cell.cell_id!r}:\n- " + "\n- ".join(trial))
    pack_sha = dict(reg.run_manifest.window_packs)[cell.window]
    window_pack = read_pack(Path(args.packs) / window_pack_file(cell.window), pack_sha)
    execution_gate(
        reg,
        cell.cell_id,
        repo_head=head,
        pack_sha256=pack_sha,  # the same pin read_pack checked the pack against
        config_sha256=args.registration_sha256,
        manifest_sha256=manifest_sha,
        changed_paths=changed,
        adapter_pins_now=pins_now,
        pack=window_pack,
    )
    pack: WindowPack | None = window_pack
    del window_pack
    if cell.kind in ("v3", "minute"):
        pack = None  # the gate has checked it; the cell reads its own inputs (Ruling F8)
    with stand_ins_for(args.mode):
        directory = run_cell_job(
            cell,
            pack,
            reg,
            Path(args.out),
            attempt_id=attempt_id,
            repo_head=head,
            repo=repo,
            packs_dir=Path(args.packs),
            picks_dir=None if args.picks is None else Path(args.picks),
            legacy_dir=None if args.legacy_data is None else Path(args.legacy_data),
        )
    return {
        "cell_id": cell.cell_id,
        "kind": cell.kind,
        "attempt_id": attempt_id,
        "repo_head": head,
        "directory": str(directory),
        "outcome_sha256": file_sha256(directory / OUTCOME_FILE),
    }


def dispatch_check_command(
    args: argparse.Namespace,
    opener: GitHubOpener | None = None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> dict[str, object]:
    """``dispatch-check`` (the module docstring). A registered check refuses the first
    earlier launch of the registration that counts, naming it and why, and fails closed
    (``dispatch_check``), its deadline passing included. A report-only check (a
    rehearsal's) prints what a registered one would decide about every earlier launch and
    refuses only when GitHub cannot be read: the current run, the runs listing, the jobs of
    an earlier launch, a record of a shape it does not know, or the deadline passing. A
    launch whose jobs GitHub answers 404 for (deleted since the listing) is listed as gone,
    and is no failure to read. Either names the earlier launches that do not count. Run in
    the plan job, so its deadline is the plan job's budget (``PLAN_JOB_BUDGET``)."""
    launches = dispatch_check(
        args.registration_sha256,
        opener,
        sleep=sleep,
        clock=clock,
        wall=wall,
        job_budget=PLAN_JOB_BUDGET,
        report_only=args.report_only,
    )
    counted = [f"run {launch.run_id}: {launch.reason}" for launch in launches if launch.counts]
    uncounted = [uncounted_line(launch.run_id) for launch in launches if not launch.counts]
    if args.report_only:
        log(
            "dispatch check (report-only): a registered check would "
            + ("refuse; counted: " + "; ".join(counted) if counted else "pass; counted: none")
            + "; not counted: "
            + ("; ".join(uncounted) or "none")
        )
        unreadable = [
            f"run {launch.run_id}: {launch.reason}"
            for launch in launches
            if launch.unreadable and not launch.gone
        ]
        if unreadable:
            raise ValueError(
                "the report-only dispatch check could not read GitHub's records: "
                + "; ".join(unreadable)
            )
    elif counted:
        raise ValueError(
            "another dispatch of this registration: "
            + ", ".join(f"run {launch.run_id}" for launch in launches if launch.counts)
            + "; a registration is dispatched once (Ruling R4-2), so this run stops here ("
            + "; ".join(counted)
            + ")"
            + "".join(f"; {line}" for line in uncounted)
        )
    return {
        "schema": DISPATCH_CHECK_SCHEMA,
        "report_only": args.report_only,
        "registration_sha256": args.registration_sha256,
        "other_dispatches": counted,
        "uncounted_dispatches": uncounted,
    }


def aggregate_cells(
    args: argparse.Namespace,
    opener: GitHubOpener | None = None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> dict[str, object]:
    _, reg, _, _ = registered_job(args)
    # A registered run checks for another dispatch of its registration (Ruling R4-2); a
    # rehearsal dispatches none. An earlier launch stopped at the plan job with nothing run
    # is named, and changes nothing (owner decision v31-d21).
    dispatches, uncounted = (
        dispatch_reasons(reg.registration.config_pin, opener, sleep=sleep, clock=clock, wall=wall)
        if args.mode == "registered"
        else ((), ())
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = aggregate(
        reg,
        Path(args.cells),
        out,
        attempt_id=args.attempt_id,
        mode=args.mode,
        other_dispatches=dispatches,
        uncounted_dispatches=uncounted,
    )
    return _verdict_document(summary)


def _verdict_document(summary: Path) -> dict[str, object]:
    raw = (summary / VERDICT_FILE).read_bytes()
    return {
        "status": json.loads(raw)["status"],
        "summary": str(summary),
        "verdict_sha256": hashlib.sha256(raw).hexdigest(),
    }


def smoke_cells(reg: DriverRegistration, count: int | None) -> list[Cell]:
    """Every registered cell, or the first ``count``: one W1 cell of each kind (for V3,
    the selector and a fixed long-only rule, which run in different matrices) and one W0
    cell first, then the rest in registration order."""
    cells = list(reg.cells)
    if count is None or count >= len(cells):
        return cells
    w1 = [cell for cell in cells if cell.window == ACCEPTANCE_WINDOW]
    firsts = [
        next(cell for cell in w1 if cell.kind == "v31"),
        next(cell for cell in w1 if cell.kind == "hold"),
        next(cell for cell in w1 if cell.kind == "v3" and needs_picks(cell.arm)),
        next(cell for cell in w1 if cell.kind == "v3" and not needs_picks(cell.arm)),
        next(cell for cell in w1 if cell.kind == "minute"),
    ]
    firsts.append(next(cell for cell in cells if cell.window == REPORTED_WINDOW))
    return [*firsts, *(cell for cell in cells if cell not in firsts)][:count]


def build_smoke_packs(
    repo: Path,
    legacy: Path,
    config: PrepareConfig,
    head: str,
    packs_dir: Path,
    *,
    mode: str,
    registration_sha256: str | None = None,
    log: Log | None = None,
) -> dict[str, object]:
    """What prepare builds, from the smoke's synthetic coins, written under the new
    directory ``packs_dir``: each window pack of ``config`` (W1's skipped hours joined by
    its extra sources, ``window_extras`` on the synthetic dataset ``legacy`` with the
    repository ``repo``'s spec, as prepare joins them) and the V3 input pack. Returns the
    prepare document. Run it under ``v31_smoke.stand_ins()``: the masks need them."""
    packs_dir.mkdir()
    sources = [(pin.path, pin.sha256) for pin in config.data_manifests]
    pins: dict[str, str] = {}
    skipped: dict[str, dict[str, object]] = {}
    for window in config.windows:
        extras: dict[str, tuple[int, ...]] = {}
        if window.id == ACCEPTANCE_WINDOW:
            extras = window_extras(repo, legacy, window.start_ms, window.end_ms)
        pack = build_window_pack(
            window.id,
            window.start_ms,
            window.end_ms,
            v31_smoke.window_coins(window.id),
            sources,
            extra_missing_hours=extras,
        )
        pins[window.id] = write_pack(pack, packs_dir / window_pack_file(window.id))
        skipped[window.id] = skipped_document(pack)
        if log is not None:
            log(f"window {window.id}: pack {pins[window.id]}, {len(pack.skipped_hours)} skipped")
    v3_pin = write_v3_pack(v31_smoke.v3_fields(), packs_dir / V3_PACK_FILE)
    return prepare_document(mode, head, config, skipped, pins, v3_pin, registration_sha256)


def smoke_packs(world: v31_smoke.World, packs_dir: Path) -> dict[str, object]:
    """``build_smoke_packs`` for the smoke ``world``."""
    return build_smoke_packs(
        world.repo, world.legacy, world.prepare, world.head, packs_dir, mode="smoke"
    )


def smoke(args: argparse.Namespace) -> dict[str, object]:
    """``smoke`` (the module docstring): a synthetic world, end to end, to a verdict."""
    if args.cells is not None and args.cells < 1:
        raise ValueError("--cells: a positive number of cells required")
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root)
        packs_dir = root / PACKS_DIR
        document = smoke_packs(world, packs_dir)
        reg, _ = v31_smoke.register(world, document, code_pin=world.head)
        pins = dict(reg.run_manifest.window_packs)  # each cell reads its pack by its pin
        attempt = "smoke-attempt-1"
        # The layout aggregation accepts, as the workflow downloads it. The trees holding
        # cells go through their extended-length paths on Windows: a nested bundle file
        # passes 260 characters on a system without long paths (aggregate reads them so).
        cells_dir = _extended(root / "cells")
        picks_dir = cells_dir / "v3-picks-attempt-1" / V3_PICKS
        picks_dir.parent.mkdir(parents=True)
        made = run_picks(
            reg,
            packs_dir,
            _extended(root / "p"),
            attempt_id=job_attempt_id(attempt, V3_PICKS),
            repo_head=world.head,
        )
        made.rename(picks_dir)
        selected = smoke_cells(reg, args.cells)
        for cell in selected:
            pack = read_pack(packs_dir / window_pack_file(cell.window), pins[cell.window])
            directory = run_cell_job(
                cell,
                pack,
                reg,
                _extended(root / "r"),
                attempt_id=job_attempt_id(attempt, cell.cell_id),
                repo_head=world.head,
                repo=world.repo,
                packs_dir=packs_dir,
                picks_dir=picks_dir if needs_picks(cell.arm) else None,  # as the workflow
                legacy_dir=world.legacy,
            )
            folder = cells_dir / f"cell-{cell.cell_id}-attempt-1"
            folder.mkdir()
            directory.rename(folder / cell.cell_id)
        (root / "a").mkdir()
        summary = aggregate(
            reg,
            cells_dir,
            _extended(root / "a"),
            attempt_id=attempt,
            mode="smoke",
            other_dispatches=(),
        )
    seconds = time.monotonic() - began
    log(f"smoke: {len(selected)} of {len(reg.cells)} cells, picks and aggregate in {seconds:.1f} s")
    return {
        "schema": SMOKE_SCHEMA,
        **_verdict_document(summary),
        "cells_registered": len(reg.cells),
        "cells_run": len(selected),
        "stand_ins": list(v31_smoke.STAND_INS),
        "prepare": document,
    }


# --- the rehearsal world (Ruling F3) ----------------------------------------------------


def rehearsal_world(args: argparse.Namespace) -> dict[str, object]:
    """``rehearsal-world`` (the module docstring): the synthetic world a rehearsal runs on.

    The code pin commits the smoke world (``v31_smoke.build_world``: the synthetic legacy
    dataset's spec and manifest, the bot config, the menu, an FX record, snapshot
    stand-ins and the prepare config), every module of this checkout's package
    (``v31_smoke.source_modules``) and the rehearsal marker, on top of the synthetic V3.1
    trial's spec and registration event (``v31_smoke.register_trial``), as the trial gate
    requires of a registered run's code pin. The packs are built once, as prepare-only
    would, into a temporary directory that is then deleted (the rehearsal's prepare job
    builds them again and must reproduce them), and the registration of all 216 cells, its
    adapter pins read at the code pin, is committed on top with the trial's completion
    (``v31_smoke.complete_trial``): the head differs from the code pin by the registration
    artifacts alone, and every job's trial gate runs on it as on a registered run."""
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=False)
    extra = {
        **v31_smoke.source_modules(),
        v31_smoke.REHEARSAL_MARKER: v31_smoke.rehearsal_marker(),
    }
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root, extra_files=extra, trial=True)
        with tempfile.TemporaryDirectory(prefix="packs-", dir=root) as scratch:
            document = build_smoke_packs(
                world.repo,
                world.legacy,
                world.prepare,
                world.head,
                Path(scratch) / PACKS_DIR,
                mode="rehearsal",
            )
    pins = adapter_pins(world.repo, world.head)
    reg, config_sha = v31_smoke.register(world, document, code_pin=world.head, adapter_pins=pins)
    v31_smoke.complete_trial(
        world.repo,
        code_pin=world.head,
        config_sha256=config_sha,
        manifest_sha256=reg.run_manifest_pin,
    )
    head = v31_smoke.commit_all(world.repo, "the rehearsal registration (synthetic)")
    return {
        "schema": REHEARSAL_WORLD_SCHEMA,
        "repo": str(world.repo),
        "legacy": str(world.legacy),
        "code_pin": world.head,
        "head": head,
        "registration_sha256": config_sha,
        "cells_registered": len(reg.cells),
        "window_packs": document["window_packs"],
        "v3_pack_sha256": document["v3_pack_sha256"],
        "stand_ins": list(v31_smoke.STAND_INS),
    }


# --- timing (Ruling F4) -----------------------------------------------------------------


def peak_rss_kib() -> int | None:
    """This process's peak resident set size so far, in KiB (``ru_maxrss`` on Linux);
    None where ``resource`` does not exist (Windows)."""
    try:
        resource = importlib.import_module("resource")
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


_wall: Callable[[], float] = time.time  # wall-clock seconds; replaced in tests


class TimingLog:
    """A timing part's streamed record ``out/<part>.timing.jsonl``: one canonical line per
    event, each flushed and synced, so a part killed at its step timeout keeps what it
    measured. Every line holds the elapsed seconds and the peak RSS so far; the first is
    ``started`` with the wall-clock start. Only ``TIMING_KEYS`` may appear."""

    def __init__(self, out: Path, part: str) -> None:
        out.mkdir(parents=True, exist_ok=True)
        self.out, self.part = out, part
        self._stream: BinaryIO = (out / f"{part}.timing.jsonl").open("xb")
        self._began = time.monotonic()
        self.phases: dict[str, float] = {}
        self.event("started", started_at=round(_wall(), 3))

    def elapsed(self) -> float:
        return round(time.monotonic() - self._began, 3)

    def event(self, name: str, **fields: object) -> None:
        line = {"event": name, "elapsed_s": self.elapsed(), "peak_rss_kib": peak_rss_kib()}
        write_timing_line(self._stream, {**line, **fields})

    @contextlib.contextmanager
    def phase(self, name: str, *, strategy: bool = False) -> Iterator[None]:
        """Time the block as phase ``name``. A ``strategy`` phase computes on market data:
        its error is reported by type alone, so no message can carry a value."""
        began = time.monotonic()
        try:
            yield
        except Exception as exc:
            self.event("failed", phase=name, error_type=type(exc).__name__)
            if strategy:
                raise ValueError(
                    f"timing {self.part}: the {name} step failed with {type(exc).__name__} "
                    "(its message is withheld: timing prints no strategy value)"
                ) from None
            raise
        self.phases[name] = round(time.monotonic() - began, 3)
        self.event("phase", phase=name, seconds=self.phases[name])

    def finish(self, head: str, **counts: object) -> dict[str, object]:
        """The part's summary, written once to ``out/<part>.json``, and the stream closed."""
        self.event("finished")
        self._stream.close()
        document = {
            "schema": TIMING_SCHEMA,
            "part": self.part,
            "finished": True,
            "code_commit": head,
            "elapsed_s": self.elapsed(),
            "peak_rss_kib": peak_rss_kib(),
            "phases": dict(self.phases),
            **counts,
        }
        check_timing_keys(document)
        with open(self.out / f"{self.part}.json", "xb") as handle:
            handle.write(canonical(document))
        return document

    def close(self) -> None:
        if not self._stream.closed:
            self._stream.close()


def check_timing_keys(document: Mapping[str, object]) -> None:
    """Refuse any key outside ``TIMING_KEYS``, nested ones included: a timing file holds
    times, memory, counts and names, never an outcome, report or equity value."""
    for key, value in document.items():
        if key not in TIMING_KEYS:
            raise ValueError(f"timing: the key {key!r} is not a timing field")
        if isinstance(value, Mapping) and key != "phases":
            check_timing_keys(value)


def write_timing_line(stream: BinaryIO, row: Mapping[str, object]) -> None:
    check_timing_keys(row)
    stream.write(canonical(dict(row)))
    stream.flush()
    os.fsync(stream.fileno())


class TimedAttempts:
    """V3's record callback in timing mode. Each ``Attempt`` goes first to the real
    ``_AttemptLog`` (in a temporary directory that is deleted, as V3's contract asks:
    persisted before the walk-forward goes on), then, as bookkeeping only, to
    ``out/picks.attempts.jsonl``: its run (the random prefix dropped), state, phase,
    rule, window, multiples, the type of any error, whether a result exists, and the
    elapsed time and peak RSS. Never the result, the error's message or the picks."""

    def __init__(self, log: _AttemptLog, path: Path, timing: TimingLog) -> None:
        self._log, self._timing = log, timing
        self._stream: BinaryIO = path.open("xb")
        self.count = 0

    def __call__(self, attempt: Attempt) -> None:
        self._log(attempt)
        self.count += 1
        error = attempt.error
        row = {
            "seq": self.count,
            "elapsed_s": self._timing.elapsed(),
            "peak_rss_kib": peak_rss_kib(),
            "run": attempt.run_id.partition("-")[2],
            "state": attempt.state,
            "phase": attempt.phase,
            "rule": attempt.rule,
            "start_ms": attempt.start_ms,
            "end_ms_exclusive": attempt.end_ms_exclusive,
            "multiple": attempt.multiple,
            "cost_multiple": attempt.cost_multiple,
            "error_type": None if error is None else error.partition(":")[0],
            "has_result": attempt.result is not None,
        }
        write_timing_line(self._stream, row)

    def close(self) -> None:
        self._stream.close()


def timing_registration(
    repo: Path, head: str, config: PrepareConfig, w1_skipped: Sequence[int], root: Path
) -> DriverRegistration:
    """A throwaway registration for the timing cell, never committed and never a run's:
    the prepare config's windows (W1's skipped hours ``w1_skipped``, W0's none), every
    arm's adapter pin at ``head``, the code pin ``head``, and a run-manifest whose pack
    pins name no pack (none is built or read: a minute cell reads the legacy dataset,
    which the prepare config pins). Written under the temporary directory ``root``, with
    the repository's menu and FX record (the smoke's, labelled synthetic, if it has
    none): a minute cell needs its window, capital, pins and the legacy manifest's pin."""
    (root / "config").mkdir(parents=True)
    (root / MENU_PATH).write_bytes((repo / MENU_PATH).read_bytes())
    fx = repo / v31_smoke.FX_RECORD
    if fx.is_file():
        (root / v31_smoke.FX_RECORD).write_bytes(fx.read_bytes())
    else:
        v31_smoke.write_json(root / v31_smoke.FX_RECORD, v31_smoke.fx_record())
    no_pack = hashlib.sha256(b"v3.1 timing: no pack is built or read").hexdigest()
    document = {
        "window_packs": {window.id: no_pack for window in config.windows},
        "v3_pack_sha256": no_pack,
        "skipped_hours": {
            window.id: {"hours": list(w1_skipped) if window.id == ACCEPTANCE_WINDOW else []}
            for window in config.windows
        },
    }
    world = v31_smoke.World(root, root, head, root, config)
    reg, _ = v31_smoke.register(
        world, document, code_pin=head, adapter_pins=adapter_pins(repo, head)
    )
    return reg


def timing(
    args: argparse.Namespace,
    *,
    inventory_transport: ArchiveTransport,
    legacy_transport: ArchiveTransport,
    sleep: Callable[[float], None],
    log: Log,
    v3_pack_builder: V3PackBuilder,
) -> dict[str, object]:
    """``timing`` (the module docstring): one part, timed, its results discarded."""
    repo, out, scratch = Path(args.repo), Path(args.out), Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    record = TimingLog(out, args.part)
    try:
        if args.part == "prepare":
            prepared = argparse.Namespace(
                repo=args.repo,
                prepare_config=args.prepare_config,
                mode="prepare-only",
                code_commit=args.code_commit,
                prepare_sha256=args.prepare_sha256,
                work=str(scratch / "prepare-work"),
                out=str(scratch / "prepare-out"),
            )
            with record.phase("prepare"):
                prepare(
                    prepared,
                    inventory_transport=inventory_transport,
                    legacy_transport=legacy_transport,
                    sleep=sleep,
                    log=log,
                    v3_pack_builder=v3_pack_builder,
                )
            return record.finish(head_commit(repo))
        with record.phase("gate"):
            config = load_prepare_config(repo / args.prepare_config)
            head = head_commit(repo)
            prepare_only_gate(
                repo, head, config, code_commit=args.code_commit, prepare_sha256=args.prepare_sha256
            )
            world_gate(repo, "timing", head)
            plan_gate("timing", config)
            plan_ = plan_prepare(repo, head, config)
        work = scratch / "work"
        family = "inventory" if args.part == "picks" else "legacy"
        with record.phase(f"fetch_{family}"):
            fetch_all(
                plan_,
                work,
                inventory_transport=inventory_transport,
                legacy_transport=legacy_transport,
                sleep=sleep,
                log=log,
                families=(family,),
            )
        if args.part == "picks":
            return timing_picks(record, plan_, head, work, scratch, v3_pack_builder)
        return timing_cell(record, repo, plan_, head, work, scratch)
    finally:
        record.close()


def timing_picks(
    record: TimingLog,
    plan_: Plan,
    head: str,
    work: Path,
    scratch: Path,
    v3_pack_builder: V3PackBuilder,
) -> dict[str, object]:
    """The picks part: the real V3 input pack, then V3's real walk-forward, each attempt
    streamed to the bookkeeping file; the picks and the attempt log are discarded."""
    with tempfile.TemporaryDirectory(prefix="timing-picks-", dir=scratch) as discarded:
        temporary = Path(discarded)
        with record.phase("build_v3_pack"):
            root = place_inventory(plan_, work)
            path = temporary / V3_PACK_FILE
            pin = v3_pack_builder(root, plan_.inventory_sha, plan_.first_months, path)
        with record.phase("read_v3_pack"):
            inputs = read_v3_pack(path, pin)
        attempt_log = _AttemptLog(temporary / "attempts.jsonl")
        attempts = TimedAttempts(attempt_log, record.out / "picks.attempts.jsonl", record)
        try:
            with record.phase("picks", strategy=True), attempt_log:
                selector_picks(inputs, record=attempts)
        finally:
            attempts.close()
        del inputs
    return record.finish(head, attempt_records=attempts.count)


def timing_cell(
    record: TimingLog, repo: Path, plan_: Plan, head: str, work: Path, scratch: Path
) -> dict[str, object]:
    """The cell part: the verified legacy dataset, W1's extra skipped hours (the frozen
    masks and rule 8 on real data), then ``TIMING_CELL`` under a throwaway registration;
    its artifacts are deleted."""
    legacy = work / LEGACY_DIR
    with record.phase("verify_legacy"):
        verify_legacy(repo, legacy)
    (window,) = [w for w in plan_.prepare.windows if w.id == ACCEPTANCE_WINDOW]
    with record.phase("w1_extra_skipped_hours"):
        extras = window_extras(repo, legacy, window.start_ms, window.end_ms)
    skipped = sorted({hour for hours in extras.values() for hour in hours})
    with tempfile.TemporaryDirectory(prefix="timing-cell-", dir=scratch) as discarded:
        temporary = Path(discarded)
        reg = timing_registration(repo, head, plan_.prepare, skipped, temporary / "registration")
        (cell,) = [c for c in reg.cells if c.cell_id == TIMING_CELL]
        (temporary / "cell").mkdir()
        with record.phase("minute_cell", strategy=True):
            run_minute_cell(
                cell,
                legacy,
                reg,
                temporary / "cell",
                attempt_id=f"timing-{cell.cell_id}-attempt-1",
                repo_head=head,
                repo_root=repo,
            )
    return record.finish(head, cell=TIMING_CELL)


def timing_close(args: argparse.Namespace) -> dict[str, object]:
    """``timing-close`` (the module docstring): what a timing step measured, finished or
    not, from its streamed record; written once to ``out/<part>.close.json``."""
    if args.step_outcome not in STEP_OUTCOMES:
        raise ValueError(f"--step-outcome {args.step_outcome!r}: one of {STEP_OUTCOMES}")
    out, part = Path(args.out), args.part
    stream = out / f"{part}.timing.jsonl"
    events = (
        [json.loads(line) for line in stream.read_bytes().splitlines()] if stream.is_file() else []
    )
    for event in events:
        check_timing_keys(event)
    started = events[0].get("started_at") if events else None
    elapsed = None if started is None else round(_wall() - started, 3)
    attempts = out / "picks.attempts.jsonl"
    seen = [e["peak_rss_kib"] for e in events if e.get("peak_rss_kib") is not None]
    if part == "picks" and attempts.is_file():
        rows = [json.loads(line) for line in attempts.read_bytes().splitlines()]
        seen += [row["peak_rss_kib"] for row in rows if row.get("peak_rss_kib") is not None]
    document: dict[str, object] = {
        "schema": TIMING_CLOSE_SCHEMA,
        "part": part,
        "step_outcome": args.step_outcome,
        "step_timeout_minutes": args.step_timeout_minutes,
        "finished": (out / f"{part}.json").is_file(),
        "elapsed_s_until_close": elapsed,
        "timed_out": elapsed is not None and elapsed >= args.step_timeout_minutes * 60,
        "last_event": events[-1]["event"] if events else None,
        "last_event_elapsed_s": events[-1]["elapsed_s"] if events else None,
        "peak_rss_kib_seen": max(seen, default=None),
    }
    if part == "picks":
        document["attempt_records"] = (
            len(attempts.read_bytes().splitlines()) if attempts.is_file() else 0
        )
    check_timing_keys(document)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{part}.close.json", "xb") as handle:
        handle.write(canonical(document))
    return document


# --- the command line -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v31_driver.py", description="The V3.1 run driver (see the module docstring)."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def registered(command: argparse.ArgumentParser, *, required: bool = True) -> None:
        command.add_argument("--repo", default=".", help="the checkout (default: .)")
        command.add_argument("--registration", default=REGISTRATION)
        command.add_argument("--run-manifest", default=RUN_MANIFEST)
        command.add_argument(
            "--registration-sha256",
            required=required,
            help="the dispatch's pin of the registration file",
        )

    def run_mode(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--mode",
            choices=RUN_MODES,
            default="registered",
            help="registered (the repository's registration) or rehearsal (a synthetic "
            "rehearsal world, --repo; the only mode that runs the smoke's stand-ins)",
        )

    def attempt(command: argparse.ArgumentParser, recorded: str) -> None:
        command.add_argument(
            "--attempt-id",
            required=True,
            help=f"the workflow's <run_id>-attempt-<run_attempt>, the same for every job of a "
            f"run; {recorded}",
        )

    planned = commands.add_parser("plan", help="the gates, then the matrices' cells")
    run_mode(planned)
    registered(planned)
    planned.add_argument(
        "--cells",
        type=cell_count,
        default=None,
        help=f"a rehearsal: plan only this many cells (at least {MIN_REHEARSAL_CELLS}); "
        "empty: every registered cell",
    )

    check = commands.add_parser(
        "dispatch-check",
        help="refuse a second dispatch of the registration (registered); report only (a rehearsal)",
    )
    check.add_argument(
        "--registration-sha256",
        required=True,
        help="the dispatch's pin of the registration file (--report-only: the rehearsal's "
        "registration_sha256 input, which may be empty)",
    )
    check.add_argument(
        "--report-only",
        action="store_true",
        help="a rehearsal's check: look for the rehearsal's own title, print what a "
        "registered check would decide, and refuse only when GitHub cannot be read",
    )

    prep = commands.add_parser("prepare", help="fetch, verify and pack every input")
    prep.add_argument("--mode", choices=("prepare-only", *RUN_MODES), required=True)
    registered(prep, required=False)
    prep.add_argument("--prepare-config", default=PREPARE_CONFIG)
    prep.add_argument("--prepare-sha256", help="prepare-only: the expected prepare config pin")
    prep.add_argument("--code-commit", help="prepare-only: the expected checkout head")
    prep.add_argument("--work", required=True, help="the archive cache (may exist)")
    prep.add_argument("--out", required=True, help="the output directory (must not exist)")

    pick = commands.add_parser("picks", help="V3's selector picks, once")
    run_mode(pick)
    registered(pick)
    pick.add_argument("--packs", required=True)
    attempt(pick, "the picks job records <run_id>-v3_picks-attempt-<run_attempt>")
    pick.add_argument("--out", required=True)

    cell = commands.add_parser("run-cell", help="one registered cell")
    run_mode(cell)
    registered(cell)
    cell.add_argument("--cell", required=True)
    cell.add_argument("--packs", required=True)
    attempt(
        cell,
        "the cell records <run_id>-<cell_id>-attempt-<run_attempt>, unique per cell as "
        "acceptance requires",
    )
    cell.add_argument("--out", required=True)
    cell.add_argument(
        "--picks",
        help="the V3 selector (only): the v3_picks/ directory of the same run; a fixed "
        "long-only V3 rule refuses it",
    )
    cell.add_argument("--legacy-data", help="a minute cell: the verified legacy dataset")

    agg = commands.add_parser("aggregate", help="the verdict and summary")
    run_mode(agg)
    registered(agg)
    agg.add_argument("--cells", required=True)
    attempt(
        agg,
        "every W1 cell and the picks job must be attempt 1 of run <run_id>, or the verdict "
        "is incomplete (re-run detected)",
    )
    agg.add_argument("--out", required=True)

    smoke_ = commands.add_parser("smoke", help="offline, synthetic, end to end")
    smoke_.add_argument("--out", required=True, help="the smoke's directory (must not exist)")
    smoke_.add_argument("--cells", type=int, help="run only this many cells (default: all)")

    world = commands.add_parser("rehearsal-world", help="the rehearsal's synthetic world")
    world.add_argument("--out", required=True, help="the world's directory (must not exist)")

    timed = commands.add_parser("timing", help="time one heavy step, results discarded")
    timed.add_argument("--part", choices=TIMING_PARTS, required=True)
    timed.add_argument("--repo", default=".", help="the checkout (default: .)")
    timed.add_argument("--prepare-config", default=PREPARE_CONFIG)
    timed.add_argument("--code-commit", required=True, help="the expected checkout head")
    timed.add_argument("--prepare-sha256", required=True, help="the prepare config's pin")
    timed.add_argument("--scratch", required=True, help="data and discarded results")
    timed.add_argument("--out", required=True, help="the timing files, the only upload")

    close = commands.add_parser("timing-close", help="record a timing step's end")
    close.add_argument("--part", choices=TIMING_PARTS, required=True)
    close.add_argument("--step-outcome", required=True, help="the step's outcome")
    close.add_argument("--step-timeout-minutes", type=int, required=True)
    close.add_argument("--out", required=True)
    return parser


def cell_count(text: str) -> int | None:
    """A ``--cells`` value: empty for every cell, else a positive integer."""
    if text == "":
        return None
    if re.fullmatch(r"[1-9][0-9]*", text) is None:
        raise argparse.ArgumentTypeError(f"{text!r}: empty or a positive integer required")
    return int(text)


class NoNetwork:
    """The transport of a rehearsal's prepare, which fetches nothing: any use is refused."""

    def archive(self, path: str) -> bytes | None:
        raise ValueError(f"a rehearsal fetches nothing; {path} was requested")


def main(
    argv: Sequence[str] | None = None,
    *,
    inventory_transport: ArchiveTransport | None = None,
    legacy_transport: ArchiveTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    v3_pack_builder: V3PackBuilder = build_v3_pack,
    github_opener: GitHubOpener | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> int:
    """Run one subcommand; 0 with its document on stdout, 1 on a refusal (on stderr).

    The keyword arguments replace prepare's transports, the retry sleep (prepare's and the
    dispatch check's), the V3 pack builder, the dispatch check's opener and the clocks of
    its deadline (tests); by default the real guarded transports, ``time.sleep``, urllib's
    opener (``dispatch_check``), ``time.monotonic`` and ``time.time``."""
    args = build_parser().parse_args(argv)
    try:
        if args.command in ("prepare", "timing"):
            offline = args.command == "prepare" and args.mode == "rehearsal"
            network: dict[str, ArchiveTransport] = {
                "inventory_transport": (
                    NoNetwork()
                    if offline
                    else V3Transport()
                    if inventory_transport is None
                    else inventory_transport
                ),
                "legacy_transport": (
                    NoNetwork()
                    if offline
                    else LegacyTransport()
                    if legacy_transport is None
                    else legacy_transport
                ),
            }
            run = prepare if args.command == "prepare" else timing
            document = run(args, **network, sleep=sleep, log=log, v3_pack_builder=v3_pack_builder)
        elif args.command == "plan":
            document = plan(args)
        elif args.command == "dispatch-check":
            document = dispatch_check_command(
                args, github_opener, sleep=sleep, clock=clock, wall=wall
            )
        elif args.command == "picks":
            document = picks(args)
        elif args.command == "run-cell":
            document = run_cell(args)
        elif args.command == "aggregate":
            document = aggregate_cells(args, github_opener, sleep=sleep, clock=clock, wall=wall)
        elif args.command == "rehearsal-world":
            document = rehearsal_world(args)
        elif args.command == "timing-close":
            document = timing_close(args)
        else:
            document = smoke(args)
    except (ValueError, OSError, FeedError) as exc:  # OSError: a missing or existing path
        log(f"v31_driver {args.command}: refused: {exc}")
        return 1
    sys.stdout.write(canonical(document).decode("ascii"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
