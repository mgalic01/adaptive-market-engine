"""Extract Bob's final answer from a ``bob run -f stream-json`` log, or refuse.

Shared by bob-review.yml (the posted review) and bob-task.yml (the task summary), so
both follow one tested rule (Codex's audit, PR #33 comment 5838607730). It fails
closed: nothing is printed unless all of these hold.

- **Final success:** the last ``result`` event has ``status == "success"``. An
  earlier success followed by a failure is a failure. Events after it are ignored.
- **Answer text:** the assistant's non-reasoning ``message`` text streamed after its
  last tool call.
- **Signature:** the text contains ``— IBM Bob (<label>)``. The last one ends the
  answer, and anything written after it is dropped.
- **Header:** the answer starts at the last line that *begins* with ``IBM Bob`` before
  that signature. Drafts and reasoning written earlier are dropped, and a mention of
  the name inside a line is never mistaken for the start.
- **Size:** the answer is not blank and at most ``--max-chars`` characters.

On refusal it prints one ``Rejected:`` line and a count of event types, never the raw
stream, which could echo file contents.

Usage: ``extract_bob_answer.py [--max-chars N] STREAM`` (answer on stdout, exit 1 on
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

SIGNATURE = re.compile(r"—[ \t]*IBM Bob \([^()\n]*\)")
HEADER = re.compile(r"(?m)^IBM Bob\b")
DEFAULT_MAX_CHARS = 20_000


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


def extract(stream: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    items = events(stream)
    results = [i for i, e in enumerate(items) if e.get("type") == "result"]
    if not results or items[results[-1]].get("status") != "success":
        raise Rejected("the run did not end with a successful result")
    text = ""
    for event in items[: results[-1]]:
        kind = event.get("type")
        if kind in ("tool_use", "tool_result"):
            text = ""
        elif kind == "message" and event.get("role") == "assistant":
            content = event.get("content")
            if not event.get("isReasoning") and isinstance(content, str):
                text += content
    signatures = list(SIGNATURE.finditer(text))
    if not signatures:
        raise Rejected("the final answer has no '— IBM Bob (...)' signature")
    end = signatures[-1].end()
    headers = [m.start() for m in HEADER.finditer(text, 0, signatures[-1].start())]
    if not headers:
        raise Rejected("the final answer has no line starting with 'IBM Bob'")
    answer = text[headers[-1] : end].strip()
    if not answer:
        raise Rejected("the final answer is blank")
    if len(answer) > max_chars:
        raise Rejected(f"the final answer is {len(answer)} characters, over {max_chars}")
    return answer


def stats(stream: str) -> str:
    counts = Counter(str(e.get("type")) for e in events(stream))
    return ", ".join(f"{kind}={n}" for kind, n in sorted(counts.items())) or "no events"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stream", type=Path)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)
    stream = args.stream.read_text(encoding="utf-8", errors="replace")
    if args.stats:
        print(f"Bob's stream: {stats(stream)}")
        return 0
    try:
        answer = extract(stream, args.max_chars)
    except Rejected as exc:
        print(f"Rejected: {exc}. Bob's stream: {stats(stream)}", file=sys.stderr)
        return 1
    sys.stdout.write(answer + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
