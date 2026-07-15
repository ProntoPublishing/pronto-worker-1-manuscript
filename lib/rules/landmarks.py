"""
Landmark pattern matcher — amendment spec v2.2 §2.1/§2.1b as patched by
the v2.2.1 rulings addendum (2026-07-15). Iteration 3.

Pure library code: classification wiring is iteration 4+. Implements:

  §2.1 (spaced, primary):   ^ <section-word> \\s+ <ordinal> [.:—]? (\\s+ <trailing-title>)? $
  Q2 ruling (fused variant): ^ <section-word><ordinal> [.:—]? $
      — no whitespace between word and ordinal, valid for all three
      ordinal systems, no trailing title. Fires only when the ordinal
      remainder parses ("Chapterhouse" fails the parse, so real words
      never match). A fused match carries fused=True so the classifier
      can emit the ruled normalization warning ("probable missing space
      in heading"). Candidate-block gating is the CLASSIFIER's job.
  §2.1b unnumbered:         {Prologue, Epilogue} → chapter_number null
                            + landmark_subtype.

  Q1 ruling (two-stage matching), in match_landmark_lines():
      (1) whole-normalized-text match (preserves DQ trailing titles);
      (2) on failure, each line tested independently. Exactly ONE
          matching line → the block matches via that line, and the
          non-matching non-empty lines are returned as caption_lines
          (routed to §2.3 subtitle/caption treatment by the classifier
          — P&P's 34 caption-merged headings). TWO OR MORE matching
          lines → ambiguous: no classification, scan.ambiguous=True so
          the classifier emits the ruled warning.
      Per the ruling, per-line results are only valid on blocks that
      are already landmark candidates (dominant stratum / visually
      gated) — enforced at classification time, not here.

NOTE on "wires in as coded": the addendum's rationale blesses the
iter-2 helper by name, but its normative text adds the exactly-one-line
rule and caption routing, which the iter-2 helper lacked. The normative
text wins; the helper was extended accordingly (see MIGRATION_NOTES
"Q1 interpretation" entry).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .ordinals import parse_ordinal, detect_ordinal_style

__all__ = [
    "CHAPTER_CLASS_LEXICON",
    "PART_CLASS_LEXICON",
    "UNNUMBERED_LEXICON",
    "normalize_ws",
    "match_landmark",
    "match_landmark_lines",
    "LandmarkMatch",
    "LandmarkScan",
]

# Config constants (spec §2.1: "additions are one-line").
CHAPTER_CLASS_LEXICON = (
    "chapter", "chap.", "stave", "letter", "canto",
    "section", "act", "scene", "lesson",
)
PART_CLASS_LEXICON = ("part", "book", "volume", "vol.")
UNNUMBERED_LEXICON = ("prologue", "epilogue")

# NBSP family → space (Carol's "STAVE ONE." embeds U+00A0), then
# collapse runs. \s in Python already matches \xa0 but replacing first
# keeps the lexicon regexes simple and the intent visible.
_NBSP_RE = re.compile('[\u00a0\u2007\u202f]')
_WS_RUN_RE = re.compile(r"\s+")

_TRAILING_PUNCT = ".:—"


def normalize_ws(text: str) -> str:
    """NBSP→space, collapse whitespace runs, strip. Spec §2.1 line 1."""
    if not text:
        return ""
    return _WS_RUN_RE.sub(" ", _NBSP_RE.sub(" ", text)).strip()


def _lexicon_alternation(words) -> str:
    # Longest-first so "chap." wins over prefix collisions; escape dots.
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_NUMBERED_RE = re.compile(
    rf"^(?P<word>{_lexicon_alternation(CHAPTER_CLASS_LEXICON + PART_CLASS_LEXICON)})"
    rf"\s+(?P<ordinal>\S+?)"
    rf"(?P<punct>[{_TRAILING_PUNCT}])?"
    rf"(?:\s+(?P<title>.+))?$",
    re.IGNORECASE,
)

# Q2 fused variant: section word immediately followed by the ordinal
# token, no whitespace, optional trailing punctuation, nothing else.
# The ordinal group is letters/digits/hyphens only (spelled compounds
# like TWENTY-SEVEN keep their hyphen); the parse_ordinal gate does the
# real filtering.
_FUSED_RE = re.compile(
    rf"^(?P<word>{_lexicon_alternation(CHAPTER_CLASS_LEXICON + PART_CLASS_LEXICON)})"
    rf"(?P<ordinal>[A-Za-z0-9\-]+)"
    rf"[{_TRAILING_PUNCT}]?$",
    re.IGNORECASE,
)

_UNNUMBERED_RE = re.compile(
    rf"^(?P<word>{_lexicon_alternation(UNNUMBERED_LEXICON)})"
    rf"(?:[{_TRAILING_PUNCT}])?"
    rf"(?:\s+(?P<title>.+))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LandmarkMatch:
    """Result of a landmark pattern match.

    kind: "chapter" | "part" | "unnumbered"
    section_word: the matched word as it appears in the (normalized) source
    ordinal: integer chapter/part number (None for unnumbered)
    ordinal_display: the ordinal token as written ("LXXIV", "ONE", "12");
        None for unnumbered
    ordinal_style: "arabic" | "roman" | "words" | None
    trailing_title: text after the ordinal on the same normalized line
        (DQ: "WHICH TREATS OF THE CHARACTER…"); None when absent
    landmark_subtype: "prologue" | "epilogue" for the unnumbered branch
    fused: True when the Q2 no-space variant fired ("CHAPTERXXVII.") —
        classifier must emit the normalization warning
    matched_via: "whole" | "line" — which Q1 stage produced the match
    caption_lines: for matched_via="line", the block's non-matching
        non-empty normalized lines (§2.3 subtitle/caption routing —
        P&P's merged captions). Empty tuple otherwise.
    """
    kind: str
    section_word: str
    ordinal: Optional[int] = None
    ordinal_display: Optional[str] = None
    ordinal_style: Optional[str] = None
    trailing_title: Optional[str] = None
    landmark_subtype: Optional[str] = None
    fused: bool = False
    matched_via: str = "whole"
    caption_lines: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LandmarkScan:
    """Result of the Q1 two-stage scan (match_landmark_lines).

    match: the LandmarkMatch, or None when nothing matched or the
        per-line stage was ambiguous.
    ambiguous: True when 2+ lines matched at the per-line stage (ruled:
        no classification + warning).
    matching_line_count: number of per-line matches (0 when the whole
        text matched — the per-line stage never ran).
    """
    match: Optional[LandmarkMatch]
    ambiguous: bool = False
    matching_line_count: int = 0


def _classify_word(word: str) -> str:
    return (
        "part"
        if word.lower().rstrip(".") in
        tuple(w.rstrip(".") for w in PART_CLASS_LEXICON)
        else "chapter"
    )


def match_landmark(text: str) -> Optional[LandmarkMatch]:
    """Match §2.1 (+ Q2 fused variant, + §2.1b) against the
    whitespace-normalized WHOLE text. Stage 1 of the Q1 algorithm;
    also the per-line primitive for stage 2.
    """
    normalized = normalize_ws(text)
    if not normalized:
        return None

    m = _NUMBERED_RE.match(normalized)
    if m:
        word = m.group("word")
        # The regex's lazy \S+? plus optional punct group leaves clean
        # tokens; strip any residual trailing punctuation defensively.
        ordinal_token = m.group("ordinal").rstrip(_TRAILING_PUNCT)
        value = parse_ordinal(ordinal_token)
        if value is not None:
            title = m.group("title")
            return LandmarkMatch(
                kind=_classify_word(word),
                section_word=word,
                ordinal=value,
                ordinal_display=ordinal_token,
                ordinal_style=detect_ordinal_style(ordinal_token),
                trailing_title=title.strip() if title else None,
            )
        # Ordinal token didn't parse ("Chapter Once") → not a numbered
        # landmark; fall through to fused / unnumbered.

    f = _FUSED_RE.match(normalized)
    if f:
        word = f.group("word")
        ordinal_token = f.group("ordinal")
        value = parse_ordinal(ordinal_token)
        if value is not None:
            return LandmarkMatch(
                kind=_classify_word(word),
                section_word=word,
                ordinal=value,
                ordinal_display=ordinal_token,
                ordinal_style=detect_ordinal_style(ordinal_token),
                fused=True,
            )
        # Remainder isn't an ordinal ("Chapterhouse") → not fused.

    u = _UNNUMBERED_RE.match(normalized)
    if u:
        word = u.group("word")
        return LandmarkMatch(
            kind="unnumbered",
            section_word=word,
            landmark_subtype=word.lower().rstrip("."),
            trailing_title=(u.group("title") or "").strip() or None,
        )

    return None


def match_landmark_lines(text: str) -> LandmarkScan:
    """Q1 ruling: whole-text first, per-line fallback with the
    exactly-one-line rule.

    Stage 1 — whole normalized text (preserves DQ trailing-title
    extraction). Stage 2 — each line independently; exactly one
    matching line classifies the block via that line, with the
    remaining non-empty lines as caption_lines (§2.3 routing); two or
    more matching lines → ambiguous (no match + classifier warning).

    Candidate gating (dominant stratum / visual gates) is enforced by
    the caller — per the ruling, per-line matching only ever runs
    inside candidate blocks.
    """
    whole = match_landmark(text)
    if whole is not None:
        return LandmarkScan(match=whole)

    line_hits = []   # (LandmarkMatch, normalized_line)
    others = []      # non-matching non-empty normalized lines
    for raw_line in (text or "").splitlines():
        norm_line = normalize_ws(raw_line)
        if not norm_line:
            continue
        lm = match_landmark(norm_line)
        if lm is not None:
            line_hits.append((lm, norm_line))
        else:
            others.append(norm_line)

    if len(line_hits) == 1:
        lm, _ = line_hits[0]
        return LandmarkScan(
            match=LandmarkMatch(
                kind=lm.kind,
                section_word=lm.section_word,
                ordinal=lm.ordinal,
                ordinal_display=lm.ordinal_display,
                ordinal_style=lm.ordinal_style,
                trailing_title=lm.trailing_title,
                landmark_subtype=lm.landmark_subtype,
                fused=lm.fused,
                matched_via="line",
                caption_lines=tuple(others),
            ),
            matching_line_count=1,
        )
    if len(line_hits) >= 2:
        return LandmarkScan(
            match=None, ambiguous=True, matching_line_count=len(line_hits),
        )
    return LandmarkScan(match=None)
