"""Parse Agent Skills SKILL.md (YAML frontmatter + markdown body)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    body: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


def parse_skill_md(text: str, *, expect_dir_name: str | None = None) -> ParsedSkill:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter delimited by ---")
    meta_raw = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta_raw, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    name = str(meta_raw.get("name") or "").strip()
    description = str(meta_raw.get("description") or "").strip()
    if not name or len(name) > 64 or not _NAME_RE.match(name):
        raise ValueError("invalid skill name in frontmatter")
    if expect_dir_name is not None and name != expect_dir_name:
        raise ValueError(f"skill name {name!r} must match directory {expect_dir_name!r}")
    if not description or len(description) > 1024:
        raise ValueError("invalid skill description in frontmatter")
    allowed: list[str] = []
    at = meta_raw.get("allowed-tools") or meta_raw.get("allowed_tools")
    if isinstance(at, str) and at.strip():
        allowed = at.split()
    elif isinstance(at, list):
        allowed = [str(x) for x in at]
    metadata = {
        str(k): str(v)
        for k, v in (meta_raw.get("metadata") or {}).items()
        if isinstance(k, str)
    }
    return ParsedSkill(
        name=name,
        description=description,
        body=match.group(2).strip(),
        license=(str(meta_raw["license"]) if meta_raw.get("license") else None),
        compatibility=(
            str(meta_raw["compatibility"]) if meta_raw.get("compatibility") else None
        ),
        metadata=metadata,
        allowed_tools=allowed,
        raw_frontmatter={str(k): v for k, v in meta_raw.items()},
    )
