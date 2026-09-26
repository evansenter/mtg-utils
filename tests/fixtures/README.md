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
| `brawl.txt` / `brawl.scry.json` | Terra, Magical Adept -- a 60-card **Standard Brawl** list, identity WUBRG, built BRG |
| `make_fixtures.py` | Provenance: how the above were built, run once on 2026-08-15 |
| `brawl.arena.json` | Every Arena printing of every card in `brawl.txt`, projected -- see below |
| `make_brawl_fixture.py` | Provenance for `brawl.txt`/`brawl.scry.json`, run once on 2026-08-30 |
| `make_arena_fixture.py` | Provenance for `brawl.arena.json`, run once on 2026-08-30 |
| `ceiling.rec.json` | A real EDHREC commander page (Thrasios / Tymna), whole cardlists dropped to keep it small |
| `ceiling.top16.json` | A real edhtop16 response for the same pair, trimmed to 6 tournament entries |
| `ceiling.scry.json` | Scryfall records for the cards those two rank — a **projection**, see below |
| `primer.md` | A primer for the `multi` deck carrying one of each `primer` finding |
| `primer.scry.json` | Scryfall records for the cards `primer.md` links — a **projection** |
| `partner.decisions.txt` | `partner.txt` with a decision-note block on top — parses to the identical deck |
| `ceiling.combos.json` | A real Commander Spellbook find-my-combos response for `partner.txt`, trimmed to whole combos |
| `ceiling.lands.rec.json` | An EDHREC-shaped page ranking seven lands: four the roster can rank, three it deliberately cannot |
| `ceiling.lands.scry.json` | Real Scryfall records for those seven — a **projection**, kept for their type lines |
| `roster_brg.scry.json` | Whole Scryfall records for Ziatora's Proving Ground and Savage Lands, captured 2026-09-26 — the two BRG cycle members `roster --colours=BRG` looks up that `brawl.scry.json` never held |
| `fetchland.scry.json` | Whole Scryfall records for the fetch family, captured 2026-08-17 — every way a "search your library for a land" clause can behave |

## The `fetchland` fixture

Not a projection: whole records, because `verify` reads `legalities` and
`color_identity` off them as well as the oracle text. Twelve lands and one
commander, chosen one per behaviour rather than by deck:

| card | why it is here |
|---|---|
| Evolving Wilds, Terramorphic Expanse | produce nothing, fetch a basic **tapped** — scored untapped until `KNOWN_ISSUES.md` #23 |
| Fabled Passage | fetches tapped, then untaps on a board state neither model prices |
| Bad River | **enters tapped itself**, and its fetch is untapped — the other half of the same bug |
| Prismatic Vista, Wooded Foothills | fetch **untapped**: the class the old universal claim was true of |
| Terminal Moraine | carries the tapped-fetch wording *and* taps for `{C}` — the near miss the mana gate refuses |
| Plains / Island / Swamp / Mountain / Forest | the fetch targets: a fetch's colours are read off the basic types in the same deck |
| Kenrith, the Returned King | a five-colour commander, so `verify` can be run over any subset of the above |

Deliberately **no typed nonbasics** (no Bayou, no shockland). `fetch_targets`
matches a basic *type* rather than a basic *card*, which is correct for Verdant
Catacombs and wrong for Evolving Wilds — a separate finding, listed as a
residual under `KNOWN_ISSUES.md` #23 and not fixed there. Keeping duals out of
this fixture means none of its cases silently depends on which way that goes.

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

## The `brawl` fixture

The fifth shape, and the first that is not Commander. It was added because
none of the four Commander decks can break a claim about format or deck size,
and a green suite over fixtures that cannot break a claim is evidence about
the fixtures.

What it holds that nothing else here does:

- **60 cards**, so a hard-coded 100 fails on it -- 1 commander + 59, against
  100 = 1 + 99 everywhere else.
- **A DFC commander**, spelled with the front face in the file. That is the
  one shape where Moxfield (`A // B`) and Commander Spellbook (`A // B`)
  disagree with EDHREC (`A`) in opposite directions, and `diff` and `combos`
  each reported a wrong answer on it.
- **A five-colour identity on a three-colour build.** Terra is WUBRG; the list
  is BRG. `roster` walks the identity, so it prints the WU and W rows for a
  deck that will never play them.
- **A gated coloured half.** The Verge cycle -- `{T}: Add {R}. Activate only
  if you control a Mountain or a Forest` -- and Training Compound's board
  condition. No other fixture has a land whose colour is behind a condition.
- **A taxed coloured half.** Hidden Grotto, Conduit Pylons and Crystal Grotto
  all read `{1}, {T}: Add one mana of any color`, which was scored as a free
  five-colour source with the `{1}` nowhere.
- **A turn-conditional tap.** Starting Town enters tapped *unless it is your
  first, second or third turn* -- untapped early and tapped late, which is the
  mirror image of every conditional marker already modelled and was falling
  through to TRULY TAPPED.
- **A commander combo piece**, The Apprentice's Folly, which combos with Terra
  and only with Terra.

Every card in it is legal in Standard Brawl, and `test_golden.py` asserts
that: a fixture that quietly drifts out of the format it was built for stops
covering the thing it was added for. The manabase is chosen by hand for the
paths above; the 33 filler spells came from one `legal:standardbrawl ci<=wubrg
-t:land` search ordered by EDHREC rank.

The golden harness passes `--format=standardbrawl` for this deck and for no
other -- see `DECK_EXTRA` in `tests/conftest.py`. Run as Commander the same
file is a 60-card deck reported as 40 cards short, with its legality column
read off a key that says nothing about the format it is in.

## `brawl.arena.json`

One Scryfall search per distinct card in `brawl.txt`, `unique=prints`,
projected to the five fields `pick_arena_printing` reads (`set`,
`collector_number`, `rarity`, `released_at`, `games`, `legalities`). A
projection for the same reason `ceiling.scry.json` is one, and every value in
it is verbatim.

**Captured with no format filter applied**, deliberately: a file already
narrowed to one format could not test the selection at all, because every row
in it would be a valid answer. Abrade came back with five printings spanning
six years, which is what makes the "newest wins" rule testable.

**The three basic lands are truncated at 175 printings**, one Scryfall page:
the capture predates pagination in `arena_fetch`, and Swamp had 209 Arena
printings on 2026-09-24. Pages come back newest first, so the truncation drops
only the oldest printings and cannot change a pick; a cache hit never
refetches, so it stays as captured. The capture also holds `TRK` basics dated
2026-11-13 -- a preview set, which is what `test_an_unreleased_printing_is_not_named`
pins with `today` fixed on both sides of that date.

Two of the three selection filters reject NOTHING in it, and that is a fact
about the data rather than a gap. The search applies `game:arena` itself, and
Scryfall's `legalities` is an oracle-level field repeated identically on every
printing of a card — so neither can pick one printing over another. Both are
tested against hand-built candidates instead, and the cases say so, because a
case that passes for a reason other than the one it names is the failure this
repo has already been bitten by.

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
