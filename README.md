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

Compute lives in `analysis.py` and below; `report/` only formats what it is
given, which is what lets the tests assert on numbers instead of scraping
stdout.

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

A hypergeometric over coloured sources is in here as `at_least_in_draw()`. It
is **not** a castability figure and must never be reported as one: it asks
whether you drew N sources, not whether you have enough lands in play to cast
the spell, and it cannot see filter lands or sequencing.

It was called `hypergeometric()` until the name was changed to state the
question rather than the maths — a function whose only documented property is
"never quote this" is a trap, and that one was short enough to paste into a
primer. The old name is not aliased; it raises and names the replacement.

What it is legitimately for is a question purely about the draw — how often an
opening seven holds at most one land — which is the opening-hand floor `mana`
prints below the play simulation.

### No mulligan is modelled, and `mana` says how much that costs

`playsim` deals seven and never looks back, so every opening hand is kept,
zero-land hands included. Real play mulligans, which makes **every play-
simulation figure a floor**, not an estimate. `mana` prints the size of that
floor for the deck in front of it:

```
  No mulligan is modelled: every opening seven is kept, so the figures above are FLOORS.
  38.2% of opening sevens hold at most one land (9.9% hold none), off 27 lands in 99.
```

The share is large — around one hand in seven on a 40-land deck — and it
**moves with land count**, so it skews decks against each other as well as
lowering each one. That matters most in `calibrate`, which puts decks side by
side in a single table.

Computed exactly rather than simulated: the opening hand is a counting
question. Modelling an actual mulligan is deliberately **not** done — it needs
a keep heuristic, and inventing one is the mistake `KNOWN_ISSUES.md` #13
records.

### Mana sources means lands *plus* cheap accelerants

Rocks and dorks of mana value 3 or less, plus MDFC land backs. Lands-only
understates castability badly — measured on one deck, `{2}{R}{G}{W}` on turn
five was 36.4% lands-only and 53.5% once accelerants were counted. The
lands-only figure is a statement about land count, not about castability.

**A source is a permanent with an activated ability that adds mana.** The cost
need not be `{T}`: Ashnod's Altar adds `{C}{C}` off a sacrifice and is a real
repeatable source. One-shots are not sources — Dark Ritual is an Instant, and
counting it as a permanent had it producing three mana every turn from the
moment it was drawn. Spells that merely *make* a mana-producing token are
excluded too: a Treasure's reminder text says "Add one mana of any color",
which once made a counterspell count as one of your sources.

### A ritual is a one-turn burst, in the play simulation only

Not counting a ritual at all understated a ritual deck by more than the
~3-point band the diagnostic below uses, so `playsim` now reads one out of hand
as a single-turn burst. The rules are narrow on purpose:

| rule | why |
|---|---|
| **net, not gross** | Dark Ritual `{B}` → `{B}{B}{B}` is **+2**. Gross is the bug `KNOWN_ISSUES.md` #2 removed. |
| **payable, in colour, off the board that turn** | A Dark Ritual with no untapped black source adds nothing. This is what makes it more than a flat bonus. |
| **one per turn, read after deployment** | It can never fund an accelerant — a rock bought with invented mana would still be there next turn. |
| **the clause must BE a sentence of mana symbols** | "Add {R} for each card in target opponent's hand" is an unknown quantity; a token's granted ability is not this card's mana. |

**The sources model still counts rituals at zero**, because it has no turn
ordering to attach "available on exactly this turn" to. The two models
therefore disagree by design on a ritual deck, which is one more reason every
quoted figure says which one produced it. `mana` names the rituals it counted
and their net, on its own line, and prints nothing when the deck runs none.

A ritual is **not** an accelerant and is never counted as one: the
`accelerants counted:` line, `skeleton` and the `variants --accel` sweep all
mean sources, and the sweep varies exactly what that number says.

**A triggered mana ability is the third category.** The activated-ability
pattern requires a colon, so a card whose mana arrives off a *trigger* matched
nothing and was dropped entirely — not misclassified, invisible. Lotus Cobra
and Nissa, Resurgent Animist are both MV ≤ 3, both make mana, and neither was
counted. The two trigger shapes are not equally reliable and are not treated
alike:

