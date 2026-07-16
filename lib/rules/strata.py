"""
Stratum detection — amendment spec v2.2 §2.2, iteration 4.

A stratum is a horizontal layer of the document where landmarks may
live: one per heading level, plus THE short-styled-paragraph stratum
(visual tags gate candidacy there — "tags locate the stratum, never
promote a block alone").

The dominant landmark stratum is the stratum with the most chapter-class
pattern matches (Frankenstein: H3's 27 beat H2's 3; DQ: H3's 126 vs 0;
Hatch: the paragraph stratum's 9). Part-class matches do NOT vote —
part-words win in any stratum per §2.3 and never define where chapters
live (Leaves: 34 BOOK matches, zero chapter matches → no dominant
stratum → 0 chapters, by design).

Coherence note: the spec asks for "the most members forming a coherent
numbered sequence." On all six corpus books plain match-count picks the
same stratum a sequence-coherence metric would; the count is the
implementation, ties broken by earliest first match in document order.
Recorded in MIGRATION_NOTES as a documented simplification — revisit if
a future book produces a tie or a large incoherent cluster.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .landmarks import LandmarkScan, match_landmark_lines, normalize_ws

__all__ = [
    "SHORT_TEXT_MAX",
    "PARAGRAPH_VISUAL_STRATUM",
    "stratum_key",
    "is_visually_gated",
    "analyze_strata",
    "StrataAnalysis",
]

# "Short" for the styled-paragraph stratum gate. The spec gives the
# gate's shape (short + centered + bold/large_font) but no number; 120
# normalized chars clears every corpus landmark (longest: Hatch's
# "CHAPTER TWENTY-THREE") while excluding body paragraphs. Config
# constant on purpose.
SHORT_TEXT_MAX = 120

PARAGRAPH_VISUAL_STRATUM: Tuple[str, ...] = ("paragraph_visual",)


def _block_text(block: Dict[str, Any]) -> str:
    if "spans" in block:
        return "".join(s.get("text", "") for s in block["spans"])
    return block.get("text", "") or ""


def has_visual(block: Dict[str, Any], name: str) -> bool:
    """True when a visual property applies to the whole block: present
    in style_tags, OR carried as a span mark on EVERY non-empty span
    (the DOCX extractor emits run styling like bold/italic as span
    marks, not block tags — Hatch's chapter paragraphs are the
    motivating case)."""
    if name in (block.get("style_tags") or []):
        return True
    spans = [s for s in (block.get("spans") or []) if (s.get("text") or "").strip()]
    return bool(spans) and all(name in (s.get("marks") or []) for s in spans)


def is_visually_gated(block: Dict[str, Any]) -> bool:
    """§2.2 paragraph-stratum gate: short + centered + (bold OR
    large_font). Never promotes a block alone — only locates the
    stratum it may vote in.
    """
    if block.get("type") != "paragraph":
        return False
    if not has_visual(block, "centered"):
        return False
    if not (has_visual(block, "bold") or has_visual(block, "large_font")):
        return False
    return len(normalize_ws(_block_text(block))) <= SHORT_TEXT_MAX


def stratum_key(block: Dict[str, Any]) -> Optional[Tuple]:
    """The stratum a block belongs to, or None when the block cannot
    carry landmarks (body paragraphs without the visual gate, tables,
    images, ...).
    """
    if block.get("type") == "heading":
        return ("heading", block.get("heading_level") or 0)
    if is_visually_gated(block):
        return PARAGRAPH_VISUAL_STRATUM
    return None


@dataclass
class StrataAnalysis:
    """Result of the §2.2 sweep.

    dominant: stratum key of the dominant landmark stratum, or None
        when no stratum produced any chapter-class match.
    chapter_counts: stratum key → count of chapter-class matches.
    scans: block id → LandmarkScan for every block that sits in ANY
        stratum (classifier reuses these instead of re-scanning).
    strata_of: block id → stratum key for the same population.
    """
    dominant: Optional[Tuple]
    chapter_counts: Dict[Tuple, int] = field(default_factory=dict)
    scans: Dict[str, LandmarkScan] = field(default_factory=dict)
    strata_of: Dict[str, Tuple] = field(default_factory=dict)


def analyze_strata(blocks: List[Dict[str, Any]]) -> StrataAnalysis:
    chapter_counts: Dict[Tuple, int] = {}
    first_match_pos: Dict[Tuple, int] = {}
    scans: Dict[str, LandmarkScan] = {}
    strata_of: Dict[str, Tuple] = {}

    for pos, block in enumerate(blocks):
        # I-10 extension (rules 1.2): blocks already claimed by an
        # earlier classifier — C-007's source-TOC blocks are the
        # motivating case — neither vote for a stratum nor carry
        # landmarks. Before C-007 existed nothing had a role at
        # analysis time, so this is a no-op for the 1.1 corpus.
        if block.get("role"):
            continue
        key = stratum_key(block)
        if key is None:
            continue
        bid = block.get("id") or f"__pos_{pos}"
        strata_of[bid] = key
        scan = match_landmark_lines(_block_text(block))
        scans[bid] = scan
        m = scan.match
        if m is not None and m.kind == "chapter":
            chapter_counts[key] = chapter_counts.get(key, 0) + 1
            first_match_pos.setdefault(key, pos)

    dominant: Optional[Tuple] = None
    if chapter_counts:
        dominant = min(
            chapter_counts,
            key=lambda k: (-chapter_counts[k], first_match_pos[k]),
        )

    return StrataAnalysis(
        dominant=dominant,
        chapter_counts=chapter_counts,
        scans=scans,
        strata_of=strata_of,
    )
