"""Iteration 4 tests — stratum detection (§2.2) + C-001/C-002 v2
landmark classification (§2.1–§2.3 + Q1/Q2 rulings). Block shapes are
synthetic reductions of the six corpus books' run_record findings.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.rules.strata import analyze_strata, is_visually_gated, stratum_key
from lib.rules.classification import (
    C001_LandmarkClassification,
    C002_StructuralPartDetection,
)


def H(bid, level, text):
    return {"id": bid, "type": "heading", "heading_level": level,
            "spans": [{"text": text, "marks": []}]}


def P(bid, text, tags=()):
    return {"id": bid, "type": "paragraph", "style_tags": list(tags),
            "spans": [{"text": text, "marks": []}]}


def classify(blocks):
    ctx = RuleContext(blocks=blocks)
    C001_LandmarkClassification().run(ctx)
    C002_StructuralPartDetection().run(ctx)
    return ctx


class TestStratumKey(unittest.TestCase):
    def test_heading_levels_are_strata(self):
        self.assertEqual(stratum_key(H("b1", 3, "x")), ("heading", 3))

    def test_visually_gated_paragraph(self):
        b = P("b1", "CHAPTER ONE", ("centered", "bold"))
        self.assertTrue(is_visually_gated(b))
        self.assertEqual(stratum_key(b), ("paragraph_visual",))

    def test_plain_body_paragraph_has_no_stratum(self):
        self.assertIsNone(stratum_key(P("b1", "It was a truth universally...")))

    def test_long_centered_bold_paragraph_not_gated(self):
        b = P("b1", "word " * 60, ("centered", "bold"))
        self.assertFalse(is_visually_gated(b))


class TestFrankensteinShape(unittest.TestCase):
    """H3 carries 27 letters/chapters; H2 carries 3 identical title
    pages. Dominant = H3; repeated H2 titles → part_divider (C-002)."""

    def _blocks(self):
        blocks = [H("t1", 2, "Frankenstein; or, the Modern Prometheus")]
        blocks += [H(f"l{i}", 3, f"LETTER {n}.") for i, n in
                   enumerate(["I", "II", "III", "IV"], 1)]
        blocks += [H("t2", 2, "Frankenstein; or, the Modern Prometheus")]
        blocks += [H(f"c{i}", 3, f"CHAPTER {n}.") for i, n in
                   enumerate(["I", "II", "III"], 1)]
        blocks += [H("t3", 2, "Frankenstein; or, the Modern Prometheus")]
        return blocks

    def test_dominant_is_h3(self):
        analysis = analyze_strata(self._blocks())
        self.assertEqual(analysis.dominant, ("heading", 3))
        self.assertEqual(analysis.chapter_counts[("heading", 3)], 7)

    def test_chapters_assigned_and_titles_become_parts(self):
        ctx = classify(self._blocks())
        roles = {b["id"]: b.get("role") for b in ctx.blocks}
        for bid in ("l1", "l2", "l3", "l4", "c1", "c2", "c3"):
            self.assertEqual(roles[bid], "chapter_heading", bid)
        for bid in ("t1", "t2", "t3"):
            self.assertEqual(roles[bid], "part_divider", bid)
        t1 = next(b for b in ctx.blocks if b["id"] == "t1")
        self.assertIsNone(t1["part_number"])
        self.assertTrue(t1["force_page_break"])


class TestDQShape(unittest.TestCase):
    """'Volume II' sits at H3 INSIDE the landmark stratum — §2.3
    precedence must make it part_divider, not chapter (DQ Amendment 1).
    Commendatory-verse titles in-stratum stay non-landmarks."""

    def _blocks(self):
        blocks = [H(f"c{i}", 3, f"CHAPTER {r}. WHICH TREATS OF THING {i}")
                  for i, r in enumerate(["I", "II", "III", "IV", "V"], 1)]
        blocks.insert(3, H("v2", 3, "Volume II"))
        blocks.insert(0, H("verse1", 3, "URGANDA THE UNKNOWN"))
        return blocks

    def test_volume_divider_precedence_in_stratum(self):
        ctx = classify(self._blocks())
        v2 = next(b for b in ctx.blocks if b["id"] == "v2")
        self.assertEqual(v2["role"], "part_divider")
        self.assertEqual(v2["part_number"], 2)

    def test_trailing_titles_extracted(self):
        ctx = classify(self._blocks())
        c1 = next(b for b in ctx.blocks if b["id"] == "c1")
        self.assertEqual(c1["role"], "chapter_heading")
        self.assertEqual(c1["chapter_number"], 1)
        self.assertTrue(c1["chapter_title"].startswith("WHICH TREATS"))

    def test_verse_title_stays_unclassified(self):
        ctx = classify(self._blocks())
        verse = next(b for b in ctx.blocks if b["id"] == "verse1")
        self.assertIsNone(verse.get("role"))


class TestLeavesShape(unittest.TestCase):
    """34 'BOOK n.' headings, hundreds of poem titles, all H2, zero
    chapter-class matches → no dominant stratum, 0 chapters, parts
    classified, poem titles left for the terminal default."""

    def _blocks(self):
        blocks = []
        for i, r in enumerate(["I", "II", "III"], 1):
            blocks.append(H(f"bk{i}", 2, f"BOOK {r}. INSCRIPTIONS {i}"))
            blocks += [H(f"p{i}_{j}", 2, t) for j, t in enumerate(
                ["Eidolons", "To a Historian", "As I Ponder'd in Silence"])]
        return blocks

    def test_no_dominant_stratum(self):
        analysis = analyze_strata(self._blocks())
        self.assertIsNone(analysis.dominant)

    def test_parts_yes_chapters_no(self):
        ctx = classify(self._blocks())
        roles = [b.get("role") for b in ctx.blocks]
        self.assertEqual(roles.count("part_divider"), 3)
        self.assertEqual(roles.count("chapter_heading"), 0)
        poem = next(b for b in ctx.blocks if b["id"] == "p1_0")
        self.assertIsNone(poem.get("role"))


class TestHatchShape(unittest.TestCase):
    """9 'CHAPTER ONE…NINE' as centered+bold plain paragraphs — the
    visually gated paragraph stratum is dominant (C-001 v1 scored 0/9
    here; the amendment's reason to exist)."""

    WORDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE",
             "SIX", "SEVEN", "EIGHT", "NINE"]

    def _blocks(self):
        blocks = []
        for i, w in enumerate(self.WORDS, 1):
            blocks.append(P(f"ch{i}", f"CHAPTER {w}", ("centered", "bold")))
            blocks.append(P(f"body{i}", "Plain body text follows here."))
        return blocks

    def test_dominant_is_paragraph_stratum(self):
        analysis = analyze_strata(self._blocks())
        self.assertEqual(analysis.dominant, ("paragraph_visual",))

    def test_nine_chapters_numbered(self):
        ctx = classify(self._blocks())
        chapters = [b for b in ctx.blocks if b.get("role") == "chapter_heading"]
        self.assertEqual(len(chapters), 9)
        self.assertEqual([c["chapter_number"] for c in chapters],
                         list(range(1, 10)))
        bodies = [b for b in ctx.blocks if b["id"].startswith("body")]
        self.assertTrue(all(b.get("role") is None for b in bodies))


