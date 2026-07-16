"""Manual-page-break observation (2026-07-16, V-007 tripwire plumbing).

The extractor records a manual page break — a lone w:br w:type=page
paragraph (Word Insert → Page Break, python-docx add_page_break) or a
w:pPr/w:pageBreakBefore property — as force_page_break: true on the
first CONTENT block that follows the break. No new blocks are emitted
(block counts and indices are unchanged relative to 5.2.0-a1, so
C-003's contiguity arithmetic is untouched); the mid-paragraph inline
split that already emits explicit page_break blocks is unchanged.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.cir import extract_docx
from lib.rules.base import RuleContext
from lib.rules.normalization import N001_CollapseDoubleSpaces

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_DOC_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
{body}
 </w:body>
</w:document>
"""


def _p(text):
    return f"  <w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _empty_p():
    return "  <w:p/>"


def _lone_break_p():
    return "  <w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def _pbb_p(text):
    return (
        "  <w:p><w:pPr><w:pageBreakBefore/></w:pPr>"
        f"<w:r><w:t>{text}</w:t></w:r></w:p>"
    )


def _text_of(block):
    return "".join(s["text"] for s in block.get("spans") or [])


class _DocxCase(unittest.TestCase):
    def _extract(self, *body_lines):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        docx = Path(tmp.name) / "t.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr(
                "word/document.xml",
                _DOC_TEMPLATE.format(body="\n".join(body_lines)),
            )
        blocks, _ = extract_docx(docx)
        return blocks


class TestLoneBreakParagraph(_DocxCase):
    def test_flag_lands_on_next_content_block(self):
        blocks = self._extract(
            _p("Title page text."),
            _lone_break_p(),
            _p("Dedication text."),
        )
        by_text = {_text_of(b): b for b in blocks}
        self.assertNotIn("force_page_break", by_text["Title page text."])
        self.assertTrue(by_text["Dedication text."].get("force_page_break"))

    def test_flag_skips_intervening_empty_lines(self):
        """Book 15's exact shape: break paragraph, then a run of empty
        paragraphs, then the dedication. The flag must land on the
        dedication (a content block), never on an empty_line paragraph
        (N-001's run collapse would silently drop it there)."""
        blocks = self._extract(
            _p("Naomi Cartwright"),
            _lone_break_p(),
            _empty_p(), _empty_p(), _empty_p(),
            _p("For my sister, who stayed."),
        )
        for b in blocks:
            tags = b.get("style_tags") or []
            if "empty_line" in tags:
                self.assertNotIn("force_page_break", b)
        by_text = {_text_of(b): b for b in blocks}
        self.assertTrue(
            by_text["For my sister, who stayed."].get("force_page_break")
        )

    def test_no_new_blocks_emitted(self):
        """Tripwire plumbing must not shift block indices: the lone-break
        paragraph still emits exactly its empty_line phantom, as in
        5.2.0-a1."""
        with_break = self._extract(
            _p("A"), _lone_break_p(), _p("B"),
        )
        without_break = self._extract(
            _p("A"), _empty_p(), _p("B"),
        )
        self.assertEqual(len(with_break), len(without_break))
        self.assertEqual(
            [b["type"] for b in with_break],
            [b["type"] for b in without_break],
        )

    def test_flag_survives_n001_empty_run_collapse(self):
        blocks = self._extract(
            _p("Author Name"),
            _empty_p(),
            _lone_break_p(),
            _empty_p(), _empty_p(),
            _p("Dedication."),
        )
        ctx = RuleContext(blocks=blocks)
        N001_CollapseDoubleSpaces().run(ctx)
        by_text = {_text_of(b): b for b in ctx.blocks}
        self.assertTrue(by_text["Dedication."].get("force_page_break"))

    def test_break_at_end_of_document_is_dropped(self):
        blocks = self._extract(_p("The end."), _lone_break_p())
        self.assertFalse(any(b.get("force_page_break") for b in blocks))


class TestPageBreakBeforeProperty(_DocxCase):
    def test_flag_lands_on_own_block(self):
        """Hatch's shape: pageBreakBefore on each chapter paragraph."""
        blocks = self._extract(
            _p("Body before."),
            _pbb_p("CHAPTER TWO"),
        )
        by_text = {_text_of(b): b for b in blocks}
        self.assertNotIn("force_page_break", by_text["Body before."])
        self.assertTrue(by_text["CHAPTER TWO"].get("force_page_break"))

    def test_explicit_false_val_is_ignored(self):
        blocks = self._extract(
            "  <w:p><w:pPr><w:pageBreakBefore w:val=\"false\"/></w:pPr>"
            "<w:r><w:t>Not a break.</w:t></w:r></w:p>",
        )
        self.assertFalse(any(b.get("force_page_break") for b in blocks))


class TestInlineSplitUnchanged(_DocxCase):
    def test_mid_paragraph_break_still_emits_page_break_block(self):
        blocks = self._extract(
            "  <w:p><w:r><w:t>before</w:t></w:r>"
            "<w:r><w:br w:type=\"page\"/></w:r>"
            "<w:r><w:t>after</w:t></w:r></w:p>",
        )
        types = [b["type"] for b in blocks]
        self.assertIn("page_break", types)
        self.assertFalse(any(b.get("force_page_break") for b in blocks))

    def test_break_before_text_in_same_paragraph_marks_own_block(self):
        blocks = self._extract(
            _p("Earlier paragraph."),
            "  <w:p><w:r><w:br w:type=\"page\"/></w:r>"
            "<w:r><w:t>Starts a new page.</w:t></w:r></w:p>",
        )
        by_text = {_text_of(b): b for b in blocks}
        self.assertTrue(by_text["Starts a new page."].get("force_page_break"))
        self.assertNotIn("force_page_break", by_text["Earlier paragraph."])


if __name__ == "__main__":
    unittest.main()
