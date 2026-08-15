# Golden fixtures

**These files are frozen. Do not regenerate them.**

They are the fixed inputs the golden suite diffs old-against-new output over.
Regenerating one changes the baseline without changing a line of code, which is
the one thing the golden suite exists to make impossible.

| File | What it is |
|---|---|
| `mono.txt` / `mono.scry.json` | Magda, Brazen Outlaw — mono-red (`R`) |
| `multi.txt` / `multi.scry.json` | Muldrotha, the Gravetide — Sultai (`UBG`) |
| `colourless.txt` / `colourless.scry.json` | Zhulodok, Void Gorger — colourless (identity `C`, empty string internally) |
| `collection.csv` | A ManaBox export with the real column set, UTF-8 with BOM |
| `make_fixtures.py` | Provenance: how the above were built, run once on 2026-08-15 |
| `ceiling.rec.json` | A real EDHREC commander page (Thrasios / Tymna), whole cardlists dropped to keep it small |
| `ceiling.top16.json` | A real edhtop16 response for the same pair, trimmed to 6 tournament entries |
| `ceiling.scry.json` | Scryfall records for the cards those two rank — a **projection**, see below |
| `primer.md` | A primer for the `multi` deck carrying one of each `primer` finding |
| `primer.scry.json` | Scryfall records for the cards `primer.md` links — a **projection** |
| `ceiling.combos.json` | A real Commander Spellbook find-my-combos response for `partner.txt`, trimmed to whole combos |

## The `ceiling` fixtures

Captured live on 2026-08-15 and frozen like everything else here. Values are
verbatim; the trimming removes whole records, it never edits one.

**`ceiling.rec.json` keeps `Creatures` at exactly 50 entries on purpose.** That
length *is* the signal: EDHREC truncates each cardlist at 50, so a card absent
from a full list is of unknown inclusion rather than unplayed. Trim that list
and `test_a_full_cardlist_is_marked_capped` stops testing anything.

**`ceiling.scry.json` is a projection**, not a whole Scryfall cache: each card
keeps only the fields the ceiling path reads (`name`, `type_line`, `prices`,
and identifiers). The full records for these 117 cards came to 1.2 MB, which is
a lot of committed bytes to price a dozen rows. Every value in it is verbatim.

**The cache keys matter.** `edhtop16_fetch` keys on `edhtop16/{first}/{name}`,
so a fixture built at one `first` is a MISS at another and the code goes to the
network. That happened while these tests were being written: the case stayed
green against 100 live entries instead of the 6 committed ones. `_no_network`
in `test_ceiling.py` now makes any outbound call an assertion failure, which is
the only reliable way to notice.

## Why three shapes

A mono-colour deck never exercises the filter-land or multi-pip paths. A
multicolour deck never exercises the "colourless utility land costs a coloured
source" path. **Neither one has a `{C}` pip to get wrong**, which is how a
`{C}`-parsing bug survived a regression pass run on the first two — it turned a
whole archetype's worst-lines table empty, and an empty table reads as "no
colour constraints" rather than as a failure.

The colourless fixture is not decoration. Zhulodok's own cost is `{5}{C}`, so
the commander line itself carries the pip, and `test_golden.py` asserts that
deck's worst-lines table is **non-empty** rather than merely equal — two empty
tables compare equal perfectly happily.

## What each fixture deliberately covers

- **mono** — a restricted accelerant (Fíli and Kíli, Joyous: `Add {R}{R}`, Dwarf
  and Equipment and Saga spells only), an accented card name matched exactly, an
  MDFC land back that pays 3 life, a conditional tap (`unless you control a`),
  a truly tapped land, and Game Changer lands.
- **multi** — all three filter lands of its pairs, both omni-typing lands
  (Urborg, Yavimaya), a karoo (`Add {B}{G}` is one alternative worth 2), three
  fetchlands whose `produced_mana` is empty, a Triome, both conditional-tap
  marker classes (shockland "you may pay 2 life", battlebond "unless you have
  two or more opponents"), three MDFC land backs, a split card whose top-level
  `cmc` is the sum of both halves, a two-brid cost, and a second restricted
  accelerant (Delighted Halfling, legendary spells only).
- **colourless** — real `{C}` pips on six spells and on the commander, a
  fetchland with no basic-type targets in the deck (zero colours, still a
  source), and Eldrazi Temple, whose restricted mana is **not** flagged because
  `restricted` is only modelled for accelerants, never for lands.

`collection.csv` covers one card across two printings and two finishes (must sum,
never double-count), a DFC keyed on both the full name and the front face, an
accented name, and roster cards owned but in none of the decks so the
`BENCH xN` branch fires. It contains no basic lands, because ManaBox does not
track them.

## Why the caches are committed

`scry_fetch` writes its cache back on every run, so the golden tests copy these
to a temp directory before running rather than letting the suite mutate its own
inputs.

The caches pin more than oracle text. `roster` and `own` print `prices.usd` and
`edhrec_rank`, both of which move daily — a refreshed cache changes those
outputs with no code change at all. Freezing them is what makes the output
diffable. The trade is deliberate: if a card is errata'd, the fixture diverges
from the real card. That is correct, because the fixture tests this code's
behaviour, not the card's truth.

## Reproducibility

`make_fixtures.py` is provenance, not a build step. Re-running it will **not**
reproduce these files byte-for-byte: Scryfall's `order=edhrec` ranking shifts
week to week, so a different set of filler cards comes back, and the price and
rank fields drift regardless. The fixtures are the artifact; the script records
how they came to exist and which code path each card was chosen for.

To add coverage, add a **new** fixture. Never edit an existing one — editing
changes what the suite covers while every test carries on passing.
