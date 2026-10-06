"""The stage-1 identity check (scripts/stage1_identity.py), on synthetic results.json files.

Stage 1's real files are not in the repository, so every test builds small documents with
the layout the backtest CLI writes (``backtest/__main__.py``: ``policy`` only for a
non-V0 run, ``code_commit`` and ``code_sha256`` only for a recorded run, both intrabar
paths and both gate settings as rows of one file) and checks the script's verdicts, its
exit code and what it prints.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from crypto_grid_bot.backtest.features import FEATURE_VERSION, STRUCTURE_FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import variant_policy
from crypto_grid_bot.backtest.replay import PATH_MODES
from crypto_grid_bot.simulation.runner import FULL_STACK

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage1_identity.py"
sys.path.insert(0, str(SCRIPT.parent))

import stage1_identity  # noqa: E402

Document = dict[str, Any]

DATASETS = ("practice-2022", "verify-2024h1")
# Stage 1's inputs per dataset: V0 (no policy key), variants, and the V2 structure runs.
INPUTS = [(None, False), ("A", False), ("C+G", False), (None, True), (FULL_STACK, True)]
# The six fields spec v1 section 5 rule 1 adds; the controller's ruling names them.
MASK_FIELDS = (
    "masked_hours",
    "days_skipped_for_masks",
    "fills_after_masked_span",
    "comparison_mask",
    "daily_days_skipped_for_masks",
    "tick_limit_quotes",
)


def document(
    dataset: str, variant: str | None = None, structure: bool = False, *, commit: str = "a" * 40
) -> Document:
    """A results.json as the CLI writes it. V0 without a recorded commit has neither a
    ``policy`` nor a fingerprint, as stage 1's V0 files do."""
    policy = variant_policy(variant, structure=structure)
    # The CLI writes the identity with ``default=str`` (a cap is a Decimal): as plain JSON.
    identity = json.loads(json.dumps(policy.identity(), default=str)) if policy else None
    version = STRUCTURE_FEATURE_VERSION if structure else FEATURE_VERSION
    rows: list[Document] = []
    for number, mode in enumerate(PATH_MODES):
        for gated in (True, False):
            # A structure run's ungated rows are V0's baseline, with V0's label.
            label = f"gated grid ({version})" if gated else "ungated grid baseline"
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "path_mode": mode,
                    "strategy": label,
                    "return_pct": 1.0 + number + gated,
                    "fees": "12.5",
                    "buys": 40 + number,
                    "hourly_equity": [10000.0, 10001.5, 10002.25],
                }
            )
    return {
        "dataset": dataset,
        "purpose": "stage 1",
        "feature_version": version,
        "engine_version": "engine-v1",
        "manifest_created_at": "2026-10-05T00:00:00+00:00",
        "spec_sha256": "s" * 64,
        "manifest_sha256": "m" * 64,
        "config_sha256": "c" * 64,
        "integrity_rules": {"version": "drift-tolerance-v1"},
        "fees": {"maker": "0.001", "taker": "0.001"},
        **({"policy": identity} if identity is not None else {}),
        **({"code_commit": commit, "code_sha256": "d" * 64} if identity is not None else {}),
        "valid": True,
        "failures": [],
        "hourly_cross_checks": [{"symbol": "BTCUSDT", "hours_missing": 0}],
        "results": rows,
    }


def stage1_documents() -> list[Document]:
    return [document(d, variant, structure) for d in DATASETS for variant, structure in INPUTS]


def rerun_of(documents: list[Document]) -> list[Document]:
    """The same documents from a later build: only the fingerprints move."""
    moved = copy.deepcopy(documents)
    for doc in moved:
        doc["code_commit"] = "b" * 40
        doc["code_sha256"] = "e" * 64
    return moved


