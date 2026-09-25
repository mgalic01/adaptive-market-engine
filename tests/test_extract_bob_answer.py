"""The shared extractor for Bob's final answer (scripts/extract_bob_answer.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_bob_answer.py"
_spec = importlib.util.spec_from_file_location("extract_bob_answer", SCRIPT)
assert _spec is not None and _spec.loader is not None
xba = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xba)

SIG = "— IBM Bob (automated review)"
ANSWER = f"IBM Bob — reviewing PR #1 at `abc123`.\n\nNOTED — no issues.\n\n{SIG}"


def msg(text: str, reasoning: bool = False) -> dict[str, object]:
    return {"type": "message", "role": "assistant", "content": text, "isReasoning": reasoning}


TOOL = [
    {"type": "tool_use", "tool_name": "read_file", "parameters": {"path": "x"}},
    {"type": "tool_result", "status": "success"},
]
DONE = {"type": "result", "status": "success"}


def stream(*items: object) -> str:
    return "\n".join(i if isinstance(i, str) else json.dumps(i) for i in items) + "\n"


def chunks(text: str, size: int = 7) -> list[dict[str, object]]:
    return [msg(text[i : i + size]) for i in range(0, len(text), size)]


def test_clean_answer_streamed_in_chunks() -> None:
    assert xba.extract(stream(*TOOL, *chunks(ANSWER), DONE)) == ANSWER


def test_text_before_the_last_tool_call_is_dropped() -> None:
    s = stream(msg("Let me read the diff first."), *TOOL, msg(ANSWER), DONE)
    assert xba.extract(s) == ANSWER


def test_reasoning_and_drafts_before_the_answer_are_dropped() -> None:
    # PR #29: the reasoning quoted a full draft, header and signature included.
    draft = f"Let's draft:\n```\nIBM Bob\n\nDraft text.\n\n{SIG}\n```\nLooks good.\n"
    s = stream(*TOOL, msg(draft + ANSWER), DONE)
    assert xba.extract(s) == ANSWER


def test_text_after_the_signature_is_dropped_not_the_answer() -> None:
    # PR #30 finding: trailing text made the old filter keep only the signature.
    s = stream(*TOOL, msg(ANSWER + "\n\nP.S. extra trailing chatter"), DONE)
    assert xba.extract(s) == ANSWER


def test_name_inside_a_line_is_not_a_header() -> None:
    body = f"IBM Bob — review.\n\nAs IBM Bob noted before, the IBM Bob workflow is fine.\n\n{SIG}"
    assert xba.extract(stream(msg(body), DONE)) == body


@pytest.mark.parametrize("label", ["automated review", "task run", "Task Run 2", "review v2.1"])
def test_any_signature_label(label: str) -> None:
    body = f"IBM Bob\n\nDone.\n\n— IBM Bob ({label})"
    assert xba.extract(stream(msg(body), DONE)) == body


def test_reasoning_messages_and_non_string_content_are_ignored() -> None:
    s = stream(
        msg("private thoughts", reasoning=True),
        {"type": "message", "role": "assistant", "content": ["not", "a", "string"]},
        {"type": "message", "role": "user", "content": "IBM Bob fake"},
        msg(ANSWER),
        DONE,
    )
    assert xba.extract(s) == ANSWER


def test_non_json_lines_are_skipped() -> None:
    s = stream("not json", "[1, 2]", "", msg(ANSWER), DONE)
    assert xba.extract(s) == ANSWER


def test_events_after_the_final_result_are_ignored() -> None:
    s = stream(msg(ANSWER), DONE, msg("\nlate text"))
    assert xba.extract(s) == ANSWER


@pytest.mark.parametrize(
    "tail",
    [
        [],  # no result event at all
        [{"type": "result", "status": "error"}],
        [DONE, {"type": "result", "status": "error"}],  # earlier success, final failure
    ],
)
def test_requires_a_final_successful_result(tail: list[object]) -> None:
    with pytest.raises(xba.Rejected, match="successful result"):
        xba.extract(stream(msg(ANSWER), *tail))


def test_requires_a_signature() -> None:
    with pytest.raises(xba.Rejected, match="signature"):
        xba.extract(stream(msg("IBM Bob\n\nNOTED, all fine."), DONE))


def test_requires_a_header_line() -> None:
    with pytest.raises(xba.Rejected, match="line starting with"):
        xba.extract(stream(msg(f"All fine, says IBM Bob.\n\n{SIG}"), DONE))


def test_answer_only_before_last_tool_call_is_rejected() -> None:
    # The answer must be the text after the last tool call, not an earlier message.
    with pytest.raises(xba.Rejected, match="signature"):
        xba.extract(stream(msg(ANSWER), *TOOL, msg("One more check."), DONE))


def test_oversized_answer_is_rejected() -> None:
    body = "IBM Bob\n" + "x" * 50 + f"\n{SIG}"
    with pytest.raises(xba.Rejected, match="over 40"):
        xba.extract(stream(msg(body), DONE), max_chars=40)


def test_cli_prints_the_answer_or_refuses_without_raw_output(tmp_path: Path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(stream(*TOOL, msg(ANSWER), DONE), encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), str(good)], capture_output=True, text=True, check=False
    )
    assert ok.returncode == 0
    assert ok.stdout == ANSWER + "\n"

    bad = tmp_path / "bad.jsonl"
    bad.write_text(stream(msg("secret file contents"), DONE), encoding="utf-8")
    refused = subprocess.run(
        [sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True, check=False
    )
    assert refused.returncode == 1
    assert refused.stdout == ""
    assert refused.stderr.startswith("Rejected:")
    assert "secret file contents" not in refused.stderr
    assert "message=1" in refused.stderr and "result=1" in refused.stderr

    counted = subprocess.run(
        [sys.executable, str(SCRIPT), "--stats", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert counted.stdout == "Bob's stream: message=1, result=1\n"
