"""Phase 10 skill parse, install security, bake, and skill_read tool."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from corvus.server.catalog import DEFAULT_CATALOG
from corvus.skills.bake import bake_skills_into_launch_package
from corvus.skills.fetch import assert_source_allowed, fetch_and_extract
from corvus.skills.install import InstallRequest, install_skill
from corvus.skills.parse import parse_skill_md
from corvus.skills.runner import SkillToolError, run_skill_read
from corvus.skills.validate import validate_skill_tree
from corvus.tools.runner import run_tool


def _make_skill_zip(
    tmp_path: Path, *, name: str = "demo-skill", with_script: bool = False
) -> tuple[Path, str]:
    root = tmp_path / name
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo skill for Corvus tests.\n"
        f'metadata:\n  version: "1.0.0"\n---\n\n# Demo\n\nHello.\n',
        encoding="utf-8",
    )
    if with_script:
        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "hello.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(tmp_path).as_posix())
    data = buf.getvalue()
    zpath = tmp_path / f"{name}.zip"
    zpath.write_bytes(data)
    return zpath, hashlib.sha256(data).hexdigest()


def test_parse_skill_md_ok():
    parsed = parse_skill_md(
        "---\nname: demo-skill\ndescription: Does a thing.\n---\n\nBody\n"
    )
    assert parsed.name == "demo-skill"
    assert "Body" in parsed.body


def test_parse_skill_md_rejects_bad_name():
    with pytest.raises(ValueError):
        parse_skill_md("---\nname: Bad_Name\ndescription: x\n---\n\n")


def test_validate_rejects_symlink(tmp_path: Path):
    root = tmp_path / "demo-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: x\n---\n\n", encoding="utf-8"
    )
    target = root / "evil"
    target.write_text("x", encoding="utf-8")
    link = root / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        validate_skill_tree(root)


def test_source_allowlist_denies_by_default(monkeypatch):
    monkeypatch.delenv("CORVUS_SKILL_SOURCE_ALLOWLIST", raising=False)
    with pytest.raises(ValueError, match="denied"):
        assert_source_allowed("https://evil.example/skill.zip")


def test_install_dry_run_and_commit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    zpath, digest = _make_skill_zip(tmp_path)
    source = f"file:{zpath}"
    dry = install_skill(
        InstallRequest(source=source, pin="v1.0.0", sha256=digest, dry_run=True)
    )
    assert dry.dry_run is True
    assert dry.name == "demo-skill"
    assert dry.files
    committed = install_skill(
        InstallRequest(source=source, pin="v1.0.0", sha256=digest, dry_run=False)
    )
    assert committed.store_path
    assert Path(committed.store_path, "SKILL.md").is_file()
    assert committed.entry["format"] == "agentskills"


def test_install_rejects_sha_mismatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    zpath, _ = _make_skill_zip(tmp_path)
    with pytest.raises(ValueError, match="sha256"):
        install_skill(
            InstallRequest(
                source=f"file:{zpath}",
                pin="v1",
                sha256="0" * 64,
                dry_run=True,
            )
        )


def test_install_rejects_latest_pin(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    zpath, digest = _make_skill_zip(tmp_path)
    with pytest.raises(ValueError, match="latest"):
        fetch_and_extract(
            f"file:{zpath}", pin="latest", sha256=digest, dest=tmp_path / "x"
        )


def test_skill_read_builtin(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    out = run_skill_read({"skill": "base-runtime"})
    assert out["skill"] == "base-runtime"
    assert "Base runtime" in out["content"] or "base-runtime" in out["content"]


def test_skill_read_tool_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    result = run_tool("skill_read", {"skill": "base-runtime"})
    assert "content" in result


def test_skill_run_denied_without_allow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("CORVUS_SKILL_ALLOW_SCRIPTS_base-runtime", raising=False)
    with pytest.raises(SkillToolError, match="disabled"):
        run_tool(
            "skill_run",
            {"skill": "base-runtime", "script": "scripts/x.sh", "allow_scripts": False},
        )


def test_bake_skills_into_launch_package(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    launch = tmp_path / "launch"
    launch.mkdir()
    env = bake_skills_into_launch_package(
        launch,
        skill_names=["base-runtime"],
        catalog=DEFAULT_CATALOG,
    )
    assert (launch / "skills" / "base-runtime" / "SKILL.md").is_file()
    assert (launch / "skills" / "index.json").is_file()
    assert env["CORVUS_SKILLS_DIR"].endswith("skills")


@pytest.mark.asyncio
async def test_catalog_skills_install_api(app_ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    zpath, digest = _make_skill_zip(tmp_path)
    from httpx import ASGITransport, AsyncClient

    from corvus.management.api import create_app

    app = create_app(app_ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-API-Key": "test-key"}
        dry = await client.post(
            "/v1/catalog/skills/install",
            headers=headers,
            json={
                "source": f"file:{zpath}",
                "pin": "v1.0.0",
                "sha256": digest,
                "dry_run": True,
            },
        )
        assert dry.status_code == 200, dry.text
        body = dry.json()
        assert body["dry_run"] is True
        assert body["name"] == "demo-skill"

        commit = await client.post(
            "/v1/catalog/skills/install",
            headers=headers,
            json={
                "source": f"file:{zpath}",
                "pin": "v1.0.0",
                "sha256": digest,
                "dry_run": False,
            },
        )
        assert commit.status_code == 200, commit.text
        skills = await client.get("/v1/catalog/skills", headers=headers)
        names = {s["name"] for s in skills.json()["skills"]}
        assert "demo-skill" in names


@pytest.mark.asyncio
async def test_engine1_skill_read_via_server(app_ctx, tmp_path, full_manifest_agent, monkeypatch):
    monkeypatch.setenv("CORVUS_SKILL_STORE_DIR", str(tmp_path / "store"))
    import asyncio

    from test_tool_integration import _register_turn, _start_node_stack

    from corvus.protocol import EngineId
    from corvus.runtime.ipc_client import NodeIpcClient
    from corvus.runtime.tool_client import (
        build_tool_call,
        build_tool_result,
        parse_tool_call_response,
        parse_tool_result_ack,
    )
    from corvus.server.bootstrap import FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID

    gateway, node, node_task, ipc_path, config = await _start_node_stack(app_ctx, tmp_path)
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE1,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(ipc_path, config.vm_id)
        tool_call = build_tool_call(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            tool_name="skill_read",
            arguments={"skill": "base-runtime"},
        )
        call_ack = await client.submit_and_wait(tool_call, timeout=30.0)
        approval = parse_tool_call_response(call_ack)
        assert approval.ok is True
        assert approval.approved is True

        out = run_tool("skill_read", {"skill": "base-runtime"})
        tool_result = build_tool_result(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            tool_name="skill_read",
            request_correlation_id=tool_call.correlation_id,
            success=True,
            result=out,
            duration_ms=1,
        )
        result_ack = await client.submit_and_wait(tool_result, timeout=30.0)
        assert parse_tool_result_ack(result_ack).ok
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()


def test_skill_gate_requires_manifest_skill():
    from corvus.tools.service import ToolGatewayService

    err = ToolGatewayService._skill_gate(
        {"skills": []}, "skill_read", {"skill": "base-runtime"}
    )
    assert err is not None
    assert err[0] == "SKILL_NOT_ALLOWED"
    ok = ToolGatewayService._skill_gate(
        {"skills": ["base-runtime"]}, "skill_read", {"skill": "base-runtime"}
    )
    assert ok is None
