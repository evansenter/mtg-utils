# mtg-utils

Deck validation and mana castability modelling for Commander decks.

It answers three kinds of question about a 100-card list, and it is careful to
say which one it answered:

- **Mechanical** — is this 100 cards, is everything legal, is anything outside
  the commander's colour identity, how many Game Changers, what is the average
  non-land mana value.
- **Mana** — can this deck actually pay the pips its spells demand, and does it
  have N mana on turn N. These are two different questions; see below.
- **Roster** — for every colour pair in the identity, is each premium land slot
  filled, and if not, is the card owned or does it need buying.

```
python3 mana_model.py audit deck.txt --cache scry.json
```

Standard library only. `pytest` is the sole dev dependency.

## The two models, and why they are not interchangeable

This is the single most important thing to get right when reading the output.

**The sources model answers "can I make these pips."** It draws
`7 + turn - 1` cards, requires at least one land and at least `turn` mana
sources present, and solves for whether the required coloured pips can be paid
— resolving filter-land activation as a pairing between the filter and another
source producing one of its two colours. It treats Sol Ring as one source and
ignores sequencing entirely.

**The play simulation answers "do I have N mana on turn N."** It draws seven,
draws one per turn, plays a land if it has one, deploys the cheapest affordable
accelerant, and reads off available mana at the target turn. It reports **on
the play and on the draw separately**, because in a four-player game you are on
the draw three turns in four and quoting only the on-the-play figure understates
by roughly ten points.

Anywhere a spell's mana value is close to the turn number — most obviously the
commander's own cast — the sources model understates badly. Use it for pip
questions on cheap spells. **Say which model produced any number you quote.**

A hypergeometric over coloured sources is in here as `hypergeometric()` and is
a fast sanity check only. It overstates castability: it asks whether you drew N
coloured sources, not whether you have enough lands in play to cast the spell,
and it cannot see filter lands. Never quote it.

### Mana sources means lands *plus* cheap accelerants

Rocks and dorks of mana value 3 or less, plus MDFC land backs. Lands-only
understates castability badly — measured on one deck, `{2}{R}{G}{W}` on turn
five was 36.4% lands-only and 53.5% once accelerants were counted. The
lands-only figure is a statement about land count, not about castability.

**Restricted mana is not mana.** Fíli and Kíli, Joyous taps for `{R}{R}` *"only
to cast Dwarf, Equipment, and Saga spells"*; Delighted Halfling's coloured mana
is legendary-only. `build_accel_profiles` flags these `restricted` and excludes
them by default, and `mana` prints which cards it dropped. If a line genuinely
qualifies, re-run with them counted and say so.

### Diagnosing: quantity versus colour

`mana` prints the generic "any N mana on turn N" baseline beside every line for
exactly one reason. A line **close** to its baseline is a quantity problem and
no land swap will move it. A line **far below** its baseline is a colour
problem and a filter land for that pip is the answer. In practice the split is
sharp: treat a delta inside ~3 points as quantity and beyond ~9 as colour;
anything in between is a signal to look at the deck by hand rather than guess.

### "Enters tapped" has three classes and only one is a cost

- **Unconditional** — Triomes, tri-lands, most surveil lands. A real cost,
  often bought with cycling or surveil value.
- **Conditional in your favour at four players** — "unless you have two or more
  opponents". Always untapped in Commander.
- **Conditional on a choice or board state** — shocklands (pay 2), The Black
  Gate and the Zendikar-style MDFC land backs (pay **3**), checklands.

Classes two and three are modelled as untapped and reported separately, with
the matched oracle text printed beside each one. The life figure varies across
the class, so the classifier matches `you may pay \d+ life`, never a literal
number — hard-coding the shockland's 2 sent The Black Gate and the whole
pay-3 MDFC cycle to TRULY TAPPED, a wrong verdict that looked right.

This means **the model cannot price a checkland's real downside at all**. When
a checkland question comes up, answer the turn-one-tapped part from the deck's
basic-type density in prose rather than pretending a number covers it.

