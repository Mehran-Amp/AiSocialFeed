import asyncio
import pytest

from bot.utils.logger import get_request_id, set_request_id

@pytest.mark.asyncio
async def test_request_id_isolation():
    # Initial value in a new context should be "-"
    assert get_request_id() == "-"

    async def worker(req_id: str) -> str:
        set_request_id(req_id)
        assert get_request_id() == req_id
        # Yield to let other tasks run, ensuring context variables stay isolated
        await asyncio.sleep(0.01)
        assert get_request_id() == req_id
        return get_request_id()

    # Run tasks concurrently
    task1 = asyncio.create_task(worker("id_1"))
    task2 = asyncio.create_task(worker("id_2"))
    task3 = asyncio.create_task(worker("id_3"))

    results = await asyncio.gather(task1, task2, task3)

    assert results == ["id_1", "id_2", "id_3"]
    # The parent context's ID should remain unmodified
    assert get_request_id() == "-"
