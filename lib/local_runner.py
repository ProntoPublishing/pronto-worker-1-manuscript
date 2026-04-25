"""
Local runner — bypass Airtable/R2/HTTP, drive the W1 pipeline directly.

Purpose
  The production path (`pronto_worker_1.ManuscriptProcessor.process_service`)
  threads through Airtable lookups, R2 uploads, and the Flask HTTP layer.
  All of that is irrelevant when you want to:
    - Iterate on rule changes against a fixture corpus
    - Diff golden artifacts in CI to catch unintended drift
    - Repro a corpus-test finding deterministically

  This module exposes the *pure pipeline*: DOCX in, manuscript.v2.0 JSON
  out. No network, no Airtable, no R2, no run_id-of-the-day.

Determinism
  When `deterministic=True` (the default), every wall-clock-derived or
  random field in the artifact is pinned:
    - run_id            → "00000000-0000-0000-0000-000000000000"
    - artifact_id       → "art_local0000000000" (no entropy)
    - processed_at      → "1970-01-01T00:00:00+00:00"
    - ingested_at       → "1970-01-01T00:00:00+00:00"
    - service_id        → "local"
    - project_id        → "local"
  Plus `processing.processing_time_seconds` is omitted entirely.

  Non-deterministic-by-design fields are kept (and ARE deterministic
  given the same input bytes):
    - source.source_hash_sha256
    - source.original_file_size_bytes
    - source.original_filename
    - source.original_format

CLI
    python -m pronto_worker_1 --local --input <docx> --output <json>
                              [--update-golden] [--no-deterministic]

  See pronto_worker_1.py's __main__ block.
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .cir import extract_docx
from .emit import build_artifact, compute_source_hash, SCHEMA_VERSION
from .pipeline import run_all_phases
from .rules.base import RuleContext
from .rules.rejection import RuleRejectException

logger = logging.getLogger(__name__)


# Pinned values for deterministic mode. Chosen to be obviously
# synthetic so a stray production run carrying these can't be
# mistaken for a real artifact in operational logs.
DETERMINISTIC_RUN_ID = "00000000-0000-0000-0000-000000000000"
DETERMINISTIC_ARTIFACT_ID = "art_local0000000000"
DETERMINISTIC_TIMESTAMP_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)
DETERMINISTIC_TIMESTAMP_STR = DETERMINISTIC_TIMESTAMP_DT.isoformat()
DETERMINISTIC_SERVICE_ID = "local"
DETERMINISTIC_PROJECT_ID = "local"


class LocalRunResult:
    """Payload from `run_local()`. Carries the artifact + a brief summary."""

    __slots__ = ("artifact", "blocks_count", "warnings_count",
                 "rule_faults_count", "applied_rules_count",
                 "rejected", "rejection_rule", "rejection_message")

    def __init__(self) -> None:
        self.artifact: Optional[Dict[str, Any]] = None
        self.blocks_count: int = 0
        self.warnings_count: int = 0
        self.rule_faults_count: int = 0
        self.applied_rules_count: int = 0
        self.rejected: bool = False
        self.rejection_rule: Optional[str] = None
        self.rejection_message: Optional[str] = None


def run_local(
    input_path: Path | str,
    output_path: Optional[Path | str] = None,
    *,
    deterministic: bool = True,
    intake_metadata: Optional[Dict[str, Any]] = None,
    worker_version: str,
    rules_version: str,
) -> LocalRunResult:
    """Run the full W1 pipeline against a local DOCX file.

    Args
        input_path: Source DOCX (or other ingest-supported format).
        output_path: Where to write the JSON artifact. If None, the
            artifact is built and returned in the result but not
            written.
        deterministic: When True, non-deterministic artifact fields
            (run_id, timestamps, artifact_id) are pinned to fixed
            values so repeated runs produce byte-identical JSON.
        intake_metadata: Optional dict for H-001 (title/subtitle/author
            from the intake submission). When None, H-001 has nothing
            to compare against and won't fire — fine for fixtures that
            don't exercise H-001.
        worker_version, rules_version: Required. Caller passes the
            module-level constants from pronto_worker_1 so this module
            doesn't have to know them.

    Returns
        LocalRunResult. On a Layer-4 rejection (R-001 etc.) the result
        carries `rejected=True` and `rejection_*` populated; artifact
        is None and nothing is written.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"input not found: {input_path}")

    started_at = (
        DETERMINISTIC_TIMESTAMP_DT if deterministic
        else datetime.now(timezone.utc)
    )

    ctx = RuleContext(blocks=[], intake_metadata=intake_metadata)
    factory_args = {"source_path": str(input_path)}

    result = LocalRunResult()

    # Phase 1: ingest. R-001 fires here. A rejection halts the run
    # cleanly — we surface it on the result and exit early.
    from .pipeline import run_phase
    try:
        run_phase("ingest", ctx, factory_args=factory_args)
    except RuleRejectException as e:
        result.rejected = True
        result.rejection_rule = e.rule_id
        result.rejection_message = e.message
        logger.warning(
            f"local run rejected by {e.rule_id}: {e.message}"
        )
        return result

    # Phase 2: extract DOCX → CIR. (N-002 acceptance happens inside.)
    blocks, extra_source = extract_docx(str(input_path))
    ctx.blocks = blocks

    # Phases 3..6: strip → classify → normalize → validate → emit.
    for phase in ("strip", "classify", "normalize", "validate", "emit"):
        run_phase(phase, ctx, factory_args=factory_args)

    # Build the artifact. Source meta is deterministic given input
    # bytes; only the timestamp varies.
    source_meta = {
        "original_filename": input_path.name,
        "original_format": input_path.suffix.lstrip(".").lower() or "docx",
        "original_file_size_bytes": input_path.stat().st_size,
        "source_hash_sha256": compute_source_hash(input_path),
        "ingested_at": (
            DETERMINISTIC_TIMESTAMP_STR if deterministic
            else datetime.now(timezone.utc).isoformat()
        ),
        # source_url intentionally omitted in --local mode (no URL).
    }
    if extra_source.get("original_filename"):
        source_meta["original_filename"] = extra_source["original_filename"]

    finished_at = (
        DETERMINISTIC_TIMESTAMP_DT if deterministic
        else datetime.now(timezone.utc)
    )

    artifact = build_artifact(
        ctx_blocks=ctx.blocks,
        ctx_applied_rules=ctx.applied_rules,
        ctx_warnings=ctx.warnings,
        ctx_rule_faults=ctx.rule_faults,
        worker_version=worker_version,
        rules_version=rules_version,
        service_id=(DETERMINISTIC_SERVICE_ID if deterministic else "local"),
        project_id=(DETERMINISTIC_PROJECT_ID if deterministic else "local"),
        run_id=(DETERMINISTIC_RUN_ID if deterministic else None),
        source_meta=source_meta,
        processed_at=finished_at,
        # processing_time_seconds intentionally omitted in deterministic
        # mode; non-deterministic local runs also omit it (it's a
        # wall-clock-derived field with no value to a local run).
        processing_time_seconds=None,
        manuscript_meta=ctx.manuscript_meta,
    )

    if deterministic:
        # build_artifact synthesizes artifact_id from uuid4().hex. Pin
        # it post-hoc rather than threading another override through
        # the production builder signature.
        artifact["artifact_id"] = DETERMINISTIC_ARTIFACT_ID

    result.artifact = artifact
    result.blocks_count = len(ctx.blocks)
    result.warnings_count = len(ctx.warnings)
    result.rule_faults_count = len(ctx.rule_faults)
    result.applied_rules_count = len(ctx.applied_rules)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Keys in document order, indented for diff-readability. The
        # JSON encoder is deterministic given a deterministic Python
        # dict iteration order (3.7+ preserves insertion order); our
        # builder inserts in a fixed order.
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(artifact, f, indent=2, ensure_ascii=False,
                      sort_keys=False)
            f.write("\n")
        logger.info(
            f"local run wrote {output_path} "
            f"(blocks={result.blocks_count}, "
            f"applied={result.applied_rules_count}, "
            f"warnings={result.warnings_count}, "
            f"faults={result.rule_faults_count})"
        )

    return result
