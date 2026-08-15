"""report_* formatting.

The golden suite covers verify, mana and roster because those run offline.
The other printers need Moxfield, Spellbook or the collection file, so nothing
exercised their formatting at all -- and formatting is where a number gets
attached to the wrong label, or a column silently stops lining up.

Dependencies are patched in mtg_utils.report, where the names resolve.
"""
import json
import os
import re
from collections import Counter

import pytest

from conftest import FIXTURES, load_fixture_collection


@pytest.fixture
def report(mm):
    import mtg_utils.report as r
    return r


@pytest.fixture
def owned(monkeypatch, report):
    monkeypatch.setattr(report, "load_collection", load_fixture_collection)


def _card(name, tl, usd=None, rank=None, **kw):
    d = {"name": name, "type_line": tl, "cmc": 1, "oracle_text": "",
         "color_identity": [], "legalities": {"commander": "legal"},
         "prices": {"usd": usd}, "edhrec_rank": rank}
    d.update(kw)
    return d


# ============================================================ report_own
OWN_SCRY = {
    "sol ring": _card("Sol Ring", "Artifact", "1.50", 1),          # owned x4
    "mountain": _card("Mountain", "Basic Land — Mountain", "0.10"),  # never a buy
    "tundra": _card("Tundra", "Land", "399.99", 900),               # owned x1
    "birds of paradise": _card("Birds of Paradise", "Creature — Bird", "8.25", 120),
    "skullclamp": _card("Skullclamp", "Artifact — Equipment", "3.10", 44),
    "rhystic study": _card("Rhystic Study", "Enchantment", "40.00", 2),
    "brainstorm": _card("Brainstorm", "Instant", "0.25", 300),
    "reserved thing": _card("Reserved Thing", "Artifact", None, 5000),
    "cmdr": _card("Cmdr", "Legendary Creature — Human", "1.00", 10),
}


def _own_output(report, capsys, entries):
    report.report_own("Cmdr", Counter(entries), OWN_SCRY)
    return capsys.readouterr().out


def test_own_excludes_basic_lands(report, owned, capsys):
    """own/basics are never a buy line

    ManaBox does not track basics, so a naive ownership diff reports
    "Mountain -- not owned" and it looks like a real result.
    """
    out = _own_output(report, capsys, {"Mountain": 10, "Brainstorm": 1})
    assert "Mountain" not in out
    assert "Brainstorm" in out


def test_own_excludes_what_is_owned(report, owned, capsys):
    """own/owned cards do not appear

    Sol Ring is in the fixture collection four times over; Tundra once.
    """
    out = _own_output(report, capsys, {"Sol Ring": 1, "Tundra": 1, "Brainstorm": 1})
    assert "Sol Ring" not in out
    assert "Tundra" not in out


@pytest.mark.parametrize("name,bucket", [
    ("Birds of Paradise", "Creatures"),
    ("Skullclamp", "Equipment"),
    ("Rhystic Study", "Enchantments"),
    ("Brainstorm", "Instants / Sorceries"),
], ids=["own/creature bucket", "own/equipment before artifact",
        "own/enchantment bucket", "own/instant bucket"])
def test_own_buckets_by_type(report, owned, capsys, name, bucket):
    """Equipment is checked before Artifact, so Skullclamp is Equipment and
    not an Artifact -- the branch order is the classification."""
    out = _own_output(report, capsys, {name: 1})
    section = out.split(bucket)[1]
    assert name in section.split("\n\n")[0]


def test_own_row_format(report, owned, capsys):
    """own/(BUY) row layout"""
    out = _own_output(report, capsys, {"Brainstorm": 1})
    row = [l for l in out.splitlines() if "Brainstorm" in l][0]
    assert re.fullmatch(r"  \(BUY\) Brainstorm {25}\$   0\.25  EDHREC #300", row), repr(row)


def test_own_total_excludes_nulls(report, owned, capsys):
    """own/total excludes null prices

    A Reserved List card has no usd price. Adding it as zero would understate
    the total silently; the line says nulls are excluded and the next line
    says how to re-query them.
    """
    out = _own_output(report, capsys, {"Brainstorm": 1, "Rhystic Study": 1,
                                       "Reserved Thing": 1})
    # 0.25 + 40.00 + 1.00: the unowned COMMANDER is a buy line too, since
    # report_own walks as_cmdrs(cmdr) + entries. Reserved Thing has a null
    # price and contributes nothing.
    assert "total listed USD (nulls excluded): $41.25" in out
    assert "Reserved List / promo" in out
    assert "$    n/a" in out


# ============================================================ report_diff
def _fake_moxfield(name, cmdrs, main):
    def _f(deck_id):
        return name, cmdrs, Counter(main)
    return _f


