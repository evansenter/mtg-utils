"""`combos`: the names sent to Commander Spellbook, and the names read back.

Spellbook resolves a double-faced card by its FULL `A // B` name. Sent the
front face alone it does not fail -- it drops the card, derives the deck's
colour identity from what is left, and answers a question about a different
deck. Measured against the live endpoint on 2026-08-30 with one commander and
one spell:

    "Terra, Magical Adept"                  identity UR,    included 0
    "Terra, Magical Adept // Esper Terra"   identity WUBRG, included 1

so a deck whose commander is a DFC had every combo running through that
commander demoted from `included` to "one card away, needs <the commander>".
The output is not merely wrong there, it is reassuring: a list being assessed
for a bracket reads "in-deck combos: 0" and stops.

Three sources, three conventions, and no two agree -- EDHREC answers in front
faces, edhtop16 and Spellbook in full names. See cards.front_name.
"""
import json
from collections import Counter

import pytest

from conftest import patch_everywhere

# A DFC commander and a DFC in the 99, as Scryfall spells them. The cache is
# keyed on both forms by scry_fetch, which is what a decklist holding either
# spelling relies on.
TERRA = "Terra, Magical Adept // Esper Terra"
ORIGINS = "Esper Origins // Summon: Esper Maduin"


def _scry(*full_names):
    cache = {}
    for n in full_names:
        cache[n.lower()] = {"name": n}
        cache[n.split(" // ")[0].lower()] = {"name": n}
    return cache


# --- the name sent ------------------------------------------------------
@pytest.mark.parametrize("written", ["Terra, Magical Adept", TERRA],
                         ids=["combos/front face is sent in full",
                              "combos/full name is sent unchanged"])
def test_a_dfc_commander_is_sent_under_its_full_name(mm, monkeypatch, written):
    """However the decklist spells it, the API sees the full name."""
    import mtg_utils.sources.spellbook as sb
    sent = {}

    class _R:
        stdout = json.dumps({"results": {"included": [], "almostIncluded": []}})

    def fake_run(argv, **kw):
        sent["payload"] = json.loads(argv[argv.index("-d") + 1])
        return _R()

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    sb.spellbook(written, Counter({"Sol Ring": 1}), _scry(TERRA))
    assert sent["payload"]["commanders"] == [{"card": TERRA}]


def test_a_dfc_in_the_99_is_sent_under_its_full_name(mm, monkeypatch):
    """combos/a DFC in the main deck is sent in full

    Not only the commander: a two-card combo whose other piece is a DFC in the
    99 is demoted the same way, and the deck the API scores is missing that
    card entirely.
    """
    import mtg_utils.sources.spellbook as sb
    sent = {}

    class _R:
        stdout = json.dumps({"results": {"included": [], "almostIncluded": []}})

    def fake_run(argv, **kw):
        sent["payload"] = json.loads(argv[argv.index("-d") + 1])
        return _R()

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    sb.spellbook("Terra, Magical Adept",
                 Counter({"Esper Origins": 1, "Sol Ring": 1}),
                 _scry(TERRA, ORIGINS))
    assert {c["card"] for c in sent["payload"]["main"]} == {ORIGINS, "Sol Ring"}


def test_a_name_the_cache_never_saw_is_sent_as_written(mm, monkeypatch):
    """combos/an unknown name is passed through

    The cache is the only thing that can expand a front face, and a caller
    without one -- or a card too new for it -- must still get what it got
    before rather than an exception.
    """
    import mtg_utils.sources.spellbook as sb
    assert sb.spellbook_name("Some Unfetched Card", {}) == "Some Unfetched Card"
    assert sb.spellbook_name("Some Unfetched Card", None) == "Some Unfetched Card"


# --- what that changes in the report ------------------------------------
def _oracle(deck_full_names):
    """A fake find-my-combos that behaves the way the live endpoint measured.

    The combo needs Terra. Spellbook only knows Terra if it was sent the full
    name, so a payload carrying the front face gets the combo back as "one
    card away" -- which is the bug, reproduced, rather than asserted about.
    """
    combo = {"uses": [{"card": {"name": TERRA}},
                      {"card": {"name": "The Apprentice's Folly"}}],
             "produces": [{"feature": {"name": "Infinite mana"}}],
             "requires": []}

    def fake_spellbook(cmdr, entries, scry=None):
        from mtg_utils.sources.spellbook import spellbook_name
        from mtg_utils.decklist import as_cmdrs
        sent = {spellbook_name(n, scry)
                for n in list(as_cmdrs(cmdr)) + list(entries)}
        if TERRA in sent:
            return {"included": [combo], "almostIncluded": []}
        return {"included": [], "almostIncluded": [combo]}

    return fake_spellbook


