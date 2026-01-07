"""
Pronto Artifacts Registry - Lineage Tracking
Version: 1.0.0
Purpose: Build and track artifact lineage for full traceability
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


def build_lineage_entry(
    parent_key: str,
    parent_hash: str,
    parent_type: str,
    parent_version: str,
    produced_by: str,
    produced_at: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Build a lineage entry for a parent artifact.
    
    Args:
        parent_key: R2 key of the parent artifact (e.g., "services/recXXX/manuscript.v1.json")
        parent_hash: Hash of the parent artifact with algorithm prefix (e.g., "sha256:abc123...")
        parent_type: Type of the parent artifact (e.g., "manuscript")
        parent_version: Version of the parent artifact (e.g., "1")
        produced_by: Worker that produced the parent artifact (e.g., "worker_1_manuscript_processor")
        produced_at: When the parent was produced (defaults to now)
    
    Returns:
        Lineage entry dictionary
    
    Example:
        lineage = build_lineage_entry(
            parent_key="services/recXXX/manuscript.v1.json",
            parent_hash="sha256:abc123...",
            parent_type="manuscript",
            parent_version="1",
            produced_by="worker_1_manuscript_processor",
            produced_at=datetime.utcnow()
        )
    """
    if produced_at is None:
        produced_at = datetime.utcnow()
    
    return {
        "artifact_type": parent_type,
        "artifact_version": parent_version,
        "artifact_key": parent_key,
        "artifact_hash": parent_hash,
        "produced_by": produced_by,
        "produced_at": produced_at.isoformat() + "Z"
    }


def build_lineage_chain(
    artifact: Dict[str, Any],
    include_self: bool = True
) -> List[Dict[str, Any]]:
    """
    Build a complete lineage chain from an artifact.
    
    Args:
        artifact: Artifact dictionary (must have parent_artifacts field)
        include_self: Whether to include the artifact itself in the chain
    
    Returns:
        List of lineage entries from oldest (source) to newest (this artifact)
    
    Example:
        chain = build_lineage_chain(interior_pdf_artifact)
        # Returns: [manuscript entry, interior_pdf entry]
        
        for i, entry in enumerate(chain):
            print(f"{i+1}. {entry['artifact_type']} v{entry['artifact_version']}")
            print(f"   Produced by: {entry['produced_by']}")
            print(f"   Key: {entry['artifact_key']}")
    """
    chain = []
    
    # Add parent artifacts
    parent_artifacts = artifact.get("parent_artifacts", [])
    chain.extend(parent_artifacts)
    
    # Add self if requested
    if include_self:
        processing = artifact.get("processing", {})
        self_entry = {
            "artifact_type": artifact.get("artifact_type"),
            "artifact_version": artifact.get("artifact_version"),
            "artifact_key": None,  # Not known yet (not uploaded)
            "artifact_hash": None,  # Not computed yet
            "produced_by": processing.get("worker_name"),
            "produced_at": processing.get("processed_at")
        }
        chain.append(self_entry)
    
    return chain


def format_lineage_chain(chain: List[Dict[str, Any]]) -> str:
    """
    Format a lineage chain as a human-readable string.
    
    Args:
        chain: List of lineage entries
    
    Returns:
        Formatted string representation
    
    Example:
        chain = build_lineage_chain(artifact)
        print(format_lineage_chain(chain))
        # Output:
        # 1. manuscript v1 (worker_1_manuscript_processor @ 2026-01-03T12:00:00Z)
        #    → services/recXXX/manuscript.v1.json
        # 2. interior_pdf v1 (worker_2_interior_formatter @ 2026-01-03T12:05:00Z)
        #    → services/recXXX/interior_pdf.v1.json
    """
    lines = []
    for i, entry in enumerate(chain, 1):
        artifact_type = entry.get("artifact_type", "unknown")
        artifact_version = entry.get("artifact_version", "?")
        produced_by = entry.get("produced_by", "unknown")
        produced_at = entry.get("produced_at", "unknown")
        artifact_key = entry.get("artifact_key", "not yet uploaded")
        
        lines.append(
            f"{i}. {artifact_type} v{artifact_version} ({produced_by} @ {produced_at})"
        )
        lines.append(f"   → {artifact_key}")
    
    return "\n".join(lines)


