"""Validate skill package trees for path safety and size."""

from __future__ import annotations

import os
from pathlib import Path

MAX_PACKAGE_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_FILES = 200


def validate_skill_tree(root: Path) -> list[str]:
    """Return relative file paths under root. Raises ValueError on hostile trees."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("skill package root must be a directory")
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError("SKILL.md missing")
    files: list[str] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Reject symlinked directories
        for d in list(dirnames):
            p = Path(dirpath) / d
            if p.is_symlink():
                raise ValueError(f"symlink directories denied: {p.relative_to(root)}")
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                raise ValueError(f"symlink files denied: {path.relative_to(root)}")
            rel = path.relative_to(root).as_posix()
            if ".." in Path(rel).parts:
                raise ValueError(f"path traversal denied: {rel}")
            size = path.stat().st_size
            total += size
            if total > MAX_PACKAGE_BYTES:
                raise ValueError("skill package exceeds size limit")
            files.append(rel)
            if len(files) > MAX_FILES:
                raise ValueError("skill package has too many files")
    return sorted(files)
