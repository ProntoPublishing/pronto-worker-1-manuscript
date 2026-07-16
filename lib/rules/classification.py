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
from .landmarks import (
    CHAPTER_CLASS_LEXICON,
    PART_CLASS_LEXICON,
    LandmarkMatch,
    match_landmark,
    match_landmark_lines,
    normalize_ws,
)
from .ordinals import parse_ordinal
from .strata import analyze_strata, is_visually_gated

# Marker note for blocks promoted by the rules-1.2 pattern-only path.
# V-006 (validation) scans for this exact prefix — keep them in sync.
PATTERN_ONLY_NOTE = "promoted via pattern-only path"


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
            base = m.trailing_title
        else:
            base = f"{m.section_word.title()} {m.ordinal_display}"
            _add_note(block, "chapter_title synthesized from number-only heading")
        # Caption routing (Q1 / §2.3): W2 renders chapter headings from
        # chapter_title alone, and its multi-line mechanism (W2 v1.3.1)
        # styles the label line and renders every other line as a
        # centered italic caption beneath. Caption lines therefore ride
        # IN chapter_title — leaving them only in the block text would
        # drop them from the rendered book (P&P's 34).
        if m.caption_lines:
            block["chapter_title"] = "\n".join([base, *m.caption_lines])
        else:
            block["chapter_title"] = base
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
    repeated in a stratum ABOVE the dominant landmark stratum (its
    volume title pages) → part_divider.

    Corpus-reality refinement (spec-premise mismatch, see
    MIGRATION_NOTES "Frankenstein 5-vs-3"): the 1818 source repeats the
    identical title FIVE times — three true volume pages (each followed
    by an "IN THREE VOLUMES. / VOL. n." block) plus two bare
    half-titles. When any repeated candidate has an adjacent following
    block whose per-line scan yields a part-class match, only the
    confirmed candidates become part_dividers, numbered from the
    adjacent match. When NO candidate confirms (the spec's imagined
    all-bare shape), every repeat classifies with part_number null —
    the rule "as before".

    Only fires when the dominant stratum is a heading stratum (a
    paragraph-stratum book has no "above"). Skips role-carrying blocks
    (I-10).
    """

    id = "C-002"
    phase = "classify"
    order = 2
    version = "v2"

    _ADJACENT_LOOKAHEAD = 3  # blocks to scan for the VOL-line confirmation

    def run(self, ctx: RuleContext) -> None:
        analysis = ctx.extras.get("strata")
        if analysis is None or analysis.dominant is None:
            return
        if analysis.dominant[0] != "heading":
            return
        dom_level = analysis.dominant[1]

        # Candidate population: unclassified heading blocks strictly
        # above (numerically lower level than) the dominant stratum.
        candidates: List[int] = [
            i for i, b in enumerate(ctx.blocks)
            if not _has_role(b)
            and b.get("type") == "heading"
            and (b.get("heading_level") or 0) < dom_level
        ]
        if len(candidates) < 2:
            return

        from collections import Counter
        texts = Counter(
            normalize_ws(_block_text(ctx.blocks[i])) for i in candidates
        )
        repeated = [
            i for i in candidates
            if normalize_ws(_block_text(ctx.blocks[i]))
            and texts[normalize_ws(_block_text(ctx.blocks[i]))] >= 2
        ]
        if not repeated:
            return

        confirmations = {i: self._adjacent_part_match(ctx.blocks, i)
                         for i in repeated}
        any_confirmed = any(m is not None for m in confirmations.values())

        for i in repeated:
            b = ctx.blocks[i]
            norm = normalize_ws(_block_text(b))
            m = confirmations[i]
            if any_confirmed and m is None:
                _add_note(
                    b,
                    "repeated-book-title candidate NOT confirmed by an "
                    "adjacent part marker — left for terminal default "
                    "(bare half-title; see MIGRATION_NOTES)",
                )
                continue
            b["role"] = "part_divider"
            b["part_number"] = m.ordinal if m else None
            b["part_title"] = norm
            b["force_page_break"] = True
            _add_note(
                b,
                f"repeated-book-title shape (§2.3): identical heading "
                f"×{texts[norm]} above the landmark stratum"
                + (f"; part_number {m.ordinal} from adjacent "
                   f"'{m.section_word} {m.ordinal_display}' marker"
                   if m else ""),
            )

    def _adjacent_part_match(self, blocks, i) -> Optional[LandmarkMatch]:
        """Scan a few following blocks for a part-class pattern line
        (Frankenstein's 'IN THREE VOLUMES. / VOL. n.' paragraph)."""
        seen = 0
        for j in range(i + 1, len(blocks)):
            if seen >= self._ADJACENT_LOOKAHEAD:
                return None
            b = blocks[j]
            text = _block_text(b)
            if not normalize_ws(text):
                continue  # empty_line spacers don't consume lookahead
            seen += 1
            if _has_role(b):
                return None
            scan = match_landmark_lines(text)
            if scan.match is not None and scan.match.kind == "part":
                return scan.match
            if scan.match is not None:
                return None  # a chapter landmark ends the title page
        return None


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
        from .strata import has_visual
        if has_visual(cand, "italic"):
            return "italic"
        if has_visual(cand, "centered"):
            return "centered"
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

        # The document's first content block, for the head-H1 guard.
        first_content_idx = next(
            (i for i, b in enumerate(ctx.blocks)
             if normalize_ws(_block_text(b))),
            None,
        )

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
                # Rules 1.2 guard (Book 16 regression): an UNRECOGNIZED
                # H1 that is the document's very first content block is
                # far more plausibly the book title than front matter —
                # leave it for C-003 (title-page detection, order 8).
                # Recognized labels above still classify normally, and
                # non-head generic H1s keep the I-6 fallback.
                if i == first_content_idx:
                    _add_note(
                        block,
                        "document-head H1 with unrecognized label left "
                        "for title-page detection (C-003; rules 1.2)",
                    )
                    continue
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
        # Display-styled members (large_font / heading-typed) read as
        # subtitle material, as in v1. For plain members, byline shape
        # ("By X") or a short name-shaped run of capitalized words is
        # the author; anything else (Hatch's long "Being a True…"
        # subtitle, which v1 mislabeled as the author) is subtitle.
        tags = block.get("style_tags") or []
        if "large_font" in tags or block.get("type") == "heading":
            return "subtitle"
        text = normalize_ws(_block_text(block))
        if self._BYLINE_RE.match(text):
            return "author_or_byline"
        if self._NAME_RE.match(text):
            from .ordinals import parse_ordinal
            # Roman-numeral years ("MCMXX") are name-shaped but not
            # authors; anything the ordinal parser accepts is excluded.
            if parse_ordinal(text.rstrip(".")) is None:
                return "author_or_byline"
        return "subtitle"


# ---------------------------------------------------------------------------
# C-007: Source-TOC detection (rules 1.2, Gate 2 ruling Q3)
# ---------------------------------------------------------------------------

# Inline-entry scanner for shape (a): landmark-pattern instances INSIDE
# one block's text ("Letter 1 Letter 2 … Chapter 24" as a single
# paragraph — Book 16's b_000007).
_INLINE_ENTRY_RE = re.compile(
    r"\b(?P<word>"
    + "|".join(re.escape(w) for w in sorted(
        CHAPTER_CLASS_LEXICON + PART_CLASS_LEXICON, key=len, reverse=True))
    + r")\s+(?P<ordinal>[A-Za-z0-9\-]+)",
    re.IGNORECASE,
)

_TOC_LABEL_RE = re.compile(r"^(table\s+of\s+)?contents[.:]?$", re.IGNORECASE)


class C007_SourceTocDetection:
    """C-007 v1 (rules 1.2, ruling Q3): detect the SOURCE's own table
    of contents and suppress it from body output without deleting it.

    Two shapes (both from Book 16/17 evidence):
      (a) a single block containing multiple landmark-pattern entries
          and almost nothing else;
      (b) a run of consecutive short paragraphs, each wholly matching a
          landmark pattern, with no intervening body text.
    Both must sit early in the document (_EARLY_BLOCKS window).

    Detected blocks get role="structural" + subtype="source_toc" —
    schema 2.1's enum already carries "structural", and W2's structural
    handler renders non-page-break/non-rule structural blocks as a
    traceability comment, so the blocks are suppressed from the
    rendered book but preserved in the artifact for audit. (Recorded in
    MIGRATION_NOTES_v1.2: the ruling offered "source_toc role or
    suppressed flag"; role=structural+subtype gets the same semantics
    with no schema bump and no W2 change.) An adjacent-above
    "Contents" / "Table of Contents" label block joins the detection.

    Parsed entries are stored at ctx.extras["source_toc_entries"] as
    (word, ordinal) tuples — C-008 uses them as CORROBORATION for
    pattern-only promotion (never a prerequisite, per ruling Q1).

    Runs FIRST in the classify phase so detected blocks are off the
    table before stratum analysis and every other classifier.
    Rule id C-007 is provisional; confirm at Doc 22 v1.2 drafting.
    """

    id = "C-007"
    phase = "classify"
    order = 1
    version = "v1"

    _EARLY_BLOCKS = 80        # detection window: first N blocks
    _MIN_ENTRIES = 3          # fewer pattern instances is not a TOC
    _MAX_RESIDUE_FRACTION = 0.2   # shape (a): non-entry alnum content cap
    _RUN_ENTRY_MAX_CHARS = 80     # shape (b): entry paragraphs are short

    def run(self, ctx: RuleContext) -> None:
        entries: List[tuple] = []
        window = min(self._EARLY_BLOCKS, len(ctx.blocks))

        # ---- shape (a): multi-entry single block --------------------
        for i in range(window):
            b = ctx.blocks[i]
            if _has_role(b) or b.get("type") not in ("paragraph", "heading"):
                continue
            text = normalize_ws(_block_text(b))
            if not text:
                continue
            found = self._inline_entries(text)
            if found is None:
                continue
            self._mark(b, f"shape (a): {len(found)} inline entries")
            self._mark_label_above(ctx.blocks, i)
            entries.extend(found)

        # ---- shape (b): consecutive pure-label paragraphs -----------
        # Entries are PARAGRAPH blocks whose entire text is a bare
        # landmark label ("Letter 3", "Chapter 12" — NO trailing
        # title): a body paragraph that merely BEGINS with a label
        # ("Chapter one body.") whole-matches the landmark pattern via
        # its trailing-title branch and must not count, and
        # heading-typed label runs are real structure (C-001/C-002
        # territory), not a source TOC. The run's ordinals must also
        # be non-decreasing — source TOCs list in order.
        run: List[int] = []
        run_entries: List[tuple] = []

        def close_run():
            nonlocal run, run_entries
            ordered = all(
                run_entries[k][1] >= run_entries[k - 1][1]
                or run_entries[k][0] != run_entries[k - 1][0]
                for k in range(1, len(run_entries))
            )
            if len(run) >= self._MIN_ENTRIES and ordered:
                for j in run:
                    self._mark(
                        ctx.blocks[j],
                        f"shape (b): run of {len(run)} consecutive entries",
                    )
                self._mark_label_above(ctx.blocks, run[0])
                entries.extend(run_entries)
            run, run_entries = [], []

        for i in range(window):
            b = ctx.blocks[i]
            tags = b.get("style_tags") or []
            text = normalize_ws(_block_text(b))
            if not text or "empty_line" in tags:
                continue  # blank spacers neither extend nor break a run
            if (
                not _has_role(b)
                and b.get("type") == "paragraph"
                and len(text) <= self._RUN_ENTRY_MAX_CHARS
                and (m := match_landmark(text)) is not None
                and m.kind in ("chapter", "part")
                and m.trailing_title is None
                and m.ordinal is not None
            ):
                run.append(i)
                run_entries.append((m.section_word.lower(), m.ordinal))
            else:
                close_run()
        close_run()

        if entries:
            ctx.extras["source_toc_entries"] = entries

    # -- helpers ------------------------------------------------------------

    def _inline_entries(self, text: str) -> Optional[List[tuple]]:
        """Return the parsed (word, ordinal) entries when the text is a
        shape-(a) source TOC; None otherwise. The residue rule is
        load-bearing: prose that merely MENTIONS several landmarks
        ("chapter 1 and chapter 2 …") keeps most of its characters
        outside the matches and is rejected."""
        found: List[tuple] = []
        matched_chars = 0
        for m in _INLINE_ENTRY_RE.finditer(text):
            value = parse_ordinal(m.group("ordinal").rstrip(".:—"))
            if value is None:
                continue
            found.append((m.group("word").lower(), value))
            matched_chars += m.end() - m.start()
        if len(found) < self._MIN_ENTRIES:
            return None
        total_alnum = sum(1 for ch in text if ch.isalnum())
        # Residue = alnum characters outside matched spans.
        outside = []
        last = 0
        for m in _INLINE_ENTRY_RE.finditer(text):
            outside.append(text[last:m.start()])
            last = m.end()
        outside.append(text[last:])
        residue = sum(1 for ch in "".join(outside) if ch.isalnum())
        if total_alnum and residue / total_alnum > self._MAX_RESIDUE_FRACTION:
            return None
        return found

    def _mark(self, block: Dict[str, Any], how: str) -> None:
        block["role"] = "structural"
        block["subtype"] = "source_toc"
        _add_note(
            block,
            f"source TOC detected ({how}; rules 1.2 Q3) — suppressed "
            f"from body output; W2 renders its generated TOC. Block "
            f"retained for audit and promotion corroboration.",
        )

    def _mark_label_above(self, blocks: List[Dict[str, Any]], i: int) -> None:
        """A short 'Contents' label directly above the detected TOC
        (empty_line spacers skipped) is part of the source TOC
        apparatus — suppress it the same way."""
        for j in range(i - 1, -1, -1):
            b = blocks[j]
            text = normalize_ws(_block_text(b))
            tags = b.get("style_tags") or []
            if not text or "empty_line" in tags:
                continue
            if not _has_role(b) and _TOC_LABEL_RE.match(text):
                self._mark(b, "adjacent 'Contents' label")
            return


# ---------------------------------------------------------------------------
# C-008: Pattern-only landmark promotion (rules 1.2, Gate 2 ruling Q1)
# ---------------------------------------------------------------------------

class C008_PatternOnlyLandmarks:
    """C-008 v1 (rules 1.2, ruling Q1): promote pattern-matching
    paragraphs to landmarks in ZERO-STRUCTURE documents — where the
    §2.2 machinery found nothing to work with (no heading stratum with
    chapter matches, no visually gated paragraphs). Book 16 (test 21's
    Pandoc plain-text Frankenstein) is the defining fixture.

    All four ruling requirements gate the promotion:
      1. Coherent sequence PER LEXICON CLASS ("letter" and "chapter"
         are separate sequences): ordinals strictly increasing within
         a class; a restart is permitted only where a part-class
         candidate intervenes between the two positions.
      2. Whole-paragraph: the block's entire normalized text is a
         single pattern instance, capped at _MAX_CHARS. Mid-prose
         mentions ("as I said in Chapter 1, …") fail the whole-text
         anchor by construction.
      3. Multiplicity: >= _MIN_CLASS_RUN matches in the class sequence.
      4. Dispersion: consecutive candidates must be separated by
         >= _DISPERSION_MIN_WORDS of intervening content. An ADJACENT
         cluster of >= _MIN_CLASS_RUN matches is a source-TOC candidate
         (handed the C-007 treatment as a belt — C-007 normally catches
         it first) and never a landmark run; clustered candidates are
         excluded from promotion either way.

    A source TOC is CORROBORATION only (ctx.extras entries recorded in
    the block notes when they agree) — promotion must succeed without
    one (Book 16 has none in shape-(b) form). Promotion emits no
    warning here; V-006 (validate phase) fires on the marker note so
    the finished book routes through the Review gate (training wheels,
    Gate 2 ruling: medium until a few real books pass review clean).

    Thresholds are PROPOSALS pending Manus review (MIGRATION_NOTES_v1.2):
    _MAX_CHARS=80 (longest corpus landmark line "CHAPTER TWENTY-THREE."
    is 21 chars; 80 leaves room for modest trailing titles while
    excluding prose sentences), _DISPERSION_MIN_WORDS=50 (the shortest
    plausible real chapter body dwarfs it; a TOC run has ~0-5 words
    between entries), _MIN_CLASS_RUN=3 (ruling text).
    Rule id C-008 is provisional; confirm at Doc 22 v1.2 drafting.
    """

    id = "C-008"
    phase = "classify"
    order = 3
    version = "v1"

    _MAX_CHARS = 80
    _MIN_CLASS_RUN = 3
    _DISPERSION_MIN_WORDS = 50

    def run(self, ctx: RuleContext) -> None:
        analysis = ctx.extras.get("strata")
        if analysis is not None and analysis.dominant is not None:
            return  # the visual-gate path found landmarks — stay off
        if any(
            b.get("role") in ("chapter_heading", "part_divider")
            for b in ctx.blocks
        ):
            return

        # Requirement 2: whole-paragraph single-pattern candidates.
        cands: List[tuple] = []  # (block_index, LandmarkMatch)
        for i, b in enumerate(ctx.blocks):
            if _has_role(b) or b.get("type") not in ("paragraph", "heading"):
                continue
            text = normalize_ws(_block_text(b))
            if not text or len(text) > self._MAX_CHARS:
                continue
            m = match_landmark(text)
            if m is None or m.kind == "unnumbered" or m.ordinal is None:
                continue
            cands.append((i, m))
        if not cands:
            return

        # Requirement 4: dispersion. Split the candidate list into
        # adjacency clusters; a cluster (mutually < threshold apart) is
        # never a landmark run.
        def words_between(a: int, b: int) -> int:
            return sum(
                len(_block_text(ctx.blocks[j]).split())
                for j in range(a + 1, b)
            )

        groups: List[List[int]] = [[0]]
        for k in range(1, len(cands)):
            if words_between(cands[k - 1][0], cands[k][0]) < self._DISPERSION_MIN_WORDS:
                groups[-1].append(k)
            else:
                groups.append([k])

        promotable: List[tuple] = []
        for g in groups:
            if len(g) == 1:
                promotable.append(cands[g[0]])
                continue
            # Adjacent cluster: source-TOC candidate, never landmarks.
            if len(g) >= self._MIN_CLASS_RUN:
                for k in g:
                    i, m = cands[k]
                    b = ctx.blocks[i]
                    b["role"] = "structural"
                    b["subtype"] = "source_toc"
                    _add_note(
                        b,
                        f"adjacent cluster of {len(g)} pattern matches "
                        f"(dispersion < {self._DISPERSION_MIN_WORDS} words; "
                        f"rules 1.2 Q1 req 4) — source-TOC candidate, "
                        f"suppressed from body output",
                    )
            else:
                for k in g:
                    _add_note(
                        ctx.blocks[cands[k][0]],
                        f"pattern match excluded from pattern-only "
                        f"promotion: adjacent to another match "
                        f"(dispersion < {self._DISPERSION_MIN_WORDS} words) "
                        f"but below source-TOC multiplicity",
                    )

        if not promotable:
            return

        # Requirement 1: per-class coherent sequences, part-pivot
        # restarts. Class key = section word, normalized.
        part_positions = [
            i for i, m in promotable if m.kind == "part"
        ]
        by_class: Dict[str, List[tuple]] = {}
        for i, m in promotable:
            if m.kind != "chapter":
                continue
            by_class.setdefault(
                m.section_word.lower().rstrip("."), []
            ).append((i, m))

        toc_entries = ctx.extras.get("source_toc_entries") or []
        toc_set = {(w, o) for (w, o) in toc_entries}

        promoted_any = False
        used_pivots: Set[int] = set()
        c001 = C001_LandmarkClassification()
        for cls, items in sorted(by_class.items()):
            if len(items) < self._MIN_CLASS_RUN:
                for i, _m in items:
                    _add_note(
                        ctx.blocks[i],
                        f"pattern-only class '{cls}' below multiplicity "
                        f"({len(items)} < {self._MIN_CLASS_RUN}) — not promoted",
                    )
                continue
            ok, pivots = self._sequence_coherent(items, part_positions)
            if not ok:
                for i, _m in items:
                    _add_note(
                        ctx.blocks[i],
                        f"pattern-only class '{cls}' sequence incoherent — "
                        f"not promoted",
                    )
                continue
            used_pivots.update(pivots)
            corroborated = sum(
                1 for _i, m in items
                if (m.section_word.lower().rstrip("."), m.ordinal) in toc_set
            )
            for i, m in items:
                block = ctx.blocks[i]
                c001._assign_chapter(ctx, block, m)
                _add_note(
                    block,
                    f"{PATTERN_ONLY_NOTE} (rules 1.2 Q1): class '{cls}', "
                    f"no visual confirmation"
                    + (
                        f"; source TOC corroborates {corroborated}/{len(items)}"
                        if toc_entries else ""
                    ),
                )
            promoted_any = True

        # Part candidates: promote when their class meets multiplicity
        # +sequence on its own, or when they served as a restart pivot
        # for a promoted chapter class.
        if promoted_any or part_positions:
            parts_by_class: Dict[str, List[tuple]] = {}
            for i, m in promotable:
                if m.kind == "part":
                    parts_by_class.setdefault(
                        m.section_word.lower().rstrip("."), []
                    ).append((i, m))
            for cls, items in sorted(parts_by_class.items()):
                standalone = (
                    len(items) >= self._MIN_CLASS_RUN
                    and self._sequence_coherent(items, [])[0]
                )
                for i, m in items:
                    if standalone or (i in used_pivots and promoted_any):
                        block = ctx.blocks[i]
                        c001._assign_part(ctx, block, m)
                        _add_note(
                            block,
                            f"{PATTERN_ONLY_NOTE} (rules 1.2 Q1): part class "
                            f"'{cls}', "
                            + ("standalone sequence" if standalone
                               else "restart pivot for a promoted chapter class"),
                        )
                        promoted_any = True

    def _sequence_coherent(
        self, items: List[tuple], part_positions: List[int],
    ) -> tuple:
        """Requirement 1: strictly increasing ordinals in document
        order; a restart (ordinal <= previous) is allowed only when a
        part-class candidate sits between the two blocks. Returns
        (coherent, pivot_positions_used)."""
        pivots: Set[int] = set()
        prev_pos: Optional[int] = None
        prev_ord: Optional[int] = None
        for i, m in items:
            if prev_ord is not None and m.ordinal <= prev_ord:
                pivot = next(
                    (p for p in part_positions if prev_pos < p < i), None,
                )
                if pivot is None:
                    return False, set()
                pivots.add(pivot)
            prev_pos, prev_ord = i, m.ordinal
        return True, pivots


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
