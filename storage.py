from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Iterator
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp_rating(value: int) -> int:
    return max(0, min(100, value))


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    mod_role_id: int | None
    alert_channel_id: int | None
    alert_threshold: int


@dataclass(frozen=True)
class ThreatRecord:
    guild_id: int
    user_id: int
    rating: int
    updated_at: str
    updated_by: int | None
    last_reason: str | None


class ThreatStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    mod_role_id INTEGER,
                    alert_channel_id INTEGER,
                    alert_threshold INTEGER NOT NULL DEFAULT 80
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS threats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER,
                    last_reason TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS threat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    old_rating INTEGER NOT NULL,
                    new_rating INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_threat_history_lookup
                ON threat_history (guild_id, user_id, created_at DESC)
                """
            )

    def ensure_guild(
        self,
        guild_id: int,
        *,
        default_mod_role_id: int | None = None,
        default_alert_channel_id: int | None = None,
        default_alert_threshold: int = 80,
    ) -> GuildSettings:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO guild_settings (
                    guild_id, mod_role_id, alert_channel_id, alert_threshold
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    guild_id,
                    default_mod_role_id,
                    default_alert_channel_id,
                    clamp_rating(default_alert_threshold),
                ),
            )
        return self.get_settings(guild_id)

    def get_settings(self, guild_id: int) -> GuildSettings:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM guild_settings WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
        if row is None:
            return GuildSettings(guild_id, None, None, 80)
        return GuildSettings(
            guild_id=row["guild_id"],
            mod_role_id=row["mod_role_id"],
            alert_channel_id=row["alert_channel_id"],
            alert_threshold=row["alert_threshold"],
        )

    def update_settings(
        self,
        guild_id: int,
        *,
        mod_role_id: int | None | object = ...,
        alert_channel_id: int | None | object = ...,
        alert_threshold: int | object = ...,
    ) -> GuildSettings:
        self.ensure_guild(guild_id)
        assignments: list[str] = []
        values: list[int | None] = []

        if mod_role_id is not ...:
            assignments.append("mod_role_id = ?")
            values.append(mod_role_id)
        if alert_channel_id is not ...:
            assignments.append("alert_channel_id = ?")
            values.append(alert_channel_id)
        if alert_threshold is not ...:
            assignments.append("alert_threshold = ?")
            values.append(clamp_rating(int(alert_threshold)))

        if assignments:
            values.append(guild_id)
            with self._connect() as db:
                db.execute(
                    f"UPDATE guild_settings SET {', '.join(assignments)} WHERE guild_id = ?",
                    values,
                )
        return self.get_settings(guild_id)

    def get_record(self, guild_id: int, user_id: int) -> ThreatRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM threats WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return ThreatRecord(
            guild_id=row["guild_id"],
            user_id=row["user_id"],
            rating=row["rating"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            last_reason=row["last_reason"],
        )

    def change_rating(
        self,
        guild_id: int,
        user_id: int,
        *,
        action: str,
        new_rating: int,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        if not reason.strip():
            raise ValueError("A reason is required.")

        old_record = self.get_record(guild_id, user_id)
        old_rating = old_record.rating if old_record else 0
        rating = clamp_rating(new_rating)
        now = utc_now_iso()

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO threats (
                    guild_id, user_id, rating, updated_at, updated_by, last_reason
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    rating = excluded.rating,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    last_reason = excluded.last_reason
                """,
                (guild_id, user_id, rating, now, moderator_id, reason.strip()),
            )
            db.execute(
                """
                INSERT INTO threat_history (
                    guild_id, user_id, action, delta, old_rating, new_rating,
                    reason, moderator_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    user_id,
                    action,
                    rating - old_rating,
                    old_rating,
                    rating,
                    reason.strip(),
                    moderator_id,
                    now,
                ),
            )

        record = self.get_record(guild_id, user_id)
        if record is None:
            raise RuntimeError("Threat record was not saved.")
        return record, old_rating

    def reset_rating(
        self,
        guild_id: int,
        user_id: int,
        *,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        return self.change_rating(
            guild_id,
            user_id,
            action="reset",
            new_rating=0,
            reason=reason,
            moderator_id=moderator_id,
        )

    def history(self, guild_id: int, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(
                """
                SELECT * FROM threat_history
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, user_id, max(1, min(25, limit))),
            ).fetchall()

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[ThreatRecord]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM threats
                WHERE guild_id = ? AND rating > 0
                ORDER BY rating DESC, updated_at DESC
                LIMIT ?
                """,
                (guild_id, max(1, min(25, limit))),
            ).fetchall()
        return [
            ThreatRecord(
                guild_id=row["guild_id"],
                user_id=row["user_id"],
                rating=row["rating"],
                updated_at=row["updated_at"],
                updated_by=row["updated_by"],
                last_reason=row["last_reason"],
            )
            for row in rows
        ]
