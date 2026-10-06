"""Byte-identity check: V0 and every spec v1 variant must stay exactly what they were.

    python scripts/byte_identity.py check    # replay every run; compare with the baseline
    python scripts/byte_identity.py record   # rewrite scripts/byte_identity_baseline.json

Synthetic data only, no network, paper only: three datasets (``up``, ``down``, ``nod``)
are built through ``dataset.fetch_dataset`` from a fake archive in a temporary directory
and removed afterwards. Every run is then replayed on them:

* the backtest CLI's ``run``, in this process (``--jobs 1``, its inline executor), on
  ``up``, ``down`` and ``nod``, and with ``--structure`` on ``up`` and ``down``; the
  ``up`` and ``down`` V0 runs add ``--trend-benchmark``, so variant D is checked too;
* every registered v1 variant through ``run_job`` for all four path and gated cases,
  so that a change to a shared path cannot pass unseen.

Each run has two SHA-256s in the baseline. ``sha256`` is of the run's output document with
the identity keys set aside (``IDENTITY_KEYS``): the code, spec, manifest and config
hashes, which a later change may legitimately move. ``trace_sha256`` is of what
``StepTrace`` saw: every fill, exit reason and resting order after every
``PaperSimulator.step``, in order. The output document holds aggregates, so a change that
moved, reordered or relabelled fills could keep every row and still match on the first.

Everything is deterministic: seeded generators, a fixed clock for the manifest, and fixed
dates and attributes in the zip archives. A run that differs between two builds is a
defect in this script, not noise.

``check`` prints one line per run, ``<run> <sha256> IDENTICAL|DIFFERENT``, then
``ALL IDENTICAL`` or ``SOME DIFFER``, and exits 0 only when every run matches. A run the
baseline lists but this script no longer makes prints ``<run> - DIFFERENT``, the hash
field a placeholder. What differs in a run that does not match goes to stderr. A check
is 15 runs of four replays each: about 45 minutes on one core, about 20 with ``--jobs 4``
on four cores (the outcomes are the same). The baseline is recorded from main before any
code that is meant to change a run's output; if main moves first, record it again on the
new merge base. It was recorded on CPython 3.14 on Windows: the engine's features are
floats, so another platform's libm could in principle move a last digit, and a failure
that appears only there is to be told apart from a change in the code by running
``check`` on the recording platform.

The functions below are importable: each run function returns its output document, not
only a hash, so two trees' (or two harnesses') documents can be compared directly.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import io
import json
import math
import platform
import random
import sys
import tempfile
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_grid_bot.backtest import __main__ as backtest_cli  # noqa: E402
from crypto_grid_bot.backtest import jobs as backtest_jobs  # noqa: E402
from crypto_grid_bot.backtest.dataset import (  # noqa: E402
    archive_path,
    fetch_dataset,
    funding_archive_path,
    load_spec,
    write_manifest,
)
from crypto_grid_bot.backtest.replay import PATH_MODES  # noqa: E402
from crypto_grid_bot.simulation.models import Account  # noqa: E402
from crypto_grid_bot.simulation.runner import FULL_STACK, PaperSimulator  # noqa: E402

BASELINE = Path(__file__).with_name("byte_identity_baseline.json")
CONFIG = ROOT / "config" / "default.toml"
BASELINE_FORMAT = 1
# Keys that name the code, spec, manifest and config a document came from. A later
# change may move them without changing a result, so no hash covers them.
IDENTITY_KEYS = frozenset(
    {"spec_sha256", "manifest_sha256", "config_sha256", "code_commit", "code_sha256"}
)

MINUTE = 60_000
HOUR = 3_600_000
DAY = 86_400_000
# The dataset builds are deterministic: the manifest's clock, and every zip entry's date.
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# Each dataset: its price drift per day (the price is the random walk times
# exp(drift * days since the start)) and whether it has daily history. ``up`` and ``down``
# have it, so variants A, C and H and variant D run on them; ``nod`` has none.
DATASETS = {"up": (0.0, True), "down": (-0.004, True), "nod": (0.0, False)}
BASKET = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
FILTERS = {
    "base": "BTC",
    "quote": "USDT",
    "tick_size": "0.01",
    "quantity_step": "0.00001",
    "min_notional": "5",
}

Bar = tuple[int, float, float, float, float, float]  # open time (ms), O, H, L, C, volume


def ms(year: int, month: int, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


def csv_row(bar: Bar, step: int) -> str:
    open_ms, o, h, low, c, volume = bar
    quote_volume = volume * c
    return ",".join(
        [str(open_ms), f"{o:.2f}", f"{h:.2f}", f"{low:.2f}", f"{c:.2f}", f"{volume:.4f}"]
        + [
            str(open_ms + step - 1),
            f"{quote_volume:.4f}",
            "100",
            f"{volume / 2:.4f}",
            f"{quote_volume / 2:.4f}",
            "0",
        ]
    )


def walk(seed: int, start: int, end: int, base: float) -> list[Bar]:
    """Minute OHLCV: a slow 120-day cycle times a mean-reverting minute-scale wiggle."""
    # Seeded synthetic prices, nothing secret.
    rng = random.Random(seed)  # nosec B311
    bars: list[Bar] = []
    x, previous = 0.0, None
    for t in range(start, end, MINUTE):
        x = 0.998 * x + rng.gauss(0, 0.003)
        days = (t - start) / DAY
        price = base * (1 + 0.25 * math.sin(2 * math.pi * days / 120)) * math.exp(x)
        o = previous if previous is not None else price
        h = max(o, price) * (1 + abs(rng.gauss(0, 0.001)))
        low = min(o, price) * (1 - abs(rng.gauss(0, 0.001)))
        volume = 5000 + 5000 * rng.random()
        bars.append((t, o, h, low, price, volume))
        previous = price
    return bars


def aggregate(bars: Sequence[Bar], step: int) -> list[Bar]:
    """The bars rolled up to ``step`` ms: first open, extreme highs and lows, last close."""
    rolled: dict[int, list[float]] = {}
    for t, o, h, low, c, volume in bars:
        key = t - t % step
        if key not in rolled:
            rolled[key] = [o, h, low, c, volume]
        else:
            bar = rolled[key]
            bar[1], bar[2], bar[3], bar[4] = max(bar[1], h), min(bar[2], low), c, bar[4] + volume
    return [(key, bar[0], bar[1], bar[2], bar[3], bar[4]) for key, bar in rolled.items()]


def by_month(bars: Sequence[Bar]) -> dict[str, list[Bar]]:
    months: dict[str, list[Bar]] = {}
    for bar in bars:
        key = datetime.fromtimestamp(bar[0] / 1000, UTC).strftime("%Y-%m")
        months.setdefault(key, []).append(bar)
    return months


def funding_text() -> str:
    """January 2024 of BTCUSDT's perpetual funding, in the layout ``load_funding`` reads:
    an 8-hourly settlement stamped a few milliseconds after the hour, at 0.01% except for
    the 10th to the 14th, where it reads 0.08%, above variant G's block rate."""
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    for n in range(93):
        rate = "0.00080000" if 9 <= n // 3 < 14 else "0.00010000"
        lines.append(f"{ms(2024, 1) + n * 8 * HOUR + 5},8,{rate}")
    return "\n".join(lines) + "\n"


