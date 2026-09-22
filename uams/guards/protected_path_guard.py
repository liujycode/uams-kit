r"""
ProtectedPathGuard - Guards protected source paths from write operations.

This module implements Requirement 1.1, 1.3: Protects paths beneath
the protected source root (e.g., ~\.claude\...) from any modifying
operations.

Validates: Requirements 1.1, 1.3
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from enum import Enum


class OperationType(Enum):
    """Enumeration of operation types that can be guarded against."""
    MOVE = "move"
    DELETE = "delete"
    OVERWRITE = "overwrite"
    RENAME = "rename"
    METADATA_CHANGE = "metadata_change"
    CONTENT_WRITE = "content_write"
    DIRECT_BYPASS = "direct_bypass"


class GuardDecision:
    """Result of a guard check operation."""
    
    def __init__(self, allowed: bool, reason: Optional[str] = None, 
                 audit_event_id: Optional[str] = None):
        self.allowed = allowed
        self.reason = reason
        self.audit_event_id = audit_event_id
    
    def __bool__(self) -> bool:
        return self.allowed
    
    def __repr__(self) -> str:
        return f"GuardDecision(allowed={self.allowed}, reason={self.reason!r})"


class ProtectedPathGuard:
    r"""
    Guards protected source paths from write operations.
    
    Any path beneath the protected root (e.g., ~\.claude\...) is
    considered a protection source. The guard rejects any operation with
    move, delete, overwrite, rename, metadata-change, content-write, or
    direct-bypass intent on protected paths.
    
    Requirements validated:
    - 1.1: Classify every path beneath protected root as protection source
    - 1.3: Reject modifying operations and record rejection in log
    - 8.3: Reject bypass attempts to write directly beneath protected source
    
    Example:
        guard = ProtectedPathGuard(protected_root=str(Path.home() / ".claude"))
        decision = guard.check_operation(r"~\.claude\memory.json",
                                         OperationType.DELETE)
        if not decision.allowed:
            print(f"Rejected: {decision.reason}")
    """
    
    # Operations that modify the source (not allowed on protected paths)
    MODIFYING_OPERATIONS = {
        OperationType.MOVE,
        OperationType.DELETE,
        OperationType.OVERWRITE,
        OperationType.RENAME,
        OperationType.METADATA_CHANGE,
        OperationType.CONTENT_WRITE,
        OperationType.DIRECT_BYPASS,
    }
    
    def __init__(self, protected_root: str, audit_log_path: Optional[str] = None):
        r"""
        Initialize the protected path guard.
        
        Args:
            protected_root: The root path to protect (e.g., ~\.claude)
            audit_log_path: Path to the audit log file. If None, uses default.
        """
        self._protected_root = Path(protected_root).resolve()
        self._audit_log_path = audit_log_path
        self._rejection_counter = 0
    
    @property
    def protected_root(self) -> Path:
        """Return the protected root path."""
        return self._protected_root
    
    def is_protected_path(self, path: str) -> bool:
        r"""
        Check if a path is beneath the protected root.
        
        This implements Requirement 1.1: Classify every path beneath
        the protected root (e.g., ~\.claude\...) as a protection source.
        
        Args:
            path: The path to check (can be relative or absolute)
            
        Returns:
            True if the path is beneath the protected root, False otherwise
        """
        try:
            resolved_path = Path(path).resolve()
            # Check if the resolved path is a subpath of the protected root
            # Use string comparison after normalization to handle case-insensitivity on Windows
            protected_str = str(self._protected_root).lower()
            resolved_str = str(resolved_path).lower()
            return resolved_str.startswith(protected_str + os.sep) or resolved_str == protected_str
        except (OSError, ValueError):
            # Invalid path - not protected
            return False
    
    def check_operation(self, path: str, operation: OperationType,
                       ai_identity: Optional[str] = None) -> GuardDecision:
        """
        Check if an operation on a path is allowed.
        
        This implements Requirement 1.3: Reject modifying operations on
        protected paths before source access and record rejection.
        
        Args:
            path: The target path for the operation
            operation: The type of operation being performed
            ai_identity: Optional AI identity for audit logging
            
        Returns:
            GuardDecision indicating if the operation is allowed
        """
        if not self.is_protected_path(path):
            # Path is not protected, operation is allowed
            return GuardDecision(allowed=True)
        
        if operation not in self.MODIFYING_OPERATIONS:
            # Read-only operation on protected path is allowed
            return GuardDecision(allowed=True)
        
        # Modifying operation on protected path - reject
        audit_event_id = self._record_rejection(path, operation, ai_identity)
        return GuardDecision(
            allowed=False,
            reason=f"Operation '{operation.value}' is not allowed on protected path: {path}",
            audit_event_id=audit_event_id
        )
    
    def validate_path_for_read(self, path: str) -> GuardDecision:
        """
        Validate that a path can be read.
        
        For protected paths, only read operations are allowed.
        
        Args:
            path: The path to validate for reading
            
        Returns:
            GuardDecision indicating if reading is allowed
        """
        if not self.is_protected_path(path):
            return GuardDecision(allowed=True)
        
        # Reading from protected path is allowed
        return GuardDecision(allowed=True, reason="Protected path - read allowed")
    
    def validate_path_for_write(self, path: str, 
                                ai_identity: Optional[str] = None) -> GuardDecision:
        """
        Validate that a path can be written to.
        
        This implements Requirement 1.3: Reject write operations on protected paths.
        
        Args:
            path: The path to validate for writing
            ai_identity: Optional AI identity for audit logging
            
        Returns:
            GuardDecision indicating if writing is allowed
        """
        return self.check_operation(path, OperationType.CONTENT_WRITE, ai_identity)
    
    def validate_no_bypass(self, path: str, 
                           ai_identity: Optional[str] = None) -> GuardDecision:
        """
        Validate that an operation is not bypassing UAMS to directly access protected source.
        
        This implements Requirement 8.3: Reject bypass attempts.
        
        Args:
            path: The target path
            ai_identity: Optional AI identity for audit logging
            
        Returns:
            GuardDecision indicating if the operation is allowed
        """
        if self.is_protected_path(path):
            audit_event_id = self._record_rejection(path, OperationType.DIRECT_BYPASS, ai_identity)
            return GuardDecision(
                allowed=False,
                reason=f"Direct bypass of protected path is not allowed: {path}",
                audit_event_id=audit_event_id
            )
        return GuardDecision(allowed=True)
    
    def _record_rejection(self, path: str, operation: OperationType,
                         ai_identity: Optional[str]) -> str:
        """
        Record a rejection in the audit log.
        
        This implements Requirement 1.3: Record rejection in migration log.
        
        Args:
            path: The path that was rejected
            operation: The operation type that was rejected
            ai_identity: Optional AI identity
            
        Returns:
            The audit event ID
        """
        self._rejection_counter += 1
        event_id = f"rejection-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._rejection_counter:06d}"
        
        audit_entry = {
            "eventId": event_id,
            "timestamp": datetime.now().isoformat(),
            "path": str(path),
            "operation": operation.value,
            "aiIdentity": ai_identity,
            "rejectionReason": f"Protected path - {operation.value} not allowed"
        }
        
        if self._audit_log_path:
            self._append_to_audit_log(audit_entry)
        
        return event_id
    
    def _append_to_audit_log(self, entry: dict) -> None:
        """Append an entry to the audit log file."""
        try:
            log_path = Path(self._audit_log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except (OSError, IOError) as e:
            # Log the error but don't fail the operation
            print(f"Warning: Could not write to audit log: {e}")