def trace_artifact_to_source(
    artifact: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Trace an artifact back to its original source file.
    
    Args:
        artifact: Artifact dictionary
    
    Returns:
        Dictionary with source information
    
    Example:
        source_info = trace_artifact_to_source(interior_pdf_artifact)
        print(f"Original file: {source_info['original_filename']}")
        print(f"Uploaded at: {source_info['ingested_at']}")
        print(f"File hash: {source_info['source_hash']}")
    """
    # Walk back through parent artifacts to find the first one
    chain = build_lineage_chain(artifact, include_self=False)
    
    if not chain:
        # This artifact has no parents, check if it has source info
        source = artifact.get("source", {})
        if source:
            return {
                "original_filename": source.get("original_filename"),
                "original_format": source.get("original_format"),
                "original_file_size_bytes": source.get("original_file_size_bytes"),
                "source_hash": source.get("source_hash_sha256"),
                "ingested_at": source.get("ingested_at"),
                "source_url": source.get("source_url")
            }
        else:
            return {"error": "No source information found"}
    
    # The first artifact in the chain should have source info
    # In practice, we'd need to fetch that artifact from R2 and read its source field
    # For now, return the first parent's info
    first_parent = chain[0]
    return {
        "note": "To get source info, fetch the first parent artifact from R2",
        "first_parent_key": first_parent.get("artifact_key"),
        "first_parent_type": first_parent.get("artifact_type"),
        "first_parent_hash": first_parent.get("artifact_hash")
    }


def validate_lineage_integrity(
    artifact: Dict[str, Any],
    parent_artifacts_from_r2: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Validate lineage integrity by checking hashes.
    
    Args:
        artifact: Artifact dictionary
        parent_artifacts_from_r2: Optional list of actual parent artifacts fetched from R2
    
    Returns:
        Dictionary with validation results
    
    Example:
        # Fetch parent artifacts from R2
        parent_artifacts = [fetch_from_r2(key) for key in parent_keys]
        
        # Validate
        result = validate_lineage_integrity(artifact, parent_artifacts)
        if result['valid']:
            print("✓ Lineage integrity verified")
        else:
            print(f"✗ Lineage integrity failed: {result['errors']}")
    """
    from artifact_hash import compute_artifact_hash
    
    declared_parents = artifact.get("parent_artifacts", [])
    
    if not parent_artifacts_from_r2:
        return {
            "valid": None,
            "message": "Cannot validate without fetching parent artifacts from R2",
            "declared_parent_count": len(declared_parents)
        }
    
    if len(declared_parents) != len(parent_artifacts_from_r2):
        return {
            "valid": False,
            "error": f"Parent count mismatch: declared {len(declared_parents)}, provided {len(parent_artifacts_from_r2)}"
        }
    
    errors = []
    for i, (declared, actual) in enumerate(zip(declared_parents, parent_artifacts_from_r2)):
        declared_hash = declared.get("artifact_hash")
        actual_hash = compute_artifact_hash(actual)
        
        if declared_hash != actual_hash:
            errors.append({
                "parent_index": i,
                "parent_key": declared.get("artifact_key"),
                "declared_hash": declared_hash,
                "actual_hash": actual_hash,
                "message": "Hash mismatch - parent artifact has been modified or corrupted"
            })
    
    return {
        "valid": len(errors) == 0,
        "parent_count": len(declared_parents),
        "errors": errors if errors else None
    }


if __name__ == "__main__":
    # Example usage
    import json
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python artifact_lineage.py <artifact.json>")
        sys.exit(1)
    
    artifact_file = sys.argv[1]
    
    try:
        with open(artifact_file, 'r', encoding='utf-8') as f:
            artifact = json.load(f)
        
        print("Lineage Chain:")
        print("=" * 60)
        chain = build_lineage_chain(artifact, include_self=True)
        print(format_lineage_chain(chain))
        
        print("\n" + "=" * 60)
        print("Source Trace:")
        print("=" * 60)
        source_info = trace_artifact_to_source(artifact)
        for key, value in source_info.items():
            print(f"{key}: {value}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
