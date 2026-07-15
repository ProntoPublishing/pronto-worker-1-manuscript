"""
Layer 2 classification rules — C-001 through C-005.

C-001/C-002 are the Doc 22 v1.1 amendment cores (spec v2.2 + v2.2.1
rulings, iteration 4): pattern + dominant-stratum landmark
classification replaces the absolute-heading-level matching and the
H2→chapter_heading catch-all (~400 false chapters across the corpus).
C-004/C-005 remain Doc 22 v1.0.1. All classifiers honor I-10
(non-overwrite): a classifier skips any block that already carries a
non-null role assigned by an earlier-ordered classifier.

Classifiers extract role-specific fields where the schema supports
them: chapter_number/chapter_title/landmark_subtype (C-001),
part_number/part_title/force_page_break (C-001 part branch, C-002),
subtype (C-004, C-005). C-003 writes ctx.manuscript_meta.
"""
from __future__ import annotations
import re
from typing import Dict, List, Any, Optional, Set

from .base import RuleContext
from .landmarks import LandmarkMatch, match_landmark_lines, normalize_ws
from .strata import analyze_strata, is_visually_gated


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


# ---------------------------------------------------------------------------
# C-001: Landmark classification (Doc 22 v1.1 core — spec v2.2 §2.1–§2.3)
# ---------------------------------------------------------------------------

class C001_LandmarkClassification:
    """C-001 v2: pattern + dominant-stratum landmark classification.

    Replaces the v1 absolute-H2 matcher AND the H2 catch-all. Behavior
    (spec v2.2 §2.1/§2.1b/§2.2/§2.3 + v2.2.1 rulings Q1/Q2):

      1. §2.2 — run stratum analysis (each heading level + the visually
         gated short-paragraph stratum); the dominant landmark stratum
         is where chapter-class landmarks live. Analysis is cached at
         ctx.extras["strata"] for C-002 and validators.
      2. Per candidate block, the Q1 two-stage scan (whole-text first,
         per-line fallback, exactly-one-line rule).
      3. Part-class match → part_divider in ANY stratum, precedence
         over chapter_heading (§2.3 / DQ Amendment 1).
      4. Chapter-class match → chapter_heading ONLY inside the dominant
         stratum (the catch-all is dead; chapter-shaped text elsewhere
         falls through to C-004/C-005/terminal default).
      5. §2.1b unnumbered ({Prologue, Epilogue}) → chapter_heading with
         chapter_number null + landmark_subtype, valid in the dominant
         stratum or under the visual gates.
      6. Q2 fused matches emit the ruled normalization warning; Q1
         ambiguous scans (2+ matching lines) emit a warning and leave
         the block unclassified.

    Unmatched blocks are NOT defaulted here — generic `heading` role
    arrives via the terminal default; front/back matter via C-004/C-005.
    """

    id = "C-001"
    phase = "classify"
    order = 1
    version = "v2"

    def run(self, ctx: RuleContext) -> None:
        analysis = analyze_strata(ctx.blocks)
        ctx.extras["strata"] = analysis

        for pos, block in enumerate(ctx.blocks):
            if _has_role(block):
                continue
            bid = block.get("id") or f"__pos_{pos}"
            key = analysis.strata_of.get(bid)
            if key is None:
                continue  # not a landmark-candidate carrier
            scan = analysis.scans.get(bid)
            if scan is None:
                continue
            in_dominant = (
                analysis.dominant is not None and key == analysis.dominant
            )

            if scan.ambiguous:
                if in_dominant:
                    ctx.warnings.append({
                        "rule": "C-001",
                        "severity": "medium",
                        "detail": (
                            f"ambiguous landmark block: "
                            f"{scan.matching_line_count} lines match the "
                            f"landmark pattern (Q1 exactly-one-line rule) — "
                            f"left unclassified"
                        ),
                        "block_id": block.get("id"),
                    })
                continue

            m = scan.match
            if m is None:
                continue

            if m.kind == "part":
                # §2.3: part-class words win in ANY stratum.
                self._assign_part(ctx, block, m)
            elif m.kind == "chapter":
                if not in_dominant:
                    continue  # catch-all is dead — no absolute-level promotion
                self._assign_chapter(ctx, block, m)
            elif m.kind == "unnumbered":
                # §2.1b: dominant stratum or visual gates.
                if in_dominant or is_visually_gated(block):
                    self._assign_unnumbered(ctx, block, m)

    # -- assignment helpers -------------------------------------------------

    def _assign_part(
        self, ctx: RuleContext, block: Dict[str, Any], m: LandmarkMatch,
    ) -> None:
        block["role"] = "part_divider"
        block["part_number"] = m.ordinal
        block["part_title"] = (
            m.trailing_title
            or f"{m.section_word.title()} {m.ordinal_display}"
        )
        block["force_page_break"] = True
        self._common_notes(ctx, block, m)

    def _assign_chapter(
        self, ctx: RuleContext, block: Dict[str, Any], m: LandmarkMatch,
    ) -> None:
        block["role"] = "chapter_heading"
        block["chapter_number"] = m.ordinal
        if m.trailing_title:
            block["chapter_title"] = m.trailing_title
        else:
            block["chapter_title"] = (
                f"{m.section_word.title()} {m.ordinal_display}"
            )
            _add_note(block, "chapter_title synthesized from number-only heading")
        self._common_notes(ctx, block, m)

    def _assign_unnumbered(
        self, ctx: RuleContext, block: Dict[str, Any], m: LandmarkMatch,
    ) -> None:
        block["role"] = "chapter_heading"
        block["chapter_number"] = None
        block["landmark_subtype"] = m.landmark_subtype
        text = normalize_ws(_block_text(block))
        block["chapter_title"] = m.trailing_title or text or "Untitled"
        _add_note(block, f"unnumbered landmark (§2.1b): {m.landmark_subtype}")
        self._common_notes(ctx, block, m)

    def _common_notes(
        self, ctx: RuleContext, block: Dict[str, Any], m: LandmarkMatch,
    ) -> None:
        if m.matched_via == "line":
            _add_note(
                block,
                f"matched per-line (Q1 fallback); {len(m.caption_lines)} "
                f"caption line(s) carried in block text for §2.3 treatment",
            )
        if m.ordinal_style:
            _add_note(block, f"ordinal style: {m.ordinal_style}")
        if m.fused:
            _add_note(block, "fused heading matched via Q2 no-space variant")
            ctx.warnings.append({
                "rule": "C-001",
                "severity": "low",
                "detail": (
                    f"probable missing space in heading: "
                    f"'{m.section_word}{m.ordinal_display}'"
                ),
                "block_id": block.get("id"),
            })


