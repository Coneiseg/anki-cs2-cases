"""Tests for the economy engine. Pure Python, no Anki import required."""
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import economy, unboxing


def load_dataset():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cs2_cases", "data", "cases.json",
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def make_entry(state, rarity, case_id="clutch_case", value=1.0):
    """Craft a minimal inventory entry directly (bypasses RNG) for deterministic tests."""
    uid = state["next_uid"]
    state["next_uid"] += 1
    entry = {
        "uid": uid, "case_id": case_id,
        "item": {"id": "x", "weapon": "W", "skin": "S"},
        "rarity": rarity, "wear": {"id": "ft", "name": "Field-Tested"},
        "float": 0.2, "stattrak": False, "value": value, "name": "W | S (Field-Tested)",
    }
    state["inventory"].append(entry)
    return entry


class EarningTest(unittest.TestCase):
    def test_add_earnings_accumulates(self):
        state = economy.new_state()
        self.assertEqual(economy.add_earnings(state, 1.0), 1.0)
        self.assertEqual(economy.add_earnings(state, 1.0), 2.0)
        self.assertEqual(state["stats"]["earned"], 2.0)


class OpenCaseTest(unittest.TestCase):
    def setUp(self):
        self.data = load_dataset()
        self.state = economy.new_state()

    def test_open_deducts_price_and_adds_item(self):
        self.state["balance"] = 10.0
        result = economy.open_case(self.state, self.data, "clutch_case",
                                   rng=random.Random(3))
        self.assertEqual(self.state["balance"], round(10.0 - 2.5, 2))
        self.assertEqual(len(self.state["inventory"]), 1)
        self.assertEqual(result["drop"]["uid"], self.state["inventory"][0]["uid"])
        self.assertIn("reel", result)
        self.assertTrue(any(t["id"] == result["drop"]["item"]["id"]
                            for t in result["reel"]))

    def test_insufficient_funds_raises_and_no_mutation(self):
        self.state["balance"] = 1.0
        with self.assertRaises(economy.InsufficientFunds):
            economy.open_case(self.state, self.data, "clutch_case",
                              rng=random.Random(1))
        self.assertEqual(self.state["balance"], 1.0)
        self.assertEqual(len(self.state["inventory"]), 0)

    def test_unknown_case_raises(self):
        self.state["balance"] = 100.0
        with self.assertRaises(economy.EconomyError):
            economy.open_case(self.state, self.data, "no_such_case")

    def test_tracks_spent_and_best_drop(self):
        self.state["balance"] = 100.0
        for _ in range(20):
            economy.open_case(self.state, self.data, "clutch_case", rng=random.Random())
        stats = self.state["stats"]
        self.assertEqual(stats["spent"], round(20 * 2.5, 2))
        self.assertEqual(stats["cases_opened"], 20)
        # best_value must equal the max value actually in/ever in inventory history
        self.assertGreater(stats["best_value"], 0.0)
        self.assertTrue(stats["best_name"])
        self.assertGreaterEqual(stats["best_value"],
                                max(e["value"] for e in self.state["inventory"]))

    def test_tracks_pulls_per_rarity_and_gold_drought(self):
        self.state["balance"] = 1000.0
        for _ in range(60):
            economy.open_case(self.state, self.data, "clutch_case", rng=random.Random())
        st = self.state["stats"]
        self.assertEqual(sum(st["pulls"].values()), 60)          # every open counted
        for rarity in st["pulls"]:
            self.assertIn(rarity, self.data["rarities"])
        # drought counts opens since the last special, so it can't exceed total opens
        self.assertLessEqual(st["since_special"], 60)
        self.assertGreaterEqual(st["since_special"], 0)

    def test_gold_resets_drought(self):
        state = economy.new_state()
        state["stats"]["since_special"] = 42
        # craft a special drop straight into open_case's bookkeeping via trade_up path
        uids = [make_entry(state, "covert")["uid"] for _ in range(5)]
        economy.trade_up(state, self.data, uids, rng=random.Random(2))
        # trade-ups aren't unboxes, so the drought is untouched
        self.assertEqual(state["stats"]["since_special"], 42)

    def test_history_records_and_caps(self):
        self.state["balance"] = 1000.0
        for _ in range(60):
            economy.open_case(self.state, self.data, "clutch_case", rng=random.Random())
        hist = self.state["history"]
        self.assertEqual(len(hist), economy.HISTORY_LIMIT)  # capped at 50
        for h in hist:
            self.assertIn("name", h)
            self.assertIn("rarity", h)
            self.assertIn("value", h)

    def test_uids_are_unique(self):
        self.state["balance"] = 100.0
        uids = set()
        for _ in range(5):
            r = economy.open_case(self.state, self.data, "clutch_case",
                                  rng=random.Random())
            uids.add(r["drop"]["uid"])
        self.assertEqual(len(uids), 5)


