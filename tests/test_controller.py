"""Tests for the orchestration controller. Pure Python, no Anki import required."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import controller


def load_dataset():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cs2_cases", "data", "cases.json",
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state.json")
        self.config = {"earn_per_card": 1.0, "case_price": 2.5, "sell_fraction": 1.0}
        self.ctrl = controller.Controller(self.path, self.config, load_dataset())

    def test_earn_persists_across_reload(self):
        self.ctrl.earn_for_card()
        self.ctrl.earn_for_card()
        reloaded = controller.Controller(self.path, self.config, load_dataset())
        self.assertEqual(reloaded.state["balance"], 2.0)

    def test_global_case_price_override(self):
        self.config["case_price"] = 5.0
        ctrl = controller.Controller(self.path, self.config, load_dataset())
        payload = ctrl.state_payload()
        self.assertTrue(all(c["price"] == 5.0 for c in payload["cases"]))

    def test_open_then_inventory_in_payload(self):
        for _ in range(3):
            self.ctrl.earn_for_card()
        result = self.ctrl.open_case("clutch_case")
        payload = self.ctrl.state_payload()
        self.assertEqual(len(payload["inventory"]), 1)
        self.assertEqual(payload["inventory"][0]["uid"], result["drop"]["uid"])

    def test_payload_has_catalog_metadata(self):
        payload = self.ctrl.state_payload()
        self.assertIn("rarities", payload)
        self.assertIn("wear_tiers", payload)
        self.assertTrue(len(payload["cases"]) >= 1)


if __name__ == "__main__":
    unittest.main()
