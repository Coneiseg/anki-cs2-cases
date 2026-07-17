# Friend Gifting — design

Status: awaiting review · Supersedes the "Phase 2: global marketplace" backlog item

## Why this, and not a global market

The original Phase 2 plan was a server-backed global market with anti-cheat. That plan
rested on a premise that does not survive inspection:

1. **"Anki has to run online anyway."** It doesn't. Anki is offline-first — a local Qt app
   over a local SQLite collection, with AnkiWeb sync strictly opt-in. This add-on runs 100%
   offline today, by explicit requirement.
2. **Being online would not buy anti-cheat.** These are unrelated properties. Currency here
   is minted by "answered a card" — an event that happens on the user's machine, in their
   own SQLite collection, in an open-source Python app, via an add-on whose source is plain
   text in their add-ons folder. `state.json` is editable. `EARN_PER_CARD` is a line of
   Python. Anki ships a debug console (`Ctrl+Shift+;`) from which
   `entry.get_controller().earn_for_card()` mints money in a loop. Any "proof of review" the
   client sends is authored by the client and is therefore forgeable.

There is no remote attestation for open-source Python on a machine the user controls, so a
server can never distinguish a real review from a fabricated one. Server-authoritative
earning is **unachievable**, not merely expensive. A server could only rate-limit and apply
heuristics — which makes cheating boring, not impossible.

This matters most for a *global* market specifically: skins are scarce by design, so a
single cheater with unlimited currency corners the float or hyperinflates the supply, and
the market stops meaning anything for every honest player. A shared economy is the one
design where one cheater ruins it for everyone.

**Therefore: pick a design where cheating doesn't pay, rather than one that needs cheating
to be impossible.** Trading with a small group of invited friends replaces enforcement with
social trust. If a friend mints a knife, everyone knows. This needs no server, no accounts,
no hosting, no moderation, and preserves offline-first.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Scope | Friends-only, trust-based | Cheating is unpreventable; make it socially visible instead |
| Transport | Trade codes pasted via existing chat | Zero infra, zero cost, no accounts, stays offline-first |
| Trade shape | One-way gift only | No escrow, nothing can deadlock; a swap is two gifts |
| Targeting | Locked to recipient Player ID | Kills the realistic accident of a code pasted in a group chat |
| Payload | Self-contained, zlib+base64 | Works even if the friend is on the starter set |
| Giftable | Skins only, never currency | Skins are the fun part; currency is the easiest thing to mint |
| Favourites | Cannot be gifted | Consistent with existing sell / trade-up protection |
| Cancel | None; codes are permanent + re-copyable | Escrow+cancel duplicates items accidentally (see below) |

### The bearer problem, and what we do about it

With no server there is no shared ledger, so nothing can globally prevent double-redemption.
A code pasted into a group chat would otherwise be redeemable by everyone who sees it.
Locking each code to a Player ID reduces this to: only the named recipient's copy will accept
it. This does **not** stop a determined cheater (who can edit their save anyway) — it stops
the accident, which is the realistic failure.

### Why there is no Cancel

Escrowing the item with a Cancel button creates a duplication hole: the friend redeems, the
sender cancels anyway, and the skin now exists twice. That is an *accidental* path to
duplication, and accidents are what quietly wreck a trusted economy.

Instead, the code **is** the item. It leaves the sender's inventory at generation. Every code
ever generated is kept in a Sent log with a re-copy button, so it cannot be lost and can be
redeemed months later. Accepted cost: if the recipient never redeems, that skin is gone.
Duplication then requires a deliberate lie, which is socially visible.

## Architecture

Python stays authoritative; JS stays presentation. One new pure-logic module, mirroring the
existing `economy.py` / `unboxing.py` split:

```
cs2_cases/
  gifting.py      # NEW — pure logic: player id, encode, decode, redeem. No Anki imports.
  economy.py      # + gift_item() / receive_item(), favourite guard
  controller.py   # + orchestration: gift(uid, to_id), redeem(code), sent log
  web/app.js      # + FRIENDS tab, Gift action in the inventory selection bar
```

