"""Orchestrate dry-run and commit skill installs."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from typing import Any

from corvus.server.catalog import SkillCatalogEntry
from corvus.skills.fetch import fetch_and_extract, staging_dir
from corvus.skills.parse import ParsedSkill, parse_skill_md
from corvus.skills.store import SkillStore
from corvus.skills.validate import validate_skill_tree


@dataclass
class InstallRequest:
    source: str
    pin: str
    sha256: str
    allow_scripts: bool = False
    dry_run: bool = False
    version: str | None = None


@dataclass
class InstallResult:
    dry_run: bool
    name: str
    version: str
    description: str
    content_hash: str
    files: list[str]
    allow_scripts: bool
    source_uri: str
    source_pin: str
    store_path: str | None = None
    entry: dict[str, Any] = field(default_factory=dict)
    parsed: ParsedSkill | None = None


def install_skill(req: InstallRequest, store: SkillStore | None = None) -> InstallResult:
    store = store or SkillStore()
    stage = staging_dir()
    try:
        skill_root = fetch_and_extract(
            req.source, pin=req.pin, sha256=req.sha256, dest=stage
        )
        files = validate_skill_tree(skill_root)
        parsed = parse_skill_md(
            (skill_root / "SKILL.md").read_text(encoding="utf-8"),
            expect_dir_name=parsed_name_hint(skill_root),
        )
        name = parsed.name
        # Enforce directory name matches skill name when nested
        if skill_root.name not in {name, "extract"} and (skill_root / "SKILL.md").is_file():
            if skill_root.name != name:
                raise ValueError(
                    f"directory name {skill_root.name!r} must match skill name {name!r}"
                )
        version = req.version or parsed.metadata.get("version") or req.pin

        if req.dry_run:
            digest = hashlib.sha256()
            for rel in files:
                digest.update(rel.encode("utf-8"))
                digest.update(b"\0")
                digest.update((skill_root / rel).read_bytes())
            return InstallResult(
                dry_run=True,
                name=name,
                version=version,
                description=parsed.description,
                content_hash=digest.hexdigest(),
                files=files,
                allow_scripts=req.allow_scripts,
                source_uri=req.source,
                source_pin=req.pin,
                parsed=parsed,
            )

        content_hash, dest, parsed = store.write_tree(
            skill_root, name=name, version=version
        )
        entry = SkillCatalogEntry(
            name=name,
            version=version,
            runtime_dependencies=[],
            exposed_tool_schemas=["skill_read", "skill_run"],
            package_source="agentskills",
            format="agentskills",
            content_hash=content_hash,
            source_uri=req.source,
            source_pin=req.pin,
            allow_scripts=req.allow_scripts,
            install_status="approved",
            description=parsed.description,
            store_path=str(dest),
        )
        return InstallResult(
            dry_run=False,
            name=name,
            version=version,
            description=parsed.description,
            content_hash=content_hash,
            files=files,
            allow_scripts=req.allow_scripts,
            source_uri=req.source,
            source_pin=req.pin,
            store_path=str(dest),
            entry=entry.model_dump(mode="json"),
            parsed=parsed,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def parsed_name_hint(skill_root) -> str | None:
    """If archive extracted to a single named folder, expect that name."""
    name = skill_root.name
    if name in {"extract", "tmp", "tmp0"}:
        return None
    return name