def test_a_combo_through_a_dfc_commander_is_reported_as_in_deck(
        mm, monkeypatch, capsys):
    """combos/a commander combo is IN the deck, not one card away

    The regression the FR asks for, and it is written against a fake whose
    rule is the endpoint's measured behaviour -- a fixture whose commander is
    NOT a combo piece would pass either way.
    """
    import mtg_utils.report as report
    entries = Counter({"The Apprentice's Folly": 1})
    patch_everywhere(monkeypatch, "spellbook",
                     _oracle({TERRA, "The Apprentice's Folly"}))
    report.report_combos("Terra, Magical Adept", entries, _scry(TERRA))
    out = capsys.readouterr().out
    assert "in-deck combos: 1" in out
    assert "one card away: 0" in out


@pytest.mark.parametrize("written", ["Esper Origins", ORIGINS],
                         ids=["combos/front face in the list groups",
                              "combos/full name in the list groups"])
def test_the_grouping_reads_full_names_against_the_decklist(
        mm, monkeypatch, capsys, written):
    """The mirror of the send: Spellbook answers in full names, a decklist may
    hold EITHER, and compared verbatim the piece the reader is already holding
    lands in `miss` -- rendering as "one card away" from a card in their list.

    Both spellings, because the two sides are normalised separately and each
    one alone is enough to make the other case pass.
    """
    import mtg_utils.report as report

    def fake_spellbook(cmdr, entries, scry=None):
        return {"included": [],
                "almostIncluded": [
                    {"uses": [{"card": {"name": ORIGINS}},
                              {"card": {"name": "Missing One"}}],
                     "requires": []}]}

    patch_everywhere(monkeypatch, "spellbook", fake_spellbook)
    report.report_combos("Cmdr", Counter({written: 1}))
    out = capsys.readouterr().out
    assert f"    {ORIGINS}: 1   two-card: Missing One" in out


# --- the format filter --------------------------------------------------
# Spellbook reports legality per VARIANT, which is a better answer than
# checking each piece: a combo is legal only if every card in it is, and the
# payload has already done that join. Its keys are spelled differently from
# Scryfall's -- `standardBrawl` against `standardbrawl` -- so formats.py
# carries both.
LEGAL_ANYWHERE = {"commander": True, "brawl": True, "standardBrawl": True}
COMMANDER_ONLY = {"commander": True, "brawl": False, "standardBrawl": False}


def _variant(name, legalities=None):
    v = {"uses": [{"card": {"name": "Cmdr"}}, {"card": {"name": name}}],
         "produces": [{"feature": {"name": "Infinite mana"}}], "requires": []}
    if legalities is not None:
        v["legalities"] = legalities
    return v


@pytest.mark.parametrize("legalities,fmt,wanted", [
    (COMMANDER_ONLY, "standardbrawl", True),
    (COMMANDER_ONLY, "commander", False),
    (LEGAL_ANYWHERE, "standardbrawl", False),
    (None, "standardbrawl", False),
], ids=["combos/a Commander-only combo is illegal in Brawl",
        "combos/the same combo is legal in Commander",
        "combos/a legal combo is kept",
        "combos/a payload with no legalities keeps its row"])
def test_variant_says_illegal(mm, legalities, fmt, wanted):
    assert mm.variant_says_illegal(_variant("X", legalities), fmt) is wanted


def test_illegal_suggestions_are_dropped_and_counted(mm, monkeypatch, capsys):
    """combos/an unregisterable suggestion is not offered

    The payload carries no format, so `almostIncluded` comes back
    Commander-legal whatever deck was sent. Low harm -- every row here needs
    hand-verification anyway -- but a wasted read, and a silently shortened
    list is indistinguishable from a short one.
    """
    import mtg_utils.report as report

    def fake_spellbook(cmdr, entries, scry=None):
        return {"included": [],
                "almostIncluded": [_variant("Legal Piece", LEGAL_ANYWHERE),
                                   _variant("Banned Piece", COMMANDER_ONLY)]}

    patch_everywhere(monkeypatch, "spellbook", fake_spellbook)
    report.report_combos("Cmdr", Counter({"Cmdr": 1}), None, "standardbrawl")
    out = capsys.readouterr().out
    assert "1 combo not legal in Standard Brawl, dropped." in out
    assert "one card away: 1" in out
    assert "Banned Piece" not in out


def test_commander_drops_nothing(mm, monkeypatch, capsys):
    """combos/the default format filters nothing out"""
    import mtg_utils.report as report

    def fake_spellbook(cmdr, entries, scry=None):
        return {"included": [],
                "almostIncluded": [_variant("Banned Piece", COMMANDER_ONLY)]}

    patch_everywhere(monkeypatch, "spellbook", fake_spellbook)
    report.report_combos("Cmdr", Counter({"Cmdr": 1}))
    out = capsys.readouterr().out
    assert "dropped." not in out
    assert "one card away: 1" in out
