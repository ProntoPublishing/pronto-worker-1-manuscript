"""
Artifact Builder - Manuscript Artifact Construction
====================================================

Builds manuscript.v1.json artifacts conforming to Pronto Artifacts Registry.

Includes:
- Schema version and artifact metadata
- Source provenance
- Processing metadata
- Content blocks with inline marks
- Analysis warnings

Author: Pronto Publishing
Version: 4.1.0 (Schema-compliant)
"""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ArtifactBuilder:
    """Builds manuscript.v1.json artifacts."""
    
    def __init__(self, worker_name: str, worker_version: str):
        """
        Initialize artifact builder.
        
        Args:
            worker_name: Name of the worker (e.g., "worker_1_manuscript_processor")
            worker_version: Version of the worker (e.g., "4.1.0")
        """
        self.worker_name = worker_name
        self.worker_version = worker_version
    
    def build(
        self,
        blocks: List[Dict[str, Any]],
        warnings: List[Dict[str, Any]],
        source_meta: Dict[str, Any],
        service_id: str,
        project_id: str,
        file_size_bytes: int,
        file_hash_sha256: str,
        ingested_at: str
    ) -> Dict[str, Any]:
        """
        Build complete manuscript artifact.
        
        Args:
            blocks: List of extracted blocks
            warnings: List of detected warnings
            source_meta: Source file metadata
            service_id: Airtable service record ID
            project_id: Airtable project record ID
            file_size_bytes: Original file size in bytes
            file_hash_sha256: SHA-256 hash of the original file
            ingested_at: ISO 8601 timestamp when file was ingested
            
        Returns:
            Complete manuscript.v1.json artifact
        """
        run_id = str(uuid4())
        processed_at = datetime.now(timezone.utc).isoformat()
        
        # Calculate word count from blocks
        word_count = 0
        for block in blocks:
            if 'text' in block:
                word_count += len(block['text'].split())
            elif 'spans' in block:
                for span in block['spans']:
                    word_count += len(span['text'].split())
        
        chapter_count = sum(1 for block in blocks if block.get('type') == 'chapter_heading')
        
        artifact = {
            # Schema metadata
            "schema_version": "1.0",
            "artifact_type": "manuscript",
            "artifact_version": "1",
            
            # Source provenance
            "source": {
                "original_filename": source_meta.get('original_filename'),
                "original_format": source_meta.get('original_format'),
                "original_file_size_bytes": file_size_bytes,
                "source_hash_sha256": file_hash_sha256,
                "ingested_at": ingested_at
            },
            
            # Processing metadata
            "processing": {
                "worker_name": self.worker_name,
                "worker_version": self.worker_version,
                "run_id": run_id,
                "project_id": project_id,
                "service_id": service_id,
                "processed_at": processed_at
            },
            
            # Content blocks
            "content": {
                "language": "en",
                "reading_direction": "ltr",
                "blocks": blocks,
                "stats": {
                    "word_count": word_count,
                    "block_count": len(blocks),
                    "chapter_count": chapter_count
                }
            },
            
            # Analysis warnings
            "analysis": {
                "warnings": warnings,
                "unsupported_elements": [],
                "quality": {
                    "chapter_boundary_confidence": 0.9,
                    "ocr_used": False
                }
            }
        }
        
        logger.info(f"Built artifact: {len(blocks)} blocks, {len(warnings)} warnings")
        
        return artifact
