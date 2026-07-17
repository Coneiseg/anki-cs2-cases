"""Tests for the ByMykel catalog importer. Pure Python, no network."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import data, unboxing

CRATES = [
    {
        "id": "crate-1", "name": "Test Case", "type": "Case",
        "image": "https://cdn.example/case.png",
        "contains": [
            {"id": "skin-a", "name": "AK-47 | Redline",
             "rarity": {"id": "rarity_legendary_weapon", "name": "Classified"},
             "image": "https://cdn.example/a.png"},
            {"id": "skin-b", "name": "MP9 | Sand Dashed",
             "rarity": {"id": "rarity_rare_weapon", "name": "Mil-Spec Grade"},
             "image": "https://cdn.example/b.png"},
            {"id": "skin-c", "name": "AWP | Asiimov",
             "rarity": {"id": "rarity_ancient_weapon", "name": "Covert"},
             "image": "https://cdn.example/c.png"},
            {"id": "skin-d", "name": "Glock-18 | Water",
             "rarity": {"id": "rarity_mythical_weapon", "name": "Restricted"},
             "image": "https://cdn.example/d.png"},
        ],
        "contains_rare": [
            {"id": "knife-1", "name": "★ Karambit | Fade",
             "rarity": {"id": "rarity_ancient_weapon", "name": "Covert"},
             "image": "https://cdn.example/k.png"},
        ],
    },
    {"id": "sticker-1", "name": "Sticker Capsule", "type": "Sticker Capsule",
     "contains": [], "contains_rare": []},
]

SKINS = [
    {"id": "skin-a", "min_float": 0.0, "max_float": 0.5},
    {"id": "skin-c", "min_float": 0.1, "max_float": 0.7},
]


class ImporterTest(unittest.TestCase):
    def setUp(self):
        self.cat = data.build_catalog_from_bymykel(CRATES, SKINS)

    def test_only_case_type_included(self):
        self.assertEqual(len(self.cat["cases"]), 1)
        self.assertEqual(self.cat["cases"][0]["name"], "Test Case")

    def test_rarity_mapping_and_special_pool(self):
        items = self.cat["cases"][0]["items"]
        self.assertEqual(items["mil_spec"][0]["skin"], "Sand Dashed")
        self.assertEqual(items["restricted"][0]["weapon"], "Glock-18")
        self.assertEqual(items["classified"][0]["weapon"], "AK-47")
        self.assertEqual(items["covert"][0]["skin"], "Asiimov")
        self.assertEqual(items["special"][0]["weapon"], "★ Karambit")

    def test_float_caps_joined_when_available(self):
        classified = self.cat["cases"][0]["items"]["classified"][0]
        self.assertEqual(classified["min_float"], 0.0)
        self.assertEqual(classified["max_float"], 0.5)
        # skin-b had no entry in SKINS -> no float caps set (defaults apply at roll)
        mil = self.cat["cases"][0]["items"]["mil_spec"][0]
        self.assertNotIn("min_float", mil)

    def test_keeps_fixed_odds_from_template(self):
        self.assertAlmostEqual(self.cat["rarities"]["mil_spec"]["odds"], 0.7992)
        self.assertIn("wear_tiers", self.cat)

    def test_imported_case_is_rollable(self):
        case = self.cat["cases"][0]
        rng = random.Random(0)
        for _ in range(1000):
            drop = unboxing.roll(case, self.cat, rng=rng)
            self.assertIn(drop["rarity"], self.cat["rarities"])
            self.assertTrue(drop["item"]["id"])

    def test_values_are_graded_by_tier(self):
        items = self.cat["cases"][0]["items"]
        self.assertLess(items["mil_spec"][0]["base_value"], items["covert"][0]["base_value"])
        self.assertLess(items["covert"][0]["base_value"], items["special"][0]["base_value"])


if __name__ == "__main__":
    unittest.main()
