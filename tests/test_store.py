"""Tests for atomic JSON persistence. Pure Python, no Anki import required."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import economy, store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state.json")

    def test_missing_file_returns_fresh_state(self):
        state = store.load(self.path)
        self.assertEqual(state["balance"], 0.0)
        self.assertEqual(state["inventory"], [])

    def test_round_trip(self):
        state = economy.new_state()
        state["balance"] = 12.34
        economy.add_earnings(state, 1.0)
        store.save(self.path, state)
        loaded = store.load(self.path)
        self.assertEqual(loaded["balance"], state["balance"])
        self.assertEqual(loaded["stats"]["earned"], state["stats"]["earned"])

    def test_corrupt_file_is_backed_up_not_lost(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        state = store.load(self.path)
        self.assertEqual(state["balance"], 0.0)  # fresh state returned
        self.assertTrue(os.path.exists(self.path + ".corrupt"))

    def test_partial_state_gets_defaults(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"balance": 5.0}')
        state = store.load(self.path)
        self.assertEqual(state["balance"], 5.0)
        self.assertIn("inventory", state)
        self.assertIn("next_uid", state)
        self.assertIn("cards", state["stats"])

    def test_no_leftover_temp_files(self):
        store.save(self.path, economy.new_state())
        leftovers = [n for n in os.listdir(self.dir) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
