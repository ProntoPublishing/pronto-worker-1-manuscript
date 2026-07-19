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
# E3 2a (5.4.0-a1): drawing/relationship namespaces for embedded images.
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PKG_R = "http://schemas.openxmlformats.org/package/2006/relationships"


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
        (blocks, source_meta, figures_media). Blocks are in document
        order; figures_media maps media_name -> raw bytes for every
        embedded image an emitted figure block references (E3 2a).
        source_meta
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
        # Footnote ingestion (5.3.0-a1): read word/footnotes.xml when
        # present. Absence (or malformed XML) degrades to the pre-5.3
        # behavior — no footnote blocks, never a crash.
        try:
            footnotes_xml = z.read("word/footnotes.xml").decode("utf-8")
        except KeyError:
            footnotes_xml = None
        # E3 2a: relationships + embedded media. Degrades to no-figures
        # on any malformation — never a crash.
        rels: Dict[str, str] = {}
        media: Dict[str, bytes] = {}
        try:
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8")
            for rel in ET.fromstring(rels_xml):
                rid = rel.get("Id")
                target = rel.get("Target") or ""
                if rid and target.startswith("media/"):
                    rels[rid] = target
            for name in z.namelist():
                if name.startswith("word/media/"):
                    media[name[len("word/"):]] = z.read(name)
        except Exception:
            rels, media = {}, {}

    root = ET.fromstring(doc_xml)
    body = root.find("w:body", NS)
    if body is None:
        return [], _empty_source_meta(file_path), {}

    ids = BlockIdGenerator()
    blocks: List[Dict[str, Any]] = []

    # --- First pass: collect median body-text font size for large/small_font
    # style_tag resolution. We scan headings out; the median of non-heading
    # paragraph sizes is the dominant body size.
    dominant_half_points = body_sizes.get("median_half_points")

    # Footnote context (5.3.0-a1): note bodies keyed by w:id, display
    # numbers assigned by order of first reference in the document walk.
    fn_ctx = _FootnoteContext.parse(footnotes_xml)

    # --- Main walk.
    # Manual-page-break observation (tripwire plumbing, 2026-07-16): a
    # paragraph consisting solely of a page-break run (Word Insert →
    # Page Break; python-docx add_page_break) produces NO page_break
    # block — _split_on_inline_page_breaks collapses it to one empty
    # segment and the break was silently lost. Rather than emit a new
    # block (which would shift block indices through C-003's contiguity
    # arithmetic), record the observation on the first CONTENT block
    # that follows the break as force_page_break: true — already legal
    # on any block per manuscript.v2.1 schema (I-5 uses it on
    # part_divider). W1 classification never reads it; W2 renders it
    # only on part_divider (unchanged) and reads it in the V-007 title-
    # cluster gate check. Same treatment for w:pPr/w:pageBreakBefore.
    pending_break = False
    for element in body:
        tag = _local_tag(element.tag)
        if tag == "p":
            if _paragraph_page_break_before(element):
                pending_break = True
            n_before = len(blocks)
            disposition = _emit_paragraph(
                element, blocks, ids, dominant_half_points, fn_ctx
            )
            if disposition == "self":
                # Swallowed inline break preceding this paragraph's own
                # content — the break lands on this paragraph's block.
                pending_break = True
            if pending_break and _mark_first_content_block(blocks, n_before):
                pending_break = False
            if disposition == "next":
                # Lone-break paragraph, or break after this paragraph's
                # content: the next content block starts the new page.
                pending_break = True
            # E3 2a: embedded images ride in w:drawing/a:blip runs.
            # Caption convention: a directly-following paragraph styled
            # `Caption` attaches to the figure instead of the body (the
            # paragraph was already emitted above — reassign its text).
            for blip in element.iter(f"{{{A}}}blip"):
                rid = blip.get(f"{{{R}}}embed")
                target = rels.get(rid or "")
                if not target or target not in media:
                    continue
                alt = None
                for doc_pr in element.iter(f"{{{WP}}}docPr"):
                    alt = doc_pr.get("descr") or doc_pr.get("name") or None
                    break
                blocks.append(make_block(
                    id=ids.next(),
                    type="image",
                    figure={
                        "media_name": target,
                        "alt": alt,
                        "caption": None,
                        "credit": None,
                        "acquisition_class": "customer_supplied",
                        "rights_basis": "author manuscript submission "
                                        "(docx-embedded)",
                    },
                    source={"note": f"embedded image {target} "
                                    f"(rel {rid})"},
                ))
                if pending_break:
                    blocks[-1]["force_page_break"] = True
                    pending_break = False
            if (blocks and blocks[-1].get("type") != "image"
                    and len(blocks) >= 2
                    and blocks[-2].get("type") == "image"
                    and _paragraph_style_is_caption(element)):
                last = blocks[-1]
                cap_text = (last.get("text")
                            or "".join(s.get("text", "")
                                       for s in last.get("spans") or [])
                            ).strip()
                if cap_text and blocks[-2].get("figure") is not None:
                    blocks[-2]["figure"]["caption"] = cap_text
                    blocks.pop()   # the caption is figure metadata, not body
        elif tag == "tbl":
            # Placeholder — real table extraction lands in a later iteration.
            blocks.append(make_block(
                id=ids.next(),
                type="table",
                source={"note": "table placeholder; structured extraction deferred"},
            ))
            if pending_break:
                blocks[-1]["force_page_break"] = True
                pending_break = False
        elif tag == "sectPr":
            continue
        # Anything else (bookmarkStart etc.) — ignore at this layer.

    # Note: paragraph-level empty-line run collapsing is N-001's job
    # (paragraph-level extension). The extractor emits empty-line blocks
    # as they appear in the source; N-001 in the strip phase collapses
    # runs of 2+ into one.

    figures_media = {name: data for name, data in media.items()
                     if any(b.get("type") == "image"
                            and (b.get("figure") or {}).get("media_name") == name
                            for b in blocks)}

    source_meta = {
        "original_filename": file_path.name,
        "original_format": "docx",
        "original_file_size_bytes": file_path.stat().st_size,
        # source_hash_sha256 + ingested_at are set by the caller, not by
        # the extractor — those are outer pipeline concerns.
    }
    return blocks, source_meta, figures_media


