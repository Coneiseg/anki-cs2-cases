"""Orchestration layer between the Anki UI and the pure engines.

Owns the loaded state, config, and catalog; every mutating action persists
immediately. Anki-free so it can be unit-tested and, later, reused server-side.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from . import economy, gifting, store


class Controller:
    """The economy (payout, prices, sell-back) is fixed in code, not read from config —
    a shared/global market requires every player on identical, non-tunable rules."""

    def __init__(self, state_path: str, config: Dict[str, Any],
                 catalog: Dict[str, Any], asset_base: str = ""):
        self.state_path = state_path
        self.config = config          # cosmetic/data options only (mute, motion, source)
        self.catalog = catalog
        self.asset_base = asset_base
        self.state = store.load(state_path)

    def reload_catalog(self, catalog: Dict[str, Any]) -> None:
        """Swap in a freshly downloaded catalog (keeps state/inventory intact)."""
        self.catalog = catalog

    def _save(self) -> None:
        store.save(self.state_path, self.state)

    # --- actions (each persists) ------------------------------------------

    def claim_daily(self) -> Optional[str]:
        """Give the player their free case for the day (idempotent)."""
        granted = economy.claim_daily(self.state, self.catalog, date.today().isoformat())
        if granted:
            self._save()
        return granted

    def earn_for_card(self) -> float:
        self.claim_daily()  # first card of the day also drops the free case
        balance = economy.add_earnings(self.state, economy.EARN_PER_CARD)
        self._save()
        return balance

    def open_case(self, case_id: str, free: bool = False) -> Dict[str, Any]:
        result = economy.open_case(self.state, self.catalog, case_id, free=free)
        self._save()
        return result

    def sell(self, uid: int) -> Dict[str, Any]:
        result = economy.sell_item(self.state, int(uid), economy.SELL_FRACTION)
        self._save()
        return result

    def sell_many(self, uids: List[int]) -> Dict[str, Any]:
        result = economy.sell_items(self.state, uids, economy.SELL_FRACTION)
        self._save()
        return result

    def set_favorite(self, uids: List[int], value: bool) -> Dict[str, Any]:
        result = economy.set_favorite(self.state, uids, value)
        self._save()
        return result

    def trade_up(self, uids: List[int]) -> Dict[str, Any]:
        result = economy.trade_up(self.state, self.catalog, [int(u) for u in uids])
        self._save()
        return result

    # --- gifting ------------------------------------------------------------

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
        if not gifting.is_player_id(to_id):
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

    # --- read model for the webview ---------------------------------------

    def state_payload(self) -> Dict[str, Any]:
        inventory = self.state["inventory"]
        inv_value = round(sum(float(e.get("value", 0.0)) for e in inventory), 2)
        return {
            "balance": self.state["balance"],
            "stats": self.state.get("stats", {}),
            "inventory_value": inv_value,
            "inventory_count": len(inventory),
            "history": list(reversed(self.state.get("history", []))),  # newest first
            "free_cases": list(self.state.get("free_cases", [])),
            "player_id": self.state.get("player_id", ""),
            "sent_gifts": list(self.state.get("sent_gifts", [])),
            "is_full_catalog": self.catalog.get("source") == "bymykel",
            "config": {
                "muted": bool(self.config.get("muted", False)),
                "reduced_motion": bool(self.config.get("reduced_motion", False)),
                "earn_per_card": economy.EARN_PER_CARD,   # fixed, shown for reference
            },
            "asset_base": self.asset_base,
            "rarities": self.catalog["rarities"],
            "wear_tiers": self.catalog["wear_tiers"],
            "trade_up_order": self.catalog["trade_up_order"],
            "cases": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "category": c.get("category", "Case"),
                    "price": economy.case_price(c, self.catalog),
                    "image": c.get("image"),
                }
                # cheapest first — real prices span ~$2.78 to $200+ (collector cases)
                for c in sorted(self.catalog["cases"],
                                key=lambda c: economy.case_price(c, self.catalog))
            ],
            "inventory": self.state["inventory"],
        }
