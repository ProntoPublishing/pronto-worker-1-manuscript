"""
E3 2a (5.4.0-a1): embedded-image extraction — a hand-built docx with
one paragraph, one inline image (with alt text), and a Caption-styled
paragraph must yield an image block carrying the figure node (media
name, alt, attached caption, customer_supplied provenance pair) plus
the media bytes; docx without images behaves exactly as before.
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.cir.extractor_docx import extract_docx

PNG_1PX = (b"\x89PNG\r\n\x1a\n" + bytes.fromhex(
    "0000000d494844520000000100000001080200000090775" 
    "3de0000000c4944415408d763f8cfc00000030001" 
    "80a2f1590000000049454e44ae426082"))

DOC_XML = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
<w:body>
<w:p><w:r><w:t>The orchard before the frost.</w:t></w:r></w:p>
<w:p><w:r><w:drawing>
  <wp:inline><wp:docPr id="1" name="orchard.png" descr="The old orchard at dusk"/>
    <a:graphic><a:graphicData>
      <pic:pic><pic:blipFill><a:blip r:embed="rId7"/></pic:blipFill></pic:pic>
    </a:graphicData></a:graphic>
  </wp:inline>
</w:drawing></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>
  <w:r><w:t>Figure 1: The orchard, year one.</w:t></w:r></w:p>
<w:p><w:r><w:t>After the image, life went on.</w:t></w:r></w:p>
</w:body></w:document>"""

RELS_XML = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId7"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
 Target="media/image1.png"/>
</Relationships>"""


def _build_docx(path, with_image=True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", DOC_XML if with_image else
                   DOC_XML.replace("rId7", "rIdMISSING"))
        z.writestr("word/_rels/document.xml.rels", RELS_XML)
        if with_image:
            z.writestr("word/media/image1.png", PNG_1PX)


class TestFigureExtraction(unittest.TestCase):
    def test_image_block_with_figure_node_and_caption(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.docx")
            _build_docx(path)
            blocks, _, media = extract_docx(path)
        images = [b for b in blocks if b.get("type") == "image"]
        self.assertEqual(len(images), 1)
        fig = images[0]["figure"]
        self.assertEqual(fig["media_name"], "media/image1.png")
        self.assertEqual(fig["alt"], "The old orchard at dusk")
        self.assertEqual(fig["caption"], "Figure 1: The orchard, year one.")
        self.assertEqual(fig["acquisition_class"], "customer_supplied")
        self.assertIn("manuscript submission", fig["rights_basis"])
        self.assertIn("media/image1.png", media)
        self.assertEqual(media["media/image1.png"], PNG_1PX)
        # Caption paragraph was absorbed into the figure, not the body.
        def _text(b):
            return (b.get("text") or "".join(
                s.get("text", "") for s in b.get("spans") or []))
        texts = [_text(b) for b in blocks]
        self.assertFalse(any("Figure 1" in t for t in texts))
        self.assertTrue(any("life went on" in t for t in texts))

    def test_missing_media_emits_no_figure(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.docx")
            _build_docx(path, with_image=False)
            blocks, _, media = extract_docx(path)
        self.assertEqual([b for b in blocks if b.get("type") == "image"], [])

    def test_no_image_docx_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.docx")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml",
                           DOC_XML.split("<w:p><w:r><w:drawing>")[0]
                           + "</w:body></w:document>")
            blocks, _, media = extract_docx(path)
        self.assertEqual(media, {})
        self.assertEqual(len(blocks), 1)


if __name__ == "__main__":
    unittest.main()