# ---------------------------------------------------------------------------
# C-002: Structural part detection (Doc 22 v1.1 — spec §2.3 above-stratum)
# ---------------------------------------------------------------------------

class C002_StructuralPartDetection:
    """C-002 v2: the repeated-book-title shape above the landmark stratum.

    Pattern-matching part-words are C-001 v2's job (any stratum). What
    remains for C-002 is Frankenstein's shape: identical heading blocks
    repeated in a stratum ABOVE the dominant landmark stratum (its three
    volume title pages) → part_divider with a null part_number.

    Only fires when the dominant stratum is a heading stratum (a
    paragraph-stratum book has no "above"). Skips role-carrying blocks
    (I-10).
    """

    id = "C-002"
    phase = "classify"
    order = 2
    version = "v2"

    def run(self, ctx: RuleContext) -> None:
        analysis = ctx.extras.get("strata")
        if analysis is None or analysis.dominant is None:
            return
        if analysis.dominant[0] != "heading":
            return
        dom_level = analysis.dominant[1]

        # Candidate population: unclassified heading blocks strictly
        # above (numerically lower level than) the dominant stratum.
        candidates: List[Dict[str, Any]] = [
            b for b in ctx.blocks
            if not _has_role(b)
            and b.get("type") == "heading"
            and (b.get("heading_level") or 0) < dom_level
        ]
        if len(candidates) < 2:
            return

        from collections import Counter
        texts = Counter(normalize_ws(_block_text(b)) for b in candidates)

        for b in candidates:
            norm = normalize_ws(_block_text(b))
            if norm and texts[norm] >= 2:
                b["role"] = "part_divider"
                b["part_number"] = None
                b["part_title"] = norm
                b["force_page_break"] = True
                _add_note(
                    b,
                    f"repeated-book-title shape (§2.3): identical heading "
                    f"×{texts[norm]} above the landmark stratum",
                )


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
