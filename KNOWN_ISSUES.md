# Known issues — found during the repo migration

Entries marked FIXED have been dealt with since; RESOLVED means the behaviour
was examined and deliberately kept, with the reasoning recorded; CHANGED means
a reported number was moved on purpose, with what moved written down beside it.
**Nothing here is currently outstanding.**

The file's job does not end when the list empties. It exists because a finding
that lives only in scrollback gets rediscovered — so a decision NOT to do
something belongs here too, not in a commit message nobody greps. #13, #14,
#18 and #20 are that shape, and #15 is the other one: a limitation that was priced,
kept, and later revisited deliberately, with the earlier entry left standing.
#17 carries a residual of the same kind inside an otherwise-fixed entry, with
the four repairs considered and why each was worse.

Everything here was found while moving `mana_model.py` into `mtg_utils/`, and
every one was left exactly as it was, because **fixing any of them would change
a reported number** and the migration's whole contract was that no output moves.

They are recorded here rather than in a chat message because a finding that
lives only in scrollback is a finding that gets rediscovered.

Each entry says what it costs and which direction it moves the number, so the
decision to fix or keep is yours to make deliberately. Several are arguably
correct-as-designed; they are listed because the behaviour is surprising, not
because it is definitely wrong.

Verified empirically against the committed fixtures, not asserted from reading.

---

## 1. The play simulation never spends the mana it uses to deploy accelerants — FIXED

`playsim`, the four-pass deployment loop.

Each pass recomputes total available mana from `online()` and deploys any
accelerant whose `cost` is at or below that total. Nothing is deducted. Two
untapped lands can therefore deploy Sol Ring *and* a two-drop rock in the same
turn, and the Sol Ring's own mana immediately counts toward the next pass, so a
third can follow.

**Cost:** inflates every play-simulation figure, and inflates it most in exactly
the decks that lean on accelerants. This is the largest single item on this
list.

**Fixed.** The loop tracks mana spent this turn and compares each candidate
against what is left, not against the board total.

The chain is deliberately preserved where it is real: an untapped non-creature
rock is online the turn it enters, so a Sol Ring cast off two lands leaves
1 + 2 = 3 available, and one-cost rocks that tap for one genuinely pay for each
other up to the four-pass cap. Deducting the cost is the whole change; it is not
a ban on deploying more than one thing.

Measured after the accelerant-gate fix had already removed the worst phantom
sources, so the remaining movement is modest — every line down, mean -0.4 to
-1.1 points, largest -1.8 (Reality Smasher T5, 81.2% -> 79.4%).

---

## 2. One-shot rituals are counted as permanent, repeatable mana sources — FIXED

`build_accel_profiles`, the second filter:

```python
if not re.search(r"\{t\}[^:]*:\s*add", txt) and "add " not in txt:
    continue
```

The `"add " not in txt` arm admits any card of mana value ≤ 3 whose oracle text
contains "add", regardless of whether it is a permanent or has a tap ability.

Measured on the committed multicolour fixture:

```
Dark Ritual        type=Instant  mv=1  -> counted as a source, amount=3
```

A one-mana instant is modelled as a permanent producing three mana **every turn
from the moment it is drawn**.

**Cost:** inflates both models in any deck running rituals. The multicolour
fixture contains Dark Ritual, so the committed snapshots embed this behaviour.

**Fixed**, and the survey found three distinct things being counted, not one:

- **Token reminder text.** An Offer You Can't Refuse and Deadly Dispute carry
  "Add one mana of any color" inside a Treasure's *parenthetical reminder
  text*; Warping Wail the same via an Eldrazi Scion. An Offer is a counterspell
  and its Treasures go to the **opponent**. Unambiguous.
- **Deferred, conditional mana.** Mana Drain adds `{C}` at your next main
  phase, and only if it countered something.
- **Real rituals.** Dark Ritual at `amount=3`, Seething Song at `amount=5`.

The rule is now: a **permanent** with an **activated ability that adds mana**,
matched against oracle text with parentheticals stripped. The cost deliberately
need not be `{T}` — Ashnod's Altar and Phyrexian Altar add mana off a sacrifice
and are real repeatable sources that a `{T}`-only rule silently drops. The strip
is applied to the accelerant gate only, never to lands, where an ABUR dual's
entire ability is reminder text.

Rituals are therefore not counted at all. That understates a ritual-heavy deck,
which is the deliberate trade: both models answer "what sources are available on
turn N", and a ritual is not one. Modelling a genuine one-shot burst would need
a new concept in both models and was not attempted.

Measured, matched line-by-line rather than by row position (the table is sorted,
so positional comparison compares different cards): **every line on every deck
moved down**, from -0.1 to -9.1 points. Muldrotha's commander line went 83.9% ->
74.8%. Accelerant counts fell 22->20, 18->14, 25->24 and 16->13.

**Any stored figure predating this is invalid for a deck running rituals or
Treasure-makers**, and the shift is larger than the ~3-point band the
quantity/colour diagnostic uses.

**Superseded in part by #15**, which models a ritual as a one-shot burst in the
play simulation. Nothing above is edited: this entry is the record of why the
number moved the *first* time, and the thing it removed — a permanent,
repeatable source producing its full amount every turn — is not coming back.
What #15 revisits is the sentence saying a genuine burst "was not attempted".

---

## 3. Restricted mana is modelled for accelerants but not for lands — FIXED

`build_accel_profiles` sets a `restricted` flag from `"spend this mana only"`.
`build_land_profiles` has no such flag, and neither model looks for one on a
land.

Measured on the colourless fixture:

```
Eldrazi Temple  "{T}: Add {C}.  {T}: Add {C}{C}. Spend this mana only to cast
                 colorless Eldrazi spells."
                -> amount=2, no `restricted` key at all
```

So Eldrazi Temple contributes two unrestricted mana to every line, including
lines that are not Eldrazi spells. The same applies to any land with conditional
output.

**Cost:** inflates colourless and tribal decks specifically. Note this is the
mirror of a bug the project already fixed once for accelerants — the reasoning
in `build_accel_profiles`' docstring applies verbatim to lands.

