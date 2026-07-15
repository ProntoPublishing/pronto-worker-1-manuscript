"""Iteration 1 tests — shared ordinal parser (amendment spec v2.2 §2.1).

Corpus anchors: LXXIV (DQ Vol II's last chapter), XXVII (P&P's fused-
heading chapter), spelled ordinals (Hatch "ONE"…"NINE", Carol "ONE"…"FIVE").
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.ordinals import (
    parse_arabic,
    parse_roman,
    parse_word_ordinal,
    parse_ordinal,
    detect_ordinal_style,
)


class TestParseArabic(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_arabic("12"), 12)
        self.assertEqual(parse_arabic(" 7 "), 7)

    def test_rejects(self):
        self.assertIsNone(parse_arabic("0"))
        self.assertIsNone(parse_arabic("-3"))
        self.assertIsNone(parse_arabic("3.5"))
        self.assertIsNone(parse_arabic("IV"))
        self.assertIsNone(parse_arabic(""))


class TestParseRoman(unittest.TestCase):
    def test_corpus_anchors(self):
        self.assertEqual(parse_roman("LXXIV"), 74)   # DQ Vol II final chapter
        self.assertEqual(parse_roman("XXVII"), 27)   # P&P fused-heading chapter
        self.assertEqual(parse_roman("LII"), 52)     # DQ Vol I final chapter
        self.assertEqual(parse_roman("LXI"), 61)     # P&P final chapter

    def test_subtractive_and_case(self):
        self.assertEqual(parse_roman("IV"), 4)
        self.assertEqual(parse_roman("IX"), 9)
        self.assertEqual(parse_roman("xl"), 40)
        self.assertEqual(parse_roman("MCMXCIV"), 1994)

    def test_non_canonical_is_permissive(self):
        self.assertEqual(parse_roman("IIII"), 4)

    def test_rejects(self):
        self.assertIsNone(parse_roman("ONE"))
        self.assertIsNone(parse_roman("I2"))
        self.assertIsNone(parse_roman(""))
        self.assertIsNone(parse_roman("chapter"))


class TestParseWordOrdinal(unittest.TestCase):
    def test_units_teens_tens(self):
        self.assertEqual(parse_word_ordinal("ONE"), 1)      # Hatch/Carol
        self.assertEqual(parse_word_ordinal("NINE"), 9)     # Hatch final
        self.assertEqual(parse_word_ordinal("FIVE"), 5)     # Carol final stave
        self.assertEqual(parse_word_ordinal("Twelve"), 12)
        self.assertEqual(parse_word_ordinal("ninety"), 90)

    def test_compounds(self):
        self.assertEqual(parse_word_ordinal("TWENTY-ONE"), 21)
        self.assertEqual(parse_word_ordinal("twenty one"), 21)
        self.assertEqual(parse_word_ordinal("FORTY-SEVEN"), 47)

    def test_rejects(self):
        self.assertIsNone(parse_word_ordinal("ONCE"))
        self.assertIsNone(parse_word_ordinal("TEN-ONE"))
        self.assertIsNone(parse_word_ordinal("HUNDRED"))
        self.assertIsNone(parse_word_ordinal(""))


class TestParseOrdinalDispatch(unittest.TestCase):
    def test_each_system(self):
        self.assertEqual(parse_ordinal("3"), 3)
        self.assertEqual(parse_ordinal("XXVII"), 27)
        self.assertEqual(parse_ordinal("SEVEN"), 7)

    def test_style_detection_matches_dispatch(self):
        self.assertEqual(detect_ordinal_style("3"), "arabic")
        self.assertEqual(detect_ordinal_style("LXXIV"), "roman")
        self.assertEqual(detect_ordinal_style("ONE"), "words")
        self.assertIsNone(detect_ordinal_style("Eidolons"))

    def test_single_letter_roman_words_no_collision(self):
        # "I" is roman 1; no English number word shares the roman charset.
        self.assertEqual(parse_ordinal("I"), 1)
        self.assertEqual(detect_ordinal_style("I"), "roman")

    def test_none_cases(self):
        self.assertIsNone(parse_ordinal(""))
        self.assertIsNone(parse_ordinal("   "))
        self.assertIsNone(parse_ordinal("the First"))


if __name__ == "__main__":
    unittest.main()
