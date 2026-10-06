"""Disposable offline probe for ONE pinned development artifact, not a general importer.

No engine imports, network, credentials, execution or recalculation. JSON request bodies
are prepared for inspection only; an OpenTraderWorld installation is not contacted.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

EXPECTED_SHA256 = "a78ea9282cb01f451cab73dfc02d254c9eaaf7115ff5439be0506f92404d89a2"
SOURCE_URL = "https://github.com/mgalic01/adaptive-market-engine/actions/runs/37441444046"
REPORT_URL = (
    "https://github.com/mgalic01/adaptive-market-engine/blob/"
    "ecabad046c5585d2473cc37661b2004fba9918ef/"
    "docs/backtests/2026-10-06-spec-v1-stage-1.md"
)
UPSTREAM = "a3383baff1b5bb6d78c349437c45fbbe32cd4836"
TITLE = "AME external research — practice-2022 V0 and D — historical stage 1"


def encoded(value: Any) -> str:
    # Decimal JSON numbers become exact text in the note, not binary float rounding.
    # The original JSON bytes remain the authoritative typed representation.
    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"


def note_text(document: dict[str, Any]) -> str:
    status = "INTEGRITY-VALID" if document["valid"] is True else "INVALID — DIAGNOSTIC ONLY"
    metadata = {k: v for k, v in document.items() if k != "results"}
    rows = [{k: v for k, v in row.items() if k != "hourly_equity"} for row in document["results"]]
    overview = "\n\n".join(
        f"{row['symbol']} | {row['strategy']} | {row['path_mode']}\n"
        f"  Strategy return: {row['return_pct']}%; "
        f"holding return: {row['buy_and_hold_return_pct']}%\n"
        f"  Total drawdown: {row['max_drawdown_pct']}%; "
        f"active drawdown: {row.get('active_max_drawdown_pct', 'not reported')}%"
        for row in rows
    )
    return (
        f"{TITLE}\n\n"
        "EXPERIMENTAL VIEWING COPY — externally produced AME results, not an OTW backtest.\n"
        "POST-RESULT note: prepared after observing this historical run.\n"
        "The complete v1 experiment ended with NO WINNER. This one artifact cannot choose "
        "a strategy; benchmark D is not selectable.\n\n"
        f"Source status: {status}. Integrity-valid does not mean passing C1–C6.\n"
        f"Source workflow: {SOURCE_URL}\nSource SHA-256: {EXPECTED_SHA256}\n"
        f"Committed evidence and exclusions: {REPORT_URL}\n\n"
        "No returns or verdicts were recalculated. All rows remain in original order, "
        "including ungated baselines and benchmark D. All metadata, failures, exclusions "
        "and per-row diagnostics are included below. Hourly equity arrays alone are omitted "
        "from this viewing copy; they remain in the exact source file. Decimal numbers "
        "are rendered as exact text (quoted in these JSON excerpts).\n\n"
        "ROW OVERVIEW — source values, not annualised or rescored\n"
        + overview
        + "\n\nSOURCE METADATA AND CROSS-CHECKS\n"
        + encoded(metadata)
        + "\nALL RESULT ROWS (WITHOUT HOURLY EQUITY)\n"
        + encoded(rows)
    )


def editor_payload(note: str) -> dict[str, Any]:
    # Literal text in a Tiptap node; source labels never become HTML or Markdown.
    return {
        "content": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": note}]}],
        }
    }


def preview_html(note: str) -> str:
    introduction, separator, evidence = note.partition("SOURCE METADATA AND CROSS-CHECKS")
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>AME research note — offline trial</title>"
        "<style>body{max-width:1000px;margin:40px auto;padding:0 24px;background:#f5f7fa;"
        "color:#172033;font:16px/1.6 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;"
        "background:white;padding:24px;border:1px solid #d8dfea;font:14px/1.5 monospace}"
        "h1{font-size:26px}</style><h1>Historical research · viewing copy</h1>"
        "<p>Offline feasibility preview. No connection to OpenTraderWorld.</p><pre>"
        + html.escape(introduction)
        + "</pre><details><summary>Inspect provenance, exclusions and row diagnostics</summary>"
        + "<pre>"
        + html.escape(separator + evidence)
        + "</pre></details></html>\n"
    )


def export(source: Path, out: Path) -> None:
    if source.stat().st_size > 50_000_000:
        raise ValueError("source exceeds the 50 MB probe limit")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("source SHA-256 differs from the committed stage-1 evidence pin")
    # Only these exact historical bytes are accepted, not arbitrary untrusted schemas.
    document = json.loads(raw, parse_float=Decimal)
    note = note_text(document)
    files = {
        "results.json": raw,
        "note.txt": note.encode("utf-8"),
        "preview.html": preview_html(note).encode("utf-8"),
        "create-page.json": encoded({"kind": "page", "title": TITLE, "parent_id": None}).encode(
            "utf-8"
        ),
        "update-page.json": encoded(editor_payload(note)).encode("utf-8"),
    }
    manifest = {
        "status": "offline probe only; no import or runtime verification",
        "source_url": SOURCE_URL,
        "evidence_url": REPORT_URL,
        "source_sha256": EXPECTED_SHA256,
        "otw_source_commit": UPSTREAM,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    # Refuse an existing folder, including another probe's output. Never overwrite inputs.
    out.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (out / name).write_bytes(data)
    (out / "bundle.json").write_text(encoded(manifest), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="the pinned historical results.json")
    parser.add_argument("out", type=Path, help="new folder for the disposable bundle")
    args = parser.parse_args()
    export(args.source, args.out)
    print(f"Prepared offline viewing copy in {args.out}; no data sent to any service.")


if __name__ == "__main__":
    main()
