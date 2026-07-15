"""
Shared ordinal parser — amendment spec v2.2 §2.1, iteration 1.

Parses the three ordinal systems the corpus produced into integers:
arabic ("12"), roman ("LXXIV" — DQ Vol II runs to 74; "XXVII"), and
spelled words ("ONE" … Hatch/Carol style, compounds like "TWENTY-ONE").

The roman parser is hoisted from W2's fix branch (`848a259`,
`BlocksToLatexConverter._chapter_number_as_int`) so both workers
converge on one implementation when the shared-library consolidation
lands (punchlist §3, Option C). Keep the two in sync until then.

Pure functions, no pipeline coupling. The integer is metadata; callers
preserve the source's display form (spec: "the integer is metadata").
"""
from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "parse_ordinal",
    "parse_arabic",
    "parse_roman",
    "parse_word_ordinal",
    "detect_ordinal_style",
]

_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

_WORD_UNITS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9,
}
_WORD_TEENS = {
    "TEN": 10, "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14,
    "FIFTEEN": 15, "SIXTEEN": 16, "SEVENTEEN": 17, "EIGHTEEN": 18,
    "NINETEEN": 19,
}
_WORD_TENS = {
    "TWENTY": 20, "THIRTY": 30, "FORTY": 40, "FIFTY": 50,
    "SIXTY": 60, "SEVENTY": 70, "EIGHTY": 80, "NINETY": 90,
}


def parse_arabic(token: str) -> Optional[int]:
    """"12" → 12. Positive integers only."""
    s = token.strip()
    if s.isdigit():
        value = int(s)
        return value if value > 0 else None
    return None


def parse_roman(token: str) -> Optional[int]:
    """"LXXIV" → 74. Charset-validated, subtractive notation honored.

    Permissive about non-canonical forms ("IIII" → 4) — real books are
    not canonical. Case-insensitive.
    """
    s = token.strip()
    if not s or not _ROMAN_RE.match(s):
        return None
    upper = s.upper()
    total = 0
    for i, ch in enumerate(upper):
        v = _ROMAN_VALUES[ch]
        if i + 1 < len(upper) and _ROMAN_VALUES[upper[i + 1]] > v:
            total -= v
        else:
            total += v
    return total if total > 0 else None


def parse_word_ordinal(token: str) -> Optional[int]:
    """"ONE" → 1, "TWENTY-ONE"/"TWENTY ONE" → 21. Range 1–99.

    Case-insensitive. Compounds join with hyphen or space.
    """
    s = re.sub(r"[\s\-]+", " ", token.strip().upper()).strip()
    if not s:
        return None
    if s in _WORD_UNITS:
        return _WORD_UNITS[s]
    if s in _WORD_TEENS:
        return _WORD_TEENS[s]
    if s in _WORD_TENS:
        return _WORD_TENS[s]
    parts = s.split(" ")
    if len(parts) == 2 and parts[0] in _WORD_TENS and parts[1] in _WORD_UNITS:
        return _WORD_TENS[parts[0]] + _WORD_UNITS[parts[1]]
    return None


def parse_ordinal(token: str) -> Optional[int]:
    """Try arabic, then roman, then spelled words. None if no system
    parses the token.

    Order note: arabic first (digits are unambiguous), roman before
    words (the corpus's roman forms — "I", "V", "C" — are all valid
    roman charset; no English number word collides with the charset).
    """
    if not token or not token.strip():
        return None
    for parser in (parse_arabic, parse_roman, parse_word_ordinal):
        value = parser(token)
        if value is not None:
            return value
    return None


def detect_ordinal_style(token: str) -> Optional[str]:
    """"arabic" | "roman" | "words" | None — the system that parses the
    token, matching parse_ordinal's precedence. Callers use this to
    preserve the source's display style.
    """
    if not token or not token.strip():
        return None
    if parse_arabic(token) is not None:
        return "arabic"
    if parse_roman(token) is not None:
        return "roman"
    if parse_word_ordinal(token) is not None:
        return "words"
    return None
