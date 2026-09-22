"""
Universal AI Memory System (UAMS)

A tool-independent memory storage and access system for Claude, Kiro, Codex, K3, and future AIs.
"""

import os
from pathlib import Path

__version__ = "0.2.0"


def _detect_uams_root() -> str:
    """Resolve the UAMS root automatically.

    Priority:
      1. ``UAMS_ROOT`` environment variable
      2. ``~/.ai-memory/uams-root`` (default layout)
    """
    env = os.environ.get("UAMS_ROOT")
    if env:
        return str(Path(env).expanduser())
    return str(Path.home() / "ai-memory" / "uams-root")


def _detect_protected_source_root() -> str:
    """Resolve the protected (legacy) source root automatically.

    Priority:
      1. ``UAMS_PROTECTED_SOURCE_ROOT`` environment variable
      2. ``~/.claude`` (default layout)
    """
    env = os.environ.get("UAMS_PROTECTED_SOURCE_ROOT")
    if env:
        return str(Path(env).expanduser())
    return str(Path.home() / ".claude")


# Core constants (auto-detected; override via environment variables)
PROTECTED_SOURCE_ROOT = _detect_protected_source_root()
UAMS_ROOT = _detect_uams_root()

# Supported AI identities
SUPPORTED_AI_IDENTITIES = ["claude", "kiro", "codex", "k3", "trae", "dsh", "workbuddy"]
