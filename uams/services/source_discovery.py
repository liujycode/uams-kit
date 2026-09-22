r"""
SourceDiscoveryService - Discovers and catalogs legacy Claude memory files.

This module implements Requirement 3.1: Creates a source manifest containing
every importable old Claude memory file's normalized relative path, byte length,
SHA-256 content digest, and source discovery timestamp.

Validates: Requirements 3.1
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from uams.adapters.legacy_source_adapter import LegacySourceAdapter, SourceFileInfo
from uams.models.source_manifest_entry import SourceManifestEntry


class SourceManifest:
    """
    A complete source manifest for migration.
    
    Contains all discovered files from the legacy source with their metadata.
    """
    
    def __init__(self, manifest_id: str, source_root: str, 
                 discovered_at: datetime, entries: List[SourceManifestEntry]):
        self.manifest_id = manifest_id
        self.source_root = source_root
        self.discovered_at = discovered_at
        self.entries = entries
    
    @property
    def entry_count(self) -> int:
        """Return the number of entries in the manifest."""
        return len(self.entries)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON persistence."""
        return {
            "manifestId": self.manifest_id,
            "sourceRoot": self.source_root,
            "discoveredAt": self.discovered_at.isoformat(),
            "entryCount": self.entry_count,
            "entries": [entry.to_dict() for entry in self.entries],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SourceManifest":
        """Deserialize from dictionary."""
        return cls(
            manifest_id=data["manifestId"],
            source_root=data["sourceRoot"],
            discovered_at=datetime.fromisoformat(data["discoveredAt"]),
            entries=[SourceManifestEntry.from_dict(e) for e in data["entries"]],
        )


class SourceDiscoveryService:
    r"""
    Service for discovering and cataloging legacy Claude memory files.
    
    This service enumerates all files beneath the protected source root
    (the legacy source root, e.g., ~\.claude\...) and creates a source manifest with
    metadata for each file.
    
    Requirements validated:
    - 3.1: Create source manifest with normalized relative path, byte length,
           SHA-256 digest, and discovery timestamp
    
    Example:
        service = SourceDiscoveryService(uams_root, source_root)
        manifest = service.discover()
        print(f"Discovered {manifest.entry_count} files")
    """
    
    def __init__(self, uams_root: str, source_root: str, 
                 audit_log_path: Optional[str] = None):
        r"""
        Initialize the source discovery service.
        
        Args:
            uams_root: The UAMS root directory for output
            source_root: The legacy source root (e.g., ~\.claude)
            audit_log_path: Optional path for audit logging
        """
        self._uams_root = Path(uams_root)
        self._source_root = source_root
        self._adapter = LegacySourceAdapter(source_root, audit_log_path)
        self._manifests_dir = self._uams_root / "migration" / "source-manifests"
    
    @property
    def manifests_dir(self) -> Path:
        """Return the manifests output directory."""
        return self._manifests_dir
    
    def discover(self, manifest_id: Optional[str] = None) -> SourceManifest:
        """
        Discover all files in the legacy source and create a manifest.
        
        This method:
        1. Enumerates all files beneath the source root
        2. Creates a SourceManifestEntry for each file with:
           - Normalized relative path
           - Byte length
           - SHA-256 content digest
           - Discovery timestamp
        3. Writes the manifest to <UAMS_ROOT>/migration/source-manifests/<manifest-id>.json
        
        Args:
            manifest_id: Optional manifest identifier. If not provided, one will be generated.
            
        Returns:
            SourceManifest containing all discovered files
        """
        # Generate manifest ID if not provided
        if manifest_id is None:
            manifest_id = self._generate_manifest_id()
        
        discovered_at = datetime.now(timezone.utc)
        
        # Enumerate files through the read-only adapter
        file_infos = self._adapter.enumerate_to_list(recursive=True)
        
        # Convert to SourceManifestEntry objects
        entries = []
        for file_info in file_infos:
            entry = SourceManifestEntry(
                relativePath=file_info.relative_path,
                byteLength=file_info.byte_length,
                sha256=file_info.sha256,
                discoveredAt=datetime.fromisoformat(file_info.discovered_at),
            )
            entries.append(entry)
        
        # Create the manifest
        manifest = SourceManifest(
            manifest_id=manifest_id,
            source_root=str(self._source_root),
            discovered_at=discovered_at,
            entries=entries,
        )
        
        # Persist the manifest
        self._write_manifest(manifest)
        
        return manifest
    
    def load_manifest(self, manifest_id: str) -> SourceManifest:
        """
        Load a previously created manifest.
        
        Args:
            manifest_id: The manifest identifier
            
        Returns:
            SourceManifest loaded from disk
            
        Raises:
            FileNotFoundError: If the manifest does not exist
        """
        manifest_path = self._manifests_dir / f"{manifest_id}.json"
        
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_id}")
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return SourceManifest.from_dict(data)
    
    def list_manifests(self) -> List[str]:
        """
        List all available manifest IDs.
        
        Returns:
            List of manifest identifiers
        """
        if not self._manifests_dir.exists():
            return []
        
        return [p.stem for p in self._manifests_dir.glob("*.json")]
    
    def _generate_manifest_id(self) -> str:
        """Generate a unique manifest identifier."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"manifest-{timestamp}-{unique_id}"
    
    def _write_manifest(self, manifest: SourceManifest) -> None:
        """
        Write the manifest to disk.
        
        Args:
            manifest: The manifest to persist
        """
        # Ensure the output directory exists
        self._manifests_dir.mkdir(parents=True, exist_ok=True)
        
        # Write the manifest file
        manifest_path = self._manifests_dir / f"{manifest.manifest_id}.json"
        
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)