# ---------------------------------------------------------------------------
# Paragraph walker
# ---------------------------------------------------------------------------

def _emit_paragraph(
    p_elem: ET.Element,
    blocks: List[Dict[str, Any]],
    ids: BlockIdGenerator,
    dominant_half_points: Optional[int],
    fn_ctx: Optional["_FootnoteContext"] = None,
) -> Optional[str]:
    """Translate a w:p element to one or more CIR blocks.

    A single w:p may produce:
      - One paragraph/heading/blockquote block (the common case).
      - Multiple blocks when an inline page break splits the paragraph.
      - A single empty paragraph (type=paragraph, style_tag=empty_line)
        when the paragraph has no textual content.
      - Trailing footnote blocks (5.3.0-a1): one type=footnote block per
        footnote referenced in this paragraph, emitted immediately after
        the paragraph's own block(s), with footnote_ref = the anchor
        block's id (per the schema: "id of the origin paragraph that
        anchored this footnote"). Document-order placement at the anchor
        is a PROVISIONAL policy — Gate 3 Q1 decides anchor-position vs
        chapter-end vs book-end; only the extractor changes if it moves.

    Returns the swallowed-break disposition for the caller's manual-
    page-break observation pass:
      - "self": an inline break preceded this paragraph's own content
        (the break belongs on this paragraph's block).
      - "next": the paragraph carried a page break but emitted no
        page_break block and no content after it (lone-break paragraph,
        or trailing break) — the break belongs on the NEXT content block.
      - None: no swallowed break (none present, or the multi-segment
        path already emitted explicit page_break blocks).
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
                fn_ctx=fn_ctx,
            )
        _emit_pending_footnotes(blocks, ids, fn_ctx)
        return None

    _emit_paragraph_segment(
        segments[0] if segments else [],
        p_style, alignment, dominant_half_points,
        blocks, ids,
        fn_ctx=fn_ctx,
    )
    _emit_pending_footnotes(blocks, ids, fn_ctx)
    return _swallowed_break_disposition(p_elem)


def _emit_pending_footnotes(
    blocks: List[Dict[str, Any]],
    ids: BlockIdGenerator,
    fn_ctx: Optional["_FootnoteContext"],
) -> None:
    """Emit one type=footnote block per footnote referenced by the
    paragraph just emitted (fn_ctx.pending), anchored to the last
    content block. Each note is emitted once, on its first reference."""
    if fn_ctx is None or not fn_ctx.pending:
        return
    pending, fn_ctx.pending = fn_ctx.pending, []
    # Anchor = the most recent block that can carry a footnote_ref
    # target: the last non-page_break block (the paragraph's own block).
    anchor_id = None
    for b in reversed(blocks):
        if b.get("type") != "page_break":
            anchor_id = b.get("id")
            break
    for number, note_id in pending:
        if note_id in fn_ctx.emitted:
            continue  # second reference to the same note: marker only
        spans = fn_ctx.note_spans(note_id)
        if not any((s.get("text") or "").strip() for s in spans):
            continue  # empty/malformed note body — nothing to carry
        fn_ctx.emitted.add(note_id)
        # Lead with the display number, superscript — matching how Word
        # renders the note area (the number lives OUTSIDE the note text,
        # in the w:footnoteRef marker run we skip).
        all_spans = [make_span(str(number), ["superscript"]),
                     make_span(" ", [])] + spans
        blocks.append(make_block(
            id=ids.next(),
            type="footnote",
            spans=all_spans,
            footnote_ref=anchor_id,
        ))


def _emit_paragraph_segment(
    run_elems: List[ET.Element],
    p_style: Dict[str, Any],
    alignment: Optional[str],
    dominant_half_points: Optional[int],
    blocks: List[Dict[str, Any]],
    ids: BlockIdGenerator,
    *,
    source_paragraph_id: Optional[str] = None,
    fn_ctx: Optional["_FootnoteContext"] = None,
) -> None:
    """Emit one CIR block from a list of w:r elements (a paragraph segment)."""
    spans = _runs_to_spans(run_elems, fn_ctx=fn_ctx)

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

    # pStyle → style_tags synthesis (Doc 22 v1.0.3, frozen table):
    # semantically-loaded named styles imply presentation even when the
    # paragraph carries no explicit alignment/size attributes (Pandoc
    # and Word default Title/Author styles emit no explicit centering).
    # Dedupe-merged with the attribute-derived tags above.
    for tag in _PSTYLE_SYNTHESIS.get((p_style.get("name") or "").lower(), ()):
        if tag not in style_tags:
            style_tags.append(tag)

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

# Doc 22 v1.0.3 pStyle-name → style_tags synthesis table (FROZEN).
# Keys lowercased for the case-insensitive lookup.
_PSTYLE_SYNTHESIS = {
    "title":     ("centered", "large_font"),
    "subtitle":  ("centered", "large_font"),
    "booktitle": ("centered", "large_font"),
    "author":    ("centered",),
}

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
            # "blocktext" is pandoc's blockquote paragraph style
            # (Book 18 epigraphs, 5.3.1) — Word's own are quote /
            # intensequote; "quotation"/"blockquote" cover other
            # converters.
            if lv in ("quote", "quotation", "intensequote", "blockquote",
                      "blocktext"):
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


def _paragraph_page_break_before(p_elem: ET.Element) -> bool:
    """True when the paragraph carries w:pPr/w:pageBreakBefore (the
    Format → Paragraph → "Page break before" property — Hatch-style
    manual chapter breaks). An explicit false/0 val negates it."""
    el = p_elem.find("w:pPr/w:pageBreakBefore", NS)
    if el is None:
        return False
    val = (el.get(f"{{{W}}}val") or "").lower()
    return val not in ("false", "0", "none")


def _swallowed_break_disposition(p_elem: ET.Element) -> Optional[str]:
    """For a paragraph that produced a SINGLE segment, classify any
    inline page-break run the splitter swallowed (see the lone-break
    trace in extract_docx): "self" when the break precedes the
    paragraph's first text run, "next" when the paragraph has no text
    or the break follows it, None when no break is present. Only
    top-level w:r children are checked for breaks, matching
    _split_on_inline_page_breaks.
    """
    first_break: Optional[int] = None
    first_text: Optional[int] = None
    for pos, child in enumerate(list(p_elem)):
        tag = _local_tag(child.tag)
        if tag == "r":
            if first_break is None and _run_contains_page_break(child):
                first_break = pos
            if first_text is None and _run_text(child):
                first_text = pos
        elif tag in ("hyperlink", "ins"):
            if first_text is None and any(
                _run_text(r) for r in child.findall("w:r", NS)
            ):
                first_text = pos
    if first_break is None:
        return None
    if first_text is not None and first_break < first_text:
        return "self"
    return "next"


def _mark_first_content_block(
    blocks: List[Dict[str, Any]], start: int,
) -> bool:
    """Set force_page_break: true on the first CONTENT block at or
    after index `start`. Content = anything except an empty_line
    paragraph or a page_break block, so the observation survives
    N-001's empty-line run collapse (which only ever drops empty_line
    paragraphs). Returns True when a block was marked."""
    for b in blocks[start:]:
        if b.get("type") == "page_break":
            continue
        if (
            b.get("type") == "paragraph"
            and "empty_line" in (b.get("style_tags") or [])
        ):
            continue
        b["force_page_break"] = True
        return True
    return False


def _runs_to_spans(
    runs: List[ET.Element],
    fn_ctx: Optional["_FootnoteContext"] = None,
) -> List[Dict[str, Any]]:
    """Convert a list of w:r elements to CIR spans, preserving inter-run
    whitespace (Extractor Responsibilities — the fix for the space-loss
    bug). Runs with identical marks are NOT collapsed here; later a Layer 1a
    pass can collapse them if desired.

    Footnote anchors (5.3.0-a1): a run containing w:footnoteReference
    contributes a superscript span with the note's display number
    (assigned by order of first reference — Word's w:id values are
    arbitrary, the rendered numbering is sequential) and queues the
    note body on fn_ctx.pending for the caller to emit after the
    paragraph. Pre-5.3 these runs contributed nothing (no w:t), which
    is how 33 markers vanished from Book 11 without a trace. When
    fn_ctx is None (note bodies themselves, or a doc with no
    footnotes.xml) the pre-5.3 behavior stands.
    """
    spans: List[Dict[str, Any]] = []
    for r in runs:
        if fn_ctx is not None:
            note_id = _run_footnote_reference_id(r)
            if note_id is not None and note_id in fn_ctx.notes:
                number = fn_ctx.assign_number(note_id)
                spans.append(make_span(str(number), ["superscript"]))
                fn_ctx.pending.append((number, note_id))
                continue
        text = _run_text(r)
        if not text:
            continue
        marks = _run_marks(r)
        spans.append(make_span(text, marks))
    return spans


def _run_footnote_reference_id(r_elem: ET.Element) -> Optional[str]:
    """The w:id of a w:footnoteReference in this run, or None. (Not to
    be confused with w:footnoteRef — the note's own self-marker inside
    footnotes.xml, which we deliberately skip.)"""
    ref = r_elem.find("w:footnoteReference", NS)
    if ref is None:
        return None
    return ref.get(f"{{{W}}}id")


class _FootnoteContext:
    """State for footnote ingestion across the document walk.

    notes    — w:id → list of the note's w:p elements (content notes
               only; separator/continuation pseudo-notes are excluded).
    numbers  — w:id → display number, assigned on first reference.
    pending  — (number, id) queue for the paragraph being emitted;
               drained by _emit_pending_footnotes.
    emitted  — ids whose blocks are already in the stream (a repeated
               reference renders a marker but not a second body).
    """

    def __init__(self, notes: Dict[str, List[ET.Element]]):
        self.notes = notes
        self.numbers: Dict[str, int] = {}
        self.pending: List[Tuple[int, str]] = []
        self.emitted: set = set()

    @classmethod
    def parse(cls, footnotes_xml: Optional[str]) -> "_FootnoteContext":
        notes: Dict[str, List[ET.Element]] = {}
        if footnotes_xml:
            try:
                froot = ET.fromstring(footnotes_xml)
                for fn in froot.findall("w:footnote", NS):
                    # Separator / continuationSeparator / continuation-
                    # Notice pseudo-notes carry w:type; content notes don't.
                    if fn.get(f"{{{W}}}type"):
                        continue
                    fid = fn.get(f"{{{W}}}id")
                    if fid is None:
                        continue
                    notes[fid] = fn.findall("w:p", NS)
            except ET.ParseError:
                notes = {}
        return cls(notes)

    def assign_number(self, note_id: str) -> int:
        if note_id not in self.numbers:
            self.numbers[note_id] = len(self.numbers) + 1
        return self.numbers[note_id]

    def note_spans(self, note_id: str) -> List[Dict[str, Any]]:
        """The note body as CIR spans: every run of every paragraph,
        w:footnoteRef marker runs skipped (fn_ctx=None — a footnote
        cannot itself anchor another footnote), paragraphs joined with
        a single space span."""
        spans: List[Dict[str, Any]] = []
        for i, p in enumerate(self.notes.get(note_id) or []):
            runs: List[ET.Element] = []
            for child in list(p):
                tag = _local_tag(child.tag)
                if tag == "r":
                    if child.find("w:footnoteRef", NS) is not None:
                        continue
                    runs.append(child)
                elif tag in ("hyperlink", "ins"):
                    runs.extend(child.findall("w:r", NS))
            p_spans = _runs_to_spans(runs, fn_ctx=None)
            if p_spans and spans:
                spans.append(make_span(" ", []))
            spans.extend(p_spans)
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
         default body font size. This is the correct notion of "body size"
         in Word: any paragraph that overrides it is intentionally larger
         or smaller.
      2. Median of explicit w:sz values on non-heading paragraphs. Used
         when docDefaults is absent; can be skewed by title-cluster
         paragraphs that set explicit sizes, so treated as a fallback.
      3. DOCX spec default (22 half-points = 11pt).

    This function is intentionally DOCX-specific. The concept of "dominant
    body font size" depends on the source format — a Markdown extractor
    will derive it entirely differently (probably from a config value,
    since Markdown has no explicit font sizes). Doc 22 §CIR should not
    specify the resolution mechanism; it lives here in the extractor.
    On the standing docs-hygiene punchlist as "extractor-level
    documentation item" per Jesse's note on 2026-04-24.
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


def _paragraph_style_is_caption(element) -> bool:
    """E3 2a: True when the paragraph's pStyle is Word's Caption style
    (the convention that binds a caption to the figure above it)."""
    p_style = element.find("w:pPr/w:pStyle", NS)
    if p_style is None:
        return False
    val = (p_style.get(f"{{{W}}}val") or "").strip().lower()
    return val == "caption"
