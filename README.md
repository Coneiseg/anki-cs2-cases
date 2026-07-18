# CS2 Cases — Anki add-on

Gamify your reviews. Every card you answer earns **virtual** in-app dollars. Spend them in a
built-in market to buy and open CS2-style weapon cases — the decelerating reel, real skin art,
rarity colors, wear/float, StatTrak™, the hidden gold "Rare Special Item" tier, and the real
CS2 sounds. Collect skins, sell them back at real market values, and run trade-up contracts.

> All currency is **virtual**. No real money is involved and nothing can be cashed out. This is
> a self-motivation toy for studying, not gambling.

## Install

**One-click:** double-click `cs2_cases.ankiaddon` (or in Anki: **Tools ▸ Add-ons ▸ Install from
file…** and pick it), then restart Anki.

**Manual:** copy the `cs2_cases/` folder into your add-ons folder (**Tools ▸ Add-ons ▸ View
Files**) and restart.

Target: Anki **23.10+** on Qt6.

## Use

- **Answer cards** in the reviewer → your balance ticks up **$0.10** each.
- **A free case every day**, on the house — a random weapon case lands in your market the
  first time you review (or open the market) each day, to start you off.
- The **★** in Anki's toolbar (or **Tools ▸ CS2 Cases**) toggles the **market panel** — a
  dockable sidebar. Drag it to float/re-dock.
  - **Cases** — click a case to preview its full skin pool + real drop odds; hit **Open**.
  - **Inventory** — search, sort, filter; sell single skins or multi-select and bulk-sell.
  - **Trade Up** — pick 10 skins of one rarity to forge one of the next tier (button pinned).
  - **Friends** — your Player ID, a box to redeem a friend's gift code, and every code
    you've sent (re-copyable forever).
- **Gifting:** select a skin in your inventory → **Gift** → paste your friend's Player ID.
  You get a `CS2GIFT-…` code to send them however you like; they paste it into their
  Friends tab and the skin lands in their inventory, tagged with your ID. Codes are locked
  to one recipient, work offline, and need no account or server. Favourites can't be
  gifted — unfavourite first. **There is no cancel: the code *is* the skin**, so it leaves
  your inventory when you generate it (it's kept in your Sent list, so it can't be lost).
  - **Stats** — cards, earnings, cases opened, spend, collection value, unbox net, recent drops.
- Opening a case takes over the whole Anki window with the reel + reveal. **Click during the
  spin to quick-open**, then **Continue**, **Open Another**, or **Sell**.

## Real data, prices, and offline use

Ships with a small **offline starter set** so it works immediately with no network. **Tools ▸
CS2 Cases: Update catalog** does a one-time (~1–2 min) download of the full **42-case catalog**,
**real per-wear/StatTrak market prices**, and **skin images**, caching everything locally — after
which it runs **100% offline**. Data from the open [ByMykel CS2 API](https://github.com/ByMykel/CSGO-API)
and [price tracker](https://github.com/ByMykel/counter-strike-price-tracker).

## Configuration

**Tools ▸ Add-ons ▸ CS2 Cases ▸ Config** (details in `config.md`): mute, reduced-motion,
and the online data source. Mute and reduced-motion are also toggleable in the Stats tab.

**The economy is fixed and deliberately not configurable** — payout ($0.10/card), case
prices (real market + $2.49 key), and sell-back (100%) are locked in code so every player
runs identical rules. This is a prerequisite for the planned global market: a tunable
payout would let anyone mint value at will.

## Attribution & disclaimer

**This is an unofficial fan project and is not affiliated with, endorsed by, or sponsored by
Valve Corporation.** "Counter-Strike", "CS2", the case/skin names and artwork, and the in-game
sounds are trademarks and copyrighted works of **Valve** — all rights to those assets remain
with Valve. They are included here for **personal, non-commercial** use to recreate the
case-opening experience for studying motivation. If you are Valve and want something removed,
open an issue. The substitute UI font is **Chakra Petch** (SIL Open Font License); drop a real
Stratum2 at `user_files/assets/fonts/stratum2.woff2` for an exact match. Add-on **code** is free
to use; **bundled Valve assets are not covered** by that and are Valve's property.

## Architecture

Python is the authoritative engine (economy, seedable-RNG unboxing, real-price valuation,
dataset, persistence — all unit-tested); two webviews (dockable market panel + full-window
opening overlay) are pure presentation over a `pycmd` bridge. The engine is kept isolated so a
future Phase 2 (trading with other people) could move it server-side for anti-cheat.

```
cs2_cases/
  economy.py unboxing.py store.py controller.py   # pure logic (tested)
  data.py                                          # catalog import, real prices, image cache
  reviewer_hook.py entry.py ui.py                  # Anki wiring (hooks, dock, overlay)
  web/                                             # SPA: store / inventory / trade-ups / reel
  data/cases.json                                  # bundled offline starter set
  user_files/assets/                               # bundled sounds + fonts (+ cached images)
tests/                                             # python3 -m unittest discover -s tests
```

## Tests

```
python3 -m unittest discover -s tests -v
```

Covers rarity-distribution accuracy, wear bands, seeded reproducibility, real-price valuation
with fallbacks, economy buy/sell/bulk-sell/trade-up invariants, history/stats, atomic
persistence, and controller orchestration.

## Building the .ankiaddon

```
python3 scripts/build_ankiaddon.py
```

Writes `dist/cs2_cases.ankiaddon` (bundles code + Valve sounds/fonts + starter dataset; excludes
per-user runtime files: state, downloaded catalog, cached images).

## things alric is brainstorming

- ~~fix ui overflow (top bar, inv selected)~~ — top bar wraps to 2 rows with the balance
  inline; the inventory action bar wraps instead of clipping
- ~~auto-select for tradeups~~ — an Auto-fill button completes the contract with your
  cheapest eligible skins of a tier
- ~~change stats bar to show collection value (money + items in inv)~~ — the Career panel
  now shows "Collection value" = balance + inventory worth
- cobblestone packages
- ~~global marketplace to trade~~ — dropped deliberately: earning happens locally in an
  open-source app, so no server can verify a review really happened and a single cheater
  would wreck a shared economy. Friend-to-friend gifting ships instead (see
  `docs/superpowers/specs/2026-07-17-friend-gifting-design.md`).


- down the line: pattern based inspection??
- equip a loadout?