**Fixed**, and the survey found the *colour* half mattered more than the amount.
Scryfall puts one ability per line and the restriction rides on the line it
restricts, so dropping those lines leaves exactly the mana that pays for
anything:

| land | was | now |
|---|---|---|
| Eldrazi Temple | `{C}`, amount 2 | `{C}`, amount 1 |
| Cavern of Souls | **WUBRGC**, amount 1 | `{C}`, amount 1 |
| Unclaimed Territory | **WUBRGC**, amount 1 | `{C}`, amount 1 |
| Plaza of Heroes | WUBRGC | WUBRGC — unchanged, correctly |

Cavern and Unclaimed Territory were the damaging pair: their any-colour mana
only casts one creature type, and counting it as free colour gave a **mono-red
deck five colours**. Plaza keeps its colours because its third ability is
genuinely any-colour, merely conditional on board state — a condition the model
does not price, exactly as it does not price a checkland's.

A land whose every ability is restricted is flagged and dropped by both models,
mirroring a restricted rock. None of the fixtures has one; a synthetic case
covers it.

Movement: mono and colourless only (multi and partner have no restricted land),
every line down, largest -3.3 (Faithless Looting T1, 92.3% -> 89.0%).

---

## 4. The `verify` printer hard-codes "1 commander" — FIXED

`mtg_utils/cli.py`, the `verify` branch:

```python
print(f"  {v['total']} cards = 1 commander + {v['nonland']} non-land "
      f"+ {v['lands']} lands  ...")
```

`total` counts both commanders of a partner pair; the sentence claims one.
Measured on a synthetic partner deck:

```
printed: 100 cards = 1 commander + 8 non-land + 90 lands
         1 + 8 + 90 = 99, but total is 100
```

**The data is right and only the sentence is wrong** — `verify()` returns the
correct `total`, and the ported test `verify/arithmetic closes` asserts
`total == 2 + lands + nonland`. It is the format string that lies.

**Cost:** the header block of a partner deck's primer does not add up — which is
the exact failure mode the "make it arithmetically self-consistent" rule exists
to prevent.

**Fixed.** The count is `len(as_cmdrs(cmdr))` and the noun is pluralised. A
partner-pair fixture was added first, so the wrong arithmetic is in the git
history as a committed snapshot rather than only as a description of it. The
output change is one line on one deck shape; single-commander output is
byte-identical.

---

## 5. Deck size is hard-coded to 99 — FIXED

`analysis.py` twice, `report.py` once:

```python
probability(lands, accels, 99, ...)
playsim_report(lands, accels, 99, ...)
```

A partner or background deck has 98 non-commander cards, not 99. The simulation
draws from a library one card larger than the real one.

**Cost:** small and optimistic — it dilutes the library with one extra
non-source, biasing a partner deck's figures.

**Fixed.** The library size is now `len(names)`, the non-commander multiset,
threaded through `worst_lines`, `analyse_mana` and `report_calibrate`. On the
partner fixture 33 reported figures moved by a mean of +0.30 points, range
-0.1 to +1.0, none by more than a point; two rows of the worst-lines table
swapped rank as a result. Not every figure moved upward, because a smaller
library also changes the RNG draw sequence — the systematic effect is upward,
the per-line jitter is noise. Single-commander decks are byte-identical: their
library was already 99.

---

## 6. Omni-typing is applied to every source, not only to lands — FIXED

`castable`:

```python
omni = set(p["omni"] for p in sources if p.get("omni")) - {None}
def cols(p):
    return set(p["colours"]) | omni
```

Urborg, Tomb of Yawgmoth makes every *land* a Swamp. Here it makes every
*source* produce black, including mana rocks and dorks. Verified:

```
colourless rock + Urborg pays {B}{B}: True
```

**Cost:** overstates coloured availability in any deck running Urborg or
Yavimaya alongside colourless accelerants.

**Fixed.** The omni colour is applied to sources of kind `land` only.

No fixture output moved — at 8000 sims and 20000 trials the four committed
decks show no measurable difference, so this one is asserted directly rather
than through a snapshot. A real bug the golden suite happens not to exercise is
precisely the case that needs its own test, and it is mutation-checked.

---

## 7. Tapped-land counts are per entry; land counts are per quantity — FIXED

`verify` appends a land's **name** to `truly_tapped` / `conditional_tapped` once
per entry, while incrementing `lands` by the entry's **quantity**. The `mana`
header then prints both in one sentence:

```
=== MANA BASE (37 front-face lands + 3 MDFC land-backs, 3 truly tapped) ===
```

37 counts copies; 3 counts distinct cards. In Commander singleton they coincide
for everything except basics, which is why it has never bitten — but the two
numbers in that sentence are in different units.

**Fixed.** `verify` now returns `truly_tapped_copies` and
`conditional_tapped_copies` alongside the name lists, and the header prints the
copy count, so both numbers are in copies. The name lists still list each card
once. No fixture output moved, because the two agree in a singleton deck — a
test asserts they agree on all four fixtures, so a future fixture that breaks
the assumption is noticed rather than silently changing a header.

---

## 8. `scry_fetch` never caches a `not_found` — RESOLVED, keeping the behaviour

A name Scryfall cannot resolve is returned to the caller and is not written to
the cache, so every later run asks about it again.

**Cost:** none to correctness, and it is the right behaviour for a typo about to
be corrected. It is the wrong behaviour for a name that will never resolve, and
in `calibrate` — which walks every deck — it means a repeated round trip per
run.

**Resolved by keeping it, deliberately.** Caching a negative would make a name
permanently unfindable in that cache, and the two reasons a lookup fails are a
typo (fixed in the next run) and a card too new for Scryfall (findable in the
next run). Both want a retry. The cost is one round trip per unresolvable name
per run, against a failure mode where a real card stays invisible until someone
thinks to delete the cache. Pinned by a test as behaviour, and now stated as a
decision rather than left as an open question.

---

## 9. `report_variants` has a latent `TypeError` — FIXED

