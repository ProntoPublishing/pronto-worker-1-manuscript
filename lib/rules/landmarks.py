"""
Landmark pattern matcher — amendment spec v2.2 §2.1/§2.1b, iteration 2.

Pure library code: NOT wired into classification (that is iteration 3+).
Implements the frozen pattern

    ^ <section-word> \\s+ <ordinal> [.:—]? (\\s+ <trailing-title>)? $

over whitespace-normalized text, the chapter-class / part-class lexicon
split (§2.3 gives part-class words precedence at classification time —
this module only REPORTS the class), and the §2.1b unnumbered branch
({Prologue, Epilogue} → chapter_number null + landmark_subtype).

⚠️ SPEC QUESTIONS Q1/Q2 (MIGRATION_NOTES_v1.1.md): `match_landmark()`
is whole-text per spec — P&P's caption-merged headings ("<caption>
\\n\\n CHAPTER II.") and fused forms ("CHAPTERXXVII.") do NOT match, in
tension with §6's "P&P 61/61 preserved". `match_landmark_lines()` is
the line-wise helper iteration 3 wires IF the spec ruling picks the
whole-text-then-per-line resolution. Do not wire either until ruled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ordinals import parse_ordinal, detect_ordinal_style

__all__ = [
    "CHAPTER_CLASS_LEXICON",
    "PART_CLASS_LEXICON",
    "UNNUMBERED_LEXICON",
    "normalize_ws",
    "match_landmark",
    "match_landmark_lines",
    "LandmarkMatch",
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
    """
    kind: str
    section_word: str
    ordinal: Optional[int] = None
    ordinal_display: Optional[str] = None
    ordinal_style: Optional[str] = None
    trailing_title: Optional[str] = None
    landmark_subtype: Optional[str] = None


def match_landmark(text: str) -> Optional[LandmarkMatch]:
    """Match the §2.1 pattern against the whitespace-normalized WHOLE
    text (spec-as-written semantics; see module docstring for the
    Q1 caveat on caption-merged sources).
    """
    normalized = normalize_ws(text)
    if not normalized:
        return None

    m = _NUMBERED_RE.match(normalized)
    if m:
        word = m.group("word")
        ordinal_token = m.group("ordinal")
        # The regex's lazy \S+? plus optional punct group leaves clean
        # tokens; strip any residual trailing punctuation defensively.
        ordinal_token = ordinal_token.rstrip(_TRAILING_PUNCT)
        value = parse_ordinal(ordinal_token)
        if value is not None:
            kind = (
                "part"
                if word.lower().rstrip(".") in
                tuple(w.rstrip(".") for w in PART_CLASS_LEXICON)
                else "chapter"
            )
            title = m.group("title")
            return LandmarkMatch(
                kind=kind,
                section_word=word,
                ordinal=value,
                ordinal_display=ordinal_token,
                ordinal_style=detect_ordinal_style(ordinal_token),
                trailing_title=title.strip() if title else None,
            )
        # Ordinal token didn't parse ("Chapter the First", "BOOK I."
        # parses fine but "Chapter Once" doesn't) → not a numbered
        # landmark; fall through to the unnumbered branch (it won't
        # match either unless the word is Prologue/Epilogue).

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


def match_landmark_lines(text: str) -> Optional[LandmarkMatch]:
    """Q1 helper (NOT wired anywhere): whole-text first, then per-line.

    Whole-text preserves DQ's trailing-title extraction; the per-line
    fallback catches P&P's caption-merged shape where the chapter line
    sits after caption text. Awaiting the spec ruling — iteration 3
    wires exactly one of match_landmark / match_landmark_lines.
    """
    whole = match_landmark(text)
    if whole is not None:
        return whole
    for line in (text or "").splitlines():
        line_match = match_landmark(line)
        if line_match is not None:
            return line_match
    return None
