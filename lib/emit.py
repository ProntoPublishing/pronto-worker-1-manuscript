"""
Emit a manuscript.v2.0 artifact from a RuleContext.

Also exposes the Operational Policy versioned storage-key helper per I-8
(key-and-artifact agreement).
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
from uuid import uuid4

SCHEMA_VERSION = "2.0"


def build_artifact(
    *,
    ctx_blocks: list,
    ctx_applied_rules: list,
    ctx_warnings: list,
    ctx_rule_faults: list,
    worker_version: str,
    rules_version: str,
    service_id: str,
    project_id: str,
    run_id: Optional[str] = None,
    source_meta: Dict[str, Any],
    processed_at: Optional[datetime] = None,
    processing_time_seconds: Optional[float] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Assemble the top-level v2.0 artifact object.

    Caller is responsible for filling source_meta with source_hash_sha256
    and ingested_at (the extractor doesn't know these).
    """
    processed_at = processed_at or datetime.now(timezone.utc)
    run_id = run_id or str(uuid4())

    artifact: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "worker_version": worker_version,
        "rules_version": rules_version,
        "artifact_type": "manuscript",
        "artifact_id": f"art_{uuid4().hex[:16]}",
        "service_id": service_id,
        "source": source_meta,
        "processing": {
            "worker_name": "worker_1_manuscript_processor",
            "run_id": run_id,
            "project_id": project_id,
            "processed_at": processed_at.isoformat(),
        },
        "content": {
            "blocks": ctx_blocks,
        },
        "applied_rules": ctx_applied_rules,
        "warnings": ctx_warnings,
        "rule_faults": ctx_rule_faults,
    }
    if processing_time_seconds is not None:
        artifact["processing"]["processing_time_seconds"] = processing_time_seconds
    if dry_run:
        artifact["processing"]["dry_run"] = True
    return artifact


def versioned_key(
    *,
    project_intake_submission_id: str,
    service_sku: str,
    schema_version: str = SCHEMA_VERSION,
    worker_version: str,
    rules_version: str,
) -> str:
    """Compose the v2.0 storage key (Doc 22 §Operational Policy → Re-Run
    and Artifact Versioning).

    Form:
        services/{submission_id}/{sku}/manuscript/v{schema}/w{worker}-r{rules}/manuscript.json

    Per I-8, every segment MUST agree with the corresponding artifact field.
    """
    return (
        f"services/{project_intake_submission_id}/{service_sku}"
        f"/manuscript/v{schema_version}"
        f"/w{worker_version}-r{rules_version}"
        f"/manuscript.json"
    )


def legacy_v1_key(service_id: str) -> str:
    """Pre-v2.0 flat key format, retained for grandfathered lookups per
    Doc 22 §Legacy-Artifact Migration.
    """
    return f"services/{service_id}/manuscript.v1.json"


def compute_source_hash(file_path: Path) -> str:
    """SHA-256 of the source DOCX. Populates source.source_hash_sha256."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