```python
basic = next((p for p in base_lands if not p["tapped"] and p["colours"]), None)
...
lands = base_lands + [dict(basic) for _ in range(dl)]
```

If no untapped colour-producing land exists, `basic` is `None` and `dict(None)`
raises `TypeError: 'NoneType' object is not iterable`.

**Checked, and it does not fire on any of the fixtures**, including the
colourless one: Wastes produce `{C}`, and `frozenset({'C'})` is truthy. It needs
a deck whose entire manabase is tapped or produces nothing.

**Fixed.** A positive `--lands` delta with no untapped colour-producing land to
clone now raises `SystemExit` naming the problem and the two ways out, instead
of a `TypeError` several frames later that reads as a crash.

---

## 10. `enters_tapped(face, card)` never uses `card` — FIXED

Every call site passes one. Harmless, and worth a moment's thought before
removing in case the second argument was meant to carry the whole-card context
that a land-back check would need.

**Fixed by making it optional** rather than removing it. `mtg_utils` re-exports
`enters_tapped`, so dropping the parameter would break any script still calling
`enters_tapped(face, card)`. Every call site keeps working and the signature no
longer demands an argument nothing reads.

---

## 11. The sources model assumes any drawn source is deployable — RESOLVED, by design

`probability` picks `turn` sources out of everything seen and asks whether they
can pay the cost. It does not model the one-land-per-turn rule, nor the mana
spent casting an accelerant.

So four lands plus a Sol Ring "have" five mana on turn five, without ever paying
the one to cast the Sol Ring.

**Resolved as by design.** This is the sources model's stated idealisation, not
a defect: it answers "can I make these pips", and the play simulation exists
precisely because it does not answer "do I have N mana on turn N". Both the
README and CLAUDE.md say so in those terms, and `report_mana` prints both models
side by side. Recorded so the optimism is explicit and nobody quotes a
sources-model figure as an on-curve number.

---

## 12. `moxfield` prints its header twice — FIXED

`cli.py` prints `# {name} (fetched ...)` to stdout, then builds a second,
slightly different header (`# {name} (deck {id}, fetched ...)`) into the text it
emits or writes. Printing to stdout shows both; writing to `--out` still prints
the first to the terminal.

**Cost:** cosmetic. The file written by `--out` contains exactly one header, so
`read_decklist` is unaffected.

**Fixed.** The bare header is gone; the one that survives carries the deck id,
because that is the provenance a delta has to name. Writing to `--out` now
prints only `wrote <path>`.

---

## 13. Conditional accelerants are counted as unconditional — RESOLVED, documented

Found while fixing #2 and #3, by sweeping the fixtures for counted sources whose
availability has a cost or condition the model does not read:

| card | condition |
|---|---|
| Mox Opal | metalcraft — dead until you control three artifacts |
| Chrome Mox | imprint — produces the colour of an exiled card, or nothing |
| Mox Diamond | discards a **land** to enter, so it converts a land into a rock |

Each is counted as a full, unconditional source.

**Resolved as a documented limitation, not fixed.** This is the same family as
the checkland downside the README already declines to price: the model does not
invent probabilities for board states. Inventing one here would repeat a failure
this project has already had — a play simulation once hard-coded tap
probabilities of 0.25/0.30/0.05 for three conditional lands, and those made-up
numbers moved a reported commander-on-curve figure by about five points.

Mox Diamond is the sharpest of the three, because its cost is a land: the model
gains a source and does not lose the land that paid for it. Worth saying out
loud when a deck runs it.

### Not an issue: Lotus Petal and other self-sacrificing sources

The sweep also turned up Lotus Petal, whose mana ability sacrifices it. It looks
like the ritual case from #2 and is not: both models read the mana available on
**one** turn, and a Petal on the battlefield genuinely provides one mana that
turn. Dark Ritual was excluded because an Instant is never on the battlefield to
be read at all, not because it is one-shot. Counted, correctly.

Commander's Sphere and Mind Stone also match "sacrifice this", but theirs is a
DRAW ability, not the mana one — a rule keyed on that phrase alone would have
dropped two ordinary rocks.

---

## 14. No mulligan is modelled — RESOLVED, documented and measured

`playsim` deals seven and never looks back, so every opening hand is kept,
zero-land hands included. Real play mulligans, so **every play-simulation
figure is a floor**, not an estimate.

Measured exactly over the committed fixtures — the share of opening sevens a
real player ships back:

| deck | lands (incl. MDFC backs) | P(0 lands) | P(<=1 land) |
|---|---|---|---|
| mono | 36 | 3.7% | 20.1% |
| multi | 40 | 2.3% | 14.4% |
| colourless | 27 | 9.9% | 38.2% |
| partner | 39 | 2.5% | 15.2% |

**Cost:** understates every play-simulation figure, and unevenly. The share
moves with land count, so a 27-land deck is penalised nearly three times as
hard as a 40-land one — which means it skews decks *against each other*, not
just the level of each. `calibrate` prints decks side by side in one table.

**Resolved by stating it with its size rather than by modelling it.** `mana`
now prints this deck's own figure below the play simulation, computed exactly
with `at_least_in_draw` — the opening hand is a counting question, so it has
an exact answer.

Modelling an actual mulligan is deliberately not attempted. It needs a keep
heuristic, and inventing one is precisely the failure #13 records: a play
simulation once hard-coded tap probabilities of 0.25/0.30/0.05 for three
conditional lands, and those made-up numbers moved a reported
commander-on-curve figure by about five points. A London mulligan with a
"keep 2-5 lands" rule is defensible and standard, but it is a modelling
choice that would move every number in the repo, and it should arrive as its
own commit with the snapshot diff shown.

---

## 15. One-shot rituals were not counted at all — CHANGED, the number moved on purpose

The residual left over from #2. That entry removed rituals-as-permanent-sources
and, having no concept of a one-turn burst to replace it with, counted them at
zero. Zero is wrong in the other direction, and by more than the ~3-point band
the quantity/colour diagnostic uses: a Dark Ritual in hand with an untapped
Swamp genuinely does give you three mana on turn one.