| shape | example | treatment |
|---|---|---|
| `phase` | *"At the beginning of your first main phase, add `{G}{G}`"* | counted — it fires on its own every turn, as reliable as a rock |
| `event` | *"Landfall — Whenever a land you control enters, add one mana of any color"* | flagged and excluded from generic totals, like restricted mana |

A phase-triggered source is also **offline the turn it enters**, for the same
reason a mana creature is: the beginning of your first main phase has already
happened by the time you cast it.

Worth stating plainly, because it is the surprising part: **recognising the
shape does not by itself surface the cards that prompted it.** Hulking Raptor
is MV 4 and Regal Behemoth is MV 6, against a default `max_mv` of 3, so both
stay outside the accelerant window. And Sword of the Animist adds no mana at
all — it fetches a land, which is a change to the land count partway through a
game and a different model entirely.

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

The same applies to conditional *accelerants* — Mox Opal needs metalcraft,
Chrome Mox needs a card to imprint, Mox Diamond discards a land to enter — all
of which are counted as full sources. Inventing probabilities for those board
states is precisely the mistake that once moved a commander-on-curve figure by
five points; `KNOWN_ISSUES.md` #13 records them instead.

## Subcommands

| Command | What it does |
|---|---|
| `fetch` | Build or refresh the Scryfall cache for a decklist |
| `verify` | Count, legality, colour identity, Game Changers, average MV, tapped classes |
| `mana` | The full mana pass: sources model + play simulation |
| `skeleton` | Slot budget and curve: `100 = commanders + lands + non-land`, asserted |
| `roster` | The roster walk: every cycle slot, IN / benched / buy |
| `variants` | Land and accelerant count sweep. Slow, opt-in |
| `combos` | Commander Spellbook full-deck audit |
| `own` | Ownership vs the ManaBox export, plus a grouped buy list |
| `contention` | Copies owned vs the number of decks wanting the card |
| `moxfield` | Fetch a live deck into decklist format |
| `write` | Write the final 100 and assert it back |
| `diff` | Card-multiset diff of a local list against the live Moxfield deck |
| `audit` | verify + mana + roster + combos + own |
| `ceiling` | EDHREC (or `--cedh` edhtop16) inclusion: what is above the bar and missing, with ownership and price |
| `floor` | The inverse: what is **in** the list and below the bar, so a cut has a number beside it |
| `calibrate` | Re-measure every live deck into one table |
| `selftest` | Run the test suite |

Flags: `--cache` (default `scry.json`), `--sims` (8000), `--trials` (20000),
`--reps` (3), `--seed` (17), `--out`, `--decks`, `--lands`, `--accel`,
`--adds`, `--cuts`, `--swap`, and for `ceiling` and `floor`: `--rec-cache`
(default `edhrec.json`), `--cedh`, `--bar` (50), `--sort`.

### Every figure carries its own noise

`mana` and `variants` print `72.3±0.2%`, and the header names the budget, the
replicate count and the seed that produced it. The bar is the standard error
of the **reported** figure — the mean of `--reps` replicates — not the spread
of the replicates themselves, which would overstate it by `sqrt(reps)`.

**A gap smaller than the two bars beside it is noise, not a finding.** Without
this, a 0.4-point difference between two manabases read exactly like a
4-point one, and separating them meant running seeds by hand and computing the
spread outside the tool.

`--sims` and `--trials` are the budget for the whole measurement, **split
across `--reps`, not multiplied by it**. A default run therefore does the same
work it always did and its mean is exactly as precise as it was; the error bar
comes out of re-slicing that budget. `--reps=1` reproduces the pre-replicate
numbers exactly at the same seed, and prints `±0.0`.

### `skeleton` — the slot budget, before you pick cards

```
python3 mana_model.py skeleton deck.txt --cache scry.json
```

Land count, non-land count, the curve and the counts by type — the numbers you
set *before* selecting cards, and the ones that otherwise get done by hand.

**The identity is asserted, not printed for you to check.** `100 = commanders +
lands + non-land` is verified in `deck_skeleton`, which raises when it does not
hold and names the cards that landed in no category (in practice, a name
Scryfall could not resolve). Hand arithmetic once shipped a header reading
"24 lands plus 75 non-land" for a 100-card deck — the commander was missing
from the sum and nothing caught it.

