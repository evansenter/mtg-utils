"""The collection-ceiling audit: what is above the inclusion bar and missing.

Run by hand outside the package this analysis found nine missing cards on one
deck -- a bigger improvement than every manabase finding on it combined -- and
it also shipped a wrong answer, by keying the deck on the full DFC name while
EDHREC returns front faces only. It reported a card as missing that was in the
list. `cards.py` exists to centralise exactly that, which is why the audit
belongs in here rather than in a scratch script.

The two ranking sources disagree about names in opposite directions, verified
against both live endpoints:

    EDHREC     "Agadeem's Awakening"                     -- front face only
    edhtop16   "Sink into Stupor // Soporific Springs"   -- full name

so a comparison that handles one is wrong against the other. Everything is
reduced to the front face.

The other guarded behaviours are all "do not turn an absence of data into a
confident zero": a capped cardlist, a redirect page, and a tournament sample
too small to quote.
"""
import json
import os
import shutil

import pytest

from conftest import FIXTURES, load_fixture_collection

REC = os.path.join(FIXTURES, "ceiling.rec.json")
TOP16 = os.path.join(FIXTURES, "ceiling.top16.json")
SCRY = os.path.join(FIXTURES, "ceiling.scry.json")
PAIR = ["Tymna the Weaver", "Thrasios, Triton Hero"]


def _rec_page():
    with open(REC, encoding="utf-8") as f:
        return list(json.load(f).values())[0]


def _top16_data():
    with open(TOP16, encoding="utf-8") as f:
        return list(json.load(f).values())[0]


def _scry():
    with open(SCRY, encoding="utf-8") as f:
        return json.load(f)


# --- the slug ---------------------------------------------------------
@pytest.mark.parametrize("name,want", [
    ("Tymna the Weaver", "tymna-the-weaver"),
    ("Y'shtola, Night's Blessed", "yshtola-nights-blessed"),
    ("Kroxa, Titan of Death's Hunger", "kroxa-titan-of-deaths-hunger"),
    ("Agadeem's Awakening // Agadeem, the Undercrypt", "agadeems-awakening"),
], ids=["slug/plain", "slug/apostrophes are DROPPED not hyphenated",
        "slug/possessive inside a word", "slug/DFC uses the front face"])
def test_edhrec_slug(mm, name, want):
    """The apostrophe rule is the expensive one.

    `y-shtola-nights-blessed` -- what a naive punctuation-to-hyphen rule
    builds -- returns 403, not 404. The failure therefore reads as "EDHREC is
    blocking us" rather than as "that slug is wrong", which is a much longer
    afternoon. Both forms were checked against the live endpoint.
    """
    assert mm.edhrec_slug(name) == want


def test_partner_slug_is_alphabetical(mm):
    """A pair slug in the wrong order is NOT a 404.

    It answers 200 with {"redirect": ...} and no cardlists. Parsed as a page
    that ranks zero cards, and an audit over zero cards reports nothing
    missing -- a silent all-clear for a deck nobody actually checked.
    """
    assert mm.edhrec_slug(PAIR) == "thrasios-triton-hero-tymna-the-weaver"


# --- parsing the commander page ---------------------------------------
def test_inclusion_is_computed_not_read(mm):
    """There is no `inclusion` field on a cardview.

    Reading one gives None, and None formatted into a percent column reads as
    0% -- a card everybody plays would be reported as a card nobody plays.
    """
    rows, _capped = mm.parse_commander_page(_rec_page())
    assert rows
    for r in rows:
        assert r["inclusion"] == pytest.approx(
            100.0 * r["num_decks"] / r["potential_decks"])
    assert rows == sorted(rows, key=lambda r: -r["inclusion"])


