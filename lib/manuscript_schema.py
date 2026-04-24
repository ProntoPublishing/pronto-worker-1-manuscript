"""
Pronto Publishing — Manuscript Artifact Schema v1.1
====================================================

Single source of truth for the manuscript.v1.json contract.
Both Worker 1 (producer) and Worker 2 (consumer) import this module.

Usage:
    from manuscript_schema import (
        SCHEMA_VERSIONS_ACCEPTED,
        BLOCK_TYPES,
        BLOCK_TYPES_WITH_TEXT,
        BLOCK_TYPES_STRUCTURAL,
        INLINE_MARKS,
        validate_artifact,
        validate_block,
        normalize_block_text,
    )
"""

from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION_CURRENT = "1.1"
SCHEMA_VERSIONS_ACCEPTED = {"1.0", "1.1"}

# ---------------------------------------------------------------------------
# Canonical block types (exhaustive — no others are permitted)
# ---------------------------------------------------------------------------

# Front matter
BLOCK_FRONT_MATTER_TITLE = "front_matter_title"
BLOCK_FRONT_MATTER_COPYRIGHT = "front_matter_copyright"
BLOCK_FRONT_MATTER_DEDICATION = "front_matter_dedication"
BLOCK_TOC_MARKER = "toc_marker"

# Body
BLOCK_CHAPTER_HEADING = "chapter_heading"
BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_BLOCKQUOTE = "blockquote"
BLOCK_LIST = "list"
BLOCK_SCENE_BREAK = "scene_break"
BLOCK_HORIZONTAL_RULE = "horizontal_rule"
BLOCK_PAGE_BREAK = "page_break"

# Back matter
BLOCK_BACK_MATTER_ABOUT_AUTHOR = "back_matter_about_author"
BLOCK_BACK_MATTER_ALSO_BY = "back_matter_also_by"

# The complete set — both workers must agree on this exactly
BLOCK_TYPES = frozenset({
    BLOCK_FRONT_MATTER_TITLE,
    BLOCK_FRONT_MATTER_COPYRIGHT,
    BLOCK_FRONT_MATTER_DEDICATION,
    BLOCK_TOC_MARKER,
    BLOCK_CHAPTER_HEADING,
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_BLOCKQUOTE,
    BLOCK_LIST,
    BLOCK_SCENE_BREAK,
    BLOCK_HORIZONTAL_RULE,
    BLOCK_PAGE_BREAK,
    BLOCK_BACK_MATTER_ABOUT_AUTHOR,
    BLOCK_BACK_MATTER_ALSO_BY,
})

# Blocks that carry text (via spans)
BLOCK_TYPES_WITH_TEXT = frozenset({
    BLOCK_FRONT_MATTER_TITLE,
    BLOCK_FRONT_MATTER_COPYRIGHT,
    BLOCK_FRONT_MATTER_DEDICATION,
    BLOCK_CHAPTER_HEADING,
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_BLOCKQUOTE,
    BLOCK_LIST,
    BLOCK_BACK_MATTER_ABOUT_AUTHOR,
    BLOCK_BACK_MATTER_ALSO_BY,
})

# Structural blocks (no text, no spans)
BLOCK_TYPES_STRUCTURAL = frozenset({
    BLOCK_TOC_MARKER,
    BLOCK_SCENE_BREAK,
    BLOCK_HORIZONTAL_RULE,
    BLOCK_PAGE_BREAK,
})

assert BLOCK_TYPES_WITH_TEXT | BLOCK_TYPES_STRUCTURAL == BLOCK_TYPES, \
    "Every block type must be classified as text-carrying or structural"
assert BLOCK_TYPES_WITH_TEXT & BLOCK_TYPES_STRUCTURAL == frozenset(), \
    "No block type can be both text-carrying and structural"

# ---------------------------------------------------------------------------
# Inline marks (exhaustive)
# ---------------------------------------------------------------------------

INLINE_MARKS = frozenset({"italic", "bold", "smallcaps", "code"})

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """Raised when artifact data violates the manuscript schema."""
    pass


def validate_span(span: Dict[str, Any], block_id: str) -> List[str]:
    """
    Validate a single span object.

    Returns list of error messages (empty = valid).
    """
    errors = []

    if not isinstance(span, dict):
        return [f"Block {block_id}: span is not a dict: {type(span)}"]

    if "text" not in span:
        errors.append(f"Block {block_id}: span missing 'text' field")
    elif not isinstance(span["text"], str):
        errors.append(f"Block {block_id}: span 'text' is not a string")

    if "marks" not in span:
        errors.append(f"Block {block_id}: span missing 'marks' field")
    elif not isinstance(span["marks"], list):
        errors.append(f"Block {block_id}: span 'marks' is not a list")
    else:
        for mark in span["marks"]:
            if mark not in INLINE_MARKS:
                errors.append(
                    f"Block {block_id}: unknown inline mark '{mark}' "
                    f"(valid: {sorted(INLINE_MARKS)})"
                )

    return errors