class DailyFreeCaseTest(unittest.TestCase):
    def setUp(self):
        self.data = load_dataset()
        self.state = economy.new_state()

    def test_grants_once_per_day(self):
        got = economy.claim_daily(self.state, self.data, "2026-07-17", rng=random.Random(1))
        self.assertIsNotNone(got)
        self.assertEqual(self.state["free_cases"], [got])
        # same day again -> nothing new
        self.assertIsNone(economy.claim_daily(self.state, self.data, "2026-07-17"))
        self.assertEqual(len(self.state["free_cases"]), 1)
        # next day -> another one
        self.assertIsNotNone(economy.claim_daily(self.state, self.data, "2026-07-18",
                                                 rng=random.Random(2)))
        self.assertEqual(len(self.state["free_cases"]), 2)

    def test_free_open_costs_nothing_and_consumes_voucher(self):
        cid = economy.claim_daily(self.state, self.data, "2026-07-17", rng=random.Random(1))
        self.state["balance"] = 0.0  # broke, but the free case still opens
        res = economy.open_case(self.state, self.data, cid, rng=random.Random(3), free=True)
        self.assertEqual(self.state["balance"], 0.0)      # not charged
        self.assertEqual(self.state["free_cases"], [])    # voucher consumed
        self.assertEqual(self.state["stats"]["spent"], 0.0)  # free != spend
        self.assertEqual(len(self.state["inventory"]), 1)
        self.assertTrue(res["drop"]["uid"])

    def test_free_open_without_voucher_raises(self):
        self.state["balance"] = 100.0
        with self.assertRaises(economy.EconomyError):
            economy.open_case(self.state, self.data, "clutch_case", free=True)
        self.assertEqual(len(self.state["inventory"]), 0)


class SellTest(unittest.TestCase):
    def test_sell_credits_and_removes(self):
        state = economy.new_state()
        entry = make_entry(state, "restricted", value=4.0)
        res = economy.sell_item(state, entry["uid"], fraction=1.0)
        self.assertEqual(res["amount"], 4.0)
        self.assertEqual(state["balance"], 4.0)
        self.assertEqual(len(state["inventory"]), 0)

    def test_sell_fraction(self):
        state = economy.new_state()
        entry = make_entry(state, "restricted", value=10.0)
        res = economy.sell_item(state, entry["uid"], fraction=0.75)
        self.assertEqual(res["amount"], 7.5)

    def test_sell_unknown_raises(self):
        state = economy.new_state()
        with self.assertRaises(economy.ItemNotFound):
            economy.sell_item(state, 999)

    def test_bulk_sell_credits_sum_and_removes(self):
        state = economy.new_state()
        a = make_entry(state, "mil_spec", value=1.0)
        b = make_entry(state, "restricted", value=4.0)
        make_entry(state, "covert", value=20.0)  # keep this one
        res = economy.sell_items(state, [a["uid"], b["uid"]], fraction=1.0)
        self.assertEqual(res["amount"], 5.0)
        self.assertEqual(res["count"], 2)
        self.assertEqual(state["balance"], 5.0)
        self.assertEqual(len(state["inventory"]), 1)

    def test_favorite_blocks_single_sell(self):
        state = economy.new_state()
        e = make_entry(state, "covert", value=20.0)
        economy.set_favorite(state, [e["uid"]], True)
        with self.assertRaises(economy.EconomyError):
            economy.sell_item(state, e["uid"])
        self.assertEqual(len(state["inventory"]), 1)  # still there
        # unfavourite -> now sellable
        economy.set_favorite(state, [e["uid"]], False)
        economy.sell_item(state, e["uid"])
        self.assertEqual(len(state["inventory"]), 0)

    def test_bulk_sell_keeps_favorites(self):
        state = economy.new_state()
        a = make_entry(state, "mil_spec", value=1.0)
        fav = make_entry(state, "covert", value=50.0)
        economy.set_favorite(state, [fav["uid"]], True)
        res = economy.sell_items(state, [a["uid"], fav["uid"]], fraction=1.0)
        self.assertEqual(res["count"], 1)        # only the non-favourite sold
        self.assertEqual(res["protected"], 1)
        self.assertEqual(res["amount"], 1.0)     # favourite's value not credited
        self.assertEqual([e["uid"] for e in state["inventory"]], [fav["uid"]])

    def test_bulk_sell_unknown_uid_no_mutation(self):
        state = economy.new_state()
        a = make_entry(state, "mil_spec", value=1.0)
        with self.assertRaises(economy.ItemNotFound):
            economy.sell_items(state, [a["uid"], 999])
        self.assertEqual(len(state["inventory"]), 1)
        self.assertEqual(state["balance"], 0.0)


