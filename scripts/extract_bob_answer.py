"""Extract Bob's final answer from a ``bob run -f stream-json`` log, or refuse.

Shared by bob-review.yml (the posted review) and bob-task.yml (the task summary), so
both follow one tested rule (Codex's audit, PR #33 comment 5838607730). It fails
closed: nothing is printed unless all of these hold.

- **Final success:** the last ``result`` event has ``status == "success"``. An
  earlier success followed by a failure is a failure. Events after it are ignored.
- **Answer text:** the assistant's non-reasoning ``message`` text. Tool output never
  enters it; each tool call starts a new line.
- **Signature:** a ``— IBM Bob (<label>)`` that ends its line, after the last tool
  call. The last one ends the answer, and anything written after it is dropped. A
  signature quoted inside a sentence is not a signature.
- **Header:** the answer starts at the *first* line beginning with ``IBM Bob``
  (markdown ``#``, ``>``, ``*`` or ``_`` markers before it are allowed) after the
  previous signature, or after the last tool call if there is none. A draft that ends
  with its own signature is dropped whole; a line inside the answer that begins with
  the name does not cut the answer short, and a mention inside a line is never taken
  as the start.
- **One tool call bridged:** if no header follows the last tool call, the last
  unsigned header in the turn just before it starts the answer (Bob wrote his
  header, read one more file, then finished). Nothing earlier is ever used.
- **Size:** the answer is not blank and at most ``--max-bytes`` bytes of UTF-8, the
  same unit the task publisher's validator uses.

On refusal it prints one ``Rejected:`` line with the answer's structure (lines,
headers and signatures before and after the last tool call) and a count of event
types, never text: the raw stream could echo file contents.

Usage: ``extract_bob_answer.py [--max-bytes N] STREAM`` (answer on stdout, exit 1 on
refusal) or ``extract_bob_answer.py --stats STREAM`` (event counts only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# A signature must end its line, so a signature quoted inside a sentence (Bob discussing
# the format) is not mistaken for the end of a draft.
SIGNATURE = re.compile(r"(?m)—[ \t]*IBM Bob \([^()\n]*\)[ \t*_\r]*$")
# Markdown emphasis, heading or quote markers before the name are allowed: Bob sometimes
# writes "**IBM Bob**" or "## IBM Bob", and a correct answer must not be refused for it.
# One flat character class: a nested quantifier here backtracks exponentially on a long
# run of markers (a 24-character run took over a second), and the text is untrusted.
HEADER = re.compile(r"(?m)^[#>*_ \t]*IBM Bob(?![A-Za-z0-9])")
DEFAULT_MAX_BYTES = 20_000
DESCRIPTION = "Extract Bob's final answer from a bob run stream-json log, or refuse."


class Rejected(Exception):
    """No answer may be published."""


def events(text: str) -> list[dict[str, Any]]:
    """Parsed JSON-object lines; anything else (blank, partial, non-object) is skipped."""
    parsed: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            parsed.append(value)
    return parsed


def extract(stream: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    items = events(stream)
    results = [i for i, e in enumerate(items) if e.get("type") == "result"]
    if not results or items[results[-1]].get("status") != "success":
        raise Rejected("the run did not end with a successful result")
    # All of Bob's own (non-reasoning) text; `tail` is where the text after his last
    # tool call starts. Tool output never enters `text`.
    text, tail, turn = "", 0, 0
    for event in items[: results[-1]]:
        kind = event.get("type")
        if kind in ("tool_use", "tool_result"):
            # A tool call ends a turn: the next text starts on a new line.
            if text and not text.endswith("\n"):
                text += "\n"
            if len(text) != tail:  # a new turn ended; `turn` is where it began
                turn, tail = tail, len(text)
        elif kind == "message" and event.get("role") == "assistant":
            content = event.get("content")
            if not event.get("isReasoning") and isinstance(content, str):
                text += content
    signatures = [s for s in SIGNATURE.finditer(text) if s.start() >= tail]
    if not signatures:
        raise Rejected(
            "the final answer has no '— IBM Bob (...)' signature line after the last tool "
            f"call ({shape(text, tail)})"
        )
    final = signatures[-1]
    start = signatures[-2].end() if len(signatures) > 1 else tail
    header = HEADER.search(text, start, final.start())
    if header is None and len(signatures) == 1:
        # Bob sometimes writes his header, checks one more file, then finishes. Only the
        # turn just before the last tool call is searched, so the answer bridges at most
        # one tool call and no earlier turn or draft is spliced in.
        before = [h for h in HEADER.finditer(text, turn, tail) if not _signed_after(text, h, tail)]
        header = before[-1] if before else None
    if header is None:
        raise Rejected(
            f"the final answer has no line starting with 'IBM Bob' ({shape(text, tail)})"
        )
    answer = text[header.start() : final.end()].strip()
    if not answer:
        raise Rejected("the final answer is blank")
    size = len(answer.encode("utf-8"))
    if size > max_bytes:
        raise Rejected(f"the final answer is {size} bytes, over {max_bytes}")
    return answer


def _signed_after(text: str, header: re.Match[str], end: int) -> bool:
    """True if a signature closes this header's text before `end` (a finished draft)."""
    return SIGNATURE.search(text, header.end(), end) is not None


def shape(text: str, tail: int) -> str:
    """Structure only, never content: where headers and signatures are."""
    parts = (("before", 0, tail), ("after", tail, len(text)))
    counts = [
        f"{name} the last tool call: {len(text[a:b].splitlines())} lines, "
        f"{len(HEADER.findall(text, a, b))} header, {len(SIGNATURE.findall(text, a, b))} signature"
        for name, a, b in parts
    ]
    return "; ".join(counts)


def stats(stream: str) -> str:
    counts = Counter(str(e.get("type")) for e in events(stream))
    return ", ".join(f"{kind}={n}" for kind, n in sorted(counts.items())) or "no events"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("stream", type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)
    stream = args.stream.read_text(encoding="utf-8", errors="replace")
    if args.stats:
        print(f"Bob's stream: {stats(stream)}")
        return 0
    try:
        answer = extract(stream, args.max_bytes)
    except Rejected as exc:
        print(f"Rejected: {exc}. Bob's stream: {stats(stream)}", file=sys.stderr)
        return 1
    sys.stdout.write(answer + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
