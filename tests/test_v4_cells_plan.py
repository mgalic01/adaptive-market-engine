"""The v4-cells workflow's plan (``scripts/v4_cells_plan.py``): the inputs it validates and the
matrix it builds, on synthetic inputs only.

The plan job reads the dispatcher's four inputs (the data run's id, the arms, the capitals and the
cost multiples). It refuses what is not a run's or an arm's, a capital's or a cost's, and writes the
validated id and the matrix of cells to ``$GITHUB_OUTPUT``. No test reads market data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from crypto_grid_bot.v4.engine.arms import ARMS, DIAGNOSTIC_ARMS, CellSpec, all_cells

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cells_plan  # noqa: E402
import v4_diagnose  # noqa: E402

ALL_ARMS = ",".join(DIAGNOSTIC_ARMS)
CELLS_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "v4-cells.yml"


def test_the_plan_allows_the_eight_diagnostic_arms_two_capitals_and_two_costs():
    # The matrix is at most 8 x 2 x 2 = 32 jobs, well inside GitHub's 256.
    assert len(DIAGNOSTIC_ARMS) == 8 and len(ARMS) == 12
    assert v4_cells_plan.CAPITAL_CHOICES == {"1000": 1000, "10000": 10000}
    assert v4_cells_plan.COST_CHOICES == {"1": 1, "2": 2}


def test_the_default_inputs_make_the_eight_arms_at_10000_and_1x():
    cells = v4_cells_plan.build_cells(ALL_ARMS, "10000", "1")
    assert [cell.cell_id for cell in cells] == [f"{arm}-10000-1x" for arm in DIAGNOSTIC_ARMS]


def test_every_diagnostic_arm_capital_and_cost_makes_the_32_cells_in_the_runs_order():
    cells = v4_cells_plan.build_cells(ALL_ARMS, "1000,10000", "1,2")
    assert cells == tuple(cell for cell in all_cells() if cell.arm in DIAGNOSTIC_ARMS)
    assert len(cells) == 32


def test_the_order_is_the_arms_order_then_capital_then_cost_whatever_the_input_order():
    cells = v4_cells_plan.build_cells("hold_btc,v4_main", "10000,1000", "2,1")
    # Arms in ARMS order (v4_main before hold_btc), then capital, then cost multiple.
    assert [cell.cell_id for cell in cells] == [
        "v4_main-1000-1x",
        "v4_main-1000-2x",
        "v4_main-10000-1x",
        "v4_main-10000-2x",
        "hold_btc-1000-1x",
        "hold_btc-1000-2x",
        "hold_btc-10000-1x",
        "hold_btc-10000-2x",
    ]


def test_spaces_around_the_commas_are_ignored():
    cells = v4_cells_plan.build_cells(" v4_main , hold_btc ", " 1000 , 10000 ", " 1 ")
    assert [cell.cell_id for cell in cells] == [
        "v4_main-1000-1x",
        "v4_main-10000-1x",
        "hold_btc-1000-1x",
        "hold_btc-10000-1x",
    ]


def test_the_matrix_is_one_compact_json_line_of_include_entries():
    cells = v4_cells_plan.build_cells("v4_main,hold_btc", "10000", "1,2")
    text = v4_cells_plan.matrix_json(cells)
    assert "\n" not in text and " " not in text
    assert json.loads(text) == {
        "include": [
            {"cell": "v4_main-10000-1x", "arm": "v4_main", "capital": 10000, "costs": 1},
            {"cell": "v4_main-10000-2x", "arm": "v4_main", "capital": 10000, "costs": 2},
            {"cell": "hold_btc-10000-1x", "arm": "hold_btc", "capital": 10000, "costs": 1},
            {"cell": "hold_btc-10000-2x", "arm": "hold_btc", "capital": 10000, "costs": 2},
        ]
    }


def test_every_matrix_entry_is_a_cell_the_cell_cli_accepts():
    for entry in json.loads(v4_cells_plan.matrix_json(all_cells()))["include"]:
        cell = CellSpec(entry["arm"], entry["capital"], entry["costs"])
        assert entry["cell"] == cell.cell_id


@pytest.mark.parametrize(
    "arms",
    [
        "",
        " ",
        "v4_mian",
        "V4_MAIN",
        "v4_main,",
        ",v4_main",
        "v4_main,,hold_btc",
        "v4_main,v4_main",
        "v4_main,unknown",
        "v4_main; echo injected",
        "v4_main\nhold_btc",
    ],
)
def test_unknown_or_malformed_arms_are_refused(arms):
    with pytest.raises(ValueError, match="arm"):
        v4_cells_plan.build_cells(arms, "10000", "1")


@pytest.mark.parametrize(
    "capitals",
    ["", "500", "5000", "100000", "1000,", "1000,1000", "10000.0", "1e4", "+1000", "01000"]
    + ["1_000", "-1000", "１０００", "one thousand", "1000\n10000"],
)
def test_capitals_other_than_1000_and_10000_are_refused(capitals):
    with pytest.raises(ValueError, match="capital"):
        v4_cells_plan.build_cells("v4_main", capitals, "1")


@pytest.mark.parametrize("costs", ["", "0", "3", "4", "1.0", "01", "2,2", "1,", "true", "x", "１"])
def test_costs_other_than_1_and_2_are_refused(costs):
    with pytest.raises(ValueError, match="cost"):
        v4_cells_plan.build_cells("v4_main", "10000", costs)


@pytest.mark.parametrize("text", ["1", "9", "11234567890", "98765432101234567890"])
def test_a_run_id_of_digits_is_kept(text):
    assert v4_cells_plan.check_run_id(text) == text


@pytest.mark.parametrize(
    "text",
    ["", "0", "01", "-1", "+1", "12a", " 12", "12 ", "12\n", "１２３", "²", "1" * 21]
    + ["1;echo injected", "../1", "$(id)", "1e3", "12.0"],
)
def test_a_run_id_that_is_not_plain_digits_is_refused(text):
    with pytest.raises(ValueError, match="run id"):
        v4_cells_plan.check_run_id(text)


def plan(
    tmp_path: Path, capsys, *, data_run="1234567890", arms=ALL_ARMS, capitals="10000", costs="1"
):
    output = tmp_path / "github_output"
    code = v4_cells_plan.main(
        [
            "--data-run",
            data_run,
            "--arms",
            arms,
            "--capitals",
            capitals,
            "--costs",
            costs,
            "--github-output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err, output


def test_main_writes_the_validated_id_the_matrix_and_the_cell_count(tmp_path, capsys):
    code, out, err, output = plan(tmp_path, capsys, arms="v4_main,hold_btc", costs="1,2")
    assert code == 0 and err == ""
    cells = v4_cells_plan.build_cells("v4_main,hold_btc", "10000", "1,2")
    ids = "v4_main-10000-1x,v4_main-10000-2x,hold_btc-10000-1x,hold_btc-10000-2x"
    assert [cell.cell_id for cell in cells] == ids.split(",")
    assert output.read_text(encoding="ascii") == (
        f"data_run=1234567890\nmatrix={v4_cells_plan.matrix_json(cells)}\ncells=4\ncell_ids={ids}\n"
    )
    assert out == "v4_cells_plan: 4 cells planned for data run 1234567890\n"


def test_the_cell_ids_are_what_the_diagnosis_takes_as_planned(tmp_path, capsys):
    """Codex P2 on #294: the diagnosis' --planned is the plan's cell_ids line, which it reads
    back as the matrix's cells, in the same order."""
    code, _, _, output = plan(tmp_path, capsys, capitals="1000,10000", costs="1,2")
    assert code == 0
    lines = dict(line.split("=", 1) for line in output.read_text(encoding="ascii").splitlines())
    matrix = [row["cell"] for row in json.loads(lines["matrix"])["include"]]
    order = {spec.cell_id: index for index, spec in enumerate(all_cells())}
    assert v4_diagnose.planned_cells(lines["cell_ids"], order) == matrix
    assert len(matrix) == int(lines["cells"]) == 32


