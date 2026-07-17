# CS2 Cases — configuration

All currency is **virtual**. No real money is involved.

> **The economy is fixed and not configurable.** Earnings (**$0.10 per card**), case prices
> (real market price + $2.49 key), and sell-back (**100%** of value) are locked in code so
> every player is on the same rules — a prerequisite for the planned global market. Only the
> cosmetic/data options below can be changed.

- **muted** — silence case-opening sounds. Default `false`.
- **reduced_motion** — skip the long reel animation and reveal instantly. Default `false`.
- **enable_online_refresh** — allow fetching the full catalog + images/sounds from a source. Default `false`.
- **data_source_url** — base URL/manifest for the online refresh (only used when the above is on).

## Font

The UI uses **Chakra Petch** (a free squared, engineered grotesque close to CS2's Stratum2).
For a pixel-exact match, drop the real `Stratum2` font as
`user_files/assets/fonts/stratum2.woff2` and it takes over automatically. Stratum2 is
proprietary (Process Type Foundry / Valve) — personal use only.

## Real CS2 sounds

The add-on ships with the real CS2 case audio in `user_files/assets/sounds/`:
`tick.mp3` (the scroll click) and per-rarity reveal stingers `reveal_mil_spec.mp3`,
`reveal_restricted.mp3`, `reveal_classified.mp3`, `reveal_covert.mp3`, and
`reveal_special.mp3` (the knife/glove fanfare). Delete or replace any of them to change the
sound; anything missing falls back to a synthesized tone. These are Valve's audio — fine for
personal use, but mind the IP if you ever share the add-on.
