"""One registered V3.1 cell, run once: the execution gate, the replay and its artifacts.

``execution_gate`` refuses a run unless the checkout, the configuration and the pack are
the registered ones (Rulings P10c and P12). ``run_v31_cell`` replays a component cell
from its window pack, with costs from the cell's cost multiple alone and the capital,
window and pins from the registration, and writes the cell's artifacts once
(Ruling P13)::

    <out_dir>/<cell_id>/outcome.json            encode_outcome, report evidence included
    <out_dir>/<cell_id>/report.json             encode_report
    <out_dir>/<cell_id>/<invocation>/           write_bundle: the funnel journal, the
                                                evidence records, report.json when the
                                                report's exact JSON is above the page's
                                                inline limit, metadata and the receipt

where ``<invocation>`` is the cell id with each ``.`` replaced by ``-``. Every file is an
exclusive create, so a second run of a cell into the same directory is refused and
leaves the first one's files as they were. ``changed_since`` and ``head_commit`` read the
checkout with git; nothing here touches the network.
"""

import hashlib
import re
import subprocess
from collections.abc import Mapping
from decimal import Context, localcontext
from pathlib import Path, PurePosixPath

from crypto_grid_bot.combined.artifacts import _name, _write, write_bundle
from crypto_grid_bot.combined.dashboard import render_bundle_report
from crypto_grid_bot.combined.driver.packs import WindowPack
from crypto_grid_bot.combined.driver.registration import (
    Cell,
    DriverRegistration,
    check_registration,
)
from crypto_grid_bot.combined.driver.serialize import encode_outcome, encode_report
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS, cost_profile
from crypto_grid_bot.combined.evidence import Evidence
from crypto_grid_bot.combined.experiment import Capital, RunIdentity, Window, capital_label
from crypto_grid_bot.combined.observation_policy import POLICY_ID
from crypto_grid_bot.combined.outcomes import strategy_outcome
from crypto_grid_bot.combined.replay_records import evidence_records, strategy_report
from crypto_grid_bot.combined.strategy_replay import (
    ReplayRun,
    StrategyTrace,
    SymbolMarket,
    VenueMarket,
    replay_strategy,
)

# The files a checkout may change after the code pin (Ruling P10c), besides the FX
# records the registration names and anything under the two document directories.
REGISTRATION_ARTIFACTS = frozenset(
    {
        "config/v3_1_registration.json",
        "config/v3_1_run_manifest.json",
        "config/v3_1_prepare.json",
        "config/v3_1_experiment_menu.json",
        "docs/trials/register.jsonl",
    }
)
REGISTRATION_DIRECTORIES = ("docs/reviews/", "docs/tasks/")
METADATA_SCHEMA = "v3.1-cell-1"

_COMMIT = re.compile(r"[0-9a-f]{40}")


def execution_gate(
    reg: DriverRegistration,
    cell_id: str,
    *,
    repo_head: str,
    pack_sha256: str,
    config_sha256: str,
    manifest_sha256: str,
    changed_paths: tuple[str, ...],
    adapter_pins_now: Mapping[str, str],
    pack: WindowPack,
) -> Cell:
    """The registered cell ``cell_id``, once every input matches the registration;
    otherwise one ``ValueError`` naming every mismatch.

    The registration must pass ``check_registration``; ``config_sha256`` must be its
    config pin and ``manifest_sha256`` its run-manifest pin; ``pack_sha256`` must be the
    run-manifest's pin of the cell's window, and ``pack`` (already read by ``read_pack``
    against that pin) must hold that window's id, start, end and skipped hours.
    ``changed_paths`` (``changed_since(repo, code_pin)``) may touch only the
    registration artifacts, the FX records it names and ``docs/reviews/``/``docs/tasks/``.
    ``adapter_pins_now`` (``adapter_pins(repo, head_commit(repo))``) must give the cell's
    arm its registered adapter pin. ``repo_head`` is provenance only: the code pin
    precedes the registration commit, so the head is never compared with it.
    """
    if not isinstance(reg, DriverRegistration):
        raise ValueError("execution gate: a DriverRegistration required")
    errors: list[str] = []
    try:
        check_registration(reg)
    except ValueError as exc:
        errors.append(str(exc))
    registration = reg.registration
    if type(repo_head) is not str or _COMMIT.fullmatch(repo_head) is None:
        errors.append(f"the repo head {repo_head!r} is not a 40 lowercase hex commit")
    if config_sha256 != registration.config_pin:
        errors.append(
            f"config SHA-256 {config_sha256} differs from the config pin {registration.config_pin}"
        )
    if manifest_sha256 != reg.run_manifest_pin:
        errors.append(
            f"run-manifest SHA-256 {manifest_sha256} differs from the registered "
            f"{reg.run_manifest_pin}"
        )
    errors.extend(_path_errors(changed_paths, reg.fx_record_paths))
    cells = [cell for cell in reg.cells if cell.cell_id == cell_id]
    if not cells:
        errors.append(f"cell {cell_id!r} is not registered")
    else:
        (cell,) = cells
        pinned = dict(reg.run_manifest.window_packs).get(cell.window)
        if pinned is None or pack_sha256 != pinned:
            errors.append(
                f"pack SHA-256 {pack_sha256} differs from the run-manifest's pin {pinned} "
                f"of window {cell.window}"
            )
        registered = dict(registration.adapter_pins).get(cell.arm)
        current = adapter_pins_now.get(cell.arm)
        if registered is None or current != registered:
            errors.append(
                f"the adapter pin of {cell.arm} at the checkout is {current}; the "
                f"registration pins {registered}"
            )
        window = _windows(reg).get(cell.window)
        if window is None:
            errors.append(f"window {cell.window} is not registered")
        else:
            errors.extend(_pack_errors(pack, window))
    if errors:
        raise ValueError(f"execution gate refused cell {cell_id!r}:\n- " + "\n- ".join(errors))
    return cell


