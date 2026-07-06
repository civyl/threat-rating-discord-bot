import tempfile
import unittest
from pathlib import Path
import sqlite3

from storage import ThreatStore


class ThreatStoreTests(unittest.TestCase):
    def make_store(self) -> ThreatStore:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        return ThreatStore(Path(self.temp_dir.name) / "threats.sqlite3")

    def test_change_rating_clamps_and_records_history(self):
        store = self.make_store()
        store.ensure_guild(123)

        record, old_rating = store.change_rating(
            123,
            456,
            action="set",
            new_rating=15,
            reason="Masquerade breach caught on traffic cameras",
            moderator_id=999,
        )

        self.assertEqual(old_rating, 0)
        self.assertEqual(record.rating, 10)
        self.assertEqual(record.last_reason, "Masquerade breach caught on traffic cameras")

        history = store.history(123, 456)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_rating"], 0)
        self.assertEqual(history[0]["new_rating"], 10)

    def test_leaderboard_orders_by_rating(self):
        store = self.make_store()
        store.ensure_guild(123)

        store.change_rating(123, 1, action="set", new_rating=2, reason="A", moderator_id=9)
        store.change_rating(123, 2, action="set", new_rating=8, reason="B", moderator_id=9)
        store.change_rating(123, 3, action="set", new_rating=4, reason="C", moderator_id=9)

        records = store.leaderboard(123)

        self.assertEqual([record.user_id for record in records], [2, 3, 1])

    def test_settings_can_be_updated_partially(self):
        store = self.make_store()
        store.ensure_guild(123)

        store.update_settings(123, mod_role_id=111)
        settings = store.update_settings(123, alert_threshold=7)

        self.assertEqual(settings.mod_role_id, 111)
        self.assertEqual(settings.alert_threshold, 7)

    def test_existing_hundred_point_data_is_migrated_to_ten_point_scale(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        database_path = Path(self.temp_dir.name) / "threats.sqlite3"

        db = sqlite3.connect(database_path)
        try:
            db.execute(
                """
                CREATE TABLE guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    mod_role_id INTEGER,
                    alert_channel_id INTEGER,
                    alert_threshold INTEGER NOT NULL DEFAULT 80
                )
                """
            )
            db.execute(
                """
                CREATE TABLE threats (
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
                CREATE TABLE threat_history (
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
            db.execute("INSERT INTO guild_settings VALUES (123, NULL, NULL, 80)")
            db.execute("INSERT INTO threats VALUES (123, 456, 75, 'now', 999, 'Old scale')")
            db.execute(
                """
                INSERT INTO threat_history (
                    guild_id, user_id, action, delta, old_rating, new_rating,
                    reason, moderator_id, created_at
                )
                VALUES (123, 456, 'add', 25, 50, 75, 'Old scale', 999, 'now')
                """
            )
            db.commit()
        finally:
            db.close()

        store = ThreatStore(database_path)

        self.assertEqual(store.get_record(123, 456).rating, 8)
        self.assertEqual(store.get_settings(123).alert_threshold, 8)
        history = store.history(123, 456)
        self.assertEqual(history[0]["action"], "raise")
        self.assertEqual(history[0]["old_rating"], 5)
        self.assertEqual(history[0]["new_rating"], 8)
        self.assertEqual(history[0]["delta"], 3)


if __name__ == "__main__":
    unittest.main()
