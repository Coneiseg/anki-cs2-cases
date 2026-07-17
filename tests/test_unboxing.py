"""Tests for the unboxing engine. Pure Python, no Anki import required."""
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import unboxing


def load_dataset():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cs2_cases", "data", "cases.json",
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class WearBandTest(unittest.TestCase):
    def setUp(self):
        self.tiers = load_dataset()["wear_tiers"]

    def test_boundaries_map_to_expected_tier(self):
        cases = [
            (0.00, "fn"), (0.0699, "fn"),
            (0.07, "mw"), (0.1499, "mw"),
            (0.15, "ft"), (0.3799, "ft"),
            (0.38, "ww"), (0.4499, "ww"),
            (0.45, "bs"), (1.00, "bs"),
        ]
        for value, expected in cases:
            self.assertEqual(unboxing.wear_tier(value, self.tiers)["id"], expected,
                             msg="float %.4f should be %s" % (value, expected))


class ValueForTest(unittest.TestCase):
    def test_exact_real_price_used(self):
        item = {"base_value": 1.0, "prices": {"ft": 43.28, "st_ft": 90.0, "fn": 100.0}}
        self.assertEqual(unboxing.value_for(item, "ft", False), 43.28)
        self.assertEqual(unboxing.value_for(item, "ft", True), 90.0)
        self.assertEqual(unboxing.value_for(item, "fn", False), 100.0)

    def test_stattrak_missing_uses_premium_on_base_wear(self):
        item = {"base_value": 1.0, "prices": {"ft": 40.0}}
        # no st_ft -> 40 * STATTRAK multiplier
        self.assertEqual(unboxing.value_for(item, "ft", True),
                         round(40.0 * unboxing.STATTRAK_VALUE_MULTIPLIER, 2))

    def test_nearest_wear_fallback(self):
        item = {"base_value": 1.0, "prices": {"bs": 5.0}}  # only BS priced
        self.assertEqual(unboxing.value_for(item, "fn", False), 5.0)

    def test_no_prices_falls_back_to_synthetic(self):
        item = {"base_value": 10.0}  # no prices -> synthetic model
        self.assertEqual(unboxing.value_for(item, "fn", False),
                         round(unboxing.compute_value(item, "fn", False), 2))


class RollDeterminismTest(unittest.TestCase):
    def setUp(self):
        self.data = load_dataset()
        self.case = self.data["cases"][0]

    def test_same_seed_same_result(self):
        a = unboxing.roll(self.case, self.data, rng=random.Random(1234))
        b = unboxing.roll(self.case, self.data, rng=random.Random(1234))
        self.assertEqual(a["item"]["id"], b["item"]["id"])
        self.assertEqual(a["float"], b["float"])
        self.assertEqual(a["stattrak"], b["stattrak"])

    def test_result_shape(self):
        drop = unboxing.roll(self.case, self.data, rng=random.Random(1))
        for key in ("item", "rarity", "wear", "float", "stattrak", "value", "case_id"):
            self.assertIn(key, drop)
        self.assertIn(drop["rarity"], self.data["rarities"])
        self.assertGreaterEqual(drop["float"], 0.0)
        self.assertLessEqual(drop["float"], 1.0)
        self.assertIsInstance(drop["stattrak"], bool)


class EmptyTierFallbackTest(unittest.TestCase):
    def test_roll_never_crashes_on_empty_tier(self):
        data = load_dataset()
        # A case whose common tier is empty (e.g. hand-edited/partial catalog).
        case = {
            "id": "sparse",
            "items": {
                "mil_spec": [],
                "restricted": [{"id": "r1", "weapon": "W", "skin": "S", "base_value": 1.0}],
                "classified": [],
                "covert": [],
                "special": [],
            },
        }
        rng = random.Random(1)
        for _ in range(500):
            drop = unboxing.roll(case, data, rng=rng)
            self.assertIn(drop["rarity"], data["rarities"])
            self.assertTrue(drop["item"])  # always resolves to a real item


class RarityDistributionTest(unittest.TestCase):
    def test_distribution_matches_configured_odds(self):
        data = load_dataset()
        case = data["cases"][0]
        rng = random.Random(42)
        n = 200000
        counts = {r: 0 for r in data["rarities"]}
        for _ in range(n):
            counts[unboxing.roll(case, data, rng=rng)["rarity"]] += 1
        for rarity, meta in data["rarities"].items():
            observed = counts[rarity] / n
            expected = meta["odds"]
            # 4-sigma-ish tolerance; special tier is rare so allow a wider absolute floor
            tol = max(0.01, 4 * (expected * (1 - expected) / n) ** 0.5)
            self.assertAlmostEqual(observed, expected, delta=tol,
                                   msg="%s observed %.4f vs expected %.4f" %
                                       (rarity, observed, expected))

    def test_stattrak_roughly_ten_percent(self):
        data = load_dataset()
        case = data["cases"][0]
        rng = random.Random(7)
        n = 100000
        st = sum(1 for _ in range(n)
                 if unboxing.roll(case, data, rng=rng)["stattrak"])
        self.assertAlmostEqual(st / n, data["stattrak_odds"], delta=0.01)


if __name__ == "__main__":
    unittest.main()