The two manabase levers sit on one line, land count beside accelerants at
MV ≤ 3, because they are what you trade against each other.

Categories are **type lines**, not functional roles. Ramp, draw and interaction
are what a skeleton really budgets, and they are not inferrable without a
heuristic this repo would have to invent, so they are absent and said to be
absent. The one functional count is measured: accelerants come from the same
gate the mana models use.

### `ceiling` — what is above the bar and missing

```
python3 mana_model.py ceiling deck.txt --rec-cache edhrec.json --bar 65
python3 mana_model.py ceiling deck.txt --cedh          # edhtop16 instead
```

Which cards above the inclusion bar for this commander are **not** in the list,
whether they are already owned, and what the rest cost. **Network** on a cache
miss, like `calibrate`; the frozen fixtures under `tests/fixtures/` keep the
suite offline.

Four things this encodes so they are not rediscovered:

- **The EDHREC slug drops apostrophes, it does not hyphenate them.**
  `yshtola-nights-blessed` resolves; `y-shtola-nights-blessed` returns **403**,
  so a wrong slug reads as a block rather than as a typo.
- **A partner pair is one page, in alphabetical order.** The wrong order is not
  a 404 — it is a 200 carrying `{"redirect": ...}` and no cardlists, which
  parses as zero ranked cards and reports a deck with nothing missing. The
  command refuses to print an all-clear from a page that ranked nothing.
- **Cardlists are capped at 50.** Absence from a capped list is unknown
  inclusion, never 0%, and the report says so.
- **The two sources disagree about names in opposite directions** — EDHREC
  returns front faces (`Agadeem's Awakening`), edhtop16 returns full names
  (`Sink into Stupor // Soporific Springs`). Everything is keyed to the front
  face; getting this wrong once reported an in-deck card as missing.

With `--cedh`, the tournament entry count is printed beside every percentage,
and below five entries **no percentage is quoted at all** — at four entries
every card is 25%, 50%, 75% or 100%.

#### Decision notes: why a card is *not* in the list

Ten of nineteen rows on a real run were cards already rejected, with reasons.
Without a record every run re-litigates them. The record lives **in the
decklist**, as comments `read_decklist` has always skipped:

```
# CUT: Wakening Sun's Avatar -- board wipe kills [[Craterhoof Behemoth]] too
# TRAP: Sword of the Animist -- ramp that needs combat; [[Sol Ring]] is faster
# DEFER: Displacer Kitten -- revisit once [[Dockside Extortionist]] is in
```

`ceiling` then annotates the row instead of re-proposing the card:

```
  Displacer Kitten                      7.9%  -0.045     896/11360    0  $29.99
      DEFER revisit once [[Dockside Extortionist]] is in
```

Three decisions, and each is the opposite of the obvious one:

**In the decklist, not a separate store keyed by commander.** A second store is
a thing nothing keeps honest — its entries are invalidated by deck changes it
cannot observe, and nothing fails when they go stale. In the decklist, a note
travels in the same file as the cards it reasons about, changes in the same
diff, and is reviewed by whoever edits the list. It is also keyed **per deck**,
which is the right key: two builds of the same commander diverge on the first
swap.

**Annotates, never suppresses.** Hiding rejected rows behind a flag is the one
thing a note must not do — a stale `CUT` would silently remove a card that has
since become right, and a shorter table reads as less work to do.

**The notes are falsifiable, which is what makes them storable at all.** This
repo does not store measurements; `report_calibrate` says *never quote a stored
row*. A judgement can be stored only if something can tell you it has gone
wrong, so reasons cite cards with `[[...]]` — the same markup `primer` uses,
checked by the same extractor — and `ceiling` reports both ways a note expires:

```
  NOTES THAT NOW CONTRADICT THE LIST (1):
    line 12: Sol Ring is marked CUT and is IN the deck

  NOTES WHOSE REASON HAS EXPIRED (1):
    line 11: Displacer Kitten -- reason cites Dockside Extortionist, no longer in the deck
```

The separator is ` -- ` rather than a comma or a colon because card names
contain commas constantly — every *"Name, the Title"* legend.

