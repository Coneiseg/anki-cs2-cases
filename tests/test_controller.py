"""Tests for the orchestration controller. Pure Python, no Anki import required."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import controller, economy


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
        self.config = {"muted": False, "reduced_motion": False}  # cosmetic only
        self.ctrl = controller.Controller(self.path, self.config, load_dataset())

    def test_earn_persists_across_reload(self):
        self.ctrl.earn_for_card()
        self.ctrl.earn_for_card()
        reloaded = controller.Controller(self.path, self.config, load_dataset())
        self.assertEqual(reloaded.state["balance"], round(2 * economy.EARN_PER_CARD, 2))

    def test_economy_is_not_tunable_via_config(self):
        # a doctored config must not change payout, price, or sell-back
        rigged = {"earn_per_card": 1000.0, "case_price": 0.0, "sell_fraction": 99.0}
        ctrl = controller.Controller(self.path, rigged, load_dataset())
        ctrl.earn_for_card()
        self.assertEqual(ctrl.state["balance"], economy.EARN_PER_CARD)   # not 1000
        payload = ctrl.state_payload()
        self.assertTrue(all(c["price"] > 0 for c in payload["cases"]))   # not free
        ctrl.state["balance"] = 100.0
        drop = ctrl.open_case("clutch_case")["drop"]
        before = ctrl.state["balance"]
        res = ctrl.sell(drop["uid"])
        self.assertAlmostEqual(res["amount"], drop["value"], places=2)   # not 99x

    def test_open_then_inventory_in_payload(self):
        self.ctrl.state["balance"] = 10.0
        result = self.ctrl.open_case("clutch_case")
        payload = self.ctrl.state_payload()
        self.assertEqual(len(payload["inventory"]), 1)
        self.assertEqual(payload["inventory"][0]["uid"], result["drop"]["uid"])

    def test_daily_free_case_granted_once(self):
        first = self.ctrl.claim_daily()
        self.assertIsNotNone(first)
        self.assertIsNone(self.ctrl.claim_daily())  # same day -> no second grant
        self.assertEqual(self.ctrl.state_payload()["free_cases"], [first])

    def test_earning_a_card_grants_the_daily(self):
        self.ctrl.earn_for_card()
        self.assertEqual(len(self.ctrl.state["free_cases"]), 1)

    def test_payload_has_catalog_metadata(self):
        payload = self.ctrl.state_payload()
        self.assertIn("rarities", payload)
        self.assertIn("wear_tiers", payload)
        self.assertTrue(len(payload["cases"]) >= 1)


if __name__ == "__main__":
    unittest.main()
