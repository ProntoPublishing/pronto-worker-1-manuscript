"""
DOCX → CIR extractor.

Implements the extractor contract in Doc 22 v1.0.1 §CIR Block Structure →
Extractor Responsibilities. Produces format-agnostic CIR blocks from a .docx
file; assigns no roles (Layer 2 classifiers do that).

Implements at the extractor level:
  - N-002 (tracked-change acceptance). Tracked changes are resolved during
    extraction; V-004 (validator) catches any that leak through.
  - Extractor-responsibility list items from Doc 22 §CIR: unique ids,
    document order, inter-run whitespace preservation, style-tag
    normalization, preformatted flag, empty-paragraph handling, inline
    page-break splitting.

Does NOT yet handle (deferred to later iterations by design, one file):
  - Footnotes (DOCX footnote surfacing to a footnote block with footnote_ref).
  - Tables beyond placeholder emission.
  - Images beyond placeholder emission.
  - DOCX numbered/bulleted list → list_item (v1 emits as paragraph; list
    detection arrives with Layer 2 rules in a later iteration).

Body font-size resolution for large_font / small_font style tags:
  The extractor resolves "body font size" (the denominator for the
  ≥1.5× / ≤0.75× ratio checks) in the following order, first hit wins:
    1. styles.xml docDefaults/rPrDefault/rPr/sz — the document-declared
       default body size. This is the correct notion of "body size" in
       Word: any paragraph that overrides it is intentionally larger or
       smaller.
    2. Median of explicit w:sz values across non-heading paragraphs in
       the document. Used only when docDefaults is absent. Can be
       skewed by title-cluster paragraphs that set explicit sizes, so
       it's a fallback, not the preferred signal.
    3. DOCX spec default (22 half-points = 11pt).
  This is a DOCX-specific mechanism; format-agnostic Doc 22 does not
  (and should not) specify it. Future format extractors (Markdown, etc.)
  will have their own notion of body size. On the standing docs-hygiene
  punchlist as an extractor-level documentation item.

Version: 5.0.0a1 (contract v1.1, manuscript.v2.0 producer — pre-release).
"""
from __future__ import annotations
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import xml.etree.ElementTree as ET

from .types import make_block, make_span, STYLE_TAGS

# OOXML namespaces we care about.
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


class BlockIdGenerator:
    """Sequential b_###### ids, stable within a single extraction."""

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"b_{self._n:06d}"


