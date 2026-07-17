# Friend Gifting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a player gift one skin to a named friend by pasting a `CS2GIFT-…` code into chat, with no server, no accounts, and offline-first preserved.

**Architecture:** A new pure-logic module `cs2_cases/gifting.py` (stdlib only, no Anki imports) encodes an inventory entry into a recipient-locked, CRC-checked, zlib+base64 code. `economy.py` gains the two inventory mutations (`gift_item` removes, `receive_item` reconstructs), `controller.py` orchestrates and persists, `ui.py` routes two new bridge actions, and `app.js` grows a FRIENDS tab plus a Gift button in the inventory selection bar. Python stays authoritative; JS stays presentation — the same split as the rest of the add-on.

**Tech Stack:** Python 3.9+ (Anki 23.10+/Qt6), stdlib only (`json`, `zlib`, `base64`, `binascii`, `secrets`, `re`). Vanilla ES5-style JS, no frameworks. `unittest`.

## Global Constraints

- **Trust-based, not enforced.** Codes are NOT signed and MUST NOT pretend to be secure. A player who wants to cheat edits their own save; signing would buy nothing. The recipient lock exists to stop a code pasted in a group chat being redeemed by five people — an accident, not an attacker.
- **No server, no accounts, no network.** `gifting.py` must import nothing outside the stdlib and must not import Anki (`aqt`/`anki`), matching `economy.py` / `unboxing.py` / `store.py`.
- **The code never carries `value` or `name`.** The recipient recomputes both locally via `unboxing.wear_tier()` and `unboxing.value_for()`. A doctored value in a code must be impossible, not merely ignored — the field does not exist in the payload.
- **Skins only.** Never gift currency.
- **Favourites cannot be gifted** — mirrors the existing sell/trade-up guard, message wording included.
- **No Cancel.** Generating a code removes the item permanently; every code is kept in a re-copyable Sent log. Escrow+cancel would allow accidental duplication.
- **Python authoritative, JS presentation.** All validation lives in Python. JS only renders and sends.
- Existing suite must stay green: `python3 -m unittest discover -s tests` (62 tests at plan time).
- Text must wrap, never truncate with `…` (existing project rule).
- Buttons square, no rounding (existing project rule; `.btn` class handles it).

## File Structure

| File | Responsibility |
|---|---|
| `cs2_cases/gifting.py` | **Create.** Player IDs, encode/decode, redeem validation. Pure, stdlib-only. |
| `cs2_cases/economy.py` | **Modify.** `new_state()` gains 3 keys; add `gift_item()`, `receive_item()`, `_catalog_item()`. |
| `cs2_cases/controller.py` | **Modify.** Add `gift()`, `redeem()`; expose `player_id` + `sent_gifts` in `state_payload()`. |
| `cs2_cases/ui.py` | **Modify.** Route `gift` and `redeem` bridge actions. |
| `cs2_cases/web/index.html` | **Modify.** Add FRIENDS tab button + `#view-friends` section. |
| `cs2_cases/web/app.js` | **Modify.** `renderFriends()`, Gift in selection bar, route the two replies. |
| `cs2_cases/web/styles.css` | **Modify.** Styles for the code box and sent log. |
| `tests/test_gifting.py` | **Create.** Encode/decode/validation. |
| `tests/test_economy.py` | **Modify.** Gift/receive inventory invariants. |
| `tests/test_controller.py` | **Modify.** Two-player round trip, persistence. |
| `README.md` | **Modify.** Document gifting + the trust model. |

Old saves migrate for free: `store._merge_defaults()` already backfills any key missing from `new_state()`.

---

### Task 1: `gifting.py` — player IDs, encode, decode, validation

