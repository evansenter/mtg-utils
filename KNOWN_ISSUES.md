# Known issues — found during the repo migration, deliberately not fixed

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

## 1. The play simulation never spends the mana it uses to deploy accelerants

`playsim`, the four-pass deployment loop.

Each pass recomputes total available mana from `online()` and deploys any
accelerant whose `cost` is at or below that total. Nothing is deducted. Two
untapped lands can therefore deploy Sol Ring *and* a two-drop rock in the same
turn, and the Sol Ring's own mana immediately counts toward the next pass, so a
third can follow.

**Cost:** inflates every play-simulation figure, and inflates it most in exactly
the decks that lean on accelerants. This is the largest single item on this
list.

**Fixing it** means tracking mana spent per turn, which lowers on-curve numbers
across the board — including any number already written into a primer.

---

## 2. One-shot rituals are counted as permanent, repeatable mana sources

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

**Fixing it** requires deciding what a ritual *should* count as — arguably
something, since it does produce mana once — which makes it a modelling
decision, not just a bug fix.

---

## 3. Restricted mana is modelled for accelerants but not for lands

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

---

## 4. The `verify` printer hard-codes "1 commander"

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
to prevent. This is the cheapest fix on the list and the one I would do first.

---

## 5. Deck size is hard-coded to 99

`analysis.py` twice, `report.py` once:

```python
probability(lands, accels, 99, ...)
playsim_report(lands, accels, 99, ...)
```

A partner or background deck has 98 non-commander cards, not 99. The simulation
draws from a library one card larger than the real one.

**Cost:** small and consistently optimistic — it slightly dilutes the library
with one extra non-source. It biases every partner deck's numbers in the same
direction.

---

## 6. Omni-typing is applied to every source, not only to lands

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

---

## 7. Tapped-land counts are per entry; land counts are per quantity

`verify` appends a land's **name** to `truly_tapped` / `conditional_tapped` once
per entry, while incrementing `lands` by the entry's **quantity**. The `mana`
header then prints both in one sentence:

```
=== MANA BASE (37 front-face lands + 3 MDFC land-backs, 3 truly tapped) ===
```

37 counts copies; 3 counts distinct cards. In Commander singleton they coincide
for everything except basics, which is why it has never bitten — but the two
numbers in that sentence are in different units.

---

## 8. `scry_fetch` never caches a `not_found`

A name Scryfall cannot resolve is returned to the caller and is not written to
the cache, so every later run asks about it again.

**Cost:** none to correctness, and it is the right behaviour for a typo about to
be corrected. It is the wrong behaviour for a name that will never resolve, and
in `calibrate` — which walks every deck — it means a repeated round trip per
run. Pinned by a test as current behaviour, not endorsed.

---

## 9. `report_variants` has a latent `TypeError`

```python
basic = next((p for p in base_lands if not p["tapped"] and p["colours"]), None)
...
lands = base_lands + [dict(basic) for _ in range(dl)]
```

If no untapped colour-producing land exists, `basic` is `None` and `dict(None)`
raises `TypeError: 'NoneType' object is not iterable`.

**Checked, and it does not fire on any of the three fixtures**, including the
colourless one: Wastes produce `{C}`, and `frozenset({'C'})` is truthy. It needs
a deck whose entire manabase is tapped or produces nothing, which is not a
realistic list. Latent, not live.

---

## 10. `enters_tapped(face, card)` never uses `card`

Every call site passes one. Harmless, and worth a moment's thought before
removing in case the second argument was meant to carry the whole-card context
that a land-back check would need.

---

## 11. The sources model assumes any drawn source is deployable

`probability` picks `turn` sources out of everything seen and asks whether they
can pay the cost. It does not model the one-land-per-turn rule, nor the mana
spent casting an accelerant.

So four lands plus a Sol Ring "have" five mana on turn five, without ever paying
the one to cast the Sol Ring.

This is the documented idealisation of the sources model rather than a defect —
the model exists to answer "can I make these pips", and the play simulation
exists precisely because this one does not answer "do I have N mana on turn N".
Recorded so the optimism is explicit and nobody quotes a sources-model figure as
an on-curve number.

---

## 12. `moxfield` prints its header twice

`cli.py` prints `# {name} (fetched ...)` to stdout, then builds a second,
slightly different header (`# {name} (deck {id}, fetched ...)`) into the text it
emits or writes. Printing to stdout shows both; writing to `--out` still prints
the first to the terminal.

**Cost:** cosmetic. The file written by `--out` contains exactly one header, so
`read_decklist` is unaffected.