class TestPPShape(unittest.TestCase):
    """H2 chapters incl. caption-merged and fused forms; junk H2s
    (PREFACE., CONTENTS) must not be chapters."""

    def _blocks(self):
        blocks = [
            H("junk1", 2, "PREFACE."),
            H("junk2", 2, "CONTENTS"),
            H("c1", 2, "CHAPTER I."),
            H("c2", 2, "“I hope Mr. Bingley will like it.\n\nCHAPTER II."),
            H("c27", 2, "CHAPTERXXVII."),
            H("c28", 2, "CHAPTER XXVIII."),
        ]
        return blocks

    def test_caption_merged_and_fused_classified(self):
        ctx = classify(self._blocks())
        by_id = {b["id"]: b for b in ctx.blocks}
        self.assertEqual(by_id["c2"]["role"], "chapter_heading")
        self.assertEqual(by_id["c2"]["chapter_number"], 2)
        self.assertEqual(by_id["c27"]["role"], "chapter_heading")
        self.assertEqual(by_id["c27"]["chapter_number"], 27)

    def test_fused_emits_normalization_warning(self):
        ctx = classify(self._blocks())
        fused_warnings = [w for w in ctx.warnings
                          if "missing space" in w.get("detail", "")]
        self.assertEqual(len(fused_warnings), 1)
        self.assertEqual(fused_warnings[0]["block_id"], "c27")

    def test_junk_not_chapters(self):
        ctx = classify(self._blocks())
        by_id = {b["id"]: b for b in ctx.blocks}
        self.assertIsNone(by_id["junk1"].get("role"))
        self.assertIsNone(by_id["junk2"].get("role"))


class TestCarolShape(unittest.TestCase):
    """Staves with NBSP between word and ordinal (normalization proven)."""

    def test_staves_numbered(self):
        blocks = [H(f"s{i}", 2, f"STAVE {w}.") for i, w in
                  enumerate(["ONE", "TWO", "THREE", "FOUR", "FIVE"], 1)]
        ctx = classify(blocks)
        chapters = [b for b in ctx.blocks if b.get("role") == "chapter_heading"]
        self.assertEqual([c["chapter_number"] for c in chapters], [1, 2, 3, 4, 5])


class TestAmbiguityAndUnnumbered(unittest.TestCase):
    def test_ambiguous_candidate_warns_and_stays_unclassified(self):
        blocks = [H(f"c{i}", 2, f"CHAPTER {r}.") for i, r in
                  enumerate(["I", "II", "III"], 1)]
        blocks.append(H("amb", 2, "A caption line\nCHAPTER IV.\nCHAPTER V."))
        ctx = classify(blocks)
        amb = next(b for b in ctx.blocks if b["id"] == "amb")
        self.assertIsNone(amb.get("role"))
        warnings = [w for w in ctx.warnings
                    if "ambiguous landmark" in w.get("detail", "")]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["block_id"], "amb")

    def test_prologue_in_dominant_stratum(self):
        blocks = [H("pro", 2, "PROLOGUE")]
        blocks += [H(f"c{i}", 2, f"Chapter {i}") for i in range(1, 4)]
        ctx = classify(blocks)
        pro = next(b for b in ctx.blocks if b["id"] == "pro")
        self.assertEqual(pro["role"], "chapter_heading")
        self.assertIsNone(pro["chapter_number"])
        self.assertEqual(pro["landmark_subtype"], "prologue")

    def test_chapter_shaped_text_outside_dominant_stratum_ignored(self):
        # The dead catch-all: an H1 "Chapter 9" while H2 is dominant.
        blocks = [H("h1", 1, "Chapter 9")]
        blocks += [H(f"c{i}", 2, f"Chapter {i}") for i in range(1, 4)]
        ctx = classify(blocks)
        h1 = next(b for b in ctx.blocks if b["id"] == "h1")
        self.assertIsNone(h1.get("role"))


if __name__ == "__main__":
    unittest.main()
