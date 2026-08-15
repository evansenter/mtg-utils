# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The rule that governs everything else

**No change may move a reported number unless moving it is the point of the change.**

Almost every function here encodes a bug that once shipped a wrong figure into a
document someone acted on. A refactor that shifts a probability by half a point
is worse than no refactor, because the number still looks plausible. The golden
suite exists to make that impossible by accident:
`tests/test_golden.py` runs `verify`, `mana`, `roster` and `--help` over three
frozen decks and asserts stdout is byte-identical to committed snapshots in
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

`KNOWN_ISSUES.md` lists twelve things that look wrong and are deliberately left
alone, because fixing them moves numbers. Do not quietly "fix" one while doing
something else. Fixing one on purpose is welcome — as its own commit, with the
snapshot diff shown.

## Commands

```bash
pytest                                   # whole suite, ~20s, fully offline
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
python3 -m mtg_utils --help              # equivalent entry point
```

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

Any figure quoted anywhere must say which model produced it. `hypergeometric()`
exists as a fast sanity check and must never be reported.

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

`report_calibrate` is the one printer that also computes. It is network-only, so
no offline test could verify a split of it; left whole deliberately.

### Module map

`cards.py` → `profiles.py` → `castability.py` → `analysis.py` → `report.py` →
`cli.py`, with `decklist.py`, `roster.py` and `sources/` alongside. Constants
live with their consumer rather than in a shared constants module.

`mana_model.py` at the root is the entry point and a compatibility shim:
`mtg_utils` re-exports everything the original single file exposed, so
`import mana_model` still works as a library import. **The CLI surface is
fixed** — same subcommands, flags and argument names.

The `--help` banner is `mtg_utils.__doc__`, passed to argparse explicitly. Do
not switch it to `__doc__` inside `cli.py`; that silently replaces the whole
banner with a different module's docstring, and `--help` is snapshot-tested.

## Fixtures

`tests/fixtures/` holds three decks — mono-colour, multicolour, colourless —
plus frozen Scryfall caches and a ManaBox export. **They are frozen inputs.
Never edit one; add a new one.**

The colourless deck is not optional. A mono deck exercises no filter lands, a
multicolour deck exercises no colourless-utility path, and **neither has a `{C}`
pip to get wrong**. A `{C}` parsing bug once survived a two-shape regression
pass, and it did not produce a wrong number — it produced an *empty* table,
which read as "no colour constraints". Hence
`test_colourless_worst_lines_is_not_empty`: two empty tables compare equal.

The caches pin `prices.usd` and `edhrec_rank`, which `roster` and `own` print
and which drift daily. Regenerating a cache changes output with no code change.

Two traps the harness already handles, which any new test must too:
`scry_fetch` rewrites its cache file on every run (copy to tmp first), and
`load_collection(path=COLLECTION)` binds its default at import, so patch the
function, not the constant.

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
