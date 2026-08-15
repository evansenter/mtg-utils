# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The rule that governs everything else

**No change may move a reported number unless moving it is the point of the change.**

Almost every function here encodes a bug that once shipped a wrong figure into a
document someone acted on. A refactor that shifts a probability by half a point
is worse than no refactor, because the number still looks plausible. The golden
suite exists to make that impossible by accident:
`tests/test_golden.py` runs `verify`, `mana`, `roster`, `skeleton` and `--help`
over **four** frozen decks and asserts stdout is byte-identical to committed snapshots in
`tests/fixtures/expected/`.

- **Refactoring?** The snapshots must not move. If they do, you changed
  behaviour — find out why before touching the snapshot.
- **Deliberately changing output?** Regenerate with
  `pytest tests/test_golden.py --regen-golden`, review the diff, and commit the
  moved snapshots *in the same commit* as the code, saying what moved and why.
  That flag rewrites the definition of correct output from the current code, so
  it will just as happily bless an accidental change — only reach for it when
  moving the number is the point.
- **Claiming a change is behaviour-preserving?** Run it and diff. Do not reason
  about the code.

`KNOWN_ISSUES.md` is the durable record of things that look wrong. Every entry
in it is now marked **FIXED** or **RESOLVED** — resolved meaning the behaviour
was examined and deliberately kept, with the reasoning written down. Nothing in
it is currently outstanding.

Its job did not end when the list emptied. It exists because "a finding that
lives only in scrollback is a finding that gets rediscovered", so when you
decide NOT to do something, record it there rather than in a commit message
nobody greps. #13 (conditional accelerants) and #14 (no mulligan model) are both
that shape: deliberate limitations, priced and kept.

Do not quietly "fix" a resolved entry while doing something else — several are
resolved *because* changing them would move numbers. Changing one on purpose is
welcome, as its own commit, with the snapshot diff shown.

## Commands

```bash
pytest                                   # whole suite, ~40s, fully offline
python3 mana_model.py selftest           # same thing via the CLI contract
PYTHONHASHSEED=0 pytest -q --durations=5 # exactly what CI runs
```

Selecting a single case. Test names are deliberately the labels of the bugs they
prevent, and many contain spaces, which `-k` cannot parse as a substring:

```bash
pytest "tests/test_castability.py::test_filter_makes_no_black"          # node id
pytest "tests/test_roster.py::test_pair_cycle_has_its_members[roster/ABUR dual has 10 members]"
pytest -k "filter and makes and no and black"   # -k needs and-joined tokens
grep -rn "filter makes no black" tests/         # find which file a label is in
```

Roughly half the labels are parametrize ids (visible in `--collect-only`); the
rest live in the test's docstring because the label is not a legal Python
identifier. `grep` finds either.

Running the tool:

```bash
python3 mana_model.py audit deck.txt --cache scry.json
python3 mana_model.py mana tests/fixtures/multi.txt --cache tests/fixtures/multi.scry.json
python3 mana_model.py variants deck.txt --swap="Clifftop Retreat->Rugged Prairie"
python3 mana_model.py skeleton deck.txt --cache scry.json
python3 mana_model.py ceiling deck.txt --bar 65      # network; --cedh for edhtop16
python3 -m mtg_utils --help              # equivalent entry point
```

`ceiling` and `calibrate` are the network subcommands. Everything else runs off
the Scryfall cache.

`argparse` reads a leading-minus value as a flag, so sweeps need `=`:
`--lands=-2,0,2`, never `--lands -2,0,2`.

## Architecture

### Two models that answer different questions

Getting these confused is the most consequential mistake available here.

- **Sources model** (`probability` in `castability.py`) — "can I make these
  pips". Draws `7 + turn - 1` cards, requires a land and `turn` sources, solves
  pip payment including filter-land pairing. Ignores sequencing and the cost of
  deploying an accelerant, so it **understates** whenever a spell's mana value
  is near the turn number.
- **Play simulation** (`playsim`) — "do I have N mana on turn N". Draws, plays a
  land a turn, deploys accelerants, reads off available mana. Reports on the
  play and on the draw separately, because you are on the draw three turns in
  four at a four-player table.

Any figure quoted anywhere must say which model produced it.
`at_least_in_draw()` (renamed from `hypergeometric()`, which is not aliased and
raises) counts cards in the draw and is **not** a castability figure — it is
used for the opening-hand land count and nothing else.

