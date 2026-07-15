"""Iteration 2 tests — landmark pattern matcher (amendment spec v2.2
§2.1/§2.1b). Every string here is lifted from the six corpus
run_records: Books 01 (Hatch), 02 (P&P), 03 (Frankenstein), 04 (DQ),
05 (Leaves), 07 (Carol).
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.landmarks import (
    normalize_ws,
    match_landmark,
    match_landmark_lines,
)


class TestNormalizeWs(unittest.TestCase):
    def test_nbsp_to_space(self):
        # Carol's real heading embeds U+00A0 between STAVE and ONE.
        self.assertEqual(normalize_ws("STAVE ONE."), "STAVE ONE.")

    def test_collapse_runs_and_newlines(self):
        self.assertEqual(
            normalize_ws("CHAPTER I.\n\nWHICH  TREATS"),
            "CHAPTER I. WHICH TREATS",
        )


class TestChapterClassPositives(unittest.TestCase):
    """Real landmark headings from the corpus — must match, with the
    right ordinal and kind."""

    def test_pp_clean_roman(self):
        m = match_landmark("CHAPTER IV.")
        self.assertEqual((m.kind, m.ordinal, m.ordinal_style), ("chapter", 4, "roman"))
        self.assertIsNone(m.trailing_title)

    def test_pp_final_chapter(self):
        self.assertEqual(match_landmark("CHAPTER LXI.").ordinal, 61)

    def test_hatch_spelled(self):
        m = match_landmark("CHAPTER ONE")
        self.assertEqual((m.kind, m.ordinal, m.ordinal_style), ("chapter", 1, "words"))

    def test_carol_stave_with_nbsp(self):
        m = match_landmark("STAVE ONE.")
        self.assertEqual((m.kind, m.ordinal), ("chapter", 1))
        self.assertEqual(m.section_word.lower(), "stave")

    def test_frankenstein_letter(self):
        m = match_landmark("LETTER IV.")
        self.assertEqual((m.kind, m.ordinal), ("chapter", 4))
        self.assertEqual(m.section_word.lower(), "letter")

    def test_dq_trailing_title(self):
        m = match_landmark(
            "CHAPTER I.\nWHICH TREATS OF THE CHARACTER AND PURSUITS OF "
            "THE FAMOUS GENTLEMAN DON QUIXOTE OF LA MANCHA"
        )
        self.assertEqual((m.kind, m.ordinal), ("chapter", 1))
        self.assertTrue(m.trailing_title.startswith("WHICH TREATS OF"))

    def test_dq_deep_roman(self):
        self.assertEqual(match_landmark("CHAPTER LXXIV.").ordinal, 74)

    def test_title_case_with_colon(self):
        m = match_landmark("Act One: The Beginning")
        self.assertEqual((m.kind, m.ordinal), ("chapter", 1))
        self.assertEqual(m.trailing_title, "The Beginning")


class TestPartClassPositives(unittest.TestCase):
    """Part-class words — kind must be 'part' (spec §2.3 precedence is
    applied at classification time; the matcher reports the class)."""

    def test_dq_volume_divider(self):
        m = match_landmark("Volume II")
        self.assertEqual((m.kind, m.ordinal), ("part", 2))

    def test_leaves_book_sections(self):
        m = match_landmark("BOOK I. INSCRIPTIONS")
        self.assertEqual((m.kind, m.ordinal), ("part", 1))
        self.assertEqual(m.trailing_title, "INSCRIPTIONS")

    def test_vol_abbreviation(self):
        m = match_landmark("Vol. IV.")
        self.assertEqual((m.kind, m.ordinal), ("part", 4))

    def test_part_arabic(self):
        self.assertEqual(match_landmark("Part 2").kind, "part")


class TestUnnumberedBranch(unittest.TestCase):
    def test_prologue(self):
        m = match_landmark("PROLOGUE")
        self.assertEqual((m.kind, m.landmark_subtype), ("unnumbered", "prologue"))
        self.assertIsNone(m.ordinal)

    def test_epilogue_with_punct_and_title(self):
        m = match_landmark("Epilogue: Ten Years Later")
        self.assertEqual(m.landmark_subtype, "epilogue")
        self.assertEqual(m.trailing_title, "Ten Years Later")


class TestNegatives(unittest.TestCase):
    """Strings the corpus proved MUST NOT match — poem titles, verse
    titles, boilerplate, bylines, names."""

    NEGATIVES = [
        # Leaves of Grass poem titles (381 false chapters under the old catch-all)
        "Eidolons",
        "To a Historian",
        "One’s-Self I Sing",
        "As I Ponder’d in Silence",
        # DQ commendatory-verse titles (in-stratum with real chapters)
        "URGANDA THE UNKNOWN",
        "AMADIS OF GAUL",
        "THE LADY OF ORIANA",
        # Boilerplate / front matter
        "The Project Gutenberg eBook of Pride and Prejudice",
        "PREFACE.",
        "CONTENTS",
        "ILLUSTRATIONS",
        "THE FULL PROJECT GUTENBERG™ LICENSE",
        "A Ghost Story of Christmas",
        # Bylines / names / subtitle-ish
        "CHARLES DICKENS",
        "By Walt Whitman",
        "MARLEY’S GHOST.",
        # Shape traps
        "Chapters 12",                # plural — no match
        "Letter to My Daughter",      # section word, no ordinal
        "FEDERALIST No. 10",          # mid-line section word — deferred to Book 10
    ]

    def test_all_negatives(self):
        for s in self.NEGATIVES:
            with self.subTest(s=s):
                self.assertIsNone(match_landmark(s), f"false match: {s!r}")


class TestDocumentedInterplay(unittest.TestCase):
    def test_gutenberg_license_section_matches_by_design(self):
        """'Section 5. General Information…' DOES match (section + 5).
        Stripping Gutenberg boilerplate is N-005's job (rules 1.0.3),
        which runs in the strip phase BEFORE classification. Documented
        so nobody mistakes this for a matcher bug.
        """
        m = match_landmark(
            "Section 5. General Information About Project Gutenberg electronic works"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.ordinal, 5)


class TestQ1TwoStageRuled(unittest.TestCase):
    """Q1 ruling (v2.2.1 addendum): whole-text first, per-line fallback,
    exactly-one-line rule, non-matching lines → caption_lines."""

    PP_CAPTION_MERGED = "“I hope Mr. Bingley will like it. \n\nCHAPTER II."

    def test_caption_merged_still_fails_whole_text(self):
        # §2.1 whole-text anchor: caption text precedes the chapter word.
        self.assertIsNone(match_landmark(self.PP_CAPTION_MERGED))

    def test_caption_merged_matches_per_line_with_caption_routing(self):
        scan = match_landmark_lines(self.PP_CAPTION_MERGED)
        self.assertFalse(scan.ambiguous)
        m = scan.match
        self.assertIsNotNone(m)
        self.assertEqual(m.ordinal, 2)
        self.assertEqual(m.matched_via, "line")
        self.assertEqual(len(m.caption_lines), 1)
        self.assertIn("Bingley", m.caption_lines[0])

    def test_whole_text_still_primary_for_dq(self):
        scan = match_landmark_lines("CHAPTER I.\nWHICH TREATS OF THE CHARACTER")
        m = scan.match
        self.assertEqual(m.ordinal, 1)
        self.assertEqual(m.matched_via, "whole")
        self.assertTrue(m.trailing_title.startswith("WHICH TREATS"))
        self.assertEqual(m.caption_lines, ())

    def test_two_matching_lines_is_ambiguous(self):
        # Leading caption defeats stage 1 (whole-text), so stage 2 runs
        # and finds two matching lines → ambiguous per the ruling.
        scan = match_landmark_lines("A caption line\nCHAPTER II.\nCHAPTER III.")
        self.assertIsNone(scan.match)
        self.assertTrue(scan.ambiguous)
        self.assertEqual(scan.matching_line_count, 2)

    def test_whole_text_swallows_adjacent_heading_lines_by_design(self):
        # Stage-1 primacy (ruling: "keeps DQ's whole-text trailing-title
        # path primary"): a block that IS two heading lines still matches
        # whole-text, the second line becoming the trailing title. Not a
        # corpus shape; pinned so the precedence is explicit.
        scan = match_landmark_lines("CHAPTER II.\nCHAPTER III.")
        self.assertEqual(scan.match.ordinal, 2)
        self.assertEqual(scan.match.trailing_title, "CHAPTER III.")

    def test_no_matching_lines_is_a_clean_miss(self):
        scan = match_landmark_lines("A caption line\nAnother caption line")
        self.assertIsNone(scan.match)
        self.assertFalse(scan.ambiguous)
        self.assertEqual(scan.matching_line_count, 0)


class TestQ2FusedRuled(unittest.TestCase):
    """Q2 ruling: fused no-space variant, all ordinal systems, flagged
    fused=True for the classifier's normalization warning."""

    def test_pp_fused_roman(self):
        for s, expect in (("CHAPTERXXVII.", 27), ("CHAPTERXXVIII.", 28)):
            with self.subTest(s=s):
                m = match_landmark(s)
                self.assertIsNotNone(m, f"fused variant must match {s!r}")
                self.assertEqual((m.kind, m.ordinal), ("chapter", expect))
                self.assertTrue(m.fused)

    def test_fused_arabic_and_spelled(self):
        self.assertEqual(match_landmark("CHAPTER12").ordinal, 12)
        m = match_landmark("STAVEONE.")
        self.assertEqual(m.ordinal, 1)
        self.assertTrue(m.fused)

    def test_fused_part_class(self):
        m = match_landmark("BOOKII.")
        self.assertEqual((m.kind, m.ordinal), ("part", 2))
        self.assertTrue(m.fused)

    def test_fused_rejects_real_words(self):
        # The parse gate is the guard: remainders that aren't ordinals fail.
        for s in ("Chapterhouse", "Partition", "Bookend", "ACTION", "Sectional"):
            with self.subTest(s=s):
                self.assertIsNone(match_landmark(s), f"false fused match: {s!r}")

    def test_fused_line_inside_caption_merged_block(self):
        scan = match_landmark_lines("Some caption text\n\nCHAPTERXXVII.")
        m = scan.match
        self.assertIsNotNone(m)
        self.assertEqual(m.ordinal, 27)
        self.assertTrue(m.fused)
        self.assertEqual(m.matched_via, "line")
        self.assertEqual(m.caption_lines, ("Some caption text",))

    def test_spaced_match_is_not_fused(self):
        self.assertFalse(match_landmark("CHAPTER IV.").fused)


if __name__ == "__main__":
    unittest.main()
