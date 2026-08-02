"""Host-side VM memory turn wait helper tests."""

from uuid import uuid4

import pytest

from corvus.vm.memory_wait import find_engine4_turn_record, wait_for_engine4_turn_record


@pytest.mark.asyncio
async def test_find_engine4_turn_record(app_ctx):
    turn_key = f"turn-{uuid4()}"
    await app_ctx.db.create_memory_record(
        agent_id="test-agent-01",
        namespace="private",
        key=turn_key,
        content="Engine4 memory snapshot for test",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    found = find_engine4_turn_record(app_ctx.config.db_path)
    assert found is not None
    assert found["key"] == turn_key


def test_wait_for_engine4_turn_record_times_out(tmp_path):
    db_path = tmp_path / "empty.db"
    with pytest.raises(TimeoutError):
        wait_for_engine4_turn_record(db_path, timeout=0.2, poll_interval=0.05)