## Subcommands

| Command | What it does |
|---|---|
| `fetch` | Build or refresh the Scryfall cache for a decklist |
| `verify` | Count, legality, colour identity, Game Changers, average MV, tapped classes |
| `mana` | The full mana pass: sources model + play simulation |
| `roster` | The roster walk: every cycle slot, IN / benched / buy |
| `variants` | Land and accelerant count sweep. Slow, opt-in |
| `combos` | Commander Spellbook full-deck audit |
| `own` | Ownership vs the ManaBox export, plus a grouped buy list |
| `contention` | Copies owned vs the number of decks wanting the card |
| `moxfield` | Fetch a live deck into decklist format |
| `write` | Write the final 100 and assert it back |
| `diff` | Card-multiset diff of a local list against the live Moxfield deck |
| `audit` | verify + mana + roster + combos + own |
| `calibrate` | Re-measure every live deck into one table |
| `selftest` | Run the test suite |

Flags: `--cache` (default `scry.json`), `--sims` (8000), `--trials` (20000),
`--out`, `--decks`, `--lands`, `--accel`, `--adds`, `--cuts`.

`audit` deliberately does **not** run `variants` — the sweep is the expensive
part and is wasted work on a settled base. Run it explicitly when a manabase is
being designed or a land count is questioned.

`diff` exits 0 when the local file and the live deck have identical card
multisets and 2 when they do not, so it can gate a step rather than just print.
It compares the multiset, never `lastUpdatedAtUtc`, which moves on a
description or folder edit.

`calibrate` takes no target: it walks every public Commander deck on the
account and prints one table with a single UTC timestamp. Its rows are dated
measurements — regenerate them, never quote a stored one. They rot on three
axes at once: the deck changes, the model changes, and Monte Carlo noise moves
them a few tenths regardless.

### `argparse` and leading-minus values

```
python3 mana_model.py variants deck.txt --lands=-2,0,2 --accel=0,2
```

`--lands -2,0,2` is parsed as a flag, not a value. Use `=`.

## Decklist format

The commander **block** comes first — one line, or two for a partner or
background pair — then a blank line, then the deck:

```
# optional comment; moxfield --out stamps the deck id and fetch time here
Muldrotha, the Gravetide

1 Ancient Tomb
3 Forest
Sol Ring
```

`N Card Name` or a bare `Card Name` (which means one). Lines starting with `#`
are ignored. A file with no blank line falls back to "line one is the
commander", so older files still read.

Commanders are always a **list** internally. Taking only line one silently
produced a 99-card deck whose second commander's colours read as identity
violations.

`write` emits exactly this format and reads it back with assertions —
the count is 100, every intended add is present, every intended cut is absent.
Those assertions **raise**; they do not warn. A delivered list once did not
contain a swap its accompanying message described and was imported in good
faith.

## API quirks that are load-bearing

These are not preferences. Each one was established by testing and each one
will re-break if "modernised".

### Moxfield

`api2.moxfield.com` is the site's private backend: undocumented, unsupported,
read-only, low volume. Legitimate access is available on request via
`support@moxfield.com`.

**It must be called with `curl` and a full Chrome User-Agent string.** `urllib`
returns 403 regardless of headers — this is client fingerprinting, confirmed by
controlled A/B testing. Do not rewrite it to `requests` or `urllib`.

Behind an egress proxy that terminates and re-originates TLS, even `curl` gets
a Cloudflare 403, because the fingerprint the edge sees is the proxy's. That is
worth knowing before concluding the endpoint is down.

v3 shape: boards nest under `boards`, cards are keyed by opaque internal id, and
the board key union includes **`partners`** alongside `commanders`. Both are
commanders and both must be read, or a partner deck silently comes back at 99
cards with half its colour identity. The parse is isolated in
`parse_moxfield()` and raises rather than returning a plausible partial deck.

v3 card objects do **not** carry `game_changer`; a Moxfield zero is the field's
absence. Take Game Changer status from Scryfall.