def write_side(root: Path, documents: list[Document], *, nested: bool = False) -> Path:
    """One results.json per document under ``root``; ``nested`` lays them out the way a
    downloaded workflow artifact does, ``dataset/stamp/results.json``."""
    for number, doc in enumerate(documents):
        stamp = f"2026100{number}T000000Z"
        where = root / doc["dataset"] / stamp if nested else root / f"r{number}"
        where.mkdir(parents=True)
        (where / "results.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return root


class Result(NamedTuple):
    code: int
    out: str
    err: str

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()

    @property
    def everything(self) -> str:
        return f"{self.out}{self.err}"


def run_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Result:
    """The script on ``tmp_path``'s ``stage1`` and ``rerun`` directories."""
    code = stage1_identity.main([str(tmp_path / "stage1"), str(tmp_path / "rerun")])
    captured = capsys.readouterr()
    return Result(code, captured.out, captured.err)


def check(
    tmp_path: Path,
    stage1: list[Document],
    rerun: list[Document],
    capsys: pytest.CaptureFixture[str],
) -> Result:
    """Write the two sides, one results.json per document, and run the script on them."""
    write_side(tmp_path / "stage1", stage1, nested=True)
    write_side(tmp_path / "rerun", rerun)
    return run_main(tmp_path, capsys)


def key(doc: Document) -> str:
    return str(stage1_identity.key_of(doc))


def verdicts(result: Result) -> list[str]:
    """The per-pair lines: each starts with the pair's key, which holds `` | ``."""
    return [line for line in result.lines if " | " in line and not line.startswith(" ")]


def block(result: Result, pair: str) -> list[str]:
    """The lines that follow ``pair``'s ``DIFFERENT`` line, up to the next unindented one."""
    lines = result.lines
    start = lines.index(f"{pair} DIFFERENT") + 1
    stop = next((n for n in range(start, len(lines)) if not lines[n].startswith("  ")), None)
    return lines[start:stop]


def target(rerun: list[Document]) -> Document:
    """The re-run document the difference tests change: V2 on `verify-2024h1`."""
    return next(
        d for d in rerun if d["dataset"] == "verify-2024h1" and "structure" in d.get("policy", {})
    )


# --- identical apart from the fingerprints --------------------------------------------


def test_identical_apart_from_fingerprints_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    # The V0 files carry no fingerprint at stage 1; the re-run's may carry them.
    assert "code_commit" not in stage1[0] and "code_commit" in rerun[0]
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 0, result.everything
    pairs = verdicts(result)
    assert len(pairs) == len(DATASETS) * len(INPUTS) == 10
    assert all(line.endswith(" IDENTICAL") for line in pairs)
    assert {line.rsplit(" ", 1)[0] for line in pairs} == {key(d) for d in stage1}
    assert result.lines[-1] == "ALL IDENTICAL"
    assert result.lines[0] == "10 results.json files on each side, one per key"
    assert result.err == ""


def test_pairs_are_matched_by_key_not_by_file_name_or_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    rerun.reverse()  # written under other names, in the other order
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 0, result.everything
    assert result.lines[-1] == "ALL IDENTICAL"


def test_dict_key_order_is_not_a_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    for doc in rerun:
        doc["results"] = [dict(reversed(list(row.items()))) for row in doc["results"]]
    rerun = [dict(reversed(list(doc.items()))) for doc in rerun]
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 0, result.everything


# --- any other difference fails -------------------------------------------------------


def edit_metric(doc: Document) -> None:
    doc["results"][1]["return_pct"] += 1e-9


def edit_trade_count(doc: Document) -> None:
    doc["results"][2]["buys"] += 1


def edit_equity_curve(doc: Document) -> None:
    doc["results"][3]["hourly_equity"][2] = 10002.26


def edit_row_order(doc: Document) -> None:
    doc["results"].reverse()


def drop_a_row(doc: Document) -> None:
    doc["results"].pop()


def add_a_field(doc: Document) -> None:
    doc["results"][0]["new_field"] = 0


def add_a_top_level_field(doc: Document) -> None:
    doc["new_field"] = []


def drop_a_field(doc: Document) -> None:
    del doc["results"][0]["fees"]


def rename_a_field(doc: Document) -> None:
    doc["results"][0]["fees_paid"] = doc["results"][0].pop("fees")


def int_for_float(doc: Document) -> None:
    doc["results"][0]["return_pct"] = int(doc["results"][0]["return_pct"])


def bool_for_int(doc: Document) -> None:
    doc["results"][0]["buys"] = True


def edit_strategy_label(doc: Document) -> None:
    doc["results"][1]["strategy"] += " (renamed)"


def flip_valid(doc: Document) -> None:
    doc["valid"] = False


def add_a_failure(doc: Document) -> None:
    doc["failures"].append("something failed")


def edit_cross_check(doc: Document) -> None:
    doc["hourly_cross_checks"][0]["hours_missing"] = 1


def edit_spec_hash(doc: Document) -> None:
    doc["spec_sha256"] = "0" * 64


def edit_manifest_hash(doc: Document) -> None:
    doc["manifest_sha256"] = "0" * 64


def edit_config_hash(doc: Document) -> None:
    doc["config_sha256"] = "0" * 64


def edit_engine_version(doc: Document) -> None:
    doc["engine_version"] = "engine-v2"


def edit_nested_fingerprint(doc: Document) -> None:
    # Only the top-level provenance fields may differ; a row's own field is a result.
    doc["results"][0]["code_commit"] = "f" * 40


@pytest.mark.parametrize(
    ("edit", "where"),
    [
        (edit_metric, "results[1].return_pct"),
        (edit_trade_count, "results[2].buys"),
        (edit_equity_curve, "results[3].hourly_equity[2]"),
        (edit_row_order, "results[0].path_mode"),
        (drop_a_row, "results"),
        (add_a_field, "results[0].new_field"),
        (add_a_top_level_field, "new_field"),
        (drop_a_field, "results[0].fees"),
        (rename_a_field, "results[0].fees_paid"),
        (int_for_float, "results[0].return_pct"),
        (bool_for_int, "results[0].buys"),
        (edit_strategy_label, "results[1].strategy"),
        (flip_valid, "valid"),
        (add_a_failure, "failures"),
        (edit_cross_check, "hourly_cross_checks[0].hours_missing"),
        (edit_spec_hash, "spec_sha256"),
        (edit_manifest_hash, "manifest_sha256"),
        (edit_config_hash, "config_sha256"),
        (edit_engine_version, "engine_version"),
        (edit_nested_fingerprint, "results[0].code_commit"),
    ],
)
def test_any_other_difference_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], edit: Any, where: str
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    changed = target(rerun)
    edit(changed)
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 1, result.everything
    pairs = verdicts(result)
    assert len(pairs) == 10  # every pair is compared and reported, not only the first
    assert f"{key(changed)} DIFFERENT" in pairs
    assert sum(line.endswith(" IDENTICAL") for line in pairs) == 9
    # The difference is named under its own pair's line.
    assert any(line.startswith(f"  {where}:") for line in block(result, key(changed)))
    assert result.lines[-1] == "SOME DIFFER"


