"""Authoritative economy engine: balance, buying/opening, sell-back, trade-ups.

Operates on a plain ``state`` dict (JSON-serializable) so it can be persisted and,
in a future phase, moved server-side. No Anki imports. RNG is injectable.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from . import unboxing

# The economy is FIXED, not user-configurable: a global market needs every player on
# identical rules, and a tunable payout/price would let anyone mint value at will.
EARN_PER_CARD = 0.10
DEFAULT_CASE_PRICE = 2.50      # fallback only; real cases carry their own baked price
SELL_FRACTION = 1.0            # you get the full listed value back
DEFAULT_SELL_FRACTION = SELL_FRACTION


class EconomyError(Exception):
    """Base class for recoverable economy errors (shown to the user)."""


class InsufficientFunds(EconomyError):
    pass


class ItemNotFound(EconomyError):
    pass


class InvalidTradeUp(EconomyError):
    pass


def trade_up_size(rarity: str) -> int:
    """Inputs required for a contract: the Covert->Gold (red->gold) contract takes 5;
    every other tier takes 10 (real CS2 rules)."""
    return 5 if rarity == "covert" else 10


HISTORY_LIMIT = 50


def new_state() -> Dict[str, Any]:
    return {
        "balance": 0.0,
        "inventory": [],
        "history": [],
        "free_cases": [],     # unopened free cases (case ids) you own
        "last_daily": "",     # ISO date of the last daily grant
        "next_uid": 1,
        "player_id": "",          # lazily minted by gifting.ensure_player_id()
        "sent_gifts": [],         # every code ever generated, so it can be re-copied
        "redeemed_nonces": [],    # replay guard for incoming gifts
        "stats": {
            "cards": 0, "earned": 0.0, "cases_opened": 0, "spent": 0.0,
            "best_value": 0.0, "best_name": "", "best_rarity": "",
            "pulls": {},          # all-time unboxed count per rarity
            "since_special": 0,   # opens since the last gold (drought counter)
        },
    }


# --- helpers ---------------------------------------------------------------

def case_by_id(data: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    for case in data["cases"]:
        if case["id"] == case_id:
            return case
    raise EconomyError("Unknown case: %s" % case_id)


def _display_name(drop: Dict[str, Any]) -> str:
    prefix = "StatTrak™ " if drop["stattrak"] else ""
    item = drop["item"]
    return "%s%s | %s (%s)" % (
        prefix, item.get("weapon", ""), item.get("skin", ""), drop["wear"]["name"],
    )


def _entry_from_drop(state: Dict[str, Any], drop: Dict[str, Any]) -> Dict[str, Any]:
    uid = state["next_uid"]
    state["next_uid"] += 1
    return {
        "uid": uid,
        "case_id": drop["case_id"],
        "item": drop["item"],
        "rarity": drop["rarity"],
        "rarity_meta": drop.get("rarity_meta"),
        "wear": drop["wear"],
        "float": drop["float"],
        "stattrak": drop["stattrak"],
        "value": drop["value"],
        "name": _display_name(drop),
    }


def _index_of(state: Dict[str, Any], uid: int) -> int:
    for i, entry in enumerate(state["inventory"]):
        if entry["uid"] == uid:
            return i
    raise ItemNotFound("No inventory item with uid %s" % uid)


# --- earning ---------------------------------------------------------------

def claim_daily(state: Dict[str, Any], data: Dict[str, Any], today: str,
                rng: Optional[random.Random] = None) -> Optional[str]:
    """Grant one free random weapon case for the day, to open on the house. Idempotent:
    returns the granted case id, or None if today's case was already claimed."""
    if state.get("last_daily") == today:
        return None
    pool = [c for c in data.get("cases", []) if c.get("category", "Case") == "Case"]
    if not pool:
        pool = data.get("cases", [])
    if not pool:
        return None
    rng = rng or random.Random()
    case = pool[rng.randrange(len(pool))]
    state.setdefault("free_cases", []).append(case["id"])
    state["last_daily"] = today
    return case["id"]


def add_earnings(state: Dict[str, Any], amount: float) -> float:
    state["balance"] = round(state["balance"] + amount, 2)
    stats = state.setdefault("stats", {})
    stats["earned"] = round(stats.get("earned", 0.0) + amount, 2)
    stats["cards"] = stats.get("cards", 0) + 1
    return state["balance"]


# --- buying / opening ------------------------------------------------------