### Scryfall

**Rate limits differ by endpoint.** `/cards/collection` tolerates 0.1–0.2s
between calls. `/cards/search` returns 429 at that rate and needs ~0.5s plus
backoff — and `rulings_uri` and `prints_search_uri` are search calls, so they
inherit the stricter limit. An unguarded per-card `prints_search_uri` loop at
0.12s silently 429'd and misclassified 100+ cards in a way that looked like a
real result.

Batch through `POST /cards/collection`, at most 75 identifiers per request,
**front-face name only** — the full `X // Y` form comes back in `not_found`.
Responses arrive under the full name, so the cache is keyed on **both** forms.

Send `Content-Type` **and** `Accept: application/json`; omitting `Accept`
returns 400.

The cache persists between subcommands: one fetch per deck, not one per
question. It is written back on every run.

### The collection file

`ManaBox_Collection.csv`, UTF-8 with a BOM (`encoding='utf-8-sig'`). It is the
authoritative ownership source. Its path is the `COLLECTION` constant in
`mtg_utils/sources/collection.py`.

Sum `Quantity` across rows, never count rows — the same card appears once per
printing and per finish. Match case-insensitively, and always also compare
`name.split(' // ')[0]`. **Accented names must match exactly**: `Lim-Dûl's
Vault` and `Lórien Revealed` false-flag without the diacritic.

Use `load_collection()` rather than rewriting the loader. The obvious version
is wrong:

```python
# WRONG -- double-counts every non-DFC, because both keys are the same string.
owned[name] += q
owned[name.split(' // ')[0]] += q
```

That bug shipped a contention report claiming two copies of a card when one is
owned, and hid three further contended cards by inflating their counts past the
threshold. The correct form only adds the front-face key when it **differs**.

**Basic lands are not tracked** in ManaBox, so they are filtered out of every
gap analysis. A naive ownership diff reports "Mountain — not owned" and it
looks like a real result.

## Layout

```
mtg_utils/
  cards.py         faces and DFC plumbing, enters_tapped, fetch_targets,
                   mana_amount, pips-relevant constants
  profiles.py      build_land_profiles, build_accel_profiles
  castability.py   pips_from_cost, castable, probability, playsim, playsim_report
  roster.py        PAIR_CYCLES, TRIPLE_CYCLES, ANY_COLOUR, roster_names, roster_status
  decklist.py      read_decklist, flat, as_cmdrs, write_deck, diff_multiset
  sources/         scryfall.py, moxfield.py, spellbook.py, collection.py
  analysis.py      verify, analyse_mana, worst_lines, commander_lines, collapse_temps
  report.py        every report_* printer
  cli.py           argparse wiring
mana_model.py      entry point; also re-exports the package as a library
tests/
```

**Compute is separate from printing, and that separation is load-bearing.**
`verify`, `analyse_mana`, `worst_lines`, `commander_lines`, `parse_moxfield`,
`diff_multiset` and `collapse_temps` return data; the `report_*` wrappers only
format it. That is what lets a test assert on numbers instead of scraping
stdout. Keep it that way.

`report_calibrate` is the one exception: it fetches, measures, picks the worst
line and prints in a single body. It is network-only, so no offline test could
verify a split of it, and splitting unverifiable code that produces numbers is
exactly what this repo exists to prevent. Left whole, deliberately.

`mana_model.py` remains the entry point, so every command already in use keeps
working. `python -m mtg_utils` is equivalent, and `import mana_model` still
works as a library import.

## Testing

```
pytest                      # or: python3 mana_model.py selftest
```

243 cases, offline, about 40 seconds. No test touches the network; anything
that would need Scryfall or Moxfield uses a frozen fixture instead.

### The invariant

**No output may change.** Not "should be equivalent" — measured equal, on real
decks. Nearly every function here encodes a bug that once shipped a wrong
number into a document someone acted on, and a refactor that moves a
probability by half a point is worse than no refactor, because the number still
looks plausible.

