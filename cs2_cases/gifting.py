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


def is_player_id(value: str) -> bool:
    """True if ``value`` is shaped like a Player ID (after normalizing case/space)."""
    return bool(_ID_RE.match(normalize_id(value)))


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
        # RecursionError: deeply-nested JSON blows the stack inside json.loads, and a
        # ~100-char code is enough to trigger it. This function's contract is that any
        # pasted text becomes data or a GiftError, so it must not escape.
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, zlib.error, ValueError, RecursionError):
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
