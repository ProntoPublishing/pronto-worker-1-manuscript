"""Iteration 7 tests — N-005 license-boilerplate strip and the Doc 22
v1.0.3 pStyle→style_tags synthesis table."""
from __future__ import annotations
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.rules.base import RuleContext
from lib.rules.normalization import N005_StripLicenseBoilerplate
from lib.cir import extract_docx


def H(bid, level, text):
    return {"id": bid, "type": "heading", "heading_level": level,
            "spans": [{"text": text, "marks": []}]}


def P(bid, text):
    return {"id": bid, "type": "paragraph",
            "spans": [{"text": text, "marks": []}]}


class TestN005(unittest.TestCase):
    def test_gutenberg_preamble_and_license_stripped(self):
        blocks = [
            H("g1", 2, "The Project Gutenberg eBook of Pride and Prejudice"),
            P("g2", "This ebook is for the use of anyone anywhere."),
            P("g3", "Title: Pride and Prejudice"),
            H("c1", 2, "CHAPTER I."),
            P("b1", "It is a truth universally acknowledged."),
            H("gl1", 2, "*** END OF THE PROJECT GUTENBERG EBOOK ***"),
            P("gl2", "Updated editions will replace the previous one."),
            H("gl3", 2, "Section 1. General Terms of Use"),
            P("gl4", "More license text."),
        ]
        ctx = RuleContext(blocks=blocks)
        N005_StripLicenseBoilerplate().run(ctx)
        ids = [b["id"] for b in ctx.blocks]
        self.assertEqual(ids, ["c1", "b1"])
        entries = [r for r in ctx.applied_rules if r["rule"] == "N-005"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["count"], 7)
        self.assertEqual(entries[0]["version"], "v1")

    def test_negation_guard_walks_through_license_headings(self):
        """License headings inside the boilerplate range must not stop
        the forward walk."""
        blocks = [
            H("g1", 2, "*** START OF THE PROJECT GUTENBERG EBOOK ***"),
            P("g2", "Preamble."),
            H("g3", 2, "Section 2. Information about the Mission"),
            P("g4", "Mission text."),
            H("c1", 2, "CHAPTER I."),
            P("b1", "Real content."),
        ]
        ctx = RuleContext(blocks=blocks)
        N005_StripLicenseBoilerplate().run(ctx)
        self.assertEqual([b["id"] for b in ctx.blocks], ["c1", "b1"])

    def test_author_supplied_gutenberg_mention_kept(self):
        """The canon negative fixture shape: an author writing ABOUT
        Gutenberg mid-paragraph must survive (patterns are ^-anchored)."""
        blocks = [
            H("c1", 2, "CHAPTER I."),
            P("b1", "She discovered the Project Gutenberg archive that "
                     "winter and read everything in it."),
        ]
        ctx = RuleContext(blocks=blocks)
        N005_StripLicenseBoilerplate().run(ctx)
        self.assertEqual(len(ctx.blocks), 2)
        self.assertEqual(ctx.applied_rules, [])

    def test_matching_paragraph_removed_alone(self):
        blocks = [
            P("g1", "This ebook is for the use of anyone anywhere."),
            P("b1", "Actual opening paragraph."),
        ]
        ctx = RuleContext(blocks=blocks)
        N005_StripLicenseBoilerplate().run(ctx)
        self.assertEqual([b["id"] for b in ctx.blocks], ["b1"])
        self.assertEqual(ctx.applied_rules[0]["count"], 1)


_DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>
   <w:r><w:t>Pride and Prejudice</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Author"/></w:pPr>
   <w:r><w:t>Jane Austen</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Title"/><w:jc w:val="center"/></w:pPr>
   <w:r><w:t>Explicitly Centered Title</w:t></w:r></w:p>
  <w:p><w:r><w:t>Plain body paragraph.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="BlockText"/></w:pPr>
   <w:r><w:t>A graft is a wound you make on purpose.</w:t></w:r></w:p>
 </w:body>
</w:document>
"""

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""


class TestPStyleSynthesis(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.docx = Path(self._tmp.name) / "synth.docx"
        with zipfile.ZipFile(self.docx, "w") as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("word/document.xml", _DOC_XML)

    def tearDown(self):
        self._tmp.cleanup()

    def test_synthesis_table(self):
        blocks, _ = extract_docx(self.docx)
        texts = {"".join(s["text"] for s in b["spans"]): b for b in blocks}

        title = texts["Pride and Prejudice"]
        self.assertIn("centered", title.get("style_tags") or [])
        self.assertIn("large_font", title.get("style_tags") or [])

        author = texts["Jane Austen"]
        self.assertIn("centered", author.get("style_tags") or [])
        self.assertNotIn("large_font", author.get("style_tags") or [])

        body = texts["Plain body paragraph."]
        self.assertNotIn("centered", body.get("style_tags") or [])

    def test_blocktext_maps_to_blockquote(self):
        """5.3.1: pandoc's BlockText paragraph style is a blockquote
        (Book 18 epigraphs arrived as plain body prose without it)."""
        blocks, _ = extract_docx(self.docx)
        bq = [b for b in blocks if b["type"] == "blockquote"]
        self.assertEqual(len(bq), 1)
        self.assertIn("wound you make on purpose",
                      "".join(s["text"] for s in bq[0]["spans"]))

    def test_dedupe_merge_with_explicit_attributes(self):
        blocks, _ = extract_docx(self.docx)
        texts = {"".join(s["text"] for s in b["spans"]): b for b in blocks}
        explicit = texts["Explicitly Centered Title"]
        tags = explicit.get("style_tags") or []
        self.assertEqual(tags.count("centered"), 1, f"dupes in {tags}")
        self.assertIn("large_font", tags)


if __name__ == "__main__":
    unittest.main()