`tests/test_golden.py` enforces it: it runs the current code over checked-in
fixtures with a fixed seed and asserts the stdout is byte-identical to committed
snapshots, for `verify`, `mana`, `roster` and `--help`, on three decks.

Those snapshots were produced by the original single-file version, which lived
at `reference/mana_model_v0.py` through the refactor. While it existed the suite
asserted three ways — reference against snapshot, current against snapshot, and
reference directly against current — so the snapshots are provably the original
program's bytes and not something typed to make a test pass. The reference copy
is gone; the snapshots carry the invariant, and the tests that compared against
it skip with a message saying so.

**The snapshots are the definition of correct output.** Regenerating them is a
deliberate act: `pytest tests/test_golden.py --regen-golden` rewrites them from
the current code, which means it blesses whatever the code now prints. If you
intend to change what the tool reports, regenerate, review the diff, and commit
the snapshots alongside the code, saying what moved and why. If you did not
intend to change it, the failing diff is the finding.

### The three deck shapes

Mono-colour, multicolour, and **colourless**. The third is not optional. A
mono-colour deck never exercises the filter-land or multi-pip paths; a
multicolour deck never exercises the "colourless utility land costs a coloured
source" path; and neither has a `{C}` pip to get wrong. A `{C}`-parsing bug
survived a regression pass run on the first two, and it did not produce a wrong
number — it produced an **empty** worst-lines table, which read as "this deck
has no colour constraints".

So `test_golden.py` also asserts the colourless deck's table is non-empty. Two
empty tables compare equal perfectly happily.

**An empty result from your own tooling is a finding to investigate, never a
clean bill of health.**

### Rules for adding tests

- **Name each case after the bug it prevents.** The names are the changelog:
  `filter makes no black`, `no double count`, `dual amount is 1`,
  `rejects surviving cut`, `forests cannot pay {C}`,
  `Black Gate pays 3, still conditional`.
- **Mutation-check every new case.** Revert the code it guards, confirm the
  case fails, restore. A test that passes the moment it is written has not been
  shown to test anything. Two real examples from this repo: a commander-identity
  canary that used a **basic land**, which has an empty colour identity and can
  never register a violation; and a contention test whose substring check passed
  with the code it guarded removed, because of how `sorted()` orders
  `"[Bracket 3 Temp]"` against `"[Bracket 3]"`.
- **Write fixtures from verbatim Scryfall text, never a paraphrase.** A case for
  the MDFC land backs used the invented string `"enters tapped unless you pay 3
  life"`. No printed card uses that wording, so it passed while the real cards
  were misclassified.
- **Cases that look redundant usually are not.**
  `collection/sums quantities across printings` and `collection/no double count`
  assert the same value for two different reasons.
- **Fixtures are frozen.** To add coverage, add a new fixture; never edit an
  existing one. See `tests/fixtures/README.md`.

### Where a change is claimed to be behaviour-preserving

Run both copies and diff them. Do not reason about the code.

## Known issues

`KNOWN_ISSUES.md` lists twelve things found during the migration that look
wrong and were deliberately left alone, because fixing any of them would change
a reported number and the migration's contract was that none do. Each entry says
what it costs and which way it moves the figure. The largest is that the play
simulation never spends the mana it uses to deploy accelerants; the cheapest to
fix is the `verify` header claiming "1 commander" for a partner pair.

## Provenance

This tool spent its life as a single 1914-line `mana_model.py`, re-delivered
whole on every change because there was no other way to distribute it. That
rule — one file, complete, every time, no snippets or patches — existed because
a partial edit has to be reassembled by hand, and two copies of the mana model
is a worse failure than two copies of the instructions, since the wrong one
still produces plausible numbers.

The repository replaces the mechanism, not the reasoning. Git history is the
delivery channel now, and the golden suite is what makes a partial change safe
in a way that re-uploading the whole file never actually did. The "do not write
a second script beside it" rule still holds, and now has teeth: a parallel
implementation would have no fixtures, no golden baseline, and no reason to
believe its numbers.
