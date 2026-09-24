"""Atomic observations and failure records, isolated from the paper-account database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from crypto_grid_bot.market_data.collector import SCHEMA_VERSION, encode
from crypto_grid_bot.market_data.parsing import DataError


class ObservationStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5)
        try:
            tables = {
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            allowed = {"capture_settings", "captures", "candles", "books", "failures"}
            if tables - allowed:
                raise DataError("use a separate market-data database, not a paper account")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS capture_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS captures (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, server_ms INTEGER NOT NULL,
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS capture_symbol_time ON captures(symbol, server_ms);
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL, open_ms INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(symbol, open_ms));
                CREATE TABLE IF NOT EXISTS books (
                    symbol TEXT NOT NULL, update_id INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(symbol, update_id));
                CREATE TABLE IF NOT EXISTS failures (
                    received_ms INTEGER NOT NULL, symbol TEXT NOT NULL, reason TEXT NOT NULL,
                    blocked_until_ms INTEGER NOT NULL);
            """)
            with self.connection:
                self.connection.execute(
                    "INSERT OR IGNORE INTO capture_settings VALUES (1, ?)", (SCHEMA_VERSION,)
                )
                version = self.connection.execute("SELECT version FROM capture_settings").fetchone()
                if version != (SCHEMA_VERSION,):
                    raise DataError("unsupported observation database version")
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def check_cooldown(self, now_ms: int) -> None:
        row = self.connection.execute("SELECT MAX(blocked_until_ms) FROM failures").fetchone()
        if row and row[0] and now_ms < row[0]:
            raise DataError(f"public API cooldown active until Unix milliseconds {row[0]}")

    def failure(self, symbol: str, now_ms: int, reason: str, retry_after: int = 0) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO failures VALUES (?, ?, ?, ?)",
                (
                    now_ms,
                    symbol,
                    reason,
                    now_ms + retry_after * 1000 if retry_after else 0,
                ),
            )

    def save(self, observation: dict[str, Any]) -> bool:
        """Commit the full validated observation or nothing; return False for exact retry."""
        body = encode(observation)
        item = json.loads(body)
        if item["schema_version"] != SCHEMA_VERSION or item["orders_authorized"] is not False:
            raise DataError("only current observe-only records can be saved")
        symbol = item["symbol"]
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT body FROM captures WHERE id=?", (item["capture_id"],)
            ).fetchone()
            if existing:
                if existing[0] != body:
                    raise DataError("capture ID was reused with changed data")
                return False
            latest = self.connection.execute(
                "SELECT MAX(server_ms) FROM captures WHERE symbol=?", (symbol,)
            ).fetchone()[0]
            if latest is not None and item["server_finished_ms"] <= latest:
                raise DataError("observation clock did not advance")
            previous_book = self.connection.execute(
                "SELECT MAX(update_id) FROM books WHERE symbol=?", (symbol,)
            ).fetchone()[0]
            if previous_book is not None and item["book"]["update_id"] < previous_book:
                raise DataError("order-book update ID regressed")
            for candle in item["candles"]:
                self._candle(symbol, candle["open_ms"], encode(candle))
            self._book(symbol, item["book"]["update_id"], encode(item["book"]))
            self.connection.execute(
                "INSERT INTO captures VALUES (?, ?, ?, ?)",
                (
                    item["capture_id"],
                    symbol,
                    item["server_finished_ms"],
                    body,
                ),
            )
        return True

    def _candle(self, symbol: str, open_ms: int, body: str) -> None:
        existing = self.connection.execute(
            "SELECT body FROM candles WHERE symbol=? AND open_ms=?", (symbol, open_ms)
        ).fetchone()
        if existing and existing[0] != body:
            raise DataError("previously closed candle changed; inspect source revision")
        self.connection.execute(
            "INSERT OR IGNORE INTO candles VALUES (?, ?, ?)", (symbol, open_ms, body)
        )

    def _book(self, symbol: str, update_id: int, body: str) -> None:
        existing = self.connection.execute(
            "SELECT body FROM books WHERE symbol=? AND update_id=?", (symbol, update_id)
        ).fetchone()
        if existing and existing[0] != body:
            raise DataError("order-book update ID was reused with changed levels")
        self.connection.execute(
            "INSERT OR IGNORE INTO books VALUES (?, ?, ?)", (symbol, update_id, body)
        )
