"""
Pronto Artifacts Registry - Validation Utilities
Version: 1.0.0
Purpose: Validate artifacts against their schemas
"""

import json
from typing import Any, Dict, List, Optional

try:
    import jsonschema
    from jsonschema import Draft7Validator, validators
except ImportError:
    raise ImportError(
        "jsonschema is required for validation. Install with: pip install jsonschema"
    )

from .artifact_registry import get_schema, SchemaNotFoundError


class ArtifactValidationError(Exception):
    """
    Raised when an artifact fails validation.
    
    Attributes:
        artifact_type: Type of artifact that failed validation
        schema_version: Schema version used for validation
        validation_errors: List of validation error dictionaries
        message: Human-readable error summary
    """
    
    def __init__(
        self,
        artifact_type: str,
        schema_version: str,
        validation_errors: List[Dict[str, Any]],
        message: Optional[str] = None
    ):
        self.artifact_type = artifact_type
        self.schema_version = schema_version
        self.validation_errors = validation_errors
        self.message = message or self._build_message()
        super().__init__(self.message)
    
    def _build_message(self) -> str:
        """Build a human-readable error message from validation errors."""
        error_count = len(self.validation_errors)
        summary = f"Artifact validation failed: {error_count} error(s) found\n"
        summary += f"Artifact type: {self.artifact_type}\n"
        summary += f"Schema version: {self.schema_version}\n\n"
        
        for i, error in enumerate(self.validation_errors[:5], 1):  # Show first 5
            path = error.get('path', 'unknown')
            message = error.get('message', 'unknown error')
            summary += f"{i}. {path}: {message}\n"
        
        if error_count > 5:
            summary += f"\n... and {error_count - 5} more errors"
        
        return summary
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_type": "ArtifactValidationError",
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "validation_errors": self.validation_errors,
            "message": self.message
        }


def validate_artifact(
    artifact: Dict[str, Any],
    expected_artifact_type: Optional[str] = None,
    expected_schema_version: Optional[str] = None
) -> None:
    """
    Validate an artifact against its schema.
    
    Args:
        artifact: Artifact dictionary to validate
        expected_artifact_type: Optional expected artifact type (validates artifact_type field)
        expected_schema_version: Optional expected schema version (validates schema_version field)
    
    Raises:
        ArtifactValidationError: If validation fails
        SchemaNotFoundError: If the schema doesn't exist
    
    Example:
        try:
            validate_artifact(artifact_json, "manuscript", "1.0")
        except ArtifactValidationError as e:
            print(f"Validation failed: {e.message}")
            for error in e.validation_errors:
                print(f"  - {error['path']}: {error['message']}")
    """
    # Extract artifact type and schema version from artifact
    artifact_type = artifact.get("artifact_type")
    schema_version = artifact.get("schema_version")
    
    # Validate artifact_type field
    if not artifact_type:
        raise ArtifactValidationError(
            artifact_type="unknown",
            schema_version=schema_version or "unknown",
            validation_errors=[{
                "path": "artifact_type",
                "message": "Missing required field 'artifact_type'",
                "value": None
            }]
        )
    
    # Validate schema_version field
    if not schema_version:
        raise ArtifactValidationError(
            artifact_type=artifact_type,
            schema_version="unknown",
            validation_errors=[{
                "path": "schema_version",
                "message": "Missing required field 'schema_version'",
                "value": None
            }]
        )
    
    # Check expected values if provided
    if expected_artifact_type and artifact_type != expected_artifact_type:
        raise ArtifactValidationError(
            artifact_type=artifact_type,
            schema_version=schema_version,
            validation_errors=[{
                "path": "artifact_type",
                "message": f"Expected artifact_type '{expected_artifact_type}', got '{artifact_type}'",
                "value": artifact_type
            }]
        )
    
    if expected_schema_version and schema_version != expected_schema_version:
        raise ArtifactValidationError(
            artifact_type=artifact_type,
            schema_version=schema_version,
            validation_errors=[{
                "path": "schema_version",
                "message": f"Expected schema_version '{expected_schema_version}', got '{schema_version}'",
                "value": schema_version
            }]
        )
    
    # Load schema
    try:
        schema = get_schema(artifact_type, schema_version)
    except SchemaNotFoundError as e:
        raise ArtifactValidationError(
            artifact_type=artifact_type,
            schema_version=schema_version,
            validation_errors=[{
                "path": "schema",
                "message": f"Schema not found: {e}",
                "value": None
            }]
        )
    
    # Validate against schema
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(artifact))
    
    if errors:
        validation_errors = []
        for error in errors:
            # Build JSON path
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            
            validation_errors.append({
                "path": path,
                "message": error.message,
                "value": error.instance if hasattr(error, 'instance') else None,
                "schema_path": ".".join(str(p) for p in error.schema_path) if error.schema_path else None
            })
        
        raise ArtifactValidationError(
            artifact_type=artifact_type,
            schema_version=schema_version,
            validation_errors=validation_errors
        )


