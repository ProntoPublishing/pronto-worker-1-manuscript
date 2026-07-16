"""Rules 1.2 tests — Gate 2 rulings Q1 (pattern-only promotion, C-008 +
V-006) and Q3 (source-TOC detection, C-007). 2026-07-16.

Book 16 (test 21's Pandoc plain-text Frankenstein) is the defining
shape: zero heading structure, zero style tags, whole-paragraph
"Letter N" / "Chapter N" openers with long bodies between them, and a
one-block inline source contents list.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.rules.classification import (
    C001_LandmarkClassification,
    C007_SourceTocDetection,
    C008_PatternOnlyLandmarks,
    PATTERN_ONLY_NOTE,
)
from lib.rules.validation import V006_PatternOnlyPromotion


def para(bid, text):
    return {"id": bid, "type": "paragraph",
            "spans": [{"text": text, "marks": []}]}


def body(bid, words=80):
    return para(bid, "lorem ipsum " * (words // 2))


def run_classify(blocks, with_c001=True):
    ctx = RuleContext(blocks=blocks)
    C007_SourceTocDetection().run(ctx)
    if with_c001:
        C001_LandmarkClassification().run(ctx)
    C008_PatternOnlyLandmarks().run(ctx)
    return ctx


def zero_structure_book(n_letters=4, n_chapters=24):
    """Book-16-shaped synthetic: openers as plain whole paragraphs,
    long bodies between."""
    blocks = []
    i = 0
    for k in range(1, n_letters + 1):
        blocks.append(para(f"b_{i:06d}", f"Letter {k}")); i += 1
        blocks.append(body(f"b_{i:06d}")); i += 1
        blocks.append(body(f"b_{i:06d}")); i += 1
    for k in range(1, n_chapters + 1):
        blocks.append(para(f"b_{i:06d}", f"Chapter {k}")); i += 1
        blocks.append(body(f"b_{i:06d}")); i += 1
        blocks.append(body(f"b_{i:06d}")); i += 1
    return blocks


class TestC008PatternOnly(unittest.TestCase):

    def test_book16_shape_promotes_all_classes(self):
        blocks = zero_structure_book()
        ctx = run_classify(blocks)
        chapters = [b for b in blocks if b.get("role") == "chapter_heading"]
        self.assertEqual(len(chapters), 28)
        letters = [b for b in chapters
                   if b["chapter_title"].startswith("Letter")]
        self.assertEqual(len(letters), 4)
        self.assertTrue(all(
            any(PATTERN_ONLY_NOTE in n for n in b["classification_notes"])
            for b in chapters))

    def test_mid_prose_mention_is_not_a_candidate(self):
        blocks = zero_structure_book()
        blocks.insert(10, para("b_900000",
                               "As I said in Chapter 1, the weather held. "
                               "We spoke of it for days afterward."))
        ctx = run_classify(blocks)
        self.assertIsNone(blocks[10].get("role"))
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 28)

    def test_multiplicity_below_three_not_promoted(self):
        blocks = []
        for k in (1, 2):
            blocks.append(para(f"b_{k:06d}", f"Chapter {k}"))
            blocks.append(body(f"b_x{k:06d}"))
        ctx = run_classify(blocks)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 0)

    def test_incoherent_sequence_not_promoted(self):
        blocks = []
        for i, k in enumerate((1, 5, 3, 9)):
            blocks.append(para(f"b_{i:06d}", f"Chapter {k}"))
            blocks.append(body(f"b_x{i:06d}"))
        ctx = run_classify(blocks)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 0)

    def test_restart_requires_part_pivot(self):
        # Chapter 1..3, Volume 2, Chapter 1..3 → restart allowed, parts
        # promoted as pivot.
        blocks = []
        i = 0
        for k in (1, 2, 3):
            blocks.append(para(f"b_{i:06d}", f"Chapter {k}")); i += 1
            blocks.append(body(f"b_{i:06d}")); i += 1
        blocks.append(para(f"b_{i:06d}", "Volume 2")); i += 1
        blocks.append(body(f"b_{i:06d}")); i += 1
        for k in (1, 2, 3):
            blocks.append(para(f"b_{i:06d}", f"Chapter {k}")); i += 1
            blocks.append(body(f"b_{i:06d}")); i += 1
        ctx = run_classify(blocks)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 6)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "part_divider"), 1)

    def test_restart_without_pivot_not_promoted(self):
        blocks = []
        i = 0
        for k in (1, 2, 3, 1, 2, 3):
            blocks.append(para(f"b_{i:06d}", f"Chapter {k}")); i += 1
            blocks.append(body(f"b_{i:06d}")); i += 1
        ctx = run_classify(blocks)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 0)

    def test_adjacent_cluster_is_source_toc_not_landmarks(self):
        # A bare cluster (no intervening bodies) that C-007's early
        # window missed — C-008's dispersion belt catches it.
        blocks = [body("b_000000", words=600)]  # push past C-007's window? no —
        # C-007 window is block-count based; use position > 80 blocks.
        blocks = [body(f"b_{i:06d}", words=30) for i in range(85)]
        cluster_start = len(blocks)
        for k in range(1, 6):
            blocks.append(para(f"b_9{k:05d}", f"Chapter {k}"))
        ctx = run_classify(blocks)
        cluster = blocks[cluster_start:]
        self.assertTrue(all(b.get("role") == "structural" for b in cluster))
        self.assertTrue(all(b.get("subtype") == "source_toc" for b in cluster))
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 0)

    def test_stays_off_when_visual_path_found_landmarks(self):
        # A styled doc: chapter headings at H2 — dominant stratum exists,
        # C-008 must not touch the plain-paragraph pattern matches.
        blocks = []
        for k in (1, 2, 3):
            blocks.append({"id": f"b_{k:06d}", "type": "heading",
                           "heading_level": 2,
                           "spans": [{"text": f"Chapter {k}", "marks": []}]})
            blocks.append(body(f"b_x{k:06d}"))
        blocks.append(para("b_777777", "Chapter 99"))  # plain paragraph
        blocks.append(body("b_777778"))
        ctx = run_classify(blocks)
        self.assertIsNone(blocks[-2].get("role"))
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 3)

    def test_promotion_works_without_source_toc(self):
        # Ruling: TOC is a confidence booster, never a prerequisite.
        blocks = zero_structure_book(n_letters=0, n_chapters=5)
        ctx = run_classify(blocks)
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 5)


class TestC007SourceToc(unittest.TestCase):

    def test_shape_a_inline_block(self):
        entries = " ".join(
            [f"Letter {k}" for k in range(1, 5)]
            + [f"Chapter {k}" for k in range(1, 25)])
        blocks = [
            para("b_000001", "CONTENTS"),
            para("b_000002", entries),
            body("b_000003"),
        ]
        ctx = RuleContext(blocks=blocks)
        C007_SourceTocDetection().run(ctx)
        self.assertEqual(blocks[1]["role"], "structural")
        self.assertEqual(blocks[1]["subtype"], "source_toc")
        self.assertEqual(blocks[0]["role"], "structural")  # label joins
        self.assertEqual(len(ctx.extras["source_toc_entries"]), 28)

    def test_shape_b_consecutive_run(self):
        blocks = [para("b_000000", "Table of Contents")]
        blocks += [para(f"b_{k:06d}", f"Chapter {k}") for k in range(1, 8)]
        blocks.append(body("b_000099"))
        ctx = RuleContext(blocks=blocks)
        C007_SourceTocDetection().run(ctx)
        self.assertTrue(all(
            b["role"] == "structural" for b in blocks[1:8]))
        self.assertEqual(blocks[0]["role"], "structural")
        self.assertIsNone(blocks[-1].get("role"))

    def test_prose_mentioning_chapters_not_detected(self):
        blocks = [para(
            "b_000001",
            "In chapter 1 we met the crew, and by chapter 2 the storm had "
            "come; chapter 3 finally brought them home to the island where "
            "everything began, after months of drifting and doubt.")]
        ctx = RuleContext(blocks=blocks)
        C007_SourceTocDetection().run(ctx)
        self.assertIsNone(blocks[0].get("role"))

    def test_late_toc_outside_window_not_detected(self):
        blocks = [body(f"b_{i:06d}") for i in range(100)]
        entries = " ".join(f"Chapter {k}" for k in range(1, 10))
        blocks.append(para("b_999999", entries))
        ctx = RuleContext(blocks=blocks)
        C007_SourceTocDetection().run(ctx)
        self.assertIsNone(blocks[-1].get("role"))

    def test_end_to_end_with_promotion(self):
        # Fake TOC (shape b) + real dispersed openers: TOC suppressed,
        # landmarks promoted, count correct — the Book 17 shape.
        blocks = [para("b_000000", "CONTENTS")]
        blocks += [para(f"b_1{k:05d}", f"Chapter {k}") for k in range(1, 6)]
        blocks.append(body("b_200000"))
        i = 0
        for k in range(1, 6):
            blocks.append(para(f"b_3{i:05d}", f"Chapter {k}")); i += 1
            blocks.append(body(f"b_3{i:05d}")); i += 1
        ctx = run_classify(blocks)
        toc_blocks = [b for b in blocks if b.get("subtype") == "source_toc"]
        self.assertEqual(len(toc_blocks), 6)  # label + 5 entries
        self.assertEqual(
            sum(1 for b in blocks if b.get("role") == "chapter_heading"), 5)


class TestC004HeadH1Guard(unittest.TestCase):
    """Rules 1.2 regression guard: with pattern-only chapters giving
    C-004 a cutoff, the document-head H1 (the book title in Book 16's
    shape) must be left for C-003 — not claimed as generic front
    matter, which killed manuscript_meta and H-001."""

    def _blocks(self, head_text):
        blocks = [{"id": "b_000001", "type": "heading", "heading_level": 1,
                   "spans": [{"text": head_text, "marks": []}]}]
        blocks += zero_structure_book(n_letters=0, n_chapters=3)
        return blocks

    def test_unrecognized_head_h1_left_for_c003(self):
        from lib.rules.classification import C004_FrontMatter
        blocks = self._blocks("Frankenstein")
        ctx = run_classify(blocks)
        C004_FrontMatter().run(ctx)
        self.assertIsNone(blocks[0].get("role"))

    def test_recognized_label_still_classifies(self):
        from lib.rules.classification import C004_FrontMatter
        blocks = self._blocks("Preface")
        ctx = run_classify(blocks)
        C004_FrontMatter().run(ctx)
        self.assertEqual(blocks[0].get("role"), "front_matter")
        self.assertEqual(blocks[0].get("subtype"), "preface")


class TestV006(unittest.TestCase):

    def test_fires_on_pattern_only_promotion(self):
        blocks = zero_structure_book(n_letters=4, n_chapters=5)
        ctx = run_classify(blocks)
        V006_PatternOnlyPromotion().run(ctx)
        v006 = [w for w in ctx.warnings if w["rule"] == "V-006"]
        self.assertEqual(len(v006), 1)
        self.assertEqual(v006[0]["severity"], "medium")
        self.assertIn("9 landmark(s)", v006[0]["detail"])
        self.assertIn("letter", v006[0]["detail"])
        self.assertIn("chapter", v006[0]["detail"])

    def test_silent_on_visual_path_landmarks(self):
        blocks = []
        for k in (1, 2, 3):
            blocks.append({"id": f"b_{k:06d}", "type": "heading",
                           "heading_level": 2,
                           "spans": [{"text": f"Chapter {k}", "marks": []}]})
            blocks.append(body(f"b_x{k:06d}"))
        ctx = run_classify(blocks)
        V006_PatternOnlyPromotion().run(ctx)
        self.assertEqual(
            [w for w in ctx.warnings if w["rule"] == "V-006"], [])


if __name__ == "__main__":
    unittest.main()