def test_diff_identical_returns_true(report, monkeypatch, capsys):
    """diff/IDENTICAL exits truthy

    `diff` gates a step -- it exits 0 when the multiset matches and 2 when it
    does not -- so the return value is a contract, not a convenience.
    """
    monkeypatch.setattr(report, "moxfield_deck",
                        _fake_moxfield("D", ["Cmdr"], {"Sol Ring": 1, "Island": 9}))
    got = report.report_diff("Cmdr", Counter({"Sol Ring": 1, "Island": 9}), "abc")
    out = capsys.readouterr().out
    assert got is True
    assert "IDENTICAL -- the live list already matches this file." in out
    assert "local 11 cards | live 11 cards" in out


def test_diff_reports_both_directions(report, monkeypatch, capsys):
    """diff/+ is local, - is live"""
    monkeypatch.setattr(report, "moxfield_deck",
                        _fake_moxfield("D", ["Cmdr"], {"Island": 8, "Swamp": 1}))
    got = report.report_diff("Cmdr", Counter({"Island": 9}), "abc")
    out = capsys.readouterr().out
    assert got is False
    assert "  -1 Swamp      (in live, not in file)" in out
    assert "  +1 Island      (in file, not in live)" in out


def test_diff_flags_a_commander_change(report, monkeypatch, capsys):
    """diff/commander differs is called out first"""
    monkeypatch.setattr(report, "moxfield_deck",
                        _fake_moxfield("D", ["Other"], {"Island": 9}))
    report.report_diff("Cmdr", Counter({"Island": 9}), "abc")
    out = capsys.readouterr().out
    assert "COMMANDER DIFFERS: local ['Cmdr'] | live ['Other']" in out


# ============================================================ report_contention
def test_contention_collapses_a_temp(report, monkeypatch, capsys):
    """contention/a Temp is not a second physical deck

    Counting a Temp separately made every shared card look contended and
    turned an output into a phantom purchase line.
    """
    decks = {"m1": ("Muldrotha [Bracket 3]", [], {"Sol Ring": 1}),
             "m2": ("Muldrotha [Bracket 3 Temp]", [], {"Sol Ring": 1}),
             "t1": ("Teval [B4]", [], {"Sol Ring": 1})}
    monkeypatch.setattr(report, "moxfield_deck", lambda i: decks[i])
    monkeypatch.setattr(report, "load_collection", lambda *a, **k: {"sol ring": 2})
    monkeypatch.setattr(report.time, "sleep", lambda *_: None)
    report.report_contention("Cmdr", Counter({"Sol Ring": 1}), ["m1", "m2", "t1"])
    out = capsys.readouterr().out
    assert "Muldrotha [Bracket 3 Temp]" in out.split("===")[0]     # named as collapsed

    # Match the WHOLE line. A substring check here is decorative: sorted()
    # puts "Muldrotha [Bracket 3 Temp]" BEFORE "Muldrotha [Bracket 3]",
    # because " " sorts before "]", so the uncollapsed output still ends
    # "...Muldrotha [Bracket 3], Teval [B4]" and an `in` check passes with
    # the collapse removed. Found by mutation-checking this test, not by
    # reading it.
    line = [l for l in out.splitlines() if "owned 2" in l]
    assert line == ["  Sol Ring                       owned 2 | also in: "
                    "Muldrotha [Bracket 3], Teval [B4]"], line
    assert "Contention is an OUTPUT. It never decides a slot." in out


def test_contention_says_none_when_supply_is_fine(report, monkeypatch, capsys):
    """contention/none when every owned card has enough copies"""
    monkeypatch.setattr(report, "moxfield_deck",
                        lambda i: ("Other", [], {"Sol Ring": 1}))
    monkeypatch.setattr(report, "load_collection", lambda *a, **k: {"sol ring": 9})
    monkeypatch.setattr(report.time, "sleep", lambda *_: None)
    report.report_contention("Cmdr", Counter({"Sol Ring": 1}), ["x"])
    out = capsys.readouterr().out
    assert "none — every owned card here has enough copies" in out


# ============================================================ report_combos
def test_combos_groups_by_the_piece_in_the_deck(report, monkeypatch, capsys):
    """combos/grouped by the piece already in the deck

    A flat list of 41 entries hides the shape; grouping collapses it to
    "Bloom Tender and Faeburrow Elder, eight untappers each".
    """
    def fake_spellbook(cmdr, entries):
        return {
            "included": [{"uses": [{"card": {"name": "A"}}, {"card": {"name": "B"}}],
                          "produces": [{"feature": {"name": "Infinite mana"}}]}],
            "almostIncluded": [
                {"uses": [{"card": {"name": "A"}}, {"card": {"name": "Missing One"}}],
                 "requires": []},
                {"uses": [{"card": {"name": "A"}}, {"card": {"name": "Missing Two"}}],
                 "requires": []},
            ]}
    monkeypatch.setattr(report, "spellbook", fake_spellbook)
    report.report_combos("Cmdr", Counter({"A": 1, "B": 1}))
    out = capsys.readouterr().out
    assert "in-deck combos: 1" in out
    assert "   * A + B -> Infinite mana" in out
    assert "one card away: 2" in out
    assert "    A: 2   two-card: Missing One, Missing Two" in out
    assert "Spellbook is a CANDIDATE GENERATOR." in out


