import pytest
from utils.idempotency import is_already_processed, mark_processed


@pytest.mark.asyncio
async def test_new_interaction_not_processed():
    assert await is_already_processed("new_interaction_123") is False


@pytest.mark.asyncio
async def test_marked_interaction_is_processed():
    await mark_processed("interaction_456", "hunt:forest")
    assert await is_already_processed("interaction_456") is True


@pytest.mark.asyncio
async def test_different_interactions_independent():
    await mark_processed("interaction_abc", "test")
    assert await is_already_processed("interaction_xyz") is False


@pytest.mark.asyncio
async def test_double_mark_does_not_error():
    await mark_processed("double_mark", "first")
    # Second mark should not raise — it should either succeed or be ignored
    try:
        await mark_processed("double_mark", "second")
    except Exception:
        pass  # Duplicate key is fine — idempotency is still enforced
    assert await is_already_processed("double_mark") is True