def zip_member(member: str, text: str) -> bytes:
    """A zip holding one file. Every field is fixed, the date and the creating system
    included, so the bytes are the same whenever and wherever it is built."""
    info = zipfile.ZipInfo(member, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, text)
    return buffer.getvalue()


class FakeArchive:
    """The archive host's objects by path, each zip with the checksum file beside it."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def add(self, path: str, text: str) -> None:
        name = path.rsplit("/", 1)[1]
        body = zip_member(name.removesuffix(".zip") + ".csv", text)
        self.objects[path] = body
        self.objects[path + ".CHECKSUM"] = f"{hashlib.sha256(body).hexdigest()}  {name}".encode()

    def __call__(self, path: str) -> bytes | None:
        return self.objects.get(path)


def build_dataset(work: Path, name: str) -> None:
    """Build dataset ``name`` (a key of ``DATASETS``) in ``work``: ``synth.toml``, the
    archives under ``data/`` and ``synth.manifest.json``, through ``fetch_dataset``.
    The month before the evaluation month is warm-up, so the CLI's integrity checks pass
    over the whole evaluation month."""
    drift, daily = DATASETS[name]
    work.mkdir(parents=True, exist_ok=True)
    spec_path = work / "synth.toml"
    spec_lines = [
        'name = "synth"',
        'purpose = "strategy PR byte-identity check"',
        'traded = ["BTCUSDT"]',
        'market_proxy = "BTCUSDT"',
        "breadth_basket = " + json.dumps(BASKET),
        *(['daily_warmup_start = "2023-05"'] if daily else []),
        'warmup_start = "2023-11"',
        'start = "2024-01"',
        'end = "2024-01"',
        'initial_quote = "10000"',
        'fee_rate = "0.001"',
        'slippage_rate = "0.0005"',
        'participation = "0.10"',
        'assumed_spread_pct = "0.05"',
    ]
    spec_path.write_text("\n".join(spec_lines) + "\n")
    archive = FakeArchive()
    start, warm = ms(2023, 5), ms(2023, 11)
    eval_start, eval_end = ms(2024, 1), ms(2024, 2)
    for i, symbol in enumerate(["BTCUSDT", *BASKET]):
        bars = []
        first = start if symbol == "BTCUSDT" else warm
        for t, o, h, low, c, volume in walk(100 + i, first, eval_end, 100 + 7 * i):
            factor = math.exp(drift * (t - start) / DAY)
            bars.append((t, o * factor, h * factor, low * factor, c * factor, volume))
        hours = [bar for bar in aggregate(bars, HOUR) if bar[0] >= warm]
        for month, rows in by_month(hours).items():
            text = "\n".join(csv_row(bar, HOUR) for bar in rows) + "\n"
            archive.add(archive_path(symbol, "1h", month), text)
        if symbol == "BTCUSDT":
            if daily:
                for month, rows in by_month(aggregate(bars, DAY)).items():
                    text = "\n".join(csv_row(bar, DAY) for bar in rows) + "\n"
                    archive.add(archive_path(symbol, "1d", month), text)
            minutes = [bar for bar in bars if bar[0] >= eval_start]
            text = "\n".join(csv_row(bar, MINUTE) for bar in minutes) + "\n"
            archive.add(archive_path(symbol, "1m", "2024-01"), text)
    # Variant G refuses a manifest without BTCUSDT's funding archive for an evaluation
    # month from 2020-01. The spec does not name funding archives, so the manifest lists
    # this one the way a re-fetch keeps them: through ``previous``.
    archive.add(funding_archive_path("BTCUSDT", "2024-01"), funding_text())
    funding = {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2024-01"}
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: dict(FILTERS),
        now=lambda: FIXED_NOW,
        previous={"files": [funding]},
    )
    write_manifest(work / "synth.manifest.json", manifest)


def set_aside(value: Any) -> Any:
    """``value`` without the identity keys, wherever they appear."""
    if isinstance(value, dict):
        return {k: set_aside(v) for k, v in value.items() if k not in IDENTITY_KEYS}
    if isinstance(value, list | tuple):
        return [set_aside(v) for v in value]
    return value


def document_sha256(document: Any) -> str:
    """SHA-256 of the document with the identity keys set aside."""
    blob = json.dumps(set_aside(document), sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


class StepTrace:
    """A SHA-256 over every step the replays of one run take, in order.

    After each step it takes in the report's fills (order id, side, price, quantity and
    fee), the report's exit reason and the account's resting orders (id, side, price and
    remaining quantity), each in the order the engine holds them. A step that fills
    nothing and rests nothing still counts. A new simulator starts a new section, so two
    replays of one step each differ from one replay of two.
    """

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._simulator: object | None = None
        self.steps = 0

    def record(self, simulator: object, account: Account, report: Mapping[str, Any]) -> None:
        if simulator is not self._simulator:
            self._simulator = simulator
            self._digest.update(b"replay\n")
        fills = ";".join(
            f"{f['order_id']},{f['side']},{f['price']},{f['quantity']},{f['fee']}"
            for f in report["fills"]
        )
        resting = ";".join(
            f"{o.order_id},{o.side},{o.price},{o.remaining}" for o in account.orders.values()
        )
        reason = report.get("exit_reason") or ""
        self._digest.update(f"{fills}|{reason}|{resting}\n".encode())
        self.steps += 1

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


@contextlib.contextmanager
def step_trace() -> Iterator[StepTrace]:
    """Wrap ``PaperSimulator.step`` so that every step taken inside the block is traced.
    The wrapper forwards whatever arguments it is given and finds the account among them
    by the name ``step`` gives it, so a change to ``step``'s other parameters, or to how a
    caller passes them, does not break the check. Renaming or removing the ``account``
    parameter still fails every traced step at once, with a ``KeyError``."""
    trace = StepTrace()
    original = PaperSimulator.step
    signature = inspect.signature(original)

    def step(self: PaperSimulator, *args: Any, **kwargs: Any) -> dict[str, Any]:
        report: dict[str, Any] = original(self, *args, **kwargs)
        trace.record(self, signature.bind(self, *args, **kwargs).arguments["account"], report)
        return report

    with mock.patch.object(PaperSimulator, "step", step):
        yield trace


def run_cli(work: Path, out: Path, flags: Sequence[str] = ()) -> dict[str, Any]:
    """The backtest CLI's ``run`` on the dataset in ``work``, in this process; returns the
    ``results.json`` document it wrote under ``out``."""
    argv = [
        "run",
        "--spec",
        str(work / "synth.toml"),
        "--config",
        str(CONFIG),
        "--data-dir",
        str(work / "data"),
        "--out",
        str(out),
        # One job runs inline, in this process, as the CLI's own in-process executor.
        "--jobs",
        "1",
        *flags,
    ]
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = backtest_cli.main(argv)
    if code != 0:
        raise RuntimeError(f"the CLI exited {code} on {' '.join(flags)}:\n{printed.getvalue()}")
    (written,) = out.rglob("results.json")
    document: dict[str, Any] = json.loads(written.read_text(encoding="utf-8"))
    return document


def variant_label(variant: str, structure: bool) -> str:
    return f"{variant}+V2" if structure else variant


def run_variant(work: Path, variant: str, *, structure: bool = False) -> dict[str, Any]:
    """Spec v1 variant ``variant`` on the dataset in ``work`` through ``run_job``,
    for all four path and gated cases. Returns the rows by
    ``<variant>-<path>-<gated|ungated>``, each without its ``variant`` key."""
    policy = backtest_jobs.variant_policy(variant, structure=structure)
    label = variant_label(variant, structure)
    spec, data = work / "synth.toml", work / "data"
    results: dict[str, Any] = {}
    for mode in PATH_MODES:
        for gated in (True, False):
            row = backtest_jobs.run_job(spec, CONFIG, data, "BTCUSDT", mode, gated, None, policy)
            row.pop("variant", None)
            results[f"{label}-{mode}-{'gated' if gated else 'ungated'}"] = row
    return results


@dataclass(frozen=True)
class Run:
    """One run of the check: a CLI run (``variant`` None) or a variant run, on a dataset."""

    name: str
    dataset: str
    flags: tuple[str, ...] = ()
    variant: str | None = None
    structure: bool = False

    def replay(self, work: Path) -> dict[str, Any]:
        """The run's output document, from a replay on the dataset in ``work``."""
        if self.variant is None:
            return run_cli(work, work / "out" / self.name, self.flags)
        return run_variant(work, self.variant, structure=self.structure)