**Files:**
- Create: `cs2_cases/gifting.py`
- Test: `tests/test_gifting.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `PREFIX: str = "CS2GIFT"`, `VERSION: int = 1`
  - `class GiftError(Exception)`
  - `new_player_id() -> str` — e.g. `"CS2-7F2A-9C4E"`
  - `ensure_player_id(state: Dict[str, Any]) -> str`
  - `encode(entry: Dict[str, Any], sender_id: str, recipient_id: str, nonce: Optional[str] = None) -> str`
  - `decode(code: str) -> Dict[str, Any]` — returns `{"n","to","fr","i"}` where `i` is `{"case_id","rarity","float","stattrak","item"}`
  - `check_redeemable(payload: Dict[str, Any], my_id: str, redeemed_nonces: Iterable[str]) -> None`
  - `normalize_id(value: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gifting.py`:

```python
"""Tests for the gift-code codec. Pure Python, no Anki import required."""
import os
import sys
import unittest

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_gifting -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cs2_cases.gifting'`

- [ ] **Step 3: Write the implementation**

Create `cs2_cases/gifting.py`:

```python
"""Friend gifting: encode one skin as a pasteable, recipient-locked code.

Pure logic (stdlib only, no Anki imports) so it is unit-testable and portable.

Trust model: codes are NOT signed and prove nothing about who sent them. That is
deliberate — currency here is minted by a local event in an open-source app on a
machine the player controls, so anyone determined to cheat edits their own save and
no signature would stop them. The recipient lock exists to stop the realistic
accident: a code pasted into a group chat being redeemed by everyone who sees it.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import zlib
from typing import Any, Dict, Iterable, Optional

PREFIX = "CS2GIFT"
VERSION = 1

_ID_RE = re.compile(r"^CS2-[0-9A-F]{4}-[0-9A-F]{4}$")


class GiftError(Exception):
    """Recoverable gifting error; the message is shown to the user verbatim."""


def new_player_id() -> str:
    """A routing identifier, not a credential: public and unauthenticated."""
    token = secrets.token_hex(4).upper()
    return "CS2-%s-%s" % (token[:4], token[4:])


def ensure_player_id(state: Dict[str, Any]) -> str:
    """Lazily mint this save's id. Kept out of new_state() so that stays deterministic."""
    if not state.get("player_id"):
        state["player_id"] = new_player_id()
    return state["player_id"]


def normalize_id(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def encode(entry: Dict[str, Any], sender_id: str, recipient_id: str,
           nonce: Optional[str] = None) -> str:
    """Pack an inventory entry into a code addressed to ``recipient_id``.

    Deliberately omits ``value`` and ``name``: the recipient recomputes both from
    their own price data, so an inflated value is not merely ignored but unsendable.
    """
    payload = {
        "n": nonce or secrets.token_hex(8),
        "to": normalize_id(recipient_id),
        "fr": normalize_id(sender_id),
        "i": {
            "case_id": entry["case_id"],
            "rarity": entry["rarity"],
            "float": entry["float"],
            "stattrak": bool(entry["stattrak"]),
            "item": entry["item"],
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    crc = format(binascii.crc32(raw) & 0xFFFFFFFF, "08x")
    return "%s-%d-%s-%s" % (PREFIX, VERSION, body, crc)


def decode(code: str) -> Dict[str, Any]:
    """Parse and integrity-check a code. Raises GiftError with a user-facing message."""
    text = re.sub(r"\s+", "", str(code or ""))
    if not text.startswith(PREFIX + "-"):
        raise GiftError("That doesn't look like a gift code.")
    parts = text.split("-", 2)
    if len(parts) != 3:
        raise GiftError("That code looks incomplete — copy the whole thing.")
    try:
        version = int(parts[1])
    except ValueError:
        raise GiftError("That doesn't look like a gift code.")
    if version != VERSION:
        raise GiftError("This code was made by a newer version of the add-on.")
    if "-" not in parts[2]:
        raise GiftError("That code looks incomplete — copy the whole thing.")
    # the body is urlsafe base64 and may itself contain '-', so split off the trailing crc
    body, crc = parts[2].rsplit("-", 1)
    try:
        packed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        raw = zlib.decompress(packed)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, zlib.error, ValueError):
        raise GiftError("That code looks incomplete — copy the whole thing.")
    if format(binascii.crc32(raw) & 0xFFFFFFFF, "08x") != crc.lower():
        raise GiftError("That code looks incomplete — copy the whole thing.")
    if not isinstance(payload, dict) or "i" not in payload or "n" not in payload:
        raise GiftError("That code looks incomplete — copy the whole thing.")
    return payload


def check_redeemable(payload: Dict[str, Any], my_id: str,
                     redeemed_nonces: Iterable[str]) -> None:
    """Raise GiftError unless this payload may be redeemed by ``my_id`` right now."""
    me = normalize_id(my_id)
    if normalize_id(payload.get("fr", "")) == me:
        raise GiftError("You can't redeem your own gift.")
    if normalize_id(payload.get("to", "")) != me:
        raise GiftError("This gift is for %s, not you." % payload.get("to", "someone else"))
    if payload.get("n") in set(redeemed_nonces):
        raise GiftError("You've already redeemed this gift.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_gifting -v`
Expected: PASS — 18 tests OK

- [ ] **Step 5: Verify the module stayed pure**

Run: `grep -nE "^(import|from)" cs2_cases/gifting.py`
Expected: only `__future__`, `base64`, `binascii`, `json`, `re`, `secrets`, `zlib`, `typing` — no `aqt`, no `anki`, no third-party.

- [ ] **Step 6: Commit**

```bash
git add cs2_cases/gifting.py tests/test_gifting.py
git commit -m "Add gift-code codec (recipient-locked, crc-checked)"
```

---

### Task 2: `economy` — gift and receive an item

**Files:**
- Modify: `cs2_cases/economy.py` (`new_state()` ~line 46; new functions after `set_favorite` ~line 202)
- Test: `tests/test_economy.py`

**Interfaces:**
- Consumes: `gifting.decode()`'s payload shape `{"n","to","fr","i":{"case_id","rarity","float","stattrak","item"}}` from Task 1.
- Produces:
  - `new_state()` additionally returns `"player_id": ""`, `"sent_gifts": []`, `"redeemed_nonces": []`
  - `gift_item(state: Dict[str, Any], uid: int) -> Dict[str, Any]` — pops and returns the entry; raises `EconomyError` on favourite, `ItemNotFound` on bad uid
  - `receive_item(state: Dict[str, Any], data: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]` — appends and returns the new entry, tagged `entry["from"]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_economy.py` (the file already imports `economy` and has a `load_dataset()` helper):

```python
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

    def test_receive_falls_back_to_the_embedded_item_for_an_unknown_case(self):
        # friend is on the starter set and has never seen this case
        payload = self._payload(case_id="no_such_case")
        recipient = economy.new_state()
        entry = economy.receive_item(recipient, self.data, payload)
        self.assertEqual(entry["item"]["id"], payload["i"]["item"]["id"])
        self.assertGreaterEqual(entry["value"], 0.0)

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_economy -v`
Expected: FAIL — `AttributeError: module 'cs2_cases.economy' has no attribute 'gift_item'`

- [ ] **Step 3: Add the three gifting keys to `new_state()`**

In `cs2_cases/economy.py`, change `new_state()` to include them (insert after the `"next_uid": 1,` line):

```python
        "next_uid": 1,
        "player_id": "",          # lazily minted by gifting.ensure_player_id()
        "sent_gifts": [],         # every code ever generated, so it can be re-copied
        "redeemed_nonces": [],    # replay guard for incoming gifts
```

- [ ] **Step 4: Add the gifting functions**

In `cs2_cases/economy.py`, append after `set_favorite()` (~line 202):

```python
# --- gifting ---------------------------------------------------------------

def _catalog_item(data: Dict[str, Any], case_id: str,
                  item_id: str) -> Optional[Dict[str, Any]]:
    """The recipient's own copy of a skin, whose prices are authoritative for them.
    Returns None when they don't have that case (e.g. still on the starter set)."""
    for case in data.get("cases", []):
        if case["id"] != case_id:
            continue
        for pool in case.get("items", {}).values():
            for item in pool:
                if item.get("id") == item_id:
                    return item
    return None


def gift_item(state: Dict[str, Any], uid: int) -> Dict[str, Any]:
    """Remove a skin from the inventory so it can be encoded into a gift code.

    There is no escrow and no cancel: the code *is* the item. Holding it locally
    while a code is outstanding would let the sender reclaim an already-redeemed
    gift and duplicate it.
    """
    idx = _index_of(state, uid)
    if state["inventory"][idx].get("favorite"):
        raise EconomyError("That skin is a favourite — unfavourite it to gift.")
    return state["inventory"].pop(idx)


def receive_item(state: Dict[str, Any], data: Dict[str, Any],
                 payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruct a gifted skin into the inventory.

    Wear, value and name are recomputed here from the float against *this* player's
    catalog and prices — the code carries none of them, so a sender cannot inflate
    what a gift is worth.
    """
    gift = payload["i"]
    item = _catalog_item(data, gift["case_id"], gift["item"].get("id")) or gift["item"]
    float_value = float(gift["float"])
    wear = unboxing.wear_tier(float_value, data["wear_tiers"])
    stattrak = bool(gift["stattrak"])
    drop = {
        "case_id": gift["case_id"],
        "item": item,
        "rarity": gift["rarity"],
        "rarity_meta": data.get("rarities", {}).get(gift["rarity"]),
        "wear": wear,
        "float": float_value,
        "stattrak": stattrak,
        "value": unboxing.value_for(item, wear["id"], stattrak),
    }
    entry = _entry_from_drop(state, drop)
    entry["from"] = payload.get("fr", "")
    state["inventory"].append(entry)
    return entry
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_economy -v`
Expected: PASS — all previously passing tests plus 10 new ones OK

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK (72 tests)

- [ ] **Step 7: Commit**

```bash
git add cs2_cases/economy.py tests/test_economy.py
git commit -m "Add gift/receive inventory moves with local value recomputation"
```

---

### Task 3: `controller` — orchestrate gift and redeem

**Files:**
- Modify: `cs2_cases/controller.py` (import line 11; new methods after `trade_up()` ~line 71; `state_payload()` ~line 78)
- Test: `tests/test_controller.py`

**Interfaces:**
- Consumes: `gifting.ensure_player_id/encode/decode/check_redeemable/GiftError/normalize_id` (Task 1); `economy.gift_item/receive_item` (Task 2).
- Produces:
  - `Controller.player_id() -> str`
  - `Controller.gift(uid: int, to_id: str) -> Dict[str, Any]` → `{"code","name","to"}`
  - `Controller.redeem(code: str) -> Dict[str, Any]` → `{"item": entry}`
  - `state_payload()` additionally returns `"player_id": str` and `"sent_gifts": List[{"code","name","to","date"}]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_controller.py`:

```python
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
```

Also add `gifting` to the import at the top of `tests/test_controller.py`:

```python
from cs2_cases import controller, economy, gifting
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_controller -v`
Expected: FAIL — `AttributeError: 'Controller' object has no attribute 'player_id'`

- [ ] **Step 3: Implement the controller methods**

In `cs2_cases/controller.py`, change the import on line 11:

```python
from . import economy, gifting, store
```

Append after `trade_up()` (~line 71):

```python
    # --- gifting ----------------------------------------------------------

    def player_id(self) -> str:
        """This save's routing id, minted on first use and then stable."""
        pid = gifting.ensure_player_id(self.state)
        self._save()
        return pid

    def gift(self, uid: int, to_id: str) -> Dict[str, Any]:
        """Turn a skin into a code addressed to a friend. The item leaves the
        inventory here and lives in the code from now on."""
        to_id = gifting.normalize_id(to_id)
        if not to_id:
            raise gifting.GiftError("Enter your friend's Player ID.")
        if not gifting._ID_RE.match(to_id):
            raise gifting.GiftError("That isn't a Player ID — it looks like CS2-7F2A-9C4E.")
        me = gifting.ensure_player_id(self.state)
        if to_id == me:
            raise gifting.GiftError("That's your own Player ID.")
        entry = economy.gift_item(self.state, int(uid))   # validates favourite/uid first
        code = gifting.encode(entry, me, to_id)
        self.state.setdefault("sent_gifts", []).insert(0, {
            "code": code, "name": entry["name"], "to": to_id,
            "date": date.today().isoformat(),
        })
        self._save()
        return {"code": code, "name": entry["name"], "to": to_id}

    def redeem(self, code: str) -> Dict[str, Any]:
        me = gifting.ensure_player_id(self.state)
        payload = gifting.decode(code)
        gifting.check_redeemable(payload, me, self.state.get("redeemed_nonces", []))
        entry = economy.receive_item(self.state, self.catalog, payload)
        self.state.setdefault("redeemed_nonces", []).append(payload["n"])
        self._save()
        return {"item": entry}
```

- [ ] **Step 4: Expose the read model**

In `cs2_cases/controller.py`, inside `state_payload()`'s returned dict, add after the `"free_cases": ...` line:

```python
            "player_id": self.state.get("player_id", ""),
            "sent_gifts": list(self.state.get("sent_gifts", [])),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_controller -v`
Expected: PASS — 11 new tests OK

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK (83 tests)

- [ ] **Step 7: Commit**

```bash
git add cs2_cases/controller.py tests/test_controller.py
git commit -m "Wire gifting through the controller with a persistent sent log"
```

---

### Task 4: `ui.py` — route the bridge actions

**Files:**
- Modify: `cs2_cases/ui.py` (import ~line 29; `_on_panel_bridge` ~line 184-232)

**Interfaces:**
- Consumes: `Controller.gift(uid, to_id)`, `Controller.redeem(code)` (Task 3).
- Produces: bridge actions `gift` → `{"code","name","to","state"}` and `redeem` → `{"item","state"}`, both wrapped in the existing `{"ok": ...}` envelope by the surrounding handler.

- [ ] **Step 1: Add the handlers**

In `cs2_cases/ui.py`, change the import on line 29 to include `gifting`:

```python
from . import data, economy, gifting
```

In `_on_panel_bridge`, add two branches immediately after the `favorite` branch (~line 207):

```python
        elif action == "gift":
            res = c.gift(args["uid"], args.get("to", ""))
            res["state"] = c.state_payload()
        elif action == "redeem":
            res = c.redeem(args.get("code", ""))
            res["state"] = c.state_payload()
```

- [ ] **Step 2: Confirm GiftError reaches the user as a toast**

Read the `except` block at the end of `_on_panel_bridge`. `GiftError` must be caught and returned as `{"ok": False, "error": str(e)}`.

Run: `sed -n '230,250p' cs2_cases/ui.py`
Expected: an `except` clause catching `economy.EconomyError` (or `Exception`). If it catches only `economy.EconomyError`, widen it to `except (economy.EconomyError, gifting.GiftError) as e:` so every message in the spec's error table reaches the toast. If it already catches `Exception`, leave it alone.

- [ ] **Step 3: Verify it compiles**

Run: `python3 -m py_compile cs2_cases/ui.py && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add cs2_cases/ui.py
git commit -m "Route gift/redeem over the panel bridge"
```

---

### Task 5: Web UI — FRIENDS tab and the Gift button

**Files:**
- Modify: `cs2_cases/web/index.html:5-19`
- Modify: `cs2_cases/web/app.js` (`render()` ~line 178, `renderSelBar()` ~line 463, `cs2.on` ~line 702)
- Modify: `cs2_cases/web/styles.css` (append)

**Interfaces:**
- Consumes: `state.player_id`, `state.sent_gifts` (Task 3); bridge actions `gift`, `redeem` (Task 4).
- Produces: no Python-facing interface.

- [ ] **Step 1: Add the tab and the view**

In `cs2_cases/web/index.html`, add the tab button after the Stats tab (line 9):

```html
      <button class="tab" data-view="friends">Friends</button>
```

and the view section after `#view-stats` (line 18):

```html
    <section id="view-friends" class="view hidden"></section>
```

- [ ] **Step 2: Route the view**

In `cs2_cases/web/app.js`, change `render()` (~line 178):

```js
  function render() {
    var v = currentView();
    if (v === "store") renderStore();
    else if (v === "inventory") renderInventory();
    else if (v === "tradeup") renderTradeUp();
    else if (v === "friends") renderFriends();
    else renderStats();
  }
```

- [ ] **Step 3: Add the Gift button to the selection bar**

In `cs2_cases/web/app.js`, in `renderSelBar()`, change the `bar.innerHTML` assignment to include a Gift button (only for a single selection — one code carries one skin):

```js
    bar.innerHTML =
      '<span class="count">' + n + " selected · $" + invSelValue().toFixed(2) + "</span>"
      + '<button class="btn sec small" id="sel-fav">' + (allFav ? "Unfavourite" : "Favourite") + "</button>"
      + (n === 1 ? '<button class="btn sec small" id="sel-gift">Gift</button>' : "")
      + '<button class="btn danger small" id="sel-sell">Sell selected</button>'
      + '<button class="btn sec small" id="sel-clear">Clear</button>';
```

and wire it directly after the existing `$("#sel-fav").onclick = ...` block:

```js
    var giftBtn = $("#sel-gift");
    if (giftBtn) giftBtn.onclick = function () {
      var uid = Number(Object.keys(_inv.sel)[0]);
      var to = window.prompt("Your friend's Player ID (they'll find it in their Friends tab):");
      if (to) cs2.send("gift", { uid: uid, to: to });
    };
```

- [ ] **Step 4: Add `renderFriends()`**

In `cs2_cases/web/app.js`, add before `renderSelBar()`:

```js
  function renderFriends() {
    var s = window.__state, el = $("#view-friends");
    var sent = s.sent_gifts || [];
    el.innerHTML =
      '<div class="section-title">Your Player ID<span class="note">give this to friends</span></div>'
      + '<div class="idbox"><code id="my-id">' + esc(s.player_id || "—") + "</code>"
      + '<button class="btn sec small" id="copy-id">Copy</button></div>'
      + '<div class="section-title">Redeem a gift<span class="note">paste a code from a friend</span></div>'
      + '<textarea id="redeem-box" class="codebox" rows="3" placeholder="CS2GIFT-1-…"></textarea>'
      + '<button class="btn small" id="redeem-go">Redeem</button>'
      + '<div class="section-title">Sent gifts<span class="note">' + sent.length + "</span></div>"
      + (sent.length
          ? sent.map(function (g, i) {
              return '<div class="sent">'
                + '<div class="sent-name">' + esc(g.name) + "</div>"
                + '<div class="sent-meta">to ' + esc(g.to) + " · " + esc(g.date) + "</div>"
                + '<button class="btn sec small copy-sent" data-i="' + i + '">Copy code</button>'
                + "</div>";
            }).join("")
          : '<div class="empty">Gift a skin from your inventory and the code shows up here. '
            + "It stays here forever, so you can always send it again.</div>");
    $("#copy-id").onclick = function () { copyText(s.player_id || ""); };
    $("#redeem-go").onclick = function () {
      var v = $("#redeem-box").value.trim();
      if (v) cs2.send("redeem", { code: v });
    };
    el.querySelectorAll(".copy-sent").forEach(function (b) {
      b.onclick = function () { copyText(sent[Number(b.getAttribute("data-i"))].code); };
    });
  }

  function copyText(text) {
    // Anki's webview has no clipboard permission prompt, but execCommand always works.
    var ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); toast("Copied."); }
    catch (e) { toast("Copy failed — select it by hand.", true); }
    document.body.removeChild(ta);
  }
```

- [ ] **Step 5: Handle the replies**

In `cs2_cases/web/app.js`, inside `cs2.on`, after the `sell_many` block (~line 719):

```js
      if (action === "gift") {
        _inv.sel = {};
        copyText(res.code);
        toast("Gift code for " + res.name + " copied — paste it to " + res.to + ".");
        setView("friends");
      }
      if (action === "redeem") {
        $("#redeem-box").value = "";
        toast("Received " + res.item.name + " from " + res.item.from + "!");
      }
```

- [ ] **Step 6: Show provenance in the inventory cell**

In `cs2_cases/web/app.js`, in `itemCellHtml(entry, extra)`, add a `from` line inside the `.info` block, directly after the `.skn` div:

```js
      + (entry.from ? '<div class="from">from ' + esc(entry.from) + "</div>" : "")
```

- [ ] **Step 7: Style it**

Append to `cs2_cases/web/styles.css`:

```css
/* ---- friends / gifting ---- */
.idbox { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; }
.idbox code {
  flex: 1; background: #0c1418; border: 1px solid var(--edge); padding: 8px 10px;
  font-family: var(--font); font-size: 14px; letter-spacing: 1.5px; color: var(--gold);
  overflow-wrap: anywhere;
}
.codebox {
  width: 100%; background: #0c1418; border: 1px solid var(--edge); color: #cddded;
  font-family: var(--font); font-size: 11px; padding: 8px; margin-bottom: 8px;
  resize: vertical; overflow-wrap: anywhere;
}
.sent {
  border: 1px solid var(--edge); border-left: 2px solid var(--gold);
  padding: 8px 10px; margin-bottom: 6px;
}
.sent-name { font-size: 12px; color: #fff; font-weight: 600; overflow-wrap: anywhere; }
.sent-meta { font-size: 10px; color: var(--muted); margin: 2px 0 6px; overflow-wrap: anywhere; }
.cell .from { font-size: 9px; color: var(--gold); letter-spacing: .3px; overflow-wrap: anywhere; }
.empty { color: var(--muted); font-size: 12px; line-height: 1.5; }
```

- [ ] **Step 8: Verify the JS parses**

Run: `node --check cs2_cases/web/app.js && echo OK`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add cs2_cases/web/
git commit -m "Add Friends tab: player id, redeem box, sent-gift log"
```

---

### Task 6: Docs, build, and end-to-end verification

**Files:**
- Modify: `README.md:21-34` (Use section), `README.md:101-111` (brainstorm backlog)
- Modify: `docs/superpowers/specs/2026-07-17-friend-gifting-design.md` (status line)

**Interfaces:**
- Consumes: everything above.
- Produces: a built `dist/cs2_cases.ankiaddon` containing `gifting.py`.

- [ ] **Step 1: Document it in the README**

In `README.md`, add to the bullet list in the **Use** section, after the Trade Up line:

```markdown
  - **Friends** — your Player ID, a box to redeem a friend's gift code, and every code
    you've sent (re-copyable forever).
- **Gifting:** select a skin in your inventory → **Gift** → paste your friend's Player ID.
  You get a `CS2GIFT-…` code to send them however you like; they paste it into their
  Friends tab and the skin lands in their inventory, tagged with your ID. Codes are locked
  to one recipient, work offline, and need no account or server. Favourites can't be
  gifted — unfavourite first. **There is no cancel: the code *is* the skin**, so it leaves
  your inventory when you generate it (it's kept in your Sent list, so it can't be lost).
```

- [ ] **Step 2: Replace the backlog item**

In `README.md`, in the "things alric is brainstorming" list, replace `- global marketplace to trade` with:

```markdown
- ~~global marketplace to trade~~ — dropped deliberately: earning happens locally in an
  open-source app, so no server can verify a review really happened and a single cheater
  would wreck a shared economy. Friend-to-friend gifting ships instead (see
  `docs/superpowers/specs/2026-07-17-friend-gifting-design.md`).
```

- [ ] **Step 3: Mark the spec shipped**

In `docs/superpowers/specs/2026-07-17-friend-gifting-design.md`, change the status line to:

```markdown
Status: implemented · Supersedes the "Phase 2: global marketplace" backlog item
```

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK (83 tests)

- [ ] **Step 5: Build and confirm the new module ships**

```bash
python3 scripts/build_ankiaddon.py
python3 -c "import zipfile; print('gifting.py' in zipfile.ZipFile('dist/cs2_cases.ankiaddon').namelist())"
```
Expected: build prints `27 files`, then `True`

- [ ] **Step 6: Prove a real two-player round trip**

```bash
python3 - <<'EOF'
import json, tempfile, os
from cs2_cases import controller
data = json.load(open('cs2_cases/data/cases.json'))
d = tempfile.mkdtemp()
cfg = {"muted": False, "reduced_motion": False}
a = controller.Controller(os.path.join(d, 'a.json'), cfg, data)
b = controller.Controller(os.path.join(d, 'b.json'), cfg, data)
a.state['balance'] = 10.0
uid = a.open_case('clutch_case')['drop']['uid']
name = a.state['inventory'][0]['name']
res = a.gift(uid, b.player_id())
print("code length:", len(res['code']), "chars")
print("sender inventory after gift:", len(a.state['inventory']))
got = b.redeem(res['code'])
print("recipient got:", got['item']['name'], "from", got['item']['from'])
assert got['item']['name'] == name and len(a.state['inventory']) == 0
try:
    b.redeem(res['code']); print("BUG: replay allowed")
except Exception as e:
    print("replay correctly rejected:", e)
EOF
```
Expected: code length prints (roughly 300-400 chars), sender inventory `0`, the recipient receives the same skin name, and the replay is rejected with "You've already redeemed this gift."

- [ ] **Step 7: Install into Anki and check by hand**

```bash
rsync -a --delete --exclude 'user_files/state.json' --exclude 'user_files/catalog.json' \
  --exclude 'user_files/assets/images' --exclude '__pycache__' \
  cs2_cases/ ~/Library/Application\ Support/Anki2/addons21/cs2_cases/
```
Then restart Anki and confirm: the **Friends** tab appears and shows a Player ID; selecting one inventory skin shows a **Gift** button (and selecting two hides it); gifting copies a code and the skin disappears; the Sent log lists it with a working **Copy code**; pasting a code addressed to someone else shows "This gift is for CS2-…, not you."; the tab bar still wraps rather than truncating at minimum sidebar width.

- [ ] **Step 8: Commit**

```bash
git add README.md docs/
git commit -m "Document friend gifting; retire the global-market backlog item"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `gifting.py`, stdlib-only, no Anki imports | 1 (Step 5 asserts it) |
| Code format `CS2GIFT-1-<b64>-<crc32>` | 1 |
| Payload `{n, to, fr, i{...}}`, no value/name | 1 (`test_code_never_carries_value_or_name`) |
| Player ID `CS2-XXXX-XXXX` via `secrets`, in `state["player_id"]` | 1, 2, 3 |
| Recipient recomputes wear/value locally | 2 (`test_receive_recomputes_value_from_the_local_catalog`) |
| Catalog-mismatch fallback to embedded item | 2 (`test_receive_falls_back_to_the_embedded_item_for_an_unknown_case`) |
| Favourites cannot be gifted | 2 (`test_cannot_gift_a_favourite`) |
| Every error-table message | 1 (decode/check_redeemable), 3 (recipient id), 2 (favourite) |
| Sent log, re-copyable, no cancel | 3 (`test_gift_is_recorded_in_the_sent_log_and_persists`), 5 |
| Replay guard + survives reload | 3 (`test_replay_guard_survives_reload`) |
| Gift removes exactly once / redeem adds exactly once | 2 (`test_gift_then_receive_conserves_exactly_one_item`) |
| Provenance `from <id>` shown in inventory | 2 (tag), 5 (Step 6 renders it) |
| FRIENDS tab: id + copy, redeem box, sent log | 5 |
| Gift action in inventory selection bar, single item only | 5 |
| Skins only, never currency | Enforced by omission — no code path touches `balance`; 2 asserts `test_gift_item_does_not_touch_balance` |
| Out of scope: swaps, currency, server, signing | Not implemented anywhere |

**Placeholder scan:** No TBD/TODO. Every code step carries complete code. Task 4 Step 2 is a conditional edit, but states both the condition and the exact replacement.

**Type consistency:** `encode(entry, sender_id, recipient_id, nonce=None)` takes a whole entry — matches Task 3's `gifting.encode(entry, me, to_id)`. `decode()` → `{"n","to","fr","i"}` is consumed identically by `check_redeemable` (Task 1), `economy.receive_item` (Task 2, reads `payload["i"]` and `payload["fr"]`), and `Controller.redeem` (Task 3, reads `payload["n"]`). `_ID_RE` is defined in Task 1 and used by Task 3. `state_payload()` keys `player_id`/`sent_gifts` (Task 3) match `s.player_id`/`s.sent_gifts` in `renderFriends()` (Task 5). `entry["from"]` (Task 2) matches `res.item.from` (Task 5 Step 5) and `entry.from` (Task 5 Step 6).

**One known coupling:** Task 3 uses `gifting._ID_RE`, a private name. Acceptable — same package, and the alternative (a public `is_player_id()`) is a wrapper with one caller. If a second caller ever appears, promote it.