#### Land rows are cross-referenced against the roster

Inclusion is the right tool for spells and the wrong one for lands: EDHREC's
land data reflects the population playing the commander, which is a budget
population. `roster.py` already enumerates every cycle slot per colour pair,
**best first**, so it can answer what inclusion cannot — is this land worse than
what is already filling that slot:

```
  Glacial Fortress                     79.2%  +0.300    9000/11360    0  $0.32
      ROSTER: WU already holds Tundra (ABUR dual), Hallowed Fountain (Shockland), Flooded Strand (Fetchland); this is the Checkland
  Canopy Vista                         78.3%  +0.290    8900/11360    0  $0.28
      ROSTER: WG already holds Savannah (ABUR dual), Temple Garden (Shockland), Windswept Heath (Fetchland); this is on no roster cycle
```

Two mechanisms, because one is not enough. A land **on** a roster cycle gets its
pair and its rank from the cycle table. A land on **no** cycle — a battle land,
say — gets its pair from its **basic land types** (`Land — Forest Plains` → `WG`)
and ranks below every cycle, because that is what being on no cycle means.
Without the second mechanism a battle land is indistinguishable from Gaea's
Cradle.

It **annotates, never suppresses**. A suppressed row is indistinguishable from a
row that was never ranked, and a shorter table reads as less work to do.

And it stays quiet wherever the roster has no opinion, which matters more than
the verdicts:

- **A land with no colour pair** (Gaea's Cradle, Urza's Saga) gets nothing.
  These are among the best rows the table will ever print, and a "not on the
  roster" warning would land on exactly the cards worth buying.
- **An any-colour slot** (Exotic Orchard, Unclaimed Territory) is named by the
  roster but carries no quality ordering, so it is not ranked. These two are the
  known residue: the roster cannot say they are worse than what is in.
- **A pair with nothing better already in it** is not a downgrade.

The comparison is one-directional: holding the WU Pathway does not make the ABUR
dual a downgrade, it makes it the upgrade.

#### The Commander Spellbook cross-check

A ceiling row is ranked on how often *other people* play the card. That says
nothing about what it does with **this** list. Every row is therefore checked
against Commander Spellbook's `find-my-combos` and annotated inline when it
would complete a combo the deck already half-holds:

```
  Hullbreaker Horror                    6.8%  +0.041     767/11360    0  $6.38
      COMBO with Sol Ring, Permanent Castable for {C} (template) -> Infinite colorless mana, Infinite storm count
```

**On by default**, because the rows this catches are the ones you would never
have looked up. On the deck that prompted it, both interacting rows sat at 7.9%
and 6.8% inclusion — below any default bar, reachable only by *lowering* it,
which is exactly the moment nobody thinks to add a flag. `--no-combos` skips it.

Three rules:

- **A combo is a fact, not a recommendation.** The interaction that prompted
  this was a card forming a *forced draw* with two cards already in the deck.
  Whether an interaction argues for or against a card is not Spellbook's to
  say, and the report does not pretend otherwise.
- **"Also needs X" is printed.** Spellbook's *almost included* means at least
  one piece is missing, not exactly one, so a combo needing two more cards must
  not read like one this card finishes on its own. Templates
  (`Permanent Castable for {C}`) count as pieces.
- **An outage is announced, never silently clean.** If Spellbook fails, the
  report says the cross-check did not run and that the rows are *not* known to
  be free of combos — an unrun check and a clean result are otherwise the same
  empty column. `ceiling` still prints its table.

#### `--sort=synergy`

Inclusion alone cannot tell a commander-specific card from generic goodstuff:
Sol Ring is played in most decks ever built and that says nothing about *this*
commander. EDHREC ships the discriminator — `synergy`, the gap between a card's
inclusion here and its inclusion wherever else it is legal — in the same
payload, so the `syn` column costs nothing extra to fetch.

```
python3 mana_model.py ceiling deck.txt --sort=synergy
```

Two rules the column follows:

- **The bar stays on inclusion whichever way the table is sorted.** Synergy is
  a difference of two rates and is noisiest exactly where inclusion is lowest,
  so a bar on synergy would promote cards played in one deck in ten over the
  staples the audit exists to catch. `--sort` orders rows; it never selects
  them.
