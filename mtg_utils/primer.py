"""Primer link extraction: every `[[Card Name]]` in a written primer.

A primer is prose, so nothing about it is checked by anything else here. The
two failures this module exists to catch both look fine in the source text and
are only visible in the rendered page, or not at all:

**A link broken across a line does not render.** Hard-wrapping a paragraph puts
a newline inside the brackets, and `[[Sword of Feast\nand Famine]]` renders as
literal text with the brackets showing. Reading the markdown back does not
surface it -- the words are all present and in the right order.

**A link outlives the card.** Cut a card from the list and the primer still
argues for it. That paragraph is now describing a deck that does not exist, and
it is the single most common way a primer goes quietly wrong: nothing about
editing a decklist touches the prose that discusses it.

Both were hit by hand twice in one session, which is what a mechanical check is
for.
"""
import re

# [[Card Name]] and [[Card Name|SET]] -- the Moxfield / Reddit primer
# convention.
#
# re.S is load-bearing and counterintuitive. WITHOUT it, `.` does not cross a
# newline, so a link broken across a line does not match this pattern AT ALL:
# the scan walks straight past the one link on the page that does not render
# and the primer comes back clean. Matching the wrapped link and then
# REJECTING it is the entire point. Declining to match it is how this check
# would pass a broken primer.
LINK_RE = re.compile(r"\[\[(.*?)\]\]", re.S)

# Counted separately so an opener with no closer at all -- which LINK_RE
# cannot match by construction, and which therefore contributes nothing to the
# list of links to check -- is still reported rather than vanishing.
OPENER_RE = re.compile(r"\[\[")


def parse_primer_links(text):
    """Every `[[...]]` in a primer, in document order.

    Each link carries its 1-based line number, because the whole value of the
    report is being told WHERE to look; a list of bad card names in a
    3000-word primer is barely better than no report.

    `name` is whitespace-normalised, so a link broken across a line still
    reports the card it was meant to be. That is deliberate: "line 84 is
    broken and it means Sword of Feast and Famine" is an actionable sentence
    and "line 84 is broken" is a search.
    """
    links = []
    for m in LINK_RE.finditer(text):
        raw = m.group(1)
        # The set code is display sugar -- [[Sol Ring|LEA]] is the same card
        # as [[Sol Ring]]. Stripped before the name reaches Scryfall or the
        # decklist, or every deliberately-pinned printing in the primer reads
        # as a card that does not exist.
        name = raw.split("|")[0]
        links.append({
            "raw": raw,
            "name": " ".join(name.split()),
            "line": text.count("\n", 0, m.start()) + 1,
            "wrapped": "\n" in raw,
            "start": m.start(),
            "end": m.end(),
        })
    return links


def unclosed_openers(text, links):
    """Line numbers of every `[[` that no link consumed.

    An opener with no closer cannot appear in `links` -- LINK_RE needs a `]]`
    to match -- so without this it is not merely unreported, it is invisible:
    the card it names is never checked against the deck, never checked against
    Scryfall, and the primer passes with a dangling bracket in the middle of a
    sentence.
    """
    spans = [(l["start"], l["end"]) for l in links]
    out = []
    for m in OPENER_RE.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        out.append(text.count("\n", 0, m.start()) + 1)
    return out