class TradeUpTest(unittest.TestCase):
    def setUp(self):
        self.data = load_dataset()
        self.state = economy.new_state()

    def test_ten_same_rarity_produce_one_higher(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(10)]
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(5))
        self.assertEqual(len(self.state["inventory"]), 1)
        out = self.state["inventory"][0]
        self.assertEqual(out["rarity"], "restricted")
        self.assertEqual(res["output"]["uid"], out["uid"])

    def test_wrong_count_raises(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(9)]
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)
        self.assertEqual(len(self.state["inventory"]), 9)  # unchanged

    def test_mixed_rarity_raises(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(9)]
        uids.append(make_entry(self.state, "restricted")["uid"])
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)

    def test_covert_trades_up_to_special_with_five(self):
        uids = [make_entry(self.state, "covert")["uid"] for _ in range(5)]
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(2))
        self.assertEqual(res["output"]["rarity"], "special")

    def test_covert_needs_five_not_ten(self):
        uids = [make_entry(self.state, "covert")["uid"] for _ in range(10)]
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)

    def test_special_is_top_tier_cannot_trade_up(self):
        uids = [make_entry(self.state, "special")["uid"] for _ in range(10)]
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)

    def test_favorites_cannot_be_traded_up(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(10)]
        economy.set_favorite(self.state, [uids[0]], True)
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)
        self.assertEqual(len(self.state["inventory"]), 10)  # nothing consumed
        # unfavourite -> contract goes through
        economy.set_favorite(self.state, [uids[0]], False)
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(1))
        self.assertEqual(res["output"]["rarity"], "restricted")

    def test_normal_contract_allows_mixed_stattrak(self):
        uids = []
        for i in range(10):
            e = make_entry(self.state, "mil_spec")
            e["stattrak"] = (i < 3)  # 3 StatTrak, 7 not -> allowed
            uids.append(e["uid"])
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(4))
        self.assertEqual(res["output"]["rarity"], "restricted")

    def test_all_stattrak_inputs_give_stattrak_output(self):
        uids = []
        for _ in range(10):
            e = make_entry(self.state, "mil_spec")
            e["stattrak"] = True
            uids.append(e["uid"])
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(1))
        self.assertTrue(res["output"]["stattrak"])  # 10/10 -> 100% chance

    def test_no_stattrak_inputs_give_plain_output(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(10)]
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(1))
        self.assertFalse(res["output"]["stattrak"])  # 0/10 -> 0% chance

    def test_stattrak_share_drives_output_rate(self):
        # 5 of 10 StatTrak -> output should be StatTrak roughly half the time
        hits = 0
        trials = 400
        for t in range(trials):
            state = economy.new_state()
            uids = []
            for i in range(10):
                e = make_entry(state, "mil_spec")
                e["stattrak"] = (i < 5)
                uids.append(e["uid"])
            res = economy.trade_up(state, self.data, uids, rng=random.Random(t))
            if res["output"]["stattrak"]:
                hits += 1
        self.assertAlmostEqual(hits / trials, 0.5, delta=0.08)

    def test_red_to_gold_rejects_mixed_stattrak(self):
        uids = []
        for i in range(5):
            e = make_entry(self.state, "covert")
            e["stattrak"] = (i == 0)  # mixed -> not allowed for red->gold
            uids.append(e["uid"])
        with self.assertRaises(economy.InvalidTradeUp):
            economy.trade_up(self.state, self.data, uids)
        self.assertEqual(len(self.state["inventory"]), 5)  # nothing consumed

    def test_float_is_averaged(self):
        uids = []
        for i in range(10):
            e = make_entry(self.state, "mil_spec")
            e["float"] = 0.5  # all inputs at 0.5
            uids.append(e["uid"])
        res = economy.trade_up(self.state, self.data, uids, rng=random.Random(1))
        out = res["output"]
        # output float = min + avg(0.5) * (max-min); with default [0,1] range that's 0.5
        self.assertAlmostEqual(out["float"], 0.5, places=6)

    def test_unknown_uid_raises_and_no_mutation(self):
        uids = [make_entry(self.state, "mil_spec")["uid"] for _ in range(9)]
        uids.append(999)
        with self.assertRaises(economy.ItemNotFound):
            economy.trade_up(self.state, self.data, uids)
        self.assertEqual(len(self.state["inventory"]), 9)