def test_a_wide_difference_is_summarised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    changed = target(rerun)
    before = next(d for d in stage1 if key(d) == key(changed))
    before["results"][0]["hourly_equity"] = [float(n) for n in range(100)]
    changed["results"][0]["hourly_equity"] = [float(n + 1) for n in range(100)]
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 1
    shown = block(result, key(changed))
    # All 100 values differ; a screenful is shown and the rest is counted.
    assert stage1_identity.MAX_SHOWN == 10
    assert len(shown) == stage1_identity.MAX_SHOWN + 1
    assert shown[0].startswith("  results[0].hourly_equity[0]:")
    assert shown[-1] == "  and 90 more"


# --- a new mask field fails -----------------------------------------------------------

MASK_VALUES: dict[str, Any] = {name: 0 for name in MASK_FIELDS} | {"comparison_mask": {}}


def at_top_level(doc: Document, name: str) -> str:
    doc[name] = MASK_VALUES[name]
    return name


def in_a_row(doc: Document, name: str) -> str:
    doc["results"][1][name] = MASK_VALUES[name]
    return f"results[1].{name}"


def in_a_cross_check(doc: Document, name: str) -> str:
    doc["hourly_cross_checks"][0][name] = MASK_VALUES[name]
    return f"hourly_cross_checks[0].{name}"


def test_the_mask_fields_are_the_six_the_ruling_names() -> None:
    assert set(stage1_identity.MASK_FIELDS) == set(MASK_FIELDS)


@pytest.mark.parametrize("place", [at_top_level, in_a_row, in_a_cross_check])
@pytest.mark.parametrize("name", MASK_FIELDS)
def test_a_new_mask_field_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, place: Any
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    changed = target(rerun)
    where = place(changed, name)  # empty or zero: still a new field
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 1, result.everything
    assert f"{key(changed)} DIFFERENT" in verdicts(result)
    # Reported as a mask field alone, not also as a field that is only in the re-run.
    assert block(result, key(changed)) == [f"  new mask field {where}"]
    assert result.lines[-1] == "SOME DIFFER"


