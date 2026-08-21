"""Bake approved skill packages into a VM launch package directory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from corvus.server.catalog import CapabilityCatalog, SkillCatalogEntry
from corvus.skills.store import SkillStore


def bake_skills_into_launch_package(
    launch_package_dir: Path,
    *,
    skill_names: list[str],
    catalog: CapabilityCatalog,
    store: SkillStore | None = None,
) -> dict[str, str]:
    """Copy selected skills under launch_package_dir/skills/<name>.

    Returns env overrides (CORVUS_SKILLS_DIR and per-skill allow_scripts flags).
    """
    store = store or SkillStore()
    skills_dir = launch_package_dir / "skills"
    if skills_dir.exists():
        shutil.rmtree(skills_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    env: dict[str, str] = {"CORVUS_SKILLS_DIR": str(skills_dir)}

    for name in skill_names:
        entry = catalog.skills.get(name)
        if entry is None:
            continue
        src = _resolve_source(entry, store)
        dest = skills_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        index.append(
            {
                "name": name,
                "version": entry.version,
                "content_hash": entry.content_hash,
                "allow_scripts": entry.allow_scripts,
                "format": entry.format,
            }
        )
        if entry.allow_scripts:
            env[f"CORVUS_SKILL_ALLOW_SCRIPTS_{name}"] = "1"

    (skills_dir / "index.json").write_text(
        json.dumps({"skills": index}, indent=2) + "\n", encoding="utf-8"
    )
    return env


def _resolve_source(entry: SkillCatalogEntry, store: SkillStore) -> Path:
    if entry.store_path and Path(entry.store_path).is_dir():
        return Path(entry.store_path)
    if entry.format == "builtin" and entry.name == "base-runtime":
        return store.ensure_builtin_base_runtime()
    if entry.content_hash:
        candidate = store.package_dir(entry.name, entry.version, entry.content_hash)
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"cannot bake skill {entry.name}: package missing")
