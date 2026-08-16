"""Decklist IO: read, write with assertions, and multiset diff."""
import re
from collections import Counter

# ============================================================ decklist IO
def _entry(line):
    m = re.match(r"^(\d+)\s+(.*)$", line)
    return (int(m.group(1)), m.group(2).strip()) if m else (1, line)


def read_decklist(path):
    """Returns (commanders, entries). Commanders is a LIST -- partner and
    background decks have two, and taking only line one silently produced a
    99-card deck whose second commander's colours read as identity violations.

    Format: the commander BLOCK comes first, then a blank line, then the deck
    (this is exactly what `write` emits). A file with no blank line falls back
    to "line one is the commander" so older files still read.
    """
    blocks, cur = [], []
    for l in open(path, encoding="utf-8"):
        l = l.strip()
        if l.startswith("#"):
            continue
        if not l:
            if cur:
                blocks.append(cur); cur = []
            continue
        cur.append(l)
    if cur:
        blocks.append(cur)
    if not blocks:
        return [], Counter()
    if len(blocks) > 1 and 1 <= len(blocks[0]) <= 2:
        head, rest = blocks[0], [l for b in blocks[1:] for l in b]
    else:
        flatlines = [l for b in blocks for l in b]
        head, rest = flatlines[:1], flatlines[1:]
    cmdrs = [_entry(l)[1] for l in head]
    entries = Counter()
    for l in rest:
        n, name = _entry(l)
        entries[name] += n
    return cmdrs, entries


def as_cmdrs(cmdr):
    """Every function here accepts a commander string or a list of them."""
    return list(cmdr) if isinstance(cmdr, (list, tuple)) else [cmdr]


def flat(cmdr, entries):
    out = list(as_cmdrs(cmdr))
    for n, q in entries.items():
        out.extend([n] * q)
    return out