def test_a_full_cardlist_is_marked_capped(mm):
    """EDHREC truncates each list at 50, so absence from a capped list is not
    evidence a card is unplayed. The fixture keeps 'Creatures' at its real
    length of exactly 50 for this reason -- trimming it would destroy the
    signal being tested."""
    rows, capped = mm.parse_commander_page(_rec_page())
    assert "Creatures" in capped
    page = _rec_page()
    lengths = {cl["header"]: len(cl["cardviews"])
               for cl in page["container"]["json_dict"]["cardlists"]}
    assert lengths["Creatures"] == mm.PAGE_CAP
    for header, n in lengths.items():
        assert (header in capped) == (n >= mm.PAGE_CAP), (header, n)


def test_a_card_in_two_cardlists_is_counted_once(mm):
    """'Agadeem's Awakening' appears under both Lands and Utility Lands on a
    real page. Counted twice it makes one absent card look like two, and the
    buy total double-counts its price."""
    rows, _ = mm.parse_commander_page(_rec_page())
    names = [r["name"].lower() for r in rows]
    assert len(names) == len(set(names)), "duplicate card across cardlists"


def test_a_cardview_without_a_ratio_is_skipped_not_zeroed(mm):
    """No ratio means no percentage. Emitting 0.0 is how a missing field
    becomes a confident wrong number in a printed table."""
    page = {"container": {"json_dict": {"cardlists": [{
        "header": "Top Cards",
        "cardviews": [{"name": "Sol Ring", "num_decks": 9, "potential_decks": 10},
                      {"name": "Mana Crypt"},
                      {"name": "Chrome Mox", "num_decks": 5, "potential_decks": 0}]}]}}}
    rows, _ = mm.parse_commander_page(page)
    assert [r["name"] for r in rows] == ["Sol Ring"]


