"""
Path Normalization Utilities for UAMS

This module provides path and title normalization functions that ensure
deterministic and consistent representations across the system.

Validates: Requirements 5.1, 6.2
"""

import os
import re
import hashlib
import unicodedata
from pathlib import Path
from typing import Union


def normalize_path(path: Union[str, Path]) -> str:
    """
    Normalize a path to its canonical absolute representation.
    
    This function ensures that equivalent path representations produce
    identical normalized results. It handles:
    - Relative paths (converted to absolute)
    - Path separators (normalized to forward slashes)
    - Case sensitivity (preserved, but symlinks resolved)
    - Redundant separators and dot segments
    - Unicode normalization (NFC form)
    
    Args:
        path: A file path as string or Path object
        
    Returns:
        Normalized absolute path as a string with forward slashes
        
    Example:
        >>> normalize_path("C:\\Users\\demo\\some\\path")
        'C:/Users/demo/some/path'
        >>> normalize_path("relative/path")  # doctest: +SKIP
        '<cwd resolved>/relative/path'
    """
    # Convert to Path object
    p = Path(path) if not isinstance(path, Path) else path
    
    # Resolve to absolute path (handles relative paths)
    # Use resolve() to handle symlinks and redundant segments
    try:
        resolved = p.resolve()
    except (OSError, ValueError):
        # If resolution fails, fall back to absolute path
        resolved = p.absolute()
    
    # Convert to string
    normalized = str(resolved)
    
    # Normalize path separators to forward slashes for consistency
    normalized = normalized.replace(os.sep, '/')
    
    # Unicode NFC normalization for consistent string comparison
    normalized = unicodedata.normalize('NFC', normalized)
    
    # Remove trailing slash (except for root)
    if len(normalized) > 1 and normalized.endswith('/'):
        normalized = normalized[:-1]
    
    return normalized


def normalize_title_slug(title: str, max_length: int = 100) -> str:
    """
    Normalize a title to a deterministic slug for filename generation.
    
    This function produces a filesystem-safe, deterministic slug from
    a title string. The slug is suitable for use in the filename format:
    `<entry-id>--<normalized-title-slug>.md`
    
    The transformation is:
    1. Unicode NFC normalization
    2. Convert to lowercase
    3. Replace non-alphanumeric characters with hyphens
    4. Collapse multiple hyphens
    5. Strip leading/trailing hyphens
    6. Truncate to max_length
    
    Args:
        title: The title string to normalize
        max_length: Maximum length of the resulting slug (default 100)
        
    Returns:
        Normalized slug string suitable for filenames
        
    Example:
        >>> normalize_title_slug("My Memory Entry!")
        'my-memory-entry'
        >>> normalize_title_slug("  Multiple   Spaces  ")
        'multiple-spaces'
    """
    if not title:
        return "untitled"
    
    # Unicode NFC normalization
    slug = unicodedata.normalize('NFC', title)
    
    # Convert to lowercase
    slug = slug.lower()
    
    # Replace any character that's not alphanumeric, hyphen, or underscore
    # with a hyphen
    slug = re.sub(r'[^a-z0-9_-]', '-', slug)
    
    # Collapse multiple consecutive hyphens to single hyphen
    slug = re.sub(r'-+', '-', slug)
    
    # Strip leading and trailing hyphens
    slug = slug.strip('-_')
    
    # Handle empty result
    if not slug:
        return "untitled"
    
    # Truncate to max_length while preserving word boundaries
    if len(slug) > max_length:
        slug = slug[:max_length]
        # Remove trailing partial word
        if '-' in slug:
            slug = slug.rsplit('-', 1)[0]
        # Remove trailing hyphen after truncation
        slug = slug.rstrip('-')
    
    return slug or "untitled"


def compute_content_digest(content: str) -> str:
    """
    Compute SHA-256 content digest for a string.
    
    The content is normalized (Unicode NFC) before hashing to ensure
    equivalent content produces identical digests.
    
    Args:
        content: The content string to hash
        
    Returns:
        Hexadecimal SHA-256 digest string
        
    Example:
        >>> compute_content_digest("Hello, World!")
        'dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f'
    """
    # Unicode NFC normalization for consistent hashing
    normalized = unicodedata.normalize('NFC', content)
    
    # Compute SHA-256 hash
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    return digest


def generate_entry_filename(entry_id: str, title: str) -> str:
    """
    Generate a deterministic filename for a memory entry.
    
    Format: `<entry-id>--<normalized-title-slug>.md`
    
    Args:
        entry_id: Unique entry identifier
        title: Entry title
        
    Returns:
        Deterministic filename string
    """
    slug = normalize_title_slug(title)
    return f"{entry_id}--{slug}.md"


def is_protected_path(path: Union[str, Path]) -> bool:
    """
    Check if a path is beneath the protected source root.
    
    Protected paths (paths beneath the protected source root, e.g.
    ``~/.claude``) must never be modified by UAMS operations.
    
    Args:
        path: Path to check
        
    Returns:
        True if the path is beneath the protected source root
    """
    from uams import PROTECTED_SOURCE_ROOT
    
    normalized_path = normalize_path(path)
    normalized_protected = normalize_path(PROTECTED_SOURCE_ROOT)
    
    return normalized_path.startswith(normalized_protected + '/') or \
           normalized_path == normalized_protected


def ensure_uams_path(path: Union[str, Path]) -> bool:
    """
    Check if a path is within the UAMS root directory.
    
    All UAMS outputs must be within the UAMS root.
    
    Args:
        path: Path to check
        
    Returns:
        True if the path is within UAMS root
    """
    from uams import UAMS_ROOT
    
    normalized_path = normalize_path(path)
    normalized_uams = normalize_path(UAMS_ROOT)
    
    return normalized_path.startswith(normalized_uams + '/') or \
           normalized_path == normalized_uams
