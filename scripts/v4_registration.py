"""V4.0's registration files, the run's job gate and its dispatch check: V3.1's registration pattern
with V4's files, trial, workflow and jobs.

V4's registered run is registered as V3.1's was (spec, "Registration and the run"): a trial register
entry before the code pin; the code pin, the data pins and the run manifest; the registration file
and its review; the owner's go; one dispatch, never cancelled, never re-run. Step 5 writes the real
registration files. This script reads and checks them in every job of
``.github/workflows/v4-run.yml``, refuses a second dispatch of a registration, and builds the
repository of the synthetic rehearsal world, which the workflow's rehearsal gates exactly as a
registered run is gated (``build_rehearsal_repo``). V3.1's generic helpers are imported unchanged
from ``scripts/v31_driver.py``, ``scripts/trial_register.py`` and
``crypto_grid_bot.combined.driver.run_cell``; each V3.1 function that hard-codes V3.1's files,
family, workflow or jobs is copied here with V4's, and its docstring names the original.

**The files** (Ruling G1), both canonical JSON (``combined.artifacts._canonical``: sorted keys, no
spaces, ASCII, no newline):

- ``config/v4_registration.json`` (``read_registration``): exactly ``schema``
  (``v4-registration-1``), ``code_pin`` (40 lowercase hex), ``run_manifest_sha256``, ``spec``
  (``{path, sha256}``), ``cells`` (the 48 ids of ``arms.all_cells()``, in order) and ``trial_id``.
  It never holds its own SHA-256: the dispatch passes it.
- ``config/v4_run_manifest.json`` (``read_manifest``): exactly ``schema`` (``v4-run-manifest-1``),
  ``data`` (``{config_path, config_sha256, end_month, daily_sha256, index_sha256}``) and
  ``v3_pack_sha256``.

``gate --repo R --mode registered|rehearsal --registration-sha256 S [--github-output F]`` is the
job gate (Rulings G2, G3). It reads the checkout ``R``:

1. the registration file hashes to ``S`` and reads;
2. the run manifest hashes to the registration's ``run_manifest_sha256`` and reads;
3. the checkout is of the mode's kind (``world_errors``): a rehearsal needs ``REHEARSAL_MARKER``,
   byte for byte ``marker_bytes()``, at the code pin and in the working tree; a registered run
   refuses it in the working tree, at the head and at the code pin;
4. nothing changed since the code pin, in the commits to the head or in the tracked working tree,
   but ``ALLOWED`` (the two files and the trial register) and anything under ``docs/reviews/`` or
   ``docs/tasks/`` (``run_cell.changed_since``, ``run_cell._allowed``);
5. the V4 trial authorizes the registration (``trial_errors``): exactly one ``spec-v4.0``
   completion, in the trial register as the head commits it, pins the registration at ``S``; its
   trial passes ``trial_register.check_ready`` at the head; the completion pins the code pin and
   the run manifest at the registration's pin; and the registration names that trial and the
   spec its registration event pinned.

Accepted, it appends ``code_pin``, ``v3_pack_sha256`` and the manifest's five data pins to ``F``
as ``key=value`` lines (GitHub's step outputs), then prints one line. Refused, it prints every
error on a line of its own on standard error, writes nothing, and exits 1.

``dispatch-check --mode M --registration-sha256 S [--report-only] [--judge-all] [--out F]`` is one
dispatch per registration (Ruling G4): V3.1's check (``v31_driver.dispatch_check_command``, owner
decision v31-d21's layers L1 to L3), on V4's workflow, whose runs GitHub titles ``v4-run <mode>
<registration_sha256>`` (``run_titles``), and on V4's jobs (``launch_decision``):

- ``--mode registered`` (the plan job's check) refuses another run titled ``v4-run registered S``
  created before this run (``GITHUB_RUN_ID``) or in the same second, naming the first that counts
  and why, unless GitHub's records show it stopped at the plan job with nothing run. It refuses
  too on any failure to read GitHub's API (a transient one after its retries) and at its
  deadline: 20 minutes, and no later than ``PLAN_JOB_BUDGET`` after the job's start
  (``V4_JOB_STARTED``, which the job's first step records).
- ``--report-only`` goes with ``--mode rehearsal`` or ``timing``, and only with them; ``S`` may be
  empty. It looks for the mode's own titles, logs what a registered check would decide about
  every earlier launch, and refuses only when GitHub cannot be read. It also reads this run's
  own job listing and checks its shape.
- ``--judge-all`` (the verdict job's check; ``--mode registered`` and ``--out`` required) is
  V3.1's ``dispatch_reasons``. It judges every earlier launch, refuses none, and writes each one
  that counts, or why none could be ruled out (any failure of the check, its deadline of
  ``VERDICT_JOB_BUDGET`` after the job's start among them), so the verdict is incomplete. New
  in V4, it also reads the current run's own attempts (``replay_reasons``; spec, "Registration
  and the run", item 5): after a first attempt, every job record of every attempt
  (``run_jobs``, ``filter=all``, with the same retries and deadline). It writes a line for each
  job other than ``verdict``, ``analysis`` and ``status`` (``RERUN_JOBS``, the single
  aggregate-only re-run's) that ran in an attempt after the first, even one that failed before
  it uploaded anything, so that no artifact names it; one for an attempt past
  ``MAX_RUN_ATTEMPT``; and one when the attempts cannot be read.

``--out F`` writes ``{"format": "v4-dispatch-check-1", "earlier": [...]}``, one line per reason
(this run's attempts, an earlier launch that counts, or a check that could not rule one out),
the verdict step's ``--dispatch-reasons`` (``report.read_dispatch_reasons``).
It is canonical JSON, created exclusively, and written only when the check passes. An ``F`` that
exists is refused before any request. The check prints one line of counts on standard output;
its decisions and retries go to standard error.

``build_rehearsal_repo`` is the rehearsal world's repository (Task 7 tars it into ``world.tar``).

**Exit status**: 0 when the gate accepts or the check passes (``--judge-all``: once its file is
written); 1 on a refusal; 2 for bad arguments (argparse's own).

**Public logs**: counts, ids, titles, run ids, commits and pins only. Nothing here reads market
data, a cell's outcome or a verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess  # nosec B404
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from trial_register import _parse, append_event, check_ready, code_digest
from v31_driver import (
    _GITHUB_REPOSITORY,
    _RUN_ID,
    GITHUB_API,
    RUNS_PER_PAGE,
    CurrentRunMissing,
    DeadlineExpired,
    EarlierLaunch,
    GitHubNotFound,
    GitHubOpener,
    Log,
    _committed,
    _Deadline,
    _job_fields_error,
    _listing,
    _NoRedirect,
    _repo_path,
    _run_fields,
    _sha,
    github_json,
    github_retry,
    job_listing_error,
    log,
    run_jobs,
    strict_json,
    uncounted_line,
)

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.driver.run_cell import _allowed, changed_since, head_commit
from crypto_grid_bot.v4.engine.arms import all_cells
from crypto_grid_bot.v4.verdict.report import DISPATCH_FORMAT

REGISTRATION = "config/v4_registration.json"
RUN_MANIFEST = "config/v4_run_manifest.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"
# A rehearsal world commits this file at its code pin; a registered run refuses any checkout
# holding it (Ruling G3). The repository itself never holds it.
REHEARSAL_MARKER = "config/v4_rehearsal.json"
V4_FAMILY = "spec-v4.0"  # the V4 trial, whose completion authorizes the registration
WORKFLOW_FILE = "v4-run.yml"
REGISTRATION_SCHEMA = "v4-registration-1"
MANIFEST_SCHEMA = "v4-run-manifest-1"
DISPATCH_CHECK_SCHEMA = DISPATCH_FORMAT  # "v4-dispatch-check-1": the verdict step reads it
# The files that may differ from the code pin, besides anything under docs/reviews/ and
# docs/tasks/ (run_cell.REGISTRATION_DIRECTORIES, which run_cell._allowed adds; Ruling G2).
ALLOWED = frozenset({REGISTRATION, RUN_MANIFEST, TRIAL_REGISTER})
# The dispatch check's deadline counts from its job's start, recorded by the job's first step,
# and ends at least five minutes inside the job's timeout (Ruling G4): 25 of the plan job's 60
# minutes, and 55 of the verdict job's 180, which leaves the verdict more than two hours after it.
JOB_STARTED = "V4_JOB_STARTED"
PLAN_JOB_BUDGET = 25 * 60  # seconds
VERDICT_JOB_BUDGET = 55 * 60  # seconds
# The workflow's jobs, as GitHub's jobs listing names them (L2): the plan job, the status job
# that always runs, and every other job, which a launch stopped at the plan job skips. A matrix
# job is named "<job> (<matrix values>)", or "<job>" when skipped before its matrix expanded.
PLAN_JOB = "plan"
STATUS_JOB = "status"
SKIPPED_JOBS = ("v3-pack", "v3-picks", "scenarios", "verdict", "analysis")
SKIPPED_MATRIX_JOBS = ("cell", "v3-cell")
# The spec's single aggregate-only re-run, after an infrastructure failure ("Registration and the
# run", item 5): a registered run's second attempt may run these jobs again and no other, the
# verdict job and the jobs GitHub may run beside it (the status job needs every job). A third
# attempt is a second re-run.
RERUN_JOBS = ("verdict", "analysis", STATUS_JOB)
MAX_RUN_ATTEMPT = 2
GATE_MODES = ("registered", "rehearsal")  # the registered job graph, on the repo or a world
TITLE_MODES = ("registered", "rehearsal", "timing")  # the workflow's modes, in its run-name
# The workflow's name, which starts its run-name:
# v4-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}
RUN_NAME = "v4-run"
SPEC = "docs/superpowers/specs/2026-10-17-v4-design.md"  # V4's spec, at its real path
REHEARSAL_SCHEMA = "v4-rehearsal-1"
REHEARSAL_TRIAL = "v4-0-synthetic"  # the rehearsal world's synthetic trial
MAX_FILE_BYTES = 1 << 20  # the registration and the run manifest hold a few kilobytes

_REGISTRATION_KEYS = frozenset(
    {"schema", "code_pin", "run_manifest_sha256", "spec", "cells", "trial_id"}
)
_MANIFEST_KEYS = frozenset({"schema", "data", "v3_pack_sha256"})
# The run manifest's data pins, in the order GitHub's outputs list them.
_DATA_ORDER = ("config_path", "config_sha256", "end_month", "daily_sha256", "index_sha256")
_DATA_KEYS = frozenset(_DATA_ORDER)
_SPEC_KEYS = frozenset({"path", "sha256"})
_COMMIT = re.compile("[0-9a-f]{40}")
_MONTH = re.compile("[0-9]{4}-(?:0[1-9]|1[0-2])")
_TRIAL_ID = re.compile("[A-Za-z0-9][A-Za-z0-9._-]*")
# What the rehearsal repository copies from the checkout (the tracked files only), and
# trial_register.check_ready's code inventory, which the completion lists.
_COPIED = ("src", "scripts", "pyproject.toml", "requirements-dev.lock")
_CODE_PREFIXES = ("src/", "scripts/")
_CODE_FILES = frozenset({"pyproject.toml", "requirements-dev.lock", "requirements.txt"})
_RECORDED_AT = "2024-12-31T00:00:00Z"  # the synthetic trial's events
# Every git call of the rehearsal repository: its identity, LF bytes as written, no signing and
# no hook, all passed with -c, so no config is written and none of the machine's is needed.
_GIT_OPTIONS = (
    "-c",
    "user.name=v4-rehearsal",
    "-c",
    "user.email=rehearsal@invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.hooksPath=.git/v4-no-hooks",
    "-c",
    "init.defaultBranch=main",
)


# ---- the registration files (Ruling G1) --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunManifest:
    """The run manifest: the data run's pins (``data``: ``config_path``, ``config_sha256``,
    ``end_month``, ``daily_sha256``, ``index_sha256``) and V3's input pack's pin."""

    data: Mapping[str, str]
    v3_pack_sha256: str


@dataclass(frozen=True, slots=True)
class Registration:
    """The registration file: the code pin, the run manifest's pin, the spec (``{path,
    sha256}``), the 48 cells and the trial that registers them."""

    code_pin: str
    run_manifest_sha256: str
    spec: Mapping[str, str]
    cells: tuple[str, ...]
    trial_id: str


@dataclass(frozen=True, slots=True)
class Gated:
    """What the job gate accepted: the head, the registration, the run manifest and the
    registration's SHA-256, the dispatch's pin."""

    head: str
    registration: Registration
    manifest: RunManifest
    registration_sha256: str


class GateError(ValueError):
    """The job gate's refusal: ``errors``, every check that failed, one line each."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("job gate refused:\n- " + "\n- ".join(self.errors))


