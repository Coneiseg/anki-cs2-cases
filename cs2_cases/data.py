"""Hybrid data layer: load the bundled catalog (offline fallback), prefer a
refreshed copy in user_files when present, and manage the local asset cache.

The online refresh is best-effort and fully optional; if it is disabled or fails,
everything falls back to the bundled dataset so the game always works offline.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import tempfile
import urllib.request
from typing import Any, Callable, Dict, List, Optional

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_CATALOG = os.path.join(ADDON_DIR, "data", "cases.json")
REFRESHED_CATALOG_NAME = "catalog.json"
ASSETS_DIRNAME = "assets"

# Open community CS2 dataset (no API key). Real cases, skins, images, float caps.
BYMYKEL_BASE = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/"
# Real market prices (market_hash_name -> cents), one bulk file, fetched at update.
PRICES_URL = "https://raw.githubusercontent.com/ByMykel/counter-strike-price-tracker/main/static/latest.json"

WEAR_NAMES = {
    "fn": "Factory New", "mw": "Minimal Wear", "ft": "Field-Tested",
    "ww": "Well-Worn", "bs": "Battle-Scarred",
}
# The real cost to open a case = its market price + a key. Old case keys aren't
# purchasable on the market (their listed prices are noise), so use the fixed Steam
# key price. Case with no market price falls back to a small nominal container cost.
KEY_PRICE = 2.49
DEFAULT_CONTAINER_PRICE = 0.30

# ByMykel rarity ids -> our tiers. Everything in a crate's `contains_rare` (the
# knife/glove pool) becomes the gold `special` tier regardless of its label.
RARITY_ID_MAP = {
    "rarity_common_weapon": "consumer",
    "rarity_uncommon_weapon": "uncommon",
    "rarity_rare_weapon": "mil_spec",
    "rarity_mythical_weapon": "restricted",
    "rarity_legendary_weapon": "classified",
    "rarity_ancient_weapon": "covert",
    "rarity_contraband_weapon": "covert",
}

# Weapon-skin container types (contain weapon skins). Everything else — sticker /
# autograph / patch capsules, music kits, pins, graffiti — is excluded.
INCLUDED_TYPES = {"Case", "Souvenir", "Souvenir Highlight"}

# Low->high tier order used to weight per-case odds (each rarer tier ~1/5 the last).
TIER_ORDER = ["consumer", "uncommon", "mil_spec", "restricted", "classified", "covert"]
SPECIAL_PROB = 0.0026  # the yellow knife/glove tier, when a case has one

# Currency is virtual; ByMykel has no prices. Synthesize a per-tier base value with
# deterministic per-item variation so sell-back/trade-up feel graded.
TIER_BASE_VALUE = {
    "consumer": 0.05, "uncommon": 0.12, "mil_spec": 0.30, "restricted": 1.50,
    "classified": 6.00, "covert": 25.00, "special": 350.00,
}


def _compute_odds(present_tiers) -> dict:
    """Per-case rarity odds from the tiers a case actually contains, using CS2's ~5x
    rarity scaling (lowest tier most common). Reproduces the official weapon-case
    numbers and gives souvenir packages a sensible consumer->covert spread."""
    tiers = [t for t in TIER_ORDER if t in present_tiers]
    has_special = "special" in present_tiers
    if not tiers:
        return {"special": 1.0} if has_special else {}
    weights = {t: (0.2 ** i) for i, t in enumerate(tiers)}
    total = sum(weights.values())
    special_p = SPECIAL_PROB if has_special else 0.0
    scale = (1.0 - special_p) / total
    odds = {t: round(weights[t] * scale, 6) for t in tiers}
    if has_special:
        odds["special"] = special_p
    return odds


def user_files_dir() -> str:
    return os.path.join(ADDON_DIR, "user_files")


def assets_dir() -> str:
    return os.path.join(user_files_dir(), ASSETS_DIRNAME)


def load_catalog(uf_dir: Optional[str] = None) -> Dict[str, Any]:
    """Return the active catalog: a refreshed copy in user_files if it exists and is
    valid, otherwise the bundled dataset. The rarity/tier config (rarities, wear tiers,
    trade-up order, StatTrak odds) always tracks the current code, not whatever was
    frozen into an older downloaded catalog — only the `cases` list is real download
    data — so engine rules stay correct without forcing a re-download."""
    uf_dir = uf_dir or user_files_dir()
    refreshed = os.path.join(uf_dir, REFRESHED_CATALOG_NAME)
    for path in (refreshed, BUNDLED_CATALOG):
        try:
            with open(path, encoding="utf-8") as f:
                catalog = json.load(f)
        except (OSError, ValueError):
            continue
        if path != BUNDLED_CATALOG:  # refresh engine config from the bundled template
            template = _load_bundled()
            for key in ("rarities", "trade_up_order", "wear_tiers", "stattrak_odds"):
                if key in template:
                    catalog[key] = template[key]
        return catalog
    raise RuntimeError("No usable catalog found (bundled dataset missing/corrupt).")


def cached_asset_path(filename: str, uf_dir: Optional[str] = None) -> Optional[str]:
    """Absolute path to a cached asset, or None if it isn't downloaded."""
    if not filename:
        return None
    uf_dir = uf_dir or user_files_dir()
    path = os.path.join(uf_dir, ASSETS_DIRNAME, filename)
    return path if os.path.exists(path) else None


