"""Tests for the gift-code codec. Pure Python, no Anki import required."""
import base64
import binascii
import json
import os
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cs2_cases import gifting


def make_entry():
    """An inventory entry shaped exactly like economy._entry_from_drop() produces."""
    return {
        "uid": 3,
        "case_id": "clutch_case",
        "item": {"id": "cc_mp9_black_sand", "weapon": "MP9", "skin": "Black Sand",
                 "base_value": 0.18, "prices": {"ww": 0.14}},
        "rarity": "mil_spec",
        "rarity_meta": {"name": "Mil-Spec", "color": "#4b69ff", "odds": 0.7992},
        "wear": {"id": "ww", "name": "Well-Worn", "max": 0.45},
        "float": 0.3948234964231735,
        "stattrak": True,
        "value": 0.14,
        "name": "StatTrak™ MP9 | Black Sand (Well-Worn)",
    }


class PlayerIdTest(unittest.TestCase):
    def test_new_player_id_shape(self):
        pid = gifting.new_player_id()
        self.assertRegex(pid, r"^CS2-[0-9A-F]{4}-[0-9A-F]{4}$")

    def test_ids_are_unique(self):
        ids = {gifting.new_player_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_ensure_player_id_is_stable(self):
        state = {}
        first = gifting.ensure_player_id(state)
        self.assertEqual(gifting.ensure_player_id(state), first)
        self.assertEqual(state["player_id"], first)

    def test_normalize_id_is_case_and_space_insensitive(self):
        self.assertEqual(gifting.normalize_id("  cs2-7f2a-9c4e \n"), "CS2-7F2A-9C4E")

    def test_is_player_id_accepts_a_real_id(self):
        self.assertTrue(gifting.is_player_id(gifting.new_player_id()))
        self.assertTrue(gifting.is_player_id("  cs2-7f2a-9c4e  "))

    def test_is_player_id_rejects_junk(self):
        for bad in ("", "not-an-id", "CS2-7F2A", "CS2-ZZZZ-9C4E", "7F2A-9C4E"):
            self.assertFalse(gifting.is_player_id(bad), bad)


class EncodeDecodeTest(unittest.TestCase):
    def setUp(self):
        self.entry = make_entry()
        self.code = gifting.encode(self.entry, "CS2-1111-1111", "CS2-2222-2222")

    def test_code_is_prefixed_and_versioned(self):
        self.assertTrue(self.code.startswith("CS2GIFT-1-"))

    def test_round_trip_preserves_the_skin(self):
        p = gifting.decode(self.code)
        self.assertEqual(p["to"], "CS2-2222-2222")
        self.assertEqual(p["fr"], "CS2-1111-1111")
        self.assertEqual(p["i"]["case_id"], "clutch_case")
        self.assertEqual(p["i"]["rarity"], "mil_spec")
        self.assertEqual(p["i"]["stattrak"], True)
        self.assertAlmostEqual(p["i"]["float"], self.entry["float"], places=12)
        self.assertEqual(p["i"]["item"]["id"], "cc_mp9_black_sand")

    def test_code_never_carries_value_or_name(self):
        # the recipient must recompute these; a doctored value must be unrepresentable
        p = gifting.decode(self.code)
        self.assertNotIn("value", p["i"])
        self.assertNotIn("name", p["i"])
        self.assertNotIn("value", p["i"]["item"])

    def test_recipient_id_is_normalized(self):
        code = gifting.encode(self.entry, "CS2-1111-1111", " cs2-2222-2222 ")
        self.assertEqual(gifting.decode(code)["to"], "CS2-2222-2222")

    def test_nonces_differ_between_codes(self):
        other = gifting.encode(self.entry, "CS2-1111-1111", "CS2-2222-2222")
        self.assertNotEqual(gifting.decode(self.code)["n"], gifting.decode(other)["n"])

    def test_whitespace_and_newlines_are_tolerated(self):
        # chat clients wrap long codes across lines
        mangled = self.code[:20] + "\n  " + self.code[20:] + "\n"
        self.assertEqual(gifting.decode(mangled)["n"], gifting.decode(self.code)["n"])

    def test_code_never_carries_an_image_url(self):
        # an attacker-supplied image would be fetched by the recipient's webview,
        # leaking their IP and breaking the add-on's offline guarantee
        entry = make_entry()
        entry["item"]["image"] = "https://tracker.example.com/pixel.png"
        code = gifting.encode(entry, "CS2-1111-1111", "CS2-2222-2222")
        self.assertNotIn("image", gifting.decode(code)["i"]["item"])
        self.assertNotIn("tracker.example.com", code)

    def test_code_keeps_the_fields_valuation_needs(self):
        p = gifting.decode(gifting.encode(make_entry(), "CS2-1111-1111", "CS2-2222-2222"))
        for key in ("id", "weapon", "skin", "base_value", "prices"):
            self.assertIn(key, p["i"]["item"])


class DecodeRejectionTest(unittest.TestCase):
    def setUp(self):
        self.code = gifting.encode(make_entry(), "CS2-1111-1111", "CS2-2222-2222")

    def test_rejects_non_code(self):
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.decode("hello friend")
        self.assertIn("doesn't look like", str(cm.exception))

    def test_rejects_empty(self):
        with self.assertRaises(gifting.GiftError):
            gifting.decode("")

    def test_rejects_future_version(self):
        body = self.code.split("-", 2)[2]
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.decode("CS2GIFT-99-" + body)
        self.assertIn("newer version", str(cm.exception))

    def test_rejects_truncated_code(self):
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.decode(self.code[:-12])
        self.assertIn("incomplete", str(cm.exception))

    def test_rejects_corrupted_body(self):
        head, crc = self.code.rsplit("-", 1)
        flipped = head[:-3] + ("A" if head[-3] != "A" else "B") + head[-2:]
        with self.assertRaises(gifting.GiftError):
            gifting.decode(flipped + "-" + crc)

    def test_rejects_deeply_nested_json_without_blowing_the_stack(self):
        # a ~100-char code can nest deeply enough to raise RecursionError inside
        # json.loads; decode()'s contract is that pasted text yields data or GiftError
        raw = (b"[" * 20000) + (b"]" * 20000)
        body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")
        crc = format(binascii.crc32(raw) & 0xFFFFFFFF, "08x")
        with self.assertRaises(gifting.GiftError):
            gifting.decode("CS2GIFT-1-%s-%s" % (body, crc))


class DecodeShapeTest(unittest.TestCase):
    """A valid CRC proves nothing: codes are unsigned, so anyone can craft one."""

    def _code_for(self, payload):
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
        crc = format(binascii.crc32(raw) & 0xFFFFFFFF, "08x")
        return "CS2GIFT-1-%s-%s" % (body, crc)

    def _valid(self):
        return {"n": "deadbeef", "to": "CS2-2222-2222", "fr": "CS2-1111-1111",
                "i": {"case_id": "clutch_case", "rarity": "mil_spec", "float": 0.3,
                      "stattrak": False, "item": {"id": "cc_mp9_black_sand"}}}

    def test_the_control_payload_decodes(self):
        # guards the rejection tests below from passing for the wrong reason
        self.assertEqual(gifting.decode(self._code_for(self._valid()))["n"], "deadbeef")

    def test_rejects_empty_item_payload(self):
        p = self._valid(); p["i"] = {}
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_non_dict_payload(self):
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for([1, 2, 3]))

    def test_rejects_missing_recipient(self):
        p = self._valid(); del p["to"]
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_item_without_an_id(self):
        p = self._valid(); p["i"]["item"] = {"weapon": "AK-47"}
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_non_numeric_float(self):
        p = self._valid(); p["i"]["float"] = "shiny"
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_boolean_float(self):
        # bool is an int subclass; True must not sneak through as 1.0
        p = self._valid(); p["i"]["float"] = True
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_non_bool_stattrak(self):
        p = self._valid(); p["i"]["stattrak"] = "yes"
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_prices_that_are_not_a_dict(self):
        for bad in (["ft"], "left", 3):
            p = self._valid(); p["i"]["item"]["prices"] = bad
            with self.assertRaises(gifting.GiftError):
                gifting.decode(self._code_for(p))

    def test_rejects_a_non_numeric_price(self):
        p = self._valid(); p["i"]["item"]["prices"] = {"ft": "not-a-number"}
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_a_boolean_price(self):
        p = self._valid(); p["i"]["item"]["prices"] = {"ft": True}
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_rejects_a_non_numeric_base_value(self):
        p = self._valid(); p["i"]["item"]["base_value"] = "abc"
        with self.assertRaises(gifting.GiftError):
            gifting.decode(self._code_for(p))

    def test_accepts_an_item_with_no_prices(self):
        # starter-set items legitimately carry base_value only
        p = self._valid(); p["i"]["item"] = {"id": "cc_mp9_black_sand", "base_value": 0.18}
        self.assertEqual(gifting.decode(self._code_for(p))["n"], "deadbeef")

    def test_accepts_a_real_priced_item(self):
        p = self._valid()
        p["i"]["item"] = {"id": "skin-2ca8", "base_value": 0.41,
                          "prices": {"mw": 27.57, "st_mw": 28.66}}
        self.assertEqual(gifting.decode(self._code_for(p))["n"], "deadbeef")

    def test_rejects_numbers_too_large_to_be_floats(self):
        # Python ints are unbounded and JSON caps nothing: float() raises OverflowError
        huge = 10 ** 400
        for build in (lambda p: p["i"].__setitem__("float", huge),
                      lambda p: p["i"]["item"].__setitem__("base_value", huge),
                      lambda p: p["i"]["item"].__setitem__("prices", {"ft": huge})):
            p = self._valid()
            build(p)
            with self.assertRaises(gifting.GiftError):
                gifting.decode(self._code_for(p))

    def test_rejects_nan_and_infinity(self):
        # json.loads accepts these non-standard literals; an Infinity price would sell
        # for an infinite balance that no later play can undo
        for bad in (float("nan"), float("inf"), float("-inf")):
            for build in (lambda p, b=bad: p["i"].__setitem__("float", b),
                          lambda p, b=bad: p["i"]["item"].__setitem__("base_value", b),
                          lambda p, b=bad: p["i"]["item"].__setitem__("prices", {"ft": b})):
                p = self._valid()
                build(p)
                with self.assertRaises(gifting.GiftError):
                    gifting.decode(self._code_for(p))

    def test_decode_strips_an_image_url_from_a_crafted_code(self):
        # codes are unsigned: an attacker hand-builds the JSON and never calls encode(),
        # so the allow-list has to be enforced here, at the trust boundary. app.js would
        # otherwise put this straight into an <img src> and leak the recipient's IP.
        p = self._valid()
        p["i"]["item"]["image"] = "https://tracker.example.com/pixel.png?id=victim"
        self.assertNotIn("image", gifting.decode(self._code_for(p))["i"]["item"])

    def test_decode_strips_unknown_fields_from_a_crafted_code(self):
        p = self._valid()
        p["i"]["item"]["surprise"] = {"nested": [1, 2, 3]}
        item = gifting.decode(self._code_for(p))["i"]["item"]
        self.assertNotIn("surprise", item)
        self.assertEqual(item["id"], "cc_mp9_black_sand")   # real fields still arrive

    def test_still_accepts_ordinary_numbers(self):
        # guard against over-rejecting: ints, floats and zero are all legitimate
        p = self._valid()
        p["i"]["float"] = 0
        p["i"]["item"]["base_value"] = 3
        p["i"]["item"]["prices"] = {"ft": 0.0, "st_ft": 27.57}
        self.assertEqual(gifting.decode(self._code_for(p))["n"], "deadbeef")

    def test_rejects_prices_beyond_the_plausible_domain(self):
        # merely-large finite values overflow to inf once value_for() applies the
        # StatTrak premium; the priciest real skin is ~$2,212
        for build in (lambda p: p["i"]["item"].__setitem__("base_value", 1.7e308),
                      lambda p: p["i"]["item"].__setitem__("prices", {"ft": 1e308}),
                      lambda p: p["i"]["item"].__setitem__("base_value", gifting.MAX_MONEY + 1)):
            p = self._valid()
            build(p)
            with self.assertRaises(gifting.GiftError):
                gifting.decode(self._code_for(p))

    def test_rejects_negative_prices(self):
        # a negative price would drain the recipient's balance on sale
        for build in (lambda p: p["i"]["item"].__setitem__("base_value", -1.0),
                      lambda p: p["i"]["item"].__setitem__("prices", {"ft": -1e9})):
            p = self._valid()
            build(p)
            with self.assertRaises(gifting.GiftError):
                gifting.decode(self._code_for(p))

    def test_accepts_the_priciest_real_skin(self):
        # guard against a bound set too tight: a StatTrak Butterfly Knife really is $2,212
        p = self._valid()
        p["i"]["item"]["prices"] = {"mw": 2212.09, "st_mw": 2212.09}
        self.assertEqual(gifting.decode(self._code_for(p))["n"], "deadbeef")

    def test_rejects_wear_floats_outside_zero_to_one(self):
        for bad in (-0.5, 1.5, -1e6):
            p = self._valid(); p["i"]["float"] = bad
            with self.assertRaises(gifting.GiftError):
                gifting.decode(self._code_for(p))

    def test_accepts_wear_floats_at_the_boundaries(self):
        for ok in (0, 0.0, 1.0, 0.9999):
            p = self._valid(); p["i"]["float"] = ok
            self.assertEqual(gifting.decode(self._code_for(p))["n"], "deadbeef")


class CheckRedeemableTest(unittest.TestCase):
    def setUp(self):
        self.payload = gifting.decode(
            gifting.encode(make_entry(), "CS2-1111-1111", "CS2-2222-2222"))

    def test_accepts_the_named_recipient(self):
        gifting.check_redeemable(self.payload, "CS2-2222-2222", [])  # must not raise

    def test_rejects_wrong_recipient(self):
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.check_redeemable(self.payload, "CS2-9999-9999", [])
        self.assertIn("CS2-2222-2222", str(cm.exception))

    def test_rejects_self_gift(self):
        payload = gifting.decode(
            gifting.encode(make_entry(), "CS2-1111-1111", "CS2-1111-1111"))
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.check_redeemable(payload, "CS2-1111-1111", [])
        self.assertIn("your own", str(cm.exception))

    def test_rejects_replayed_nonce(self):
        with self.assertRaises(gifting.GiftError) as cm:
            gifting.check_redeemable(self.payload, "CS2-2222-2222", [self.payload["n"]])
        self.assertIn("already redeemed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