def extract_docx(file_path: str | Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Extract CIR blocks from a DOCX file.

    Returns:
        (blocks, source_meta). Blocks are in document order. source_meta
        carries the fields the v2.0 schema expects under `source` (plus a
        few extras the emit layer may filter out).
    """
    file_path = Path(file_path)
    with zipfile.ZipFile(file_path, "r") as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
        try:
            body_sizes = _detect_body_font_size(z)
        except Exception:
            body_sizes = {"median_half_points": None, "median_pt": None}

    root = ET.fromstring(doc_xml)
    body = root.find("w:body", NS)
    if body is None:
        return [], _empty_source_meta(file_path)

    ids = BlockIdGenerator()
    blocks: List[Dict[str, Any]] = []

    # --- First pass: collect median body-text font size for large/small_font
    # style_tag resolution. We scan headings out; the median of non-heading
    # paragraph sizes is the dominant body size.
    dominant_half_points = body_sizes.get("median_half_points")

    # --- Main walk.
    for element in body:
        tag = _local_tag(element.tag)
        if tag == "p":
            _emit_paragraph(element, blocks, ids, dominant_half_points)
        elif tag == "tbl":
            # Placeholder — real table extraction lands in a later iteration.
            blocks.append(make_block(
                id=ids.next(),
                type="table",
                source={"note": "table placeholder; structured extraction deferred"},
            ))
        elif tag == "sectPr":
            continue
        # Anything else (bookmarkStart etc.) — ignore at this layer.

    # Note: paragraph-level empty-line run collapsing is N-001's job
    # (paragraph-level extension). The extractor emits empty-line blocks
    # as they appear in the source; N-001 in the strip phase collapses
    # runs of 2+ into one.

    source_meta = {
        "original_filename": file_path.name,
        "original_format": "docx",
        "original_file_size_bytes": file_path.stat().st_size,
        # source_hash_sha256 + ingested_at are set by the caller, not by
        # the extractor — those are outer pipeline concerns.
    }
    return blocks, source_meta


# ---------------------------------------------------------------------------
# Paragraph walker
# ---------------------------------------------------------------------------

def _emit_paragraph(
    p_elem: ET.Element,
    blocks: List[Dict[str, Any]],
    ids: BlockIdGenerator,
    dominant_half_points: Optional[int],
) -> None:
    """Translate a w:p element to one or more CIR blocks.

    A single w:p may produce:
      - One paragraph/heading/blockquote block (the common case).
      - Multiple blocks when an inline page break splits the paragraph.
      - A single empty paragraph (type=paragraph, style_tag=empty_line)
        when the paragraph has no textual content.
    """
    p_style = _paragraph_style(p_elem)
    alignment = _paragraph_alignment(p_elem)
    is_preformatted, pstyle_name = p_style["is_preformatted"], p_style["name"]
    heading_level = p_style["heading_level"]

    # Split the paragraph on inline page breaks. Each segment is a list of
    # w:r elements; between segments we emit a page_break block.
    segments = _split_on_inline_page_breaks(p_elem)

    if len(segments) > 1:
        # Mark both halves with the same source_paragraph_id.
        src_id = ids.next()
        # Note: we used an id here purely as a correlation token. It won't
        # appear as a block id; it just tags the halves.
        for i, seg in enumerate(segments):
            if i > 0:
                blocks.append(make_block(id=ids.next(), type="page_break"))
            _emit_paragraph_segment(
                seg, p_style, alignment, dominant_half_points,
                blocks, ids,
                source_paragraph_id=src_id,
            )
        return

    _emit_paragraph_segment(
        segments[0] if segments else [],
        p_style, alignment, dominant_half_points,
        blocks, ids,
    )


def _emit_paragraph_segment(
    run_elems: List[ET.Element],
    p_style: Dict[str, Any],
    alignment: Optional[str],
    dominant_half_points: Optional[int],
    blocks: List[Dict[str, Any]],
    ids: BlockIdGenerator,
    *,
    source_paragraph_id: Optional[str] = None,
) -> None:
    """Emit one CIR block from a list of w:r elements (a paragraph segment)."""
    spans = _runs_to_spans(run_elems)

    # Determine style_tags from alignment + per-run dominant styling.
    style_tags: List[str] = []
    if alignment:
        style_tags.append(alignment)
    if spans:
        # Large/small-font style tag: compare the segment's dominant run
        # size (if set) against the document body median.
        size_hp = _dominant_run_size_half_points(run_elems)
        if size_hp and dominant_half_points:
            ratio = size_hp / dominant_half_points
            if ratio >= 1.5:
                style_tags.append("large_font")
            elif ratio <= 0.75:
                style_tags.append("small_font")

    # Empty paragraph? Emit as type=paragraph with style_tag=empty_line.
    if not spans:
        style_tags.append("empty_line")
        blocks.append(make_block(
            id=ids.next(),
            type="paragraph",
            spans=[make_span("", [])],
            style_tags=style_tags or None,
            source_paragraph_id=source_paragraph_id,
        ))
        return

    # Blockquote style?
    if p_style.get("is_blockquote"):
        blocks.append(make_block(
            id=ids.next(),
            type="blockquote",
            spans=spans,
            style_tags=style_tags or None,
            preformatted=p_style["is_preformatted"],
            source_paragraph_id=source_paragraph_id,
        ))
        return

    # Heading?
    heading_level = p_style.get("heading_level")
    if heading_level:
        blocks.append(make_block(
            id=ids.next(),
            type="heading",
            heading_level=heading_level,
            spans=spans,
            style_tags=style_tags or None,
            source_paragraph_id=source_paragraph_id,
        ))
        return

    # Preformatted code-ish paragraph?
    if p_style.get("is_preformatted"):
        blocks.append(make_block(
            id=ids.next(),
            type="paragraph",
            spans=spans,
            style_tags=style_tags or None,
            preformatted=True,
            source_paragraph_id=source_paragraph_id,
        ))
        return

    # Default: body paragraph.
    blocks.append(make_block(
        id=ids.next(),
        type="paragraph",
        spans=spans,
        style_tags=style_tags or None,
        source_paragraph_id=source_paragraph_id,
    ))


# ---------------------------------------------------------------------------
# Paragraph-style detection
# ---------------------------------------------------------------------------

_HEADING_STYLE_RE = re.compile(r"^Heading\s*(\d+)$", re.IGNORECASE)

def _paragraph_style(p_elem: ET.Element) -> Dict[str, Any]:
    """Inspect w:pPr → w:pStyle and derive CIR-relevant fields.

    Returns dict with keys: name, heading_level (int|None),
    is_preformatted (bool), is_blockquote (bool).
    """
    out = {
        "name": None,
        "heading_level": None,
        "is_preformatted": False,
        "is_blockquote": False,
    }

    ppr = p_elem.find("w:pPr", NS)
    if ppr is not None:
        pstyle = ppr.find("w:pStyle", NS)
        if pstyle is not None:
            style_val = pstyle.get(f"{{{W}}}val", "")
            out["name"] = style_val
            m = _HEADING_STYLE_RE.match(style_val or "")
            if m:
                lvl = int(m.group(1))
                if 1 <= lvl <= 6:
                    out["heading_level"] = lvl
            lv = style_val.lower() if style_val else ""
            if lv in ("quote", "quotation", "intensequote", "blockquote"):
                out["is_blockquote"] = True
            if lv in (
                "code", "codeblock", "sourcecode", "preformatted",
                "htmlpreformatted",
            ):
                out["is_preformatted"] = True

    # Run-level monospace detection as a second preformatted signal —
    # checked regardless of whether a w:pPr was present, because DOCX
    # files can carry monospace font hints at the run level without
    # declaring a paragraph style.
    if not out["is_preformatted"]:
        if _has_monospace_run(p_elem):
            out["is_preformatted"] = True

    return out


def _has_monospace_run(p_elem: ET.Element) -> bool:
    """True if any run in the paragraph declares a monospace font."""
    mono_hits = {"courier new", "courier", "consolas", "monaco", "menlo"}
    for r in p_elem.findall(".//w:r", NS):
        rpr = r.find("w:rPr", NS)
        if rpr is None:
            continue
        rfonts = rpr.find("w:rFonts", NS)
        if rfonts is None:
            continue
        for attr in ("ascii", "hAnsi", "cs"):
            val = rfonts.get(f"{{{W}}}{attr}") or ""
            if val.lower() in mono_hits:
                return True
    return False


def _paragraph_alignment(p_elem: ET.Element) -> Optional[str]:
    """Return a canonical style_tag for the paragraph's alignment, or None."""
    ppr = p_elem.find("w:pPr", NS)
    if ppr is None:
        return None
    jc = ppr.find("w:jc", NS)
    if jc is None:
        return None
    val = (jc.get(f"{{{W}}}val") or "").lower()
    if val == "center":
        return "centered"
    if val == "right":
        return "right_aligned"
    if val in ("both", "distribute", "justify"):
        return "justified"
    return None


# ---------------------------------------------------------------------------
# Run-level extraction: spans + tracked-change acceptance (N-002)
# ---------------------------------------------------------------------------

def _split_on_inline_page_breaks(
    p_elem: ET.Element,
) -> List[List[ET.Element]]:
    """Split a paragraph's runs on inline w:br w:type=page. Returns a list
    of run-segments. Most paragraphs produce exactly one segment.
    """
    segments: List[List[ET.Element]] = [[]]
    for child in list(p_elem):
        tag = _local_tag(child.tag)
        if tag == "pPr":
            continue
        if tag == "r":
            if _run_contains_page_break(child):
                # If the run has both text AND a page-break, split at the
                # break. Simpler heuristic: if the run has a page break
                # among its children, end the current segment BEFORE this
                # run, treat this run as the split point, and start a new
                # segment AFTER it. We keep the run itself out of both
                # halves — the page_break block replaces it.
                # In practice authored DOCX usually places page-break runs
                # alone; this simplification covers the common case.
                if segments[-1]:
                    segments.append([])
                # Start a new segment to receive subsequent runs.
                segments.append([])
                continue
            segments[-1].append(child)
        elif tag == "ins":
            # N-002: accept tracked insertions. Descend into the <w:ins>
            # wrapper and treat its child runs as normal runs. Their text
            # becomes part of the paragraph.
            for inner in child.findall("w:r", NS):
                segments[-1].append(inner)
        elif tag == "del":
            # N-002: accept the author's deletion — i.e., drop the deleted
            # content entirely. Do nothing with <w:del> children.
            continue
        elif tag == "hyperlink":
            # Hyperlinks wrap runs; flatten.
            for inner in child.findall("w:r", NS):
                segments[-1].append(inner)
    # Drop trailing empty segments introduced by splits at the end.
    while len(segments) > 1 and not segments[-1]:
        segments.pop()
    # Drop leading empty segments (if a page-break started the paragraph).
    if len(segments) > 1 and not segments[0]:
        segments.pop(0)
    return segments


def _run_contains_page_break(r_elem: ET.Element) -> bool:
    for br in r_elem.findall("w:br", NS):
        if (br.get(f"{{{W}}}type") or "").lower() == "page":
            return True
    return False


def _runs_to_spans(runs: List[ET.Element]) -> List[Dict[str, Any]]:
    """Convert a list of w:r elements to CIR spans, preserving inter-run
    whitespace (Extractor Responsibilities — the fix for the space-loss
    bug). Runs with identical marks are NOT collapsed here; later a Layer 1a
    pass can collapse them if desired.
    """
    spans: List[Dict[str, Any]] = []
    for r in runs:
        text = _run_text(r)
        if not text:
            continue
        marks = _run_marks(r)
        spans.append(make_span(text, marks))
    return spans


def _run_text(r_elem: ET.Element) -> str:
    """Concatenate w:t and w:tab within a run. xml:space=preserve is honored
    by ElementTree's .text access (we do not strip whitespace here — that's
    the point of the whitespace-preservation invariant).
    """
    pieces: List[str] = []
    for child in list(r_elem):
        tag = _local_tag(child.tag)
        if tag == "t":
            pieces.append(child.text or "")
        elif tag == "tab":
            pieces.append("\t")
        elif tag == "br":
            # Non-page break (e.g. line break inside heading).
            if (child.get(f"{{{W}}}type") or "").lower() != "page":
                pieces.append("\n")
        elif tag == "noBreakHyphen":
            pieces.append("-")
        elif tag == "softHyphen":
            # Author-intentional hyphenation hint; drop in body text.
            continue
    return "".join(pieces)


def _run_marks(r_elem: ET.Element) -> List[str]:
    """Derive the span's marks list from w:rPr."""
    marks: List[str] = []
    rpr = r_elem.find("w:rPr", NS)
    if rpr is None:
        return marks
    if rpr.find("w:b", NS) is not None and not _is_off(rpr.find("w:b", NS)):
        marks.append("bold")
    if rpr.find("w:i", NS) is not None and not _is_off(rpr.find("w:i", NS)):
        marks.append("italic")
    if rpr.find("w:u", NS) is not None and not _is_off(rpr.find("w:u", NS)):
        marks.append("underline")
    if rpr.find("w:strike", NS) is not None and not _is_off(rpr.find("w:strike", NS)):
        marks.append("strikethrough")
    if rpr.find("w:smallCaps", NS) is not None and not _is_off(rpr.find("w:smallCaps", NS)):
        marks.append("small_caps")
    vert = rpr.find("w:vertAlign", NS)
    if vert is not None:
        v = (vert.get(f"{{{W}}}val") or "").lower()
        if v == "superscript":
            marks.append("superscript")
        elif v == "subscript":
            marks.append("subscript")
    # Monospace code-mark is ambiguous: we only emit `code` mark when the
    # specific rStyle says so (Code Char / Inline Code). The broader
    # monospace-paragraph case becomes preformatted on the block, not a
    # mark on each span.
    rstyle = rpr.find("w:rStyle", NS)
    if rstyle is not None:
        rv = (rstyle.get(f"{{{W}}}val") or "").lower()
        if rv in ("code", "codechar", "inlinecode", "verbatimchar"):
            marks.append("code")
    return marks


def _is_off(toggle_elem: ET.Element) -> bool:
    """Toggle properties in OOXML are present with val=false to mean off."""
    val = toggle_elem.get(f"{{{W}}}val")
    return val is not None and val.lower() in ("0", "false")


def _dominant_run_size_half_points(runs: List[ET.Element]) -> Optional[int]:
    """Return the mode (most common) font size in half-points across the
    paragraph's runs, or None if no size is set.
    """
    sizes: Dict[int, int] = {}
    for r in runs:
        rpr = r.find("w:rPr", NS)
        if rpr is None:
            continue
        sz = rpr.find("w:sz", NS)
        if sz is None:
            continue
        v = sz.get(f"{{{W}}}val")
        if v and v.isdigit():
            k = int(v)
            sizes[k] = sizes.get(k, 0) + 1
    if not sizes:
        return None
    return max(sizes.items(), key=lambda kv: kv[1])[0]


DEFAULT_BODY_HALF_POINTS = 22  # 11pt, the DOCX default when nothing is set.


def _detect_body_font_size(z: zipfile.ZipFile) -> Dict[str, Optional[int]]:
    """Dominant body font size, in half-points. Used to resolve large_font
    and small_font style tags as ratios against body text.

    Resolution order (first hit wins):
      1. styles.xml docDefaults/rPrDefault/rPr/sz — the document-declared
         default body font size. This is the correct notion of "body size":
         any paragraph that overrides it is intentionally larger or smaller.
      2. Median of explicit w:sz values on non-heading paragraphs. Used
         when docDefaults is absent; can be skewed by title-cluster
         paragraphs that set explicit sizes, so treated as a fallback.
      3. DOCX spec default (22 half-points = 11pt).
    """
    # Preferred: styles.xml docDefaults.
    try:
        styles_xml = z.read("word/styles.xml").decode("utf-8")
        styles_root = ET.fromstring(styles_xml)
        default_sz = styles_root.find(".//w:docDefaults/w:rPrDefault/w:rPr/w:sz", NS)
        if default_sz is not None:
            v = default_sz.get(f"{{{W}}}val")
            if v and v.isdigit():
                hp = int(v)
                return {"median_half_points": hp, "median_pt": hp / 2.0}
    except Exception:
        pass

    # Fallback: paragraph-observed median.
    doc_xml = z.read("word/document.xml").decode("utf-8")
    root = ET.fromstring(doc_xml)
    sizes: List[int] = []
    for p in root.iter(f"{{{W}}}p"):
        pstyle = p.find("w:pPr/w:pStyle", NS)
        style_val = (pstyle.get(f"{{{W}}}val") or "") if pstyle is not None else ""
        if _HEADING_STYLE_RE.match(style_val or ""):
            continue
        for sz in p.iter(f"{{{W}}}sz"):
            v = sz.get(f"{{{W}}}val")
            if v and v.isdigit():
                sizes.append(int(v))
    if sizes:
        sizes.sort()
        mid = sizes[len(sizes) // 2]
        return {"median_half_points": mid, "median_pt": mid / 2.0}

    return {
        "median_half_points": DEFAULT_BODY_HALF_POINTS,
        "median_pt": DEFAULT_BODY_HALF_POINTS / 2.0,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _empty_source_meta(file_path: Path) -> Dict[str, Any]:
    return {
        "original_filename": file_path.name,
        "original_format": "docx",
        "original_file_size_bytes": file_path.stat().st_size,
    }