The line #2 drew was a claim about the data structure, not about the question:

> Dark Ritual was excluded because an Instant is never on the battlefield to be
> read at all, not because it is one-shot.

The play simulation advertises "do I have N mana on turn N". Lotus Petal and
Dark Ritual are both one-shot and both net-positive on exactly one turn, and
only one of them was counted — because only one of them is a permanent.

**What is modelled now**, in the play simulation only:

- A ritual is a non-permanent of mana value ≤ 3 whose oracle text carries a
  clause that IS a sentence and is nothing but mana symbols — "Add {B}{B}{B}."
- Its contribution is the **net**: Dark Ritual +2, Seething Song +2, Cabal
  Ritual +1. Gross is the shape of the #2 bug.
- It fires only if its own cost is payable, in the right colours, off sources
  already online that turn — so it is worth less in a deck that cannot reliably
  make its colour, which is what the play simulation exists to measure.
- One per turn, read from hand after accelerant deployment, so it can never
  fund a rock and never compounds.
- The card's own cost is ignored, consistent with the rest of the model, which
  prices mana available and not cards spent.

**The sources model still counts rituals at zero, deliberately.** It has no
turn ordering to attach "available on exactly this turn" to. So the two models
disagree by design on a ritual deck, and the sources-model row is the lower of
the two — one more reason a quoted figure must say which model produced it.

**What moved** (20,000 trials, 3 reps, seed 17; on the play):

| deck | line | before | after |
|---|---|---|---|
| multi | Muldrotha, the Gravetide on curve | 74.9% | 78.0% |
| multi | Memory T6 | 72.3% | 75.0% |
| multi | Counterspell T2 `{U}{U}` | 54.7% | 54.7% |
| mono | Etali, Primal Storm T6 | 80.9% | 83.5% |
| mono | Big Score T4 | 90.4% | 91.1% |
| mono | Magda, Brazen Outlaw on curve (T2) | 92.8% | 92.8% |
| partner | Tymna the Weaver on curve | 84.5% | 85.4% |
| partner | Eternal Witness T3 | 75.3% | 75.5% |
| colourless | *(no ritual in the deck)* | — | — |

Every move is upward, which is the only direction a burst can move a figure,
and the largest is +3.1. The rows that did not move say as much as the ones
that did: **Counterspell T2** needs `{U}{U}` and a black burst pays neither
pip, while its generic baseline beside it moved 92.7 → 93.2; **Magda on curve**
is turn two and Seething Song costs three; every turn-one line on every deck is
unchanged. The colourless deck runs no ritual and its snapshot is byte-identical
— `mana` prints the ritual line only when there is one, so a ritual-free deck
still produces exactly the bytes it produced before this existed, which keeps
that fixture a live control on the gate.

Note that **mono moved**, and the issue proposing this expected it not to. It
runs Seething Song, which is a ritual by exactly the reading that admits Dark
Ritual, and the issue names it as one two paragraphs above saying mono is
unaffected. Admitting it is correct; the expectation was the error.

**Known residuals, priced and kept:**

- **The sources that pay for the ritual are not spent.** The burst is added to
  the board rather than swapped for the sources it cost, so every source that
  paid for it keeps its own colours on top of the mana it made. The bound is
  **up to the ritual's mana value**, and it is the GENERIC portion of the cost
  that carries it: `pips_from_cost("{2}{R}")` is one red pip, so Seething Song
  is gated on a single red source and the other two are arbitrary. Off Island,
  Island, Mountain the model holds `{U}{U}{R}` plus a two-red burst and will
  pay a double-blue cost, where reality is five red and three tapped lands —
  two surplus coloured units, off basics, with no dual involved. Dark Ritual is
  the benign end: its whole cost is the pip it is gated on, so the source it
  spends produces the colour the burst produces anyway. It costs nothing on
  `mono`, whose surplus units are red in a red deck, which is why the fixtures
  do not show it. Modelling the payment properly means choosing WHICH sources
  are tapped — a search, inside the trial loop, for a fraction of a pip.
- **Mana already spent deploying an accelerant is still available to the
  burst.** The gate reads the board from `online()`, which is not reduced by
  `spent`, so on a turn that deployed a rock the ritual can be paid for with
  mana the rock already consumed. This is the convention the reading itself
  uses rather than a new departure from it: `out[t].append(srcs)` has never
  deducted `spent` either, which is the residual #1 left behind when it fixed
  the deployment DECISION. Tightening only the gate would make the ritual
  stricter than the figure it feeds — the line would be refused a mana the
  same turn's reported total still counts — so the two move together or not at
  all.
- **A held ritual is available on every turn it is held.** It is re-read from
  hand each turn and never lands on the battlefield, so it cannot compound; but
  turn five's reading assumes you did not fire it on turn one. That is the
  right reading of a per-turn question and of how a ritual is actually played —
  firing it on sight would model casting Dark Ritual into an empty hand — and
  it is the one place where "one-shot" is not literally simulated.
- **The ritual is chosen by net, not by the line being measured.**
  `ritual_burst` runs once per turn, before any line is evaluated, and takes
  the largest castable net. On a hand holding two rituals of different colours
  that can pick the one paying nothing toward the pips: Dark Ritual (net 2) and
  Pyretic Ritual (net 1) off Swamp, Mountain, Mountain gives `{B}{R}{R}` plus
  two black against a `{R}{R}{R}` line that the smaller burst would have paid,
  and the line reads uncastable when it is castable. Understates only, which is
  the direction this model errs on purpose; no fixture runs two rituals, so
  nothing committed here is affected. Choosing per line means moving the
  decision into `playsim_report` and searching inside the trial loop — the same
  bill the payment residual above declines to pay.
- **Treasure engines are still excluded.** Pitiless Plunderer and Warren
  Soultrader are an understatement in the same direction and stay out: their
  "add" text is a Treasure's reminder, and the rate at which they make one is a
  board state, which is what #13 declines to invent.

---

