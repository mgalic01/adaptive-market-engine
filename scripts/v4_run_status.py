"""The v4-run workflow's status record: what each job of the run did, in one small file.

The ``status`` job of ``.github/workflows/v4-run.yml`` (plan
``docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md``, Task 8) needs every other job and runs
whatever they did (``if: always()``), so a run that stopped half way still leaves a record of how
far it got. It passes this script three values through the environment, never as text in a
script: ``RUN_ID`` (``github.run_id``), ``RUN_ATTEMPT`` (``github.run_attempt``) and ``NEEDS``
(``toJSON(needs)``).

``--mode M --registration-sha256 S --out F``:

1. ``M`` is one of ``inputs.MODES`` (``rehearsal``, ``timing``, ``registered``); ``S`` is 64
   lowercase hex digits, or empty (a timing or a rehearsal run may have none, and a plan job that
   stopped early has no output to give: the workflow passes the dispatch's own input), recorded as
   null; ``RUN_ID`` is 1 to 20 digits and ``RUN_ATTEMPT`` 1 to 6, neither with a leading zero;
2. ``NEEDS`` is a JSON object with unique keys that lists exactly the workflow's other jobs
   (``v4_registration``: ``plan``, ``v3-pack``, ``v3-picks``, ``scenarios``, ``verdict``,
   ``analysis``, ``cell`` and ``v3-cell``), each an object whose ``result`` is one of GitHub's
   four: ``success``, ``failure``, ``cancelled`` or ``skipped``. Only the results are read: a job's
   outputs (the cells' matrix, a pin) are not kept;
3. it creates ``F`` exclusively (a file that exists is refused) with the canonical JSON
   (``combined.artifacts._canonical``: sorted keys, no spaces, ASCII, no newline) of ``{"format":
   "v4-run-status-1", "mode": M, "run_id": int, "run_attempt": int, "registration_sha256": S or
   null, "jobs": {name: result}, "verdict_ran": bool}``. ``verdict_ran`` says whether the
   ``verdict`` job ran to an end, success or failure (a skipped or cancelled one did not). It says
   nothing of the verdict itself, which the job's exit status never carries.

**Exit status**: 0 once the file is written; 1 on any refusal, with nothing written; 2 for bad
arguments (argparse's own).

**Output.** Standard output carries one line of counts: the mode, the run and attempt numbers, how
many jobs ended each way and whether the verdict job ran. Never a price, an equity, a cell's
outcome or the verdict (owner rule: public logs). A refusal is one line on standard error,
``::error::v4_run_status: <what was wrong>: refused``, which names a variable or a job and never
quotes a value of ``NEEDS``.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from v4_registration import PLAN_JOB, SKIPPED_JOBS, SKIPPED_MATRIX_JOBS
from v31_driver import strict_json

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.verdict.inputs import MODES

STATUS_FORMAT = "v4-run-status-1"
# The workflow's jobs besides ``status``: the ``needs`` of the status job lists each of them.
JOBS = (PLAN_JOB, *SKIPPED_JOBS, *SKIPPED_MATRIX_JOBS)
RESULTS = ("success", "failure", "cancelled", "skipped")  # a job's ``needs.<job>.result``
RAN = ("success", "failure")  # the results of a job that ran to an end
# ``toJSON(needs)`` of eight jobs, outputs included (the plan's matrix is a few kilobytes): GitHub
# caps one output at 1 MB, and an environment variable is far smaller.
MAX_NEEDS_BYTES = 1 << 20

_HEX64 = re.compile("[0-9a-f]{64}")
_RUN_ID = re.compile("[1-9][0-9]{0,19}")
_RUN_ATTEMPT = re.compile("[1-9][0-9]{0,5}")


class StatusError(ValueError):
    """A refusal of this script: the message names a variable or a job, never a value."""


def _refuse(message: str) -> int:
    """One line of standard error, ``::error::v4_run_status: <message>: refused``; the exit
    status 1."""
    print(f"::error::v4_run_status: {message}: refused", file=sys.stderr, flush=True)
    return 1


def _variable(environment: Mapping[str, str], name: str, pattern: re.Pattern[str]) -> int:
    """The positive integer of the variable ``name``: set, and plain ASCII digits."""
    text = environment.get(name)
    if text is None:
        raise StatusError(f"{name} is not set")
    if pattern.fullmatch(text) is None:
        raise StatusError(f"{name} is not plain digits without a leading zero, in range")
    return int(text)


def _results(text: str) -> dict[str, str]:
    """The ``result`` of every job of ``JOBS`` in ``NEEDS``' text (module docstring, step 2)."""
    try:
        raw = text.encode("utf-8")
    except UnicodeError:
        raise StatusError("NEEDS is not UTF-8 text") from None
    if len(raw) > MAX_NEEDS_BYTES:
        raise StatusError(f"NEEDS is larger than {MAX_NEEDS_BYTES} bytes")
    try:
        document = strict_json(raw, "NEEDS")
    except (ValueError, RecursionError):  # its messages quote a key
        raise StatusError("NEEDS is not JSON with unique keys") from None
    if not isinstance(document, dict):
        raise StatusError("NEEDS is not a JSON object of jobs")
    missing = [job for job in JOBS if job not in document]
    unknown = [name for name in document if name not in JOBS]
    if missing or unknown:
        raise StatusError(
            f"NEEDS does not list exactly the workflow's other jobs: missing {len(missing)}"
            f"{' (' + ', '.join(missing) + ')' if missing else ''}, unknown {len(unknown)}"
        )
    results: dict[str, str] = {}
    for job in JOBS:
        record = document[job]
        result = record.get("result") if isinstance(record, dict) else None
        if not isinstance(result, str) or result not in RESULTS:
            raise StatusError(f"NEEDS: the result of job {job} is not one of {', '.join(RESULTS)}")
        results[job] = result
    return results


