"""Iteration 5 tests — C-006 chapter_subtitle promotion (§2.3) and the
C-003 v2 title-page redesign (§3 + Q3 mechanism attribution)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.rules.classification import (
    C001_LandmarkClassification,
    C002_StructuralPartDetection,
    C003_TitlePage,
    C006_ChapterSubtitle,
)


def H(bid, level, text):
    return {"id": bid, "type": "heading", "heading_level": level,
            "spans": [{"text": text, "marks": []}]}


def P(bid, text, tags=()):
    return {"id": bid, "type": "paragraph", "style_tags": list(tags),
            "spans": [{"text": text, "marks": []}]}


def run_classify(blocks, rules=None):
    ctx = RuleContext(blocks=blocks)
    for rule in rules or (
        C001_LandmarkClassification(),
        C002_StructuralPartDetection(),
        C006_ChapterSubtitle(),
        C003_TitlePage(),
    ):
        rule.run(ctx)
    return ctx


class TestC006CarolShape(unittest.TestCase):
    """Stave names at H4 under H2 staves → chapter_subtitle."""

    def _blocks(self):
        blocks = []
        names = ["MARLEY'S GHOST.", "THE FIRST OF THE THREE SPIRITS."]
        for i, (w, name) in enumerate(zip(["ONE", "TWO"], names), 1):
            blocks.append(H(f"s{i}", 2, f"STAVE {w}."))
            blocks.append(H(f"n{i}", 4, name))
            blocks.append(P(f"b{i}", "Marley was dead: to begin with. " * 10))
        return blocks

    def test_stave_names_promoted(self):
        ctx = run_classify(self._blocks())
        by_id = {b["id"]: b for b in ctx.blocks}
        self.assertEqual(by_id["n1"]["role"], "chapter_subtitle")
        self.assertEqual(by_id["n2"]["role"], "chapter_subtitle")
        self.assertIn("subordinate heading level",
                      " ".join(by_id["n1"]["classification_notes"]))

    def test_body_not_promoted(self):
        ctx = run_classify(self._blocks())
        by_id = {b["id"]: b for b in ctx.blocks}
        self.assertIsNone(by_id["b1"].get("role"))


class TestC006HatchShape(unittest.TestCase):
    """Italic subtitles under paragraph-stratum chapters."""

    def _blocks(self):
        blocks = []
        for i, w in enumerate(["ONE", "TWO", "THREE"], 1):
            blocks.append(P(f"ch{i}", f"CHAPTER {w}", ("centered", "bold")))
            blocks.append(P(f"sub{i}", "A quiet beginning", ("italic",)))
            blocks.append(P(f"b{i}", "Body text follows. " * 20))
        return blocks

    def test_italic_subtitles_promoted(self):
        ctx = run_classify(self._blocks())
        subs = [b for b in ctx.blocks if b.get("role") == "chapter_subtitle"]
        self.assertEqual([b["id"] for b in subs], ["sub1", "sub2", "sub3"])


class TestC006Guards(unittest.TestCase):
    def test_scene_break_marker_not_promoted(self):
        blocks = [
            H("c1", 2, "CHAPTER I."),
            P("sb", "* * *", ("centered",)),
            H("c2", 2, "CHAPTER II."),
        ]
        ctx = run_classify(blocks)
        sb = next(b for b in ctx.blocks if b["id"] == "sb")
        self.assertIsNone(sb.get("role"))

    def test_position_alone_never_promotes(self):
        blocks = [
            H("c1", 2, "CHAPTER I."),
            P("plain", "A short plain line"),  # short but no style gate
            H("c2", 2, "CHAPTER II."),
        ]
        ctx = run_classify(blocks)
        plain = next(b for b in ctx.blocks if b["id"] == "plain")
        self.assertIsNone(plain.get("role"))

    def test_empty_line_skipped_for_adjacency(self):
        blocks = [
            H("c1", 2, "CHAPTER I."),
            {"id": "e1", "type": "paragraph", "style_tags": ["empty_line"],
             "spans": [{"text": "", "marks": []}]},
            P("sub", "The Subtitle", ("italic",)),
            P("b", "Body. " * 60),
            H("c2", 2, "CHAPTER II."),
        ]
        ctx = run_classify(blocks)
        sub = next(b for b in ctx.blocks if b["id"] == "sub")
        self.assertEqual(sub.get("role"), "chapter_subtitle")


class TestC003TagPath(unittest.TestCase):
    """Hatch/P&P-with-synthesis shape: centered+large_font cluster."""

    def _blocks(self):
        return [
            P("t", "The Hatch List", ("centered", "large_font")),
            P("a", "Claude Cumberbatch", ("centered",)),
            P("b1", "Body paragraph one. " * 15),
            P("b2", "Body paragraph two. " * 15),
        ]

    def test_meta_extracted_via_tag_path(self):
        ctx = run_classify(self._blocks(), rules=(C003_TitlePage(),))
        self.assertEqual(ctx.manuscript_meta["title"], "The Hatch List")
        self.assertEqual(ctx.manuscript_meta["author"], "Claude Cumberbatch")
        self.assertEqual(ctx.extras["c003_mechanism"], "tag path")

    def test_mechanism_noted_on_blocks(self):
        ctx = run_classify(self._blocks(), rules=(C003_TitlePage(),))
        t = next(b for b in ctx.blocks if b["id"] == "t")
        notes = " ".join(t["classification_notes"])
        self.assertIn("qualified via", notes)
        self.assertIn("tag:centered", notes)


class TestC003PositionShapePath(unittest.TestCase):
    """Frankenstein/Carol shape: heading-typed cluster, zero tags —
    the v1 killer, now qualified via level+position."""

    def _blocks(self):
        return [
            H("t", 1, "FRANKENSTEIN; OR, THE MODERN PROMETHEUS"),
            P("a", "By Mary Wollstonecraft Shelley"),
            P("b1", "I am by birth a Genevese, and my family is one of. " * 8),
            P("b2", "Distinguished of that republic and my ancestors. " * 8),
        ]

    def test_heading_typed_cluster_accepted(self):
        ctx = run_classify(self._blocks(), rules=(C003_TitlePage(),))
        self.assertIsNotNone(ctx.manuscript_meta)
        self.assertTrue(
            ctx.manuscript_meta["title"].startswith("FRANKENSTEIN"))
        self.assertEqual(ctx.extras["c003_mechanism"], "position/shape path")

    def test_byline_adjacency_exception(self):
        ctx = run_classify(self._blocks(), rules=(C003_TitlePage(),))
        self.assertEqual(ctx.manuscript_meta["author"],
                         "By Mary Wollstonecraft Shelley")


class TestC003Bounds(unittest.TestCase):
    def test_deep_centered_block_not_title_page(self):
        # Sustained body run ends the window before the deep block.
        blocks = [
            H("t", 1, "REAL TITLE"),
            P("b1", "Long body paragraph. " * 15),
            P("b2", "Another long body paragraph. " * 15),
            P("deep", "A Centered Interlude", ("centered", "large_font")),
        ]
        ctx = run_classify(blocks, rules=(C003_TitlePage(),))
        deep = next(b for b in ctx.blocks if b["id"] == "deep")
        self.assertIsNone(deep.get("role"))

    def test_no_qualifiers_no_meta(self):
        blocks = [P("b1", "Plain start. " * 20), P("b2", "More body. " * 20)]
        ctx = run_classify(blocks, rules=(C003_TitlePage(),))
        self.assertIsNone(ctx.manuscript_meta)


if __name__ == "__main__":
    unittest.main()