## 16. Restricted mana is read per line for lands and per card for accelerants — FIXED

The return leg of #3, and it was created by the fix for it. #3 taught
`build_land_profiles` to drop restricted mana one ORACLE LINE at a time, via
`unrestricted_mana`. `build_accel_profiles` was left on the substring test it
had always used:

```python
"restricted": "spend this mana only" in txt,
```

which is a whole-card verdict. One restricted line anywhere condemns the card,
and both models then drop it entirely.

The two shapes are printed on the same cards, so the divergence is not
theoretical:

```
Cavern of Souls (LAND)          {T}: Add {C}.
                                {T}: Add one mana of any color. Spend this
                                     mana only to cast a creature spell of
                                     the chosen type...
Delighted Halfling (CREATURE)   {T}: Add {C}.
                                {T}: Add one mana of any color. Spend this
                                     mana only to cast a legendary spell...
```

Identical two-line shape. The land was counted as a `{C}` source. The creature
was excluded from the accelerant list altogether — a one-mana dork, in the
multi fixture, invisible to every figure the tool reports.

**Cost:** understates any deck running a partly-restricted accelerant, and
understates it in the direction that matters least visibly. The free half of
Delighted Halfling's ability is colourless, so what it moves is the QUANTITY
question — the generic baseline and the on-curve line — while the colour lines
its restricted half could pay for move only by the free half. A missing
colourless source does not make a colour line look bad; it makes the deck look
one land short.

### Still per card: what the mana may be SPENT on

The flag is per line now. The consumption is not. `castability` either drops a
profile whole (`restricted`) or spends its colours freely; there is no third
option, no notion of "this mana pays only for spells matching X". So the free
lines' colours are all a partly-restricted card ever contributes.

The multi fixture is where that shows. Delighted Halfling's restricted half is
*legendary spells only*, and `Muldrotha, the Gravetide` is a Legendary Creature
— so the one line in that report its restricted half genuinely could pay for is
the commander line, and that is exactly the line it is not counted for. The
observed movement there (78.0 → 79.5 on the play) is the free colourless half
and nothing else.

Not a regression — the card went from invisible to a `{C}` source, which is
strictly closer — and not attempted here. Pricing it means threading the pip
requirement and the spell's characteristics down to the profile, which is the
turn-and-context coupling the sources model deliberately does not have. Written
down because the direction is conservative, and **an understatement nobody
records is one that gets rediscovered as a bug**.

**Fixed** by lifting the per-line logic into `drop_restricted`, called by both
builders, so the two paths cannot drift again. The `restricted` flag now means
"no line of this card produces mana with no strings attached", which is what
both models already assumed it meant.

Getting the flag right is only half of it. `produced_mana` lists what a card
CAN make without saying what it may be spent on — Delighted Halfling's is all
five colours plus `{C}` — so a card counted unrestricted while keeping that set
would hand a legendary-only ability to every pip in the deck. The colours are
replaced by the free lines' colours, exactly as the land path already did.

| card | was | now |
|---|---|---|
| Delighted Halfling | excluded (restricted) | `{C}`, amount 1, counted |
| Fíli and Kíli, Joyous | excluded (restricted) | unchanged — every line is restricted |
| every land | — | unchanged, byte for byte |

One gap was closed on the way in, because sharing the code moved it onto a path
where it was newly reachable. `unrestricted_mana` reads colours off `{w..c}`
symbols and the literal `"any color"`, and real cards are worded past both —
Gilded Lotus taps for "three mana of any one color", Reflecting Pool for "one
mana of any type that a land you control could produce". A free line worded
that way returns **no colours with a non-zero amount**: a source that counts
toward the generic total and can pay no pip. On the accelerant path
`if not pm: continue` used to make an empty colour set impossible, so this
would have been new surface. `drop_restricted` now falls back to
`produced_mana` there — over-broad on colour, right on quantity, never the
empty inconsistency.

Neither of those two cards carries a restricted line, so no fixture reaches it
and no number moves. Widening `unrestricted_mana` to read those wordings
properly is the other repair, and it would move land figures, so it belongs in
its own commit.

Movement: the multicolour fixture only, 13 counted accelerants -> 14, every
figure up. Largest +2.6 (Memory T6 sources model, 68.6% -> 71.2%); the
generic baseline moves +1.7 on the play and +1.4 on the draw; the colour
lines it cannot pay for move by less than the error bar (T2 `{U}{U}` 73.5% ->
73.3%, T1 `{B}` 81.1% -> 81.0%), which is the shape a colourless source
should have.

The play-simulation halves of those figures are quoted against #15's
snapshot, not the one before it — this landed on top of the ritual work and
the two touch the same table. The sources-model figures are untouched by
#15, rituals being play-simulation only, so those two numbers mean the same
thing before and after. #15's own line ("rituals counted... dark ritual +2")
is still printed above them.

### Found while fixing it: the max_combos non-bias test was a coin flip

`test_250_is_not_biased_against_exhaustive` asserts the truncated figure sits
within one point of the exhaustive one, at `SIMS=4000`, on three fixed seeds.
The PAIRED difference at that budget has an sd of about 0.0066 across seeds, so
one point is 1.5 sd — the test passed because those three seeds happened to
land inside it, not because 250 is unbiased. Counting Delighted Halfling put
one more source in the turn-7 hand and seed 17 came out at exactly 0.0100.

Raised to 20000 sims for that test alone (2.1s total for the case — three
seeds, two `probability` calls each — up from 0.4s). The sd falls to 0.0034,
the three seeds sit at 0.0033 / 0.0010 / 0.0005, and over 30 seeds the
truncated figure lands above exhaustive 15 times and below it 15 times. The
tolerance was **not** loosened; the measurement was made precise enough for it
to mean something. 250 is genuinely non-biasing — that was never in doubt, only
untested.

---

## 17. `--adds` / `--cuts` split on commas, which are in card names — FIXED

`mtg_utils/cli.py`, the `write` branch:

```python
[x for x in a.adds.split(",") if x],
[x for x in a.cuts.split(",") if x])
```