# ============================================================ report_mana columns
def test_mana_table_columns(mm, capsys):
    """mana/column layout

    The play-simulation table is read by eye against its baseline column; if
    the widths drift the diagnosis gets read off the wrong pair of numbers.
    """
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "mono.txt"))
    with open(os.path.join(FIXTURES, "mono.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    mm.report_mana(cmdr, entries, scry, sims=200, trials=400)
    out = capsys.readouterr().out

    assert ("  line                                             "
            "on play     on draw        baseline(any N on TN)") in out
    # "  {label:44s} {a:6.1f}±{sa:3.1f}% {b:6.1f}±{sb:3.1f}%"
    # "   {g1:6.1f}±{s1:3.1f}% / {g2:.1f}±{s2:.1f}%"
    #
    # Each figure is now a value±spread pair. The pairs are matched in the
    # regex rather than skipped over, so a column that loses its bar in a
    # later format change fails here as a layout error instead of quietly
    # printing a bare number in a table where every neighbour is labelled.
    row_re = re.compile(r"^  (?P<label>.{44}) (?P<play>.{6})±(?P<ps>.{3})%"
                        r" (?P<draw>.{6})±(?P<ds>.{3})%"
                        r"   (?P<base>.{6})±(?P<bs>.{3})% / \d+\.\d±\d+\.\d%$")
    rows = [m for m in (row_re.match(l) for l in out.splitlines()) if m]
    assert rows, out
    for m in rows:
        assert m.group("label").rstrip() == m.group("label").strip()   # left aligned
        assert m.group("play").strip().replace(".", "").isdigit()
        assert m.group("ps").strip().replace(".", "").isdigit()
        assert m.group("base").startswith(" ")                          # right aligned
    assert "--- play simulation, 400 trials over 3 reps, seed 17 ---" in out
    assert "Diagnosis: a line CLOSE to its baseline is a QUANTITY problem" in out


# ============================================================ verify header
@pytest.mark.parametrize("deck", ["mono", "multi", "colourless", "partner"])
def test_verify_header_arithmetic_closes(candidate, deck, tmp_path):
    """verify/printed arithmetic closes

    The header is copied straight into a primer, where "24 lands plus 75
    non-land" in a 100-card deck is a sentence nobody re-adds. It has to sum.

    Shape-general on purpose: the snapshot for the partner deck pins the exact
    string, but this catches the same class of error on any deck, including one
    added later. verify() has always returned the right numbers -- it was only
    the format string that said "1 commander" regardless.
    """
    from conftest import deck_args, run_cli
    out = run_cli(candidate, deck_args(deck, "verify"), str(tmp_path))
    line = [l for l in out.splitlines() if " cards = " in l]
    assert len(line) == 1, out
    m = re.fullmatch(r"\s*(\d+) cards = (\d+) commanders? \+ (\d+) non-land"
                     r" \+ (\d+) lands\s+\((\d+) MDFC land-backs\)", line[0])
    assert m, repr(line[0])
    total, ncmdr, nonland, lands, _mdfc = (int(g) for g in m.groups())
    assert ncmdr + nonland + lands == total, line[0]


def test_verify_header_pluralises(candidate, tmp_path):
    """verify/singular for one, plural for two"""
    from conftest import deck_args, run_cli
    one = run_cli(candidate, deck_args("mono", "verify"), str(tmp_path))
    two = run_cli(candidate, deck_args("partner", "verify"), str(tmp_path))
    assert "= 1 commander +" in one
    assert "= 2 commanders +" in two


# ============================================================ guards
def test_variants_refuses_to_clone_a_land_it_does_not_have(report, capsys):
    """variants/no land to clone fails by name

    `--lands=2` clones an untapped colour-producing land. With none in the
    deck the old code reached dict(None) and raised TypeError several frames
    away, which reads as a crash rather than as a statement about the deck.
    Guards in this project fail loudly and by name.
    """
    from collections import Counter
    scry = {"cmdr": {"name": "Cmdr", "type_line": "Legendary Creature",
                     "color_identity": [], "cmc": 1, "oracle_text": "",
                     "mana_cost": "{1}", "legalities": {"commander": "legal"}},
            "tapped land": {"name": "Tapped Land", "type_line": "Land",
                            "color_identity": [], "cmc": 0,
                            "oracle_text": "Tapped Land enters tapped.",
                            "produced_mana": [], "legalities": {"commander": "legal"}}}
    with pytest.raises(SystemExit) as e:
        report.report_variants("Cmdr", Counter({"Tapped Land": 30}), scry,
                               [2], [0], 10)
    assert "cannot add lands" in str(e.value)
    capsys.readouterr()


def _big_commander_scry(cmc):
    return {"emrakul, the aeons torn":
            {"name": "Emrakul, the Aeons Torn", "cmc": cmc,
             "type_line": "Legendary Creature — Eldrazi", "mana_cost": "{%d}" % cmc,
             "oracle_text": "", "color_identity": [],
             "legalities": {"commander": "legal"}},
            "island": {"name": "Island", "type_line": "Basic Land — Island",
                       "cmc": 0, "oracle_text": "", "produced_mana": ["U"],
                       "color_identity": [], "legalities": {"commander": "legal"}}}


def test_variants_refuses_a_commander_past_the_last_turn_simulated(report, capsys):
    """variants/a commander off the end of the table fails by name

    Both columns of the sweep are read at the commander's own turn.
    `playsim_report` drops any line whose turn is past the seven it simulates,
    so for a commander of mana value eight or more the label was simply not in
    the result and reading it back raised a bare `KeyError: 'cmdr'` with
    nothing in it naming Emrakul, the mana value, or the limit.

    Raising is the fix rather than simulating further: quoting the turn-seven
    figure under a "commander on curve" heading would be a different question
    wearing this one's label, which is the failure this whole repo is built
    against. `mana` still reports turns one to seven for such a deck, and is
    checked here so the message's advice is true rather than merely soothing.
    """
    from collections import Counter
    scry = _big_commander_scry(15)
    with pytest.raises(SystemExit) as e:
        report.report_variants("Emrakul, the Aeons Torn", Counter({"Island": 99}),
                               scry, [0], [0], 60)
    msg = str(e.value)
    assert "Emrakul, the Aeons Torn" in msg
    assert "turn 15" in msg          # its own turn, not a generic complaint
    assert "turn 7" in msg           # and the limit it fell off
    capsys.readouterr()
    # The advice has to hold: `mana` really does still run on this deck.
    report.report_mana("Emrakul, the Aeons Torn", Counter({"Island": 99}),
                       scry, 60, 60)
    assert "MANA BASE" in capsys.readouterr().out


def test_variants_accepts_a_commander_on_the_last_turn_simulated(report, capsys):
    """variants/turn seven exactly is still measured

    The other side of the guard, and the one an off-by-one would break
    silently: a seven-drop is the last commander the table can report, and a
    `>=` here would retire it with a message instead of measuring it.
    """
    from collections import Counter
    with pytest.raises(SystemExit):
        report.report_variants("Emrakul, the Aeons Torn",
                               Counter({"Island": 99}), _big_commander_scry(8),
                               [0], [0], 60)
    capsys.readouterr()
    report.report_variants("Emrakul, the Aeons Torn", Counter({"Island": 99}),
                           _big_commander_scry(7), [0], [0], 60)
    out = capsys.readouterr().out
    assert "VARIANTS SWEEP" in out
    assert len([l for l in out.splitlines() if "lands," in l]) == 1


def test_variants_refuses_a_commander_the_cache_cannot_resolve(report, capsys):
    """variants/an unresolved commander fails by name

    `commander_lines` skips a name Scryfall does not know, so the list came
    back empty and `_cl[0]` raised IndexError. The CLI prints SCRYFALL NOT
    FOUND and carries on, so a typo'd commander line reaches here routinely --
    and "list index out of range" says nothing about which name was wrong.
    """
    from collections import Counter
    scry = {"island": {"name": "Island", "type_line": "Basic Land — Island",
                       "cmc": 0, "oracle_text": "", "produced_mana": ["U"],
                       "color_identity": [], "legalities": {"commander": "legal"}}}
    with pytest.raises(SystemExit) as e:
        report.report_variants("Nonesuch, the Typo", Counter({"Island": 99}),
                               scry, [0], [0], 60)
    assert "Nonesuch, the Typo" in str(e.value)
    capsys.readouterr()


def test_variants_still_works_when_there_is_a_land_to_clone(report, capsys, mm):
    """variants/the guard does not block the normal case"""
    import json
    import os

    from conftest import FIXTURES
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "mono.txt"))
    with open(os.path.join(FIXTURES, "mono.scry.json"), encoding="utf-8") as f:
        scry = json.load(f)
    report.report_variants(cmdr, entries, scry, [0, 1], [0], 20)
    out = capsys.readouterr().out
    assert "VARIANTS SWEEP" in out
    assert len([l for l in out.splitlines() if "lands," in l]) == 2