# --- the front-face rule, in both directions --------------------------
def test_a_dfc_in_the_deck_is_not_reported_missing(mm):
    """THE bug this command was written to stop.

    EDHREC says "Commit". The decklist says "Commit // Memory". Compared as
    written they are different strings, and the audit reports a card the deck
    is holding as one it needs to buy.

    Both names are verbatim: `Commit // Memory` is the entry in this repo's
    own multi fixture, and `Commit` is its front face as EDHREC returns it.
    """
    entries = {"Commit // Memory": 1, "Sol Ring": 1}
    rows = [{"name": "Commit", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"}]
    a = mm.ceiling_audit("Cmdr", entries, rows, [], {}, {}, threshold=50.0)
    assert a["missing"] == [], "an in-deck DFC was reported missing"


def test_a_ranked_row_with_a_full_dfc_name_still_matches_the_deck(mm):
    """The mirror of the case above, for the source side.

    edhtop16 ranks "Sink into Stupor // Soporific Springs". parse_edhtop16
    front-faces it, but ceiling_audit must not depend on having been handed
    already-normalised rows -- a future third source with a third convention
    would otherwise report every DFC in the deck as missing. Both sides are
    reduced, so either convention works on either side.
    """
    entries = {"Sink into Stupor // Soporific Springs": 1}
    rows = [{"name": "Sink into Stupor // Soporific Springs", "num_decks": 9,
             "potential_decks": 10, "inclusion": 90.0, "cardlist": "x"}]
    a = mm.ceiling_audit("Cmdr", entries, rows, [], {}, {}, threshold=50.0)
    assert a["missing"] == []


def test_edhtop16_full_names_are_reduced_to_the_front_face(mm):
    """edhtop16 has the OPPOSITE convention from EDHREC -- it returns
    "Sink into Stupor // Soporific Springs" where EDHREC returns
    "Agadeem's Awakening". Keying both to the front face is what lets one
    comparison work against either."""
    rows, n = mm.parse_edhtop16(_top16_data())
    assert n >= mm.MIN_ENTRIES
    assert rows
    assert not any(" // " in r["name"] for r in rows), \
        [r["name"] for r in rows if " // " in r["name"]]


def test_edhtop16_counts_entries_not_copies(mm):
    """A card is in a decklist or it is not; a second copy is not a second
    deck. Counting copies would push a card past 100% inclusion."""
    rows, n = mm.parse_edhtop16(_top16_data())
    for r in rows:
        assert r["num_decks"] <= n
        assert r["inclusion"] <= 100.0


def test_two_copies_in_one_list_are_one_deck(mm):
    """Built by hand because the committed fixture cannot show this: cEDH
    lists at this level run no basic lands, so no entry in it holds two cards
    of the same name and counting copies is indistinguishable from counting
    entries. A deck with two Islands makes the difference visible -- counted
    by copy, Island lands at 200%.
    """
    data = {"entries": {"edges": [
        {"node": {"maindeck": [{"name": "Island"}, {"name": "Island"},
                               {"name": "Sol Ring"}]}},
        {"node": {"maindeck": [{"name": "Sol Ring"}]}}]}}
    rows, n = mm.parse_edhtop16(data)
    by = {r["name"]: r for r in rows}
    assert n == 2
    assert by["Island"]["num_decks"] == 1
    assert by["Island"]["inclusion"] == pytest.approx(50.0)
    assert by["Sol Ring"]["inclusion"] == pytest.approx(100.0)


def test_a_partner_pair_is_one_commander_on_edhtop16(mm):
    """Querying one half alone resolves to a commander with ZERO entries,
    which reads as "no cEDH data for Thrasios" rather than as "wrong name".
    The pair is joined with ' / ' and sorted."""
    assert mm.edhtop16_commander_name(PAIR) == \
        "Thrasios, Triton Hero / Tymna the Weaver"
    assert mm.edhtop16_commander_name("Kinnan, Bonder Prodigy") == \
        "Kinnan, Bonder Prodigy"


# --- the audit --------------------------------------------------------
def test_the_commander_is_never_reported_missing(mm):
    rows = [{"name": "Tymna the Weaver", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"}]
    a = mm.ceiling_audit(PAIR, {"Sol Ring": 1}, rows, [], {}, {})
    assert a["missing"] == []


def test_the_audit_attaches_ownership_and_price(mm):
    """The question is not just "what is missing" but "do I already own it" --
    an owned card is a deckbuilding decision and an unowned one is a purchase.
    """
    rows = [{"name": "Thassa's Oracle", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "Top Cards"},
            {"name": "Force of Will", "num_decks": 8, "potential_decks": 10,
             "inclusion": 80.0, "cardlist": "Top Cards"}]
    owned = {"thassa's oracle": 2}
    scry = {"thassa's oracle": {"prices": {"usd": "20.86"}, "type_line": "Creature"},
            "force of will": {"prices": {"usd": "59.20"}, "type_line": "Instant"}}
    a = mm.ceiling_audit("Cmdr", {"Sol Ring": 1}, rows, [], owned, scry)
    by = {m["name"]: m for m in a["missing"]}
    assert by["Thassa's Oracle"]["owned"] == 2
    assert by["Force of Will"]["price"] == pytest.approx(59.20)
    assert a["owned_count"] == 1
    # An owned card is not a purchase, so it stays out of the buy total.
    assert a["buy_total"] == pytest.approx(59.20)


def test_the_bar_excludes_what_is_below_it(mm):
    rows = [{"name": "A", "num_decks": 9, "potential_decks": 10,
             "inclusion": 90.0, "cardlist": "x"},
            {"name": "B", "num_decks": 3, "potential_decks": 10,
             "inclusion": 30.0, "cardlist": "x"}]
    a = mm.ceiling_audit("Cmdr", {}, rows, [], {}, {}, threshold=50.0)
    assert [m["name"] for m in a["missing"]] == ["A"]


# --- the report -------------------------------------------------------
def _no_network(monkeypatch):
    """Make any outbound call a test failure, not a slow pass.

    Written after a case here silently went to the live endpoint: the
    edhtop16 cache key carries the `first` value, the fixture had been built
    at first=30, and the lookup at the default first=100 missed and fetched.
    Every other assertion in that test still passed, against 100 live entries
    instead of the 6 committed ones -- so the case was green, non-
    deterministic, and not testing the fixture at all.
    """
    import subprocess

    def boom(*a, **kw):
        raise AssertionError(
            "the offline suite tried to reach the network -- a fixture cache "
            "key probably does not match what the code asks for")

    # Every source module calls subprocess.run through the shared module
    # object, so one patch covers curl wherever it is invoked from.
    monkeypatch.setattr(subprocess, "run", boom)


def _run_ceiling(mm, monkeypatch, tmp_path, **kw):
    import mtg_utils.report as report
    monkeypatch.setattr(report, "load_collection", load_fixture_collection)
    _no_network(monkeypatch)
    # scry_fetch rewrites its cache on every run, so the committed fixture is
    # copied first -- the same trap the golden harness already handles.
    scry_copy = os.path.join(str(tmp_path), "ceiling.scry.json")
    shutil.copyfile(SCRY, scry_copy)
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "partner.txt"))
    return report.report_ceiling(cmdr, entries, _scry(), scry_copy, **kw)


def test_a_capped_list_is_reported_as_below_cutoff_never_as_zero(mm, monkeypatch,
                                                                tmp_path, capsys):
    """The acceptance criterion. A card absent from a truncated list is of
    UNKNOWN inclusion; printing it as 0% would be a number the tool could not
    have retrieved."""
    _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "display cutoff" in out
    assert "Creatures" in out
    assert "UNKNOWN inclusion, not 0%" in out
    assert "0.0%" not in out


def test_the_report_lists_missing_cards_with_their_ratio(mm, monkeypatch,
                                                        tmp_path, capsys):
    a = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=REC, threshold=75.0)
    out = capsys.readouterr().out
    assert "CEILING vs EDHREC" in out
    assert a["missing"], "the fixture should have cards above a 75% bar"
    for m in a["missing"]:
        assert m["name"][:34] in out
        # The ratio is printed beside the percentage so a reader can see the
        # sample it came from rather than trusting the percent alone.
        assert f"{m['num_decks']}/{m['potential_decks']}" in out


def test_an_empty_page_refuses_to_report_an_all_clear(mm, monkeypatch, tmp_path):
    """A redirect page ranks zero cards. Falling through, the audit finds
    nothing missing and the deck reads as needing no work -- the most
    reassuring possible output from a page that told us nothing."""
    redirect_cache = os.path.join(str(tmp_path), "redirect.json")
    with open(redirect_cache, "w", encoding="utf-8") as f:
        json.dump({"commanders/thrasios-triton-hero-tymna-the-weaver":
                   {"redirect": "/commanders/somewhere-else"}}, f)
    with pytest.raises(SystemExit) as e:
        _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=redirect_cache)
    assert "ranked no cards" in str(e.value)