def test_a_mask_field_in_the_stage_1_file_fails_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stage 1 predates the fields, so a directory that holds one is not stage 1's, even
    when the re-run holds the same field with the same value."""
    stage1 = stage1_documents()
    for doc in stage1:
        doc["results"][0]["masked_hours"] = 0
    result = check(tmp_path, stage1, rerun_of(stage1), capsys)
    assert result.code == 1, result.everything
    assert all(line.endswith(" DIFFERENT") for line in verdicts(result))
    assert block(result, key(stage1[0])) == [
        "  mask field results[0].masked_hours in stage 1, which predates them",
        "  new mask field results[0].masked_hours",
    ]


# --- the inventories must match before anything is compared ---------------------------


def lost_from_rerun(stage1: list[Document], rerun: list[Document]) -> list[str]:
    return [f"missing from the re-run: {key(rerun.pop(3))}"]


def extra_in_rerun(stage1: list[Document], rerun: list[Document]) -> list[str]:
    return [f"extra in the re-run: {key(stage1.pop(3))}"]


def duplicate_in_stage1(stage1: list[Document], rerun: list[Document]) -> list[str]:
    stage1.append(copy.deepcopy(stage1[4]))
    return [f"two files with one key in stage 1: {key(stage1[4])}"]


def duplicate_in_rerun(stage1: list[Document], rerun: list[Document]) -> list[str]:
    rerun.append(copy.deepcopy(rerun[4]))
    return [f"two files with one key in the re-run: {key(rerun[4])}"]


def one_lost_and_one_extra(stage1: list[Document], rerun: list[Document]) -> list[str]:
    return [
        f"missing from the re-run: {key(rerun.pop(0))}",
        f"extra in the re-run: {key(stage1.pop(9))}",
    ]


def other_policy(stage1: list[Document], rerun: list[Document]) -> list[str]:
    """Same count, same dataset, but the re-run's policy is not the stage-1 policy."""
    old = key(rerun[1])
    rerun[1]["policy"] = {**rerun[1]["policy"], "recovery_frames": 3}
    return [f"missing from the re-run: {old}", f"extra in the re-run: {key(rerun[1])}"]


def other_structure_label(stage1: list[Document], rerun: list[Document]) -> list[str]:
    """The structure flag is read from the rows' labels, so a re-run whose rows carry
    V0's labels under V2's policy is not V2's file."""
    changed = next(d for d in rerun if "structure" in d.get("policy", {}))
    old = key(changed)
    for row in changed["results"]:
        row["strategy"] = row["strategy"].replace(f"({STRUCTURE_FEATURE_VERSION})", "(v0)")
    return [f"missing from the re-run: {old}", f"extra in the re-run: {key(changed)}"]


@pytest.mark.parametrize(
    "make",
    [
        lost_from_rerun,
        extra_in_rerun,
        duplicate_in_stage1,
        duplicate_in_rerun,
        one_lost_and_one_extra,
        other_policy,
        other_structure_label,
    ],
)
def test_missing_extra_or_duplicate_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make: Any
) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    # Files that remain also differ, so a check that compared them would say so.
    rerun[0]["results"][0]["buys"] += 1
    expected = make(stage1, rerun)
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 1, result.everything
    for line in expected:
        assert any(shown.startswith(f"  {line}") for shown in result.err.splitlines()), line
    assert len(result.err.splitlines()) == len(expected)  # nothing else is reported
    # Nothing was compared: no pair is reported, as identical or as different.
    assert result.lines == ["INVENTORY DIFFERS"]


def test_a_duplicate_names_both_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage1 = stage1_documents()
    rerun = rerun_of(stage1)
    rerun.append(copy.deepcopy(rerun[0]))
    result = check(tmp_path, stage1, rerun, capsys)
    assert result.code == 1
    assert str(tmp_path / "rerun" / "r0" / "results.json") in result.err
    assert str(tmp_path / "rerun" / "r10" / "results.json") in result.err


# --- an inventory that cannot be read fails, and so does an empty one ------------------


def test_an_empty_side_fails_even_when_both_are_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "stage1").mkdir()
    (tmp_path / "rerun").mkdir()
    result = run_main(tmp_path, capsys)
    assert result.code == 1
    assert result.err.splitlines() == [
        f"  stage 1: no results.json under {tmp_path / 'stage1'}",
        f"  the re-run: no results.json under {tmp_path / 'rerun'}",
    ]
    assert result.lines == ["INVENTORY DIFFERS"]


