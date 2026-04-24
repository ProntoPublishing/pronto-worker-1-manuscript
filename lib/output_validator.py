"""
Worker 1 Output Validator
==========================

Validates and normalizes Worker 1's manuscript.v1.json output before upload.
Ensures the artifact conforms to the shared manuscript schema contract.

This module should be called after block extraction and before R2 upload.

Usage:
    from output_validator import validate_and_normalize_output

    # After extracting blocks...
    artifact = build_artifact(blocks, source_meta, processing_meta, analysis)

    # Validate and normalize before upload
    artifact, report = validate_and_normalize_output(artifact)
    if not report["valid"]:
        raise RuntimeError(f"Output validation failed: {report['errors']}")

    # Now safe to upload
    r2_client.upload_json(key, artifact)

Author: Pronto Publishing
Version: 1.0.0

Claude Code edit (2026-04-23, pre-merge session):
  Step 1 ("Set schema version") changed to hold the stamped schema_version at
  "1.0" for this deploy instead of bumping to SCHEMA_VERSION_CURRENT. Reason:
  Worker 2's artifact_validator is hardcoded to schema_version="1.0" and the
  canonical `manuscript.v1.0.schema.json` enum is ["1.0"]; bumping here would
  cause Worker 2 to reject every artifact. The spans-only format change is
  backward compatible within v1.0, so we stay at "1.0" until the three-surface
  bump lands as a coordinated follow-up. SCHEMA_VERSIONS_ACCEPTED is now
  imported so the validator tolerates an incoming "1.0" or "1.1" artifact
  without rewriting it. See MIGRATION_NOTES.md.

Claude Code integration into Worker 1 repo (2026-04-23):
  Dropped into `lib/output_validator.py`. Shared-schema import is relative to
  the `lib/` package, matching the existing intra-package convention (see
  `lib/artifact_validator.py`, `lib/artifact_builder.py`). Call site is wired
  into `pronto_worker_1.py` between artifact build and R2 upload.

Claude Code edit (2026-04-23, addendum #1 — Manus partner review):
  Removed the two fabricating auto-fix helpers per Pronto canon doc 09
  ("Worker 1 is not allowed to be creative") and doc 16 ("failure is a state,
  not an exception"): the helper that defaulted `heading.meta.level` to 2,
  and the helper that invented `chapter_heading.meta.chapter_number` via a
  counter. Both are gone, along with their imports. The schema validator in
  Step 4 now surfaces those as errors instead.
  Kept the list grouping helper because grouping consecutive `list` blocks is
  structural inference from context, not invention. Renamed it to
  `_warn_and_group_bare_lists` and demoted its messages from fixes_applied to
  warnings, plus a prominent logger.warning per bare block, so operators see
  that Worker 1's extractor is emitting incomplete list metadata. The artifact
  still renders; the extractor still gets flagged for repair.
  Worker 1's `block_extractor.py` must natively produce meta.level on every
  heading and meta.chapter_number on every chapter_heading BEFORE this
  validator is activated in strict mode, or every job will fail. See
  MIGRATION_NOTES.md for deploy-sequencing.
"""

import logging
from typing import Dict, Any, Tuple, List

from .manuscript_schema import (
    SCHEMA_VERSION_CURRENT,
    SCHEMA_VERSIONS_ACCEPTED,
    BLOCK_TYPES,
    BLOCK_TYPES_WITH_TEXT,
    BLOCK_LIST,
    validate_artifact,
    normalize_artifact,
)

logger = logging.getLogger(__name__)


