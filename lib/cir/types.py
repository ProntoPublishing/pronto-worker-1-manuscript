"""
CIR canonical vocabularies + block/span builders.

Vocabularies are frozen per Doc 22 v1.0.1 §CIR Block Structure. Any change
requires a schema revision; see manuscript/manuscript.v2.0.schema.json.

Blocks and spans are plain dicts, not dataclasses, so they serialize to JSON
without adapter code and match the existing codebase's idioms. Builder
functions enforce the required-field shape at construction time.
"""
from typing import Dict, List, Any, Optional

# Frozen CIR structural types (Doc 22 v1.0.1 §CIR Block Structure).
CIR_TYPES = frozenset({
    "paragraph",
    "heading",
    "list_item",
    "blockquote",
    "table",
    "image",
    "code",
    "preformatted_block",
    "footnote",
    "page_break",
    "horizontal_rule",
})

# Frozen style-tag vocabulary (Doc 22 v1.0.1 §CIR Block Structure).
STYLE_TAGS = frozenset({
    "centered", "right_aligned", "justified",
    "bold", "italic", "underline", "strikethrough", "small_caps",
    "large_font", "small_font",
    "indented", "outdented",
    "empty_line",
})

# Frozen spans-marks vocabulary (Doc 22 v1.0.1 §CIR Block Structure).
SPAN_MARKS = frozenset({
    "italic", "bold", "small_caps", "code",
    "underline", "strikethrough", "superscript", "subscript",
})


def make_block(
    *,
    id: str,
    type: str,
    source: Optional[Dict[str, Any]] = None,
    heading_level: Optional[int] = None,
    text: Optional[str] = None,
    spans: Optional[List[Dict[str, Any]]] = None,
    style_tags: Optional[List[str]] = None,
    preformatted: bool = False,
    footnote_ref: Optional[str] = None,
    source_paragraph_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a CIR block, enforcing shape at construction.

    One of `text` or `spans` must be provided for text-carrying types; neither
    is required for structural types (page_break, horizontal_rule).
    """
    if type not in CIR_TYPES:
        raise ValueError(f"unknown CIR type: {type!r}")
    if heading_level is not None and type != "heading":
        raise ValueError("heading_level is only valid on type=heading")
    if type == "heading" and heading_level is None:
        raise ValueError("heading_level is required on type=heading")
    if text is not None and spans is not None:
        raise ValueError("block has both text and spans; pick one")

    block: Dict[str, Any] = {"id": id, "type": type}
    if source is not None:
        block["source"] = source
    if heading_level is not None:
        block["heading_level"] = heading_level
    if text is not None:
        block["text"] = text
    if spans is not None:
        block["spans"] = spans
    if style_tags:
        _validate_style_tags(style_tags)
        block["style_tags"] = list(style_tags)
    if preformatted:
        block["preformatted"] = True
    if footnote_ref is not None:
        if type != "footnote":
            raise ValueError("footnote_ref is only valid on type=footnote")
        block["footnote_ref"] = footnote_ref
    if source_paragraph_id is not None:
        block["source_paragraph_id"] = source_paragraph_id
    return block


def make_span(text: str, marks: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build a CIR span (text + frozen-vocabulary marks)."""
    marks = list(marks or [])
    _validate_marks(marks)
    span: Dict[str, Any] = {"text": text}
    if marks:
        span["marks"] = marks
    else:
        span["marks"] = []  # explicit empty; schema allows it
    return span


def _validate_style_tags(tags: List[str]) -> None:
    unknown = [t for t in tags if t not in STYLE_TAGS]
    if unknown:
        raise ValueError(
            f"style_tag(s) outside frozen vocabulary: {unknown!r}. "
            f"Any change requires a schema revision; see Doc 22 §CIR."
        )


def _validate_marks(marks: List[str]) -> None:
    unknown = [m for m in marks if m not in SPAN_MARKS]
    if unknown:
        raise ValueError(
            f"span mark(s) outside frozen vocabulary: {unknown!r}. "
            f"Any change requires a schema revision; see Doc 22 §CIR."
        )