def validate_artifact_file(
    file_path: str,
    expected_artifact_type: Optional[str] = None,
    expected_schema_version: Optional[str] = None
) -> None:
    """
    Validate an artifact from a JSON file.
    
    Args:
        file_path: Path to artifact JSON file
        expected_artifact_type: Optional expected artifact type
        expected_schema_version: Optional expected schema version
    
    Raises:
        ArtifactValidationError: If validation fails
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        artifact = json.load(f)
    
    validate_artifact(artifact, expected_artifact_type, expected_schema_version)


def check_warnings(artifact: Dict[str, Any], max_severity: str = "medium") -> List[Dict[str, Any]]:
    """
    Check artifact warnings and return those above a severity threshold.
    
    Args:
        artifact: Artifact dictionary
        max_severity: Maximum acceptable severity ("low", "medium", "high")
    
    Returns:
        List of warnings above the threshold
    
    Example:
        high_warnings = check_warnings(artifact, max_severity="medium")
        if high_warnings:
            print(f"Found {len(high_warnings)} high-severity warnings")
            for warning in high_warnings:
                print(f"  - {warning['code']}: {warning.get('message', 'No message')}")
    """
    severity_levels = {"low": 0, "medium": 1, "high": 2}
    threshold = severity_levels.get(max_severity, 1)
    
    warnings = artifact.get("analysis", {}).get("warnings", [])
    
    return [
        w for w in warnings
        if severity_levels.get(w.get("severity", "low"), 0) > threshold
    ]


def check_quality_metrics(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check artifact quality metrics and return potential issues.
    
    Args:
        artifact: Artifact dictionary
    
    Returns:
        Dictionary of quality issues (empty if all good)
    
    Example:
        issues = check_quality_metrics(artifact)
        if issues:
            print("Quality issues detected:")
            for metric, issue in issues.items():
                print(f"  - {metric}: {issue}")
    """
    quality = artifact.get("analysis", {}).get("quality", {})
    issues = {}
    
    # Check chapter boundary confidence
    confidence = quality.get("chapter_boundary_confidence", 1.0)
    if confidence < 0.8:
        issues["chapter_boundary_confidence"] = (
            f"Low confidence ({confidence:.2f}). Manual review recommended."
        )
    
    # Check if OCR was used
    if quality.get("ocr_used", False):
        issues["ocr_used"] = (
            "OCR was used. Text quality may be lower than native text extraction."
        )
    
    # Check parsing errors
    parsing_errors = quality.get("parsing_errors_count", 0)
    if parsing_errors > 0:
        issues["parsing_errors"] = (
            f"{parsing_errors} parsing error(s) encountered during processing."
        )
    
    return issues


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python artifact_validate.py <artifact.json>")
        sys.exit(1)
    
    artifact_file = sys.argv[1]
    
    try:
        print(f"Validating {artifact_file}...")
        validate_artifact_file(artifact_file)
        print("✓ Validation passed!")
        
        # Load and check warnings
        with open(artifact_file, 'r') as f:
            artifact = json.load(f)
        
        high_warnings = check_warnings(artifact, max_severity="medium")
        if high_warnings:
            print(f"\n⚠ Found {len(high_warnings)} high-severity warnings:")
            for warning in high_warnings:
                print(f"  - {warning['code']}: {warning.get('message', 'No message')}")
        
        quality_issues = check_quality_metrics(artifact)
        if quality_issues:
            print(f"\n⚠ Quality issues detected:")
            for metric, issue in quality_issues.items():
                print(f"  - {metric}: {issue}")
        
    except ArtifactValidationError as e:
        print(f"✗ Validation failed:\n{e.message}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
