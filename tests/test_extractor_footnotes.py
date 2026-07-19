"""Footnote ingestion (5.3.0-a1) — extraction-only, rules stay 1.2.

Book 11 evidence: 33 real Word footnotes; the extractor read
document.xml only, so 0/33 note texts reached the artifact and the
superscript anchor markers vanished with their runs — silently.
Now: anchors contribute a superscript display-number span; each note
body becomes a type=footnote block (role=footnote via terminal
default) emitted right after the anchor block, footnote_ref = anchor
block id per the v2.1 schema. Placement-at-anchor is provisional
pending Gate 3 Q1.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.cir import extract_docx

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
 <Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
</Types>
"""

_DOC_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
{body}
 </w:body>
</w:document>
"""

_FOOTNOTES_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>
 <w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>
{notes}
</w:footnotes>
"""


def _p_with_ref(text, note_id):
    return (
        f"  <w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r>"
        f"<w:r><w:rPr><w:rStyle w:val=\"FootnoteReference\"/></w:rPr>"
        f"<w:footnoteReference w:id=\"{note_id}\"/></w:r></w:p>"
    )


def _p(text):
    return f"  <w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _note(note_id, text, italic_word=None):
    runs = (
        "<w:r><w:rPr><w:rStyle w:val=\"FootnoteReference\"/></w:rPr>"
        "<w:footnoteRef/></w:r>"
        f"<w:r><w:t xml:space=\"preserve\"> {text}</w:t></w:r>"
    )
    if italic_word:
        runs += (
            f"<w:r><w:rPr><w:i/></w:rPr>"
            f"<w:t xml:space=\"preserve\">{italic_word}</w:t></w:r>"
        )
    return f" <w:footnote w:id=\"{note_id}\"><w:p>{runs}</w:p></w:footnote>"


class _DocxCase(unittest.TestCase):
    def _extract(self, body_lines, note_lines=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        docx = Path(tmp.name) / "t.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr(
                "word/document.xml",
                _DOC_TEMPLATE.format(body="\n".join(body_lines)),
            )
            if note_lines is not None:
                z.writestr(
                    "word/footnotes.xml",
                    _FOOTNOTES_TEMPLATE.format(notes="\n".join(note_lines)),
                )
        blocks, _, _fm = extract_docx(docx)
        return blocks

    @staticmethod
    def _text(block):
        return "".join(s["text"] for s in block.get("spans") or [])


class TestFootnoteIngestion(_DocxCase):
    def test_note_block_follows_anchor_with_linkage(self):
        blocks = self._extract(
            [_p_with_ref("Anchor sentence.", 20), _p("Next paragraph.")],
            [_note(20, "The note body.")],
        )
        types = [b["type"] for b in blocks]
        self.assertEqual(types, ["paragraph", "footnote", "paragraph"])
        anchor, note = blocks[0], blocks[1]
        self.assertEqual(note["footnote_ref"], anchor["id"])
        self.assertIn("The note body.", self._text(note))

    def test_anchor_gets_superscript_display_number(self):
        blocks = self._extract(
            [_p_with_ref("Anchor.", 20)],
            [_note(20, "Note.")],
        )
        sup = [s for s in blocks[0]["spans"]
               if "superscript" in (s.get("marks") or [])]
        self.assertEqual([s["text"] for s in sup], ["1"])

    def test_display_numbers_sequential_regardless_of_word_ids(self):
        """Word w:id values are arbitrary (Book 11 starts at 20);
        rendered numbering is order-of-appearance."""
        blocks = self._extract(
            [_p_with_ref("First.", 99), _p_with_ref("Second.", 7)],
            [_note(7, "Note seven."), _note(99, "Note ninety-nine.")],
        )
        notes = [b for b in blocks if b["type"] == "footnote"]
        self.assertEqual(len(notes), 2)
        self.assertTrue(self._text(notes[0]).startswith("1"))
        self.assertIn("ninety-nine", self._text(notes[0]))
        self.assertTrue(self._text(notes[1]).startswith("2"))
        self.assertIn("seven", self._text(notes[1]))

    def test_note_italic_marks_survive(self):
        blocks = self._extract(
            [_p_with_ref("Anchor.", 20)],
            [_note(20, "The stitch is the", italic_word="Kettelstich")],
        )
        note = next(b for b in blocks if b["type"] == "footnote")
        italics = [s for s in note["spans"] if "italic" in (s.get("marks") or [])]
        self.assertEqual([s["text"] for s in italics], ["Kettelstich"])

    def test_self_marker_run_not_in_note_text(self):
        blocks = self._extract(
            [_p_with_ref("Anchor.", 20)],
            [_note(20, "Body only.")],
        )
        note = next(b for b in blocks if b["type"] == "footnote")
        # First span is the display number we synthesize; the w:footnoteRef
        # marker run from footnotes.xml must not add anything.
        self.assertEqual(note["spans"][0]["text"], "1")
        self.assertEqual(note["spans"][0]["marks"], ["superscript"])

    def test_no_footnotes_xml_is_pre_53_behavior(self):
        blocks = self._extract([_p_with_ref("Anchor.", 20), _p("Next.")])
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "paragraph"])
        # marker contributes nothing without a notes file (no dangling "1")
        self.assertEqual(self._text(blocks[0]), "Anchor.")

    def test_reference_to_missing_id_is_skipped(self):
        blocks = self._extract(
            [_p_with_ref("Anchor.", 42)],
            [_note(20, "Unrelated note.")],
        )
        self.assertEqual([b["type"] for b in blocks], ["paragraph"])
        self.assertEqual(self._text(blocks[0]), "Anchor.")

    def test_repeated_reference_emits_one_body(self):
        blocks = self._extract(
            [_p_with_ref("First anchor.", 20), _p_with_ref("Second anchor.", 20)],
            [_note(20, "Shared note.")],
        )
        notes = [b for b in blocks if b["type"] == "footnote"]
        self.assertEqual(len(notes), 1)
        # both anchors still carry the same display number
        sups = [s["text"] for b in blocks if b["type"] == "paragraph"
                for s in b["spans"] if "superscript" in (s.get("marks") or [])]
        self.assertEqual(sups, ["1", "1"])

    def test_separator_pseudo_notes_never_emit(self):
        blocks = self._extract(
            [_p("No references at all.")],
            [_note(20, "Orphan note, never referenced.")],
        )
        self.assertEqual([b["type"] for b in blocks], ["paragraph"])

    def test_footnote_in_heading_anchor(self):
        blocks = self._extract(
            ["  <w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
             "<w:r><w:t>CHAPTER I. TITLE</w:t></w:r>"
             "<w:r><w:footnoteReference w:id=\"20\"/></w:r></w:p>"],
            [_note(20, "Heading note.")],
        )
        self.assertEqual([b["type"] for b in blocks], ["heading", "footnote"])
        self.assertEqual(blocks[1]["footnote_ref"], blocks[0]["id"])


if __name__ == "__main__":
    unittest.main()
