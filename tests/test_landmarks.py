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


class TestSpecQuestionsQ1Q2(unittest.TestCase):
    """SPEC QUESTIONS (MIGRATION_NOTES_v1.1.md) — these tests document
    spec-as-written behavior. They are NOT the desired end state; they
    pin the ambiguity until the spec rules.
    """

    PP_CAPTION_MERGED = "“I hope Mr. Bingley will like it. \n\nCHAPTER II."

    def test_q1_caption_merged_fails_whole_text_per_spec(self):
        # §2.1 whole-text anchor: caption text precedes the chapter word.
        self.assertIsNone(match_landmark(self.PP_CAPTION_MERGED))

    def test_q1_lines_helper_recovers_caption_merged(self):
        # The candidate resolution (whole-text then per-line): finds it.
        m = match_landmark_lines(self.PP_CAPTION_MERGED)
        self.assertIsNotNone(m)
        self.assertEqual(m.ordinal, 2)

    def test_q1_lines_helper_still_prefers_whole_text_for_dq(self):
        m = match_landmark_lines("CHAPTER I.\nWHICH TREATS OF THE CHARACTER")
        self.assertEqual(m.ordinal, 1)
        self.assertTrue(m.trailing_title.startswith("WHICH TREATS"))

    def test_q2_fused_heading_fails_per_spec(self):
        # P&P's "CHAPTERXXVII." — §2.1 requires whitespace after the
        # section word. Two of P&P's 61 are fused; the 61/61 acceptance
        # row needs a ruling (no-space variant vs 59/61 + warning).
        self.assertIsNone(match_landmark("CHAPTERXXVII."))
        self.assertIsNone(match_landmark_lines("CHAPTERXXVII."))


if __name__ == "__main__":
    unittest.main()
