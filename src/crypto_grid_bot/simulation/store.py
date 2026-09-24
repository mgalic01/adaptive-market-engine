"""Single-writer SQLite transactions for state and idempotent replay events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, cast

from crypto_grid_bot.simulation.models import Account, MarketRules


def encode(value: object) -> str:
    def fallback(item: object) -> str:
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(f"cannot encode {type(item).__name__}")

    return json.dumps(
        value, default=fallback, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class StateStore:
    def __init__(self, path: Path, initial: Account, rules: MarketRules, identity: str) -> None:
        self.rules = rules
        self.connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), "
                "identity TEXT NOT NULL, data TEXT NOT NULL)"
            )
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, "
                "event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, result TEXT NOT NULL)"
            )
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT identity FROM state WHERE id=1").fetchone()
            if row is None:
                initial.validate(rules)
                self.connection.execute(
                    "INSERT INTO state VALUES (1, ?, ?)", (identity, encode(initial.to_dict()))
                )
            elif row[0] != identity:
                raise ValueError("saved account settings differ; use the original settings")
            self.read().validate(rules)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            self.connection.close()
            raise

    def read(self) -> Account:
        row = self.connection.execute("SELECT data FROM state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing account state")
        account = Account.from_dict(json.loads(row[0]))
        account.validate(self.rules)
        return account

    def transact(
        self, event_id: str, payload: dict[str, Any], operation: Callable[[Account], dict[str, Any]]
    ) -> dict[str, Any]:
        if not event_id.strip():
            raise ValueError("event ID is required")
        serialized = encode(payload)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            previous = self.connection.execute(
                "SELECT payload, result FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            if previous is not None:
                if previous[0] != serialized:
                    raise ValueError("event ID reused with different data")
                self.read()  # Never hide corrupted state behind a cached result.
                self.connection.commit()
                return cast(dict[str, Any], json.loads(previous[1]))
            with localcontext() as context:
                context.prec = 50
                account = self.read()
                result = operation(account)
                account.validate(self.rules)
                saved = encode(result)
                self.connection.execute(
                    "UPDATE state SET data=? WHERE id=1", (encode(account.to_dict()),)
                )
                self.connection.execute(
                    "INSERT INTO events(event_id, payload, result) VALUES (?, ?, ?)",
                    (event_id, serialized, saved),
                )
            self.connection.commit()
            return cast(dict[str, Any], json.loads(saved))
        except BaseException:
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()
