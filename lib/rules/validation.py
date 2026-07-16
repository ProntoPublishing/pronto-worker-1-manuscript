"""
Layer 3 validation rules — V-001 through V-004.

Per Doc 22 §Layer 3: flag but do not fix. Each rule emits entries into
ctx.warnings[]; blocks are not mutated.
"""
from __future__ import annotations
import logging
import re
from typing import Dict, List, Any, Optional, Tuple

from .base import RuleContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers shared across validators
# ---------------------------------------------------------------------------

def _block_text(block: Dict[str, Any]) -> str:
    if "spans" in block:
        return "".join(s.get("text", "") for s in block["spans"])
    return block.get("text", "") or ""


def _chapter_headings(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [b for b in blocks if b.get("role") == "chapter_heading"]


# ---------------------------------------------------------------------------
# V-001: Chapter number continuity
# ---------------------------------------------------------------------------

class V001_ChapterNumberContinuity:
    """V-001 v2 (amendment spec §2.4/§4): part-scoped chapter-number
    continuity with the implicit first part.

    Sequences are scoped to the enclosing part_divider: numbering
    restarts per part (Frankenstein I–VII ×3 volumes; DQ I–LII then
    I–LXXIV). The span before the first part_divider is an implicit
    first part (DQ Amendment 2 — DQ has "Volume II" but no "Volume I"
    marker). Within a scope, integer chapter_numbers must increase
    monotonically by 1 from the first observed value.

    Exclusions: unnumbered landmarks (§2.1b — chapter_number null /
    landmark_subtype set) never enter sequence math; non-int
    chapter_number is the unknown-exit case, not a gap.
    """

    id = "V-001"
    phase = "validate"
    order = 1
    version = "v2"

    def run(self, ctx: RuleContext) -> None:
        scopes = self._scoped_chapters(ctx.blocks)
        for scope_label, numbered in scopes:
            if len(numbered) < 2:
                continue
            observed = [n for _, n in numbered]
            expected = list(range(observed[0], observed[0] + len(observed)))
            if observed == expected:
                continue
            detail = _first_gap_detail(observed)
            ctx.warnings.append({
                "rule": "V-001",
                "severity": "medium",
                "detail": (
                    f"[{scope_label}] chapter numbers {observed} — {detail}"
                ),
                "blocks": [bid for bid, _ in numbered],
            })

    @staticmethod
    def _scoped_chapters(blocks):
        """[(scope_label, [(block_id, chapter_number), ...]), ...] in
        document order. Scoping is part_divider × section-word family:
        Frankenstein's Volume I runs LETTER I–IV then CHAPTER I–VII —
        two independent numbered sequences inside one part, both
        legitimate (§6 requires V-001 silent there). The section word
        is re-derived from the heading text via the landmark matcher
        (pure function; the block doesn't persist it)."""
        from .landmarks import match_landmark_lines

        part_idx = 0
        part_label = "implicit first part"
        scopes: Dict[tuple, List] = {}
        order: List[tuple] = []
        for b in blocks:
            role = b.get("role")
            if role == "part_divider":
                part_idx += 1
                part_label = str(
                    b.get("part_title")
                    or (f"part {b.get('part_number')}"
                        if b.get("part_number") is not None else None)
                    or b.get("id") or "unnamed part"
                )
            elif role == "chapter_heading":
                if b.get("landmark_subtype"):
                    continue  # §2.1b unnumbered — excluded from sequence math
                n = b.get("chapter_number")
                if not isinstance(n, int):
                    continue
                text = _block_text(b)
                scan = match_landmark_lines(text)
                word = (
                    scan.match.section_word.lower().rstrip(".")
                    if scan.match and scan.match.section_word else "chapter"
                )
                key = (part_idx, word)
                if key not in scopes:
                    scopes[key] = []
                    order.append((key, f"{part_label} / {word}s"))
                scopes[key].append((b.get("id"), n))
        return [(label, scopes[key]) for key, label in order]


def _first_gap_detail(observed: List[int]) -> str:
    for i in range(1, len(observed)):
        if observed[i] != observed[i - 1] + 1:
            if observed[i] > observed[i - 1] + 1:
                return (
                    f"gap between {observed[i - 1]} and {observed[i]}"
                )
            return (
                f"out of order at position {i} "
                f"({observed[i - 1]} → {observed[i]})"
            )
    return "expected monotonically increasing by 1"


# ---------------------------------------------------------------------------
# V-002: Heading style consistency
# ---------------------------------------------------------------------------

class V002_HeadingStyleConsistency:
    """V-002 v1: after classify, compute the dominant CIR signature for
    chapter_heading blocks. Flag any chapter_heading whose signature
    deviates from the dominant one.

    CIR signature = (type, heading_level) pair. Style_tags intentionally
    excluded — they're noisy. If the classifier evolves to catch
    "visually chaptered" paragraphs (e.g., centered-bold-large-size that
    the author used as a chapter), the signature comparison surfaces
    them as deviations for operator review.
    """

    id = "V-002"
    phase = "validate"
    order = 2
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        chapters = _chapter_headings(ctx.blocks)
        if len(chapters) < 2:
            return

        signatures = [(b.get("type"), b.get("heading_level")) for b in chapters]
        from collections import Counter
        counts = Counter(signatures)
        dominant, dominant_count = counts.most_common(1)[0]
        if dominant_count == len(signatures):
            return  # all chapters share the same signature

        deviants = [
            b for b in chapters
            if (b.get("type"), b.get("heading_level")) != dominant
        ]
        ctx.warnings.append({
            "rule": "V-002",
            "severity": "medium",
            "detail": (
                f"{dominant_count} of {len(signatures)} chapters use "
                f"{_sig_label(dominant)}; {len(deviants)} deviant"
            ),
            "blocks": [b.get("id") for b in deviants],
        })


def _sig_label(sig: Tuple[Optional[str], Optional[int]]) -> str:
    t, lvl = sig
    if t == "heading" and lvl is not None:
        return f"Heading{lvl}"
    return f"{t}{'/lvl' + str(lvl) if lvl else ''}"


# ---------------------------------------------------------------------------
# V-003: Space-loss heuristic (Doc 22 v1.0.1 narrowing to heuristic (a))
# ---------------------------------------------------------------------------

# Canonical frozen function-word list from Doc 22 v1.0.1 Patch 6 (35 words).
FUNCTION_WORDS_V1 = frozenset({
    # Original 20.
    "the", "of", "to", "in", "with", "for", "at", "on", "and", "but",
    "or", "is", "was", "are", "he", "she", "it", "that", "this", "which",
    # Added in v1.0.1 Patch 6.
    "be", "as", "by", "from", "an", "a", "have", "has", "had",
    "not", "no", "if", "so", "its", "their",
})

_TOKEN_SPLIT_RE = re.compile(r"\S+")
_ASCII_WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")


class V003_SpaceLossHeuristic:
    """V-003 v2: DEMOTED TO OBSERVATIONAL (amendment spec §4).

    Corpus tally ~499 FP / 0 TP / 2 FN (and the 2 FNs are now caught as
    landmarks by the Q2 fused variant). Findings go to the module
    logger and ctx.extras["v003_observations"] — NEVER ctx.warnings —
    so they stay out of the artifact warnings[] and the Airtable
    Warning Count (= len(warnings)). Revisit v1.2.

    Mechanics unchanged below: heuristic (a) only — function-word
    prefix + dictionary miss.

    For each body_paragraph block's text, tokenize on whitespace. For
    each token:
      - Lowercase and strip surrounding punctuation (so "Theweather,"
        matches as "theweather").
      - If the token is not alphabetic (mixed digits, hyphen-only,
        etc.), skip.
      - If the lowercased token starts with a function word from the
        canonical list AND the token AS A WHOLE fails a standard
        English dictionary lookup, emit a V-003 warning.
      - The dictionary lookup uses wordfreq (zero-frequency = not in
        the dictionary). Any standard English dictionary with
        equivalent coverage may be substituted; Doc 22 v1.0.1 names
        hunspell / pyenchant / wordfreq as acceptable backends.

    Heuristics (b) and (c) from the Doc 22 rule are deferred per v1.0.1.
    """

    id = "V-003"
    phase = "validate"
    order = 3
    version = "v2"

    def __init__(self):
        # Lazy import so the module is usable in test environments
        # without wordfreq installed; the rule itself requires it.
        try:
            from wordfreq import word_frequency
            self._word_frequency = word_frequency
            self._backend = "wordfreq"
        except ImportError:
            self._word_frequency = None
            self._backend = None

    def run(self, ctx: RuleContext) -> None:
        observations = ctx.extras.setdefault("v003_observations", [])
        if self._word_frequency is None:
            # Observational rule: a missing backend is a log line, not
            # a rule fault (demotion note in the class docstring).
            logger.warning(
                "V-003 skipped: wordfreq not installed (observational "
                "rule; no fault recorded)"
            )
            ctx.extras["v003_skipped"] = "wordfreq not installed"
            return

        for block in ctx.blocks:
            if block.get("role") != "body_paragraph":
                continue
            text = _block_text(block)
            if not text:
                continue
            self._scan(block, text, observations)

        if observations:
            logger.info(
                "V-003 (observational): %d possible missing-space "
                "token(s); first: %s",
                len(observations),
                observations[0].get("detail"),
            )

    def _scan(
        self,
        block: Dict[str, Any],
        text: str,
        warnings: List[Dict[str, Any]],
    ) -> None:
        for m in _TOKEN_SPLIT_RE.finditer(text):
            raw_token = m.group(0)
            token = raw_token.strip(" ,.;:!?()[]{}\"'\u201C\u201D\u2018\u2019")
            if not token:
                continue
            # Heuristic (a) operates on ASCII-letter tokens; skip mixed
            # digit / hyphen-only / punctuation-riddled tokens.
            if not _ASCII_WORD_RE.match(token):
                continue
            lower = token.lower()
            # Does the token start with a function-word prefix?
            fw = _find_function_word_prefix(lower)
            if fw is None:
                continue
            remainder = lower[len(fw):]
            if not remainder:
                # Token IS a function word, no join.
                continue
            # Full-token dictionary check (per v1.0.1 Patch 6
            # clarification: dictionary is consulted against the full
            # joined token, not the remainder).
            if self._word_frequency(lower, "en") > 0:
                continue  # real word (e.g., "thereon") — suppress
            warnings.append({
                "rule": "V-003",
                "severity": "high",
                "detail": f"possible missing space: '{raw_token}'",
                "block_id": block.get("id"),
                "offset": m.start(),
            })


def _find_function_word_prefix(lower_token: str) -> Optional[str]:
    """If `lower_token` starts with a function word followed by at least
    one letter, return the function word. Otherwise None.
    """
    # Longest match wins — `their` takes precedence over `the`.
    for fw in sorted(FUNCTION_WORDS_V1, key=len, reverse=True):
        if lower_token.startswith(fw) and len(lower_token) > len(fw):
            next_ch = lower_token[len(fw)]
            if next_ch.isalpha():
                return fw
    return None


# ---------------------------------------------------------------------------
# V-004: Tracked-changes residue detector
# ---------------------------------------------------------------------------

# Tokens that should never appear in CIR text after N-002 has run.
_REVISION_LITERAL_MARKERS = ("<w:ins", "<w:del", "</w:ins>", "</w:del>")

# Unicode insertion/deletion indicators (U+2040, U+2041) + a few common
# "proofing" chars that indicate unresolved revision marks.
_REVISION_UNICODE_CHARS = ("\u2040", "\u2041", "\u2380")


class V005_ZeroStructure:
    """V-005 v1 (amendment spec §4, new): warn when a substantial
    document produced no structural roles at all.

    Fires when: zero blocks with role in {chapter_heading, part_divider}
    AND block_count > 50 AND word_count > 5,000. Warning, not fault —
    a 100%-body book is legal (and the classifier may be right), but an
    operator should look.

    Rule id V-005 is provisional (next free validator id); confirm at
    Doc 22 v1.1 drafting.
    """

    id = "V-005"
    phase = "validate"
    order = 5
    version = "v1"

    _STRUCTURAL_ROLES = {"chapter_heading", "part_divider"}
    _MIN_BLOCKS = 50
    _MIN_WORDS = 5_000

    def run(self, ctx: RuleContext) -> None:
        if any(b.get("role") in self._STRUCTURAL_ROLES for b in ctx.blocks):
            return
        if len(ctx.blocks) <= self._MIN_BLOCKS:
            return
        word_count = sum(
            len(_block_text(b).split()) for b in ctx.blocks
        )
        if word_count <= self._MIN_WORDS:
            return
        ctx.warnings.append({
            "rule": "V-005",
            "severity": "medium",
            "detail": (
                f"zero structural roles across {len(ctx.blocks)} blocks / "
                f"~{word_count} words — no chapter_heading or part_divider "
                f"classified; verify the manuscript truly has no structure"
            ),
        })


class V004_TrackedChangesResidueDetector:
    """V-004 v1: scan every block for surviving tracked-change markers.

    V-004 is the safety net for N-002. If any block's text contains
    literal <w:ins> / <w:del> fragments, or if any block carries a
    style_tag or span mark referencing revision tracking, V-004 flags
    it. A clean CIR produces zero V-004 warnings; a leak means the
    extractor has a bug and needs repair before anything ships.
    """

    id = "V-004"
    phase = "validate"
    order = 4
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        for block in ctx.blocks:
            reasons = self._detect(block)
            if not reasons:
                continue
            for reason in reasons:
                ctx.warnings.append({
                    "rule": "V-004",
                    "severity": "high",
                    "detail": (
                        f"surviving tracked-change marker in block "
                        f"{block.get('id')}: {reason}"
                    ),
                    "block_id": block.get("id"),
                })

    def _detect(self, block: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        text = _block_text(block)
        for marker in _REVISION_LITERAL_MARKERS:
            if marker in text:
                reasons.append(f"literal '{marker}' in text")
        for ch in _REVISION_UNICODE_CHARS:
            if ch in text:
                reasons.append(f"revision unicode U+{ord(ch):04X} in text")

        # style_tags / span marks referencing revision tracking — future
        # proofing in case an extractor ever adopts such a tag.
        for tag in block.get("style_tags") or []:
            if "tracked_change" in tag or "revision" in tag:
                reasons.append(f"style_tag '{tag}' references revisions")
        for span in block.get("spans") or []:
            for mark in span.get("marks") or []:
                if "tracked_change" in mark or "revision" in mark:
                    reasons.append(f"span mark '{mark}' references revisions")
        return reasons