Comma is the only separator, and roughly every legendary creature has a comma
in its name. `--adds "Ghalta, Primal Hunger"` becomes two names, `Ghalta` and
`Primal Hunger`, neither of which is a card. `write_deck` then asserts and
fails with

```
AssertionError: MISSING ADD: Ghalta
```

which reads as a typo in a name that was spelled correctly. The assertion is
checking the deck it wrote; it has no way to know the name it was handed had
already been cut in half.

`--swap` already solved this: `parse_swaps` accepts `;` and lets it WIN when
present. `--adds` and `--cuts` never got the escape hatch, so the same name
could be swapped in but not added.

**Cost on `--adds`:** no wrong number — the assertion catches it — but the
flag is unusable for a large class of card names and the error points at the
wrong thing.

**Cost on `--cuts` is worse, and is the half worth remembering.** A cut
asserts *absence*. Split in half, neither `Ghalta` nor `Primal Hunger` is in
the deck, so the assertion passes — **vacuously**. The check reports success
without having checked anything, which is the silent-all-clear shape this repo
has been bitten by before (a non-canonical EDHREC slug answering 200 with no
cardlists, and the audit reporting nothing missing).

**Fixed** by giving all three flags one separator rule, `split_names`, built on
the `_sep` helper `parse_swaps` now shares. `;` wins when present, `,`
otherwise, so every existing invocation splits on the same character it did.

**It is not purely a separator change, though**, and the distinction matters to
anyone tracking down why an invocation that used to report success now fails.
The old split kept whitespace: `--cuts "Sol Ring, Island"` produced `Sol Ring`
and `' Island'`, and the leading space made the second match nothing in the
read-back — **another vacuous pass**. `split_names` strips each segment, so
that cut is now genuinely checked and can legitimately start failing. That is
the direction you want and it is part of the same fix, but it does mean
"nothing observable changed for existing callers" would be too strong a claim
for any spec written with spaces after its commas.

Costs one `--help` snapshot: `--adds` and `--cuts` had no help text at all, and
an escape hatch nobody can find is not an escape hatch. Both entries now state
the rule, and `--cuts` states the vacuous pass.

### Not fixed: a lone comma'd name still needs a trailing `;`

`;` only wins when it is PRESENT, so one name with a comma and no semicolon
anywhere still splits. The idiom is a trailing separator —
`--adds="Ghalta, Primal Hunger;"` — with the empty segment dropped. Both forms
are pinned as cases, because the trailing `;` looks like a typo and is exactly
the sort of thing a later tidy-up removes.

**Deliberately not fixed, because every fix considered was worse:**

- *Detect the mis-split and refuse*, the way `parse_swaps` does. `parse_swaps`
  can only do that because a pair has an `->` in it to validate against; a bare
  name has no structure to check.
- *Validate the names against the deck.* Decidable for `--adds`, whose names
  must be present — and not for `--cuts`, whose names must be absent, which is
  the case that needs it. A guard that covers the safe half of an asymmetric
  pair is worse than none: it makes the unguarded half look guarded.
- *Make the flags repeatable* (`action="append"`). Does not actually help —
  each occurrence still has to be split on something, so a comma inside one
  occurrence splits exactly as before.
- *Stop splitting on commas.* Breaks every existing invocation, and the CLI
  surface only grows.

The residual is a lone name, in a flag that is checking a deck the user just
wrote by hand, with the idiom in `--help` one line away. Priced and kept.

**The next thing to try is not a fifth fix — it is making it loud.** All four
options above try to *decide* whether a name was halved, which is the part
that cannot be done. An advisory does not have to decide. When a spec contains
a comma and no `;`, print one line to stderr naming the segments it produced —

```
--cuts: split on comma into 2 names: Urborg / Tomb of Yawgmoth
```

— and split exactly as before. It moves no number, no snapshot and no split;
it just refuses to be silent at the moment the mistake is made. The cost is
that it cannot tell a halved name from a legitimate two-name spec, so it fires
on `--cuts "Sol Ring,Island"` too. That noise is arguably worth paying on
`--cuts` specifically, whose failure mode is a *pass*, and not on `--adds`,
which already fails loudly with `MISSING ADD`.

Not done here because it is a behaviour addition rather than a repair to
either reported finding, and it belongs in its own commit where the asymmetry
between the two flags can be argued on its own terms. Recorded because it is
the first option considered that does not require solving the undecidable
part, and it would otherwise be rediscovered.

---

## 18. The Monte Carlo core is optimised, and where it stops — RESOLVED, measured

`mana` on the four fixture decks went 27.7s to 6.2s, and `variants` 83.0s to
15.4s, with every snapshot byte-identical. Measured end to end against the
merged tree -- not against the branch point, which had moved under this work
four times over; earlier drafts of this entry quoted the older figures and
read as freshly measured when they were not, and re-measuring after each merge
is the only thing that stops that. `castability.py` is now the one file here
written for speed rather than plainly, so the reasoning belongs somewhere
greppable rather than in four commit messages.

**What was actually slow.** Not the maths. The models asked the same question
over and over: twenty Mountains are twenty separate dicts with identical
contents, so a hand the solver had already answered arrived looking new. Four
calls in five are now answered from a memo, and most draws never enumerate a
combination at all. The rest was building things to take them apart again —
`playsim` assembled a list of source profiles per turn per trial so
`playsim_report` could immediately reduce it to a total and a key.

**Where it stops, and why that is not a to-do.** Well over half of what remains
is the random draws themselves: 6.4 to 7.3 million `getrandbits` calls per deck,
fixed by the definition of the measurement. Drawing one bit differently moves
every figure, so that half is not available. Measured, per deck, on warm caches
-- "the draws alone" counts each call's bit width during an untimed pass and
then times a bare loop making exactly those calls:

| deck | `analyse_mana` | the draws alone | calls |
|---|---|---|---|
| mono | 0.80s | 0.49s (62%) | 6,612,822 |
| multi | 0.98s | 0.55s (57%) | 7,336,742 |
| colourless | 0.74s | 0.47s (64%) | 6,405,848 |
| partner | 1.00s | 0.54s (54%) | 7,331,243 |

