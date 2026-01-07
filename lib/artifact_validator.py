"""
Artifact Validator - Worker 1 Wrapper
======================================

Simplified wrapper around artifact_validate.py for Worker 1 usage.
Converts exception-based validation to dict-based return values.

Author: Pronto Publishing
Version: 4.2.1
"""

import logging
from typing import Dict, Any

from .artifact_validate import (
    validate_artifact as _validate_artifact,
    ArtifactValidationError,
)
from .artifact_registry import SchemaNotFoundError

logger = logging.getLogger(__name__)


def validate_artifact(
    artifact: Dict[str, Any],
    artifact_type: str,
    schema_version: str
) -> Dict[str, Any]:
    """
    Validate artifact against schema.
    
    Wraps the exception-based artifact_validate.validate_artifact()
    and returns a dict with 'valid' and 'errors' keys.
    
    Args:
        artifact: Artifact data to validate
        artifact_type: Type of artifact (e.g., "manuscript")
        schema_version: Schema version (e.g., "1.0")
        
    Returns:
        Dict with 'valid' (bool) and 'errors' (list) keys
    """
    try:
        # underlying validate_artifact returns None on success and raises on failure
        _validate_artifact(artifact, artifact_type, schema_version)
        logger.info(f"Artifact validation passed: {artifact_type} v{schema_version}")
        return {"valid": True, "errors": []}

    except (ArtifactValidationError, SchemaNotFoundError) as e:
        # ArtifactValidationError has a nice message; SchemaNotFoundError may too
        msg = getattr(e, "message", str(e))
        logger.error(f"Artifact validation failed: {artifact_type} v{schema_version}: {msg}")
        return {"valid": False, "errors": [msg]}

    except Exception as e:
        logger.error(f"Validation error: {str(e)}")
        return {"valid": False, "errors": [str(e)]}
