"""Authenticated GitHub event selection and durable, bounded local work queue."""

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = "mgalic01/adaptive-market-engine"
REPO_ID = 1384347674
MAX_BODY = 1024 * 1024
SENDERS = {"mgalic01", "github-actions[bot]", "claude[bot]", "chatgpt-codex-connector[bot]"}
ACTIONS = {
    "pull_request": {"opened", "synchronize", "reopened", "ready_for_review", "closed", "edited"},
    "issue_comment": {"created", "edited", "deleted"},
    "pull_request_review": {"submitted", "edited", "dismissed"},
    "pull_request_review_comment": {"created", "edited", "deleted"},
    "check_suite": {"completed"},
    "workflow_run": {"completed"},
}


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def validate(body: bytes, signature: str, event: str, secret: bytes) -> int | None:
    """Authenticate raw bytes first; never interpret webhook text as instructions."""
    if len(secret) < 32 or len(body) > MAX_BODY:
        raise ValueError("invalid size")
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise ValueError("bad signature")
    try:
        data = object_value(json.loads(body))
        repo = object_value(data.get("repository"))
        if repo.get("id") != REPO_ID or repo.get("full_name") != REPO:
            raise ValueError("wrong repository")
        if object_value(data.get("sender")).get("login") not in SENDERS:
            raise ValueError("sender not allowed")
        if event == "ping":
            return None
        if event not in ACTIONS or data.get("action") not in ACTIONS[event]:
            return None
        if event in {"check_suite", "workflow_run"}:
            related = object_value(data.get(event)).get("pull_requests")
            if not isinstance(related, list) or len(related) != 1:
                return None
            number = object_value(related[0]).get("number")
        elif event == "issue_comment":
            issue = object_value(data.get("issue"))
            if "pull_request" not in issue:
                return None
            comment = object_value(data.get("comment", {}))
            if data["action"] == "created" and str(comment.get("body", "")).startswith(
                "<!-- codex-local-worker -->"
            ):
                return None
            number = issue.get("number")
        else:
            number = object_value(data.get("pull_request")).get("number")
        if type(number) is not int or not 0 < number < 10000000:
            raise ValueError("invalid PR number")
        return number
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("malformed payload") from exc


class Queue:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    digest TEXT PRIMARY KEY, pr INTEGER NOT NULL,
                    received REAL NOT NULL, run INTEGER);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, started REAL NOT NULL,
                    state TEXT NOT NULL, report TEXT NOT NULL DEFAULT '');
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, body: bytes, pr: int, now: float) -> bool:
        digest = hashlib.sha256(body).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM events WHERE digest=?", (digest,)).fetchone():
                return False
            if db.execute("SELECT count(*) FROM events WHERE run IS NULL").fetchone()[0] >= 1000:
                raise ValueError("queue full")
            db.execute("INSERT INTO events VALUES (?, ?, ?, NULL)", (digest, pr, now))
        return True

    def claim(self, now: float) -> tuple[int, list[int]] | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE state='running'").fetchone():
                return None
            hourly = db.execute("SELECT count(*) FROM runs WHERE started>?", (now - 3600,))
            if hourly.fetchone()[0] >= 6:
                return None
            daily = db.execute("SELECT count(*) FROM runs WHERE started>?", (now - 86400,))
            if daily.fetchone()[0] >= 24:
                return None
            rows = db.execute(
                "SELECT pr FROM events WHERE run IS NULL GROUP BY pr "
                "HAVING max(received)<=? ORDER BY min(received) LIMIT 1",
                (now - 30,),
            ).fetchall()
            if not rows:
                return None
            cursor = db.execute("INSERT INTO runs(started,state) VALUES (?, 'running')", (now,))
            run_id = cursor.lastrowid
            if run_id is None:
                raise RuntimeError("missing run ID")
            numbers = [r[0] for r in rows]
            for number in numbers:
                db.execute("UPDATE events SET run=? WHERE pr=? AND run IS NULL", (run_id, number))
            return run_id, numbers

    def finish(self, run_id: int, state: str, report: str) -> None:
        if state not in {"completed", "failed"}:
            raise ValueError("invalid terminal state")
        with self.connect() as db:
            db.execute("UPDATE runs SET state=?, report=? WHERE id=?", (state, report, run_id))

    def recover(self) -> None:
        """Only call after obtaining the service lock. Never automatically rerun uncertainty."""
        with self.connect() as db:
            db.execute("UPDATE runs SET state='interrupted' WHERE state='running'")

    def status(self) -> dict[str, Any]:
        with self.connect() as db:
            return {
                "pending": db.execute("SELECT count(*) FROM events WHERE run IS NULL").fetchone()[
                    0
                ],
                "runs": db.execute(
                    "SELECT id,state,report FROM runs ORDER BY id DESC LIMIT 20"
                ).fetchall(),
            }