Mana sources are lands **plus** accelerants of mana value ≤ 3 plus MDFC land
backs — lands-only understates castability badly. Restricted mana ("spend this
mana only to cast Dwarf spells") is flagged by `build_accel_profiles` and
excluded from generic totals.

### Compute is separate from printing, and it is load-bearing

`verify`, `analyse_mana`, `worst_lines`, `commander_lines`, `parse_moxfield`,
`diff_multiset` and `collapse_temps` return data. The `report_*` wrappers in
`report.py` only format it. This is what lets tests assert on numbers instead of
scraping stdout — preserve it. New logic goes in `analysis.py` or below, never
inside a printer.

**Fetching is not computing.** Printers are the I/O boundary and several of
them call out: `report_roster`, `report_own`, `report_contention`, `report_combos`,
`report_diff`, `report_ceiling` and `report_calibrate` all fetch. That is by
design and is not the thing the split protects — what must stay below the
printers is *measurement*, so a test can assert on a number without scraping
stdout.

`report_calibrate` is the one printer that also **measures** — its per-deck loop
is analysis living in a printer. It is network-only, so no offline test could
verify a split of it; left whole deliberately.

`report_ceiling` is the near miss to watch. It fetches twice (the ranking page,
then Scryfall for the above-bar cards, which are by definition not in the
decklist) but hands every judgement to `ceiling_audit`. Keep it that way: the
front-face matching is exactly the logic that needs an offline test.

### Module map

`cards.py` → `profiles.py` → `castability.py` → `analysis.py` → `report.py` →
`cli.py`, with `decklist.py`, `roster.py` and `sources/` alongside. Constants
live with their consumer rather than in a shared constants module.

`mana_model.py` at the root is the entry point and a compatibility shim:
`mtg_utils` re-exports everything the original single file exposed, so
`import mana_model` still works as a library import.

**The CLI surface only grows.** Existing subcommands, flags and argument names
do not change or disappear — anything already in use keeps working. Adding a
subcommand or a flag is fine and has happened (`ceiling`; `--reps`, `--seed`,
`--swap`, `--rec-cache`, `--cedh`, `--bar`), and costs one `--help` snapshot.
Renaming or removing one is not.

The same rule covers the library surface, with one worked example: when
`hypergeometric` was renamed to `at_least_in_draw` it was deliberately **not**
aliased, because the old name was the problem. Instead `mtg_utils.__getattr__`
raises a message naming the replacement, and `mana_model.py` carries a
delegating `__getattr__` so that message is reachable through the shim at all —
`from mtg_utils import *` copies names at import time, so the package's own
`__getattr__` is never consulted for a `mana_model.<name>` lookup.

The `--help` banner is `mtg_utils.__doc__`, passed to argparse explicitly. Do
not switch it to `__doc__` inside `cli.py`; that silently replaces the whole
banner with a different module's docstring, and `--help` is snapshot-tested.

## Fixtures

`tests/fixtures/` holds four decks — mono-colour, multicolour, colourless and a
partner pair — plus frozen Scryfall caches, a ManaBox export, and the `ceiling.*`
captures for EDHREC and edhtop16. **They are frozen inputs. Never edit one; add
a new one.**

The partner pair is not decoration either: it is the only shape with two
commanders and a 98-card library, which is where "1 commander" and a hard-coded
99 both used to be wrong.

The colourless deck is not optional. A mono deck exercises no filter lands, a
multicolour deck exercises no colourless-utility path, and **neither has a `{C}`
pip to get wrong**. A `{C}` parsing bug once survived a two-shape regression
pass, and it did not produce a wrong number — it produced an *empty* table,
which read as "no colour constraints". Hence
`test_colourless_worst_lines_is_not_empty`: two empty tables compare equal.

The caches pin `prices.usd` and `edhrec_rank`, which `roster`, `own` and
`ceiling` print and which drift daily. Regenerating a cache changes output with
no code change.

`ceiling.rec.json` keeps its `Creatures` cardlist at exactly 50 entries on
purpose — that length *is* the display-cap signal, so trimming the list retires
`test_a_full_cardlist_is_marked_capped` without failing it.
`ceiling.scry.json` is a deliberate projection: each card keeps only the fields
the ceiling path reads, because the full records ran to 1.2 MB to price a dozen
rows. Values in both are verbatim.

Three traps the harness already handles, which any new test must too.
`scry_fetch` rewrites its cache file on every run (copy to tmp first), and
`load_collection(path=COLLECTION)` binds its default at import, so patch the
function, not the constant.

The third is newer and cost a green-but-meaningless test: **a cache key that
does not match what the code asks for sends the suite to the network, and
everything still passes.** `edhtop16_fetch` keys on `edhtop16/{first}/{name}`,
a fixture built at `first=30` missed at the default `first=100`, and the case
ran against 100 live entries instead of the 6 committed ones. `_no_network` in
`tests/test_ceiling.py` patches `subprocess.run` to raise; use it in any test
that touches a fetching path.

## Rules for tests

- **Mutation-check every new case.** Revert the code it guards, confirm the case
  fails, restore. Clear `__pycache__` between steps, or export
  `PYTHONDONTWRITEBYTECODE=1`: a mutation the same byte length as the original
  (`+= q` for `+= 1`) restored within the same second leaves a stale `.pyc`
  that Python considers valid, and the run silently uses the wrong bytecode.
  That reads as "the test didn't catch it" and can get a perfectly good test
  rewritten. It happened here. A test that passes the moment it is written has not been shown
  to test anything. Two cases in this repo's history were decorative: one used a
  basic land as a colour-identity canary (basics have empty colour identity, so
  it could never fail), and one used a substring check that still matched with
  the code it guarded removed.
- **Fixture strings are verbatim Scryfall text.** A case for the MDFC land backs
  once used invented wording no printed card uses; it passed while the real
  cards were misclassified.
- **Cases that look redundant usually are not.**
  `collection/sums quantities across printings` and `collection/no double count`
  assert the same value for two different reasons, and both comments say which.
- The suite is fully offline and must stay that way. Anything needing Scryfall
  or Moxfield needs a fixture.

## Constraints that will re-break if "modernised"

- **Standard library only** for the package. `pytest` is the sole dev
  dependency, imported lazily inside the `selftest` subcommand.
- **Moxfield must be called with `curl` and a full Chrome User-Agent.** `urllib`
  returns 403 regardless of headers — client fingerprinting, established by
  controlled A/B testing. Behind a TLS-terminating proxy even `curl` gets a
  Cloudflare 403, since the fingerprint the edge sees is the proxy's.
- **Scryfall rate limits differ by endpoint.** `/cards/collection` tolerates
  0.1–0.2s; `/cards/search` 429s at that rate and needs ~0.5s plus backoff.
  `rulings_uri` and `prints_search_uri` are search calls and inherit the
  stricter limit. Guard every search loop and assert the result count.
- **The EDHREC slug drops apostrophes; it does not hyphenate them.** A general
  punctuation-to-hyphen "cleanup" of `edhrec_slug` breaks it, and breaks it
  confusingly: `y-shtola-nights-blessed` returns **403**, not 404, so the
  failure reads as a block rather than as a bad slug.
- **A non-canonical EDHREC slug answers 200, not 404.** A partner pair in the
  wrong order returns `{"redirect": "/commanders/..."}` with no cardlists.
  Parsed as a page that ranks zero cards, the audit reports nothing missing —
  a silent all-clear for a deck nobody checked. The slug sorts, `edhrec_fetch`
  follows the redirect, and `report_ceiling` refuses to print an all-clear from
  a page that ranked nothing. Keep all three.
- **The two ranking sources disagree about card names, in opposite
  directions.** EDHREC returns front faces only (`Agadeem's Awakening`);
  edhtop16 returns full names (`Sink into Stupor // Soporific Springs`).
  Everything is reduced to the front face on both sides. A comparison written
  for one source is wrong against the other, and the symptom is an in-deck card
  reported as missing.
- **edhtop16 commander names go through `json.dumps` as GraphQL variables.**
  Hand-built backslash escaping breaks on apostrophes, which most popular cEDH
  commanders have. A partner pair is ONE commander there, `" / "`-joined and
  sorted; querying one half returns a commander with zero entries, which reads
  as "no cEDH data" rather than "wrong name".
- **Do not reformat wholesale.** A repo-wide formatter run buries the real diff.
  If you want formatting, it is its own commit and you say so.
- **Comments that explain why a line exists usually name a bug it prevents.**
  Delete one only after verifying the failure it describes can no longer occur.
  When moving code, check the comment block moved with it — blocks separated by
  a blank line are easy to strand.

## Environment

`COLLECTION` in `sources/collection.py` is an absolute path to a ManaBox export
that does not exist in CI or in most sandboxes. Anything touching ownership
(`own`, `contention`, `roster`) needs it patched — see `load_fixture_collection`
in `tests/conftest.py`.