`gifting.py` depends only on the stdlib (`json`, `zlib`, `base64`, `binascii`, `secrets`) and
holds no Anki imports, so it is unit-testable like the rest of the engine — and portable if a
server ever does appear.

### Code format

```
CS2GIFT-1-<base64(zlib(json(payload)))>-<crc32>
```

- `CS2GIFT` prefix + version `1` — greppable, and lets a future format change be rejected cleanly.
- `crc32` suffix — catches truncated pastes, which chat clients cause routinely.
- Payload: `{n: nonce, to: <recipient id>, fr: <sender id>, i: {case_id, id, weapon, skin,
  base_value, rarity, float, stattrak}}`

**The payload carries no `value` and no `name`.** The recipient recomputes both locally via
the existing `unboxing.wear_tier()` and `unboxing.value_for()` against *their own* price data.
This keeps valuation locally authoritative — a doctored `value: 999999` in a code is simply
ignored, because the field does not exist — and it means the two players' catalogs need not
agree.

### Player ID

Generated once on first run, stored in `state["player_id"]`, format `CS2-XXXX-XXXX` from
`secrets.token_hex`. Displayed in the FRIENDS tab with a copy button. It is an identifier,
not a credential: it is not secret and proves nothing. That is fine — it exists to route
gifts, not to authenticate them.

### Data flow

1. **Gift:** select a skin → Gift → paste friend's Player ID → `controller.gift(uid, to_id)`
   → `economy` removes the item (favourite guard first) → `gifting.encode()` → code appended
   to `state["sent_gifts"]` → shown with a Copy button.
2. **Redeem:** paste code into FRIENDS tab → `gifting.decode()` validates prefix, version,
   crc32, `to == my player_id`, `fr != my player_id`, and nonce not in
   `state["redeemed_nonces"]` → `economy.receive_item()` recomputes wear/value/name locally
   and appends to inventory, tagged `from: <sender id>` → nonce recorded.

### Error handling

Every rejection is a specific, actionable message rather than a generic failure:

| Condition | Message |
|---|---|
| Bad prefix / not a code | "That doesn't look like a gift code." |
| Unknown version | "This code was made by a newer version of the add-on." |
| crc32 mismatch | "That code looks incomplete — copy the whole thing." |
| `to` != my id | "This gift is for CS2-XXXX-XXXX, not you." |
| `fr` == my id | "You can't redeem your own gift." |
| Nonce already used | "You've already redeemed this gift." |
| Favourite | "Unfavourite it first." (mirrors the sell/trade-up wording) |

### UI

- **Inventory selection bar:** a `Gift` button beside the existing Favourite / Sell selected.
  Single item only in v1 (multi-item gifting is one code per item; revisit if wanted).
- **New FRIENDS tab:** your Player ID + copy; a redeem box (paste + Redeem); the Sent log with
  re-copy. Tab bar becomes 5 wide — the topbar already wraps at minimum sidebar width.
- Gifted items show `from CS2-XXXX-XXXX` in the inventory cell.

## Testing

Pure-Python, no Anki import, consistent with the existing 62 tests:

- Round-trip: encode → decode reproduces the item exactly.
- Value is recomputed, not trusted: a payload with an inflated `base_value` yields the
  recipient's own correct valuation.
- Rejections: bad prefix, wrong version, corrupted crc32, truncated code, wrong recipient,
  self-gift, replayed nonce.
- Favourite cannot be gifted.
- Gifting removes from sender's inventory exactly once; redeeming adds exactly once.
- Catalog mismatch: an item from a case the recipient's catalog lacks still redeems, with
  wear/value derived from float + their price data.
- Persistence: sent log and redeemed nonces survive a reload.

## Explicitly out of scope

- Two-way atomic swaps (a trade is two gifts).
- Currency gifting.
- Any server, account system, or global market.
- Signed codes. There is no shared secret and no PKI in Anki's bundled stdlib, and signing
  would not stop the only attack that matters (a user editing their own save).