def test_a_thin_edhtop16_sample_prints_the_count_and_quotes_nothing(
        mm, monkeypatch, tmp_path, capsys):
    """The acceptance criterion. Below five entries every card is 25%, 50%,
    75% or 100%, and a table of those reads like a strong signal."""
    thin = os.path.join(str(tmp_path), "thin.json")
    data = _top16_data()
    data["entries"]["edges"] = data["entries"]["edges"][:4]
    with open(thin, "w", encoding="utf-8") as f:
        json.dump({"edhtop16/100/Thrasios, Triton Hero / Tymna the Weaver": data}, f)
    got = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=thin, cedh=True)
    out = capsys.readouterr().out
    assert got is None
    assert "4 tournament entries counted" in out
    assert "FEWER THAN 5 ENTRIES" in out
    assert "%" not in out.split("entries counted")[1]


def test_a_sufficient_edhtop16_sample_does_quote_percentages(
        mm, monkeypatch, tmp_path, capsys):
    """The mirror of the case above: the refusal must be about the sample
    size, not a report that never quotes anything."""
    got = _run_ceiling(mm, monkeypatch, tmp_path, rec_cache=TOP16, cedh=True,
                       threshold=90.0)
    out = capsys.readouterr().out
    assert "CEILING vs edhtop16" in out
    assert "6 tournament entries counted" in out
    assert "FEWER THAN" not in out
    assert got is not None and got["missing"]