def registered_cells() -> tuple[str, ...]:
    """The 48 cell ids a registration lists: ``arms.all_cells()``, in order."""
    return tuple(cell.cell_id for cell in all_cells())


def _document(raw: bytes, what: str) -> dict[str, Any]:
    """``raw`` as a strict canonical JSON object: at most ``MAX_FILE_BYTES``, UTF-8, unique keys,
    and byte for byte ``combined.artifacts._canonical`` of its own parse."""
    if type(raw) is not bytes:
        raise ValueError(f"{what}: bytes required")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{what}: larger than {MAX_FILE_BYTES} bytes")
    try:
        document = strict_json(raw, what)
    except ValueError as exc:
        raise ValueError(f"{what}: not strict JSON ({exc})") from None
    if not isinstance(document, dict):
        raise ValueError(f"{what}: a JSON object required")
    try:
        canonical = _canonical(document)
    except ValueError:
        canonical = None  # a float: never canonical
    if canonical != raw:
        raise ValueError(
            f"{what}: not canonical JSON (sorted keys, no spaces, ASCII, no newline: "
            "combined.artifacts._canonical)"
        )
    return document


def _exact_keys(document: object, keys: frozenset[str], what: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError(f"{what}: a JSON object required")
    if set(document) != keys:
        raise ValueError(f"{what}: the keys are {sorted(document)}, not exactly {sorted(keys)}")
    return document


def read_manifest(raw: bytes) -> RunManifest:
    """The run manifest of ``raw`` (Ruling G1), or one ``ValueError`` saying what is wrong:
    canonical JSON with exactly ``schema`` (``MANIFEST_SCHEMA``), ``data`` (exactly a repository
    path ``config_path``, the SHA-256s ``config_sha256``, ``daily_sha256`` and ``index_sha256``,
    and an ``end_month`` ``YYYY-MM``) and the SHA-256 ``v3_pack_sha256``."""
    what = RUN_MANIFEST
    document = _exact_keys(_document(raw, what), _MANIFEST_KEYS, what)
    if document["schema"] != MANIFEST_SCHEMA:
        raise ValueError(f"{what}: schema {document['schema']!r}, not {MANIFEST_SCHEMA}")
    data = _exact_keys(document["data"], _DATA_KEYS, f"{what} data")
    _repo_path(data["config_path"], f"{what} data.config_path")
    for key in ("config_sha256", "daily_sha256", "index_sha256"):
        _sha(data[key], f"{what} data.{key}")
    month = data["end_month"]
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise ValueError(f"{what} data.end_month: a month YYYY-MM required")
    pack = _sha(document["v3_pack_sha256"], f"{what} v3_pack_sha256")
    return RunManifest(MappingProxyType({key: data[key] for key in _DATA_ORDER}), pack)


def read_registration(raw: bytes) -> Registration:
    """The registration of ``raw`` (Ruling G1), or one ``ValueError`` saying what is wrong:
    canonical JSON with exactly ``schema`` (``REGISTRATION_SCHEMA``), ``code_pin`` (40 lowercase
    hex), ``run_manifest_sha256`` (a SHA-256), ``spec`` (exactly a repository ``path`` and its
    ``sha256``), ``cells`` (the ids of ``arms.all_cells()``, in order, ``registered_cells``) and
    ``trial_id``."""
    what = REGISTRATION
    document = _exact_keys(_document(raw, what), _REGISTRATION_KEYS, what)
    if document["schema"] != REGISTRATION_SCHEMA:
        raise ValueError(f"{what}: schema {document['schema']!r}, not {REGISTRATION_SCHEMA}")
    code_pin = document["code_pin"]
    if not isinstance(code_pin, str) or _COMMIT.fullmatch(code_pin) is None:
        raise ValueError(f"{what} code_pin: a commit of 40 lowercase hex required")
    manifest = _sha(document["run_manifest_sha256"], f"{what} run_manifest_sha256")
    spec = _exact_keys(document["spec"], _SPEC_KEYS, f"{what} spec")
    _repo_path(spec["path"], f"{what} spec.path")
    _sha(spec["sha256"], f"{what} spec.sha256")
    cells = registered_cells()
    if document["cells"] != list(cells):
        raise ValueError(f"{what} cells: not the {len(cells)} ids of arms.all_cells(), in order")
    trial = document["trial_id"]
    if not isinstance(trial, str) or _TRIAL_ID.fullmatch(trial) is None:
        raise ValueError(f"{what} trial_id: a trial id ([A-Za-z0-9][A-Za-z0-9._-]*) required")
    pinned = MappingProxyType({"path": spec["path"], "sha256": spec["sha256"]})
    return Registration(code_pin, manifest, pinned, cells, trial)


def marker_bytes() -> bytes:
    """The rehearsal marker's fixed bytes (canonical JSON): a world committing them at its code
    pin is synthetic, built in-job, and only a rehearsal runs on it (Ruling G3)."""
    return _canonical(
        {
            "schema": REHEARSAL_SCHEMA,
            "synthetic": True,
            "purpose": "a synthetic V4.0 rehearsal world (labelled synthetic, never market "
            "data); a registered run refuses any checkout holding this file",
        }
    )


# ---- the job gate (Rulings G2, G3) -------------------------------------------------------------


def _working(path: Path) -> bytes | None:
    """The bytes at ``path`` in the working tree, None when nothing is there, and empty for
    anything that is not a regular file (a link or a folder is not the marker)."""
    if not os.path.lexists(path):
        return None
    if path.is_symlink() or not path.is_file():
        return b""
    return path.read_bytes()


def world_errors(repo: Path, mode: str, code_pin: str) -> list[str]:
    """How the checkout ``repo`` is not of ``mode``'s kind (Ruling G3); empty when it is. Copy of
    ``v31_driver.world_gate`` (scripts/v31_driver.py:1121) with V4's marker and modes, returning
    the refusal as a list instead of raising it.

    A rehearsal world commits ``REHEARSAL_MARKER`` at its code pin, byte for byte
    ``marker_bytes()``, and holds it unchanged in the working tree: only then may ``rehearsal``
    run. ``registered`` refuses a checkout holding anything at that path: in the working tree, at
    the head or at ``code_pin``. So a registered run never runs on a world built for a rehearsal.
    Any other mode is refused."""
    if mode not in GATE_MODES:
        return [f"unknown mode {mode!r}"]
    marker = REHEARSAL_MARKER
    held: dict[str, bytes | None] = {}
    try:
        held["the working tree"] = _working(repo / marker)
    except OSError as exc:
        return [f"{marker} cannot be read in the working tree ({type(exc).__name__})"]
    for where, commit in (("the head", "HEAD"), ("the code pin", code_pin)):
        try:
            held[where] = _committed(repo, commit, marker)
        except ValueError as exc:
            return [f"{marker} cannot be read at {where} {commit}: {exc}"]
    if mode == "rehearsal":
        expected = marker_bytes()
        wrong = [where for where in ("the code pin", "the working tree") if held[where] != expected]
        if wrong:
            return [
                f"rehearsal refused: {marker} is not the rehearsal marker at "
                f"{' and '.join(wrong)}; a rehearsal runs only on a synthetic world built in-job "
                "(build_rehearsal_repo), never on the repository's own registration or data"
            ]
        return []
    found = [where for where, raw in held.items() if raw is not None]
    if found:
        return [
            f"registered run refused: the checkout is a rehearsal world ({marker} in "
            f"{', '.join(found)}); a registered run never runs on a world or registration "
            "built for a rehearsal"
        ]
    return []


def _trial(
    repo: Path, head: str, *, code_pin: str, registration_sha256: str, manifest_sha256: str
) -> tuple[list[str], dict[str, Any] | None]:
    """``trial_errors``'s errors, and the authorizing trial's registration event when there are
    none (the job gate holds the registration to its trial and spec)."""
    try:
        raw = _committed(repo, head, TRIAL_REGISTER)
    except ValueError as exc:
        return [f"the head {head} cannot be read: {exc}"], None
    if raw is None:
        return [f"the head {head} commits no {TRIAL_REGISTER}"], None
    try:
        events = _parse(raw)
    except ValueError as exc:
        return [f"{TRIAL_REGISTER} at the head {head} is not a valid trial register: {exc}"], None
    pin = {"path": REGISTRATION, "sha256": registration_sha256}
    # The register's validation holds a completion's family to its registration's, and allows
    # each trial one completion.
    trials = [
        event["trial_id"]
        for event in events
        if event["event_type"] == "completion"
        and event["family"] == V4_FAMILY
        and event["payload"]["config"] == pin
    ]
    if len(trials) != 1:
        named = f" ({', '.join(trials)})" if trials else ""
        return [
            f"{TRIAL_REGISTER} at the head {head} must hold one {V4_FAMILY} completion "
            f"pinning {REGISTRATION} at {registration_sha256}, found {len(trials)}{named}"
        ], None
    (trial,) = trials
    try:
        payload = check_ready(repo, trial, head)["payload"]
    except ValueError as exc:
        return [f"the {V4_FAMILY} trial {trial} is not ready at the head {head}: {exc}"], None
    errors = []
    if payload["code_commit"] != code_pin:
        errors.append(
            f"the {V4_FAMILY} completion pins code commit {payload['code_commit']}, not the "
            f"registration's code pin {code_pin}"
        )
    for key, path, pinned_sha in (
        ("config", REGISTRATION, registration_sha256),
        ("manifest", RUN_MANIFEST, manifest_sha256),
    ):
        pinned = payload[key]
        if pinned != {"path": path, "sha256": pinned_sha}:
            errors.append(
                f"the {V4_FAMILY} completion pins its {key} {pinned['path']} at "
                f"{pinned['sha256']}, not {path} at {pinned_sha}"
            )
    registration = next(e for e in events if e["event_id"] == payload["registration_id"])
    return errors, registration


def trial_errors(
    repo: Path, head: str, *, code_pin: str, registration_sha256: str, manifest_sha256: str
) -> list[str]:
    """How the V4 trial's committed completion fails to authorize a registration (Ruling G2);
    empty when it authorizes it. Copy of ``v31_driver.trial_errors`` (scripts/v31_driver.py:1050)
    with V4's family, registration and run manifest; a head that cannot be read is an error here,
    not a raised one.

    The trial is picked by its completion's pins: among the ``completion`` events of family
    ``V4_FAMILY`` in the trial register as ``head`` commits it, exactly one must pin its config as
    ``REGISTRATION`` at ``registration_sha256`` (none, or more than one, refuses, naming the
    count). Its trial must pass ``trial_register.check_ready`` at ``head``, whose checks are its
    own: one committed completion and no correction, the registration event already in the code
    commit's first parent, the code commit and the spec commit ancestors of the head, the spec,
    config and manifest blobs at the head matching their pins, and the code at the code commit
    and at the head matching the completion's inventory and digest. The completion must then bind
    this registration: its code commit is ``code_pin``, its config ``REGISTRATION`` at
    ``registration_sha256`` and its manifest ``RUN_MANIFEST`` at ``manifest_sha256``. Any other V4
    trial, earlier, corrected or superseded, is not read."""
    return _trial(
        repo,
        head,
        code_pin=code_pin,
        registration_sha256=registration_sha256,
        manifest_sha256=manifest_sha256,
    )[0]


def _read_file(path: Path, what: str) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{what}: larger than {MAX_FILE_BYTES} bytes")
    return raw


def gate(repo: Path, mode: Literal["registered", "rehearsal"], registration_sha256: str) -> Gated:
    """The job gate (module docstring, ``gate``; Rulings G2, G3): what it accepted, or one
    ``GateError`` naming every check that failed. Copy of ``v31_driver.job_gate``
    (scripts/v31_driver.py:1201) with V4's files, allowed set, trial and world checks: it reads
    the registration itself (V3.1's caller loaded it), runs ``world_errors`` too (V3.1's callers
    ran ``world_gate`` beside it) and holds the registration to its trial's id and spec."""
    if mode not in GATE_MODES:
        raise GateError([f"unknown mode {mode!r}: one of {', '.join(GATE_MODES)} required"])
    try:
        sha = _sha(registration_sha256, "--registration-sha256")
        head = head_commit(repo)
    except ValueError as exc:
        raise GateError([str(exc)]) from None
    errors: list[str] = []
    try:
        raw = _read_file(Path(repo) / REGISTRATION, REGISTRATION)
    except (OSError, ValueError) as exc:
        raise GateError([f"{REGISTRATION} cannot be read ({type(exc).__name__}: {exc})"]) from None
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sha:
        errors.append(f"{REGISTRATION} has SHA-256 {actual}, not the dispatch's {sha}")
    try:
        registration = read_registration(raw)
    except ValueError as exc:
        raise GateError([*errors, str(exc)]) from None
    code_pin = registration.code_pin
    manifest: RunManifest | None = None
    try:
        manifest_raw = _read_file(Path(repo) / RUN_MANIFEST, RUN_MANIFEST)
    except (OSError, ValueError) as exc:
        errors.append(f"{RUN_MANIFEST} cannot be read ({type(exc).__name__}: {exc})")
    else:
        manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
        if manifest_sha != registration.run_manifest_sha256:
            errors.append(
                f"{RUN_MANIFEST} has SHA-256 {manifest_sha}; the registration pins "
                f"{registration.run_manifest_sha256}"
            )
        try:
            manifest = read_manifest(manifest_raw)
        except ValueError as exc:
            errors.append(str(exc))
    errors.extend(world_errors(Path(repo), mode, code_pin))
    try:
        changed = changed_since(repo, code_pin)
    except ValueError as exc:
        errors.append(f"the changes since the code pin {code_pin} cannot be listed: {exc}")
    else:
        refused = [path for path in changed if not _allowed(path, ALLOWED)]
        if refused:
            errors.append(
                f"the checkout changes code or data after the code pin {code_pin}, outside the "
                f"registration files ({', '.join(sorted(ALLOWED))}, docs/reviews/, docs/tasks/): "
                + ", ".join(refused)
            )
    problems, event = _trial(
        Path(repo),
        head,
        code_pin=code_pin,
        registration_sha256=sha,
        manifest_sha256=registration.run_manifest_sha256,
    )
    errors.extend(problems)
    if event is not None and not problems:
        trial = event["trial_id"]
        if registration.trial_id != trial:
            errors.append(
                f"the registration names trial {registration.trial_id}, but the {V4_FAMILY} "
                f"completion that authorizes it is trial {trial}"
            )
        spec = event["payload"]["spec"]
        if dict(registration.spec) != {"path": spec["path"], "sha256": spec["sha256"]}:
            errors.append(
                f"the registration pins the spec {registration.spec['path']} at "
                f"{registration.spec['sha256']}, but trial {trial} registered {spec['path']} at "
                f"{spec['sha256']}"
            )
    if errors or manifest is None:
        raise GateError(errors or [f"{RUN_MANIFEST}: not read"])
    return Gated(head, registration, manifest, sha)


def github_outputs(gated: Gated) -> list[tuple[str, str]]:
    """What the gate hands the workflow's later steps (``--github-output``): the code pin, V3's
    pack pin and the run manifest's data pins, in that order."""
    return [
        ("code_pin", gated.registration.code_pin),
        ("v3_pack_sha256", gated.manifest.v3_pack_sha256),
        *((key, gated.manifest.data[key]) for key in _DATA_ORDER),
    ]


# ---- one dispatch per registration (Ruling G4) -------------------------------------------------


def registered_title(registration_sha256: str) -> str:
    """The title GitHub gives a registered dispatch of the registration: the workflow's
    ``run-name``, ``v4-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}``. Copy of
    ``v31_driver.registered_title`` (scripts/v31_driver.py:1394) with V4's run-name."""
    return f"{RUN_NAME} registered {registration_sha256}"


def run_titles(mode: str, registration_sha256: str) -> tuple[str, ...]:
    """The titles a run of ``mode`` dispatched with the ``registration_sha256`` input may have:
    the workflow's ``run-name``. Copy of ``v31_driver.run_titles`` (scripts/v31_driver.py:1400)
    with V4's run-name and its three modes (another mode is refused). A registered run's input is
    a SHA-256, so its title is ``registered_title``. A rehearsal's or a timing run's input is a
    SHA-256 or empty, and with an empty one the run-name ends in a space that GitHub may keep or
    trim, so both spellings are its titles."""
    if mode not in TITLE_MODES:
        raise ValueError(f"unknown mode {mode!r}: one of {', '.join(TITLE_MODES)} required")
    if mode == "registered":
        return (registered_title(registration_sha256),)
    if registration_sha256:
        return (f"{RUN_NAME} {mode} {registration_sha256}",)
    return (f"{RUN_NAME} {mode} ", f"{RUN_NAME} {mode}")


def other_dispatches(
    runs: Sequence[object],
    current: object,
    registration_sha256: str,
    *,
    mode: str = "registered",
) -> tuple[int, ...]:
    """The ids, ascending, of this workflow's other runs that dispatched the registration no
    later than the current run (Ruling G4): a pure decision on what the API listed. Copy of
    ``v31_driver.other_dispatches`` (scripts/v31_driver.py:1434) with V4's titles. ``current`` is
    the current run's record (its id, title and creation time are read), as in V3.1.

    A run is listed when its id is not the current run's, its display title is one of
    ``run_titles(mode, registration_sha256)`` and it was created before the current run or in
    the same second (a tie counts). Its status and conclusion do not matter here: queued, in
    progress, failed, cancelled or successful, it launched the registration; each is an earlier
    launch that ``launch_decision`` then judges. Refuses (one ``ValueError``) any run, the
    current one included, without a positive integer id, a string display title and a
    ``created_at`` of GitHub's form; a run id listed twice; and a current run titled otherwise,
    as a later dispatch could then not find it. A current run missing from the list is
    ``CurrentRunMissing``, which the caller retries (GitHub's listing can lag a run just
    created)."""
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
            f"the current run {current_id} is not among this workflow's runs (GitHub's listing "
            "can lag a run just created)"
        )
    return tuple(sorted(found))


