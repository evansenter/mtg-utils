# Known issues — found during the repo migration

Entries marked FIXED have been dealt with since; RESOLVED means the behaviour
was examined and deliberately kept, with the reasoning recorded; CHANGED means
a reported number was moved on purpose, with what moved written down beside it.
**Nothing here is currently outstanding.**

The file's job does not end when the list empties. It exists because a finding
that lives only in scrollback gets rediscovered — so a decision NOT to do
something belongs here too, not in a commit message nobody greps. #13 and #14
are that shape, and #15 is the other one: a limitation that was priced, kept,
and later revisited deliberately, with the earlier entry left standing.

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