The share rose from the 45–52% an earlier draft of this entry recorded, and it
rose because the rest got faster, not because the draws got slower: the call
counts are unchanged, since changing one would change a number. Worth knowing
before optimising: a Python-level no-op call costs *more* than `getrandbits`
does (0.66s against 0.62s over 7.3M calls), so anything that replaces one C
call with one Python call is already behind before it does any work.

The obvious next idea is batching: `getrandbits(32*N)` really does return
exactly what N calls to `getrandbits(32)` return, little-endian, so a block
could be drawn once and sliced. It was tried. **It is 2.7x slower** — the
Python-level buffer bookkeeping costs more than the C call it removes. The
per-call version is not there for want of looking.

**What it cost.** Memory. The caches are per-process and did not exist before;
a four-deck run peaks at 75 MB against about 11 MB baseline. They are bounded
by a watermark set above what one deck's full measurement needs, so a single
run keeps every hit and `calibrate` cannot grow without limit. Dropping a cache
costs time and never correctness, which is what makes the crude bound safe.

**What it cost once, in the wrong direction.** A cache keyed on less than the
answer depends on. `_DRAW_MEMO` keyed a draw on the SORTED codes of what was
drawn, but `playable_set` drops the source drawn FIRST out of a combination in
which everything is tapped -- so two draws of the same sources in a different
order can differ, and whichever arrived first answered for both. On a deck
holding a tapped source of two mana (a karoo; Azorius Chancery, Golgari Rot
Farm) it moved the reported figure by eleven points, on every seed tried.

Caught in review, not by the suite. The four fixtures did not show it, and the
reason is worth writing down because it is not the reassuring one: `multi`
carries Golgari Rot Farm and `colourless` carries Worn Powerstone, so the
ingredient WAS present in the committed decks -- they were simply never dealt
a hand where it changed a printed figure. "The snapshots did not move" was
true and proved nothing.

The fix is to key on the drawn codes in draw ORDER, which is what the loop
reads, and it is faster than the sorted key rather than slower -- building the
tuple no longer sorts it. `tests/test_solver_equivalence.py` now keeps the
pre-rewrite `probability` verbatim beside the new one and compares the whole
draw layer over decks built to reach the case, which is the check that was
missing: `castable` order-independence was pinned, and the truncation that
happens BEFORE it is not order-independent at all.

**What it risks.** `random.shuffle` and `random.sample` are reimplemented to
skip work the models throw away. That couples this repo to two stdlib
algorithms — but it *already was* coupled, because the snapshots are Monte
Carlo means drawn through them; a CPython that changed either would have moved
the numbers before, silently. Now `tests/test_rng_equivalence.py` asserts the
equivalence directly, so that change fails by name instead. Reverting the
reimplementation is a legitimate call if it ever drifts; reverting it and
keeping the snapshots is not.

**Not attempted, deliberately.** Nothing that trades an approximation for
speed: no reduced `--sims` default, no early termination once a proportion
looks settled, no sharing draws between candidate lines. Each would be a real
speedup and each changes a reported number, which makes it a modelling change
that must arrive as its own commit with the snapshot diff shown — the rule at
the top of CLAUDE.md, not an exception to it.

**And one that would NOT change a number, declined anyway.** `variants` sweeps
six configurations against the same seed and the same 99-card library, and a
Fisher-Yates shuffle permutes positions without looking at what it is moving —
so all six draw the identical permutation, six times over. Sharing it is sound,
and five sixths of the dealing a `variants` run does is repeated work — the
largest single win left anywhere in the repo.

An earlier draft priced it at 1.07s of a 2.1–2.8s run. That figure is retired
rather than updated, because the tree it was taken on is two merges gone and
the attempts to re-take it were not sound: pricing the deals by replaying the
generator calls in a bare loop, or by a calibrated per-call rate, both put the
deals at 90–210% of the run they live inside, which is arithmetic saying the
method is wrong, not that the deals are free. The honest bound is the structure
above plus the run itself, which is 2.4–6.0s per fixture deck. Anyone taking
this on gets the real number for free, by measuring before and after.

It was declined on legibility. Taking it means `_playsim_core` gains a third
mode — consume a deal you were handed, rather than draw one — in the hottest
loop here, and it means inverting `report_variants` so all six configurations
are in flight at once against one deal stream, with six interleaved
accumulators where there is now an obvious `for each config: measure it`. The
current loop is correct at a glance. That one would not be, and this is a
repository whose entire thesis is that a plausible-looking number is more
dangerous than an obvious error. One second on a command whose own docstring
says "Slow; opt-in" does not buy that.

For whoever revisits it, the analysis is done and the shape is known. Deal the
positions rather than the cards: `_playsim_core` builds
`list(range(nL + nA + nR)) + [-1] * rest` and shuffles it, but shuffling
`range(deck_size)` gives the same permutation and lets each configuration
classify a position itself (`p < nL` a land, `p < nL + nA` an accelerant,
`p < nL + nA + nR` a ritual, else a spell), which drops the `-1` sentinel and
makes the shared path fall out rather than fork. The
aggregation has to stay `100.0 * hits / trials` per replicate and then
`mean_spread` over replicates in index order, or the floats move in the last
place. And it needs one new test the repo does not have: that a shuffle's
permutation is independent of what is being shuffled. That is the invariant the
whole idea rests on, it is true of Fisher-Yates, and it is five lines to pin —
but unpinned it is exactly the assumption that stays true until someone makes
the shuffle look at the deck.

---

## 19. `variants` crashed on a commander past turn seven — FIXED

```
python3 mana_model.py variants deck.txt --cache=scry.json
KeyError: 'cmdr'
```

`report_variants` asks `replicate_playsim` for one line, the commander on
curve, then reads it back by label. `playsim_report` drops any line whose turn
is past the seven it simulates, so for a commander of mana value eight or more
the label was never in the result and the read raised a bare `KeyError` with
nothing in it naming the commander, its mana value, or the limit. Reproduced on
Emrakul, the Aeons Torn, and verified to predate the optimisation pass — it
raised identically at 4db2aa5.