def workflow_runs(repository: str, token: str, opener: GitHubOpener) -> list[object]:
    """Every run of V4's run workflow (``WORKFLOW_FILE``), all pages, refusing a malformed page
    and any pagination inconsistency (``v31_driver._listing``). Copy of
    ``v31_driver.workflow_runs`` (scripts/v31_driver.py:1828) with V4's workflow file."""
    path = f"/repos/{repository}/actions/workflows/{WORKFLOW_FILE}/runs"
    return _listing(path, "workflow_runs", "run", "this workflow", RUNS_PER_PAGE, token, opener)


def _job_kind(name: str) -> str | None:
    """Which of V4's workflow's jobs a job record named ``name`` is (``PLAN_JOB``,
    ``STATUS_JOB``, one of ``SKIPPED_JOBS`` or ``SKIPPED_MATRIX_JOBS``), or None for a name this
    workflow does not give a job. Copy of ``v31_driver._job_kind`` (scripts/v31_driver.py:1484)
    with V4's jobs."""
    if name in (PLAN_JOB, STATUS_JOB, *SKIPPED_JOBS):
        return name
    for job in SKIPPED_MATRIX_JOBS:
        if name == job or (name.startswith(f"{job} (") and name.endswith(")")):
            return job
    return None


def launch_decision(run: object, jobs: object) -> tuple[str | None, bool]:
    """Why an earlier launch of the same title counts as an execution of the registration (owner
    decision v31-d21, layer L2), or None when GitHub's records show it provably did nothing; and
    whether it counts because those records are malformed. Copy of
    ``v31_driver.launch_decision`` (scripts/v31_driver.py:1547) with V4's jobs (``_job_kind``).

    A pure decision on ``run`` (the run as the workflow-runs listing gives it) and ``jobs`` (every
    job record of every attempt, as ``run_jobs`` lists them). The launch does not count only when
    all of these hold:

    - the run's ``status`` is ``completed`` and its ``run_attempt`` a positive integer;
    - every job record is an object with a positive integer ``id`` (no id twice), the run's
      ``run_id``, a ``run_attempt`` from 1 to the run's, a string ``name`` and ``status`` and a
      string or null ``conclusion``;
    - every attempt from 1 to the run's ``run_attempt`` lists a job named ``plan``, and every
      ``plan`` job listed ended ``failure``;
    - every other job, except the always-running ``status`` job, ended ``skipped``: ``v3-pack``,
      ``v3-picks``, the ``cell`` and ``v3-cell`` matrix jobs (``<job>`` or ``<job> (<matrix
      values>)``), ``scenarios``, ``verdict`` and ``analysis``.

    Anything else counts: a run queued or still running, an attempt whose plan succeeded, was
    cancelled or is not listed, any later job that ran or failed, a job of an unknown name (V3.1's
    job names among them), a malformed run or job record, or no listing at all. The second value,
    ``malformed``, is True when the launch counts because the records lack the shape the rule
    reads; a report-only check fails on it (layer L3), a registered check counts the launch."""
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
    """``launch_decision``'s reason alone: why the launch counts, or None when it does not. Copy
    of ``v31_driver.launch_reason`` (scripts/v31_driver.py:1622), on V4's ``launch_decision``."""
    return launch_decision(run, jobs)[0]