def case_price(case: Dict[str, Any], data: Dict[str, Any]) -> float:
    return float(case.get("price", data.get("default_case_price", DEFAULT_CASE_PRICE)))


def open_case(
    state: Dict[str, Any],
    data: Dict[str, Any],
    case_id: str,
    rng: Optional[random.Random] = None,
    free: bool = False,
) -> Dict[str, Any]:
    """Buy-and-open a case (or redeem a free one). Deducts the price, appends the drop,
    returns the drop plus the reel strip for the animation. Raises before any mutation."""
    case = case_by_id(data, case_id)
    price = case_price(case, data)
    free_cases = state.setdefault("free_cases", [])
    if free:
        if case_id not in free_cases:
            raise EconomyError("You don't have a free %s to open." % case["name"])
    elif state["balance"] < price:
        raise InsufficientFunds(
            "Need $%.2f to open %s, balance is $%.2f"
            % (price, case["name"], state["balance"])
        )

    rng = rng or random.Random()
    drop = unboxing.roll(case, data, rng=rng)
    reel = unboxing.build_reel(case, data, drop, rng=rng)

    if free:
        free_cases.remove(case_id)
    else:
        state["balance"] = round(state["balance"] - price, 2)
    entry = _entry_from_drop(state, drop)
    state["inventory"].append(entry)
    stats = state.setdefault("stats", {})
    stats["cases_opened"] = stats.get("cases_opened", 0) + 1
    if not free:  # a free case costs nothing, so it doesn't count as spend
        stats["spent"] = round(stats.get("spent", 0.0) + price, 2)
    pulls = stats.setdefault("pulls", {})
    pulls[entry["rarity"]] = pulls.get(entry["rarity"], 0) + 1
    stats["since_special"] = (0 if entry["rarity"] == "special"
                              else stats.get("since_special", 0) + 1)
    if entry["value"] > stats.get("best_value", 0.0):
        stats["best_value"] = entry["value"]
        stats["best_name"] = entry["name"]
        stats["best_rarity"] = entry["rarity"]

    history = state.setdefault("history", [])
    history.append({"name": entry["name"], "rarity": entry["rarity"],
                    "value": entry["value"], "case_id": drop["case_id"]})
    del history[:-HISTORY_LIMIT]  # keep only the most recent entries

    return {"drop": entry, "reel": reel, "balance": state["balance"]}


# --- selling ---------------------------------------------------------------

def set_favorite(state: Dict[str, Any], uids: List[int], value: bool) -> Dict[str, Any]:
    """Mark/unmark skins as favourites. Favourites are protected from selling."""
    wanted = {int(u) for u in uids}
    for uid in wanted:
        _index_of(state, uid)  # validate before mutating
    count = 0
    for entry in state["inventory"]:
        if entry["uid"] in wanted:
            entry["favorite"] = bool(value)
            count += 1
    return {"count": count, "favorite": bool(value)}


def sell_item(
    state: Dict[str, Any],
    uid: int,
    fraction: float = DEFAULT_SELL_FRACTION,
) -> Dict[str, Any]:
    idx = _index_of(state, uid)
    if state["inventory"][idx].get("favorite"):
        raise EconomyError("That skin is a favourite — unfavourite it to sell.")
    entry = state["inventory"].pop(idx)
    amount = round(float(entry["value"]) * fraction, 2)
    state["balance"] = round(state["balance"] + amount, 2)
    return {"amount": amount, "balance": state["balance"], "sold": entry}


def sell_items(
    state: Dict[str, Any],
    uids: List[int],
    fraction: float = DEFAULT_SELL_FRACTION,
) -> Dict[str, Any]:
    """Bulk-sell several skins at once. Validates every uid exists before mutating,
    so a bad id leaves the inventory untouched."""
    wanted = {int(u) for u in uids}
    for uid in wanted:
        _index_of(state, uid)  # raises ItemNotFound before any mutation
    total = 0.0
    kept = []
    sold = protected = 0
    for entry in state["inventory"]:
        if entry["uid"] in wanted:
            if entry.get("favorite"):   # favourites are kept, not sold
                protected += 1
                kept.append(entry)
            else:
                total += float(entry["value"])
                sold += 1
        else:
            kept.append(entry)
    state["inventory"] = kept
    amount = round(total * fraction, 2)
    state["balance"] = round(state["balance"] + amount, 2)
    return {"amount": amount, "balance": state["balance"],
            "count": sold, "protected": protected}


