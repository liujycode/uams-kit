r"""
MigrationCopyService - Copies legacy source files to UAMS migration directory.

This module implements Requirement 3.2: Copies each manifest entry to
<UAMS_ROOT>/migration/copies/<manifest-id>/ preserving relative paths,
and records byte length and SHA-256 digest during copy.

Validates: Requirements 3.2
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from uams.adapters.legacy_source_adapter import LegacySourceAdapter
from uams.services.source_discovery import SourceManifest, SourceManifestEntry


@dataclass
class CopyResult:
    """Result of copying a single file."""
    relative_path: str
    source_byte_length: int
    source_sha256: str
    copy_byte_length: int
    copy_sha256: str
    success: bool
    error_message: Optional[str] = None
    
    @property
    def is_valid(self) -> bool:
        """Check if the copy matches the source."""
        return (self.success and 
                self.source_byte_length == self.copy_byte_length and
                self.source_sha256 == self.copy_sha256)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "relativePath": self.relative_path,
            "sourceByteLength": self.source_byte_length,
            "sourceSha256": self.source_sha256,
            "copyByteLength": self.copy_byte_length,
            "copySha256": self.copy_sha256,
            "success": self.success,
            "errorMessage": self.error_message,
        }


@dataclass
class MigrationCopyReport:
    """Report of a complete migration copy operation."""
    manifest_id: str
    started_at: datetime
    completed_at: datetime
    total_entries: int
    successful_copies: int
    failed_copies: int
    results: List[CopyResult]
    
    @property
    def is_complete(self) -> bool:
        """Check if all copies were successful."""
        return self.failed_copies == 0
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "manifestId": self.manifest_id,
            "startedAt": self.started_at.isoformat(),
            "completedAt": self.completed_at.isoformat(),
            "totalEntries": self.total_entries,
            "successfulCopies": self.successful_copies,
            "failedCopies": self.failed_copies,
            "results": [r.to_dict() for r in self.results],
        }


class MigrationCopyService:
    r"""
    Service for copying legacy source files to UAMS migration directory.
    
    This service reads source files via the read-only LegacySourceAdapter
    and copies them to <UAMS_ROOT>/migration/copies/<manifest-id>/
    preserving relative paths.
    
    Requirements validated:
    - 3.2: Copy each manifest entry preserving relative paths and byte content,
           recording byte length and SHA-256 digest
    
    Example:
        service = MigrationCopyService(uams_root, source_root)
        report = service.copy_manifest(manifest)
        print(f"Copied {report.successful_copies}/{report.total_entries} files")
    """
    
    # Buffer size for file copying
    COPY_BUFFER_SIZE = 65536  # 64KB
    
    def __init__(self, uams_root: str, source_root: str,
                 audit_log_path: Optional[str] = None):
        r"""
        Initialize the migration copy service.
        
        Args:
            uams_root: The UAMS root directory for output
            source_root: The legacy source root (e.g., ~\.claude)
            audit_log_path: Optional path for audit logging
        """
        self._uams_root = Path(uams_root)
        self._source_root = source_root
        self._adapter = LegacySourceAdapter(source_root, audit_log_path)
        self._copies_dir = self._uams_root / "migration" / "copies"
    
    @property
    def copies_dir(self) -> Path:
        """Return the copies output directory."""
        return self._copies_dir
    
    def copy_manifest(self, manifest: SourceManifest) -> MigrationCopyReport:
        """
        Copy all files from a manifest to the migration copies directory.
        
        This method:
        1. Creates <UAMS_ROOT>/migration/copies/<manifest-id>/ directory
        2. For each entry in the manifest:
           - Reads the source file via LegacySourceAdapter (read-only)
           - Copies to the target location preserving relative path
           - Computes and records byte length and SHA-256 digest
        3. Returns a report with all copy results
        
        Args:
            manifest: The source manifest to copy
            
        Returns:
            MigrationCopyReport with results of all copy operations
        """
        started_at = datetime.now(timezone.utc)
        results = []
        
        # Create the copy target directory
        copy_target_dir = self._copies_dir / manifest.manifest_id
        
        for entry in manifest.entries:
            result = self._copy_single_entry(entry, copy_target_dir)
            results.append(result)
        
        completed_at = datetime.now(timezone.utc)
        
        # Count successes and failures
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        
        return MigrationCopyReport(
            manifest_id=manifest.manifest_id,
            started_at=started_at,
            completed_at=completed_at,
            total_entries=len(results),
            successful_copies=successful,
            failed_copies=failed,
            results=results,
        )
    
    def copy_entry(self, manifest_id: str, entry: SourceManifestEntry) -> CopyResult:
        """
        Copy a single manifest entry.
        
        Args:
            manifest_id: The manifest identifier
            entry: The entry to copy
            
        Returns:
            CopyResult with the outcome
        """
        copy_target_dir = self._copies_dir / manifest_id
        return self._copy_single_entry(entry, copy_target_dir)
    
    def get_copy_path(self, manifest_id: str, relative_path: str) -> Path:
        """
        Get the path where a copy would be stored.
        
        Args:
            manifest_id: The manifest identifier
            relative_path: The relative path of the file
            
        Returns:
            Path to the copy location
        """
        return self._copies_dir / manifest_id / relative_path
    
    def verify_copy(self, manifest_id: str, entry: SourceManifestEntry) -> CopyResult:
        """
        Verify an existing copy matches the manifest entry.
        
        This method reads the existing copy and compares it against
        the manifest entry's recorded byte length and SHA-256 digest.
        
        Args:
            manifest_id: The manifest identifier
            entry: The manifest entry to verify against
            
        Returns:
            CopyResult with verification outcome
        """
        copy_path = self.get_copy_path(manifest_id, entry.relativePath)
        
        if not copy_path.exists():
            return CopyResult(
                relative_path=entry.relativePath,
                source_byte_length=entry.byteLength,
                source_sha256=entry.sha256,
                copy_byte_length=0,
                copy_sha256="",
                success=False,
                error_message="Copy file does not exist",
            )
        
        try:
            # Read the copy and compute digest
            copy_stat = copy_path.stat()
            copy_byte_length = copy_stat.st_size
            copy_sha256 = self._compute_file_digest(copy_path)
            
            return CopyResult(
                relative_path=entry.relativePath,
                source_byte_length=entry.byteLength,
                source_sha256=entry.sha256,
                copy_byte_length=copy_byte_length,
                copy_sha256=copy_sha256,
                success=True,
            )
        except Exception as e:
            return CopyResult(
                relative_path=entry.relativePath,
                source_byte_length=entry.byteLength,
                source_sha256=entry.sha256,
                copy_byte_length=0,
                copy_sha256="",
                success=False,
                error_message=str(e),
            )
    
    def _copy_single_entry(self, entry: SourceManifestEntry, 
                           copy_target_dir: Path) -> CopyResult:
        """
        Copy a single manifest entry.
        
        Args:
            entry: The manifest entry to copy
            copy_target_dir: The target directory for copies
            
        Returns:
            CopyResult with the outcome
        """
        try:
            # Read source content via read-only adapter
            content = self._adapter.read_file(entry.relativePath)
            
            # Determine target path
            target_path = copy_target_dir / entry.relativePath
            
            # Ensure parent directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write content to target
            with open(target_path, 'wb') as f:
                f.write(content)
            
            # Compute digest of written file
            copy_sha256 = self._compute_file_digest(target_path)
            copy_byte_length = len(content)
            
            return CopyResult(
                relative_path=entry.relativePath,
                source_byte_length=entry.byteLength,
                source_sha256=entry.sha256,
                copy_byte_length=copy_byte_length,
                copy_sha256=copy_sha256,
                success=True,
            )
            
        except Exception as e:
            return CopyResult(
                relative_path=entry.relativePath,
                source_byte_length=entry.byteLength,
                source_sha256=entry.sha256,
                copy_byte_length=0,
                copy_sha256="",
                success=False,
                error_message=str(e),
            )
    
    def _compute_file_digest(self, file_path: Path) -> str:
        """
        Compute SHA-256 digest of a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Hexadecimal SHA-256 digest string
        """
        sha256_hash = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(self.COPY_BUFFER_SIZE)
                if not chunk:
                    break
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