def _unread_attempts(run_id: object, why: str) -> str:
    return (
        f"the attempts of this run ({run_id}) could not be read, so a re-run of its jobs could "
        f"not be ruled out: {why}"
    )


def replay_reasons(current: object, jobs: object) -> tuple[str, ...]:
    """Why the current registered run's own attempts break its one execution (spec, "Registration
    and the run", item 5: one dispatch, never cancelled, never re-run, but for a single
    aggregate-only re-run after an infrastructure failure), one plain sentence each, naming a
    job's id, name and attempt, never its result; empty when nothing breaks it. New in V4: V3.1's
    aggregate found a re-run by its artifacts alone.

    A pure decision on ``current`` (the run as ``/actions/runs/{id}`` gives it) and ``jobs`` (every
    job record of every attempt, ``filter=all``, as ``run_jobs`` lists them). Each of these is a
    reason:

    - a ``run_attempt`` past ``MAX_RUN_ATTEMPT``: more than the one aggregate-only re-run;
    - each job record of an attempt after the first whose job (``_job_kind``) is not one of
      ``RERUN_JOBS`` (``verdict``, ``analysis``, ``status``): ``plan``, ``v3-pack``, ``v3-picks``,
      ``scenarios``, a ``cell`` or ``v3-cell`` matrix job, or a name this workflow does not give a
      job, whatever its status or conclusion. A cell job run again is a replay even when it failed
      before its upload, leaving no folder for the verdict's own re-run check (V3) to find.

    Records that lack the shape the rule reads (``job_listing_error``: a positive ``run_attempt``,
    at least one record, each of this run and of an attempt from 1 to its own, no id twice) are
    one reason: the attempts could not be read, so no replay could be ruled out."""
    run_id = current.get("id") if isinstance(current, dict) else None
    problem = job_listing_error(current, jobs)
    # job_listing_error refuses a run that is not an object and jobs that are not a list.
    if problem is not None or not isinstance(current, dict) or not isinstance(jobs, list | tuple):
        return (
            _unread_attempts(
                run_id, f"its job listing does not have the shape the check reads: {problem}"
            ),
        )
    # job_listing_error has checked the run's run_attempt and every record's fields.
    attempts: int = current["run_attempt"]
    reasons = []
    if attempts > MAX_RUN_ATTEMPT:
        reasons.append(
            f"this run ({run_id}) is at attempt {attempts}: a registered run is re-run at most "
            f"once, aggregate-only, so it has no attempt after {MAX_RUN_ATTEMPT}"
        )
    for record in jobs:
        attempt, name = record["run_attempt"], record["name"]
        if attempt > 1 and _job_kind(name) not in RERUN_JOBS:
            reasons.append(
                f"this run ({run_id}) ran job {record['id']} {name!r} again in attempt {attempt}: "
                f"only the {', '.join(RERUN_JOBS)} jobs may run in the single aggregate-only re-run"
            )
    return tuple(reasons)


