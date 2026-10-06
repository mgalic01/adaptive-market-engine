"""The two stage-2 dataset specs are spec v1 section 4's frozen definitions, and every
committed dataset spec can be dispatched from the backtest workflow."""

from __future__ import annotations

import calendar
import os
import shutil
import subprocess  # nosec B404: runs the workflow's own guard step and git in a temp repo
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from crypto_grid_bot.backtest.dataset import DatasetSpec, load_spec

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "config/datasets"
WORKFLOW = ROOT / ".github/workflows/backtest.yml"

# Spec v1 section 4: the pairs, the proxy, the basket and the pricing, the same for both.
TRADED = ("BTCUSDT", "ETHUSDT", "XRPUSDT")
BASKET = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "TRXUSDT",
)


@dataclass(frozen=True)
class Window:
    """One column of section 4's stage-2 tables."""

    warmup_start: str
    daily_warmup_start: str
    start: str
    end: str
    evaluation_days: int
    daily_bars_before_start: int
    # (symbol, from inclusive, to exclusive), each a whole UTC hour.
    exclusions: tuple[tuple[str, str, str], ...]
    # Kline files `required()` lists, by interval.
    files: dict[str, int]


SCORED = Window(
    warmup_start="2018-06",
    daily_warmup_start="2018-06",
    start="2019-01",
    end="2024-12",
    evaluation_days=2192,
    daily_bars_before_start=214,
    exclusions=(
        ("SOLUSDT", "2018-06-01T00:00Z", "2020-08-11T06:00Z"),
        ("DOGEUSDT", "2018-06-01T00:00Z", "2019-07-05T12:00Z"),
        ("LINKUSDT", "2018-06-01T00:00Z", "2019-01-16T10:00Z"),
        ("TRXUSDT", "2018-06-01T00:00Z", "2018-06-11T11:00Z"),
        ("DOGEUSDT", "2020-02-01T00:00Z", "2020-03-01T00:00Z"),
    ),
    # 3 pairs x 72 months of 1m; 9 symbols x 79 months of 1h; 3 x 79 months of 1d.
    files={"1m": 216, "1h": 711, "1d": 237},
)
REPORTED = Window(
    warmup_start="2019-01",
    daily_warmup_start="2018-07",
    start="2019-07",
    end="2024-12",
    evaluation_days=2011,
    daily_bars_before_start=365,
    exclusions=(
        ("SOLUSDT", "2019-01-01T00:00Z", "2020-08-11T06:00Z"),
        ("DOGEUSDT", "2019-01-01T00:00Z", "2019-07-05T12:00Z"),
        ("LINKUSDT", "2019-01-01T00:00Z", "2019-01-16T10:00Z"),
        ("DOGEUSDT", "2020-02-01T00:00Z", "2020-03-01T00:00Z"),
    ),
    # 3 pairs x 66 months of 1m; 9 symbols x 72 months of 1h; 3 x 78 months of 1d.
    files={"1m": 198, "1h": 648, "1d": 234},
)


