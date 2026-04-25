"""
Layer 1 normalization rules.

Per Doc 22 §Layer 1: transformations applied during processing. Layer 1a
is silent (no applied_rules[] entry); Layer 1b is applied-but-logged.

All Layer 1 rules honor the preformatted exemption: a block with
`preformatted: true` (or CIR type in {"code", "preformatted_block"}) is
left untouched. Preformatted content is verbatim by definition.
"""
from __future__ import annotations
import re
from typing import Dict, List, Any

from .base import RuleContext


# Block types whose text content is subject to Layer 1 transformations.
# Structural types (page_break, horizontal_rule, table, image) have no
# text/spans and are trivially skipped. Preformatted types (code,
# preformatted_block) are by definition verbatim.
TEXT_CARRYING_TYPES = frozenset({
    "paragraph", "heading", "blockquote", "list_item", "footnote",
})


def _is_exempt(block: Dict[str, Any]) -> bool:
    """True if the block must be left untouched by Layer 1 rules."""
    if block.get("preformatted") is True:
        return True
    if block.get("type") in ("code", "preformatted_block"):
        return True
    if block.get("type") not in TEXT_CARRYING_TYPES:
        return True
    return False


def _map_text_in_block(block: Dict[str, Any], fn) -> None:
    """Apply `fn(text: str) -> str` to the block's text payload in place."""
    if "spans" in block:
        for span in block["spans"]:
            span["text"] = fn(span.get("text", ""))
    elif "text" in block:
        block["text"] = fn(block["text"])


# ---------------------------------------------------------------------------
# N-001: Collapse double spaces
# ---------------------------------------------------------------------------

_DOUBLE_SPACE_RE = re.compile(r" {2,}")


