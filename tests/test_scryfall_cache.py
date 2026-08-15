"""scry_fetch's cache round-trip.

The cache is what makes every other test offline, and what makes a deck cost
one Scryfall call rather than one per subcommand. Nothing tested it.

No network here: subprocess.run is replaced either with a canned response or
with something that raises, so "did it call out" is itself an assertion.
"""
import json
import os
import subprocess

import pytest

from conftest import FIXTURES


class FakeRun:
    """Stands in for subprocess.run and records the curl argv it was given."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        body = self.payloads.pop(0)

        class R:
            stdout = json.dumps(body)
            returncode = 0
        return R()


def _card(name, **kw):
    d = {"name": name, "type_line": "Artifact", "cmc": 1, "oracle_text": "",
         "color_identity": [], "legalities": {"commander": "legal"}}
    d.update(kw)
    return d


@pytest.fixture
def no_network(monkeypatch):
    """Any call out is a test failure, not a slow test.

    Patching the attribute on the subprocess MODULE object covers every
    importer of it, so this holds wherever scry_fetch happens to live.
    """
    def boom(*a, **k):
        raise AssertionError("scry_fetch went to the network")
    monkeypatch.setattr(subprocess, "run", boom)


def test_complete_cache_makes_no_request(mm, no_network, tmp_path):
    """cache/a complete cache is offline

    This is the property the whole test suite rests on: with every name
    present, `want` is empty and curl is never invoked.
    """
    src = os.path.join(FIXTURES, "mono.scry.json")
    dst = tmp_path / "c.json"
    dst.write_text(open(src, encoding="utf-8").read(), encoding="utf-8")
    cache, nf = mm.scry_fetch(["Sol Ring", "Ancient Tomb", "Mountain"], str(dst))
    assert nf == []
    assert "sol ring" in cache


def test_round_trip_is_stable(mm, no_network, tmp_path):
    """cache/round-trips unchanged

    Read, write, read again: the second read must give the same dict. The
    cache is rewritten on every run, so a lossy write would degrade the file
    a little at a time rather than failing outright.
    """
    src = os.path.join(FIXTURES, "colourless.scry.json")
    dst = tmp_path / "c.json"
    dst.write_text(open(src, encoding="utf-8").read(), encoding="utf-8")
    names = ["Wastes", "Thought-Knot Seer"]
    first, _ = mm.scry_fetch(names, str(dst))
    second, _ = mm.scry_fetch(names, str(dst))
    assert first == second
    with open(dst, encoding="utf-8") as f:
        assert json.load(f) == first


def test_profiles_survive_the_round_trip(mm, no_network, tmp_path):
    """cache/profiles are identical after a rewrite

    JSON has no frozenset and no tuple. If a rewrite changed a type, the
    profiles built from the reloaded cache would differ and every number with
    them.
    """
    src = os.path.join(FIXTURES, "multi.scry.json")
    dst = tmp_path / "c.json"
    dst.write_text(open(src, encoding="utf-8").read(), encoding="utf-8")
    cmdr, entries = mm.read_decklist(os.path.join(FIXTURES, "multi.txt"))
    names = mm.flat(cmdr, entries)[1:]
    a, _ = mm.scry_fetch(mm.flat(cmdr, entries), str(dst))
    before = mm.build_land_profiles(names, a)
    b, _ = mm.scry_fetch(mm.flat(cmdr, entries), str(dst))
    after = mm.build_land_profiles(names, b)
    assert before == after


def test_fetch_keys_on_both_names_and_queries_the_front_face(mm, monkeypatch, tmp_path):
    """cache/keyed on both names, queried on the front face

    Scryfall rejects the full "X // Y" form -- it comes back in not_found --
    but answers under it. So the query carries the front face only and the
    result is stored under both, or every later lookup by full name misses.
    """
    import mtg_utils.sources.scryfall as sf
    fake = FakeRun([{"object": "list", "data": [
        _card("Agadeem's Awakening // Agadeem, the Undercrypt")], "not_found": []}])
    monkeypatch.setattr(sf.subprocess, "run", fake)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)

    dst = tmp_path / "c.json"
    cache, nf = mm.scry_fetch(["Agadeem's Awakening // Agadeem, the Undercrypt"], str(dst))

    sent = json.loads(fake.calls[0][fake.calls[0].index("-d") + 1])
    assert sent["identifiers"] == [{"name": "Agadeem's Awakening"}], sent
    assert "agadeem's awakening // agadeem, the undercrypt" in cache
    assert "agadeem's awakening" in cache
    assert cache["agadeem's awakening"] is cache[
        "agadeem's awakening // agadeem, the undercrypt"]


def test_not_found_is_returned_and_not_cached(mm, monkeypatch, tmp_path):
    """cache/not_found is reported and never cached

    Current behaviour, pinned rather than endorsed: a name Scryfall could not
    resolve is returned to the caller and is NOT written to the cache, so the
    next run asks again. That is the right call for a typo being fixed and
    the wrong one for a name that will never resolve; either way it is what
    the tool does.
    """
    import mtg_utils.sources.scryfall as sf
    fake = FakeRun([{"object": "list", "data": [_card("Sol Ring")],
                     "not_found": [{"name": "Definitely Not A Card"}]}])
    monkeypatch.setattr(sf.subprocess, "run", fake)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)

    dst = tmp_path / "c.json"
    cache, nf = mm.scry_fetch(["Sol Ring", "Definitely Not A Card"], str(dst))
    assert nf == ["Definitely Not A Card"]
    assert "definitely not a card" not in cache
    with open(dst, encoding="utf-8") as f:
        assert "definitely not a card" not in json.load(f)


def test_cache_file_is_written_even_when_nothing_was_fetched(mm, no_network, tmp_path):
    """cache/written on every run

    Why the golden tests copy the fixture cache to a temp directory before
    running: pointed at the committed file, the suite would rewrite its own
    frozen input on every invocation.
    """
    dst = tmp_path / "c.json"
    dst.write_text(json.dumps({"sol ring": _card("Sol Ring")}), encoding="utf-8")
    stamp = dst.stat().st_mtime_ns
    os.utime(dst, ns=(stamp - 10**9, stamp - 10**9))
    cache, nf = mm.scry_fetch(["Sol Ring"], str(dst))
    assert dst.stat().st_mtime_ns > stamp - 10**9, "cache was not rewritten"
    with open(dst, encoding="utf-8") as f:
        assert json.load(f) == cache


def test_no_cache_path_means_no_file(mm, monkeypatch, tmp_path):
    """cache/cache_path is optional"""
    import mtg_utils.sources.scryfall as sf
    fake = FakeRun([{"object": "list", "data": [_card("Sol Ring")], "not_found": []}])
    monkeypatch.setattr(sf.subprocess, "run", fake)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    cache, nf = mm.scry_fetch(["Sol Ring"], None)
    assert "sol ring" in cache
    assert list(tmp_path.iterdir()) == []


def test_batches_at_75(mm, monkeypatch, tmp_path):
    """cache/batched at 75 per request

    Scryfall's documented ceiling for /cards/collection. 80 names must be two
    requests, not one silently truncated to the first 75.
    """
    import mtg_utils.sources.scryfall as sf
    names = [f"Card {i}" for i in range(80)]
    fake = FakeRun([
        {"object": "list", "data": [_card(n) for n in names[:75]], "not_found": []},
        {"object": "list", "data": [_card(n) for n in names[75:]], "not_found": []},
    ])
    monkeypatch.setattr(sf.subprocess, "run", fake)
    monkeypatch.setattr(sf.time, "sleep", lambda *_: None)
    cache, nf = mm.scry_fetch(names, None)
    assert len(fake.calls) == 2
    first = json.loads(fake.calls[0][fake.calls[0].index("-d") + 1])
    assert len(first["identifiers"]) == 75
    assert all(f"card {i}" in cache for i in range(80))
