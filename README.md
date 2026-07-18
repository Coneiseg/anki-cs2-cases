# CS2 Cases — an Anki add-on

Turn studying into a reward loop. Every flashcard you answer earns **virtual** in-app
dollars; you spend them in a built-in market to open CS2-style weapon cases and collect
skins — the decelerating reel, real skin art, rarity colours, wear/float, StatTrak™, the
hidden gold "Rare Special Item" tier, and the real CS2 sounds.

> **All currency is virtual.** No real money is involved, nothing can be bought or cashed
> out, and there is no connection to your Steam account or inventory. This is a
> self-motivation toy for studying — not gambling, and not a way to get real skins.

## What you get

- A dockable **market panel** inside Anki, and a full-window **case-opening** animation.
- **206 real CS2 containers** (all 42 weapon cases plus every souvenir package) with their
  **5,200+ real skins**, real drop odds, wear tiers, float, and StatTrak.
- **Real market prices** for sell-back and collection value (see [Prices](#prices-and-offline-use)).
- **Trade-up contracts**, favourites, per-case odds preview, and career stats.
- **Gift skins to friends** with a copy-paste code — no account, no server (see [Gifting](#gifting)).
- A **free case every day** to get you started, and it all runs **fully offline**.

## Install

- **One-click:** download `cs2_cases.ankiaddon` from the
  [releases](https://github.com/Coneiseg/anki-cs2-cases/releases), double-click it (or in
  Anki: **Tools ▸ Add-ons ▸ Install from file…**), and restart Anki.
- **Manual:** copy the `cs2_cases/` folder into your add-ons folder (**Tools ▸ Add-ons ▸
  View Files**) and restart.

Requires Anki **23.10+** (Qt6). Tested on macOS; Windows/Linux should work but are less
exercised — please report issues.

## How to use it

- **Answer cards** in the reviewer → your balance ticks up **$0.10** each.
- The **★** in Anki's toolbar (or **Tools ▸ CS2 Cases**) opens the **market panel**, a
  sidebar you can drag out to float and dock back.
- **A free weapon case** lands in your market the first time you review each day.
- Opening a case takes over the whole Anki window with the reel and reveal. **Click during
  the spin to skip to the result**, then **Open Another**, **Continue**, or **Sell**.

The panel has five tabs:

- **Cases** — browse every container; click one to see its full skin pool and real odds, then open it.
- **Inventory** — search, sort, and filter; sell one skin or multi-select to bulk-sell; favourite skins to protect them.
- **Trade Up** — pick 10 skins of one rarity (5 for Covert → Gold) to forge one of the next tier, or hit **Auto-fill** to grab your cheapest eligible skins.
- **Friends** — your Player ID, a box to redeem a friend's gift code, and your log of sent codes.
- **Stats** — cards answered, cases opened, spend, **collection value** (cash + inventory), a rarity breakdown, and recent unboxes.

## Prices and offline use

The add-on ships with a tiny **offline starter set** so it works the moment you install it.
**Tools ▸ CS2 Cases: Update catalog** does a one-time (~1–2 min) download of the full
catalog, real market prices, and skin images, caching everything locally — after which it
runs **100% offline**.

Being transparent about how values are set, because it's the number you'll stare at:

- Where the market lists a price for that **exact** skin + wear + StatTrak, that **real
  price is used verbatim** — about 94% of items.
- For the combinations nobody currently lists (some StatTrak variants, rare knives), there
  is no real price to fetch, so the value is **estimated** from real market patterns —
  wear-decay and StatTrak-premium curves calibrated from thousands of priced skins. These
  are clearly approximations, and they're the only non-real values in the app.
- Your inventory **re-prices against the latest catalog every time it loads**, so sell-back
  and collection value track the market rather than freezing at unbox time.

Prices and skin data come from the open [ByMykel CS2 API](https://github.com/ByMykel/CSGO-API)
and [price tracker](https://github.com/ByMykel/counter-strike-price-tracker).

## Gifting

Select a skin → **Gift** → paste your friend's Player ID (both of you find it in the
**Friends** tab). You get a `CS2GIFT-…` code; send it however you like, and your friend
pastes it into their Friends tab to receive the skin, tagged with your ID.

It's deliberately **simple and trust-based, not secure.** There's no server, no account,
and it works offline. Codes are locked to one recipient so a code pasted in a group chat
can't be grabbed by the wrong person, but they are **not** cryptographically protected —
this is a toy to share skins between friends, not an anti-fraud system. Two honest caveats:

- **Favourites can't be gifted** — unfavourite first.
- **There is no cancel: the code *is* the skin.** It leaves your inventory the moment you
  generate the code (your Sent log keeps every code so it can't be lost, but if your friend
  never redeems it, that skin is gone).

## The economy is fixed on purpose

Payout ($0.10/card), case prices (real market price + a fixed $2.49 key), and sell-back
(100% of value) are locked in code and are **not configurable**. Everyone runs the same
rules, which is what keeps trading skins between friends meaningful — a tunable payout would
let anyone mint value at will. The currency is virtual regardless; this is about the game
feeling fair, not about real stakes.

## Privacy

The add-on makes **no network requests** except the catalog/image download you explicitly
trigger from the menu. There is no telemetry, no account, and no contact with Steam. Your
progress lives in a single local file (`user_files/state.json`).

## Attribution & disclaimer

**This is an unofficial fan project, not affiliated with, endorsed by, or sponsored by Valve
Corporation.** "Counter-Strike", "CS2", the case and skin names and artwork, and the in-game
sounds are trademarks and copyrighted works of **Valve** — all rights to those assets remain
with Valve. They're included here for **personal, non-commercial** use to recreate the
case-opening experience as a study aid. If you represent Valve and want something removed,
open an issue.

The substitute UI font is **Chakra Petch** (SIL Open Font License); drop a real Stratum2 at
`user_files/assets/fonts/stratum2.woff2` for an exact match. The add-on's own **code** is MIT
licensed (see `LICENSE`); the **bundled Valve assets are not covered** by that licence and
remain Valve's property.

## For developers

Python is the authoritative engine — economy, seedable-RNG unboxing, real-price valuation,
dataset import, and persistence, all unit-tested. Two webviews (the dockable market panel and
the full-window opening overlay) are pure presentation talking to Python over Anki's `pycmd`
bridge, so game logic never lives in the browser.

```
cs2_cases/
  economy.py unboxing.py store.py controller.py gifting.py   # pure logic (no Anki imports)
  data.py                                                    # catalog import, real prices, image cache
  reviewer_hook.py entry.py ui.py                            # Anki wiring (hooks, dock, overlay)
  web/                                                       # SPA: cases / inventory / trade-ups / friends / reel
  data/cases.json                                            # bundled offline starter set
  user_files/assets/                                         # bundled sounds + fonts (+ cached images)
tests/                                                       # 145 tests
docs/superpowers/                                            # design specs + implementation plans
```

Run the tests:

```
python3 -m unittest discover -s tests -v
```

They cover rarity-distribution accuracy, wear bands, seeded reproducibility, real-price
valuation and its estimate fallbacks, buy/sell/bulk-sell/trade-up invariants, inventory
revaluation, gift-code encode/decode and its trust-boundary validation, history/stats, and
atomic persistence.

Build the installable add-on:

```
python3 scripts/build_ankiaddon.py
```

This writes `dist/cs2_cases.ankiaddon`, bundling the code plus Valve sounds/fonts and the
starter dataset, and excluding per-user runtime files (your save, the downloaded catalog, and
cached images).

## Roadmap

Ideas under consideration: cobblestone/gamma-style packages, pattern-based inspection, and an
equippable loadout.

**Not planned: a global marketplace.** Currency is minted by a local event ("you answered a
card") in an open-source add-on on your own machine, so no server can prove a review really
happened — which means a shared, public economy can't be protected from a single determined
cheater, who would wreck it for everyone. Friend-to-friend gifting exists precisely because a
small circle of people who trust each other doesn't need that enforcement. The reasoning is
written up in `docs/superpowers/specs/2026-07-17-friend-gifting-design.md`.