def write_deck(cmdr, entries, out_path, expect_adds=(), expect_cuts=()):
    cmdrs = as_cmdrs(cmdr)
    lines = list(cmdrs) + [""]
    for n in sorted(entries, key=str.lower):
        lines.append(f"{entries[n]} {n}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # read back and assert
    got = [l.rstrip("\n") for l in open(out_path, encoding="utf-8")]
    assert got[:len(cmdrs)] == cmdrs, f"commander lines wrong: {got[:len(cmdrs)]}"
    body = [l for l in got[len(cmdrs) + 1:] if l.strip()]
    total = len(cmdrs) + sum(int(l.split(" ", 1)[0]) for l in body)
    for a in expect_adds:
        assert any(l.split(" ", 1)[1] == a for l in body), f"MISSING ADD: {a}"
    for c in expect_cuts:
        assert not any(l.split(" ", 1)[1] == c for l in body), f"CUT STILL PRESENT: {c}"
    print(f"\n=== WROTE {out_path} ===")
    print(f"  read back: {len(body)} entries, {total} cards, commander line OK")
    assert total == 100, f"deck is {total} cards, Commander is 100"
    return total


# ============================================================ card-name lists
def _sep(spec):
    """The separator a name list is using: ';' when present, else ','.

    Card names contain commas -- 'Muldrotha, the Gravetide', 'Ghalta, Primal
    Hunger' -- so a comma is not a safe separator in general. A semicolon
    WINS when present, which is the escape hatch for a name with a comma in
    it, and every flag that takes card names uses this same rule.

    One function rather than the rule written out at each caller, because it
    was written out at one caller and not the others for a while: --swap had
    the escape hatch and --adds/--cuts split on ',' alone, so 'Ghalta, Primal
    Hunger' could be swapped in but not added.
    """
    return ";" if ";" in spec else ","


def split_names(spec):
    """'A,B' -> ['A', 'B'], ';' winning when present. Empty spec -> [].

    Used by --adds and --cuts, which are names and nothing else. A comma
    inside a name used to split it: --adds "Ghalta, Primal Hunger" became
    'Ghalta' and 'Primal Hunger', and write_deck's read-back assertion then
    failed with "MISSING ADD: Ghalta" -- an error that reads as a typo in a
    name that was spelled correctly. The assertion is checking the deck it
    wrote; it cannot know the name it was handed had already been halved.
    """
    spec = (spec or "").strip()
    if not spec:
        return []
    return [x.strip() for x in spec.split(_sep(spec)) if x.strip()]


def parse_swaps(spec):
    """'A->B,C->D' -> [('A', 'B'), ('C', 'D')]. Empty spec -> [].

    Separator rule is _sep's: ';' wins when present, for the reason given
    there.

    A segment that does not hold exactly one '->' is rejected by name rather
    than mis-split quietly. A mis-split swap would cut a card nobody asked to
    cut and report the result as a measurement, which is worse than not
    running: the number would look like an answer.
    """
    spec = (spec or "").strip()
    if not spec:
        return []
    sep = _sep(spec)
    swaps = []
    for seg in spec.split(sep):
        seg = seg.strip()
        if not seg:
            continue
        if seg.count("->") != 1:
            raise SystemExit(
                f"--swap: cannot read {seg!r} as one 'cut->add' pair. Pairs are "
                f"separated by '{sep}'; if a card name contains a comma, "
                f"separate the pairs with ';' instead.")
        cut, add = (x.strip() for x in seg.split("->"))
        if not cut or not add:
            raise SystemExit(f"--swap: {seg!r} has an empty side")
        swaps.append((cut, add))
    return swaps


def apply_swaps(cmdr, entries, swaps):
    """Apply cut->add pairs to `entries`, returning a NEW Counter.

    The same contract write_deck asserts after the fact, enforced up front:
    every cut is present beforehand, every add is absent beforehand, and the
    total is unchanged. A swap naming a card the deck does not have RAISES --
    silently no-opping would report "this change moves nothing", which is
    indistinguishable from the genuine finding that a swap moves nothing
    because the deck has no unmet pip. That is the one answer this command
    exists to give, so it must not also be its failure mode.

    Matching is case-insensitive; the deck's own spelling is preserved.
    """
    out = Counter(entries)
    by_lower = {n.lower(): n for n in out}
    cmdr_lower = {c.lower(): c for c in as_cmdrs(cmdr)}
    for cut, add in swaps:
        cl, al = cut.lower(), add.lower()
        if cl == al:
            raise SystemExit(f"--swap: {cut!r} swapped for itself")
        if cl in cmdr_lower or al in cmdr_lower:
            raise SystemExit(
                f"--swap: {cut}->{add} touches a commander. The commander is "
                f"not part of the 99 and swapping it changes the deck's colour "
                f"identity, which is a different question than this measures.")
        if cl not in by_lower:
            raise SystemExit(
                f"--swap: cannot cut {cut!r} -- it is not in the deck.")
        if al in by_lower:
            raise SystemExit(
                f"--swap: cannot add {add!r} -- the deck already has it, and "
                f"Commander is singleton.")
        real_cut = by_lower[cl]
        out[real_cut] -= 1
        if out[real_cut] == 0:
            del out[real_cut]
            del by_lower[cl]
        out[add] += 1
        by_lower[al] = add
    before, after = sum(entries.values()), sum(out.values())
    assert before == after, f"swap changed the deck size: {before} -> {after}"
    return out


def diff_multiset(local_cmdrs, local_entries, live_cmdrs, live_main):
    """Card-multiset diff. Pure compute.

    lastUpdatedAtUtc moves on a description or folder edit, so the timestamp is
    not evidence the LIST changed -- diff the multiset, never the stamp.
    Returns (only_local, only_live, cmdr_change) as sorted (name, n) lists.
    """
    a, b = Counter(local_entries), Counter(live_main)
    only_local = sorted((n, c) for n, c in (a - b).items())
    only_live = sorted((n, c) for n, c in (b - a).items())
    ca, cb = sorted(as_cmdrs(local_cmdrs)), sorted(as_cmdrs(live_cmdrs))
    return only_local, only_live, (None if ca == cb else (ca, cb))


# A decision note, carried in the decklist file itself:
#
#   # CUT: Wakening Sun's Avatar -- destroys [[Craterhoof Behemoth]]
#
# The placement is the design. A separate ledger keyed by commander is a
# second store that nothing keeps honest: its entries are invalidated by deck
# changes it cannot observe, and nothing fails when they go stale. Kept in the
# decklist, a note travels in the same file as the cards it reasons about,
# changes in the same diff, and is reviewed by whoever changes the list. It is
# also already ignored by every existing reader -- read_decklist has always
# skipped '#' lines -- so no other caller sees a thing.
#
# Reasons cite cards with [[...]], the same markup a primer uses, so
# parse_primer_links does the extraction for both and the staleness rule is
# one implementation rather than two that drift.
DECISION = re.compile(r"^#\s*(CUT|TRAP|DEFER):\s*(.+?)\s+--\s+(.*)$", re.I)


def read_decisions(path):
    """The CUT / TRAP / DEFER notes in a decklist, in file order.

    Verdicts are a deliberately short vocabulary. A trap is the permanent end
    of the same ledger a cut sits on -- "I looked at this and the answer is
    no, and it will still be no next time" -- and a defer is the same sentence
    with a date on it. Three words cover what a rejection can mean; more would
    be a taxonomy nobody maintains.
    """
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            m = DECISION.match(line.strip())
            if not m:
                continue
            verdict, card, reason = m.groups()
            out.append({"verdict": verdict.upper(), "card": card.strip(),
                        "reason": reason.strip(), "line": n})
    return out
