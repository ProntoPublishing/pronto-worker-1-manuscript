"""
Pronto Artifacts Registry - Canonical Hashing
Version: 1.0.0
Purpose: Compute stable, canonical hashes of artifacts for lineage tracking
"""

import hashlib
import json
from typing import Any, Dict


def compute_artifact_hash(artifact: Dict[str, Any], algorithm: str = "sha256") -> str:
    """
    Compute a canonical hash of an artifact.
    
    Uses stable JSON serialization (sorted keys, UTF-8 encoding) to ensure
    the same artifact always produces the same hash.
    
    Args:
        artifact: Artifact dictionary to hash
        algorithm: Hash algorithm to use (default: "sha256")
    
    Returns:
        Hash string with algorithm prefix (e.g., "sha256:abc123...")
    
    Example:
        artifact_hash = compute_artifact_hash(artifact_json)
        # Returns: "sha256:a1b2c3d4e5f6..."
    """
    # Serialize to canonical JSON (sorted keys, no whitespace, UTF-8)
    canonical_json = json.dumps(
        artifact,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )
    
    # Encode to UTF-8 bytes
    json_bytes = canonical_json.encode('utf-8')
    
    # Compute hash
    if algorithm == "sha256":
        hash_obj = hashlib.sha256(json_bytes)
    elif algorithm == "sha1":
        hash_obj = hashlib.sha1(json_bytes)
    elif algorithm == "md5":
        hash_obj = hashlib.md5(json_bytes)
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    
    # Return with algorithm prefix
    return f"{algorithm}:{hash_obj.hexdigest()}"


def verify_artifact_hash(
    artifact: Dict[str, Any],
    expected_hash: str
) -> bool:
    """
    Verify that an artifact matches an expected hash.
    
    Args:
        artifact: Artifact dictionary to verify
        expected_hash: Expected hash with algorithm prefix (e.g., "sha256:abc123...")
    
    Returns:
        True if hash matches, False otherwise
    
    Example:
        is_valid = verify_artifact_hash(artifact_json, "sha256:abc123...")
        if not is_valid:
            print("Artifact has been modified!")
    """
    # Extract algorithm from expected hash
    if ':' not in expected_hash:
        raise ValueError(
            f"Invalid hash format: {expected_hash}. Expected format: 'algorithm:hash'"
        )
    
    algorithm, expected_digest = expected_hash.split(':', 1)
    
    # Compute actual hash
    actual_hash = compute_artifact_hash(artifact, algorithm)
    
    # Compare
    return actual_hash == expected_hash


def compute_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """
    Compute hash of a file (for source file hashing).
    
    Args:
        file_path: Path to file
        algorithm: Hash algorithm to use (default: "sha256")
    
    Returns:
        Hash string WITHOUT algorithm prefix (just the hex digest)
    
    Example:
        source_hash = compute_file_hash("manuscript.docx")
        # Returns: "a1b2c3d4e5f6..." (no prefix)
    """
    if algorithm == "sha256":
        hash_obj = hashlib.sha256()
    elif algorithm == "sha1":
        hash_obj = hashlib.sha1()
    elif algorithm == "md5":
        hash_obj = hashlib.md5()
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")
    
    # Read file in chunks to handle large files
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            hash_obj.update(chunk)
    
    return hash_obj.hexdigest()


def extract_hash_algorithm(hash_string: str) -> tuple[str, str]:
    """
    Extract algorithm and digest from a hash string.
    
    Args:
        hash_string: Hash with algorithm prefix (e.g., "sha256:abc123...")
    
    Returns:
        Tuple of (algorithm, digest)
    
    Example:
        algorithm, digest = extract_hash_algorithm("sha256:abc123...")
        # Returns: ("sha256", "abc123...")
    """
    if ':' not in hash_string:
        raise ValueError(
            f"Invalid hash format: {hash_string}. Expected format: 'algorithm:hash'"
        )
    
    algorithm, digest = hash_string.split(':', 1)
    return algorithm, digest


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python artifact_hash.py <artifact.json>")
        sys.exit(1)
    
    artifact_file = sys.argv[1]
    
    try:
        with open(artifact_file, 'r', encoding='utf-8') as f:
            artifact = json.load(f)
        
        # Compute hash
        artifact_hash = compute_artifact_hash(artifact)
        print(f"Artifact hash: {artifact_hash}")
        
        # Verify hash
        is_valid = verify_artifact_hash(artifact, artifact_hash)
        print(f"Verification: {'✓ PASS' if is_valid else '✗ FAIL'}")
        
        # Also compute file hash
        file_hash = compute_file_hash(artifact_file)
        print(f"File hash (sha256): {file_hash}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
