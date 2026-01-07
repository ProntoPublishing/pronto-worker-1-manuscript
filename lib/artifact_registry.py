"""
Pronto Artifacts Registry - Schema Loader
Version: 1.0.0
Purpose: Load and cache artifact schemas for validation
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional


class ArtifactRegistryError(Exception):
    """Base exception for artifact registry errors"""
    pass


class SchemaNotFoundError(ArtifactRegistryError):
    """Raised when a schema file cannot be found"""
    pass


class SchemaLoadError(ArtifactRegistryError):
    """Raised when a schema file cannot be loaded or parsed"""
    pass


class ArtifactRegistry:
    """
    Registry for loading and caching artifact schemas.
    
    Usage:
        registry = ArtifactRegistry()
        schema = registry.get_schema("manuscript", "1.0")
    """
    
    def __init__(self, registry_path: Optional[str] = None):
        """
        Initialize the artifact registry.
        
        Args:
            registry_path: Path to the artifacts registry directory.
                          If None, uses the parent directory of this file.
        """
        if registry_path is None:
            # Default to parent directory of this file
            registry_path = Path(__file__).parent.parent
        
        self.registry_path = Path(registry_path)
        self._schema_cache: Dict[tuple, dict] = {}
        
        if not self.registry_path.exists():
            raise ArtifactRegistryError(
                f"Registry path does not exist: {self.registry_path}"
            )
    
    def get_schema(self, artifact_type: str, schema_version: str) -> dict:
        """
        Load and return a schema for the given artifact type and version.
        
        Args:
            artifact_type: Type of artifact (e.g., "manuscript", "interior_pdf")
            schema_version: Schema version (e.g., "1.0", "1.1", "2.0")
        
        Returns:
            Parsed JSON schema as a dictionary
        
        Raises:
            SchemaNotFoundError: If the schema file doesn't exist
            SchemaLoadError: If the schema file can't be parsed
        """
        cache_key = (artifact_type, schema_version)
        
        # Check cache first
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]
        
        # Build schema file path
        schema_filename = f"{artifact_type}.v{schema_version}.schema.json"
        schema_path = self.registry_path / artifact_type / schema_filename
        
        if not schema_path.exists():
            raise SchemaNotFoundError(
                f"Schema not found: {schema_path}\n"
                f"Artifact type: {artifact_type}\n"
                f"Schema version: {schema_version}"
            )
        
        # Load and parse schema
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
        except json.JSONDecodeError as e:
            raise SchemaLoadError(
                f"Failed to parse schema: {schema_path}\n"
                f"Error: {e}"
            )
        except Exception as e:
            raise SchemaLoadError(
                f"Failed to load schema: {schema_path}\n"
                f"Error: {e}"
            )
        
        # Cache and return
        self._schema_cache[cache_key] = schema
        return schema
    
    def list_schemas(self, artifact_type: Optional[str] = None) -> Dict[str, list]:
        """
        List all available schemas in the registry.
        
        Args:
            artifact_type: Optional filter by artifact type
        
        Returns:
            Dictionary mapping artifact types to lists of available versions
        """
        schemas = {}
        
        # Get all artifact type directories
        if artifact_type:
            artifact_dirs = [self.registry_path / artifact_type]
        else:
            artifact_dirs = [
                d for d in self.registry_path.iterdir()
                if d.is_dir() and not d.name.startswith('_')
            ]
        
        for artifact_dir in artifact_dirs:
            if not artifact_dir.exists():
                continue
            
            artifact_name = artifact_dir.name
            versions = []
            
            # Find all schema files
            for schema_file in artifact_dir.glob(f"{artifact_name}.v*.schema.json"):
                # Extract version from filename
                # Format: {artifact_type}.v{version}.schema.json
                filename = schema_file.name
                version_part = filename.replace(f"{artifact_name}.v", "").replace(".schema.json", "")
                versions.append(version_part)
            
            if versions:
                schemas[artifact_name] = sorted(versions)
        
        return schemas
    
    def get_latest_version(self, artifact_type: str) -> Optional[str]:
        """
        Get the latest version for a given artifact type.
        
        Args:
            artifact_type: Type of artifact
        
        Returns:
            Latest version string (e.g., "1.0") or None if no schemas found
        """
        schemas = self.list_schemas(artifact_type)
        versions = schemas.get(artifact_type, [])
        
        if not versions:
            return None
        
        # Simple string sort works for semantic versions
        # (assumes proper formatting: "1.0", "1.1", "2.0", etc.)
        return versions[-1]
    
    def clear_cache(self):
        """Clear the schema cache. Useful for testing or hot-reloading."""
        self._schema_cache.clear()


# Singleton instance for convenience
_default_registry: Optional[ArtifactRegistry] = None


def get_default_registry() -> ArtifactRegistry:
    """
    Get the default singleton registry instance.
    
    Returns:
        Default ArtifactRegistry instance
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ArtifactRegistry()
    return _default_registry


def get_schema(artifact_type: str, schema_version: str) -> dict:
    """
    Convenience function to get a schema using the default registry.
    
    Args:
        artifact_type: Type of artifact
        schema_version: Schema version
    
    Returns:
        Parsed JSON schema
    """
    return get_default_registry().get_schema(artifact_type, schema_version)


def list_schemas(artifact_type: Optional[str] = None) -> Dict[str, list]:
    """
    Convenience function to list schemas using the default registry.
    
    Args:
        artifact_type: Optional filter by artifact type
    
    Returns:
        Dictionary mapping artifact types to version lists
    """
    return get_default_registry().list_schemas(artifact_type)


if __name__ == "__main__":
    # Example usage
    registry = ArtifactRegistry()
    
    print("Available schemas:")
    for artifact_type, versions in registry.list_schemas().items():
        print(f"  {artifact_type}: {', '.join(versions)}")
    
    print("\nLoading manuscript.v1.0 schema...")
    schema = registry.get_schema("manuscript", "1.0")
    print(f"  Title: {schema.get('title')}")
    print(f"  Required fields: {schema.get('required')}")
