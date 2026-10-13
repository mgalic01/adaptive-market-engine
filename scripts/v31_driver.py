"""The V3.1 run driver's command line (Task 10a): ``prepare``, ``picks``, ``run-cell``,
``aggregate`` and ``smoke``.

Every subcommand but ``smoke`` passes its gate before it reads any input beyond the
registration, then calls the driver library (``crypto_grid_bot.combined.driver``) and
prints one canonical JSON document on stdout (sorted keys, no spaces, ASCII, one
newline). Logs go to stderr; a refusal is one stderr line and exit status 1. Only
``prepare`` touches the network, and only data.binance.vision through the guarded
transports (``fetch_v3_data.V3Transport`` for the inventory, ``v31_fetch.LegacyTransport``
for the legacy archives), each archive verified against its committed SHA-256 before it is
kept. Every write is an exclusive create through the library or here: nothing deletes or
replaces an earlier attempt's output, and no attempt is retried (a transport failure is,
inside ``fetch_entries``, Ruling P6). Nothing at or after 2025-01 is fetched, opened or
read.

``prepare --mode prepare-only|registered --work W --out O`` (Ruling P1)
    The gate: in ``prepare-only``, the checkout is ``--code-commit`` with no uncommitted
    change and ``config/v3_1_prepare.json`` hashes to ``--prepare-sha256``; no
    registration exists yet. In ``registered``, the registration and run-manifest load,
    the registration hashes to ``--registration-sha256``, nothing but the registration
    artifacts changed since its code pin, and the prepare config, data manifests,
    snapshots and windows are the ones the run-manifest pins. Then it plans every archive
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
    (``prepare_document``) is written to ``O/prepare.json`` and printed.
``picks --packs P --attempt-id ID --out O``
    The gate's code, config and run-manifest checks (``job_gate``), then V3's selector
    picks from the V3 input pack read against its pin: ``O/v3_picks/``. Prints the
    SHA-256 of the picks job's completion marker ``O/v3_picks/outcome.json``.
``run-cell --cell C --packs P --attempt-id ID --out O [--picks D] [--legacy-data L]``
    ``execution_gate`` with the repo head, the changes since the code pin and the adapter
    pins at the head, on the cell's window pack read against the same pin the gate
    checks; then the cell by its kind: ``O/<cell_id>/``. A V3 cell takes the whole
    ``v3_picks/`` directory of the same workflow run (``--picks``); a minute cell the
    legacy dataset (``--legacy-data``), verified first.
``aggregate --cells D --attempt-id ID --out O``
    ``job_gate``, then the verdict and summary: ``O/summary/``. ``ID`` is the workflow's
    ``<run_id>-attempt-<run_attempt>``; a W1 cell or the picks job from another artifact
    attempt than 1 or another run makes the verdict incomplete (re-run detected).
``smoke --out O [--cells N]``
    No gate and no network: a synthetic world (``v31_smoke``) with all 42 arms and 216
    cells on three-day windows, its packs, the picks job, every cell (or the first ``N``,
    one of each kind first) and the aggregate, through the same functions as the
    subcommands, to a verdict.

Attempt ids: the workflow passes ``--attempt-id <run_id>-attempt-<run_attempt>``, the same
for every job of a run. Each job derives and records its own id from it
(``job_attempt_id``): ``<run_id>-<cell_id>-attempt-<run_attempt>`` for a cell and
``<run_id>-v3_picks-attempt-<run_attempt>`` for the picks job. Acceptance
(``experiment.evaluate``) refuses one attempt id on two outcomes, and the id still ends in
the artifact folder's ``-attempt-<n>``, which aggregation checks.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import v31_smoke
from fetch_v3_data import V3Transport
from v31_fetch import ARCHIVE_PREFIX, ArchiveTransport, LegacyTransport, entries_for, fetch_entries
from v31_v3_pack import build_v3_pack

from crypto_grid_bot.backtest.dataset import load_manifest, load_spec, verify_dataset
from crypto_grid_bot.backtest.jobs import manifest_path, quote_limits, quoted, replayed_minutes
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.backtest.masking import QUOTE_TESTED_SYMBOL, quote_spreads_pct
from crypto_grid_bot.combined.driver.aggregate import VERDICT_FILE, _extended, aggregate
from crypto_grid_bot.combined.driver.decode import (
    DecodedV31Month,
    decode_minute_month,
    decode_month,
)
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

PREPARE_CONFIG = "config/v3_1_prepare.json"
REGISTRATION = "config/v3_1_registration.json"
RUN_MANIFEST = "config/v3_1_run_manifest.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"
V3_FAMILY = "spec-v3"  # V3's registered trial, whose completion pins its inventory and calendar
PACKS_DIR = "packs"
STAGING_DIR = "staging"
PREPARE_FILE = "prepare.json"
V3_PACK_FILE = "v3-input.pack.json.gz"
INVENTORY_DIR = "inventory"  # V3's collection layout: the manifest, snapshots/, archives/
LEGACY_DIR = "legacy"  # the legacy dataset, as backtest reads it: legacy/binance/data/...
MINUTES_DIR = "minutes"  # the V3.1 minute manifests' other archives: minutes/binance/data/...
PREPARE_OUTPUT_SCHEMA = "v3.1-prepare-output-1"
SMOKE_SCHEMA = "v3.1-smoke-1"
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

Log = Callable[[str], None]
V3PackBuilder = Callable[[Path, str, Mapping[str, str], Path], str]


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
) -> None:
    """Fetch and verify every planned archive into the cache under ``work``, one
    ``fetch_entries`` call per archive family and cache, each with its own transport (one
    transport serves one family). Retries of a transport failure are ``fetch_entries``'
    (Ruling P6), each logged; every verified archive is logged too."""
    families: tuple[tuple[str, tuple[dict[str, Any], ...], Path, ArchiveTransport], ...] = (
        (
            "inventory",
            plan.inventory_entries,
            work / INVENTORY_DIR / "archives",
            inventory_transport,
        ),
        ("legacy", plan.legacy_entries, work / LEGACY_DIR / "binance", legacy_transport),
        ("minutes", plan.minute_entries, work / MINUTES_DIR / "binance", legacy_transport),
    )
    for family, entries, cache, transport in families:
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
    (the dispatch's pin), the run-manifest file to the registered pin, and every change
    since the code pin must be a registration artifact (Ruling P10c). One ``ValueError``
    names every mismatch."""
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
    if errors:
        raise ValueError("job gate refused:\n- " + "\n- ".join(errors))
    return head_commit(repo)


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
    """``prepare`` (the module docstring): the gate, the plan, the fetch, the packs."""
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
    else:
        reg, manifest_sha = load_registered(repo, args)
        job_gate(
            reg, repo, registration_sha256=args.registration_sha256, manifest_sha256=manifest_sha
        )
        prepare_pins_gate(reg, config)
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
    pack: WindowPack,
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

    ``pack`` is the cell's window pack as the gate checked it. A V3 cell reads the V3 input
    pack against its pin and the whole ``v3_picks/`` directory ``picks_dir``; a minute cell
    the legacy dataset ``legacy_dir``, verified with ``verify_dataset`` first."""
    options = {"attempt_id": attempt_id, "repo_head": repo_head}
    if cell.kind == "v3" and (picks_dir is None or Path(picks_dir).name != V3_PICKS):
        raise ValueError(f"cell {cell.cell_id}: a V3 cell needs --picks, the {V3_PICKS}/ directory")
    if cell.kind == "minute" and legacy_dir is None:
        raise ValueError(f"cell {cell.cell_id}: a minute cell needs --legacy-data")
    out.mkdir(parents=True, exist_ok=True)
    if cell.kind == "v31":
        return run_v31_cell(cell, pack, reg, out, **options)
    if cell.kind == "hold":
        return run_hold_cell(cell, pack, reg, out, **options)
    if cell.kind == "v3" and picks_dir is not None:
        inputs = read_v3_pack(packs_dir / V3_PACK_FILE, reg.run_manifest.v3_pack)
        return run_v3_cell(cell, inputs, Path(picks_dir) / PICKS_FILE, reg, out, **options)
    if cell.kind == "minute" and legacy_dir is not None:
        verify_legacy(repo, Path(legacy_dir))
        return run_minute_cell(cell, Path(legacy_dir), reg, out, repo_root=repo, **options)
    raise ValueError(f"cell {cell.cell_id}: unknown kind {cell.kind!r}")


def picks(args: argparse.Namespace) -> dict[str, object]:
    repo = Path(args.repo)
    reg, manifest_sha = load_registered(repo, args)
    attempt_id = job_attempt_id(args.attempt_id, V3_PICKS)
    head = job_gate(
        reg, repo, registration_sha256=args.registration_sha256, manifest_sha256=manifest_sha
    )
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
    pack_sha = dict(reg.run_manifest.window_packs)[cell.window]
    pack = read_pack(Path(args.packs) / window_pack_file(cell.window), pack_sha)
    execution_gate(
        reg,
        cell.cell_id,
        repo_head=head,
        pack_sha256=pack_sha,  # the same pin read_pack checked the pack against
        config_sha256=args.registration_sha256,
        manifest_sha256=manifest_sha,
        changed_paths=changed,
        adapter_pins_now=pins_now,
        pack=pack,
    )
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


def aggregate_cells(args: argparse.Namespace) -> dict[str, object]:
    repo = Path(args.repo)
    reg, manifest_sha = load_registered(repo, args)
    job_gate(reg, repo, registration_sha256=args.registration_sha256, manifest_sha256=manifest_sha)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = aggregate(reg, Path(args.cells), out, attempt_id=args.attempt_id)
    return _verdict_document(summary)


def _verdict_document(summary: Path) -> dict[str, object]:
    raw = (summary / VERDICT_FILE).read_bytes()
    return {
        "status": json.loads(raw)["status"],
        "summary": str(summary),
        "verdict_sha256": hashlib.sha256(raw).hexdigest(),
    }


def smoke_cells(reg: DriverRegistration, count: int | None) -> list[Cell]:
    """Every registered cell, or the first ``count``: one W1 cell of each kind and one W0
    cell first, then the rest in registration order."""
    cells = list(reg.cells)
    if count is None or count >= len(cells):
        return cells
    firsts = [
        next(cell for cell in cells if cell.kind == kind and cell.window == ACCEPTANCE_WINDOW)
        for kind in ("v31", "hold", "v3", "minute")
    ]
    firsts.append(next(cell for cell in cells if cell.window == REPORTED_WINDOW))
    return [*firsts, *(cell for cell in cells if cell not in firsts)][:count]


def smoke_packs(world: v31_smoke.World, packs_dir: Path) -> dict[str, object]:
    """What prepare builds, from the smoke world's synthetic coins, written under the new
    directory ``packs_dir``: each window pack (W1's skipped hours joined by its extra
    sources, ``window_extras``, as prepare joins them) and the V3 input pack. Returns the
    prepare document. Run it under ``v31_smoke.stand_ins()``: the masks need them."""
    packs_dir.mkdir()
    sources = [(pin.path, pin.sha256) for pin in world.prepare.data_manifests]
    pins: dict[str, str] = {}
    skipped: dict[str, dict[str, object]] = {}
    for window in world.prepare.windows:
        extras: dict[str, tuple[int, ...]] = {}
        if window.id == ACCEPTANCE_WINDOW:
            extras = window_extras(world.repo, world.legacy, window.start_ms, window.end_ms)
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
    v3_pin = write_v3_pack(v31_smoke.v3_fields(), packs_dir / V3_PACK_FILE)
    return prepare_document("smoke", world.head, world.prepare, skipped, pins, v3_pin, None)


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
                picks_dir=picks_dir,
                legacy_dir=world.legacy,
            )
            folder = cells_dir / f"cell-{cell.cell_id}-attempt-1"
            folder.mkdir()
            directory.rename(folder / cell.cell_id)
        (root / "a").mkdir()
        summary = aggregate(reg, cells_dir, _extended(root / "a"), attempt_id=attempt)
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

    prep = commands.add_parser("prepare", help="fetch, verify and pack every input")
    prep.add_argument("--mode", choices=("prepare-only", "registered"), required=True)
    registered(prep, required=False)
    prep.add_argument("--prepare-config", default=PREPARE_CONFIG)
    prep.add_argument("--prepare-sha256", help="prepare-only: the expected prepare config pin")
    prep.add_argument("--code-commit", help="prepare-only: the expected checkout head")
    prep.add_argument("--work", required=True, help="the archive cache (may exist)")
    prep.add_argument("--out", required=True, help="the output directory (must not exist)")

    pick = commands.add_parser("picks", help="V3's selector picks, once")
    registered(pick)
    pick.add_argument("--packs", required=True)
    pick.add_argument(
        "--attempt-id",
        required=True,
        help="the workflow's <run_id>-attempt-<run_attempt>, the same for every job of a run; "
        "the picks job records <run_id>-v3_picks-attempt-<run_attempt>",
    )
    pick.add_argument("--out", required=True)

    cell = commands.add_parser("run-cell", help="one registered cell")
    registered(cell)
    cell.add_argument("--cell", required=True)
    cell.add_argument("--packs", required=True)
    cell.add_argument(
        "--attempt-id",
        required=True,
        help="the workflow's <run_id>-attempt-<run_attempt>, the same for every job of a run; "
        "the cell records <run_id>-<cell_id>-attempt-<run_attempt>, unique per cell as "
        "acceptance requires",
    )
    cell.add_argument("--out", required=True)
    cell.add_argument("--picks", help="a V3 cell: the v3_picks/ directory of the same run")
    cell.add_argument("--legacy-data", help="a minute cell: the verified legacy dataset")

    agg = commands.add_parser("aggregate", help="the verdict and summary")
    registered(agg)
    agg.add_argument("--cells", required=True)
    agg.add_argument(
        "--attempt-id",
        required=True,
        help="the workflow's <run_id>-attempt-<run_attempt>: every W1 cell and the picks "
        "job must be attempt 1 of run <run_id>, or the verdict is incomplete (re-run "
        "detected)",
    )
    agg.add_argument("--out", required=True)

    smoke_ = commands.add_parser("smoke", help="offline, synthetic, end to end")
    smoke_.add_argument("--out", required=True, help="the smoke's directory (must not exist)")
    smoke_.add_argument("--cells", type=int, help="run only this many cells (default: all)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    inventory_transport: ArchiveTransport | None = None,
    legacy_transport: ArchiveTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    v3_pack_builder: V3PackBuilder = build_v3_pack,
) -> int:
    """Run one subcommand; 0 with its document on stdout, 1 on a refusal (on stderr).

    The keyword arguments replace prepare's transports, its retry sleep and the V3 pack
    builder (tests); by default the real guarded transports and ``time.sleep``."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            document = prepare(
                args,
                inventory_transport=(
                    V3Transport() if inventory_transport is None else inventory_transport
                ),
                legacy_transport=(
                    LegacyTransport() if legacy_transport is None else legacy_transport
                ),
                sleep=sleep,
                log=log,
                v3_pack_builder=v3_pack_builder,
            )
        elif args.command == "picks":
            document = picks(args)
        elif args.command == "run-cell":
            document = run_cell(args)
        elif args.command == "aggregate":
            document = aggregate_cells(args)
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
