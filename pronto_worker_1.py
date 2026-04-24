"""
Pronto Worker 1 - Manuscript Processor v5.0.0-a1
=================================================

Manuscript.v2.0 producer. Implements Doc 22 v1.0.2 normalization rules as
a phased pipeline (ingest → strip → classify → normalize → validate →
emit). Orchestrates DOCX ingest, rule execution, artifact emit, R2 upload,
and Airtable state transitions. Replaces the v4.x manuscript.v1.0 producer
path; the old modules (block_extractor.py, warning_detector.py,
artifact_builder.py, artifact_validator.py, output_validator.py,
manuscript_schema.py) remain in-tree for reference but are unused by
this version.

Key contract shifts from v4.x → v5.0.0
  - Output schema: manuscript.v1.0 (flat blocks) → manuscript.v2.0
    (CIR blocks + classified roles + role-specific fields).
  - Storage key: services/{service_id}/manuscript.v1.json → versioned
    form per Doc 22 §Operational Policy (I-8):
      services/{intake_submission_id}/{service_sku}/manuscript/v{schema}
        /w{worker_version}-r{rules_version}/manuscript.json
    Legacy v1 artifacts at the flat path remain readable (grandfathered
    per Doc 22 Legacy-Artifact Migration).
  - Rules + faults: rule firings + validator warnings + fault records
    all live on the artifact as structured top-level arrays. No more
    Operator Notes JSON blob; see REVIEW_NOTES M10.
  - Terminal default: Doc 22 v1.0.2 Patch 1 CIR-type → role mapping
    applied at end of Classify, so every emitted block has a non-null
    role (I-2).
  - Fault-safe emission: rule exceptions become rule_faults[] entries;
    artifact still emits. Service state transition is governed by the
    Operational Policy fault-threshold policy, not per-rule panics.

NOT DEPLOYED. This module lives only on feature/w1-v2-impl and MUST
NOT be merged to main or released to Railway until:
  (a) W2 v1.3 parallel-reader lands and accepts manuscript.v2.0.
  (b) Corpus-testing conversation has happened and revealed any Doc 22
      rule adjustments that need to land before production.
  (c) The storage-key placeholders below (project_intake_submission_id,
      service_sku derivation) are resolved against the real Airtable
      schema — currently carrying TODO markers.
See MIGRATION_NOTES.md at the repo root for the no-deploy gate details.

Author: Pronto Publishing
Version: 5.0.0-a1
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import requests
from pyairtable import Api

from lib.pronto_r2_client import ProntoR2Client

# v2 pipeline
from lib.cir import extract_docx
from lib.pipeline import run_all_phases
from lib.rules.base import RuleContext
from lib.rules.rejection import RuleRejectException
from lib.emit import build_artifact, versioned_key, compute_source_hash, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

WORKER_NAME = "worker_1_manuscript_processor"
WORKER_VERSION = "5.0.0-a1"   # SemVer 2.0 pre-release. Bump to "5.0.0" on release.
RULES_VERSION = "1.0.2"       # Doc 22 version this worker implements.

# Fault-threshold policy from Doc 22 §Operational Policy (v1.0 defaults).
MAX_LAYER_2_FAULTS_BEFORE_FAIL = 3
ANY_LAYER_4_FAULT_FAILS = True


# Environment
AIRTABLE_TOKEN        = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID      = os.getenv("AIRTABLE_BASE_ID")
R2_ACCOUNT_ID         = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID      = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY  = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME        = os.getenv("R2_BUCKET_NAME", "pronto-artifacts")
R2_PUBLIC_BASE_URL    = os.getenv("R2_PUBLIC_BASE_URL")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class ManuscriptProcessor:
    """Orchestrator for the v5.0.0 manuscript pipeline."""

    def __init__(self) -> None:
        self.airtable = Api(AIRTABLE_TOKEN)
        self.base = self.airtable.base(AIRTABLE_BASE_ID)
        self.services_table = self.base.table("Services")
        self.manuscripts_table = self.base.table("Manuscripts")
        # Best-effort handles. Not all deployments have these; reads are
        # guarded.
        try:
            self.projects_table = self.base.table("Projects")
        except Exception:
            self.projects_table = None
        try:
            self.book_metadata_table = self.base.table("Book Metadata")
        except Exception:
            self.book_metadata_table = None

        self.r2_client = ProntoR2Client(
            account_id=R2_ACCOUNT_ID,
            access_key_id=R2_ACCESS_KEY_ID,
            secret_access_key=R2_SECRET_ACCESS_KEY,
            bucket_name=R2_BUCKET_NAME,
            public_base_url=R2_PUBLIC_BASE_URL,
        )

    # -- top-level entry -----------------------------------------------------

    def process_service(self, service_id: str) -> Dict[str, Any]:
        """Process a Service record end-to-end.

        Returns a result dict with `success`, `status`, plus v2.0-specific
        fields (`artifact_url`, `artifact_key`, `rule_faults_count`,
        `warnings_count`, `blocks_count`). On a rejection (L4 halt) or
        hard exception, returns `success: False` with an error field.
        """
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        logger.info(f"[{run_id}] W1 v{WORKER_VERSION} starting for service {service_id}")

        try:
            # 1. Fetch + guard.
            service = self.services_table.get(service_id)
            current_status = service["fields"].get("Status")
            if current_status == "Complete":
                logger.info(f"[{run_id}] Service {service_id} already Complete — skip")
                return {"success": True, "status": "already_complete",
                        "service_id": service_id}
            if current_status == "Processing":
                logger.info(f"[{run_id}] Service {service_id} already Processing — skip to avoid race")
                return {"success": True, "status": "already_processing",
                        "service_id": service_id}

            # 2. Claim.
            self._claim_service(service_id)

            # 3. Resolve inputs.
            manuscript_info = self._get_manuscript_url(service)
            if not manuscript_info:
                raise ValueError("No manuscript file found in linked Manuscripts record")
            file_url, filename = manuscript_info

            project_id = self._get_project_id(service)
            intake_metadata = self._fetch_intake_metadata(service, project_id)
            intake_submission_id, service_sku = self._derive_storage_ids(service, project_id)

            # 4. Download.
            file_path = self._download_file(file_url, filename)
            ingested_at = datetime.now(timezone.utc).isoformat()

            # 5. Build the RuleContext. R-001 inspects the source path;
            # if it's not a .docx the rule raises RuleRejectException.
            ctx = RuleContext(blocks=[], intake_metadata=intake_metadata)
            factory_args = {"source_path": file_path}

            try:
                from lib.pipeline import run_phase
                run_phase("ingest", ctx, factory_args=factory_args)
            except RuleRejectException as e:
                logger.error(f"[{run_id}] {e.rule_id} rejected ingest: {e.message}")
                self._fail_service(service_id, error_message=f"{e.rule_id}: {e.message}")
                return {"success": False, "service_id": service_id,
                        "error": f"{e.rule_id}: {e.message}"}

            # 6. Extract DOCX → CIR. (N-002 tracked-change acceptance
            # happens inside the extractor.)
            blocks, extra_source = extract_docx(file_path)
            ctx.blocks = blocks

            # 7. Run the remaining phases (strip → classify → normalize →
            # validate → emit). Terminal default lands at the end of
            # classify via pipeline.run_phase.
            for phase in ("strip", "classify", "normalize", "validate", "emit"):
                run_phase(phase, ctx, factory_args=factory_args)

            # 8. Build the artifact.
            source_meta = {
                "original_filename": filename,
                "original_format": "docx",
                "original_file_size_bytes": os.path.getsize(file_path),
                "source_hash_sha256": compute_source_hash(Path(file_path)),
                "ingested_at": ingested_at,
                "source_url": file_url,
            }
            # extra_source from extract_docx carries the filename it
            # observed; prefer the caller's if they differ (the caller
            # knows the Airtable filename).
            source_meta.setdefault("original_filename", extra_source.get("original_filename"))

            finished_at = datetime.now(timezone.utc)
            artifact = build_artifact(
                ctx_blocks=ctx.blocks,
                ctx_applied_rules=ctx.applied_rules,
                ctx_warnings=ctx.warnings,
                ctx_rule_faults=ctx.rule_faults,
                worker_version=WORKER_VERSION,
                rules_version=RULES_VERSION,
                service_id=service_id,
                project_id=project_id or "",
                run_id=run_id,
                source_meta=source_meta,
                processed_at=finished_at,
                processing_time_seconds=(finished_at - started_at).total_seconds(),
                manuscript_meta=ctx.manuscript_meta,
            )

            # 9. Fault-threshold policy decides Complete vs Failed.
            final_state, fail_reason = self._decide_service_state(ctx)

            # 10. Upload even on Failed — the artifact carries the
            # rule_faults array and operators need it to diagnose.
            artifact_key = versioned_key(
                project_intake_submission_id=intake_submission_id,
                service_sku=service_sku,
                schema_version=SCHEMA_VERSION,
                worker_version=WORKER_VERSION,
                rules_version=RULES_VERSION,
            )
            upload_result = self.r2_client.upload_json(artifact_key, artifact)
            artifact_url = upload_result["public_url"]
            logger.info(f"[{run_id}] artifact uploaded: {artifact_url}")

            # 11. Airtable state transition.
            if final_state == "Complete":
                self._complete_service(
                    service_id=service_id,
                    artifact_url=artifact_url,
                    artifact_key=artifact_key,
                    warnings=ctx.warnings,
                    rule_faults=ctx.rule_faults,
                )
                return {
                    "success": True,
                    "status": "complete",
                    "service_id": service_id,
                    "artifact_url": artifact_url,
                    "artifact_key": artifact_key,
                    "blocks_count": len(ctx.blocks),
                    "warnings_count": len(ctx.warnings),
                    "rule_faults_count": len(ctx.rule_faults),
                }
            else:
                # Fault-threshold triggered Failed. Artifact still
                # uploaded; Error Log carries the reason.
                self._fail_service(
                    service_id=service_id,
                    error_message=fail_reason or "Fault-threshold exceeded",
                    artifact_url=artifact_url,
                    artifact_key=artifact_key,
                )
                return {
                    "success": False,
                    "status": "failed_threshold",
                    "service_id": service_id,
                    "artifact_url": artifact_url,
                    "artifact_key": artifact_key,
                    "error": fail_reason,
                    "rule_faults_count": len(ctx.rule_faults),
                }

        except Exception as e:
            logger.error(f"[{run_id}] processing failed: {e}")
            logger.error(traceback.format_exc())
            try:
                self._fail_service(service_id=service_id, error_message=str(e))
            except Exception as fail_exc:
                # I-7 tail: the fail-path itself must not reraise.
                logger.error(f"[{run_id}] _fail_service also raised: {fail_exc}")
            return {"success": False, "service_id": service_id, "error": str(e)}

    # -- fault threshold -----------------------------------------------------

    def _decide_service_state(self, ctx: RuleContext) -> Tuple[str, Optional[str]]:
        """Apply Doc 22 §Operational Policy fault-threshold defaults.

        Returns (state, reason). state ∈ {"Complete", "Failed"}. reason is
        None on Complete.
        """
        l4_faults = [f for f in ctx.rule_faults if (f.get("rule") or "").startswith("R-")]
        if ANY_LAYER_4_FAULT_FAILS and l4_faults:
            ids = ", ".join(sorted({f["rule"] for f in l4_faults}))
            return "Failed", f"Layer 4 rule fault(s): {ids}"

        l2_faults = [f for f in ctx.rule_faults if (f.get("rule") or "").startswith("C-")]
        if len(l2_faults) > MAX_LAYER_2_FAULTS_BEFORE_FAIL:
            return "Failed", (
                f"Layer 2 rule fault count {len(l2_faults)} exceeds "
                f"max_layer_2_faults_before_fail={MAX_LAYER_2_FAULTS_BEFORE_FAIL}"
            )
        return "Complete", None

    # -- Airtable helpers ----------------------------------------------------

    def _get_manuscript_url(self, service: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        links = service["fields"].get("Manuscripts", [])
        if not links:
            return None
        manuscript = self.manuscripts_table.get(links[0])
        attachments = manuscript["fields"].get("Manuscript File", [])
        if not attachments:
            return None
        att = attachments[0]
        return att["url"], att["filename"]

    def _get_project_id(self, service: Dict[str, Any]) -> Optional[str]:
        links = service["fields"].get("Project", [])
        return links[0] if links else None

    def _fetch_intake_metadata(
        self,
        service: Dict[str, Any],
        project_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Best-effort intake-metadata fetch for H-001.

        Walks Service → Project → Book Metadata when the tables and
        links exist. Falls back to Service record fields. Returns None
        when no meaningful data is available — H-001 won't fire.

        TODO (iter 8 / corpus conversation): firm up the walk against
        the real Airtable schema. Current field names are best-guess.
        """
        # 1. Try Book Metadata via Project.
        if project_id and self.projects_table is not None and self.book_metadata_table is not None:
            try:
                project = self.projects_table.get(project_id)
                bm_links = project["fields"].get("Book Metadata", [])
                if bm_links:
                    bm = self.book_metadata_table.get(bm_links[0])
                    f = bm.get("fields", {})
                    title  = f.get("Book Title") or f.get("Title")
                    author = f.get("Author Name") or f.get("Author")
                    subtitle = f.get("Subtitle")
                    if title or author:
                        return {
                            "title":    title or None,
                            "subtitle": subtitle or None,
                            "author":   author or None,
                        }
            except Exception as e:
                logger.warning(f"Book Metadata lookup failed, falling back: {e}")

        # 2. Fallback: Service-record fields directly.
        f = service.get("fields", {})
        title  = f.get("Book Title") or f.get("Title")
        author = f.get("Author Name") or f.get("Author")
        if title or author:
            return {"title": title or None, "subtitle": None, "author": author or None}
        return None

    def _derive_storage_ids(
        self,
        service: Dict[str, Any],
        project_id: Optional[str],
    ) -> Tuple[str, str]:
        """Derive (intake_submission_id, service_sku) for the I-8 storage
        key.

        TODO (iter 8 / corpus conversation): finalize against the real
        Airtable schema. Current behavior:
          - intake_submission_id: project's 'Intake Submission ID' field
            if present, else service_id as a stable-but-non-canonical
            fallback.
          - service_sku: service record's 'SKU' / 'Service SKU' field if
            present, else derived from Service Type via a small map,
            else 'UNKNOWN'.
        Both values appear in the storage key AND on the artifact;
        per I-8 they stay self-consistent within a single run even when
        the sources are placeholders.
        """
        fields = service.get("fields", {})
        intake_id: Optional[str] = None
        if project_id and self.projects_table is not None:
            try:
                project = self.projects_table.get(project_id)
                pf = project.get("fields", {})
                intake_id = (
                    pf.get("Intake Submission ID")
                    or pf.get("Submission ID")
                    or pf.get("Tally Submission ID")
                )
            except Exception as e:
                logger.warning(f"Project lookup for intake id failed: {e}")
        if not intake_id:
            intake_id = service.get("id") or ""

        sku = fields.get("Service SKU") or fields.get("SKU")
        if not sku:
            svc_type = (fields.get("Service Type") or "").strip().lower()
            sku_map = {
                "manuscript processing": "MSPROC",
                "interior formatting":    "INTFMT",
            }
            sku = sku_map.get(svc_type, "UNKNOWN")

        # Make both URL-safe: strip slashes and whitespace.
        intake_id = str(intake_id).strip().replace("/", "_")
        sku = str(sku).strip().replace("/", "_")
        return intake_id, sku

    # -- Airtable mutations --------------------------------------------------

    def _claim_service(self, service_id: str) -> None:
        self.services_table.update(service_id, {
            "Status": "Processing",
            "Started At": datetime.now(timezone.utc).isoformat(),
            "Worker Version": WORKER_VERSION,
            "Rules Version": RULES_VERSION,
        })
        logger.info(f"Claimed service {service_id}: Status → Processing")

    def _complete_service(
        self,
        *,
        service_id: str,
        artifact_url: str,
        artifact_key: str,
        warnings: List[Dict[str, Any]],
        rule_faults: List[Dict[str, Any]],
    ) -> None:
        fields: Dict[str, Any] = {
            "Status": "Complete",
            "Finished At": datetime.now(timezone.utc).isoformat(),
            "Artifact URL": artifact_url,
            "Artifact Key": artifact_key,
            "Artifact Type": "Manuscript JSON",
            "Schema Version": SCHEMA_VERSION,
            "Warning Count": len(warnings),
            "Rule Fault Count": len(rule_faults),
        }
        self.services_table.update(service_id, fields)
        logger.info(f"Completed service {service_id}: Status → Complete")

    def _fail_service(
        self,
        service_id: str,
        error_message: str,
        *,
        artifact_url: Optional[str] = None,
        artifact_key: Optional[str] = None,
    ) -> None:
        """Mark service Failed. Retries transient Airtable writes up to
        three times (I-7 tail: the fail path itself must not silently
        lose the state transition).
        """
        fields: Dict[str, Any] = {
            "Status": "Failed",
            "Finished At": datetime.now(timezone.utc).isoformat(),
            "Error Log": error_message[:10000],  # Airtable field cap.
        }
        if artifact_url:
            fields["Artifact URL"] = artifact_url
        if artifact_key:
            fields["Artifact Key"] = artifact_key

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                self.services_table.update(service_id, fields)
                logger.info(f"Failed service {service_id}: Status → Failed")
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"_fail_service attempt {attempt + 1} raised: {e}")
        # All retries exhausted. Log, do not raise (I-7).
        logger.error(
            f"_fail_service exhausted retries for {service_id}; "
            f"service may be stuck in Processing. Last error: {last_exc}"
        )

    # -- I/O ----------------------------------------------------------------

    def _download_file(self, url: str, filename: str) -> str:
        response = requests.get(url, stream=True, timeout=(10, 300))
        response.raise_for_status()
        ext = Path(filename).suffix or ".bin"
        temp_path = f"/tmp/manuscript_{uuid4().hex}{ext}"
        bytes_written = 0
        MAX_BYTES = 200 * 1024 * 1024  # 200 MB cap per REVIEW_NOTES C6.
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                bytes_written += len(chunk)
                if bytes_written > MAX_BYTES:
                    raise ValueError(
                        f"Manuscript file exceeds size cap ({MAX_BYTES} bytes)"
                    )
        return temp_path


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python pronto_worker_1.py <service_id>")
        sys.exit(1)
    service_id = sys.argv[1]

    required_vars = [
        "AIRTABLE_TOKEN", "AIRTABLE_BASE_ID",
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        "R2_PUBLIC_BASE_URL",
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    processor = ManuscriptProcessor()
    result = processor.process_service(service_id)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
