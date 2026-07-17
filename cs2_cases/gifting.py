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
import math
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


def is_player_id(value: str) -> bool:
    """True if ``value`` is shaped like a Player ID (after normalizing case/space)."""
    return bool(_ID_RE.match(normalize_id(value)))


# Only these fields travel. Notably absent: `image`. The recipient either has the skin
# (and uses their own catalog copy, image and all) or doesn't (and the UI falls back to
# a weapon-name placeholder) — whereas an attacker-supplied image URL would be fetched
# by the recipient's webview, leaking their IP to a stranger and breaking the add-on's
# offline guarantee.
_ITEM_FIELDS = ("id", "weapon", "skin", "base_value", "prices", "min_float", "max_float")


def _portable_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: item[k] for k in _ITEM_FIELDS if k in item}


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
            "item": _portable_item(entry["item"]),
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
        # RecursionError: deeply-nested JSON blows the stack inside json.loads, and a
        # ~100-char code is enough to trigger it. This function's contract is that any
        # pasted text becomes data or a GiftError, so it must not escape.
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, zlib.error, ValueError, RecursionError):
        raise GiftError("That code looks incomplete — copy the whole thing.")
    if format(binascii.crc32(raw) & 0xFFFFFFFF, "08x") != crc.lower():
        raise GiftError("That code looks incomplete — copy the whole thing.")
    _check_shape(payload)
    return payload


def _check_shape(payload: Any) -> None:
    """Reject a structurally wrong payload here, at the trust boundary.

    Codes are unsigned, so a well-formed CRC proves nothing about the contents: anyone
    can craft one carrying an empty or malformed body. decode()'s contract is that any
    pasted text becomes data or a GiftError, so every field the rest of the engine
    dereferences must be checked once, here, rather than blowing up as a KeyError or
    TypeError deep inside the economy (where Anki would surface it as an error dialog).
    """
    if not isinstance(payload, dict):
        raise GiftError("That gift code is corrupted.")
    gift = payload.get("i")
    if not isinstance(gift, dict):
        raise GiftError("That gift code is corrupted.")
    for key in ("n", "to", "fr"):
        if not isinstance(payload.get(key), str):
            raise GiftError("That gift code is corrupted.")
    for key in ("case_id", "rarity"):
        if not isinstance(gift.get(key), str):
            raise GiftError("That gift code is corrupted.")
    if not isinstance(gift.get("stattrak"), bool):
        raise GiftError("That gift code is corrupted.")
    if not _is_wear_float(gift.get("float")):
        raise GiftError("That gift code is corrupted.")
    _check_item(gift.get("item"))


# Generous by ~450x: the priciest thing in the real catalog is a StatTrak Butterfly
# Knife at ~$2,212. Anything above this is a crafted code, not a skin.
MAX_MONEY = 1_000_000.0


def _is_number(value: Any) -> bool:
    """A JSON number the engine can safely coerce with float().

    Type alone is not enough. Python ints are unbounded and JSON caps nothing, so
    10**400 is an ordinary-looking integer that raises OverflowError inside float().
    json.loads also accepts the non-standard NaN/Infinity literals, which coerce fine
    and then silently poison a value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _is_money(value: Any) -> bool:
    """A price the engine can safely do arithmetic on.

    Finite is not enough: value_for() multiplies by the StatTrak premium, so a merely
    large 1e308 overflows to inf, round() preserves it, and selling the gift writes an
    infinite balance no later play can undo. Bound the magnitude to the plausible domain
    instead, and reject negatives, which would drain the recipient's balance instead.
    """
    return _is_number(value) and 0.0 <= float(value) <= MAX_MONEY


def _is_wear_float(value: Any) -> bool:
    """A wear float. Real ones are always in [0, 1]; outside it wear_tier() silently
    mis-tiers rather than failing, so reject it here where we can say why."""
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _check_item(item: Any) -> None:
    """Validate the sender's embedded skin.

    receive_item() falls back to this dict whenever the recipient's catalog lacks the
    skin — routine when the sender has the full catalog and the recipient is still on the
    bundled starter set. unboxing.value_for()/compute_value() then read ``prices`` and
    ``base_value`` straight off it, so anything non-numeric there escapes as a raw
    TypeError/ValueError from deep inside the engine instead of a GiftError.
    """
    if not isinstance(item, dict) or not item.get("id"):
        raise GiftError("That gift code is corrupted.")
    if "base_value" in item and not _is_money(item["base_value"]):
        raise GiftError("That gift code is corrupted.")
    prices = item.get("prices")
    if prices is None:
        return
    if not isinstance(prices, dict):
        raise GiftError("That gift code is corrupted.")
    for key, value in prices.items():
        if not isinstance(key, str) or not _is_money(value):
            raise GiftError("That gift code is corrupted.")


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
