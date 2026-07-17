"""Authoritative unboxing engine: rarity roll -> item -> float/wear -> StatTrak.

Pure logic with an injectable RNG so every outcome is reproducible in tests. No
Anki imports. The webview only *animates* what this module decides.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

# Value model: a skin's virtual value scales down with wear and up with StatTrak.
# Deterministic and tunable; used for sell-back and the reveal panel.
WEAR_VALUE_MULTIPLIER = {"fn": 1.0, "mw": 0.85, "ft": 0.70, "ww": 0.60, "bs": 0.50}
STATTRAK_VALUE_MULTIPLIER = 1.30
DEFAULT_STATTRAK_ODDS = 0.10


def wear_tier(float_value: float, wear_tiers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Map a float in [0, 1] to its wear tier (first tier whose max it is below)."""
    for tier in wear_tiers:
        if float_value < tier["max"]:
            return tier
    return wear_tiers[-1]


def pick_weighted(weights: Dict[str, float], r: float) -> str:
    """Cumulative-odds walk over a {key: weight} map for a uniform draw ``r`` in [0, 1).
    Insertion order is preserved (JSON keeps it), so a given seed is reproducible."""
    total = sum(weights.values())
    threshold = r * total
    cumulative = 0.0
    last_key = None
    for key, weight in weights.items():
        cumulative += weight
        last_key = key
        if threshold < cumulative:
            return key
    return last_key  # float slop guard


def pick_rarity(rarities: Dict[str, Dict[str, Any]], r: float) -> str:
    """Weighted rarity selection using each rarity's ``odds``."""
    return pick_weighted({k: m["odds"] for k, m in rarities.items()}, r)


WEAR_ORDER = ["fn", "mw", "ft", "ww", "bs"]


def compute_value(item: Dict[str, Any], wear_id: str, stattrak: bool) -> float:
    """Synthetic fallback value from a tier base + wear/StatTrak multipliers. Used
    when no real market price is available for the item/wear."""
    base = float(item.get("base_value", 0.0))
    value = base * WEAR_VALUE_MULTIPLIER.get(wear_id, 1.0)
    if stattrak:
        value *= STATTRAK_VALUE_MULTIPLIER
    return value


def value_for(item: Dict[str, Any], wear_id: str, stattrak: bool) -> float:
    """Value for a specific wear/StatTrak. Prefers the real market price baked into
    ``item['prices']`` (keys like 'ft' and 'st_ft', in dollars); if the exact key is
    missing it approximates from the nearest available wear, and finally falls back to
    the synthetic model when the item has no price data at all (bundled/offline set)."""
    prices = item.get("prices") or {}
    if prices:
        key = ("st_" if stattrak else "") + wear_id
        if key in prices:
            return round(float(prices[key]), 2)
        if stattrak and wear_id in prices:  # ST price missing -> premium on base wear
            return round(float(prices[wear_id]) * STATTRAK_VALUE_MULTIPLIER, 2)
        # nearest available wear: same StatTrak-ness first, then the other
        idx = WEAR_ORDER.index(wear_id) if wear_id in WEAR_ORDER else 0
        for prefix, st_bump in ((("st_" if stattrak else ""), 1.0),
                                ("", STATTRAK_VALUE_MULTIPLIER if stattrak else 1.0),
                                ("st_", 1.0)):
            for dist in range(len(WEAR_ORDER)):
                for j in (idx - dist, idx + dist):
                    if 0 <= j < len(WEAR_ORDER):
                        k = prefix + WEAR_ORDER[j]
                        if k in prices:
                            return round(float(prices[k]) * st_bump, 2)
    return round(compute_value(item, wear_id, stattrak), 2)


def resolve(
    case_id: str,
    item: Dict[str, Any],
    rarity: str,
    data: Dict[str, Any],
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Turn a chosen ``item``/``rarity`` into a concrete drop (float, wear, StatTrak,
    value). Shared by case openings and trade-up outputs."""
    rng = rng or random.Random()

    lo = float(item.get("min_float", 0.0))
    hi = float(item.get("max_float", 1.0))
    float_value = rng.uniform(lo, hi)
    wear = wear_tier(float_value, data["wear_tiers"])

    stattrak_odds = data.get("stattrak_odds", DEFAULT_STATTRAK_ODDS)
    stattrak = rng.random() < stattrak_odds

    value = value_for(item, wear["id"], stattrak)

    return {
        "case_id": case_id,
        "item": item,
        "rarity": rarity,
        "rarity_meta": data["rarities"][rarity],
        "wear": wear,
        "float": float_value,
        "stattrak": stattrak,
        "value": value,
    }


def _nearest_nonempty(case: Dict[str, Any], rarity: str, order):
    """Return (rarity, pool) for the drawn rarity, or the nearest tier that actually
    has items. Real-world catalogs are fully populated, but this keeps a partial or
    hand-edited case from ever indexing an empty pool."""
    items = case["items"]
    if items.get(rarity):
        return rarity, items[rarity]
    idx = order.index(rarity) if rarity in order else 0
    for dist in range(1, len(order)):
        for j in (idx - dist, idx + dist):
            if 0 <= j < len(order) and items.get(order[j]):
                return order[j], items[order[j]]
    raise ValueError("Case %r has no items to drop." % case.get("id"))


def roll(
    case: Dict[str, Any],
    data: Dict[str, Any],
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Resolve one case opening into a concrete drop.

    Returns a dict with the item, its rarity/wear/float, StatTrak flag, and value.
    """
    rng = rng or random.Random()
    order = list(data["rarities"].keys())
    # Per-case odds when the catalog provides them (weapon cases vs souvenir packages
    # have different tier sets); otherwise fall back to the global rarity odds.
    weights = case.get("odds") or {k: m["odds"] for k, m in data["rarities"].items()}
    rarity = pick_weighted(weights, rng.random())
    rarity, pool = _nearest_nonempty(case, rarity, order)
    item = pool[rng.randrange(len(pool))]
    return resolve(case["id"], item, rarity, data, rng)


def build_reel(
    case: Dict[str, Any],
    data: Dict[str, Any],
    winning_drop: Dict[str, Any],
    length: int = 60,
    winning_index: int = 52,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """Build the horizontal reel strip the webview scrolls through.

    Fills ``length`` tiles with rarity-weighted filler items and plants the actual
    winning item at ``winning_index`` (the deceleration target). Purely cosmetic —
    the drop is already decided by :func:`roll`.
    """
    rng = rng or random.Random()
    rarities = data["rarities"]

    # Gold (special) must never appear as filler — it only shows if the reel is
    # actually landing on it, like real CS2. Fillers come from the other tiers,
    # weighted by the case's own odds when available.
    case_odds = case.get("odds")
    if case_odds:
        filler_weights = {r: p for r, p in case_odds.items()
                          if r != "special" and case["items"].get(r)}
    else:
        filler_weights = {r: m["odds"] for r, m in rarities.items()
                          if r != "special" and case["items"].get(r)}

    def tile(item, rarity):
        return {
            "id": item["id"],
            "weapon": item.get("weapon", ""),
            "skin": item.get("skin", ""),
            "image": item.get("image"),
            "color": rarities[rarity]["color"],
            "rarity": rarity,
        }

    def filler_tile():
        rarity = pick_weighted(filler_weights, rng.random())
        pool = case["items"][rarity]
        return tile(pool[rng.randrange(len(pool))], rarity)

    strip = [filler_tile() for _ in range(length)]
    strip[winning_index] = tile(winning_drop["item"], winning_drop["rarity"])
    return strip
