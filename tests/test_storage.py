import tempfile
import unittest
from pathlib import Path

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
            new_rating=150,
            reason="Masquerade breach caught on traffic cameras",
            moderator_id=999,
        )

        self.assertEqual(old_rating, 0)
        self.assertEqual(record.rating, 100)
        self.assertEqual(record.last_reason, "Masquerade breach caught on traffic cameras")

        history = store.history(123, 456)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_rating"], 0)
        self.assertEqual(history[0]["new_rating"], 100)

    def test_leaderboard_orders_by_rating(self):
        store = self.make_store()
        store.ensure_guild(123)

        store.change_rating(123, 1, action="set", new_rating=25, reason="A", moderator_id=9)
        store.change_rating(123, 2, action="set", new_rating=80, reason="B", moderator_id=9)
        store.change_rating(123, 3, action="set", new_rating=40, reason="C", moderator_id=9)

        records = store.leaderboard(123)

        self.assertEqual([record.user_id for record in records], [2, 3, 1])

    def test_settings_can_be_updated_partially(self):
        store = self.make_store()
        store.ensure_guild(123)

        store.update_settings(123, mod_role_id=111)
        settings = store.update_settings(123, alert_threshold=75)

        self.assertEqual(settings.mod_role_id, 111)
        self.assertEqual(settings.alert_threshold, 75)


if __name__ == "__main__":
    unittest.main()