def validate_block(block: Dict[str, Any]) -> List[str]:
    """
    Validate a single block against the schema.

    Returns list of error messages (empty = valid).
    """
    errors = []
    block_id = block.get("id", "<no id>")

    # Required fields
    if "id" not in block:
        errors.append(f"Block missing 'id' field")
    if "type" not in block:
        errors.append(f"Block {block_id}: missing 'type' field")
        return errors  # Can't validate further without type

    block_type = block["type"]

    if block_type not in BLOCK_TYPES:
        errors.append(
            f"Block {block_id}: unknown type '{block_type}' "
            f"(valid: {sorted(BLOCK_TYPES)})"
        )
        return errors

    # Text-carrying blocks must have spans (or legacy text)
    if block_type in BLOCK_TYPES_WITH_TEXT:
        has_spans = "spans" in block and isinstance(block["spans"], list)
        has_text = "text" in block and isinstance(block["text"], str)

        if not has_spans and not has_text:
            errors.append(
                f"Block {block_id} ({block_type}): text-carrying block "
                f"must have 'spans' or 'text'"
            )
        elif has_spans:
            if len(block["spans"]) == 0:
                errors.append(
                    f"Block {block_id} ({block_type}): 'spans' array is empty"
                )
            for i, span in enumerate(block["spans"]):
                errors.extend(validate_span(span, f"{block_id}.spans[{i}]"))

    # Structural blocks must NOT have text
    if block_type in BLOCK_TYPES_STRUCTURAL:
        if "spans" in block or "text" in block:
            # Warning, not error — we'll just ignore the text
            logger.warning(
                f"Block {block_id} ({block_type}): structural block has "
                f"text/spans (will be ignored)"
            )

    # Block-type-specific metadata checks
    meta = block.get("meta", {})

    if block_type == BLOCK_HEADING:
        if "level" not in meta:
            errors.append(
                f"Block {block_id} (heading): missing meta.level "
                f"(expected 2, 3, or 4)"
            )
        elif meta["level"] not in (2, 3, 4):
            errors.append(
                f"Block {block_id} (heading): meta.level={meta['level']} "
                f"(expected 2, 3, or 4)"
            )

    if block_type == BLOCK_LIST:
        if "list_type" not in meta:
            errors.append(
                f"Block {block_id} (list): missing meta.list_type "
                f"(expected 'ordered' or 'unordered')"
            )
        elif meta["list_type"] not in ("ordered", "unordered"):
            errors.append(
                f"Block {block_id} (list): meta.list_type='{meta['list_type']}' "
                f"(expected 'ordered' or 'unordered')"
            )
        if "list_group" not in meta:
            errors.append(
                f"Block {block_id} (list): missing meta.list_group "
                f"(integer grouping ID)"
            )

    if block_type == BLOCK_CHAPTER_HEADING:
        # chapter_number can be an int or None (for unnumbered chapters)
        if "chapter_number" not in meta:
            errors.append(
                f"Block {block_id} (chapter_heading): missing "
                f"meta.chapter_number (int or null)"
            )

    return errors


def normalize_block_text(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a block's text representation to the canonical spans format.

    If the block has 'text' (legacy string format) but no 'spans', convert it to:
        spans: [{"text": block["text"], "marks": []}]

    Returns a new block dict (does not mutate the input).
    """
    block = dict(block)  # shallow copy

    block_type = block.get("type", "")

    # Only normalize text-carrying blocks
    if block_type in BLOCK_TYPES_STRUCTURAL:
        # Remove any accidental text on structural blocks
        block.pop("text", None)
        block.pop("spans", None)
        return block

    if block_type in BLOCK_TYPES_WITH_TEXT:
        has_spans = "spans" in block and isinstance(block.get("spans"), list)
        has_text = "text" in block and isinstance(block.get("text"), str)

        if has_text and not has_spans:
            # Legacy format → convert to spans
            block["spans"] = [{"text": block["text"], "marks": []}]
            del block["text"]

    return block


def validate_artifact(artifact: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate an entire manuscript artifact.

    Returns:
        (is_valid, list_of_error_messages)
    """
    errors = []

    # Schema version
    sv = artifact.get("schema_version")
    if sv not in SCHEMA_VERSIONS_ACCEPTED:
        errors.append(
            f"Unsupported schema_version '{sv}' "
            f"(accepted: {sorted(SCHEMA_VERSIONS_ACCEPTED)})"
        )

    # Artifact type
    if artifact.get("artifact_type") != "manuscript":
        errors.append(
            f"Expected artifact_type='manuscript', "
            f"got '{artifact.get('artifact_type')}'"
        )

    # Content
    content = artifact.get("content")
    if not content:
        errors.append("Missing 'content' section")
        return (False, errors)

    blocks = content.get("blocks")
    if not blocks or not isinstance(blocks, list):
        errors.append("Missing or empty 'content.blocks' array")
        return (False, errors)

    if len(blocks) == 0:
        errors.append("'content.blocks' is empty")

    # Validate each block
    for i, block in enumerate(blocks):
        block_errors = validate_block(block)
        errors.extend(block_errors)

    is_valid = len(errors) == 0
    return (is_valid, errors)


def normalize_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an artifact: convert all legacy text fields to spans format.

    Returns a new artifact dict (does not deeply mutate the input).
    """
    artifact = dict(artifact)
    content = dict(artifact.get("content", {}))
    blocks = content.get("blocks", [])

    content["blocks"] = [normalize_block_text(block) for block in blocks]
    artifact["content"] = content

    return artifact