class N001_CollapseDoubleSpaces:
    """N-001 v1: Collapse runs of 2+ consecutive regular spaces to one.

    Two behaviors, both per Doc 22 N-001 (v1.0.1, with paragraph-level
    extension):

      (a) Intra-paragraph: in every text-carrying, non-preformatted block,
          replace sequences of 2+ U+0020 with a single U+0020.

      (b) Paragraph-level: collapse runs of 2+ consecutive empty_line
          paragraph blocks into a single empty_line block.

    Exemption: `preformatted: true` OR CIR type in {code, preformatted_block}.
    Layer 1a — emits nothing to applied_rules[].
    """

    id = "N-001"
    phase = "strip"
    order = 1
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        # (a) Intra-paragraph double-space collapse.
        for block in ctx.blocks:
            if _is_exempt(block):
                continue
            _map_text_in_block(block, self._collapse_spaces)

        # (b) Paragraph-level empty-line run collapse.
        ctx.blocks[:] = self._collapse_empty_line_runs(ctx.blocks)

    @staticmethod
    def _collapse_spaces(text: str) -> str:
        return _DOUBLE_SPACE_RE.sub(" ", text)

    @staticmethod
    def _collapse_empty_line_runs(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for b in blocks:
            if _is_empty_line(b) and out and _is_empty_line(out[-1]):
                continue  # drop the duplicate
            out.append(b)
        return out


def _is_empty_line(block: Dict[str, Any]) -> bool:
    return (
        block.get("type") == "paragraph"
        and "empty_line" in (block.get("style_tags") or [])
    )


# ---------------------------------------------------------------------------
# N-003: Strip zero-width and layout-hack characters
# ---------------------------------------------------------------------------

# Zero-width characters that break downstream text processing when embedded
# in body content. Per Doc 22 N-003 (v1).
_ZERO_WIDTH_CHARS = ("\u200B", "\u200C", "\u200D", "\uFEFF")

# Runs of 2+ non-breaking spaces (U+00A0) are typically pseudo-indentation
# hacks. A single NBSP may be deliberate (e.g., French spacing, "Mr.\u00A0X")
# and is preserved.
_NBSP_RUN_RE = re.compile("\u00A0{2,}")


class N003_StripZeroWidthAndLayoutHacks:
    """N-003 v1: Strip zero-width characters; collapse pseudo-indent NBSP runs.

    Per Doc 22 N-003 (v1) behavior:
      - Remove U+200B (ZWSP), U+200C (ZWNJ), U+200D (ZWJ), U+FEFF (BOM).
      - Collapse runs of 2+ U+00A0 (NBSP) to a single regular space.
    Exemption: preformatted content (type code/preformatted_block, or
    preformatted=true) is left verbatim.
    Layer 1a — emits nothing to applied_rules[].

    Ordering note: N-003 runs AFTER N-001 within the strip phase per the
    authoring-order default. In pathological input like
    ``"foo  \\u00A0\\u00A0  bar"`` (double-space, double-NBSP,
    double-space), N-001 collapses the regular doubles first but cannot
    re-run after N-003 emits a regular space in place of the NBSP run,
    leaving ``"foo   bar"``. This is an edge case not hit by any fixture
    in v1; flagging as an observation for a future v1.0.X revision that
    may tighten the rule wording or introduce an idempotency pass.
    """

    id = "N-003"
    phase = "strip"
    order = 2
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        for block in ctx.blocks:
            if _is_exempt(block):
                continue
            _map_text_in_block(block, self._strip)

    @staticmethod
    def _strip(text: str) -> str:
        for ch in _ZERO_WIDTH_CHARS:
            if ch in text:
                text = text.replace(ch, "")
        text = _NBSP_RUN_RE.sub(" ", text)
        return text


# ---------------------------------------------------------------------------
# N-004: Quote normalization (straight → curly)
# ---------------------------------------------------------------------------

# Word-boundary characters used to distinguish opening vs closing context.
# A straight quote is "opening" when preceded by nothing, whitespace, an
# opening bracket/brace, an em/en-dash, or another opening quote.
_OPEN_CONTEXT = set(" \t\n\r([{<\u2014\u2013\u2018\u201C")

# Hyphenation-like neighbors that don't change opening/closing logic
# but matter for word-boundary detection.
_WORD_CHAR_RE = re.compile(r"\w")


class N004_QuoteNormalization:
    """N-004 v1: straight → curly quote normalization.

    Layer 1b (applied-but-logged). Phase: normalize. Order: 1.

    Behavior per Doc 22 v1 N-004:
      - Convert straight quotes (") and (') to directional equivalents
        (U+201C/U+201D for double, U+2018/U+2019 for single) based on
        opening-vs-closing context.
      - Exception: blocks tagged preformatted, code, preformatted_block
        are exempt.
      - Emits one applied_rules[] entry per block touched: {rule: "N-004",
        version: "v1", count: N, block_ids: [...]} — aggregated to a
        single entry per rule run with total count and the list of
        affected block ids.

    Opening-vs-closing heuristic:
      - If the character before the straight quote is absent, whitespace,
        or an opening punctuation/dash/open-quote → OPENING.
      - Otherwise → CLOSING.
      - Apostrophes inside words ("don't", "they're") are handled by the
        "character before is a word character" branch of the CLOSING
        case, which maps to U+2019 — the correct typographic apostrophe.

    Ordering note on span boundaries: in a multi-span paragraph, the
    character immediately preceding a straight quote may live at the end
    of the prior span. The implementation walks spans in sequence and
    threads a `prev_char` state through the walk so cross-span context
    resolves correctly.
    """

    id = "N-004"
    phase = "normalize"
    order = 1
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        total_count = 0
        affected_ids: List[str] = []

        for block in ctx.blocks:
            if _is_exempt(block):
                continue
            before = _serialize_block_text(block)
            _normalize_quotes_in_block(block)
            after = _serialize_block_text(block)
            if before != after:
                # Count the net increase in curly quotes — each curly
                # quote corresponds to one normalization.
                delta = _curly_delta(before, after)
                total_count += max(delta, 1)
                affected_ids.append(block.get("id", "?"))

        if total_count > 0:
            ctx.applied_rules.append({
                "rule": "N-004",
                "version": "v1",
                "count": total_count,
                "block_ids": affected_ids,
            })


# ---------------------------------------------------------------------------
# N-004 helpers
# ---------------------------------------------------------------------------

def _serialize_block_text(block: Dict[str, Any]) -> str:
    """Concatenate a block's text content; used for before/after compare."""
    if "spans" in block:
        return "".join(s.get("text", "") for s in block["spans"])
    return block.get("text", "") or ""


def _curly_delta(before: str, after: str) -> int:
    """Count of curly-quote chars in `after` minus in `before`."""
    curly = ("\u201C", "\u201D", "\u2018", "\u2019")
    return sum(after.count(c) for c in curly) - sum(before.count(c) for c in curly)


def _normalize_quotes_in_block(block: Dict[str, Any]) -> None:
    """Apply the opening/closing heuristic across the block's spans or
    text, preserving structure. prev_char is threaded across span
    boundaries.
    """
    if "spans" in block:
        prev_char = ""
        for span in block["spans"]:
            new_text, prev_char = _normalize_quotes(span.get("text", ""), prev_char)
            span["text"] = new_text
    elif "text" in block:
        block["text"], _ = _normalize_quotes(block["text"], "")


def _normalize_quotes(text: str, prev_char: str) -> tuple:
    """Return (new_text, last_char). Straight " and ' are replaced by
    directional equivalents based on `prev_char` (plus text[i-1] as we
    scan) and what follows.
    """
    out: List[str] = []
    for i, ch in enumerate(text):
        left = text[i - 1] if i > 0 else prev_char
        if ch == '"':
            if _is_opening_context(left):
                out.append("\u201C")
            else:
                out.append("\u201D")
        elif ch == "'":
            if _is_opening_context(left):
                out.append("\u2018")
            else:
                # Includes apostrophes in contractions: a word char to
                # the left → closing single quote = U+2019.
                out.append("\u2019")
        else:
            out.append(ch)
    new_text = "".join(out)
    last = new_text[-1] if new_text else prev_char
    return new_text, last


def _is_opening_context(left: str) -> bool:
    """Straight quote at this position opens a quotation if `left` is
    empty, whitespace, an opening punctuation, a dash, or an already-
    opened quote.
    """
    if not left:
        return True
    if left in _OPEN_CONTEXT:
        return True
    # Everything else (word char, closing bracket, punctuation) → closing.
    return False