class GiftingEconomyTest(unittest.TestCase):
    def setUp(self):
        self.data = load_dataset()
        self.state = economy.new_state()
        self.state["balance"] = 10.0
        self.drop = economy.open_case(self.state, self.data, "clutch_case",
                                      random.Random(7))["drop"]
        self.uid = self.drop["uid"]

    def _payload(self, item_overrides=None, case_id=None):
        entry = self.state["inventory"][0]
        item = dict(entry["item"])
        item.update(item_overrides or {})
        return {"n": "abc123", "to": "CS2-2222-2222", "fr": "CS2-1111-1111",
                "i": {"case_id": case_id or entry["case_id"], "rarity": entry["rarity"],
                      "float": entry["float"], "stattrak": entry["stattrak"],
                      "item": item}}

    def test_new_state_has_gifting_fields(self):
        fresh = economy.new_state()
        self.assertEqual(fresh["player_id"], "")
        self.assertEqual(fresh["sent_gifts"], [])
        self.assertEqual(fresh["redeemed_nonces"], [])

    def test_gift_item_removes_it_from_inventory(self):
        entry = economy.gift_item(self.state, self.uid)
        self.assertEqual(entry["uid"], self.uid)
        self.assertEqual(self.state["inventory"], [])

    def test_gift_item_does_not_touch_balance(self):
        before = self.state["balance"]
        economy.gift_item(self.state, self.uid)
        self.assertEqual(self.state["balance"], before)

    def test_cannot_gift_a_favourite(self):
        economy.set_favorite(self.state, [self.uid], True)
        with self.assertRaises(economy.EconomyError) as cm:
            economy.gift_item(self.state, self.uid)
        self.assertIn("favourite", str(cm.exception))
        self.assertEqual(len(self.state["inventory"]), 1)  # still there

    def test_gift_unknown_uid_raises(self):
        with self.assertRaises(economy.ItemNotFound):
            economy.gift_item(self.state, 9999)

    def test_receive_item_appends_and_tags_provenance(self):
        payload = self._payload()
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertEqual(len(recipient["inventory"]), 1)
        self.assertEqual(entry["from"], "CS2-1111-1111")
        self.assertEqual(entry["item"]["id"], payload["i"]["item"]["id"])
        self.assertTrue(entry["name"])

    def test_receive_recomputes_value_from_the_local_catalog(self):
        # sender inflates their embedded copy; recipient must use their own catalog
        payload = self._payload({"base_value": 9999.0})
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertLess(entry["value"], 100.0)
        self.assertEqual(entry["value"], self.drop["value"])

    def test_a_forged_case_id_cannot_dodge_local_prices(self):
        # case_id is sender-supplied and unsigned; naming a case the recipient doesn't
        # have must not drop them through to the sender's inflated embedded copy
        payload = self._payload({"base_value": 9999.0}, case_id="no_such_case")
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertEqual(entry["value"], self.drop["value"])

    def test_receive_falls_back_to_the_embedded_item_for_an_unknown_skin(self):
        # friend is on a fuller catalog: this skin genuinely isn't in ours, so the
        # sender's copy is all we have. Trust-based by construction — assert we at
        # least reconstruct it faithfully rather than dropping the gift.
        payload = self._payload({"id": "skin-not-in-our-catalog", "base_value": 4.0,
                                 "prices": {}})
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertEqual(entry["item"]["id"], "skin-not-in-our-catalog")
        expected = unboxing.value_for(payload["i"]["item"], entry["wear"]["id"],
                                      entry["stattrak"])
        self.assertEqual(entry["value"], expected)

    def test_receive_derives_wear_from_float(self):
        payload = self._payload()
        payload["i"]["float"] = 0.02
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertEqual(entry["wear"]["id"], "fn")

    def test_gift_then_receive_conserves_exactly_one_item(self):
        payload = self._payload()
        economy.gift_item(self.state, self.uid)
        recipient = economy.new_state()
        economy.receive_item(recipient, self.data, payload)
        self.assertEqual(len(self.state["inventory"]), 0)
        self.assertEqual(len(recipient["inventory"]), 1)

    def test_trade_up_survives_an_input_from_a_case_we_do_not_have(self):
        # the default first-share case: a friend on the full catalog gifts a skin from
        # a case this player has never seen, and it must not poison their contract
        recipient = economy.new_state()
        recipient["balance"] = 50.0
        for _ in range(9):
            economy.open_case(recipient, self.data, "clutch_case", random.Random(3))
        mils = [e for e in recipient["inventory"] if e["rarity"] == "mil_spec"][:9]
        while len(mils) < 9:  # top up until we have 9 mil-specs
            economy.open_case(recipient, self.data, "clutch_case", random.Random(4))
            mils = [e for e in recipient["inventory"] if e["rarity"] == "mil_spec"][:9]
        payload = self._payload(case_id="a_case_we_never_heard_of")
        payload["i"]["rarity"] = "mil_spec"
        gifted = economy.receive_item(recipient, self.data, payload)
        uids = [gifted["uid"]] + [e["uid"] for e in mils]
        result = economy.trade_up(recipient, self.data, uids, random.Random(5))
        self.assertEqual(result["output"]["rarity"], "restricted")


if __name__ == "__main__":
    unittest.main()
