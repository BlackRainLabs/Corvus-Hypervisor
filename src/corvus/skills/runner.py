"""Engine 1 skill_read / skill_run tool implementations."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from corvus.skills.store import SkillStore, default_skill_store_dir


class SkillToolError(RuntimeError):
    pass


def _resolve_skill_root(skill_name: str, store_path: str | None = None) -> Path:
    """Resolve skill package directory from env bake path or control-plane store."""
    bake_root = os.environ.get("CORVUS_SKILLS_DIR")
    if bake_root:
        candidate = Path(bake_root) / skill_name
        if (candidate / "SKILL.md").is_file():
            return candidate
    if store_path:
        p = Path(store_path)
        if (p / "SKILL.md").is_file():
            return p
    # Builtin materialization
    store = SkillStore(default_skill_store_dir())
    if skill_name == "base-runtime":
        return store.ensure_builtin_base_runtime()
    # Search store tree for skill name
    root = store.root / skill_name
    if root.is_dir():
        for version_dir in sorted(root.iterdir(), reverse=True):
            if not version_dir.is_dir():
                continue
            for hash_dir in sorted(version_dir.iterdir(), reverse=True):
                if (hash_dir / "SKILL.md").is_file():
                    return hash_dir
    raise SkillToolError(f"skill package not found: {skill_name}")


def run_skill_read(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    skill_name = str(args.get("skill") or args.get("name") or "").strip()
    if not skill_name:
        raise SkillToolError("skill_read requires skill=")
    root = _resolve_skill_root(skill_name, store_path=args.get("store_path"))
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    return {
        "skill": skill_name,
        "path": str(root / "SKILL.md"),
        "content": text,
        "bytes": len(text.encode("utf-8")),
    }


def run_skill_run(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    skill_name = str(args.get("skill") or args.get("name") or "").strip()
    script = str(args.get("script") or "").strip()
    if not skill_name or not script:
        raise SkillToolError("skill_run requires skill= and script=")
    if Path(script).is_absolute() or ".." in Path(script).parts:
        raise SkillToolError("script path must be relative without ..")
    if not script.startswith("scripts/"):
        raise SkillToolError("script must live under scripts/")
    allow = args.get("allow_scripts")
    if allow is False or allow == "false":
        raise SkillToolError("scripts disabled for this skill")
    # Default deny unless explicitly true
    if allow is not True and allow != "true":
        # Check env from bake metadata
        meta_allow = os.environ.get(f"CORVUS_SKILL_ALLOW_SCRIPTS_{skill_name}", "")
        if meta_allow.lower() not in {"1", "true", "yes"}:
            raise SkillToolError("scripts disabled for this skill (allow_scripts=false)")

    root = _resolve_skill_root(skill_name, store_path=args.get("store_path"))
    script_path = (root / script).resolve()
    if not str(script_path).startswith(str(root.resolve())):
        raise SkillToolError("script path escapes skill package")
    if not script_path.is_file():
        raise SkillToolError(f"script not found: {script}")

    proc = subprocess.run(
        ["bash", str(script_path)],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=float(args.get("timeout_seconds") or 30),
        check=False,
    )
    return {
        "skill": skill_name,
        "script": script,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-65536:],
        "stderr": proc.stderr[-65536:],
    }


def run(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if tool_name == "skill_read":
        return run_skill_read(arguments)
    if tool_name == "skill_run":
        return run_skill_run(arguments)
    raise SkillToolError(f"unknown skill tool: {tool_name}")