def _cli_runs() -> list[Run]:
    return [
        Run("cli-up", "up", ("--trend-benchmark",)),
        Run("cli-down", "down", ("--trend-benchmark",)),
        Run("cli-nod", "nod"),
        Run("cli-up-structure", "up", ("--structure",)),
        Run("cli-down-structure", "down", ("--structure",)),
    ]


def _variant_runs() -> list[Run]:
    on_up = ("A", "B", "E", "F", "G", "H", "C+G", "C+H")
    runs = [Run(f"variant-{v}-up", "up", variant=v) for v in on_up]
    runs.append(Run("variant-C-down", "down", variant="C"))
    # The full stack is declared only with the V2 structure features.
    name = variant_label(FULL_STACK, True)
    runs.append(Run(f"variant-{name}-up", "up", variant=FULL_STACK, structure=True))
    return runs


RUNS = [*_cli_runs(), *_variant_runs()]


@dataclass(frozen=True)
class Outcome:
    """A run's output document, the SHA-256 of it and of its step trace, and its steps."""

    name: str
    document: dict[str, Any]
    sha256: str
    trace_sha256: str
    steps: int

    def entry(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "trace_sha256": self.trace_sha256, "steps": self.steps}


def execute(run: Run, work: Path) -> Outcome:
    """Replay ``run`` on the dataset in ``work`` under a step trace."""
    with step_trace() as trace:
        document = run.replay(work)
    if not trace.steps:
        raise RuntimeError(f"{run.name}: the step trace saw no step; it is not attached")
    return Outcome(run.name, document, document_sha256(document), trace.hexdigest(), trace.steps)