# --- gifting -----------------------------------------------------------

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


# --- trade-up contracts ----------------------------------------------------

def trade_up(
    state: Dict[str, Any],
    data: Dict[str, Any],
    uids: List[int],
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """CS2-style contract: 10 skins of one rarity/StatTrak -> 1 of the next tier.

    Follows the real mechanics: the output is drawn from the *collections* (cases)
    the inputs came from, weighted by how many inputs came from each, and its float is
    the average of the input floats mapped into the output skin's float range.
    StatTrak may be mixed — the share of StatTrak inputs is the chance the output is
    StatTrak — except for Covert->Gold, which must be uniform. Validates fully before
    mutating. Covert (5 inputs) trades up into the gold Special tier.
    """
    if not uids or len(set(uids)) != len(uids):
        raise InvalidTradeUp("Trade-up inputs must be distinct skins.")

    entries = [state["inventory"][_index_of(state, uid)] for uid in uids]

    if any(e.get("favorite") for e in entries):
        raise InvalidTradeUp("Favourites can't be traded up — unfavourite them first.")

    if len({e["rarity"] for e in entries}) != 1:
        raise InvalidTradeUp("All skins must share the same rarity.")
    rarity = entries[0]["rarity"]

    required = trade_up_size(rarity)
    if len(uids) != required:
        raise InvalidTradeUp("This contract needs exactly %d skins." % required)

    order = data["trade_up_order"]
    if rarity not in order:
        raise InvalidTradeUp("%s skins can't be traded up." % rarity)
    idx = order.index(rarity)
    if idx + 1 >= len(order):
        raise InvalidTradeUp("%s is the highest tradeable rarity." % rarity)
    next_rarity = order[idx + 1]

    rng = rng or random.Random()

    # StatTrak: normal contracts may mix, and the share of StatTrak inputs is the
    # chance the output is StatTrak. Red->Gold must be uniform (no mixing).
    st_count = sum(1 for e in entries if e.get("stattrak"))
    if next_rarity == "special":
        if st_count not in (0, len(entries)):
            raise InvalidTradeUp(
                "A Red → Gold contract can't mix StatTrak™ — all %d must match." % required)
        stattrak = st_count == len(entries)
    else:
        stattrak = rng.random() < (st_count / float(len(entries)))

    # Collection-weighted output: pick a source case proportional to how many inputs
    # came from it, then a random next-rarity skin from that case.
    counts = {}
    for e in entries:
        counts[e["case_id"]] = counts.get(e["case_id"], 0) + 1
    weighted = [(cid, n) for cid, n in counts.items()
                if case_by_id(data, cid)["items"].get(next_rarity)]
    if not weighted:  # source cases lack that tier (e.g. souvenir has no knives) -> any
        weighted = [(c["id"], 1) for c in data["cases"] if c["items"].get(next_rarity)]
    if not weighted:
        raise InvalidTradeUp("No %s skins available to trade up into." % next_rarity)

    total = sum(n for _, n in weighted)
    threshold = rng.random() * total
    cumulative = 0
    out_case_id = weighted[-1][0]
    for cid, n in weighted:
        cumulative += n
        if threshold < cumulative:
            out_case_id = cid
            break
    pool = case_by_id(data, out_case_id)["items"][next_rarity]
    out_item = pool[rng.randrange(len(pool))]

    # Float averaging: mean input float mapped into the output skin's float range.
    avg_float = sum(float(e.get("float", 0.0)) for e in entries) / len(entries)
    lo = float(out_item.get("min_float", 0.0))
    hi = float(out_item.get("max_float", 1.0))
    out_float = lo + avg_float * (hi - lo)
    wear = unboxing.wear_tier(out_float, data["wear_tiers"])
    value = unboxing.value_for(out_item, wear["id"], stattrak)
    output_drop = {
        "case_id": out_case_id, "item": out_item, "rarity": next_rarity,
        "rarity_meta": data["rarities"][next_rarity], "wear": wear,
        "float": out_float, "stattrak": stattrak, "value": value,
    }

    # Mutate: consume the 10 inputs, add the output.
    consumed = set(uids)
    state["inventory"] = [e for e in state["inventory"] if e["uid"] not in consumed]
    entry = _entry_from_drop(state, output_drop)
    state["inventory"].append(entry)

    return {"output": entry, "consumed": list(consumed)}
