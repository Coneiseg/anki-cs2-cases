"""Tests for the orchestration controller. Pure Python, no Anki import required."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import controller, economy, gifting


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

    def test_unclaimed_free_cases_accumulate_and_survive_restart(self):
        # skipping a day must never forfeit the case: vouchers stack and persist
        day1 = economy.claim_daily(self.ctrl.state, self.ctrl.catalog, "2026-07-15")
        day2 = economy.claim_daily(self.ctrl.state, self.ctrl.catalog, "2026-07-16")
        self.ctrl._save()
        reloaded = controller.Controller(self.path, self.config, load_dataset())
        self.assertEqual(reloaded.state["free_cases"], [day1, day2])

    def test_opening_a_free_case_consumes_only_one_voucher(self):
        economy.claim_daily(self.ctrl.state, self.ctrl.catalog, "2026-07-15")
        economy.claim_daily(self.ctrl.state, self.ctrl.catalog, "2026-07-16")
        held = list(self.ctrl.state["free_cases"])
        before = self.ctrl.state["balance"]
        self.ctrl.open_case(held[0], free=True)
        self.assertEqual(self.ctrl.state["free_cases"], held[1:])  # the other one stays
        self.assertEqual(self.ctrl.state["balance"], before)       # and it cost nothing

    def test_payload_has_catalog_metadata(self):
        payload = self.ctrl.state_payload()
        self.assertIn("rarities", payload)
        self.assertIn("wear_tiers", payload)
        self.assertTrue(len(payload["cases"]) >= 1)


class GiftingControllerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.config = {"muted": False, "reduced_motion": False}
        self.a = controller.Controller(os.path.join(self.dir, "a.json"),
                                       self.config, load_dataset())
        self.b = controller.Controller(os.path.join(self.dir, "b.json"),
                                       self.config, load_dataset())
        self.a.state["balance"] = 10.0
        self.uid = self.a.open_case("clutch_case")["drop"]["uid"]

    def test_player_ids_are_minted_and_differ(self):
        self.assertNotEqual(self.a.player_id(), self.b.player_id())

    def test_player_id_survives_reload(self):
        pid = self.a.player_id()
        reloaded = controller.Controller(self.a.state_path, self.config, load_dataset())
        self.assertEqual(reloaded.player_id(), pid)

    def test_gift_then_redeem_moves_the_skin(self):
        name = self.a.state["inventory"][0]["name"]
        res = self.a.gift(self.uid, self.b.player_id())
        self.assertEqual(self.a.state["inventory"], [])       # left the sender
        got = self.b.redeem(res["code"])
        self.assertEqual(len(self.b.state["inventory"]), 1)   # arrived
        self.assertEqual(got["item"]["name"], name)
        self.assertEqual(got["item"]["from"], self.a.player_id())

    def test_gift_is_recorded_in_the_sent_log_and_persists(self):
        res = self.a.gift(self.uid, self.b.player_id())
        reloaded = controller.Controller(self.a.state_path, self.config, load_dataset())
        log = reloaded.state_payload()["sent_gifts"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["code"], res["code"])       # re-copyable forever
        self.assertEqual(log[0]["to"], self.b.player_id())

    def test_redeeming_twice_fails_and_adds_nothing(self):
        res = self.a.gift(self.uid, self.b.player_id())
        self.b.redeem(res["code"])
        with self.assertRaises(gifting.GiftError):
            self.b.redeem(res["code"])
        self.assertEqual(len(self.b.state["inventory"]), 1)

    def test_replay_guard_survives_reload(self):
        res = self.a.gift(self.uid, self.b.player_id())
        self.b.redeem(res["code"])
        reloaded = controller.Controller(self.b.state_path, self.config, load_dataset())
        with self.assertRaises(gifting.GiftError):
            reloaded.redeem(res["code"])

    def test_a_third_player_cannot_redeem(self):
        c = controller.Controller(os.path.join(self.dir, "c.json"),
                                  self.config, load_dataset())
        res = self.a.gift(self.uid, self.b.player_id())
        with self.assertRaises(gifting.GiftError):
            c.redeem(res["code"])
        self.assertEqual(len(c.state["inventory"]), 0)

    def test_cannot_gift_to_yourself(self):
        with self.assertRaises(gifting.GiftError):
            self.a.gift(self.uid, self.a.player_id())
        self.assertEqual(len(self.a.state["inventory"]), 1)  # not consumed

    def test_gift_requires_a_recipient_id(self):
        with self.assertRaises(gifting.GiftError):
            self.a.gift(self.uid, "   ")
        self.assertEqual(len(self.a.state["inventory"]), 1)

    def test_gift_rejects_a_malformed_recipient_id(self):
        with self.assertRaises(gifting.GiftError):
            self.a.gift(self.uid, "not-an-id")
        self.assertEqual(len(self.a.state["inventory"]), 1)

    def test_payload_exposes_player_id_and_sent_log(self):
        payload = self.a.state_payload()
        self.assertIn("player_id", payload)
        self.assertIn("sent_gifts", payload)


if __name__ == "__main__":
    unittest.main()