def test_a_side_with_no_file_is_not_a_list_of_missing_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_side(tmp_path / "stage1", stage1_documents())
    (tmp_path / "rerun").mkdir()
    result = run_main(tmp_path, capsys)
    assert result.code == 1
    assert result.err.splitlines() == [f"  the re-run: no results.json under {tmp_path / 'rerun'}"]
    assert result.lines == ["INVENTORY DIFFERS"]


def test_a_missing_directory_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_side(tmp_path / "stage1", stage1_documents())
    result = run_main(tmp_path, capsys)  # there is no `rerun` directory
    assert result.code == 1
    assert result.err.splitlines() == [f"  the re-run: {tmp_path / 'rerun'} is not a directory"]
    assert result.lines == ["INVENTORY DIFFERS"]


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("{not json", "Expecting"),
        ("[1, 2]", "not a results.json"),
        ('{"purpose": "no dataset", "results": []}', "not a results.json"),
        ('{"dataset": "d"}', "not a results.json"),
        ('{"dataset": "d", "results": [{"symbol": "BTCUSDT"}]}', "not a results.json"),
        ('{"dataset": 7, "results": []}', "not a results.json"),
    ],
)
def test_a_file_that_cannot_be_keyed_fails_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, why: str
) -> None:
    stage1 = stage1_documents()
    write_side(tmp_path / "stage1", stage1)
    write_side(tmp_path / "rerun", rerun_of(stage1))
    broken = tmp_path / "rerun" / "r2" / "results.json"
    broken.write_text(text, encoding="utf-8")
    result = run_main(tmp_path, capsys)
    assert result.code == 1
    first = result.err.splitlines()[0]
    assert first.startswith(f"  the re-run: {broken}: ") and why in first
    assert result.lines == ["INVENTORY DIFFERS"]


# --- the key ----------------------------------------------------------------------------


def test_the_key_is_dataset_policy_and_the_structure_flag_of_the_labels() -> None:
    v0 = document("verify-2024h1")
    assert "policy" not in v0
    assert stage1_identity.key_of(v0) == ("verify-2024h1", "V0", False)
    a = document("verify-2024h1", "A")
    assert stage1_identity.key_of(a).policy == json.dumps(
        a["policy"], sort_keys=True, separators=(",", ":")
    )
    v2 = document("verify-2024h1", None, True)
    assert stage1_identity.key_of(v2).policy != "V0"
    # A structure run's ungated rows carry V0's label; its gated rows set the flag.
    assert any(row["strategy"] == "ungated grid baseline" for row in v2["results"])
    assert stage1_identity.key_of(v2).structure is True
    # With no policy key at all, a structure label alone still sets the flag.
    labelled = document("verify-2024h1")
    labelled["results"][0]["strategy"] = f"gated grid ({STRUCTURE_FEATURE_VERSION})"
    assert stage1_identity.key_of(labelled) == ("verify-2024h1", "V0", True)


def test_every_input_of_a_dataset_has_its_own_key() -> None:
    keys = {stage1_identity.key_of(d) for d in stage1_documents()}
    assert len(keys) == len(DATASETS) * len(INPUTS)


def test_the_key_names_the_dataset_policy_and_flag() -> None:
    assert str(stage1_identity.key_of(document("practice-2022"))) == (
        "practice-2022 | V0 | structure=False"
    )
    assert str(stage1_identity.key_of(document("practice-2022", "A"))).startswith(
        'practice-2022 | {"'
    )


# --- run as a script --------------------------------------------------------------------


def test_the_script_runs_as_documented(tmp_path: Path) -> None:
    stage1 = stage1_documents()
    write_side(tmp_path / "stage1", stage1, nested=True)
    write_side(tmp_path / "rerun", rerun_of(stage1))
    command = [sys.executable, str(SCRIPT), str(tmp_path / "stage1"), str(tmp_path / "rerun")]
    same = subprocess.run(command, capture_output=True, text=True, check=False)
    assert same.returncode == 0, same.stderr
    assert same.stdout.splitlines()[-1] == "ALL IDENTICAL"
    rerun_doc = tmp_path / "rerun" / "r0" / "results.json"
    changed = json.loads(rerun_doc.read_text(encoding="utf-8"))
    changed["valid"] = False
    rerun_doc.write_text(json.dumps(changed), encoding="utf-8")
    different = subprocess.run(command, capture_output=True, text=True, check=False)
    assert different.returncode == 1
    assert different.stdout.splitlines()[-1] == "SOME DIFFER"
    assert "  valid: true in stage 1, false in the re-run" in different.stdout