def outcomes(root: Path, runs: Sequence[Run] = RUNS, workers: int = 1) -> Iterator[Outcome]:
    """Build each dataset the runs need, in its own directory under ``root``, and yield
    each run's outcome, in order, as it finishes. With ``workers`` above 1 that many runs
    replay at once in worker processes; each outcome is the same either way."""
    for dataset in dict.fromkeys(run.dataset for run in runs):
        build_dataset(root / dataset, dataset)
    if workers <= 1:
        for run in runs:
            yield execute(run, root / run.dataset)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(runs))) as pool:
        futures = [pool.submit(execute, run, root / run.dataset) for run in runs]
        try:
            for future in futures:
                yield future.result()
        finally:
            for future in futures:
                future.cancel()


def load_baseline() -> dict[str, dict[str, Any]]:
    try:
        recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"no baseline at {BASELINE}: run `record` first") from None
    if recorded.get("format") != BASELINE_FORMAT:
        raise SystemExit(f"{BASELINE} is not format {BASELINE_FORMAT}")
    runs: dict[str, dict[str, Any]] = recorded["runs"]
    return runs


def record(workers: int) -> int:
    recorded: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="byte-identity-") as root:
        for outcome in outcomes(Path(root), workers=workers):
            recorded[outcome.name] = outcome.entry()
            print(f"{outcome.name} {outcome.sha256}", flush=True)
    baseline = {
        "format": BASELINE_FORMAT,
        # Informational: the check compares only the runs.
        "recorded_with": {"python": platform.python_version(), "platform": sys.platform},
        "runs": recorded,
    }
    BASELINE.write_bytes((json.dumps(baseline, indent=2) + "\n").encode())
    print(f"recorded {len(recorded)} runs in {BASELINE}")
    return 0


