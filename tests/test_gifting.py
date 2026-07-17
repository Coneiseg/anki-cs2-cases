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
