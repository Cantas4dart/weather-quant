from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Position


class BotDB:
    """Small database facade so modules do not depend on sqlite details."""

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_errors (
                    city TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    forecast_high_c REAL NOT NULL,
                    observed_high_c REAL NOT NULL,
                    error_c REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (city, target_date, source)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    city TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (city, market_id, strategy)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_watchlist (
                    token_id TEXT PRIMARY KEY,
                    city TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    size_usd REAL NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    opened_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exit_alerts (
                    token_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (token_id, action)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_subscribers (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    subscribed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def add_position(
        self,
        city: str,
        market_id: str,
        token_id: str,
        side: str,
        entry_price: float,
        size_usd: float = 0.0,
        notes: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO manual_watchlist
                (token_id, city, market_id, side, entry_price, size_usd, notes, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    city,
                    market_id,
                    side,
                    entry_price,
                    size_usd,
                    notes,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_positions(self) -> list[Position]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT city, market_id, token_id, side, entry_price, size_usd, opened_at, notes
                FROM manual_watchlist
                ORDER BY opened_at ASC
                """
            ).fetchall()
        return [
            Position(
                city_name=row[0],
                market_id=row[1],
                token_id=row[2],
                side=row[3],
                entry_price=float(row[4]),
                size_usd=float(row[5]),
                opened_at=datetime.fromisoformat(row[6]),
                notes=row[7],
            )
            for row in rows
        ]

    def should_exit_alert(self, token_id: str, action: str, cooldown_minutes: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM exit_alerts WHERE token_id = ? AND action = ?",
                (token_id, action),
            ).fetchone()
        if not row:
            return True
        last = datetime.fromisoformat(row[0])
        return (datetime.now(timezone.utc) - last).total_seconds() >= cooldown_minutes * 60

    def mark_exit_alerted(self, token_id: str, action: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO exit_alerts (token_id, action, created_at)
                VALUES (?, ?, ?)
                """,
                (token_id, action, datetime.now(timezone.utc).isoformat()),
            )

    def add_telegram_subscriber(self, chat_id: str, title: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO telegram_subscribers (chat_id, title, subscribed_at)
                VALUES (?, ?, ?)
                """,
                (chat_id, title, datetime.now(timezone.utc).isoformat()),
            )

    def remove_telegram_subscriber(self, chat_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM telegram_subscribers WHERE chat_id = ?", (chat_id,))

    def list_telegram_subscribers(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT chat_id FROM telegram_subscribers ORDER BY subscribed_at ASC").fetchall()
        return [str(row[0]) for row in rows]

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                (key, value),
            )
