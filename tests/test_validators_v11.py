"""Iteration 6 tests — §4 validators: V-001 v2 part scoping, V-005
zero-structure, V-003 demotion to observational."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.rules.validation import (
    V001_ChapterNumberContinuity,
    V003_SpaceLossHeuristic,
    V005_ZeroStructure,
)


def CH(bid, n, subtype=None):
    b = {"id": bid, "type": "heading", "heading_level": 2,
         "role": "chapter_heading", "chapter_number": n,
         "chapter_title": f"Chapter {n}",
         "spans": [{"text": f"CHAPTER {n}", "marks": []}]}
    if subtype:
        b["landmark_subtype"] = subtype
        b["chapter_number"] = None
    return b


def PART(bid, title):
    return {"id": bid, "type": "heading", "heading_level": 2,
            "role": "part_divider", "part_number": None, "part_title": title,
            "spans": [{"text": title, "marks": []}]}


def BODY(bid, text="Plain body text here."):
    return {"id": bid, "type": "paragraph", "role": "body_paragraph",
            "spans": [{"text": text, "marks": []}]}


class TestV001PartScoping(unittest.TestCase):
    def test_frankenstein_shape_silent(self):
        """Numbering restarts per volume — no warning."""
        blocks = []
        for v in range(3):
            blocks.append(PART(f"vol{v}", "Frankenstein Volume Page"))
            blocks += [CH(f"c{v}_{n}", n) for n in range(1, 8)]
        ctx = RuleContext(blocks=blocks)
        V001_ChapterNumberContinuity().run(ctx)
        self.assertEqual(ctx.warnings, [])

    def test_dq_implicit_first_part_silent(self):
        """Chapters before the only part_divider form the implicit
        first part (DQ Amendment 2)."""
        blocks = [CH(f"a{n}", n) for n in range(1, 6)]
        blocks.append(PART("vol2", "Volume II"))
        blocks += [CH(f"b{n}", n) for n in range(1, 8)]
        ctx = RuleContext(blocks=blocks)
        V001_ChapterNumberContinuity().run(ctx)
        self.assertEqual(ctx.warnings, [])

    def test_gap_within_scope_flagged_with_scope_label(self):
        blocks = [PART("p1", "Part One")]
        blocks += [CH(f"c{n}", n) for n in (1, 2, 4)]
        ctx = RuleContext(blocks=blocks)
        V001_ChapterNumberContinuity().run(ctx)
        self.assertEqual(len(ctx.warnings), 1)
        self.assertIn("Part One", ctx.warnings[0]["detail"])
        self.assertIn("gap", ctx.warnings[0]["detail"])

    def test_unnumbered_landmarks_excluded(self):
        blocks = [CH("pro", None, subtype="prologue")]
        blocks += [CH(f"c{n}", n) for n in (1, 2, 3)]
        blocks.append(CH("epi", None, subtype="epilogue"))
        ctx = RuleContext(blocks=blocks)
        V001_ChapterNumberContinuity().run(ctx)
        self.assertEqual(ctx.warnings, [])


class TestV005ZeroStructure(unittest.TestCase):
    def _bulk_body(self, blocks_n=60, words_per=100):
        text = "word " * words_per
        return [BODY(f"b{i}", text) for i in range(blocks_n)]

    def test_fires_on_structureless_bulk(self):
        ctx = RuleContext(blocks=self._bulk_body())
        V005_ZeroStructure().run(ctx)
        self.assertEqual(len(ctx.warnings), 1)
        self.assertEqual(ctx.warnings[0]["rule"], "V-005")

    def test_silent_with_any_landmark(self):
        blocks = self._bulk_body()
        blocks.insert(0, CH("c1", 1))
        ctx = RuleContext(blocks=blocks)
        V005_ZeroStructure().run(ctx)
        self.assertEqual(ctx.warnings, [])

    def test_silent_below_thresholds(self):
        ctx = RuleContext(blocks=self._bulk_body(blocks_n=40))
        V005_ZeroStructure().run(ctx)
        self.assertEqual(ctx.warnings, [])
        ctx2 = RuleContext(blocks=self._bulk_body(blocks_n=60, words_per=10))
        V005_ZeroStructure().run(ctx2)
        self.assertEqual(ctx2.warnings, [])


class TestV003Observational(unittest.TestCase):
    def test_findings_go_to_extras_not_warnings(self):
        rule = V003_SpaceLossHeuristic()
        if rule._word_frequency is None:
            self.skipTest("wordfreq not installed")
        blocks = [BODY("b1", "He looked at theweather and left.")]
        ctx = RuleContext(blocks=blocks)
        rule.run(ctx)
        self.assertEqual(ctx.warnings, [])
        obs = ctx.extras.get("v003_observations", [])
        self.assertEqual(len(obs), 1)
        self.assertIn("theweather", obs[0]["detail"])

    def test_missing_backend_is_not_a_fault(self):
        rule = V003_SpaceLossHeuristic()
        rule._word_frequency = None  # simulate missing wordfreq
        ctx = RuleContext(blocks=[BODY("b1")])
        rule.run(ctx)
        self.assertEqual(ctx.rule_faults, [])
        self.assertEqual(ctx.warnings, [])
        self.assertIn("v003_skipped", ctx.extras)


if __name__ == "__main__":
    unittest.main()
