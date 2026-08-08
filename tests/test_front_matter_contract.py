"""Front-Matter Contract v1 — W1 battery (build #58, amendment A1 +
C's epigraph guard, 2026-07-28).

Doc of record: 4 - Automation System/FrontMatter_Contract_v1.md.
These exercise C-009 (headless front-matter shape detection) through
the REAL ordered classify phase, so C-003's skip-by-non-overwrite is
part of what's tested — not mocked.

Cases here are the W1-side rows of the contract battery:
  1. Fixture zero (V-007, the Swallow's v1): title_page and dedication
     come out as DISJOINT block ranges — the dedication is NOT absorbed
     into the title cluster.
  2. Dropped-page-break probe: the pathology isolated — no page break
     between title and dedication, classifier still cuts on shape.
  (epigraph) A book that opens on a headless epigraph hits the identical
     absorption risk; C-009 claims it as its own class, not title_page.
  7. unknown_front tripwire: an ambiguous pre-body block matches no
     shape and is left UNTOUCHED (nothing suppressed) — the regression
     guard that keeps the detector from eating genuine prose.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.pipeline import run_phase
from lib.front_matter import build_front_matter_section


def blk(bid, text, tags=None, typ="paragraph"):
    b = {"id": bid, "type": typ, "spans": [{"text": text, "marks": []}]}
    if tags is not None:
        b["style_tags"] = tags
    return b


def classified(blocks):
    ctx = RuleContext(blocks=blocks)
    run_phase("classify", ctx)
    return ctx.blocks


def role_of(blocks, bid):
    for b in blocks:
        if b["id"] == bid:
            return b.get("role"), b.get("subtype")
    raise AssertionError(f"no block {bid}")


def ranges_by_role(blocks):
    """{role: [indices]} — for disjointness assertions."""
    out = {}
    for i, b in enumerate(blocks):
        out.setdefault(b.get("role"), []).append(i)
    return out


# The exact Swallow's-v1 front matter (C, 2026-07-28), with the page
# break between title cluster and dedication DROPPED — the docx→JSON
# pathology reproduced.
def swallow_fixture_zero():
    return [
        blk("b_000001", "THE SWALLOW'S RETURN", ["centered", "large_font"]),
        blk("b_000002", "a novel", ["centered"]),
        blk("b_000003", "Wren Calloway", ["centered"]),
        # [dropped page break]
        blk("b_000004",
            "For everyone who ever hit send too late — and for the "
            "town that bet on them anyway.", ["centered"]),
        blk("b_000005", "Chapter One: The Book of Common Wagers", []),
        blk("b_000006",
            "It was the kind of morning the town would later swear it "
            "had seen coming, though not one of them had said so aloud. "
            * 3, []),
    ]


class TestFixtureZero(unittest.TestCase):
    def test_dedication_not_absorbed_disjoint_ranges(self):
        blocks = classified(swallow_fixture_zero())
        # The load-bearing A1 assertion: dedication is its own class,
        # NOT part of the title cluster.
        ded_role, ded_sub = role_of(blocks, "b_000004")
        self.assertEqual(ded_role, "front_matter")
        self.assertEqual(ded_sub, "dedication")
        # And the title cluster does NOT span the dedication.
        by_role = ranges_by_role(blocks)
        title_idxs = by_role.get("title_page", [])
        self.assertEqual(title_idxs, [0, 1, 2],
                         "title_page must be exactly b1..b3, not reach b4")
        self.assertNotIn(3, title_idxs,
                         "V-007 regression: dedication absorbed into title")

    def test_title_cluster_intact(self):
        blocks = classified(swallow_fixture_zero())
        for bid in ("b_000001", "b_000002", "b_000003"):
            self.assertEqual(role_of(blocks, bid)[0], "title_page")


class TestDroppedBreakProbe(unittest.TestCase):
    """A2/A1: no page break anywhere between title and dedication —
    the classifier must cut on SHAPE alone, not a surviving break."""

    def test_shape_cut_without_page_break(self):
        blocks = classified([
            blk("b1", "SMALL MERCIES", ["centered", "large_font"]),
            blk("b2", "Dolores Reyes", ["centered"]),
            blk("b3", "To my mother, who kept every letter.", ["centered"]),
            blk("b4", "One", ["centered"]),
            blk("b5", "The rain had not stopped for three days, and the "
                      "gutters had given up their arguing. " * 4, []),
        ])
        self.assertEqual(role_of(blocks, "b3"), ("front_matter", "dedication"))
        self.assertEqual(role_of(blocks, "b1")[0], "title_page")
        self.assertEqual(role_of(blocks, "b2")[0], "title_page")


class TestEpigraphGuard(unittest.TestCase):
    """C's guard: an epigraph shares the identical absorption risk.
    Its own class, not title_page."""

    def test_headless_epigraph_claimed_not_absorbed(self):
        blocks = classified([
            blk("b1", "THE TIDE TABLE", ["centered", "large_font"]),
            blk("b2", "R. H. Marsh", ["centered"]),
            blk("b3", "“The sea does not ask permission.”", ["centered"]),
            blk("b4", "— a fisherman's proverb", ["centered"]),
            blk("b5", "The harbor at dawn was the colour of a bruise "
                      "healing, and Isla counted the boats twice. " * 4, []),
        ])
        self.assertEqual(role_of(blocks, "b3"), ("front_matter", "epigraph"))
        # title cluster stays b1..b2
        self.assertEqual(role_of(blocks, "b1")[0], "title_page")
        self.assertNotEqual(role_of(blocks, "b3")[0], "title_page")

    def test_unquoted_epigraph_via_attribution(self):
        blocks = classified([
            blk("b1", "FIELD NOTES", ["centered", "large_font"]),
            blk("b2", "J. Okonkwo", ["centered"]),
            blk("b3", "We are all just walking each other home.", ["centered"]),
            blk("b4", "— Ram Dass", ["centered"]),
            blk("b5", "The first entry in the notebook was dated a year "
                      "before she was born, in a hand she did not know. " * 4, []),
        ])
        self.assertEqual(role_of(blocks, "b3"), ("front_matter", "epigraph"))


class TestUnknownFrontTripwire(unittest.TestCase):
    """Case 7 — the regression guard. An ambiguous pre-body block that
    matches NO shape must be left untouched by C-009 (nothing
    suppressed): it must NOT carry a C-009-stamped front_matter role."""

    def test_ambiguous_block_left_untouched(self):
        blocks = classified([
            blk("b1", "A MURMURATION", ["centered", "large_font"]),
            blk("b2", "Kestrel Vane", ["centered"]),
            # No 'For/To', no quote, no attribution — genuinely ambiguous.
            blk("b3", "A meditation on flight and falling", ["centered"]),
            blk("b4", "The starlings came back the week the mill closed, "
                      "as if they had been waiting for the quiet. " * 4, []),
        ])
        role, sub = role_of(blocks, "b3")
        # C-009 must not have claimed it as dedication/epigraph.
        self.assertNotEqual(sub, "dedication")
        self.assertNotEqual(sub, "epigraph")

    def test_genuine_short_prose_not_eaten(self):
        # "To" opener AFTER body has begun must never be reclassified —
        # the window has already closed on the first long paragraph.
        blocks = classified([
            blk("b1", "LONG WAY DOWN", ["centered", "large_font"]),
            blk("b2", "Marcus Bell", ["centered"]),
            blk("b3", "Chapter 1", ["centered"]),
            blk("b4", "The elevator smelled of pennies and old rain. " * 6, []),
            # A later short 'To ...' line deep in the body: not front matter.
            blk("b5", "To the roof, then.", []),
        ])
        role, sub = role_of(blocks, "b5")
        self.assertNotEqual(sub, "dedication")


class TestHalfTitle(unittest.TestCase):
    """Case 3 / amendment A2: a half-title (title only) plus a full
    title page (title + author) → TWO classes. Folding the half-title
    into title_page would make W2 suppress the real title page and ship
    the bare half-title in its place."""

    def _book(self):
        return classified([
            blk("b1", "THE SWALLOW'S RETURN", ["centered", "large_font"]),
            blk("b2", "THE SWALLOW'S RETURN", ["centered", "large_font"]),
            blk("b3", "a novel", ["centered"]),
            blk("b4", "Wren Calloway", ["centered"]),
            blk("b5", "It was the kind of morning the town would later "
                      "swear it had seen coming, though not one of them "
                      "had said so aloud. " * 3, []),
        ])

    def test_half_title_is_its_own_class(self):
        blocks = self._book()
        self.assertEqual(role_of(blocks, "b1"), ("front_matter", "half_title"))

    def test_real_title_page_survives(self):
        blocks = self._book()
        for bid in ("b2", "b3", "b4"):
            self.assertEqual(role_of(blocks, bid)[0], "title_page")

    def test_section_reports_both_disjoint(self):
        section = build_front_matter_section(self._book())
        classes = [e["class"] for e in section["elements"]]
        self.assertIn("half_title", classes)
        self.assertIn("title_page", classes)
        half = next(e for e in section["elements"] if e["class"] == "half_title")
        title = next(e for e in section["elements"] if e["class"] == "title_page")
        self.assertEqual(half["block_range"], ["b1", "b1"])
        self.assertEqual(title["block_range"], ["b2", "b4"])
        # half_title is author-only: it must NOT suppress a generator.
        self.assertNotIn("half_title", section["carried"])
        self.assertIn("title_page", section["carried"])


class TestCopyrightClass(unittest.TestCase):
    """A3 (W1 half): the copyright page is claimed by shape even though
    it runs LONG — it must not be missed, and it must not be mistaken
    for the body paragraph that closes the front window. W2's verdict
    matrix keys off this class."""

    def test_long_copyright_page_claimed(self):
        blocks = classified([
            blk("b1", "SMALL MERCIES", ["centered", "large_font"]),
            blk("b2", "Dolores Reyes", ["centered"]),
            blk("b3", "Copyright © 2026 Dolores Reyes. All rights reserved. "
                      "No part of this book may be reproduced in any form "
                      "without written permission from the publisher. "
                      "ISBN 978-1-971041-07-0. First edition, 2026.", []),
            blk("b4", "To my mother, who kept every letter.", ["centered"]),
            blk("b5", "The rain had not stopped for three days. " * 8, []),
        ])
        self.assertEqual(role_of(blocks, "b3"), ("front_matter", "copyright"))
        # and the window did NOT close on it — the dedication after it
        # is still caught.
        self.assertEqual(role_of(blocks, "b4"), ("front_matter", "dedication"))

    def test_section_marks_copyright_carried(self):
        section = build_front_matter_section(classified([
            blk("b1", "TITLE HERE", ["centered", "large_font"]),
            blk("b2", "An Author", ["centered"]),
            blk("b3", "Copyright © 2026. All rights reserved.", []),
            blk("b4", "The story begins on a Tuesday in the rain. " * 8, []),
        ]))
        self.assertIn("copyright_page", section["carried"])


class TestFrontMatterSection(unittest.TestCase):
    """The W1→W2 seam itself: disjoint ranges, honest carried set."""

    def test_empty_when_no_front_matter(self):
        section = build_front_matter_section(classified([
            blk("b1", "The rain had not stopped for three days, and the "
                      "gutters had given up their arguing. " * 4, []),
        ]))
        self.assertEqual(section["carried"], [])

    def test_ranges_never_overlap(self):
        section = build_front_matter_section(swallow_fixture_zero_classified())
        seen = []
        for e in section["elements"]:
            seen.append(tuple(e["block_range"]))
        self.assertEqual(len(seen), len(set(seen)), "duplicate ranges")
        # fixture zero: title_page b1..b3, dedication b4..b4 — disjoint.
        rng = {e["class"]: e["block_range"] for e in section["elements"]}
        self.assertEqual(rng["title_page"], ["b_000001", "b_000003"])
        self.assertEqual(rng["dedication"], ["b_000004", "b_000004"])


def swallow_fixture_zero_classified():
    return classified(swallow_fixture_zero())


if __name__ == "__main__":
    unittest.main()