def _own_attempts(
    current: Mapping[str, Any],
    repository: str,
    token: str,
    opener: GitHubOpener,
    *,
    sleep: Callable[[float], None],
    log: Log,
    deadline: _Deadline,
) -> tuple[str, ...]:
    """``replay_reasons`` on the current run (the verdict job's check): a first attempt needs no
    request, since nothing ran again; a later one is judged on its jobs (``run_jobs``, retried as
    L1 says, within the check's deadline). Any failure to read them is a reason (fail closed: the
    verdict is incomplete). The deadline passing is no decision: it stops the whole check."""
    # ``current`` is the current run as dispatch_check validated it: an object with a positive
    # integer id, which is GITHUB_RUN_ID.
    run_id: int = current["id"]
    attempts = current.get("run_attempt")
    if type(attempts) is int and attempts == 1:
        return ()
    try:
        jobs = github_retry(
            lambda: run_jobs(repository, token, opener, run_id),
            f"this run's own jobs ({run_id})",
            sleep=sleep,
            log=log,
            deadline=deadline,
        )
    except DeadlineExpired:
        raise
    except ValueError as exc:
        return (_unread_attempts(run_id, str(exc)),)
    return replay_reasons(current, jobs)


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
    """The decision on one earlier launch (L2): one queued or running counts without its jobs; a
    completed one is judged on its jobs (``run_jobs``, retried as L1 says), and counts,
    ``unreadable``, when they cannot be read (``gone`` too when GitHub answered 404), or,
    ``unreadable`` too, when a record lacks the shape the rule reads. The deadline passing is no
    decision on the launch: it stops the whole check. Copy of ``v31_driver._judge``
    (scripts/v31_driver.py:1888), on V4's ``launch_decision``."""
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