# --- online refresh: import the full real catalog -------------------------

def _fetch_json(url: str, timeout: int = 120) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "cs2-cases-anki/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _atomic_write_json(path: str, obj: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".catalog-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _split_name(name: str):
    if " | " in name:
        weapon, skin = name.split(" | ", 1)
        return weapon, skin
    return name, ""


def _synth_value(item_id: str, tier: str) -> float:
    h = int(hashlib.md5(item_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(TIER_BASE_VALUE[tier] * (0.6 + 0.8 * h), 2)  # 0.6x..1.4x of tier base


def _price_key(weapon: str, skin: str, wear_name: str, stattrak: bool) -> str:
    body = "%s | %s (%s)" % (weapon, skin, wear_name)
    if not stattrak:
        return body
    if weapon.startswith("★ "):          # StatTrak knives: "★ StatTrak™ Karambit | …"
        return "★ StatTrak™ %s | %s (%s)" % (weapon[2:], skin, wear_name)
    return "StatTrak™ " + body


def _item_prices(prices: dict, weapon: str, skin: str) -> dict:
    """Build {wear_id: dollars, 'st_'+wear_id: dollars} for the wears/StatTrak that the
    price source actually lists for this skin."""
    out = {}
    if not skin:  # vanilla knives have no finish -> no reliable market key
        return out
    for wid, wname in WEAR_NAMES.items():
        c = prices.get(_price_key(weapon, skin, wname, False))
        if c is not None:
            out[wid] = round(float(c) / 100.0, 2)
        st = prices.get(_price_key(weapon, skin, wname, True))
        if st is not None:
            out["st_" + wid] = round(float(st) / 100.0, 2)
    return out


def build_catalog_from_bymykel(crates: List[dict], skins: List[dict],
                               template: Optional[dict] = None,
                               prices: Optional[dict] = None) -> dict:
    """Transform ByMykel crates+skins into our catalog schema. Keeps our fixed CS2
    rarity odds/wear tiers from the bundled template; only the case list is replaced.
    When ``prices`` is supplied, real per-wear/StatTrak market values are baked in."""
    template = template or _load_bundled()
    prices = prices or {}
    float_map = {s["id"]: (s.get("min_float"), s.get("max_float")) for s in skins}

    def make_item(entry: dict, tier: str) -> dict:
        weapon, skin = _split_name(entry.get("name", ""))
        obj = {
            "id": entry["id"],
            "weapon": weapon,
            "skin": skin,
            "base_value": _synth_value(entry["id"], tier),  # synthetic fallback
            "image": entry.get("image"),
        }
        pm = _item_prices(prices, weapon, skin)
        if pm:
            obj["prices"] = pm
        lo, hi = float_map.get(entry["id"], (None, None))
        if lo is not None:
            obj["min_float"] = lo
        if hi is not None:
            obj["max_float"] = hi
        return obj

    cases = []
    for crate in crates:
        ctype = crate.get("type")
        if ctype not in INCLUDED_TYPES:
            continue
        items = {t: [] for t in TIER_ORDER + ["special"]}
        for entry in crate.get("contains", []):
            tier = RARITY_ID_MAP.get((entry.get("rarity") or {}).get("id"))
            if tier:
                items[tier].append(make_item(entry, tier))
        for entry in crate.get("contains_rare", []):
            items["special"].append(make_item(entry, "special"))
        present = {t for t, pool in items.items() if pool}
        if not present:
            continue
        container = prices.get(crate["name"])
        container = (container / 100.0) if container is not None else DEFAULT_CONTAINER_PRICE
        # Weapon cases need a key to open; souvenir/highlight packages don't.
        price = container + (KEY_PRICE if ctype == "Case" else 0.0)
        cases.append({
            "id": crate["id"],
            "name": crate["name"],
            "category": ctype,
            "price": round(max(price, 0.10), 2),
            "image": crate.get("image"),
            "items": items,
            "odds": _compute_odds(present),
        })

    result = dict(template)
    result["cases"] = cases
    result["source"] = "bymykel"
    return result


def _load_bundled() -> dict:
    with open(BUNDLED_CATALOG, encoding="utf-8") as f:
        return json.load(f)


def _download_binary(url: str, dest: str, timeout: int = 30) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cs2-cases-anki/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        blob = resp.read()
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, dest)


def _image_filename(url: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if not ext or len(ext) > 5:
        ext = ".png"
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext


def cache_images(catalog: Dict[str, Any], uf_dir: Optional[str] = None,
                 log: Optional[Callable[[str], None]] = None) -> int:
    """Download every remote image referenced by the catalog into
    user_files/assets/images/ and rewrite the catalog's image fields to local
    paths, so the webview loads them instantly and offline. Deduplicates by URL
    (the knife/glove art is shared across many cases) and downloads in parallel.
    Images that fail keep their original remote URL as a fallback."""
    uf_dir = uf_dir or user_files_dir()
    log = log or (lambda _m: None)
    img_dir = os.path.join(uf_dir, ASSETS_DIRNAME, "images")
    os.makedirs(img_dir, exist_ok=True)

    urls = set()

    def collect(u):
        if u and u.startswith("http"):
            urls.add(u)

    for case in catalog.get("cases", []):
        collect(case.get("image"))
        for pool in case.get("items", {}).values():
            for item in pool:
                collect(item.get("image"))

    urls = list(urls)
    log("Caching %d images…" % len(urls))

    def fetch(url):
        name = _image_filename(url)
        dest = os.path.join(img_dir, name)
        if not os.path.exists(dest):
            try:
                _download_binary(url, dest)
            except Exception:
                return url, None
        return url, "images/" + name

    mapping = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for url, rel in pool.map(fetch, urls):
            if rel:
                mapping[url] = rel

    def local(u):
        return mapping.get(u, u)

    for case in catalog.get("cases", []):
        if case.get("image"):
            case["image"] = local(case["image"])
        for group in case.get("items", {}).values():
            for item in group:
                if item.get("image"):
                    item["image"] = local(item["image"])
    return len(mapping)


def refresh_catalog(uf_dir: Optional[str] = None,
                    log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Download the full real catalog, cache its images locally, and write it to
    user_files/catalog.json. Returns {ok, cases, images, error}."""
    log = log or (lambda _msg: None)
    uf_dir = uf_dir or user_files_dir()
    try:
        log("Downloading cases…")
        crates = _fetch_json(BYMYKEL_BASE + "crates.json")
        log("Downloading skins…")
        skins = _fetch_json(BYMYKEL_BASE + "skins.json")
        prices = {}
        try:
            log("Downloading prices…")
            prices = _fetch_json(PRICES_URL).get("prices", {})
        except Exception as exc:  # prices are best-effort; fall back to synthetic
            log("Price fetch failed (%s); using synthetic values." % exc)
        log("Building catalog…")
        catalog = build_catalog_from_bymykel(crates, skins, prices=prices)
        images = 0
        try:
            images = cache_images(catalog, uf_dir, log)
        except Exception as exc:  # image caching is best-effort
            log("Image cache issue: %s" % exc)
        _atomic_write_json(os.path.join(uf_dir, REFRESHED_CATALOG_NAME), catalog)
        return {"ok": True, "cases": len(catalog["cases"]), "images": images, "error": None}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        return {"ok": False, "cases": 0, "images": 0, "error": str(exc)}
