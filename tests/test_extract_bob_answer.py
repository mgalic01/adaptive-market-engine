"""The shared extractor for Bob's final answer (scripts/extract_bob_answer.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
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


@pytest.mark.parametrize(
    "header", ["**IBM Bob**", "## IBM Bob", "> IBM Bob", "_IBM Bob_", "### **IBM Bob"]
)
def test_markdown_decorated_header_is_accepted(header: str) -> None:
    # PR #42: an answer opening with a bold or heading name was refused as having no header.
    body = f"{header} review of PR #42.\n\nNOTED.\n\n{SIG}"
    assert xba.extract(stream(*TOOL, msg(body), DONE)) == body


def test_header_search_is_linear_on_long_marker_runs() -> None:
    # PR #42 review: a nested-quantifier pattern hung on a long run of "#" or "*".
    text = ("#" * 200 + "x\n" + "*_" * 100 + "\n") * 200
    started = time.perf_counter()
    assert xba.HEADER.search(text) is None
    assert time.perf_counter() - started < 1.0


def test_handoff_heading_before_the_header_is_dropped() -> None:
    body = f"IBM Bob review.\n\nNOTED.\n\n{SIG}"
    assert xba.extract(stream(msg(f"**Bob → Claude handoff**\n\n{body}"), DONE)) == body


def test_header_before_a_final_tool_call_is_kept() -> None:
    # PR #42/#43 refusals: Bob wrote his header, read one more file, then finished.
    s = stream(
        *TOOL,
        msg("IBM Bob review of PR #43.\nChecking one file."),
        *TOOL,
        msg(f"NOTED.\n\n{SIG}"),
        DONE,
    )
    assert xba.extract(s) == f"IBM Bob review of PR #43.\nChecking one file.\nNOTED.\n\n{SIG}"


def test_a_signed_draft_before_the_last_tool_call_is_never_pulled_in() -> None:
    draft = f"IBM Bob draft.\n\n{SIG}"
    s = stream(msg(draft), *TOOL, msg(f"NOTED.\n\n{SIG}"), DONE)
    with pytest.raises(xba.Rejected, match="no line starting with"):
        xba.extract(s)


def test_a_signature_quoted_inside_a_sentence_is_not_a_boundary() -> None:
    body = (
        "IBM Bob review.\n\nThe format ends with '— IBM Bob (automated review)' as the "
        f"prompt says.\n\nNOTED.\n\n{SIG}"
    )
    assert xba.extract(stream(*TOOL, msg(body), DONE)) == body


def test_signature_at_the_end_of_a_text_line_is_accepted() -> None:
    body = "IBM Bob review.\n\nNOTED. — IBM Bob (automated review)"
    assert xba.extract(stream(*TOOL, msg(body), DONE)) == body


def test_refusal_reports_structure_never_text() -> None:
    secret_words = "confidential-marker-xyz"
    s = stream(msg(f"{secret_words}\n"), *TOOL, msg(f"{secret_words} NOTED.\n\n{SIG}"), DONE)
    with pytest.raises(xba.Rejected) as caught:
        xba.extract(s)
    message = str(caught.value)
    assert secret_words not in message
    assert "after the last tool call: 3 lines, 0 header, 1 signature" in message


def test_answer_only_before_last_tool_call_is_rejected() -> None:
    # The answer must be the text after the last tool call, not an earlier message.
    with pytest.raises(xba.Rejected, match="signature"):
        xba.extract(stream(msg(ANSWER), *TOOL, msg("One more check."), DONE))


def test_oversized_answer_is_rejected_in_utf8_bytes() -> None:
    body = "IBM Bob\n" + "€" * 20 + f"\n{SIG}"  # the euro signs are 20 chars, 60 bytes
    assert len(body) < 90 < len(body.encode())
    with pytest.raises(xba.Rejected, match="bytes, over 90"):
        xba.extract(stream(msg(body), DONE), max_bytes=90)


def test_body_line_starting_with_the_name_does_not_truncate() -> None:
    # Bob's review of this PR: a body line beginning with the name must not cut the answer.
    body = (
        "IBM Bob — review of PR #39.\n\n"
        "IBM Bob's own format was checked against the tests.\n\n"
        f"NOTED.\n\n{SIG}"
    )
    assert xba.extract(stream(*TOOL, msg(body), DONE)) == body


def test_draft_without_its_own_signature_is_kept_not_truncated() -> None:
    # With no draft signature there is no boundary: the extra text is kept, so the
    # rule errs toward more text, never toward a cut answer.
    text = "IBM Bob draft: thinking.\n\n" + ANSWER
    assert xba.extract(stream(msg(text), DONE)) == text


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