def _mode_problem(mode: object, report_only: bool) -> str | None:
    """Why ``mode`` and ``report_only`` do not go together, or None: a registered check always
    decides, and the check of a rehearsal or a timing run only reports (V3.1's check was
    report-only exactly when it was a rehearsal's)."""
    if mode not in TITLE_MODES:
        return f"unknown mode {mode!r}: one of {', '.join(TITLE_MODES)} required"
    if mode == "registered" and report_only:
        return "a registered check always decides: it is never --report-only"
    if mode != "registered" and not report_only:
        return f"a {mode} check is --report-only: only a registered check refuses a dispatch"
    return None


def dispatch_check(
    registration_sha256: object,
    opener: GitHubOpener | None = None,
    *,
    mode: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
    job_budget: int = PLAN_JOB_BUDGET,
    log: Log = log,
    report_only: bool = False,
    judge_all: bool = False,
    replays: list[str] | None = None,
) -> tuple[EarlierLaunch, ...]:
    """The earlier launches of this run's title, ascending, and whether each counts (Ruling G4;
    owner decision v31-d21), from GitHub's REST API. Copy of ``v31_driver.dispatch_check``
    (scripts/v31_driver.py:1929) with V4's workflow, titles, jobs and job-start variable, an
    explicit ``mode`` (V3.1's was "rehearsal" exactly when report-only; here ``mode`` names the
    titles and must agree with ``report_only``, ``_mode_problem``) and ``replays``.

    The current run and this workflow's runs (``workflow_runs``) name the launches
    (``other_dispatches``), and each completed one's jobs (``run_jobs``) decide it
    (``launch_decision``); one queued or running counts without them. Read with the job's
    ``GITHUB_TOKEN`` for the runner's own ``GITHUB_REPOSITORY`` and ``GITHUB_RUN_ID``. ``opener``
    replaces urllib's (tests); by default urllib's, following no redirect.

    A registered check judges the launches up to the first that counts, which already decides a
    refusal, unless ``judge_all`` (the verdict job's, which names every earlier launch); a
    report-only one looks for its mode's ``run_titles``, whose input is a SHA-256 or empty, judges
    every launch, and also reads the current run's own job listing, refusing unless every record
    has the shape the rule reads (``job_listing_error``).

    ``replays``, given by the verdict job's check alone (``dispatch_reasons``, with ``judge_all``),
    collects what the current run's own attempts break (``_own_attempts``), read right after the
    current run and before this workflow's runs: ``replay_reasons``'s lines, or why the attempts
    could not be read. A first attempt makes no request for them.

    Each read is retried on a transient failure (``github_retry``, L1). The whole check has one
    deadline on ``clock``: 20 minutes from its start, or earlier, ``job_budget`` from its job's
    start when ``V4_JOB_STARTED`` gives it (the time the job has run is taken once, from
    ``wall``). A missing or malformed variable, a permanent failure, a transient one that
    outlasts the retries and the deadline passing are one ``ValueError``: the caller fails
    closed. A launch whose jobs cannot be read, or whose records are malformed, counts."""
    problem = _mode_problem(mode, report_only)
    if problem is None and replays is not None and not judge_all:
        problem = "the current run's attempts are read by the verdict job's check (judge_all) alone"
    if problem is not None:
        raise ValueError(f"the dispatch check cannot run: {problem}")
    if report_only and registration_sha256 == "":
        sha = ""
    else:
        what = "--registration-sha256"
        if report_only:
            what += " (a report-only check's may be empty)"
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
            f"{JOB_STARTED} {started!r}: the job's start, a positive integer epoch second not "
            "in the future, required (the job's first step records it)"
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
    if replays is not None:
        replays.extend(
            _own_attempts(current, repository, token, read, sleep=sleep, log=log, deadline=deadline)
        )
    if report_only:
        # The probe (L3): even a first rehearsal, with no earlier launch to judge, reads a job
        # listing, its own, and checks every record's shape.
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
                f"the jobs endpoint, checked on this run ({current_id}), does not have the shape "
                f"the check reads: {problem}"
            )
        log(
            f"dispatch check (report-only): jobs endpoint checked on this run: {len(own)} job "
            "records, shape valid"
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
    """What the verdict job hands the verdict step (``--judge-all``, Ruling G4): first what this
    run's own attempts break (``replay_reasons``: a job other than the verdict, the analysis and
    the status job run again, even one that left no artifact, or a third attempt; or why they
    could not be read), then every earlier launch of the registration that counts, with why, or
    why none could be ruled out (a failure of the check, its deadline passing among them), any of
    which leaves the verdict incomplete (fail closed); then every earlier launch that stopped at
    the plan job with nothing run (L2), which changes nothing. It judges every launch
    (``judge_all``). Copy of ``v31_driver.dispatch_reasons`` (scripts/v31_driver.py:2070) with the
    verdict job's budget (``VERDICT_JOB_BUDGET``) in place of the aggregate's, and the current
    run's attempts (``dispatch_check``'s ``replays``), which V3.1's did not read."""
    replays: list[str] = []
    try:
        launches = dispatch_check(
            registration_sha256,
            opener,
            mode="registered",
            sleep=sleep,
            clock=clock,
            wall=wall,
            job_budget=VERDICT_JOB_BUDGET,
            log=log,
            judge_all=True,
            replays=replays,
        )
    except ValueError as exc:
        # What the attempts broke before the check failed is kept beside its failure.
        failed = f"another dispatch of this registration could not be ruled out: {exc}"
        return (*replays, failed), ()
    counted = tuple(
        f"another dispatch of this registration: run {launch.run_id} ({launch.reason})"
        for launch in launches
        if launch.counts
    )
    uncounted = tuple(uncounted_line(launch.run_id) for launch in launches if not launch.counts)
    return (*replays, *counted), uncounted


def dispatch_check_command(
    args: argparse.Namespace,
    opener: GitHubOpener | None = None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> tuple[list[str], list[str]]:
    """``dispatch-check`` without ``--judge-all`` (the module docstring): the earlier launches
    that count and those that do not, one line each. Copy of
    ``v31_driver.dispatch_check_command`` (scripts/v31_driver.py:2434) with V4's ``mode`` and
    plan job budget; it returns the two lists instead of V3.1's stdout document (``main`` prints
    their counts and writes ``--out``).

    A registered check refuses the first earlier launch of the registration that counts, naming
    it and why, and fails closed (``dispatch_check``), its deadline passing included. A
    report-only check logs what a registered one would decide about every earlier launch and
    refuses only when GitHub cannot be read: the current run, the runs listing, the jobs of an
    earlier launch, a record of a shape it does not know, or the deadline passing. A launch whose
    jobs GitHub answers 404 for (deleted since the listing) is listed as gone, and is no failure
    to read. Run in the plan job, so its deadline is ``PLAN_JOB_BUDGET``."""
    launches = dispatch_check(
        args.registration_sha256,
        opener,
        mode=args.mode,
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
            + "; a registration is dispatched once (Ruling G4), so this run stops here ("
            + "; ".join(counted)
            + ")"
            + "".join(f"; {line}" for line in uncounted)
        )
    return counted, uncounted


# ---- the rehearsal world's repository ----------------------------------------------------------


def _git(repo: Path, *args: str) -> bytes:
    # Reviewed: a fixed argument list and no shell (``shell=False``). The callers pass literal
    # git subcommands and paths inside the folder they build; git is resolved from PATH, as on
    # the CI runner.
    process = subprocess.run(  # nosec B603 B607
        ["git", *_GIT_OPTIONS, "-C", str(repo), *args], capture_output=True, check=False
    )
    if process.returncode:
        message = process.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"git {args[0]} failed in {repo}: {message}")
    return process.stdout


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return head_commit(repo)


def _place(repo: Path, path: str, content: bytes) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(content)


def _tracked_code(checkout: Path) -> dict[str, bytes]:
    """The checkout's tracked ``src/**``, ``scripts/**``, ``pyproject.toml`` and
    ``requirements-dev.lock`` (its index, ``git ls-files``; an untracked file is not read), each
    as the working tree holds it."""
    listed = _git(checkout, "ls-files", "-z", "--", *_COPIED)
    paths = sorted(name.decode("utf-8") for name in listed.split(b"\0") if name)
    code = {path: (checkout / path).read_bytes() for path in paths}
    if not any(path.startswith(_CODE_PREFIXES) for path in code):
        raise ValueError(f"the checkout {checkout} tracks no src/ or scripts/ file")
    return code


def _trial_event(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """One event of the rehearsal world's synthetic V4 trial, in the trial register's schema."""
    return {
        "schema_version": 1,
        "event_id": f"{REHEARSAL_TRIAL}-{event_type}",
        "trial_id": REHEARSAL_TRIAL,
        "event_type": event_type,
        "recorded_at": _RECORDED_AT,
        "agent": "V4 rehearsal (synthetic)",
        "family": V4_FAMILY,
        "parent_trial_id": None,
        "sources": [SPEC],
        "payload": dict(payload),
    }


def _manifest_bytes(manifest: RunManifest) -> bytes:
    """The run manifest file of ``manifest``, refused unless it reads back as itself."""
    raw = _canonical(
        {
            "schema": MANIFEST_SCHEMA,
            "data": dict(manifest.data),
            "v3_pack_sha256": manifest.v3_pack_sha256,
        }
    )
    if read_manifest(raw) != manifest:
        raise ValueError("the run manifest does not read back as itself")
    return raw


def build_rehearsal_repo(root: Path, checkout: Path, manifest: RunManifest) -> tuple[Path, str]:
    """The rehearsal world's git repository, ``root/repo`` (which must not exist), laid out as a
    registered run's repository, and its registration's SHA-256 (Rulings G2, G3). Its commits,
    as ``v31_smoke.build_world`` (with ``register_trial``) and ``v31_driver.rehearsal_world``
    (with ``complete_trial``) lay out V3.1's:

    1. the spec, ``SPEC``, copied from ``checkout``;
    2. ``TRIAL_REGISTER``: the checkout's events and one synthetic ``registration`` event, trial
       ``v4-0-synthetic`` of family ``spec-v4.0``, its ``spec`` pinned to commit 1's spec (a
       registration names the commit holding its spec, so the spec comes a commit before it);
    3. the code pin: the checkout's tracked ``src/**``, ``scripts/**``, ``pyproject.toml`` and
       ``requirements-dev.lock`` (``_tracked_code``) and ``REHEARSAL_MARKER`` with
       ``marker_bytes()``; its first parent holds the registration event, as
       ``trial_register.check_ready`` requires;
    4. ``RUN_MANIFEST`` (``manifest``), ``REGISTRATION`` (the code pin, the manifest's SHA-256, the
       spec, the 48 cells, trial ``v4-0-synthetic``) and the trial's ``completion``, binding the
       code pin (its code inventory and digest as ``check_ready`` computes them), the
       registration and the run manifest.

    So the head differs from the code pin by the registration files alone, and ``gate`` in mode
    ``rehearsal`` accepts it. git runs with ``_GIT_OPTIONS`` (its identity and settings passed
    with ``-c``): no config is written, and nothing of ``checkout`` but its files and its index is
    read."""
    manifest_raw = _manifest_bytes(manifest)
    checkout = Path(checkout)
    spec = (checkout / SPEC).read_bytes()
    events = (checkout / TRIAL_REGISTER).read_bytes()
    code = _tracked_code(checkout)
    repo = Path(root) / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _place(repo, SPEC, spec)
    spec_commit = _commit(repo, "the V4 spec (synthetic rehearsal world)")
    cells = registered_cells()
    capitals = sorted({cell.capital for cell in all_cells()})
    registration_payload = {
        "preregistered": True,
        "hypothesis": "synthetic: V4's job gate, trial check and job graph run end to end on a "
        "rehearsal world (labelled synthetic, never market data)",
        "spec": {"path": SPEC, "commit": spec_commit, "sha256": hashlib.sha256(spec).hexdigest()},
        "candidates": ["synthetic: the registration's arms"],
        "sizes": capitals,
        "fees": "synthetic: the registered cost profiles",
        "folds": "synthetic: the rehearsal world's window",
        "mask": "synthetic: none",
        "seeds": [],
        "budget": f"synthetic: the registration's {len(cells)} cells, each once",
        "stopping": "synthetic: every cell, once",
        "selection": "synthetic: none",
        "data": None,
        "code": None,
    }
    _place(repo, TRIAL_REGISTER, events)
    append_event(repo / TRIAL_REGISTER, _trial_event("registration", registration_payload))
    _commit(repo, "the synthetic V4 trial's registration")
    for path, content in code.items():
        _place(repo, path, content)
    _place(repo, REHEARSAL_MARKER, marker_bytes())
    code_pin = _commit(repo, "the code pin (synthetic rehearsal world)")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    registration_raw = _canonical(
        {
            "schema": REGISTRATION_SCHEMA,
            "code_pin": code_pin,
            "run_manifest_sha256": manifest_sha,
            "spec": {"path": SPEC, "sha256": hashlib.sha256(spec).hexdigest()},
            "cells": list(cells),
            "trial_id": REHEARSAL_TRIAL,
        }
    )
    registration_sha = hashlib.sha256(registration_raw).hexdigest()
    _place(repo, RUN_MANIFEST, manifest_raw)
    _place(repo, REGISTRATION, registration_raw)
    inventory = {
        path: content
        for path, content in code.items()
        if path.startswith(_CODE_PREFIXES) or path in _CODE_FILES
    }
    completion_payload = {
        "registration_id": f"{REHEARSAL_TRIAL}-registration",
        "code_commit": code_pin,
        "code_sha256": code_digest(inventory),
        "code_paths": sorted(inventory),
        "manifest": {"path": RUN_MANIFEST, "sha256": manifest_sha},
        "config": {"path": REGISTRATION, "sha256": registration_sha},
        "review": "synthetic: a rehearsal world, never reviewed",
    }
    append_event(repo / TRIAL_REGISTER, _trial_event("completion", completion_payload))
    _commit(repo, "the rehearsal registration (synthetic)")
    return repo, registration_sha


# ---- the command line --------------------------------------------------------------------------


def _say(line: str) -> None:
    """A line of standard output: counts, ids and pins only."""
    print(line, flush=True)


def _refuse(name: str, message: str) -> int:
    """One line of standard error (the message's lines joined), the exit status 1."""
    flat = " ".join(part.strip() for part in message.splitlines() if part.strip())
    print(f"::error::{name}: refused: {flat}", file=sys.stderr, flush=True)
    return 1


def gate_command(args: argparse.Namespace) -> int:
    """``gate`` (the module docstring)."""
    name = "v4_registration gate"
    try:
        gated = gate(Path(args.repo), args.mode, args.registration_sha256)
    except GateError as exc:
        for error in exc.errors:
            _refuse(name, error)
        return 1
    except (OSError, ValueError) as exc:
        return _refuse(name, f"{type(exc).__name__}: {exc}")
    if args.github_output is not None:
        lines = "".join(f"{key}={value}\n" for key, value in github_outputs(gated))
        try:
            with Path(args.github_output).open("ab") as handle:
                handle.write(lines.encode("ascii"))
        except OSError as exc:
            return _refuse(name, f"--github-output cannot be written ({type(exc).__name__})")
    registration = gated.registration
    _say(
        f"{name}: {args.mode}, head {gated.head}, code pin {registration.code_pin}, registration "
        f"{gated.registration_sha256}, run manifest {registration.run_manifest_sha256}, trial "
        f"{registration.trial_id}, {len(registration.cells)} cells: accepted"
    )
    return 0


def _option_problem(args: argparse.Namespace) -> str | None:
    """Why ``dispatch-check``'s options do not go together, or None."""
    problem = _mode_problem(args.mode, args.report_only)
    if problem is not None:
        return problem
    if args.judge_all and args.mode != "registered":
        return "--judge-all is the verdict job's check of a registered run: --mode registered"
    if args.judge_all and args.out is None:
        return "--judge-all needs --out: its reasons are the verdict step's input"
    return None


def dispatch_command(
    args: argparse.Namespace,
    opener: GitHubOpener | None,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    wall: Callable[[], float],
) -> int:
    """``dispatch-check`` (the module docstring)."""
    name = "v4_registration dispatch-check"
    problem = _option_problem(args)
    if problem is not None:
        return _refuse(name, problem)
    out = None if args.out is None else Path(args.out)
    if out is not None and (out.exists() or out.is_symlink()):
        return _refuse(name, f"--out {out.as_posix()} exists: the reasons file is never replaced")
    try:
        if args.judge_all:
            counted, uncounted = dispatch_reasons(
                args.registration_sha256, opener, sleep=sleep, clock=clock, wall=wall
            )
            decisions = (*counted, *uncounted)
        else:
            listed = dispatch_check_command(args, opener, sleep=sleep, clock=clock, wall=wall)
            counted, uncounted = tuple(listed[0]), tuple(listed[1])
            # A report-only check has logged its decision on every launch already.
            decisions = () if args.report_only else uncounted
        for line in decisions:
            log(f"dispatch check: {line}")
        if out is not None:
            document = {"format": DISPATCH_CHECK_SCHEMA, "earlier": list(counted)}
            with out.open("xb") as handle:
                handle.write(_canonical(document))
    except (OSError, ValueError) as exc:
        return _refuse(name, str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    kind = "every launch judged" if args.judge_all else "report-only" if args.report_only else ""
    shown = args.registration_sha256 or "(empty)"
    _say(
        f"{name}: {args.mode}{f' ({kind})' if kind else ''}, registration {shown}: "
        f"{len(counted)} counted, {len(uncounted)} not counted"
        + ("" if out is None else f"; written to {out.as_posix()}")
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_registration.py",
        description="V4's job gate and dispatch check (see the module docstring).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    gated = commands.add_parser("gate", help="the job gate on a checkout")
    gated.add_argument("--repo", default=".", help="the checkout (default: .)")
    gated.add_argument("--mode", choices=GATE_MODES, required=True)
    gated.add_argument(
        "--registration-sha256", required=True, help="the dispatch's pin of the registration file"
    )
    gated.add_argument("--github-output", help="append the pins to this file ($GITHUB_OUTPUT)")
    check = commands.add_parser("dispatch-check", help="one dispatch per registration")
    check.add_argument("--mode", choices=TITLE_MODES, required=True)
    check.add_argument(
        "--registration-sha256",
        required=True,
        help="the dispatch's registration_sha256 input (a report-only check's may be empty)",
    )
    check.add_argument(
        "--report-only",
        action="store_true",
        help="a rehearsal's or timing run's check: log what a registered check would decide and "
        "refuse only when GitHub cannot be read",
    )
    check.add_argument(
        "--judge-all",
        action="store_true",
        help="the verdict job's check: judge every launch, refuse none, write each that counts",
    )
    check.add_argument("--out", help="the reasons file for the verdict step (must not exist)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    github_opener: GitHubOpener | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> int:
    """Run one subcommand: its exit status (module docstring). The keyword arguments replace the
    dispatch check's opener, its retry sleep and the clocks of its deadline (tests)."""
    args = build_parser().parse_args(argv)
    if args.command == "gate":
        return gate_command(args)
    return dispatch_command(args, github_opener, sleep=sleep, clock=clock, wall=wall)


if __name__ == "__main__":
    raise SystemExit(main())