- **Unknown synergy prints `-` and sorts last, never 0.0.** Zero is a *measured*
  value — it is what a card played at the same rate everywhere scores — so a
  missing figure rendered as zero is a specific, plausible, wrong claim. Every
  `--cedh` row is unknown: edhtop16 does not carry the statistic.

### `floor` — what is in the list and the population is not playing

```
python3 mana_model.py floor deck.txt --rec-cache edhrec.json
python3 mana_model.py floor deck.txt --bar 40 --sort=synergy
python3 mana_model.py floor deck.txt --cedh          # edhtop16 instead
```

`ceiling` prices an **addition**. Nothing here priced a **cut**, so every cut
was decided by hand — and by hand it proposed four in one session with the
inclusion figure pulled for none of them. Two of those four were at **75.5%**
and **64.5%** under that commander and went back in a day later.

Same flags as `ceiling`, same bar, read the other way: a card in the list and
*below* the bar is a cut candidate. Three blocks, and every non-land card in
the list appears in exactly one of them — the identity is asserted, not printed
for you to check.

**Rows above the bar are printed, not counted away.** They are not findings,
but they have to be *findable*: a cut you have already half-decided has to be
lookupable, and a card silently absent from the table teaches you that absence
means "safe to cut". That is the exact failure this command exists to stop.

#### Absence is a bound, and its size depends on the list

EDHREC ranks the top of each cardlist and stops, and **each list stops
somewhere different**. Measured on one commander page, 2026-08-16:

| list | rows | lowest shown |
|---|---|---|
| Creatures | 50 | 5.80% |
| Instants | 42 | 5.06% |
| Mana Artifacts | 16 | 5.44% |
| Sorceries | 15 | 5.36% |
| Enchantments | 11 | 5.34% |
| Utility Artifacts | 6 | 5.55% |

So an absent creature is only known to be below the point where the 50-row cap
fell, while an absent enchantment is below 5.3% and that is real evidence. The
depths move with the population, so they are read off the page fetched in that
run and never pinned in code. A row for an unranked card prints as a **bound**
— `<=5.1%  below the 'Instants' display floor (42 ranked rows)` — never as a
number and never as blank. The depth quoted is the number of rows that carried
a ratio, which is what the floor was measured over, rather than the number the
page displayed.

`<=` rather than `<` because the floor is the lowest figure the list actually
printed, and a tie on the boundary row is broken by something the payload does
not expose.

Three rules the bound follows:

- **Only a cardlist named for a card type can bound anything.** `New Cards`,
  `High Synergy Cards` and `Game Changers` filter on recency, synergy skew and
  the bracket list — not on inclusion — so absence from one says nothing at
  all, and they stop at 8.2%, 73.9% and 74.5% on the page above. Read as
  display floors they would put Sol Ring, at 96.6%, "below 74.5%" and rank it
  the safest cut in the deck. `Top Cards` is excluded for the other reason: it
  *is* ranked on inclusion, so its 68.7% is a real bound and a uselessly weak
  one, and under the weakest-bound rule below it would swamp every type list.
- **Where two lists could hold a card, the weakest bound wins.** An Artifact
  Creature is a creature to EDHREC and `Sorcery // Land` is filed under Lands,
  but nothing in the payload says which face a page filed a card by. Guessing
  would turn a filing convention into a claim about the card.
- **A type the page never ranked gets no bound at all** — printed as `?`, not
  as a low number and not as an empty cell. "The page could not say" and
  "below the floor" are different statements and only one is evidence.

With `--cedh` the rule inverts, and it has to: edhtop16 counts **whole
decklists**, so a card it does not rank appeared in zero of them. That is a
*measured* 0%, printed with the entry count beside it (`0/6`), not a bound.
Reading either source's convention onto the other is wrong in both directions.

#### Lands are excluded

Not scored and hidden — excluded, and the count is reported. EDHREC's land data
reflects a budget population, so inclusion is the wrong instrument for a land;
`roster` is the right one and already walks every cycle slot best-first.
`ceiling` annotates its land rows against that walk, and repeating the
judgement here would be a second, weaker copy of it.