def test_main_appends_to_the_output_file(tmp_path, capsys):
    output = tmp_path / "github_output"
    output.write_text("earlier=1\n", encoding="ascii")
    code, _, _, _ = plan(tmp_path, capsys)
    assert code == 0
    assert output.read_text(encoding="ascii").startswith("earlier=1\ndata_run=1234567890\n")


@pytest.mark.parametrize(
    "inputs",
    [
        {"data_run": "12 34"},
        {"data_run": "0"},
        {"arms": "v4_main,nope"},
        {"capitals": "5000"},
        {"costs": "3"},
        {"data_run": "1\n::error::injected"},
        {"arms": "v4_main\n::error::injected"},
    ],
)
def test_main_refuses_a_bad_input_and_writes_nothing(tmp_path, capsys, inputs):
    code, out, err, output = plan(tmp_path, capsys, **inputs)
    assert code == 1
    assert out == ""
    assert "refused" in err
    # A value is shown as its repr: one line, so it cannot start a workflow command.
    assert "\n::error::injected" not in err
    assert not output.exists()


@pytest.mark.parametrize(
    "arm", ["v4_btc200_shorts", "v4_confirm3", "hold_btc_trend", "v3_as_built"]
)
def test_the_plan_refuses_arms_outside_the_diagnostic_set(tmp_path, capsys, arm):
    """The four arms the registered run adds are real arms, but the cells workflow runs the
    diagnostic eight only (v4-d22: nobody sees the new arms' results before step 5)."""
    assert arm in ARMS and arm not in DIAGNOSTIC_ARMS
    for arms in (arm, f"v4_main,{arm}"):
        code, out, err, output = plan(tmp_path, capsys, arms=arms)
        assert code == 1
        assert out == ""
        assert f"unknown arm {arm!r}" in err and "refused" in err
        assert not output.exists()
    with pytest.raises(ValueError, match="arm"):
        v4_cells_plan.build_cells(arm, "10000", "1")
    # The workflow's default arms are exactly the diagnostic set, which the plan accepts.
    document = yaml.safe_load(CELLS_WORKFLOW.read_text(encoding="utf-8"))
    default = document[True]["workflow_dispatch"]["inputs"]["arms"]["default"]
    assert default == ",".join(DIAGNOSTIC_ARMS)
    assert len(v4_cells_plan.build_cells(default, "10000", "1")) == 8


def test_the_workflow_dispatch_defaults_are_a_plan_main_accepts(tmp_path, capsys):
    code, out, _, _ = plan(tmp_path, capsys)
    assert code == 0 and "8 cells planned" in out
