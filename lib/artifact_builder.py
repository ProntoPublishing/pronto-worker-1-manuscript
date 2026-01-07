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
- Lineage tracking (parent artifacts)

Author: Pronto Publishing
Version: 4.0.0
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
            worker_version: Version of the worker (e.g., "4.0.0")
        """
        self.worker_name = worker_name
        self.worker_version = worker_version
    
    def build(
        self,
        blocks: List[Dict[str, Any]],
        warnings: List[Dict[str, Any]],
        source_meta: Dict[str, Any],
        service_id: str,
        parent_artifacts: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Build complete manuscript artifact.
        
        Args:
            blocks: List of extracted blocks
            warnings: List of detected warnings
            source_meta: Source file metadata
            service_id: Airtable service record ID
            parent_artifacts: Optional list of parent artifacts (for lineage)
            
        Returns:
            Complete manuscript.v1.json artifact
        """
        run_id = str(uuid4())
        produced_at = datetime.now(timezone.utc).isoformat()
        
        artifact = {
            # Schema metadata
            "schema_version": "1.0",
            "artifact_type": "manuscript",
            "artifact_version": "1",
            
            # Source provenance
            "source": {
                "original_filename": source_meta.get('original_filename'),
                "original_format": source_meta.get('original_format'),
                "service_id": service_id,
                "uploaded_at": None,  # Could be populated from Airtable
                "file_size_bytes": None,  # Could be populated
                "file_hash": None  # Could be populated
            },
            
            # Processing metadata
            "processing": {
                "worker_name": self.worker_name,
                "worker_version": self.worker_version,
                "run_id": run_id,
                "started_at": produced_at,  # Simplified (would track separately in production)
                "completed_at": produced_at,
                "duration_seconds": 0  # Simplified
            },
            
            # Content blocks
            "content": {
                "blocks": blocks,
                "total_blocks": len(blocks),
                "block_type_counts": self._count_block_types(blocks)
            },
            
            # Analysis warnings
            "analysis": {
                "warnings": warnings,
                "total_warnings": len(warnings),
                "warnings_by_severity": self._count_by_severity(warnings),
                "warnings_by_code": self._count_by_code(warnings)
            },
            
            # Metadata
            "meta": {
                "detected_chapters": source_meta.get('detected_chapters', 0),
                "has_front_matter": source_meta.get('has_front_matter', False),
                "has_back_matter": source_meta.get('has_back_matter', False),
                "total_paragraphs": source_meta.get('total_paragraphs'),
                "total_pages": source_meta.get('total_pages'),
                "total_lines": source_meta.get('total_lines')
            },
            
            # Lineage tracking
            "parent_artifacts": parent_artifacts or []
        }
        
        logger.info(f"Built artifact: {len(blocks)} blocks, {len(warnings)} warnings")
        
        return artifact
    
    def _count_block_types(self, blocks: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count occurrences of each block type."""
        counts = {}
        for block in blocks:
            block_type = block['type']
            counts[block_type] = counts.get(block_type, 0) + 1
        return counts
    
    def _count_by_severity(self, warnings: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count warnings by severity level."""
        counts = {'error': 0, 'warning': 0, 'info': 0}
        for warning in warnings:
            severity = warning.get('severity', 'info')
            counts[severity] = counts.get(severity, 0) + 1
        return counts
    
    def _count_by_code(self, warnings: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count warnings by warning code."""
        counts = {}
        for warning in warnings:
            code = warning['code']
            counts[code] = counts.get(code, 0) + 1
        return counts
