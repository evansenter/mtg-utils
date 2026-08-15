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
