r"""
LegacySourceAdapter - Read-only adapter for legacy Claude memory.

This module implements Requirement 1.2, 8.3: Provides read-only access
to paths beneath the protected source root (e.g., ~\.claude\...) with enumerate, read, and
digest operations only.

Validates: Requirements 1.2, 8.3
"""

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, List, BinaryIO

from ..guards import ProtectedPathGuard


@dataclass
class SourceFileInfo:
    """Information about a source file discovered by the adapter."""
    relative_path: str           # Normalized relative path from source root
    absolute_path: str           # Absolute path to the file
    byte_length: int             # File size in bytes
    sha256: str                  # SHA-256 content digest
    discovered_at: str           # ISO 8601 timestamp of discovery
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "relativePath": self.relative_path,
            "absolutePath": self.absolute_path,
            "byteLength": self.byte_length,
            "sha256": self.sha256,
            "discoveredAt": self.discovered_at
        }


class LegacySourceAdapter:
    r"""
    Read-only adapter for accessing legacy Claude memory.
    
    This adapter provides ONLY enumerate, read, and digest operations.
    It explicitly does NOT provide write, move, delete, rename, or 
    metadata modification methods to enforce read-only access to the
    protected source.
    
    Requirements validated:
    - 1.2: Use read-only source operations for import and validation
    - 8.3: Reject direct write attempts to protected source
    
    Example:
        adapter = LegacySourceAdapter()
        for file_info in adapter.enumerate_files():
            content = adapter.read_file(file_info.relative_path)
            digest = adapter.compute_digest(content)
            print(f"{file_info.relative_path}: {digest}")
    """
    
    def __init__(self, source_root: str, audit_log_path: Optional[str] = None):
        r"""
        Initialize the legacy source adapter.
        
        Args:
            source_root: The root path of the legacy source
                         (e.g., ~\.claude)
            audit_log_path: Optional path for audit logging
        """
        self._source_root = Path(source_root).resolve()
        self._guard = ProtectedPathGuard(source_root, audit_log_path)
    
    @property
    def source_root(self) -> Path:
        """Return the source root path."""
        return self._source_root
    
    @property
    def guard(self) -> ProtectedPathGuard:
        """Return the associated protected path guard."""
        return self._guard
    
    def enumerate_files(self, recursive: bool = True) -> Iterator[SourceFileInfo]:
        """
        Enumerate all files beneath the source root.
        
        This is a read-only discovery operation that lists all importable
        files with their metadata.
        
        Args:
            recursive: If True, enumerate recursively; if False, only top level
            
        Yields:
            SourceFileInfo for each discovered file
        """
        discovered_at = datetime.now().isoformat()
        
        if recursive:
            for root, _, files in os.walk(self._source_root):
                for filename in files:
                    absolute_path = Path(root) / filename
                    # Reparse points can appear below the source root while
                    # resolving outside it. They are not importable source files.
                    if not self._is_importable_path(absolute_path):
                        continue
                    relative_path = str(absolute_path.relative_to(self._source_root))
                    
                    # Normalize path separators for cross-platform consistency
                    relative_path = relative_path.replace(os.sep, '/')
                    
                    yield self._create_file_info(absolute_path, relative_path, discovered_at)
        else:
            for item in self._source_root.iterdir():
                if item.is_file():
                    relative_path = item.name
                    yield self._create_file_info(item, relative_path, discovered_at)
    
    def enumerate_to_list(self, recursive: bool = True) -> List[SourceFileInfo]:
        """
        Enumerate all files and return as a list.
        
        Convenience method for non-streaming use cases.
        
        Args:
            recursive: If True, enumerate recursively
            
        Returns:
            List of SourceFileInfo for all discovered files
        """
        return list(self.enumerate_files(recursive))
    
    def read_file(self, relative_path: str) -> bytes:
        """
        Read the content of a file from the source.
        
        This is a read-only operation. The content is read but never modified.
        
        Args:
            relative_path: Relative path from the source root
            
        Returns:
            The file content as bytes
            
        Raises:
            FileNotFoundError: If the file does not exist
            PermissionError: If the file cannot be read
        """
        absolute_path = self._resolve_relative_path(relative_path)
        
        # Verify this is a protected path (source should always be protected)
        if not self._guard.is_protected_path(str(absolute_path)):
            raise ValueError(f"Path is not within protected source: {relative_path}")
        
        with open(absolute_path, 'rb') as f:
            return f.read()
    
    def read_file_text(self, relative_path: str, encoding: str = 'utf-8') -> str:
        """
        Read the content of a text file from the source.
        
        Convenience method for text files.
        
        Args:
            relative_path: Relative path from the source root
            encoding: Text encoding (default: utf-8)
            
        Returns:
            The file content as string
        """
        content = self.read_file(relative_path)
        return content.decode(encoding)
    
    def open_file(self, relative_path: str) -> BinaryIO:
        """
        Open a file for reading.
        
        Returns a file handle for streaming read operations.
        The caller is responsible for closing the handle.
        
        Args:
            relative_path: Relative path from the source root
            
        Returns:
            Binary file handle for reading
        """
        absolute_path = self._resolve_relative_path(relative_path)
        
        if not self._guard.is_protected_path(str(absolute_path)):
            raise ValueError(f"Path is not within protected source: {relative_path}")
        
        return open(absolute_path, 'rb')
    
    def compute_digest(self, content: bytes) -> str:
        """
        Compute SHA-256 digest of content.
        
        Args:
            content: The bytes content to digest
            
        Returns:
            Hexadecimal SHA-256 digest string
        """
        return hashlib.sha256(content).hexdigest()
    
    def compute_file_digest(self, relative_path: str) -> str:
        """
        Compute SHA-256 digest of a file.
        
        More memory-efficient than reading entire file for large files.
        
        Args:
            relative_path: Relative path from the source root
            
        Returns:
            Hexadecimal SHA-256 digest string
        """
        absolute_path = self._resolve_relative_path(relative_path)
        
        sha256_hash = hashlib.sha256()
        with open(absolute_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def file_exists(self, relative_path: str) -> bool:
        """
        Check if a file exists at the given relative path.
        
        Args:
            relative_path: Relative path from the source root
            
        Returns:
            True if the file exists, False otherwise
        """
        absolute_path = self._resolve_relative_path(relative_path)
        return absolute_path.exists() and absolute_path.is_file()
    
    def get_file_info(self, relative_path: str) -> SourceFileInfo:
        """
        Get file info for a specific file.
        
        Args:
            relative_path: Relative path from the source root
            
        Returns:
            SourceFileInfo for the file
            
        Raises:
            FileNotFoundError: If the file does not exist
        """
        absolute_path = self._resolve_relative_path(relative_path)
        
        if not absolute_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        
        # Normalize path separators
        normalized_relative = relative_path.replace(os.sep, '/')
        
        return self._create_file_info(
            absolute_path, 
            normalized_relative, 
            datetime.now().isoformat()
        )
    
    def _is_importable_path(self, path: Path) -> bool:
        """Return whether resolving a source entry remains within source_root."""
        try:
            path.resolve().relative_to(self._source_root)
        except ValueError:
            return False
        return True

    def _resolve_relative_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute path within the source root."""
        # Normalize path separators
        normalized = relative_path.replace('/', os.sep).replace('\\', os.sep)
        return self._source_root / normalized
    
    def _create_file_info(self, absolute_path: Path, relative_path: str, 
                          discovered_at: str) -> SourceFileInfo:
        """Create a SourceFileInfo for a file."""
        stat = absolute_path.stat()
        
        # Compute SHA-256 digest
        sha256 = self.compute_file_digest(str(absolute_path))
        
        return SourceFileInfo(
            relative_path=relative_path,
            absolute_path=str(absolute_path),
            byte_length=stat.st_size,
            sha256=sha256,
            discovered_at=discovered_at
        )
