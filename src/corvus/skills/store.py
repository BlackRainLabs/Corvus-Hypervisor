"""Content-addressed skill package store on the control plane."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from corvus.skills.parse import ParsedSkill, parse_skill_md
from corvus.skills.validate import validate_skill_tree


def default_skill_store_dir() -> Path:
    override = os.environ.get("CORVUS_SKILL_STORE_DIR")
    if override:
        return Path(override)
    db = os.environ.get("CORVUS_DB_PATH", "corvus.db")
    return Path(db).resolve().parent / "skill-store"


class SkillStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_skill_store_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def package_dir(self, name: str, version: str, content_hash: str) -> Path:
        safe_hash = content_hash.replace(":", "_")[:128]
        return self.root / name / version / safe_hash

    def write_tree(self, src: Path, *, name: str, version: str) -> tuple[str, Path, ParsedSkill]:
        files = validate_skill_tree(src)
        digest = hashlib.sha256()
        for rel in files:
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update((src / rel).read_bytes())
        content_hash = digest.hexdigest()
        dest = self.package_dir(name, version, content_hash)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for rel in files:
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, target)
        parsed = parse_skill_md(
            (dest / "SKILL.md").read_text(encoding="utf-8"),
            expect_dir_name=name,
        )
        meta = {
            "name": name,
            "version": version,
            "content_hash": content_hash,
            "files": files,
        }
        (dest / ".corvus-skill.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        return content_hash, dest, parsed

    def read_skill_md(self, store_path: str | Path) -> ParsedSkill:
        root = Path(store_path)
        text = (root / "SKILL.md").read_text(encoding="utf-8")
        return parse_skill_md(text)

    def ensure_builtin_base_runtime(self) -> Path:
        """Materialize builtin base-runtime package for bake/read."""
        name, version = "base-runtime", "1.0"
        content_hash = "builtin:base-runtime:1.0"
        dest = self.package_dir(name, version, content_hash)
        skill_md = dest / "SKILL.md"
        if skill_md.is_file():
            return dest
        dest.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(
            "---\n"
            "name: base-runtime\n"
            "description: Builtin Corvus runtime skill for ping and instruction stub.\n"
            "metadata:\n"
            '  version: "1.0"\n'
            "---\n\n"
            "# Base runtime\n\n"
            "Use this skill to confirm skill mediation works. "
            "Call `skill_read` with skill=`base-runtime` to load these instructions. "
            "Scripts are disabled for this builtin.\n",
            encoding="utf-8",
        )
        (dest / ".corvus-skill.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "version": version,
                    "content_hash": content_hash,
                    "files": ["SKILL.md"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return dest
