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
# C-006: chapter_subtitle promotion (spec §2.3 "Below → chapter_subtitle")
# ---------------------------------------------------------------------------

class C006_ChapterSubtitle:
    """C-006 v1: promote the block adjacent-below a landmark to
    role=chapter_subtitle when it is short AND style-gated.

    Spec §2.3: "Carol's stave names (H4), Hatch's italic subtitles:
    adjacent-below a landmark + short + style-gated (italic, centered,
    or subordinate heading level) — never position alone."

    Gates (ALL required):
      - adjacent-below a chapter_heading or part_divider (empty_line
        paragraphs between are skipped — they are layout, not content);
      - unclassified (I-10);
      - type paragraph or heading;
      - short (normalized length <= strata.SHORT_TEXT_MAX) and carrying
        at least one letter/digit (scene-break markers like "* * *"
        must not promote);
      - style gate: 'italic' tag, OR 'centered' tag, OR a heading level
        subordinate to a heading-typed landmark.

    Rule id note: the amendment spec names no Doc 22 id for this rule;
    C-006 is the next free classifier id, to be confirmed when Doc 22
    v1.1 is drafted (MIGRATION_NOTES).
    """

    id = "C-006"
    phase = "classify"
    order = 3
    version = "v1"

    _LANDMARK_ROLES = {"chapter_heading", "part_divider"}

    def run(self, ctx: RuleContext) -> None:
        from .strata import SHORT_TEXT_MAX

        blocks = ctx.blocks
        for i, landmark in enumerate(blocks):
            if landmark.get("role") not in self._LANDMARK_ROLES:
                continue
            j = self._next_content_index(blocks, i + 1)
            if j is None:
                continue
            cand = blocks[j]
            if _has_role(cand):
                continue
            if cand.get("type") not in ("paragraph", "heading"):
                continue
            text = normalize_ws(_block_text(cand))
            if not text or len(text) > SHORT_TEXT_MAX:
                continue
            if not any(ch.isalnum() for ch in text):
                continue
            gate = self._style_gate(cand, landmark)
            if gate is None:
                continue
            cand["role"] = "chapter_subtitle"
            _add_note(
                cand,
                f"chapter_subtitle promoted (§2.3): adjacent-below "
                f"{landmark.get('id')}, gate: {gate}",
            )

    @staticmethod
    def _next_content_index(blocks, start: int) -> Optional[int]:
        for j in range(start, len(blocks)):
            b = blocks[j]
            tags = b.get("style_tags") or []
            if b.get("type") == "paragraph" and "empty_line" in tags:
                continue
            if not normalize_ws(_block_text(b)):
                continue
            return j
        return None

    @staticmethod
    def _style_gate(cand, landmark) -> Optional[str]:
        tags = cand.get("style_tags") or []
        if "italic" in tags:
            return "italic tag"
        if "centered" in tags:
            return "centered tag"
        if (
            cand.get("type") == "heading"
            and landmark.get("type") == "heading"
            and (cand.get("heading_level") or 0)
            > (landmark.get("heading_level") or 0)
        ):
            return (
                f"subordinate heading level "
                f"(H{cand.get('heading_level')} under "
                f"H{landmark.get('heading_level')})"
            )
        return None


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
    """C-003 v2 — spec §3 redesign: all three v1 preconditions decoupled.

    v1 died on all six corpus books via three distinct precondition
    failures (no-landmark / no-tags / heading-typed-cluster). v2:

      - Cluster bounded by POSITION AND SHAPE, landmark-independent:
        the window runs from document start to the first sustained body
        run (2+ consecutive long unclassified paragraphs), capped at
        _WINDOW_MAX_BLOCKS.
      - Accepts paragraph AND heading blocks.
      - Scores each short candidate by independent signals — style tags
        (centered / large_font), heading level (H1/H2), early position.
        Qualification = 2+ distinct signals, so no single precondition
        is load-bearing. (Threshold choice recorded in MIGRATION_NOTES.)
      - The author line keeps its v1 adjacency exception: a short block
        immediately after qualified members that matches the byline
        shape ("By X" / short capitalized-name line) joins the cluster.

    Q3 ruling: the mechanism that satisfied extraction is recorded in
    classification_notes on every member ("qualified via: …") and
    summarized at ctx.extras["c003_mechanism"] ("tag path" when any
    member qualified through style tags, else "position/shape path") —
    the P&P acceptance row must name which fired.

    H-001 unchanged; reads ctx.manuscript_meta as before.
    """

    id = "C-003"
    phase = "classify"
    order = 6
    version = "v2"

    _WINDOW_MAX_BLOCKS = 40
    _SHAPE_MAX_CHARS = 200      # candidate shortness (shape gate)
    _BODY_RUN_CHARS = 200       # a long paragraph, for the body-run bound
    _BODY_RUN_LEN = 2           # consecutive long paragraphs ending the window
    _EARLY_POSITION = 8         # "early" = among the first N content blocks

    _BYLINE_RE = re.compile(r"^by\s+\S+", re.IGNORECASE)
    _NAME_RE = re.compile(r"^(?:[A-Z][\w.'’-]*\s+){0,3}[A-Z][\w.'’-]*$")

    def run(self, ctx: RuleContext) -> None:
        window = self._window(ctx.blocks)
        if not window:
            return

        # Score candidates inside the window.
        members: List[int] = []           # indices into ctx.blocks
        signals_by_idx: Dict[int, List[str]] = {}
        content_seen = 0
        tag_path_used = False
        for i in window:
            b = ctx.blocks[i]
            text = normalize_ws(_block_text(b))
            if not text:
                continue
            content_seen += 1
            if b.get("role") in ("chapter_heading", "part_divider"):
                # The window never REQUIRES landmarks (§3 independence)
                # but a title page cannot start past the first one.
                break
            if _has_role(b):
                continue
            if b.get("type") not in ("paragraph", "heading"):
                continue
            if len(text) >= self._SHAPE_MAX_CHARS:
                continue
            if not any(ch.isalnum() for ch in text):
                continue  # ornament lines ("* * *") are not title material

            signals: List[str] = []
            tags = b.get("style_tags") or []
            if "centered" in tags:
                signals.append("tag:centered")
            if "large_font" in tags:
                signals.append("tag:large_font")
            if b.get("type") == "heading" and (b.get("heading_level") or 9) <= 2:
                signals.append(f"level:h{b.get('heading_level')}")
            if content_seen <= self._EARLY_POSITION:
                signals.append("position:early")

            if len(signals) >= 2:
                if members and i - members[-1] > 3:
                    break  # cluster is contiguous-ish; a far gap ends it
                members.append(i)
                signals_by_idx[i] = signals
                if any(s.startswith("tag:") for s in signals):
                    tag_path_used = True
            elif members:
                # Byline adjacency exception (v1-carryover): short
                # unqualified block directly after the cluster that
                # looks like an author line.
                if i == members[-1] + 1 and (
                    self._BYLINE_RE.match(text) or self._NAME_RE.match(text)
                ):
                    members.append(i)
                    signals_by_idx[i] = ["shape:byline", "position:adjacent"]
                break  # cluster ends at the first non-qualifying content
        if not members:
            return

        mechanism = "tag path" if tag_path_used else "position/shape path"
        ctx.extras["c003_mechanism"] = mechanism

        extracted = {"title": None, "subtitle": None, "author": None}
        subtitle_parts: List[str] = []
        for idx, i in enumerate(members):
            block = ctx.blocks[i]
            block["role"] = "title_page"
            positional = self._positional(block, idx, signals_by_idx[i])
            _add_note(block, f"title_page positional role: {positional}")
            _add_note(
                block,
                f"title_page qualified via: {'+'.join(signals_by_idx[i])} "
                f"(C-003 v2 {mechanism})",
            )
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

        if ctx.manuscript_meta is None:
            ctx.manuscript_meta = extracted
        else:
            for k, v in extracted.items():
                if v is not None and not ctx.manuscript_meta.get(k):
                    ctx.manuscript_meta[k] = v

    # -- helpers ------------------------------------------------------------

    def _window(self, blocks: List[Dict[str, Any]]) -> List[int]:
        """Indices from document start to the first sustained body run
        (landmark-independent), capped at _WINDOW_MAX_BLOCKS."""
        out: List[int] = []
        long_run = 0
        for i, b in enumerate(blocks):
            if i >= self._WINDOW_MAX_BLOCKS:
                break
            text = normalize_ws(_block_text(b))
            if (
                b.get("type") == "paragraph"
                and not _has_role(b)
                and len(text) >= self._BODY_RUN_CHARS
            ):
                long_run += 1
                if long_run >= self._BODY_RUN_LEN:
                    # The run itself is body — drop its already-collected
                    # first member(s) from the window.
                    return [j for j in out if j < i - (long_run - 1)]
            else:
                long_run = 0
            out.append(i)
        return out

    def _positional(
        self, block: Dict[str, Any], idx_in_cluster: int, signals: List[str],
    ) -> str:
        if idx_in_cluster == 0:
            return "title"
        if "shape:byline" in signals:
            return "author_or_byline"
        tags = block.get("style_tags") or []
        if "large_font" in tags or block.get("type") == "heading":
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
