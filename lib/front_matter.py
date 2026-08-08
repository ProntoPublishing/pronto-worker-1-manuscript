"""
Front-Matter Contract v1 — the `front_matter` artifact section (W1).

Doc of record: `4 - Automation System/FrontMatter_Contract_v1.md`
(Jesse's ruling 2026-07-28; C signed with amendments A1/A2/A3).

W1 CLASSIFIES, W2 RESPECTS. This module is the seam between them: it
derives a declarative summary of the front matter the MANUSCRIPT
carries, so W2 can suppress the generator for any element the author
already made — without W2 re-deriving classification from raw blocks.

Shape (contract §"W1 — CLASSIFY"):

    "front_matter": {
      "elements": [
        {"class": "title_page", "block_range": ["b_000001", "b_000003"],
         "confidence": "high", "source": "manuscript"},
        {"class": "dedication", "block_range": ["b_000004", "b_000004"],
         "confidence": "high", "source": "manuscript"}
      ],
      "carried": ["dedication", "title_page"]     // sorted, dedup'd
    }

`carried` is the fast path for W2's suppression map: membership answers
"did the author already make this?" for every generatable element.

DISJOINTNESS (amendment A1): distinct elements always occupy distinct
block ranges. Two adjacent blocks of DIFFERENT class never merge; the
V-007 defect was exactly a merged range ("5 title_page blocks spanning
b_000001..b_000006" that had eaten the dedication). Contiguous blocks
of the SAME class do group — that is one element spanning several
blocks (a three-line title page is one title page).

Author-content classes (foreword/preface/introduction/prologue/
note_to_reader) are reported for completeness but are NEVER generated
by W2, so they are not part of `carried`'s suppression contract — they
already pass through untouched today.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Contract classes W2 can GENERATE — membership in `carried` suppresses
# the corresponding generator (contract §"W2 — RESPECT").
GENERATABLE_CLASSES = (
    "title_page",
    "copyright_page",
    "dedication",
    "acknowledgements",
    "about_the_author",
    "toc_authorial",
)

# Classes that are author content W2 never generates — recorded for the
# manifest/audit surface only.
AUTHOR_ONLY_CLASSES = (
    "half_title",
    "epigraph",
    "foreword",
    "preface",
    "introduction",
    "prologue",
    "note_to_reader",
    "unknown_front",
)

# (role, subtype) -> contract class. Subtype is matched case-folded and
# prefix-wise for the back-matter labels, whose text varies.
_ROLE_TO_CLASS = {
    "title_page": "title_page",
}

_FRONT_SUBTYPE_TO_CLASS = {
    "half_title": "half_title",
    "copyright": "copyright_page",
    "copyright_page": "copyright_page",
    "dedication": "dedication",
    "epigraph": "epigraph",
    "foreword": "foreword",
    "preface": "preface",
    "introduction": "introduction",
    "prologue": "prologue",
    "note_to_reader": "note_to_reader",
    "generic": "unknown_front",
}


def _classify_block(block: Dict[str, Any]) -> Optional[str]:
    """The contract class for one classified block, or None when the
    block is not front/back matter the contract speaks about."""
    role = block.get("role")
    subtype = str(block.get("subtype") or "").strip().lower()

    if role in _ROLE_TO_CLASS:
        return _ROLE_TO_CLASS[role]

    if role == "front_matter":
        return _FRONT_SUBTYPE_TO_CLASS.get(subtype, "unknown_front")

    if role == "back_matter":
        # about-the-author may live in back matter; the contract says
        # classify it wherever found. Acknowledgements likewise.
        if subtype.startswith("about"):
            return "about_the_author"
        if subtype.startswith("acknowledg"):
            return "acknowledgements"
        return None

    if role == "structural" and subtype == "source_toc":
        # An authorial typed TOC (C-007) — suppresses W2's generated one.
        return "toc_authorial"

    return None


def _confidence(cls: str) -> str:
    """unknown_front is the honest low-confidence bucket; everything
    else was matched by an explicit signal. Low confidence is a
    manifest warning surface, never a hold (contract §W1)."""
    return "low" if cls == "unknown_front" else "high"


def build_front_matter_section(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive the artifact's `front_matter` section from classified
    blocks. Pure function — reads, never mutates. Single pass."""
    elements: List[Dict[str, Any]] = []
    last_index: Optional[int] = None       # index of the previous member

    for i, block in enumerate(blocks):
        cls = _classify_block(block)
        if cls is None:
            continue
        bid = block.get("id")

        # Group ONLY with an immediately-adjacent member of the SAME
        # class. A different class always starts a new element, which is
        # what keeps ranges disjoint (A1); a gap does too.
        if elements and elements[-1]["class"] == cls and last_index == i - 1:
            elements[-1]["block_range"][1] = bid
        else:
            elements.append({
                "class": cls,
                "block_range": [bid, bid],
                "confidence": _confidence(cls),
                "source": "manuscript",
            })
        last_index = i

    carried = sorted({e["class"] for e in elements
                      if e["class"] in GENERATABLE_CLASSES})

    return {"elements": elements, "carried": carried}
