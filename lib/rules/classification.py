"""
Layer 2 classification rules — C-001 through C-005.

Per Doc 22 v1.0.1 §Layer 2 and §Execution Phase Ordering. All classifiers
honor I-10 (non-overwrite): a classifier skips any block that already
carries a non-null role assigned by an earlier-ordered classifier. That
invariant is what keeps C-003 (title_page, order 5) from clobbering
chapter_heading / part_divider / front_matter / back_matter assignments,
and what keeps C-005's back-matter pattern library from re-labeling a
part_divider titled "Resources."

Classifiers extract role-specific fields where the v2.0 schema supports
them: chapter_number/chapter_title (C-001), part_number/part_title/
force_page_break (C-002), subtype (C-004, C-005). C-003's title/subtitle/
author extraction has no schema-supported home yet — see iter-3 schema gap
note at the bottom of this file.
"""
from __future__ import annotations
import re
from typing import Dict, List, Any, Optional, Set

from .base import RuleContext


# Patterns from Doc 22 v1.0.1. DOTALL so the `.+` capturing a title can
# span embedded newlines — the Long Quiet style of "Chapter 1\nTitle" is
# the motivating case.
_C001_CHAPTER = re.compile(
    r"^(Chapter|Ch\.?|CHAPTER)\s+([\w\d]+)(?:[\s\n:.]+(.+))?",
    re.IGNORECASE | re.DOTALL,
)
_C002_PART = re.compile(
    r"^(Part|Book|Section)\s+([\w\d]+)[\s\n:.]+(.+)",
    re.IGNORECASE | re.DOTALL,
)
_C004_FRONT = re.compile(
    r"^(a\s+)?(note|preface|foreword|introduction|dedication|epigraph|prologue|to\s+the\s+reader).*",
    re.IGNORECASE | re.DOTALL,
)
_C005_BACK = re.compile(
    r"^(a\s+)?(closing|afterword|epilogue|acknowledgments?|about\s+the\s+author|appendix|resources|notes|bibliography|references|glossary|index).*",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _block_text(block: Dict[str, Any]) -> str:
    """Concatenate a block's text content across spans or return .text."""
    if "spans" in block:
        return "".join(s.get("text", "") for s in block["spans"])
    return block.get("text", "") or ""


def _has_role(block: Dict[str, Any]) -> bool:
    """True if the block already has a non-null, non-empty role (I-10)."""
    r = block.get("role")
    return r is not None and r != ""


def _parse_number(raw: str) -> Any:
    """Parse a chapter/part number: int if numeric, otherwise the raw
    string. Caller may choose to treat a non-numeric value as null.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw  # "One", "III", etc. — keep verbatim.


# ---------------------------------------------------------------------------
# C-001: Chapter heading detection
# ---------------------------------------------------------------------------

class C001_ChapterHeading:
    """C-001 v1 (with v1.0.1 Patch 3 regex): classify heading-level-2 blocks
    as role=chapter_heading, extracting chapter_number and chapter_title.

    Per-block behavior (per Doc 22 v1.0.1 C-001):
      - Apply the pattern to the block text.
      - If the pattern matches and the title group is present: role=
        chapter_heading, chapter_number=<parsed group 2>, chapter_title=
        <trimmed group 3>.
      - If the pattern matches but the title group is absent (number-only
        heading, e.g., "Chapter 5"): synthesize chapter_title="Chapter <N>"
        and add a classification_notes[] entry.
      - If the pattern fails but the block is heading-level-2: role=
        chapter_heading, chapter_number=null, chapter_title=<full text>,
        classification_notes[]=["chapter_number not extractable"].
      - Blocks with an existing non-null role are skipped (I-10).
    """

    id = "C-001"
    phase = "classify"
    order = 1
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        for block in ctx.blocks:
            if _has_role(block):
                continue
            if block.get("type") != "heading" or block.get("heading_level") != 2:
                continue

            text = _block_text(block).strip()
            m = _C001_CHAPTER.match(text)

            if m:
                num_raw = m.group(2)
                title_raw = m.group(3)
                number = _parse_number(num_raw)
                block["role"] = "chapter_heading"
                if title_raw:
                    block["chapter_number"] = number
                    block["chapter_title"] = title_raw.strip()
                else:
                    # Number-only: synthesize the title.
                    block["chapter_number"] = number
                    block["chapter_title"] = f"Chapter {num_raw}"
                    _add_note(block,
                        f"chapter_title synthesized from number-only heading")
            else:
                # Fallback: heading-level-2 without a recognizable pattern.
                block["role"] = "chapter_heading"
                block["chapter_number"] = None
                block["chapter_title"] = text if text else "Untitled"
                _add_note(block, "chapter_number not extractable")


# ---------------------------------------------------------------------------
# C-002: Part divider detection
# ---------------------------------------------------------------------------

class C002_PartDivider:
    """C-002 v1: classify heading-level-1 blocks whose text matches the
    Part/Book/Section pattern as role=part_divider.

    Emits part_number, part_title, and force_page_break=true per I-5.
    Skips blocks with an existing non-null role (I-10). Unmatched
    heading-level-1 blocks are left for C-004 / C-005 to consider.
    """

    id = "C-002"
    phase = "classify"
    order = 2
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        for block in ctx.blocks:
            if _has_role(block):
                continue
            if block.get("type") != "heading" or block.get("heading_level") != 1:
                continue

            text = _block_text(block).strip()
            m = _C002_PART.match(text)
            if not m:
                continue

            num_raw = m.group(2)
            title_raw = (m.group(3) or "").strip()
            block["role"] = "part_divider"
            block["part_number"] = _parse_number(num_raw)
            block["part_title"] = title_raw
            block["force_page_break"] = True


# ---------------------------------------------------------------------------
# C-004: Front-matter classification
# ---------------------------------------------------------------------------

class C004_FrontMatter:
    """C-004 v1 (with v1.0.1 Patch 5 disambiguation): classify heading-level-1
    blocks appearing before the first block with role=chapter_heading or
    role=part_divider as role=front_matter.

    Pattern library matches a set of canonical labels; subtype is the
    matched label. When no pattern matches but the block is structurally
    a heading-level-1 in pre-chapter position, emit subtype="generic" per
    I-6 with a classification_notes[] entry. Skips blocks with existing
    non-null role (I-10).
    """

    id = "C-004"
    phase = "classify"
    order = 3
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        cutoff_idx = _first_index_with_role(ctx.blocks, {"chapter_heading", "part_divider"})
        # If nothing is classified yet as chapter/part, there is no
        # front-matter cutoff and C-004 does not fire.
        if cutoff_idx is None:
            return

        for i in range(cutoff_idx):
            block = ctx.blocks[i]
            if _has_role(block):
                continue
            if block.get("type") != "heading" or block.get("heading_level") != 1:
                continue

            text = _block_text(block).strip()
            m = _C004_FRONT.match(text)
            if m:
                subtype = _front_subtype_from_match(m)
                block["role"] = "front_matter"
                block["subtype"] = subtype
                block["title"] = text  # role-specific field; kept for downstream.
            else:
                block["role"] = "front_matter"
                block["subtype"] = "generic"
                block["title"] = text
                _add_note(block, "front_matter subtype not recognized")


def _front_subtype_from_match(m: "re.Match[str]") -> str:
    """Map the matched front-matter label to a canonical subtype token."""
    raw = (m.group(2) or "").strip().lower()
    # Normalize a few multi-word variants.
    if raw.startswith("to the reader"):
        return "note_to_reader"
    if raw.startswith("note"):
        return "note_to_reader"
    return raw  # preface, foreword, introduction, dedication, epigraph, prologue


# ---------------------------------------------------------------------------
# C-005: Back-matter classification
# ---------------------------------------------------------------------------

class C005_BackMatter:
    """C-005 v1 (with v1.0.1 Patch 5 disambiguation): classify heading-level-1
    blocks appearing AFTER the last block with role=chapter_heading as
    role=back_matter.

    Pattern library matches canonical labels; subtype is the matched
    label. Unmatched heading-level-1 blocks in post-last-chapter position
    get subtype="generic" per I-6. Skips blocks with existing non-null
    role (I-10) — this is what prevents a part_divider titled "Resources"
    from being re-labeled back_matter.
    """

    id = "C-005"
    phase = "classify"
    order = 4
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        cutoff_idx = _last_index_with_role(ctx.blocks, {"chapter_heading"})
        if cutoff_idx is None:
            return

        for i in range(cutoff_idx + 1, len(ctx.blocks)):
            block = ctx.blocks[i]
            if _has_role(block):
                continue
            if block.get("type") != "heading" or block.get("heading_level") != 1:
                continue

            text = _block_text(block).strip()
            m = _C005_BACK.match(text)
            if m:
                subtype = _back_subtype_from_match(m)
                block["role"] = "back_matter"
                block["subtype"] = subtype
                block["title"] = text
            else:
                block["role"] = "back_matter"
                block["subtype"] = "generic"
                block["title"] = text
                _add_note(block, "back_matter subtype not recognized")


def _back_subtype_from_match(m: "re.Match[str]") -> str:
    raw = (m.group(2) or "").strip().lower()
    if raw == "about the author":
        return "about_the_author"
    if raw in ("acknowledgments", "acknowledgment"):
        return "acknowledgments"
    # "closing" comes from "A Closing Letter" — canonical token.
    return raw  # afterword, epilogue, appendix, resources, notes, bibliography, references, glossary, index


# ---------------------------------------------------------------------------
# C-003: Title page detection — runs LAST within Classify
# ---------------------------------------------------------------------------

class C003_TitlePage:
    """C-003 v1 (with v1.0.1 Patch 5 reword): identify the opening cluster
    of paragraphs that appear before any block with role ∈
    {chapter_heading, part_divider, front_matter, back_matter}, and mark
    qualifying members as role=title_page.

    Qualification per block (per Doc 22 v1.0.1 C-003):
      - style_tags[] contains 'centered'
      - style_tags[] contains 'large_font' OR the block is the author line
        immediately following large-font blocks
      - text length < 200 chars
      - no existing role (I-10)

    Title / subtitle / author extraction (what Doc 22 v1.0.1 calls
    "extract {title, subtitle, author}") currently records its findings
    in classification_notes[] per block. The v2.0 schema doesn't yet
    define block-level fields for those tokens. See iter-3 schema gap
    note at the bottom of this file.
    """

    id = "C-003"
    phase = "classify"
    order = 5
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        cutoff_idx = _first_index_with_role(
            ctx.blocks,
            {"chapter_heading", "part_divider", "front_matter", "back_matter"},
        )
        if cutoff_idx is None:
            return  # no classified landmark → no title-page cluster to bound.

        # Collect candidate cluster members: paragraphs up to the cutoff,
        # all centered, all short, none already role-assigned.
        candidates: List[int] = []
        for i in range(cutoff_idx):
            b = ctx.blocks[i]
            if _has_role(b):
                continue
            if b.get("type") != "paragraph":
                continue
            tags = b.get("style_tags") or []
            if "centered" not in tags:
                continue
            if len(_block_text(b)) >= 200:
                continue
            candidates.append(i)

        if not candidates:
            return

        # Qualify the cluster: the first block with large_font anchors it.
        # Allow the immediately-following block (the author line) even if
        # it doesn't carry large_font — the byline typically sits below
        # title/subtitle in smaller type but is still part of the cluster.
        large_font_seen = False
        cluster_members: List[int] = []
        for i in candidates:
            tags = ctx.blocks[i].get("style_tags") or []
            if "large_font" in tags:
                large_font_seen = True
                cluster_members.append(i)
            elif large_font_seen and (not cluster_members or i == cluster_members[-1] + 1):
                cluster_members.append(i)
            else:
                # Cluster broken — subsequent centered paragraphs don't
                # belong to a title page if we've left the contiguous
                # run following large_font anchors.
                break

        if not cluster_members:
            return

        # Assign role + positional note. First member = title, subsequent
        # large_font members = subtitle (joined if there are several),
        # non-large_font trailing member = author/byline. The positional
        # tag goes on each block's classification_notes[] for traceability;
        # the authoritative extraction lands on ctx.manuscript_meta, which
        # emit() surfaces at the artifact top level.
        extracted = {"title": None, "subtitle": None, "author": None}
        subtitle_parts: List[str] = []
        for idx, i in enumerate(cluster_members):
            block = ctx.blocks[i]
            block["role"] = "title_page"
            positional = _title_page_positional_role(block, idx, cluster_members, ctx.blocks)
            _add_note(block, f"title_page positional role: {positional}")

            text = _block_text(block).strip()
            if positional == "title" and not extracted["title"]:
                extracted["title"] = text or None
            elif positional == "subtitle":
                if text:
                    subtitle_parts.append(text)
            elif positional == "author_or_byline" and not extracted["author"]:
                extracted["author"] = text or None

        if subtitle_parts:
            extracted["subtitle"] = " ".join(subtitle_parts)

        # Merge with any prior manuscript_meta (classifier-order doesn't
        # currently have another writer, but keep the merge defensive).
        if ctx.manuscript_meta is None:
            ctx.manuscript_meta = extracted
        else:
            for k, v in extracted.items():
                if v is not None and not ctx.manuscript_meta.get(k):
                    ctx.manuscript_meta[k] = v


def _title_page_positional_role(
    block: Dict[str, Any],
    idx_in_cluster: int,
    cluster_members: List[int],
    all_blocks: List[Dict[str, Any]],
) -> str:
    """Best-effort label for each title_page block's contribution to the
    cluster. Not structural — just a human/operator aid in
    classification_notes[].
    """
    if idx_in_cluster == 0:
        return "title"
    tags = block.get("style_tags") or []
    if "large_font" in tags:
        return "subtitle"
    return "author_or_byline"


# ---------------------------------------------------------------------------
# Shared index helpers
# ---------------------------------------------------------------------------

def _first_index_with_role(
    blocks: List[Dict[str, Any]],
    roles: Set[str],
) -> Optional[int]:
    for i, b in enumerate(blocks):
        if b.get("role") in roles:
            return i
    return None


def _last_index_with_role(
    blocks: List[Dict[str, Any]],
    roles: Set[str],
) -> Optional[int]:
    last = None
    for i, b in enumerate(blocks):
        if b.get("role") in roles:
            last = i
    return last


def _add_note(block: Dict[str, Any], note: str) -> None:
    notes = block.setdefault("classification_notes", [])
    notes.append(note)


# ---------------------------------------------------------------------------
# title_page extraction — resolution
# ---------------------------------------------------------------------------
#
# Iter-3 flagged a schema gap: C-003's rule entry says "extract {title,
# subtitle, author}" but the v2.0 block schema has no per-block fields
# for those. Resolved in iter-4 prep via option (b): a top-level
# `manuscript_meta: {title, subtitle, author}` object on the artifact
# (schema updated; emit threads ctx.manuscript_meta through).
#
# C-003 writes to `ctx.manuscript_meta`. Per-block positional tags
# ("title" / "subtitle" / "author_or_byline") remain in
# `classification_notes[]` for cluster traceability. The authoritative
# read surface for downstream workers and reconciliation rules is
# `artifact.manuscript_meta`.