The same two lines hid a second one. `commander_lines` skips a name Scryfall
cannot resolve, so `_cl[0]` on an empty list raised `IndexError: list index out
of range`. The CLI prints SCRYFALL NOT FOUND and carries on, so a typo'd
commander line reaches this code routinely.

**Cost:** the command was unusable on those decks, and failed in a way that
read as a bug in the simulator rather than as a statement about the deck.

**Fixed by raising, not by simulating further.** Both columns of the sweep are
read at the commander's own turn, so once that turn is off the end there is no
row left to print — this is not a table with one column missing. Quoting the
turn-seven figure under a "commander on curve" heading would have been a
different question wearing this one's label, which is the exact failure the
rule at the top of CLAUDE.md exists to prevent. So both guards fail loudly and
by name, matching the "cannot add lands to a deck with no untapped
colour-producing land to copy" guard a dozen lines above them, and they fire
before the sweep spends 240,000 trials finding out.

`mana` was checked before the message was written to say so: it handles such a
deck without raising, dropping the commander line and reporting the rest, so
"`mana` still covers turns one to seven for this deck" is advice that holds.
The test asserts that too, because a message that recommends something broken
is worse than one that recommends nothing.

The limit itself is now `PLAYSIM_TURNS` in `castability.py`, the default for
both `playsim_report` and `replicate_playsim`. It was a bare 7 in three places
— the simulation, the cap `report_variants` applies, and this guard — and a
guard holding a different number from the thing it guards is how the crash
comes back.

**Not changed:** what `variants` does for a commander inside turn seven, and
what any other command does for one outside it. `mana`, `skeleton` and
`compare_swap` were all checked against a mana-value-15 commander and all
complete.

---

## 20. `floor` prices a cut against a display floor, not against zero — RESOLVED, documented

`floor` reports the cards that ARE in the list, ascending by inclusion, so a
cut has a number beside it. Most of them do not have one. On the partner
fixture, 28 of 60 non-land cards are not ranked on the EDHREC page at all, and
for those the report prints a **bound** rather than a figure.

That is the honest answer and it is also a weak one, so the limitation is
recorded here rather than left to be rediscovered as a bug.

**What the bound is.** EDHREC prints the top of each cardlist and stops, and
each list stops somewhere different. Read off one live commander page,
2026-08-16 — the page `tests/fixtures/floor.rec.json` was captured from:

| list | rows | lowest shown |
|---|---|---|
| Creatures | 50 | 5.80% |
| Instants | 42 | 5.06% |
| Mana Artifacts | 16 | 5.44% |
| Sorceries | 15 | 5.36% |
| Enchantments | 11 | 5.34% |
| Utility Artifacts | 6 | 5.55% |
| Battles | 1 | 5.44% |
| Utility Lands | 11 | 6.02% |

So absence tells you `<=5.3%` for an enchantment and only `<=5.8%` for a
creature, where the number is the point the 50-row cap fell rather than the
point the population stopped. `display_floors` reads the depths off the page
fetched in that run; they are never pinned in code, because they move.

**Why the bound is not tightened.** The obvious tightening — assume EDHREC
files a card on the one list its primary type names, and quote that list's
floor — was rejected. Nothing in the payload says which face or which type a
page filed a modal or multi-type card by: `Sorcery // Land` is filed under
Lands, an Artifact Creature under Creatures. `display_floor_bound` therefore
takes the WEAKEST bound over every list the card could be on. A tighter number
here would be a claim about EDHREC's filing rules wearing the costume of a
claim about the card.

**Why four of the page's cardlists bound nothing at all.** `New Cards`,
`High Synergy Cards` and `Game Changers` filter on recency, synergy skew and
the bracket list rather than on inclusion, so absence from one says nothing
whatever; on the captured page they stop at 8.21%, 73.87% and 74.47%. Read as
display floors they would report Sol Ring, at 96.6% inclusion, as "below
74.5%" and rank it the safest cut in the deck. `Top Cards` is ranked on
inclusion and its 68.67% is a real bound, excluded because it would win the
weakest-bound rule against every type list and swamp them. Only a
cardlist whose header names a card type is allowed to bound anything, and
`test_a_selection_cardlist_never_bounds_anything` asserts the four real depths
so the case cannot pass by testing a list that happens to be absent.

**`--cedh` does not have this problem, and must not inherit its rule.**
edhtop16 returns whole decklists, so a card it does not rank was in zero of
them: a measured 0% with a real denominator, printed as `0/6`. The two
conventions are opposite and each is wrong applied to the other source —
bounding an edhtop16 absence understates the one source that can actually say
"nobody plays this", and zeroing an EDHREC absence invents a figure for every
card the page merely stopped short of.

**Not fixed, deliberately: there is no deeper endpoint.** EDHREC's per-type
pages go further down than the commander page does, at one request per type
per commander. That is 8–13 extra fetches on a rate-limited endpoint to
sharpen numbers that are all, already, below any bar anyone sets. The bound as
printed says "this card is in the bottom few percent"; the sharper number
would say which bottom few percent, which no cut decision turns on.

**Lands are excluded rather than bounded.** EDHREC land data reflects a budget
population, so inclusion is the wrong instrument; `roster` already walks every
cycle slot best-first and `ceiling` annotates its land rows against that walk.
Excluded and counted, never silently absent — a shorter table reads as less
work to do.

**Rows above the bar are printed rather than counted away.** This is the
incident the command was written after: four cuts proposed in one session with
the inclusion figure pulled for none of them, two of which were at 75.5% and
64.5% under that commander and went back in a day later. A row above the bar
is not a finding, but if it is omitted its absence from the table is
indistinguishable from "safe to cut" — which is the belief that caused the
incident. Every non-land card in the list therefore appears in exactly one of
three blocks, and `floor_audit` asserts that identity rather than printing
arithmetic for a reader to check.
