"""Ported from `selftest`: the section 6 roster walk.

The roster is the section 6 enumeration; a missing or mis-keyed row is a
slot that never becomes a candidate, which is exactly the failure the
roster exists to prevent (six ABUR duals benched, rule never fired).
"""
import pytest

# Imported at module level for parametrize ids only, so each cycle gets its own
# node id. Looping inside one test would still assert everything, but a new
# cycle added later would not show up as its own named case.
import mana_model as _m

SLOTS = [s for s, _ in _m.PAIR_CYCLES]


def test_pair_key_canonical_order(mm):
    """pair_key/canonical order"""
    assert mm.pair_key("U", "W") == "WU"


def test_pair_key_already_ordered(mm):
    """pair_key/already ordered"""
    assert mm.pair_key("B", "G") == "BG"


def test_identity_pairs_three_colours(mm):
    """identity_pairs/three colours"""
    assert mm.identity_pairs("BUG") == ["UB", "UG", "BG"]


def test_identity_pairs_mono_has_no_pairs(mm):
    """identity_pairs/mono has no pairs"""
    assert mm.identity_pairs("R") == []


def test_identity_pairs_five_colours(mm):
    """identity_pairs/five colours"""
    assert len(mm.identity_pairs("WUBRG")) == 10


@pytest.mark.parametrize("slot", SLOTS,
                         ids=[f"roster/{s} has {6 if s == 'Horizon land' else 10} members"
                              for s in SLOTS])
def test_pair_cycle_has_its_members(mm, slot):
    """Horizon land has SIX; the other four rows are "no such card", not a
    missing row."""
    table = dict(mm.PAIR_CYCLES)[slot]
    want = 6 if slot == "Horizon land" else 10
    assert len(table) == want


@pytest.mark.parametrize("slot", SLOTS, ids=[f"roster/{s} keys canonical" for s in SLOTS])
def test_pair_cycle_is_canonically_keyed(mm, slot):
    table = dict(mm.PAIR_CYCLES)[slot]
    assert sorted(table) == sorted(mm.pair_key(*k) for k in table)


@pytest.mark.parametrize("slot", SLOTS, ids=[f"roster/{s} members unique" for s in SLOTS])
def test_pair_cycle_has_unique_members(mm, slot):
    table = dict(mm.PAIR_CYCLES)[slot]
    assert len(set(table.values())) == len(table)


def test_horizon_has_no_wu_row(mm):
    """roster/horizon has no WU row"""
    assert mm.PAIR_CYCLES[3][1].get("WU") is None


def test_triple_cycles_cover_ten_shards(mm):
    """roster/triple cycles cover ten shards"""
    assert len(mm.TRIPLE_CYCLES) == 10


# status: IN beats owned, and benched is reported as benched, never as absent
DECK = {"bayou", "sunken ruins"}
OWN = {"twilight mire": 1, "underground sea": 2, "bayou": 1}


def test_roster_in_deck(mm):
    """roster/in deck"""
    assert mm.roster_status("Bayou", DECK, OWN) == "IN"


def test_roster_owned_but_benched(mm):
    """roster/owned but benched"""
    assert mm.roster_status("Twilight Mire", DECK, OWN) == "BENCH x1"


def test_roster_not_owned(mm):
    """roster/not owned"""
    assert mm.roster_status("Tundra", DECK, OWN) == "BUY"


def test_roster_case_insensitive(mm):
    """roster/case insensitive"""
    assert mm.roster_status("SUNKEN RUINS", DECK, OWN) == "IN"


# a Sultai walk must generate the three filter lands of its pairs
@pytest.mark.parametrize("n", ["Sunken Ruins", "Twilight Mire", "Flooded Grove",
                               "Bayou", "Underground Sea", "Tropical Island",
                               "Zagoth Triome"],
                         ids=[f"roster/BUG generates {n}" for n in
                              ("Sunken Ruins", "Twilight Mire", "Flooded Grove",
                               "Bayou", "Underground Sea", "Tropical Island",
                               "Zagoth Triome")])
def test_bug_generates(mm, n):
    assert (n in set(mm.roster_names("BUG"))) is True


def test_bug_excludes_off_identity_filter(mm):
    """roster/BUG excludes off-identity filter"""
    assert ("Mystic Gate" in set(mm.roster_names("BUG"))) is False


def test_bug_keeps_off_pair_fetches(mm):
    """roster/BUG keeps off-pair fetches"""
    assert ("Flooded Strand" in set(mm.roster_names("BUG"))) is True


# mono-colour: no pair rows exist at all, but the identity-independent
# and off-pair-fetch rows must still be generated (they are legal there).
def test_mono_generates_no_filter_land(mm):
    """roster/mono generates no filter land"""
    assert ("Graven Cairns" in set(mm.roster_names("R"))) is False


def test_mono_keeps_fetches(mm):
    """roster/mono keeps fetches"""
    assert ("Bloodstained Mire" in set(mm.roster_names("R"))) is True


def test_mono_keeps_legendary_row(mm):
    """roster/mono keeps legendary row"""
    assert ("Plaza of Heroes" in set(mm.roster_names("R"))) is True