def hour(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%dT%H:%MZ")


def month_start(month: str) -> date:
    return date(int(month[:4]), int(month[5:]), 1)


def check_window(name: str, expected: Window) -> DatasetSpec:
    spec = load_spec(DATASETS / f"{name}.toml")
    assert spec.name == name
    assert spec.traded == TRADED
    assert spec.market_proxy == "BTCUSDT"
    assert spec.breadth_basket == BASKET
    assert spec.warmup_start == expected.warmup_start
    assert spec.daily_warmup_start == expected.daily_warmup_start
    assert spec.start == expected.start
    assert spec.end == expected.end
    assert spec.initial_quote == Decimal("100")
    assert spec.fee_rate == Decimal("0.001")
    assert spec.slippage_rate == Decimal("0.0005")
    assert spec.participation == Decimal("0.10")
    assert spec.assumed_spread_pct == Decimal("0.05")
    # Section 4's computed rows, from the spec's own months.
    last_day = calendar.monthrange(int(spec.end[:4]), int(spec.end[5:]))[1]
    last = date(int(spec.end[:4]), int(spec.end[5:]), last_day)
    assert (last - month_start(spec.start)).days + 1 == expected.evaluation_days
    assert (month_start(spec.start) - month_start(expected.daily_warmup_start)).days == (
        expected.daily_bars_before_start
    )
    found = sorted((x.symbol, hour(x.start_ms), hour(x.end_ms)) for x in spec.basket_exclusions)
    assert found == sorted(expected.exclusions)
    # Section 4 gives each exclusion's reason: a listing, or section 5 rule 5.
    for exclusion in spec.basket_exclusions:
        rule_5 = exclusion.symbol == "DOGEUSDT" and hour(exclusion.start_ms).startswith("2020-02")
        assert ("rule 5" if rule_5 else "listing") in exclusion.reason
    files = spec.required()
    assert len(set(files)) == len(files)
    assert Counter(interval for _, interval, _ in files) == expected.files
    return spec


def test_full_range_2017_2024_matches_spec_v1_section_4() -> None:
    spec = check_window("full-range-2017-2024", SCORED)
    assert len(spec.required()) == 1164


def test_full_range_2019_2024_matches_spec_v1_section_4() -> None:
    check_window("full-range-2019-2024", REPORTED)


def test_every_dataset_spec_is_a_workflow_choice() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    options = workflow[True]["workflow_dispatch"]["inputs"]["spec"]["options"]
    assert len(options) == len(set(options))
    assert set(options) == {path.stem for path in DATASETS.glob("*.toml")}


def _guard_step() -> tuple[list[str], str]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["run"]["steps"]
    names = [step.get("name", "") for step in steps]
    guard = next(s for s in steps if s.get("name", "").startswith("Require a committed manifest"))
    return names, guard["run"]


def _run_guard(script: str, repo: Path, spec: str) -> int:
    shell = shutil.which("bash")
    assert shell, "bash (Git Bash on Windows) is required to run the workflow step"
    env = {**os.environ, "SPEC": spec}
    return subprocess.run(  # nosec B603: a fixed shell running the workflow's own step
        [shell, "-c", script], cwd=repo, env=env, capture_output=True, check=False
    ).returncode


def test_a_registered_long_window_needs_its_committed_manifest_before_any_fetch(
    tmp_path: Path,
) -> None:
    """Codex's P2 on #183: before Task 9 commits a full-range manifest, the fetch step
    would write an untracked one and the run would use it. The guard stops a full-range
    dispatch first; an exploratory window without a committed manifest still runs."""
    names, script = _guard_step()
    guard = next(i for i, name in enumerate(names) if name.startswith("Require a committed"))
    assert guard < names.index("Fetch data")

    git = shutil.which("git")
    assert git
    subprocess.run([git, "init", "-q"], cwd=tmp_path, check=True)  # nosec B603
    manifests = tmp_path / "config" / "datasets"
    manifests.mkdir(parents=True)
    for name in ("full-range-2017-2024", "full-range-2019-2024"):
        assert (DATASETS / f"{name}.toml").is_file()
        assert _run_guard(script, tmp_path, name) == 1  # no manifest at all

    scored = manifests / "full-range-2017-2024.manifest.json"
    scored.write_text("{}\n", encoding="utf-8")
    assert _run_guard(script, tmp_path, "full-range-2017-2024") == 1  # written, not committed
    subprocess.run(  # nosec B603
        [git, "add", str(scored.relative_to(tmp_path))], cwd=tmp_path, check=True
    )
    assert _run_guard(script, tmp_path, "full-range-2017-2024") == 0
    assert _run_guard(script, tmp_path, "full-range-2019-2024") == 1
    assert _run_guard(script, tmp_path, "long-recovery-2023-2024") == 0  # exploratory