def validate_and_normalize_output(
    artifact: Dict[str, Any],
    strict: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Validate and normalize a manuscript artifact before upload.

    Steps:
      1. Normalize schema_version conservatively (hold at "1.0" for this deploy).
      2. Normalize all blocks (legacy text → spans format).
      3. Group bare `list` blocks that are missing `list_group`/`list_type`
         metadata, emitting a warning per occurrence so Worker 1's extractor
         gets fixed. Other missing metadata (heading level, chapter_number)
         is no longer auto-fixed — the schema validator will surface it.
      4. Validate against the shared schema.
      5. Return the cleaned artifact and a validation report.

    Args:
        artifact: The raw manuscript artifact dict.
        strict: If True, raise on validation errors. If False, return errors
                in the report but don't raise.

    Returns:
        Tuple of (normalized_artifact, report_dict).
        report_dict has keys: valid (bool), errors (list), warnings (list),
        fixes_applied (list).
    """
    report = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "fixes_applied": [],
    }

    # Step 1: Normalize schema version conservatively.
    # For this deploy, Worker 2's artifact_validator is hardcoded to schema_version="1.0"
    # and the canonical JSON schema file (manuscript.v1.0.schema.json) has enum ["1.0"].
    # Bumping to "1.1" here without updating those two surfaces would cause Worker 2
    # to reject every artifact. The format change (spans-only) is backward compatible
    # within v1.0, so we stay at "1.0" until the JSON schema + Worker 2 validator
    # are updated in a coordinated follow-up.
    old_version = artifact.get("schema_version")
    if old_version not in SCHEMA_VERSIONS_ACCEPTED:
        artifact["schema_version"] = "1.0"
        report["fixes_applied"].append(
            f"schema_version: '{old_version}' → '1.0' (was missing or invalid)"
        )
    # else: leave it alone

    # Step 2: Normalize text → spans
    artifact = normalize_artifact(artifact)
    report["fixes_applied"].append("Normalized all blocks to spans format")

    # Step 3: Warn about (and group) bare `list` blocks missing metadata.
    # We no longer fabricate heading level or chapter_number — those must come
    # from Worker 1's extractor. The schema validator in Step 4 will surface
    # any that are missing.
    blocks = artifact.get("content", {}).get("blocks", [])
    _warn_and_group_bare_lists(blocks, report)

    # Step 4: Validate
    is_valid, errors = validate_artifact(artifact)

    if not is_valid:
        report["valid"] = False
        report["errors"] = errors
        logger.error(
            f"Output validation failed with {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors[:20])
        )
        if strict:
            raise RuntimeError(
                f"Worker 1 output validation failed: {len(errors)} error(s). "
                f"First: {errors[0]}"
            )
    else:
        logger.info("Output validation passed")

    return artifact, report


def _warn_and_group_bare_lists(
    blocks: List[Dict[str, Any]], report: Dict[str, Any]
) -> None:
    """
    Group consecutive `list` blocks that are missing `list_group` / `list_type`
    metadata, and emit a WARNING for each occurrence.

    This is structural inference from context (adjacent `list` blocks share a
    group), not fabrication, so the artifact still renders correctly. But
    Worker 1's extractor is supposed to emit these fields natively — every
    warning here means the extractor has a bug. Operators should log and
    fix the extractor rather than rely on this fallback.
    """
    group_id = 0
    in_list = False

    for block in blocks:
        if block.get("type") != BLOCK_LIST:
            if in_list:
                in_list = False
            continue

        meta = block.setdefault("meta", {})
        block_id = block.get("id")

        if "list_group" not in meta:
            if not in_list:
                group_id += 1
                in_list = True
            meta["list_group"] = group_id
            msg = (
                f"Block {block_id}: `list` block missing meta.list_group; "
                f"grouped with consecutive bare lists as group {group_id}. "
                f"Worker 1 extractor should emit list_group natively."
            )
            report["warnings"].append(msg)
            logger.warning(msg)
        else:
            in_list = True

        if "list_type" not in meta:
            meta["list_type"] = "unordered"
            msg = (
                f"Block {block_id}: `list` block missing meta.list_type; "
                f"defaulted to 'unordered'. Worker 1 extractor should emit "
                f"list_type natively (ordered|unordered)."
            )
            report["warnings"].append(msg)
            logger.warning(msg)