def changed_since(repo_root: str | Path, commit: str) -> tuple[str, ...]:
    """Every path changed since ``commit``, sorted: in the commits to HEAD (``git diff
    --name-only <commit> HEAD``, Ruling P10c) or in the tracked working tree against HEAD.

    Renames are listed as both their paths (``--no-renames``), so moving a file out of
    ``src/`` cannot hide its removal. Untracked files are not listed. Refuses a commit
    that is not 40 lowercase hex and any git failure.
    """
    if type(commit) is not str or _COMMIT.fullmatch(commit) is None:
        raise ValueError(f"commit {commit!r}: 40 lowercase hex required")
    root = Path(repo_root)
    paths: set[str] = set()
    for revisions in ((f"{commit}^{{commit}}", "HEAD"), ("HEAD",)):
        output = _git(root, "diff", "--name-only", "--no-renames", "-z", *revisions, "--")
        paths.update(name.decode("utf-8") for name in output.split(b"\0") if name)
    return tuple(sorted(paths))


def head_commit(repo_root: str | Path) -> str:
    """The checkout's HEAD commit, as 40 lowercase hex."""
    head = _git(Path(repo_root), "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if _COMMIT.fullmatch(head) is None:
        raise ValueError(f"git rev-parse gave {head!r}, not a 40 lowercase hex commit")
    return head


def run_v31_cell(
    cell: Cell, pack: WindowPack, reg: DriverRegistration, out_dir: Path, *, attempt_id: str
) -> Path:
    """Replay the registered component cell ``cell`` on ``pack`` once and return its
    artifact directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    Each coin's spot and, when it has futures, futures market take the costs of
    ``cell.cost_multiple`` alone (``cost_profile``); the flow schedule replaces its minute
    bars. The capital, window and pins come from the registration: W1 cells and the
    reported W0 cells alike. Refuses, before anything is written, a cell that is not a
    registered ``v31`` cell, a pack of another window, an empty attempt id and an
    existing cell directory.
    """
    if not isinstance(cell, Cell) or cell.kind != "v31":
        raise ValueError("a v31 component cell required")
    if not isinstance(reg, DriverRegistration) or cell not in reg.cells:
        raise ValueError(f"cell {cell.cell_id} is not registered")
    window = _windows(reg)[cell.window]
    if errors := _pack_errors(pack, window):
        raise ValueError(f"cell {cell.cell_id}: " + "; ".join(errors))
    if type(attempt_id) is not str or not attempt_id.strip():
        raise ValueError("a nonempty attempt id required")
    invocation = cell.cell_id.replace(".", "-")
    _name(invocation)
    directory = Path(out_dir) / cell.cell_id
    if directory.exists():
        raise FileExistsError(f"{directory}: the cell has already been written")
    registration = reg.registration
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(registration.adapter_pins)[cell.arm]
    pack_pin = dict(reg.run_manifest.window_packs)[cell.window]
    multiple = cell.cost_multiple

    # A fresh default decimal context: the caller's context cannot change the cell's
    # bytes, the bundle's records (encoded by write_bundle) included.
    with localcontext(Context()):
        run = ReplayRun(
            arm=cell.arm,
            scenario=cell.scenario,
            initial_cash=capital.initial_equity,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            source_refs=(f"v31-pack:{pack_pin}", f"v31-run-manifest:{reg.run_manifest_pin}"),
        )
        trace = replay_strategy(run, _markets(pack, multiple))
        identity = RunIdentity(
            arm=cell.arm,
            window=cell.window,
            capital=capital.id,
            cost_multiple=multiple,
            data_pin=window.data_pin,
            cost_profile_pin=COST_PROFILE_PINS[multiple],
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            code_pin=registration.code_pin,
            config_pin=registration.config_pin,
            fx_pin=capital.fx_pin,
            observation_policy=POLICY_ID,
            adapter_pin=adapter_pin,
            scenario=cell.scenario,
        )
        report = strategy_report(
            trace,
            adapter_pin=adapter_pin,
            skipped_hours=pack.skipped_hours,
            capital_label=capital_label(capital),
        )
        outcome = strategy_outcome(trace, report, identity, attempt_id=attempt_id)
        outcome_raw = encode_outcome(outcome).encode("ascii")
        report_raw = encode_report(report).encode("ascii")
        records = evidence_records(trace, skipped_hours=pack.skipped_hours)
        _, report_json = render_bundle_report(report, synthetic=False)
        metadata: dict[str, object] = {
            "schema": METADATA_SCHEMA,
            "cell_id": cell.cell_id,
            "attempt_id": attempt_id,
            "arm": cell.arm,
            "window": cell.window,
            "scenario": cell.scenario,
            "cost_multiple": multiple,
            "capital": capital.id,
            "initial_equity": str(capital.initial_equity),
            "code_pin": registration.code_pin,
            "config_pin": registration.config_pin,
            "data_pin": window.data_pin,
            "run_manifest_sha256": reg.run_manifest_pin,
            "pack_sha256": pack_pin,
            "cost_profile_pin": COST_PROFILE_PINS[multiple],
            "adapter_pin": adapter_pin,
            "fx_pin": capital.fx_pin,
            "observation_policy": POLICY_ID,
            "outcome_sha256": hashlib.sha256(outcome_raw).hexdigest(),
            "report_sha256": hashlib.sha256(report_raw).hexdigest(),
        }

        directory.mkdir(exist_ok=False)
        _write(directory / "outcome.json", outcome_raw)
        _write(directory / "report.json", report_raw)
        write_bundle(
            directory,
            invocation,
            _journal(trace),
            metadata,
            report_html=None,
            records=records,
            report_json=report_json,
        )
    return directory


def _markets(pack: WindowPack, multiple: int) -> tuple[SymbolMarket, ...]:
    """One market per pack coin, every venue at the costs of ``multiple``."""
    spot, futures = cost_profile(multiple, "spot"), cost_profile(multiple, "futures")
    return tuple(
        SymbolMarket(
            symbol=coin.symbol,
            spot=VenueMarket(coin.spot_hourly, coin.spot_rules, spot),
            daily=coin.daily,
            futures=None
            if coin.futures_rules is None
            else VenueMarket(coin.futures_hourly, coin.futures_rules, futures),
            funding=coin.funding,
            minutes=(),
            flow=coin.flow,
        )
        for coin in pack.coins
    )


def _journal(trace: StrategyTrace) -> Evidence:
    """The replay's funnel journal, rebuilt from its recorded events in order: the trace
    keeps the events, and recording them again repeats the journal's own checks."""
    journal = Evidence()
    for event in trace.evidence:
        journal.record(event)
    return journal


def _windows(reg: DriverRegistration) -> dict[str, Window]:
    """The acceptance and the reported windows by id."""
    return {window.id: window for window in (*reg.registration.windows, *reg.reported_windows)}


def _capital(reg: DriverRegistration, capital_id: str) -> Capital:
    (capital,) = [c for c in reg.registration.capitals if c.id == capital_id]
    return capital


def _pack_errors(pack: WindowPack, window: Window) -> list[str]:
    """How ``pack`` differs from the registered ``window``."""
    if not isinstance(pack, WindowPack):
        return ["a WindowPack required"]
    errors = []
    held = (pack.window_id, pack.start_ms, pack.end_ms)
    registered = (window.id, window.start_ms, window.end_ms)
    if held != registered:
        errors.append(f"the pack window {held} differs from the registered {registered}")
    if pack.skipped_hours != window.skipped_hours:
        errors.append(
            f"the pack's skipped hours {pack.skipped_hours} differ from window "
            f"{window.id}'s registered {window.skipped_hours}"
        )
    return errors


def _path_errors(paths: tuple[str, ...], fx_records: tuple[str, ...]) -> list[str]:
    """The changed paths outside the registration artifacts (Ruling P10c)."""
    if not isinstance(paths, tuple) or any(type(path) is not str for path in paths):
        return ["changed paths: a tuple of repository paths required"]
    allowed = REGISTRATION_ARTIFACTS | set(fx_records)
    refused = [path for path in paths if not _allowed(path, allowed)]
    if not refused:
        return []
    return [
        "the checkout changes code or data after the code pin, outside the registration "
        f"artifacts: {', '.join(refused)}"
    ]


def _allowed(path: str, allowed: frozenset[str] | set[str]) -> bool:
    canonical = (
        bool(path)
        and "\\" not in path
        and str(PurePosixPath(path)) == path
        and not PurePosixPath(path).is_absolute()
        and ".." not in PurePosixPath(path).parts
    )
    if not canonical:
        return False
    return path in allowed or any(
        path.startswith(prefix) and len(path) > len(prefix) for prefix in REGISTRATION_DIRECTORIES
    )


def _git(root: Path, *args: str) -> bytes:
    process = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if process.returncode:
        message = process.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"git {args[0]} failed in {root}: {message}")
    return process.stdout
