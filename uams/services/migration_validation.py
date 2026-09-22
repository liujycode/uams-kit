r"""
MigrationValidationService - Validates migration copies against source.

This module implements Requirements 3.3, 3.4, 3.5:
- 3.3: Validate every source manifest entry against migration copy
- 3.4: Mark migration as unaccepted if validation fails
- 3.5: Record migration acceptance with success/failure details

Validates: Requirements 3.3, 3.4, 3.5
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from uams.adapters.legacy_source_adapter import LegacySourceAdapter
from uams.models.migration_acceptance import (
    MigrationAcceptance, MigrationFailure, MigrationResult
)
from uams.services.source_discovery import SourceManifest, SourceManifestEntry
from uams.services.migration_copy import MigrationCopyService, CopyResult
from uams.services.migration_acceptance import MigrationAcceptanceStore
from uams.services.source_preservation import SourcePreservationReport, SourcePreservationService


class ValidationResult:
    """Result of validating a single entry."""
    
    def __init__(self, relative_path: str, is_valid: bool, 
                 failure_reason: Optional[str] = None):
        self.relative_path = relative_path
        self.is_valid = is_valid
        self.failure_reason = failure_reason
    
    def __bool__(self) -> bool:
        return self.is_valid


class MigrationValidationService:
    r"""
    Service for validating migration copies against source files.
    
    This service re-reads source files and compares them with migration
    copies to verify byte length and SHA-256 digest match.
    
    Requirements validated:
    - 3.3: Validate every source manifest entry against migration copy
           by normalized relative path, byte length, and SHA-256 digest
    - 3.4: Mark migration as unaccepted if validation fails,
           identify failing relative path, prevent write-source transition
    - 3.5: Record migration acceptance with manifest ID, validated entry count,
           validation timestamp, and result
    
    Example:
        service = MigrationValidationService(uams_root, source_root)
        acceptance = service.validate(manifest)
        if acceptance.is_accepted:
            print(f"Migration accepted: {acceptance.validatedEntryCount} entries")
        else:
            print(f"Migration failed: {len(acceptance.failures)} failures")
    """
    
    def __init__(self, uams_root: str, source_root: str,
                 audit_log_path: Optional[str] = None):
        r"""
        Initialize the migration validation service.
        
        Args:
            uams_root: The UAMS root directory for output
            source_root: The legacy source root (e.g., ~\.claude)
            audit_log_path: Optional path for audit logging
        """
        self._uams_root = Path(uams_root)
        self._source_root = source_root
        self._adapter = LegacySourceAdapter(source_root, audit_log_path)
        self._copy_service = MigrationCopyService(uams_root, source_root, audit_log_path)
        self._acceptance_store = MigrationAcceptanceStore(str(self._uams_root))
        self._acceptance_dir = self._acceptance_store.acceptance_dir
        self._preservation_service = SourcePreservationService(
            str(self._uams_root), source_root, audit_log_path
        )
        self._last_preservation_report: Optional[SourcePreservationReport] = None
    
    @property
    def acceptance_dir(self) -> Path:
        """Return the acceptance output directory."""
        return self._acceptance_dir
    
    def validate(self, manifest: SourceManifest) -> MigrationAcceptance:
        """
        Validate all entries in a manifest against their migration copies.
        
        This method:
        1. Re-reads source files through the read-only LegacySourceAdapter
        2. Compares each source file with its migration copy
        3. Verifies byte length and SHA-256 digest match
        4. Generates a MigrationAcceptance record with results
        
        Args:
            manifest: The source manifest to validate
            
        Returns:
            MigrationAcceptance with validation results
        """
        # Check source preservation as a separate read-only concern.  The
        # report logs only differences and never attempts to repair the source.
        self._last_preservation_report = self._preservation_service.check(manifest)

        failures = []
        validated_count = 0
        
        for entry in manifest.entries:
            validation = self._validate_entry(manifest.manifest_id, entry)
            
            if validation.is_valid:
                validated_count += 1
            else:
                failures.append(MigrationFailure(
                    relativePath=entry.relativePath,
                    reason=validation.failure_reason or "Unknown validation failure",
                ))
        
        # Determine result based on failures
        result = MigrationResult.SUCCESS if len(failures) == 0 else MigrationResult.FAILURE
        
        acceptance = MigrationAcceptance(
            manifestId=manifest.manifest_id,
            validatedEntryCount=validated_count,
            validatedAt=datetime.now(timezone.utc),
            result=result,
            failures=failures,
        )
        
        # Persist the acceptance record
        self._write_acceptance(acceptance)
        
        return acceptance
    
    def validate_entry(self, manifest_id: str, entry: SourceManifestEntry) -> ValidationResult:
        """
        Validate a single entry against its migration copy.
        
        This method:
        1. Re-reads the source file through the read-only adapter
        2. Reads the migration copy
        3. Compares byte length and SHA-256 digest
        
        Args:
            manifest_id: The manifest identifier
            entry: The manifest entry to validate
            
        Returns:
            ValidationResult indicating success or failure with reason
        """
        return self._validate_entry(manifest_id, entry)
    
    @property
    def last_preservation_report(self) -> Optional[SourcePreservationReport]:
        """Return the most recent source-preservation check result."""
        return self._last_preservation_report

    def check_source_preservation(self, manifest: SourceManifest) -> SourcePreservationReport:
        """Run the post-validation source preservation check explicitly."""
        self._last_preservation_report = self._preservation_service.check(manifest)
        return self._last_preservation_report

    def load_acceptance(self, manifest_id: str) -> MigrationAcceptance:
        """Load a previously persisted acceptance record."""
        return self._acceptance_store.load(manifest_id)
    
    def has_acceptance(self, manifest_id: str) -> bool:
        """
        Check if an acceptance record exists for a manifest.
        
        Args:
            manifest_id: The manifest identifier
            
        Returns:
            True if acceptance record exists
        """
        return self._acceptance_store.exists(manifest_id)
    
    def is_migration_accepted(self, manifest_id: str) -> bool:
        """
        Check if migration was accepted for a manifest.
        
        Args:
            manifest_id: The manifest identifier
            
        Returns:
            True if migration was accepted (successful validation)
        """
        if not self.has_acceptance(manifest_id):
            return False
        
        return self._acceptance_store.is_successful(manifest_id)
    
    def _validate_entry(self, manifest_id: str, 
                        entry: SourceManifestEntry) -> ValidationResult:
        """
        Internal method to validate a single entry.
        
        Args:
            manifest_id: The manifest identifier
            entry: The manifest entry to validate
            
        Returns:
            ValidationResult indicating success or failure
        """
        # First verify the source file still exists
        if not self._adapter.file_exists(entry.relativePath):
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason="Source file no longer exists",
            )
        
        # Re-read the source file and compute current digest
        try:
            source_content = self._adapter.read_file(entry.relativePath)
            source_byte_length = len(source_content)
            source_sha256 = self._adapter.compute_digest(source_content)
        except Exception as e:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Failed to read source file: {e}",
            )
        
        # Verify source matches manifest entry
        if source_byte_length != entry.byteLength:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Source byte length mismatch: manifest={entry.byteLength}, actual={source_byte_length}",
            )
        
        if source_sha256 != entry.sha256:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Source SHA-256 mismatch: manifest={entry.sha256}, actual={source_sha256}",
            )
        
        # Verify the migration copy exists
        copy_result = self._copy_service.verify_copy(manifest_id, entry)
        
        if not copy_result.success:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Copy verification failed: {copy_result.error_message}",
            )
        
        # Verify copy matches source
        if copy_result.copy_byte_length != source_byte_length:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Copy byte length mismatch: source={source_byte_length}, copy={copy_result.copy_byte_length}",
            )
        
        if copy_result.copy_sha256 != source_sha256:
            return ValidationResult(
                relative_path=entry.relativePath,
                is_valid=False,
                failure_reason=f"Copy SHA-256 mismatch: source={source_sha256}, copy={copy_result.copy_sha256}",
            )
        
        # All checks passed
        return ValidationResult(
            relative_path=entry.relativePath,
            is_valid=True,
        )
    
    def _write_acceptance(self, acceptance: MigrationAcceptance) -> None:
        """
        Write the acceptance record to disk.
        
        Args:
            acceptance: The acceptance record to persist
        """
        self._acceptance_store.save(acceptance)