#### `--sort=synergy` runs the other way here

Ascending, unlike `ceiling`: the most *negative* synergy is the most off-plan
card, which is the end of the axis a cut list wants. Unknown synergy still
sorts **last** rather than at zero — "we do not know" is not evidence for a cut.

### `primer` — every `[[Card]]` link, checked

```
python3 mana_model.py primer deck.txt --primer primer.md
```

Exits non-zero on a finding, so it works as a pre-commit or CI check. A primer
is prose, so nothing else here checks it, and it goes wrong in two ways that
are invisible in the source text:

- **A link broken across a line does not render.** Hard-wrapping a paragraph
  puts a newline inside the brackets, and the link shows up as literal text,
  brackets and all. The words still read correctly in the markdown, so
  proofreading the prose does not catch it. This is also why the link pattern
  is written with `re.S`: *without* DOTALL a wrapped link does not match at
  all, and the check walks past the one link on the page that is broken and
  reports the primer clean.
- **A link outlives the card.** Cut a card and the primer still argues for it.
  Editing a decklist touches nothing in the prose that discusses it, which is
  the single most common way a primer goes quietly wrong.

Also reported: a name Scryfall does not know (a typo renders as a dead link),
and an opening `[[` with no closer — which the link pattern cannot match by
construction, so without an explicit check it is not merely unreported but
invisible.

`|SET` codes are stripped before lookup, DFCs match on the front face whichever
side spells out both halves, and a broken link is reported **once** rather than
also as not-a-card and not-in-deck — one broken link is one problem, and
listing it three times buries the other findings.

**Network** on a cache miss, like `ceiling` and `roster`: a link naming a card
that is not in the list is exactly the interesting case, so its Scryfall record
was never fetched by the decklist pass.

### Measuring a named swap

```
python3 mana_model.py variants deck.txt --swap="Clifftop Retreat->Rugged Prairie,Rootbound Crag->Fire-Lit Thicket"
```

`variants` sweeps counts. `--swap` measures a *named* change: the same deck
before and after, at the same seed, on the same lines, with the delta and the
noise on that delta beside each other. The count sweep is not run — it answers
a different question, and the output says so.

Each cut must be in the deck and each add must not be, or the command
**raises**. That is deliberate: a silent no-op prints "nothing moved", which
is exactly what a correct run prints when a swap genuinely changes nothing —
so the failure would be indistinguishable from the finding. And "this swap
changes nothing, because the deck has no unmet pip" is a real, useful answer.

A name containing a comma needs `;` between pairs, since `,` is the default
pair separator: `--swap="Muldrotha, the Gravetide->X;Island->Swamp"`.

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

Around 700 cases, offline, under half a minute. Deliberately rounded: the
exact count moves with every merge, and three files quoting three different
figures is how a reader learns to distrust all of them. `pytest` prints the
real number. No test touches the network; anything that would need Scryfall or
Moxfield uses a frozen fixture instead.

### The invariant

**No output may change.** Not "should be equivalent" — measured equal, on real
decks. Nearly every function here encodes a bug that once shipped a wrong
number into a document someone acted on, and a refactor that moves a
probability by half a point is worse than no refactor, because the number still
looks plausible.

`tests/test_golden.py` enforces it: it runs the current code over checked-in
fixtures with a fixed seed and asserts the stdout is byte-identical to committed
snapshots, for `verify`, `mana`, `roster`, `skeleton`, `variants` and
`--help`, on four decks. `variants` is snapshotted at a reduced `--trials`: it
sweeps six configurations, so at the default budget it would cost the suite
more than everything else in it together.

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

`KNOWN_ISSUES.md` began as the fourteen things found during the migration that
looked wrong and were deliberately left alone, because fixing any of them would
change a reported number and the migration's contract was that none do. Each
entry says what it costs and which way it moves the figure. Most are now FIXED;
#8, #11, #13 and #14 are RESOLVED — examined and kept, with the reasoning
written down.

It did not stop being useful when the list emptied. #15 is an entry of the
other kind: a limitation priced and kept in #2, revisited later on purpose, with
the earlier entry left standing as the record of why the number moved the first
time. **A decision not to do something goes in there, not in a commit message
nobody greps.**

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
