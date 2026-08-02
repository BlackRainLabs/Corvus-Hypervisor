"""Tool gateway service unit tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST, TEST_MANIFEST_HASH
from corvus.server.db import Database
from corvus.tools.service import ToolGatewayService


def _tool_call(*, tool_name: str, agent_id: str = TEST_AGENT_ID) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE1, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="tool_call",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"tool_name": tool_name, "arguments": {"argv": ["echo", "hi"]}},
    )


@pytest.mark.asyncio
async def test_tool_call_approved_for_manifest_tool(app_ctx, full_manifest_agent):
    message = _tool_call(tool_name="terminal")
    result = await app_ctx.tools.handle_call(
        message, user_id="test-user", matched_rules=["allow-tool-call"]
    )
    assert result.success is True
    assert result.approved is True
    assert result.tool_name == "terminal"


@pytest.mark.asyncio
async def test_tool_call_rejected_when_not_in_manifest(app_ctx):
    message = _tool_call(tool_name="unknown-tool")
    result = await app_ctx.tools.handle_call(message, user_id="test-user", matched_rules=[])
    assert result.approved is False
    assert result.error_code == "TOOL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_tool_call_rejected_for_unknown_agent_tool(app_ctx, tmp_path):
    db = Database(tmp_path / "tool-gate.db")
    await db.connect()
    manifest = {
        **TEST_MANIFEST,
        "engines": {**TEST_MANIFEST["engines"], "engine1": {"tools": ["echo"]}},
    }
    await db.upsert_agent("gate-agent", TEST_MANIFEST_HASH, manifest)
    gateway = ToolGatewayService(db, app_ctx.audit)
    message = _tool_call(tool_name="terminal", agent_id="gate-agent")
    result = await gateway.handle_call(message, user_id="test-user", matched_rules=[])
    assert result.approved is False
    assert result.error_code == "TOOL_NOT_ALLOWED"
    await db.close()