def status_document(
    mode: str, registration_sha256: str, environment: Mapping[str, str]
) -> dict[str, object]:
    """The status record (module docstring), or a ``StatusError``. ``environment`` is where
    ``RUN_ID``, ``RUN_ATTEMPT`` and ``NEEDS`` are read."""
    if not isinstance(mode, str) or mode not in MODES:
        raise StatusError(f"unknown mode: one of {', '.join(MODES)} required")
    if registration_sha256 and _HEX64.fullmatch(registration_sha256) is None:
        raise StatusError("--registration-sha256 is neither empty nor 64 lowercase hex digits")
    run_id = _variable(environment, "RUN_ID", _RUN_ID)
    run_attempt = _variable(environment, "RUN_ATTEMPT", _RUN_ATTEMPT)
    needs = environment.get("NEEDS")
    if needs is None:
        raise StatusError("NEEDS is not set")
    jobs = _results(needs)
    return {
        "format": STATUS_FORMAT,
        "mode": mode,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "registration_sha256": registration_sha256 or None,
        "jobs": jobs,
        "verdict_ran": jobs["verdict"] in RAN,
    }


def _counts_line(document: Mapping[str, object]) -> str:
    jobs = cast("Mapping[str, str]", document["jobs"])
    ended = ", ".join(f"{list(jobs.values()).count(result)} {result}" for result in RESULTS)
    ran = "ran" if document["verdict_ran"] else "did not run"
    return (
        f"v4_run_status: mode {document['mode']}, run {document['run_id']} attempt "
        f"{document['run_attempt']}, {len(jobs)} jobs ({ended}), verdict job {ran}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_run_status.py",
        description="Write the v4-run workflow's status record from RUN_ID, RUN_ATTEMPT and "
        "NEEDS (see the module docstring).",
    )
    parser.add_argument("--mode", required=True, help="rehearsal, timing or registered")
    parser.add_argument(
        "--registration-sha256",
        required=True,
        help="the dispatch's registration pin: 64 lowercase hex digits, or empty",
    )
    parser.add_argument("--out", type=Path, required=True, help="the new status.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write the status record: the exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    target = Path(args.out)
    if target.exists() or target.is_symlink():
        return _refuse("the output file already exists")
    try:
        document = status_document(args.mode, args.registration_sha256, os.environ)
    except StatusError as exc:
        return _refuse(str(exc))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(_canonical(document))
    except FileExistsError:
        return _refuse("the output file already exists")
    except OSError as exc:
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)  # created here, since FileExistsError is handled above
        return _refuse(f"writing the output file failed ({type(exc).__name__})")
    print(_counts_line(document), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
