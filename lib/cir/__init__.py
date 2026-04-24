"""
CIR (Common Intermediate Representation) — Doc 22 §CIR Block Structure.

Format-agnostic block shape consumed by all rules. Currently produced by the
DOCX extractor; future format extractors (Markdown, etc.) plug in here.
"""
from .types import (
    CIR_TYPES,
    STYLE_TAGS,
    SPAN_MARKS,
    make_block,
    make_span,
)
from .extractor_docx import extract_docx

__all__ = [
    "CIR_TYPES",
    "STYLE_TAGS",
    "SPAN_MARKS",
    "make_block",
    "make_span",
    "extract_docx",
]