def differences(outcome: Outcome, expected: dict[str, Any] | None) -> list[str]:
    """What in ``outcome`` is not what the baseline recorded; empty when identical."""
    if expected is None:
        return ["not in the baseline"]
    return [
        f"{label} differs"
        for label, now, then in (
            ("output document", outcome.sha256, expected.get("sha256")),
            ("step trace", outcome.trace_sha256, expected.get("trace_sha256")),
            ("step count", outcome.steps, expected.get("steps")),
        )
        if now != then
    ]


def check(workers: int) -> int:
    baseline = load_baseline()
    same = True
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="byte-identity-") as root:
        for outcome in outcomes(Path(root), workers=workers):
            seen.add(outcome.name)
            problems = differences(outcome, baseline.get(outcome.name))
            same &= not problems
            verdict = "DIFFERENT" if problems else "IDENTICAL"
            print(f"{outcome.name} {outcome.sha256} {verdict}", flush=True)
            for problem in problems:
                print(f"  {outcome.name}: {problem}", file=sys.stderr, flush=True)
    for name in sorted(baseline.keys() - seen):  # recorded, but no longer a run of this script
        print(f"{name} - DIFFERENT")
        print(f"  {name}: not run by this script", file=sys.stderr)
        same = False
    print("ALL IDENTICAL" if same else "SOME DIFFER")
    return 0 if same else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "record"))
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="runs to replay at once (default 1: a run takes about 3 minutes on one core)",
    )
    args = parser.parse_args(argv)
    return check(args.jobs) if args.command == "check" else record(args.jobs)


if __name__ == "__main__":
    sys.exit(main())
