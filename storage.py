from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp_rating(value: int) -> int:
    return max(0, min(10, value))


def user_target_id(user_id: int) -> str:
    return f"user:{user_id}"


def npc_target_id(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("NPC name is required.")
    return f"npc:{cleaned.casefold()}"


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    mod_role_id: int | None
    alert_channel_id: int | None
    alert_threshold: int


@dataclass(frozen=True)
class ThreatRecord:
    guild_id: int
    target_id: str
    target_name: str
    user_id: int | None
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
            self._migrate_legacy_user_tables(db)
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    mod_role_id INTEGER,
                    alert_channel_id INTEGER,
                    alert_threshold INTEGER NOT NULL DEFAULT 8
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS threats (
                    guild_id INTEGER NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    user_id INTEGER,
                    rating INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    updated_by INTEGER,
                    last_reason TEXT,
                    PRIMARY KEY (guild_id, target_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS threat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    user_id INTEGER,
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
                ON threat_history (guild_id, target_id, created_at DESC)
                """
            )
            self._migrate_scale_to_ten(db)

    def _table_columns(self, db: sqlite3.Connection, table_name: str) -> set[str]:
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    def _migrate_legacy_user_tables(self, db: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "threats" not in tables:
            return

        threat_columns = self._table_columns(db, "threats")
        if "target_id" in threat_columns:
            return

        db.execute("ALTER TABLE threats RENAME TO threats_legacy_user")
        if "threat_history" in tables:
            db.execute("ALTER TABLE threat_history RENAME TO threat_history_legacy_user")

        db.execute(
            """
            CREATE TABLE threats (
                guild_id INTEGER NOT NULL,
                target_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                user_id INTEGER,
                rating INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                last_reason TEXT,
                PRIMARY KEY (guild_id, target_id)
            )
            """
        )
        db.execute(
            """
            INSERT INTO threats (
                guild_id, target_id, target_name, user_id, rating,
                updated_at, updated_by, last_reason
            )
            SELECT
                guild_id,
                'user:' || user_id,
                '<@' || user_id || '>',
                user_id,
                rating,
                updated_at,
                updated_by,
                last_reason
            FROM threats_legacy_user
            """
        )

        if "threat_history_legacy_user" in {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }:
            db.execute(
                """
                CREATE TABLE threat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    user_id INTEGER,
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
                INSERT INTO threat_history (
                    id, guild_id, target_id, target_name, user_id, action,
                    delta, old_rating, new_rating, reason, moderator_id, created_at
                )
                SELECT
                    id,
                    guild_id,
                    'user:' || user_id,
                    '<@' || user_id || '>',
                    user_id,
                    action,
                    delta,
                    old_rating,
                    new_rating,
                    reason,
                    moderator_id,
                    created_at
                FROM threat_history_legacy_user
                """
            )

    def _migrate_scale_to_ten(self, db: sqlite3.Connection) -> None:
        db.execute(
            """
            UPDATE threat_history
            SET action = 'raise'
            WHERE action = 'add'
            """
        )

        max_rating = db.execute("SELECT MAX(rating) FROM threats").fetchone()[0]
        max_threshold = db.execute("SELECT MAX(alert_threshold) FROM guild_settings").fetchone()[0]
        max_history = db.execute("SELECT MAX(new_rating) FROM threat_history").fetchone()[0]

        if not any(value is not None and value > 10 for value in (max_rating, max_threshold, max_history)):
            return

        db.execute(
            """
            UPDATE threats
            SET rating = MIN(10, CAST(ROUND(rating / 10.0) AS INTEGER))
            WHERE rating > 10
            """
        )
        db.execute(
            """
            UPDATE guild_settings
            SET alert_threshold = MIN(10, CAST(ROUND(alert_threshold / 10.0) AS INTEGER))
            WHERE alert_threshold > 10
            """
        )
        db.execute(
            """
            UPDATE threat_history
            SET
                old_rating = MIN(10, CAST(ROUND(old_rating / 10.0) AS INTEGER)),
                new_rating = MIN(10, CAST(ROUND(new_rating / 10.0) AS INTEGER))
            WHERE old_rating > 10 OR new_rating > 10
            """
        )
        db.execute(
            """
            UPDATE threat_history
            SET delta = new_rating - old_rating
            """
        )

    def ensure_guild(
        self,
        guild_id: int,
        *,
        default_mod_role_id: int | None = None,
        default_alert_channel_id: int | None = None,
        default_alert_threshold: int = 8,
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
            return GuildSettings(guild_id, None, None, 8)
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

    def get_record(self, guild_id: int, target_id: str) -> ThreatRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM threats WHERE guild_id = ? AND target_id = ?",
                (guild_id, target_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_user_record(self, guild_id: int, user_id: int) -> ThreatRecord | None:
        return self.get_record(guild_id, user_target_id(user_id))

    def get_npc_record(self, guild_id: int, name: str) -> ThreatRecord | None:
        return self.get_record(guild_id, npc_target_id(name))

    def change_rating(
        self,
        guild_id: int,
        target_id: str,
        target_name: str,
        *,
        action: str,
        new_rating: int,
        reason: str,
        moderator_id: int,
        user_id: int | None = None,
    ) -> tuple[ThreatRecord, int]:
        if not reason.strip():
            raise ValueError("A reason is required.")

        old_record = self.get_record(guild_id, target_id)
        old_rating = old_record.rating if old_record else 0
        rating = clamp_rating(new_rating)
        now = utc_now_iso()

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO threats (
                    guild_id, target_id, target_name, user_id, rating,
                    updated_at, updated_by, last_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, target_id) DO UPDATE SET
                    target_name = excluded.target_name,
                    user_id = excluded.user_id,
                    rating = excluded.rating,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    last_reason = excluded.last_reason
                """,
                (
                    guild_id,
                    target_id,
                    target_name,
                    user_id,
                    rating,
                    now,
                    moderator_id,
                    reason.strip(),
                ),
            )
            db.execute(
                """
                INSERT INTO threat_history (
                    guild_id, target_id, target_name, user_id, action, delta,
                    old_rating, new_rating, reason, moderator_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    target_id,
                    target_name,
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

        record = self.get_record(guild_id, target_id)
        if record is None:
            raise RuntimeError("Threat record was not saved.")
        return record, old_rating

    def change_user_rating(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        *,
        action: str,
        new_rating: int,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        return self.change_rating(
            guild_id,
            user_target_id(user_id),
            display_name,
            action=action,
            new_rating=new_rating,
            reason=reason,
            moderator_id=moderator_id,
            user_id=user_id,
        )

    def change_npc_rating(
        self,
        guild_id: int,
        name: str,
        *,
        action: str,
        new_rating: int,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        display_name = " ".join(name.strip().split())
        return self.change_rating(
            guild_id,
            npc_target_id(display_name),
            display_name,
            action=action,
            new_rating=new_rating,
            reason=reason,
            moderator_id=moderator_id,
        )

    def reset_rating(
        self,
        guild_id: int,
        target_id: str,
        target_name: str,
        *,
        reason: str,
        moderator_id: int,
        user_id: int | None = None,
    ) -> tuple[ThreatRecord, int]:
        return self.change_rating(
            guild_id,
            target_id,
            target_name,
            action="reset",
            new_rating=0,
            reason=reason,
            moderator_id=moderator_id,
            user_id=user_id,
        )

    def reset_user_rating(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        *,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        return self.reset_rating(
            guild_id,
            user_target_id(user_id),
            display_name,
            reason=reason,
            moderator_id=moderator_id,
            user_id=user_id,
        )

    def reset_npc_rating(
        self,
        guild_id: int,
        name: str,
        *,
        reason: str,
        moderator_id: int,
    ) -> tuple[ThreatRecord, int]:
        display_name = " ".join(name.strip().split())
        return self.reset_rating(
            guild_id,
            npc_target_id(display_name),
            display_name,
            reason=reason,
            moderator_id=moderator_id,
        )

    def history(self, guild_id: int, target_id: str, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(
                """
                SELECT * FROM threat_history
                WHERE guild_id = ? AND target_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (guild_id, target_id, max(1, min(25, limit))),
            ).fetchall()

    def user_history(self, guild_id: int, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self.history(guild_id, user_target_id(user_id), limit)

    def npc_history(self, guild_id: int, name: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.history(guild_id, npc_target_id(name), limit)

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
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> ThreatRecord:
        return ThreatRecord(
            guild_id=row["guild_id"],
            target_id=row["target_id"],
            target_name=row["target_name"],
            user_id=row["user_id"],
            rating=row["rating"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            last_reason=row["last_reason"],
        )
